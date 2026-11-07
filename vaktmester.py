"""Broen – vaktmester. Kjøres på hver PC:  python vaktmester.py broen.json

Ser etter ny post til agentene på denne PC-en, vekker riktig agent headless
(claude -p / codex exec), og leverer svarene videre.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path

from felles import MENNESKE, TYPER, Bro, lag_melding, les_konfig, les_melding, naa

STANDARD_KOMMANDOER = {
    # Prompten sendes inn på stdin. {svarfil} byttes ut med en midlertidig fil.
    "claude": ["claude", "-p", "--output-format", "text", "--permission-mode", "acceptEdits",
               "--allowedTools", "Read,Edit,Write,Glob,Grep,Bash(git:*)"],
    # --full-auto er fjernet i nyere Codex (0.149+): sandbox og godkjenning settes hver for seg
    "codex": ["codex", "-a", "never", "exec", "-s", "workspace-write", "--skip-git-repo-check",
              "-o", "{svarfil}", "-"],
}

BLOKK = re.compile(r"===MELDING===\s*\n(.*?)\n\s*===SLUTT===", re.S)

LOGG: Path | None = None


def logg(tekst: str):
    linje = f"{naa()}  {tekst}"
    print(linje, flush=True)
    if LOGG:
        try:
            with LOGG.open("a", encoding="utf-8") as f:
                f.write(linje + "\n")
        except OSError:
            pass


# ---------- prompt ----------

def bygg_prompt(bro: Bro, agent: str, m: dict, k: dict) -> str:
    d = bro.deltakere()
    roller = d.get("agenter", {})
    koord = d.get("koordinator")
    liste = "\n".join(f"- {navn}: {rolle}" for navn, rolle in roller.items())
    historikk = [h for h in bro.historikk(m["traad"], k["historikk_meldinger"]) if h.get("id") != m["id"]]
    hist_tekst = "\n\n".join(
        f"[{h.get('tid','')}] {h.get('fra')} → {h.get('til')} ({h.get('type')}):\n{h.get('tekst','')}"
        for h in historikk) or "(ingen tidligere meldinger)"
    vedlegg = ", ".join(f".broen-inn/{m['traad']}/{v}" for v in m.get("vedlegg", [])) or "ingen"
    ferdigregel = (f"Bare koordinatoren ({koord}) kan sende type 'ferdig' til haj. "
                   f"Andre sender 'ferdig' til koordinatoren." if koord else "")
    return f"""Du er agenten «{agent}» i Broen, et samarbeid mellom flere AI-agenter på flere PC-er.
Din rolle: {roller.get(agent, 'ikke beskrevet')}

Deltakere:
{liste}
- haj: mennesket som eier prosjektet. Skriv til haj bare når du trenger en avgjørelse eller er ferdig.

Arbeidsregler:
- Arbeidskatalogen din er prosjektets git-repo. Kjør `git pull` før du endrer noe, og commit + push når du har gjort kodeendringer.
- Innkommende vedlegg ligger i .broen-inn/{m['traad']}/ i arbeidskatalogen.
- Filer du vil sende: legg dem i .broen-ut/ i arbeidskatalogen og list filnavnene i vedlegg-feltet.
- Hold meldingene korte og konkrete. Den du skriver til ser bare tråden, ikke det du har gjort lokalt.
- {ferdigregel}

Tråd: {m['traad']}
Historikk (eldst først):
{hist_tekst}

NY MELDING TIL DEG fra {m['fra']} (type: {m['type']}, vedlegg: {vedlegg}):
{m['tekst']}

Gjør arbeidet. Avslutt svaret ditt med én eller flere meldinger i nøyaktig dette formatet:

===MELDING===
til: <deltaker eller haj>
type: <oppgave | svar | spørsmål | ferdig>
vedlegg: <filnavn fra .broen-ut, kommaseparert, eller tom>
---
<meldingstekst>
===SLUTT===

