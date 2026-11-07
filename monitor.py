"""Broen – overvåkning. Kjøres på én PC (gjerne den med nettverksdisken):

    python monitor.py broen.json

Åpne http://<pc>:8765 i nettleseren.
"""
from __future__ import annotations

import json
import mimetypes
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from felles import MENNESKE, Bro, fra_tekst, helse, lag_melding, les_konfig, les_melding, trygg_navn

HTML = (Path(__file__).parent / "monitor.html").read_text(encoding="utf-8")


def lag_handler(bro: Bro, token: str | None):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def svar(self, data, kode=200, type_="application/json"):
            body = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False).encode()
            self.send_response(kode)
            self.send_header("Content-Type", type_ + ("; charset=utf-8" if "text" in type_ or "json" in type_ else ""))
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def ok_token(self) -> bool:
            if not token:
                return True
            q = parse_qs(urlparse(self.path).query)
            return self.headers.get("X-Token") == token or q.get("token", [""])[0] == token

        # ---------- GET ----------
        def do_GET(self):
            u = urlparse(self.path)
            if u.path == "/":
                return self.svar(HTML.encode(), type_="text/html")
            if not self.ok_token():
                return self.svar({"feil": "feil token"}, 401)
            q = parse_qs(u.query)
            if u.path == "/api/oversikt":
                return self.svar(self.oversikt())
            if u.path == "/api/helse":
                return self.svar(helse(bro))
            if u.path == "/api/traad":
                t = q.get("id", [""])[0]
                return self.svar({"id": t, "status": bro.status(t), "meldinger": bro.historikk(t)})
            if u.path.startswith("/vedlegg/"):
                deler = [unquote(d) for d in u.path.split("/")[2:]]
                if len(deler) == 2:
                    f = bro.vedlegg(deler[0]) / Path(deler[1]).name
                    if f.is_file():
                        return self.svar(f.read_bytes(), type_=mimetypes.guess_type(f.name)[0] or "application/octet-stream")
            self.svar({"feil": "ikke funnet"}, 404)

        def oversikt(self):
            traader = []
            d = bro.rot / "traader"
            holdt = [les_melding(f) for f in sorted(bro.venter.glob("*.md"))]
            til_haj = [les_melding(f) for f in sorted(bro.inn(MENNESKE).glob("*.md"))]
            if d.exists():
                for t in d.iterdir():
                    if not t.is_dir():
                        continue
                    filer = sorted(t.glob("*.md"))
                    sist = les_melding(filer[-1]) if filer else {}
                    traader.append({
                        "id": t.name, "antall": len(filer), "sist": sist.get("tid", ""),
                        "sist_fra": sist.get("fra", ""), "sist_type": sist.get("type", ""),
                        "pause": bro.status(t.name).get("pause", False),
                        "holdt": sum(1 for h in holdt if h.get("traad") == t.name),
                        "til_haj": sum(1 for h in til_haj if h.get("traad") == t.name),
                    })
            traader.sort(key=lambda x: x["sist"], reverse=True)
            return {
                "stopp": bro.stopp_aktiv(), "maks_runder": bro.maks_runder,
                "deltakere": bro.deltakere(), "agenter": bro.agentstatuser(),
                "traader": traader, "holdt": holdt, "til_haj": til_haj,
                "helse": helse(bro),
            }

        # ---------- POST ----------
        def do_POST(self):
            if not self.ok_token():
                return self.svar({"feil": "feil token"}, 401)
            n = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(n) or b"{}")
            p = urlparse(self.path).path
            try:
                return self.svar(self.handling(p, data))
            except (KeyError, ValueError, FileNotFoundError) as e:
                return self.svar({"feil": str(e)}, 400)

        def handling(self, p, data):
            if p == "/api/send":
                if data.get("til") not in bro.deltakere().get("agenter", {}):
                    raise ValueError(f"ukjent mottaker «{data.get('til')}» – sjekk deltakere.json")
                # Din melding nullstiller rundetelleren (runde 0)
                m = lag_melding(MENNESKE, data["til"], data["traad"], data.get("type", "oppgave"), data["tekst"])
                # når du svarer i en tråd, regnes meldingene til deg i den tråden som behandlet
                for f in bro.inn(MENNESKE).glob("*.md"):
                    if les_melding(f).get("traad") == m["traad"]:
                        f.unlink()
                return {"levert": bro.lever(m, tving=True), "traad": m["traad"]}
            if p == "/api/slipp":
                f = bro.venter / Path(data["fil"]).name
                m = fra_tekst(f.read_text(encoding="utf-8"))
                if "tekst" in data and data["tekst"].strip() != m.get("tekst", "").strip():
                    m["tekst"] = data["tekst"].strip()
                    m["redigert"] = "ja (haj)"
                if data.get("til"):
                    m["til"] = data["til"]
                m["runde"] = 0
                if bro.stopp_aktiv():
                    raise ValueError("STOPP er aktiv – slå den av før du slipper meldinger")
                f.unlink()
                return {"levert": bro.lever(m, tving=True)}
            if p == "/api/slett":
                f = bro.venter / Path(data["fil"]).name
                m = fra_tekst(f.read_text(encoding="utf-8"))
                m["holdt"] = "slettet av haj"
                bro.arkiver(m)
                f.unlink()
                return {"ok": True}
            if p == "/api/lest":
                f = bro.inn(MENNESKE) / Path(data["fil"]).name
                if f.exists():
                    f.unlink()
                return {"ok": True}
            if p == "/api/stopp":
                bro.sett_stopp(bool(data["paa"]))
                return {"stopp": bro.stopp_aktiv()}
            if p == "/api/ping":
                agenter = list(bro.deltakere().get("agenter", {}))
                valgt = agenter if data.get("agent", "alle") == "alle" else [data["agent"]]
                for a in valgt:
                    if a not in agenter:
                        raise ValueError(f"ukjent agent {a}")
                    bro.be_om_ping(a)
                return {"bestilt": valgt}
            if p == "/api/pause":
                bro.sett_status(trygg_navn(data["traad"]), pause=bool(data["paa"]))
                return {"ok": True}
            raise KeyError(f"ukjent handling {p}")

    return H


def main():
    if len(sys.argv) < 2:
        print("Bruk: python monitor.py broen.json")
        sys.exit(1)
    k = les_konfig(sys.argv[1])
    bro = Bro(k["rot"], k["maks_runder"])
    bro.sikre_mapper(bro.deltakere().get("agenter", {}))
    port = int(k.get("monitor_port", 8765))
    srv = ThreadingHTTPServer(("0.0.0.0", port), lag_handler(bro, k.get("monitor_token")))
    print(f"Broen-monitor kjører på http://localhost:{port}  (rot: {bro.rot})")
    srv.serve_forever()


if __name__ == "__main__":
    main()
