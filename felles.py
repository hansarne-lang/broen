"""Broen – felles kode for vaktmester og monitor.

Alt ligger som filer på nettverksdisken (rot):
  postkasser/<agent>/inn/*.md   meldinger som venter på en agent
  postkasser/haj/inn/*.md       meldinger til deg
  venter/*.md                   meldinger holdt tilbake (pause / rundegrense / STOPP)
  traader/<traad>/*.md          full historikk per tråd (+ status.json)
  vedlegg/<traad>/              filer som sendes mellom agentene
  status/<agent>.json           hva hver agent holder på med akkurat nå
  logg/<pc>.log                 logg fra vaktmesterne
  deltakere.json                roller (felles for alle PC-er)
  STOPP                         finnes denne fila, stopper all levering
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import threading
import uuid
from pathlib import Path

FELT = ["id", "tid", "fra", "til", "traad", "type", "runde", "vedlegg", "holdt", "redigert"]
TYPER = ["oppgave", "svar", "spørsmål", "ferdig"]
MENNESKE = "haj"


def naa() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


def ny_id() -> str:
    return _dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:-3] + "-" + uuid.uuid4().hex[:4]


def trygg_navn(s: str) -> str:
    """Gjør et tråd- eller filnavn trygt å bruke som mappenavn."""
    s = re.sub(r"[^\wæøåÆØÅ.\-]+", "-", (s or "").strip()).strip("-.")
    return s[:80] or "uten-navn"


def skriv_atomisk(sti: Path, tekst: str) -> None:
    """Skriv til .tmp og gi nytt navn, så ingen leser en halvskrevet fil."""
    sti.parent.mkdir(parents=True, exist_ok=True)
    tmp = sti.with_name(sti.name + f".{uuid.uuid4().hex[:6]}.tmp")
    tmp.write_text(tekst, encoding="utf-8")
    os.replace(tmp, sti)


# ---------- meldinger ----------

def lag_melding(fra, til, traad, type_, tekst, runde=0, vedlegg=None) -> dict:
    return {
        "id": ny_id(), "tid": naa(), "fra": fra, "til": til,
        "traad": trygg_navn(traad), "type": type_ if type_ in TYPER else "svar",
        "runde": int(runde), "vedlegg": list(vedlegg or []), "tekst": tekst.strip(),
    }


def til_tekst(m: dict) -> str:
    linjer = ["---"]
    for f in FELT:
        if f not in m or m[f] in (None, ""):
            continue
        v = m[f]
        if f == "vedlegg":
            if not v:
                continue
            v = ", ".join(v)
        linjer.append(f"{f}: {v}")
    linjer.append("---")
    return "\n".join(linjer) + "\n" + m.get("tekst", "") + "\n"


def fra_tekst(tekst: str) -> dict:
    m: dict = {"vedlegg": [], "runde": 0}
    if tekst.startswith("---"):
        _, hode, kropp = tekst.split("---", 2)
        for linje in hode.strip().splitlines():
            if ":" in linje:
                k, v = linje.split(":", 1)
                m[k.strip()] = v.strip()
        m["tekst"] = kropp.lstrip("\n").rstrip()
    else:
        m["tekst"] = tekst
    if isinstance(m.get("vedlegg"), str):
        m["vedlegg"] = [v.strip() for v in m["vedlegg"].split(",") if v.strip()]
    try:
        m["runde"] = int(m.get("runde", 0))
    except ValueError:
        m["runde"] = 0
    return m


def les_melding(sti: Path) -> dict:
    m = fra_tekst(sti.read_text(encoding="utf-8"))
    m["_fil"] = sti.name
    return m


# ---------- broen ----------

class Bro:
    def __init__(self, rot, maks_runder: int = 20):
        self.rot = Path(rot)
        self.maks_runder = maks_runder

    # stier
    def inn(self, agent: str) -> Path: return self.rot / "postkasser" / agent / "inn"
    def traad(self, t: str) -> Path: return self.rot / "traader" / trygg_navn(t)
    def vedlegg(self, t: str) -> Path: return self.rot / "vedlegg" / trygg_navn(t)
    @property
    def venter(self) -> Path: return self.rot / "venter"
    @property
    def stoppfil(self) -> Path: return self.rot / "STOPP"

    def sikre_mapper(self, agenter=()):
        for d in ["traader", "vedlegg", "venter", "status", "logg", "ping"]:
            (self.rot / d).mkdir(parents=True, exist_ok=True)
        for a in [MENNESKE, *agenter]:
            self.inn(a).mkdir(parents=True, exist_ok=True)

    # deltakere / roller
    def deltakere(self) -> dict:
        sti = self.rot / "deltakere.json"
        if sti.exists():
            return json.loads(sti.read_text(encoding="utf-8"))
        return {"koordinator": None, "agenter": {}}

    # STOPP
    def stopp_aktiv(self) -> bool:
        return self.stoppfil.exists()

    def sett_stopp(self, paa: bool):
        if paa:
            skriv_atomisk(self.stoppfil, f"Stoppet {naa()}\n")
        elif self.stoppfil.exists():
            self.stoppfil.unlink()

    # trådstatus
    def status(self, t: str) -> dict:
        sti = self.traad(t) / "status.json"
        if sti.exists():
            try:
                return json.loads(sti.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass
        return {"pause": False}

    def sett_status(self, t: str, **endringer):
        s = self.status(t)
        s.update(endringer)
        skriv_atomisk(self.traad(t) / "status.json", json.dumps(s, ensure_ascii=False, indent=2))

    def historikk(self, t: str, maks: int | None = None) -> list[dict]:
        d = self.traad(t)
        if not d.exists():
            return []
        filer = sorted(d.glob("*.md"))
        if maks:
            filer = filer[-maks:]
        return [les_melding(f) for f in filer]

    def arkiver(self, m: dict):
        skriv_atomisk(self.traad(m["traad"]) / f"{m['id']}.md", til_tekst(m))

    # levering
    def lever(self, m: dict, tving: bool = False) -> str:
        """Lever en melding. Returnerer hvor den havnet: 'inn', 'venter' eller 'haj'.

        tving=True brukes når du slipper en holdt melding: den går forbi pause
        og rundegrense (men ikke forbi STOPP).
        """
        m.pop("_fil", None)
        grunn = None
        if m["til"] != MENNESKE:
            if self.stopp_aktiv():
                grunn = "STOPP er aktiv"
            elif not tving and self.status(m["traad"]).get("pause"):
                grunn = "tråden er satt på pause"
            elif not tving and int(m.get("runde", 0)) > self.maks_runder:
                grunn = f"rundegrensen ({self.maks_runder}) er nådd"
        if grunn:
            m["holdt"] = grunn
        else:
            m.pop("holdt", None)
        self.arkiver(m)
        if grunn:
            skriv_atomisk(self.venter / f"{m['id']}.md", til_tekst(m))
            return "venter"
        skriv_atomisk(self.inn(m["til"]) / f"{m['id']}.md", til_tekst(m))
        return "haj" if m["til"] == MENNESKE else "inn"

    # agentstatus (hjerteslag + selvsjekk). Flettes, så felter fra andre kall beholdes.
    _laas = threading.Lock()

    def oppdater_agentstatus(self, agent: str, **felt):
        sti = self.rot / "status" / f"{agent}.json"
        with self._laas:
            s = {}
            if sti.exists():
                try:
                    s = json.loads(sti.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    s = {}
            s.update(felt, agent=agent)
            skriv_atomisk(sti, json.dumps(s, ensure_ascii=False, indent=1))

    def sett_agentstatus(self, agent: str, tilstand: str, traad: str | None = None):
        self.oppdater_agentstatus(agent, tilstand=tilstand, traad=traad, tid=naa(), puls=naa())

    def be_om_ping(self, agent: str):
        skriv_atomisk(self.rot / "ping" / f"{agent}.json", json.dumps({"bestilt": naa()}))

    def agentstatuser(self) -> list[dict]:
        ut = []
        for f in sorted((self.rot / "status").glob("*.json")):
            try:
                ut.append(json.loads(f.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError):
                pass
        return ut


def alder_sek(tid: str | None) -> float | None:
    if not tid:
        return None
    try:
        return (_dt.datetime.now() - _dt.datetime.fromisoformat(tid)).total_seconds()
    except ValueError:
        return None


def helse(bro: "Bro") -> dict:
    """Svarer på «er alle grønne?». Nivå per punkt: ok / gul / rod."""
    d = bro.deltakere()
    statuser = {s.get("agent"): s for s in bro.agentstatuser()}
    globalt = []

    # nettverksdisken (sett fra monitoren)
    try:
        p = bro.rot / "status" / ".skrivetest"
        p.write_text("ok", encoding="utf-8"); p.unlink()
        globalt.append(("ok", "Nettverksdisken er tilgjengelig og skrivbar"))
    except OSError as e:
        globalt.append(("rod", f"Får ikke skrevet til nettverksdisken: {e}"))
    if bro.stopp_aktiv():
        globalt.append(("gul", "STOPP er aktiv – ingenting leveres"))
    if not d.get("agenter"):
        globalt.append(("rod", "deltakere.json mangler eller er tom"))
    holdt = len(list(bro.venter.glob("*.md")))
    tilhaj = len(list(bro.inn(MENNESKE).glob("*.md")))
    if holdt:
        globalt.append(("gul", f"{holdt} melding(er) holdt tilbake og venter på deg"))
    if tilhaj:
        globalt.append(("gul", f"{tilhaj} melding(er) til deg er ubesvart"))

    agenter = []
    for navn in d.get("agenter", {}):
        s = statuser.get(navn)
        pkt = []
        if not s:
            pkt.append(("rod", "Vaktmesteren har aldri meldt seg (ikke startet, eller feil navn i broen.json)"))
        else:
            puls = alder_sek(s.get("puls") or s.get("tid"))
            if puls is None or puls > 60:
                pkt.append(("rod", f"Ingen livstegn på {int(puls or 0)} s – vaktmester nede eller PC av?"))
            else:
                pkt.append(("ok", f"Vaktmester lever (puls for {int(puls)} s siden)"))
            if s.get("tilstand") == "feil":
                pkt.append(("rod", "Vaktmesteren fikk en uventet feil i siste kjøring (se logg)"))
            sj = s.get("sjekk")
            if not sj:
                pkt.append(("gul", "Selvsjekk er ikke kjørt ennå"))
            else:
                for nokkel, tekst in [("cli", "Kommandolinjeverktøy"), ("repo", "Repo"), ("git", "Git-remote"), ("disk", "Nettverksdisk fra PC-en")]:
                    v = sj.get(nokkel, {})
                    pkt.append(("ok" if v.get("ok") else "rod", f"{tekst}: {v.get('melding', 'ukjent')}"))
                a = alder_sek(sj.get("tid"))
                if a is not None and a > 20 * 60:
                    pkt.append(("gul", f"Selvsjekken er {int(a // 60)} min gammel"))
            sf, so = s.get("sist_feil"), s.get("sist_ok")
            if sf and (not so or sf.get("tid", "") > so):
                pkt.append(("rod", f"Siste agentkjøring feilet ({sf.get('tid','')[11:16]}): {sf.get('grunn','')}"))
            ping = s.get("ping")
            if ping:
                if ping.get("ok"):
                    pkt.append(("ok", f"Dyp sjekk: svarte på {ping.get('sekunder')} s ({ping.get('tid','')[11:16]})"))
                else:
                    pkt.append(("rod", f"Dyp sjekk feilet ({ping.get('tid','')[11:16]}): {ping.get('feil','')}"))
            if (bro.rot / "ping" / f"{navn}.json").exists():
                pkt.append(("gul", "Dyp sjekk bestilt – venter på svar"))
            ko = len(list(bro.inn(navn).glob("*.md")))
            if ko > 5:
                pkt.append(("gul", f"{ko} meldinger i kø"))
        niva = "rod" if any(n == "rod" for n, _ in pkt) else "gul" if any(n == "gul" for n, _ in pkt) else "ok"
        agenter.append({"agent": navn, "niva": niva, "tilstand": (s or {}).get("tilstand", "ukjent"),
                        "punkter": [{"niva": n, "tekst": t} for n, t in pkt]})

    alle_rod = any(a["niva"] == "rod" for a in agenter) or any(n == "rod" for n, _ in globalt)
    alle_gul = any(a["niva"] == "gul" for a in agenter) or any(n == "gul" for n, _ in globalt)
    return {
        "niva": "rod" if alle_rod else "gul" if alle_gul else "ok",
        "alle_gronne": not alle_rod,
        "tid": naa(),
        "globalt": [{"niva": n, "tekst": t} for n, t in globalt],
        "agenter": agenter,
    }


def les_konfig(sti) -> dict:
    k = json.loads(Path(sti).read_text(encoding="utf-8"))
    k.setdefault("maks_runder", 20)
    k.setdefault("poll_sekunder", 5)
    k.setdefault("tidsavbrudd_sekunder", 1800)
    k.setdefault("historikk_meldinger", 30)
    k.setdefault("selvsjekk_minutter", 5)
    k.setdefault("agenter", {})
    return k