Hvis ingen trenger svar fra deg, skriv bare ===INGEN===
"""


# ---------- kjøring ----------

def kjor_agent(k: dict, info: dict, prompt: str, svarfil: Path) -> tuple[int, str, str]:
    mal = info.get("kommando") or k.get("kommandoer", {}).get(info["type"]) or STANDARD_KOMMANDOER[info["type"]]
    cmd = [a.replace("{svarfil}", str(svarfil)) for a in mal]
    cmd[0] = shutil.which(cmd[0]) or cmd[0]
    p = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=info["repo"], timeout=k["tidsavbrudd_sekunder"])
    ut = p.stdout
    if svarfil.exists():
        ut = svarfil.read_text(encoding="utf-8", errors="replace")
        svarfil.unlink()
    return p.returncode, ut, p.stderr


def selvsjekk(bro: Bro, k: dict, agent: str) -> dict:
    """Billig sjekk uten å bruke kvote: finnes verktøyet, repoet, git-remote og disken?"""
    info = k["agenter"][agent]
    mal = info.get("kommando") or k.get("kommandoer", {}).get(info["type"]) or STANDARD_KOMMANDOER[info["type"]]
    r: dict = {"tid": naa()}

    def kjor(cmd, cwd=None, t=30):
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=cwd, timeout=t)
        return p.returncode, (p.stdout + p.stderr).strip()

    exe = shutil.which(mal[0])
    if not exe:
        r["cli"] = {"ok": False, "melding": f"fant ikke «{mal[0]}» i PATH"}
    else:
        try:
            kode, ut = kjor([exe, "--version"])
            r["cli"] = {"ok": kode == 0, "melding": (ut.splitlines() or ["?"])[-1][:80]}
        except Exception as e:
            r["cli"] = {"ok": False, "melding": f"{type(e).__name__}: {e}"}

    repo = Path(info["repo"])
    if not repo.is_dir():
        r["repo"] = {"ok": False, "melding": f"mappen {repo} finnes ikke"}
        r["git"] = {"ok": False, "melding": "hoppet over (ingen repo)"}
    else:
        r["repo"] = {"ok": (repo / ".git").exists(), "melding": str(repo) if (repo / ".git").exists() else f"{repo} er ikke et git-repo"}
        try:
            kode, ut = kjor(["git", "ls-remote", "--exit-code", "origin", "HEAD"], cwd=repo)
            r["git"] = {"ok": kode == 0, "melding": "origin svarer" if kode == 0 else (ut[:120] or f"kode {kode}")}
        except Exception as e:
            r["git"] = {"ok": False, "melding": f"{type(e).__name__}: {e}"}

    try:
        p = bro.rot / "status" / f".skrivetest-{agent}"
        p.write_text("ok", encoding="utf-8"); p.unlink()
        r["disk"] = {"ok": True, "melding": "lese/skrive ok"}
    except OSError as e:
        r["disk"] = {"ok": False, "melding": str(e)}
    return r


PING_PROMPT = "Dette er en helsesjekk fra Broen. Ikke gjør noe annet. Svar bare med ordet PONG."


def dyp_sjekk(bro: Bro, k: dict, agent: str):
    info = k["agenter"][agent]
    logg(f"{agent}: dyp sjekk (ping)")
    bro.sett_agentstatus(agent, "dyp sjekk")
    start = time.time()
    try:
        kode, ut, feil = kjor_agent(dict(k, tidsavbrudd_sekunder=180), info, PING_PROMPT, Path(info["repo"]) / ".broen-svar.txt")
        ok = kode == 0 and "PONG" in ut.upper()
        resultat = {"ok": ok, "sekunder": round(time.time() - start, 1), "tid": naa()}
        if not ok:
            resultat["feil"] = (feil or ut or f"kode {kode}").strip()[-300:]
    except Exception as e:
        resultat = {"ok": False, "sekunder": round(time.time() - start, 1), "tid": naa(), "feil": f"{type(e).__name__}: {e}"}
    bro.oppdater_agentstatus(agent, ping=resultat)
    logg(f"{agent}: dyp sjekk {'OK' if resultat['ok'] else 'FEILET'} ({resultat['sekunder']} s)")
    bro.sett_agentstatus(agent, "ledig")


def puls(bro: Bro, agenter: list[str]):
    """Bakgrunnstråd: viser at vaktmesteren lever, også mens en agent jobber lenge."""
    while True:
        for a in agenter:
            try:
                bro.oppdater_agentstatus(a, puls=naa())
            except OSError:
                pass
        time.sleep(15)


def tolk_svar(ut: str) -> list[dict] | None:
    """Returnerer liste med {til, type, vedlegg, tekst}, [] for ===INGEN===, None hvis ugyldig."""
    blokker = BLOKK.findall(ut)
    if not blokker:
        return [] if "===INGEN===" in ut else None
    svar = []
    for b in blokker:
        hode, _, kropp = b.partition("\n---")
        felt = {}
        for linje in hode.splitlines():
            if ":" in linje:
                n, v = linje.split(":", 1)
                felt[n.strip().lower()] = v.strip()
        svar.append({
            "til": felt.get("til", MENNESKE),
            "type": felt.get("type", "svar"),
            "vedlegg": [v.strip() for v in felt.get("vedlegg", "").split(",") if v.strip()],
            "tekst": kropp.strip(),
        })
    return svar


def behandle(bro: Bro, k: dict, agent: str, sti: Path):
    m = les_melding(sti)
    m.setdefault("traad", "uten-navn")
    info = k["agenter"][agent]
    repo = Path(info["repo"])
    logg(f"{agent}: ny melding fra {m.get('fra')} i tråd «{m['traad']}» (runde {m['runde']})")
    bro.sett_agentstatus(agent, "arbeider", m["traad"])

    # vedlegg inn: kopier fra nettverksdisken til arbeidskatalogen
    inn_dir = repo / ".broen-inn" / m["traad"]
    for v in m.get("vedlegg", []):
        kilde = bro.vedlegg(m["traad"]) / v
        if kilde.exists():
            inn_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(kilde, inn_dir / Path(v).name)
    ut_dir = repo / ".broen-ut"
    ut_dir.mkdir(exist_ok=True)

    d = bro.deltakere()
    gyldige = set(d.get("agenter", {})) | {MENNESKE}
    koord = d.get("koordinator")
    neste_runde = int(m.get("runde", 0)) + 1

    try:
        kode, ut, feil = kjor_agent(k, info, bygg_prompt(bro, agent, m, k), repo / ".broen-svar.txt")
    except subprocess.TimeoutExpired:
        kode, ut, feil = -1, "", f"Tidsavbrudd etter {k['tidsavbrudd_sekunder']} sekunder"
    except Exception as e:  # f.eks. kommando ikke funnet
        kode, ut, feil = -1, "", f"{type(e).__name__}: {e}"

    svar = tolk_svar(ut) if kode == 0 else None
    if svar is None:
        grunn = f"feilet (kode {kode})" if kode != 0 else "svarte uten gyldig meldingsformat"
        tekst = f"Agenten {grunn}.\n\nUtdata (siste del):\n{ut[-3000:]}\n\nFeil:\n{feil[-2000:]}"
        bro.lever(lag_melding(agent, MENNESKE, m["traad"], "spørsmål", tekst, neste_runde))
        bro.oppdater_agentstatus(agent, sist_feil={"tid": naa(), "grunn": grunn + (f" – {feil.strip()[-150:]}" if feil.strip() else "")})
        logg(f"{agent}: {grunn} – sendt til haj")
    else:
        bro.oppdater_agentstatus(agent, sist_ok=naa())
        for s in svar:
            til, type_ = s["til"], s["type"]
            notat = ""
            if til not in gyldige:
                notat += f"\n\n[Broen: ukjent mottaker «{til}», sendt til haj i stedet]"
                til = MENNESKE
            if type_ not in TYPER:
                type_ = "svar"
            if type_ == "ferdig" and koord and agent != koord and til == MENNESKE:
                til = koord
                notat += "\n\n[Broen: 'ferdig' omdirigert til koordinatoren]"
            # vedlegg ut: kopier fra arbeidskatalogen til nettverksdisken
            sendt = []
            for v in s["vedlegg"]:
                kilde = ut_dir / v
                if kilde.is_file():
                    mål = bro.vedlegg(m["traad"]) / kilde.name
                    mål.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(kilde, mål)
                    sendt.append(kilde.name)
                else:
                    notat += f"\n\n[Broen: fant ikke vedlegget «{v}» i .broen-ut]"
            hvor = bro.lever(lag_melding(agent, til, m["traad"], type_, s["tekst"] + notat, neste_runde, sendt))
            logg(f"{agent} → {til} ({type_}) levert: {hvor}")
        for f in ut_dir.iterdir():
            if f.is_file():
                f.unlink()
        if not svar:
            logg(f"{agent}: ingen svar (===INGEN===)")
    bro.sett_agentstatus(agent, "ledig")


def main():
    global LOGG
    if len(sys.argv) < 2:
        print("Bruk: python vaktmester.py broen.json")
        sys.exit(1)
    k = les_konfig(sys.argv[1])
    bro = Bro(k["rot"], k["maks_runder"])
    agenter = list(k["agenter"])
    bro.sikre_mapper(agenter)
    LOGG = bro.rot / "logg" / f"{k.get('pc', 'pc')}.log"

    # gjenoppretting etter krasj: sett .behandles tilbake til .md
    for a in agenter:
        for f in bro.inn(a).glob("*.behandles"):
            f.rename(f.with_suffix(".md"))
        bro.sett_agentstatus(a, "ledig")
    logg(f"Vaktmester startet for {', '.join(agenter)} – rot: {bro.rot}")
    threading.Thread(target=puls, args=(bro, agenter), daemon=True).start()
    neste_sjekk = 0.0

    while True:
        try:
            # selvsjekk ved oppstart og hvert n. minutt
            if time.time() >= neste_sjekk:
                for a in agenter:
                    bro.oppdater_agentstatus(a, sjekk=selvsjekk(bro, k, a))
                neste_sjekk = time.time() + k["selvsjekk_minutter"] * 60
            # dyp sjekk bestilt fra monitoren (kjøres også under STOPP)
            for a in agenter:
                bestilling = bro.rot / "ping" / f"{a}.json"
                if bestilling.exists():
                    bestilling.unlink()
                    dyp_sjekk(bro, k, a)
                    bro.oppdater_agentstatus(a, sjekk=selvsjekk(bro, k, a))
            if bro.stopp_aktiv():
                for a in agenter:
                    bro.sett_agentstatus(a, "stoppet")
                time.sleep(k["poll_sekunder"])
                continue
            for a in agenter:
                for f in sorted(bro.inn(a).glob("*.md")):
                    if bro.stopp_aktiv():
                        break
                    reservert = f.with_suffix(".behandles")
                    try:
                        f.rename(reservert)  # reserver meldingen
                    except OSError:
                        continue
                    try:
                        behandle(bro, k, a, reservert)
                    except Exception:
                        logg(f"{a}: uventet feil\n{traceback.format_exc()}")
                        bro.sett_agentstatus(a, "feil")
                    finally:
                        if reservert.exists():
                            reservert.unlink()
                # hjerteslag
                if not any(bro.inn(a).glob("*.md")):
                    bro.sett_agentstatus(a, "ledig")
        except OSError as e:
            logg(f"Får ikke tak i nettverksdisken ({e}) – prøver igjen")
        time.sleep(k["poll_sekunder"])


if __name__ == "__main__":
    main()
