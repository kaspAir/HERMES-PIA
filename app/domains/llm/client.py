"""Anbindung an die Anthropic Messages API -- ueber die Pseudonymisierungsschicht.

HERMES PIA besitzt bewusst KEINEN eigenen Anbieterschluessel mehr. Der liegt im
Pseudonymisierungsdienst; damit ist das Umgehen der Schicht nicht nur verboten,
sondern unmoeglich (ANBINDUNG.md 6.4). Am JSON aendert sich nichts -- der Dienst
spricht die Anbieter-API selbst, es wechselt nur die Basis-URL.

Mandant und Projekt gehoeren je Aufruf mitgegeben. Der Client wird einmal beim
App-Start erzeugt und kennt keinen Anfragekontext; deshalb bindet `fuer(...)`
einen leichten, kurzlebigen Ableger je Session. Den Kontext auf dem gemeinsamen
Client zu setzen waere falsch -- er wuerde zwischen parallelen Anfragen lecken.
"""
import logging

import requests

from app.domains.llm.kontext import aktueller_kontext
from app.domains.llm.errors import (
    PseudoAnbieterFehler,
    PseudoAntwortUnlesbar,
    PseudoUnerwarteteAntwort,
    PseudoKeinSchluessel,
    PseudoKontextFehlt,
    PseudoNichtErreichbar,
    PseudonymisierungBlockiert,
    RueckersetzungUnvollstaendig,
)

log = logging.getLogger("hermes.llm")


def _text_aus_antwort(data):
    """Liest den Text aus der Anbieterantwort – etwas duldsamer als noetig.

    Erwartet wird die Anthropic-Form (`content` als Liste von Bloecken). Der
    Dienst reicht sie durch, koennte sie aber je nach Fassung leicht anders
    verpacken; deshalb werden auch ein einfacher `text`-Schluessel und eine
    Verschachtelung unter `data`/`message` akzeptiert. Was hier NICHT gefunden
    wird, fuehrt bewusst zu einem Fehler statt zu einer leeren Zeichenkette.
    """
    if isinstance(data, dict):
        inhalt = data.get("content")
        if isinstance(inhalt, list):
            return "".join(b.get("text", "") for b in inhalt if isinstance(b, dict))
        if isinstance(inhalt, str):
            return inhalt
        if isinstance(data.get("text"), str):
            return data["text"]
        for schluessel in ("data", "message", "response"):
            tiefer = data.get(schluessel)
            if isinstance(tiefer, (dict, list)):
                gefunden = _text_aus_antwort(tiefer)
                if gefunden:
                    return gefunden
    elif isinstance(data, list):
        return "".join(_text_aus_antwort(e) for e in data)
    return ""


