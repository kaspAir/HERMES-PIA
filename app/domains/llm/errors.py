"""Fehler der Pseudonymisierungsschicht.

Eigene Klassen, damit sie an den generischen `except Exception:`-Faengern der
Extraktion VORBEI nach oben durchschlagen. Wuerden sie dort verschluckt, saehe
der Nutzer nur ein schlechteres Ergebnis und erfuehre nie, dass sein Aufruf
angehalten wurde -- die Begruendungspflicht waere ausgehebelt (ANBINDUNG.md 6.2).
"""


class PseudoFehler(Exception):
    """Basis: alles, was die Schicht meldet und was NICHT verschluckt werden darf."""


class PseudonymisierungBlockiert(PseudoFehler):
    """HTTP 409 -- es ging nichts an den Anbieter, der Nutzer muss entscheiden."""

    def __init__(self, befunde, vorgang_id="", message=""):
        self.befunde = befunde or []
        self.vorgang_id = vorgang_id
        super().__init__(message or f"{len(self.befunde)} Fundstelle(n) erfordern eine Entscheidung.")


class RueckersetzungUnvollstaendig(PseudoFehler):
    """HTTP 502 -- Schutzabschaltung, KEIN Netzwerkfehler.

    Der Dienst liefert lieber einen Fehler als einen Text, in dem ein Platzhalter
    falsch aufgeloest wurde. Nicht stillschweigend wiederholen, kein Text uebernehmen.
    """


class PseudoKontextFehlt(PseudoFehler):
    """HTTP 400 -- Kopfzeile fehlt oder Anwendung unbekannt. Konfigurationsfehler."""


class PseudoKeinSchluessel(PseudoFehler):
    """HTTP 503 -- fuer diese Anwendung ist im Dienst kein Anbieterschluessel hinterlegt."""


class PseudoUnerwarteteAntwort(PseudoFehler):
    """Ein Statuscode, den die Spezifikation nicht vorsieht (404, 401, 405, 500 …).

    Frueher endete `_melde_fehler` mit `resp.raise_for_status()`. Das wirft einen
    `requests.HTTPError` -- KEINEN PseudoFehler. Er lief damit in den generischen
    `except Exception:` der Extraktion und wurde verschluckt: kein Fehler, keine
    Kosten, kein Hinweis, nur der Rohtext im Dokument.

    Jede Antwort ungleich 200 muss deshalb als PseudoFehler herauskommen, auch
    eine unerwartete. Was hier ankommt, ist fast immer ein Konfigurationsfehler
    (falscher Pfad, Anwendung nicht registriert) und gehoert dem Betrieb gesagt.
    """

    def __init__(self, status, koerper=""):
        self.status = status
        self.koerper = (koerper or "")[:300]
        super().__init__(
            f"Unerwartete Antwort des Pseudonymisierungsdienstes: HTTP {status}."
            + (f" Rumpf: {self.koerper!r}" if self.koerper else ""))


class PseudoAntwortUnlesbar(PseudoFehler):
    """HTTP 200, aber es liess sich kein Text aus der Antwort lesen.

    Frueher gab der Client in diesem Fall '' zurueck. Der Aufrufer hielt das fuer
    eine unbrauchbare Modellantwort und uebernahm STILL den Rohtext -- der
    Projektleiter sah sein Diktat unveraendert im Dokument und konnte nicht
    erkennen, dass gar nichts formuliert worden war. Dieselbe Fehlerklasse wie
    die Falle in ANBINDUNG.md 6.2, nur eine Ebene tiefer: lieber sichtbar kaputt
    als still falsch.
    """


class PseudoNichtErreichbar(PseudoFehler):
    """Der Dienst antwortet nicht.

    Bewusst ein harter Fehler: faellt die Schicht aus, darf NICHT still am Dienst
    vorbei zum Anbieter gesendet werden. Lieber keine Extraktion als eine ungeschuetzte.
    """
