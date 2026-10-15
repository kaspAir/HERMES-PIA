"""UI-Nachweis der Live-Anzeige «Für den PIA erkannt» – in einem echten Chrome.

Startet HERMES PIA mit einer frischen Datenbank, einem synthetischen Fall
(erfundene Organisation) und einem Drehbuch-Modell, meldet sich an, steuert
Chrome über das DevTools-Protokoll und prüft im Browser:

  - nach dem Absenden eines Beitrags aktualisiert sich die Anzeige OHNE
    Seiten-Reload (eine im Fenster gesetzte Marke überlebt),
  - neue Aussagen tragen «Neu», der Status steht als Text,
  - RAG-Themen stehen getrennt und nie unter «von Dir genannt»,
  - eine Korrektur ersetzt die Angabe ohne Neustart,
  - schmal: der Kurzstatus ist sichtbar und klappt die Erkenntnisse auf.

Ergebnis: Screenshots und ein Prüfprotokoll (JSON) im Zielordner.

    python tools/ui_nachweis_adaptiv.py [zielordner]

Wichtig: Server, Chrome und Aufnahme laufen in EINEM Prozess – getrennt
gestartete Prozesse überleben einen Werkzeugaufruf nicht.
"""
import base64
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

WURZEL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WURZEL))

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"


def freier_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class CDP:
    """Minimaler DevTools-Client über websocket-client."""

    def __init__(self, ws_url):
        import websocket
        self.ws = websocket.create_connection(ws_url, timeout=30, suppress_origin=True)
        self.nr = 0

    def __call__(self, methode, **params):
        self.nr += 1
        self.ws.send(json.dumps({"id": self.nr, "method": methode, "params": params}))
        while True:
            antwort = json.loads(self.ws.recv())
            if antwort.get("id") == self.nr:
                if "error" in antwort:
                    raise RuntimeError(f"{methode}: {antwort['error']}")
                return antwort.get("result", {})

    def js(self, ausdruck):
        r = self("Runtime.evaluate", expression=ausdruck, returnByValue=True, awaitPromise=True)
        if r.get("exceptionDetails"):
            raise RuntimeError(f"JS-Fehler: {r['exceptionDetails']}")
        return r.get("result", {}).get("value")

    def warte(self, ausdruck, sekunden=30, text="Bedingung"):
        ende = time.time() + sekunden
        while time.time() < ende:
            if self.js(ausdruck):
                return True
            time.sleep(0.25)
        raise TimeoutError(f"Zeitüberschreitung: {text}")

    def bild(self, pfad, voll=True):
        r = self("Page.captureScreenshot", format="png", captureBeyondViewport=voll)
        Path(pfad).write_bytes(base64.b64decode(r["data"]))