class LLMClient:
    def __init__(self, basis_url=None, model=None, anwendung="hermes-pia",
                 mandant="standard", projekt=None, timeout=90):
        self.basis_url = (basis_url or "").rstrip("/")
        self.model = model or "claude-sonnet-4-6"
        self.anwendung = anwendung
        self.mandant = mandant or ""
        self.projekt = projekt or ""
        # Grosszuegiger als frueher: der Aufruf durchlaeuft zusaetzlich die
        # Erkennung und die Rueckersetzung.
        self.timeout = timeout
        # Wird je Aufruf gesetzt: 'aktiv' oder 'abgeschaltet' (ANBINDUNG.md 8).
        self.letzter_status = ""

    @property
    def available(self):
        return bool(self.basis_url)

    def fuer(self, projekt=None, mandant=None):
        """Kurzlebiger Ableger mit Anfragekontext -- pro Session, nie geteilt."""
        kind = LLMClient(basis_url=self.basis_url, model=self.model,
                         anwendung=self.anwendung,
                         mandant=mandant or self.mandant,
                         projekt=str(projekt) if projekt else self.projekt,
                         timeout=self.timeout)
        return kind

    def complete(self, system, messages, max_tokens=1024, projekt=None, mandant=None):
        if not self.basis_url:
            raise RuntimeError("PSEUDO_BASIS_URL fehlt - ohne Pseudonymisierungsdienst "
                               "werden keine Projektinhalte an ein LLM gesendet.")
        # Reihenfolge: ausdruecklicher Parameter > Anfragekontext > Vorgabe.
        k_projekt, k_mandant = aktueller_kontext()
        kopf = {
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
            "X-Pseudo-Anwendung": self.anwendung,
            "X-Pseudo-Mandant": str(mandant or k_mandant or self.mandant),
            "X-Pseudo-Projekt": str(projekt or k_projekt or self.projekt),
        }
        try:
            resp = requests.post(
                f"{self.basis_url}/v1/messages",
                headers=kopf,
                json={
                    "model": self.model,
                    "max_tokens": max_tokens,
                    "system": system,
                    "messages": messages,
                },
                timeout=self.timeout,
            )
        except requests.RequestException as e:
            # Kein stiller Ausweichweg zum Anbieter: lieber keine Extraktion als
            # eine ungeschuetzte.
            raise PseudoNichtErreichbar(
                f"Pseudonymisierungsdienst nicht erreichbar ({e.__class__.__name__})."
            ) from e

        self.letzter_status = resp.headers.get("X-Pseudo-Status", "")
        if resp.status_code != 200:
            self._melde_fehler(resp)
        try:
            data = resp.json() or {}
        except ValueError:
            raise PseudoAntwortUnlesbar(
                f"Antwort ist kein JSON: {(resp.text or '')[:200]!r}") from None

        text = _text_aus_antwort(data)
        if not text.strip():
            # NICHT stillschweigend '' zurueckgeben: der Aufrufer wuerde daraus
            # 'Modell lieferte nichts' schliessen und den Rohtext uebernehmen.
            log.warning("Antwort ohne Text. Status=%s, Schluessel=%s",
                        self.letzter_status or "-", sorted(data.keys()))
            raise PseudoAntwortUnlesbar(
                "Die Antwort enthielt keinen Text. Felder der Antwort: "
                f"{sorted(data.keys())}")
        return text

    # ---- Fehlerabbildung -------------------------------------------------- #

    @staticmethod
    def _fehlerkoerper(resp):
        try:
            return (resp.json() or {}).get("error", {}) or {}
        except ValueError:
            return {}

    def _melde_fehler(self, resp):
        fehler = self._fehlerkoerper(resp)
        typ = fehler.get("type", "")
        text = fehler.get("message", "") or f"HTTP {resp.status_code}"

        if resp.status_code == 409 or typ == "pseudonymisierung_blockiert":
            pseudo = fehler.get("pseudo", {}) or {}
            raise PseudonymisierungBlockiert(
                befunde=pseudo.get("befunde", []),
                vorgang_id=pseudo.get("vorgang_id", ""),
                message=text,
            )
        if resp.status_code == 502 or typ == "rueckersetzung_unvollstaendig":
            raise RueckersetzungUnvollstaendig(text)
        if resp.status_code == 400 or typ == "kontext_fehlt":
            raise PseudoKontextFehlt(text)
        if resp.status_code == 503 or typ == "kein_anbieterschluessel":
            raise PseudoKeinSchluessel(text)
        # Der Dienst hat gearbeitet, der ANBIETER hat abgelehnt (z.B. ungueltiger
        # Schluessel im Dienst). Nicht als Pseudonymisierungsproblem darstellen --
        # der Text war zu diesem Zeitpunkt bereits pseudonymisiert.
        if typ == "anbieter_fehler" or resp.status_code == 401:
            anbieter = fehler.get("anbieter_antwort", {}) or {}
            innen = anbieter.get("error", {}) if isinstance(anbieter, dict) else {}
            raise PseudoAnbieterFehler(
                meldung=text,
                anbieter_meldung=(innen.get("message", "") if isinstance(innen, dict) else ""),
                status=resp.status_code,
            )
        # Alles Uebrige (404, 401, 405, 500, 501 …) MUSS ebenfalls als PseudoFehler
        # herauskommen. Ein requests.HTTPError waere kein PseudoFehler und liefe
        # in den generischen Faenger der Extraktion -- still zurueck zum Rohtext.
        log.warning("Unerwartete Antwort: HTTP %s auf %s/v1/messages. Rumpf: %.300r",
                    resp.status_code, self.basis_url, resp.text or "")
        raise PseudoUnerwarteteAntwort(resp.status_code, resp.text)