def main(ziel):
    ziel = Path(ziel)
    ziel.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="hp_ui_"))

    from app.config import Config
    from app.domains.corpus.service import RagService
    from app.domains.interview.adaptiv.rag_themen import ThemenQuelle
    from app.factory import create_app
    from tools.synthetische_faelle import ABLOESUNG, KORPUS, DrehbuchModell, WortEmbedder

    class Cfg(Config):
        DATABASE_URL = "sqlite:///" + str(tmp / "ui.db").replace("\\", "/")
        SECRET_KEY = secrets.token_hex(16)
        INTERVIEW_ADAPTIV = True

    app = create_app(Cfg)
    rag = RagService(WortEmbedder())
    for k in KORPUS:
        rag.ingest_document(k["text"], projekt=k["projekt"], korpus_version="synthetisch-1")
    modell = DrehbuchModell(ABLOESUNG)
    app.adaptiv_service.llm = modell
    app.adaptiv_service.themen = ThemenQuelle(rag)
    org = app.auth_service.create_org("Musterkanton – Amt für Baubewilligungen").id
    passwort = secrets.token_urlsafe(12)
    app.auth_service.create_user("pl@musterkanton.example", passwort, org_id=org,
                                 can_read=True, can_write=True)
    app.projekt_service.set_kostensatz(1200, 1800, einheit="tag", org_id=org)

    port = freier_port()
    from werkzeug.serving import make_server
    server = make_server("127.0.0.1", port, app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    basis = f"http://127.0.0.1:{port}"

    # Anmelden und Auftrag anlegen – über die echten Formulare.
    import http.cookiejar
    jar = http.cookiejar.CookieJar()
    oeffner = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    def post(pfad, daten):
        return oeffner.open(urllib.request.Request(
            basis + pfad, data=urllib.parse.urlencode(daten).encode(), method="POST"))
    post("/login", {"email": "pl@musterkanton.example", "password": passwort})
    k = ABLOESUNG["kopf"]
    post("/interview/start", {"project_name": k["projektname"], "projektleiter": k["projektleiter"],
                              "auftraggeber": k["auftraggeber"]})
    with app.app_context():
        sid = app.interview_service.sessions_for_org(org)[0].id

    profil = tmp / "chrome"
    dbg = freier_port()
    chrome = subprocess.Popen([CHROME, "--headless=new", f"--remote-debugging-port={dbg}",
                               f"--user-data-dir={profil}", "--no-first-run",
                               "--no-default-browser-check", "--disable-gpu",
                               "--window-size=1440,1000", "about:blank"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    protokoll = {"fall": ABLOESUNG["id"], "pruefungen": [], "bilder": []}

    def pruefe(name, ok, detail=""):
        protokoll["pruefungen"].append({"pruefung": name, "ok": bool(ok), "detail": detail})
        print(("  ok   " if ok else "  FEHL ") + name + (f" – {detail}" if detail else ""))

    try:
        for _ in range(60):
            try:
                ziele = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{dbg}/json").read())
                seite = next(t for t in ziele if t.get("type") == "page")
                break
            except Exception:
                time.sleep(0.25)
        cdp = CDP(seite["webSocketDebuggerUrl"])
        cdp("Page.enable")
        cdp("Runtime.enable")
        for c in jar:
            cdp("Network.setCookie", name=c.name, value=c.value, domain="127.0.0.1", path="/")
        cdp("Emulation.setDeviceMetricsOverride", width=1440, height=1000,
            deviceScaleFactor=1, mobile=False)
        cdp("Page.navigate", url=f"{basis}/interview/{sid}")
        cdp.warte("document.readyState === 'complete' && !!document.getElementById('ai-frage')",
                  text="Seite geladen")
        fehler = cdp.js("window.__fehler = []; window.addEventListener('error', e => "
                        "window.__fehler.push(String(e.message))); true")
        time.sleep(0.5)
        def aufnahme(name):
            pfad = ziel / f"{name}.png"
            cdp.bild(pfad)
            protokoll["bilder"].append(pfad.name)

        aufnahme("01_einstieg_desktop")
        pruefe("Einstiegsfrage steht", cdp.js("document.querySelector('#ai-frage .frage-text') "
                                             "&& document.querySelector('#ai-frage .frage-text').textContent.length > 20"))
        pruefe("Gespräch und Erkenntnisse nebeneinander",
               cdp.js("(() => { const a = document.querySelector('.ai-gespraech').getBoundingClientRect();"
                      " const b = document.querySelector('.ai-erkannt').getBoundingClientRect();"
                      " return b.left > a.right - 1 && Math.abs(a.top - b.top) < 40; })()"))

        def senden(text):
            cdp.js("window.__marke = 'ohne-reload'; true")
            cdp.js(f"document.getElementById('answer-text').value = {json.dumps(text)};"
                   "document.getElementById('ai-eingabe').requestSubmit(); true")
            cdp.warte("!document.getElementById('ai-senden').disabled && "
                      "document.getElementById('ai-status').textContent === ''", 60,
                      "Verarbeitung abgeschlossen")
            return cdp.js("window.__marke === 'ohne-reload'")

        # Schritt 1: zusammenhängender Beitrag
        ohne_reload = senden(ABLOESUNG["schritte"][0]["text"])
        pruefe("Aktualisierung ohne Seiten-Reload", ohne_reload)
        n_neu = cdp.js("document.querySelectorAll('.ai-marke--neu').length")
        pruefe("Neue Aussagen tragen «Neu»", n_neu and n_neu >= 5, f"{n_neu} markiert")
        status = cdp.js("[...document.querySelectorAll('.ai-marke--status')].map(e => e.textContent)")
        pruefe("Status steht als Text", any(s == "von Dir genannt – unbestätigt" for s in status)
               and any(s == "Interpretation – noch zu bestätigen" for s in status), ", ".join(sorted(set(status)))[:160])
        rag = cdp.js("(() => { const h = [...document.querySelectorAll('#ai-panel-erkannt h2')]"
                     ".find(x => x.textContent.startsWith('Mögliche Klärungspunkte'));"
                     " const ul = h && h.nextElementSibling && h.nextElementSibling.nextElementSibling;"
                     " return ul ? [...ul.querySelectorAll('.ai-marke--status')].map(e => e.textContent) : []; })()")
        pruefe("RAG-Thema getrennt, nicht «von Dir genannt»", rag and all("Vergleichsprojekten" in r for r in rag),
               "; ".join(rag))
        frage = cdp.js("document.querySelector('#ai-frage .frage-text').textContent")
        pruefe("Nächste Frage stammt aus dem Korpus-Thema", "Datenbestände" in (frage or ""), frage)
        ansage = cdp.js("document.getElementById('ai-ansage').textContent")
        pruefe("Änderung wird angesagt (aria-live)", "neue Erkenntnis" in (ansage or ""), ansage)
        aufnahme("02_nach_erstem_beitrag_desktop")

        # Schritt 2: Korrektur im Gespräch
        ohne_reload = senden(ABLOESUNG["schritte"][1]["text"])
        texte = cdp.js("[...document.querySelectorAll('.ai-eintrag .inhalt')].map(e => e.textContent)")
        pruefe("Korrektur ersetzt ohne Neustart", ohne_reload and any("31. März 2027" in t for t in texte)
               and not any("Ende Februar 2027" in t for t in texte))
        geaendert = cdp.js("document.querySelectorAll('.ai-marke--neu, .ai-marke--geaendert').length")
        pruefe("Korrigierte Angabe hervorgehoben", geaendert >= 1)
        aufnahme("03_nach_korrektur_desktop")

        # Schritt 3: Thema bestätigt, Ziele, Aufwand AG
        senden(ABLOESUNG["schritte"][2]["text"])
        aufnahme("04_nach_drittem_beitrag_desktop")
        cdp.js("document.getElementById('tab-vorschau').click(); true")
        cdp.warte("document.getElementById('ai-panel-vorschau').textContent.includes('Revision')",
                  text="Vorschau geladen")
        aufnahme("05_dokumentvorschau_desktop")
        cdp.js("document.getElementById('tab-erkannt').click(); true")

        # Schmaler Bildschirm
        cdp("Emulation.setDeviceMetricsOverride", width=390, height=844, deviceScaleFactor=2, mobile=True)
        time.sleep(0.6)
        kurz = cdp.js("(() => { const k = document.getElementById('ai-kurzstatus');"
                      " return getComputedStyle(k).display !== 'none' ? k.textContent : ''; })()")
        pruefe("Schmal: Kurzstatus sichtbar", "Für den PIA erkannt" in (kurz or ""), kurz)
        eingabe_sichtbar = cdp.js("(() => { const r = document.getElementById('answer-text')"
                                  ".getBoundingClientRect(); return r.height > 50; })()")
        pruefe("Schmal: Eingabe nicht verdrängt", eingabe_sichtbar)
        breite = cdp.js("[document.documentElement.scrollWidth, window.innerWidth]")
        pruefe("Schmal: kein seitliches Scrollen", breite[0] <= breite[1] + 1,
               f"Seite {breite[0]} px, Fenster {breite[1]} px")
        aufnahme("06_schmal_kurzstatus")
        cdp.js("document.getElementById('ai-kurzstatus').click(); true")
        time.sleep(0.4)
        offen = cdp.js("getComputedStyle(document.getElementById('ai-erkannt')).display !== 'none'")
        pruefe("Schmal: Erkenntnisse klappen auf", offen)
        aufnahme("07_schmal_aufgeklappt")

        js_fehler = cdp.js("window.__fehler")
        pruefe("Keine JavaScript-Fehler", not js_fehler, "; ".join(js_fehler or []))
        protokoll["modellaufrufe"] = modell.aufrufe
    finally:
        chrome.terminate()
        server.shutdown()
    (ziel / "pruefprotokoll.json").write_text(json.dumps(protokoll, ensure_ascii=False, indent=2),
                                             encoding="utf-8")
    fehl = [p for p in protokoll["pruefungen"] if not p["ok"]]
    print(f"\n{len(protokoll['pruefungen']) - len(fehl)} von {len(protokoll['pruefungen'])} "
          f"Prüfungen bestanden. Bilder und Protokoll: {ziel}")
    return 1 if fehl else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else
                  WURZEL / "docs" / "adaptives_interview" / "nachweis"))
