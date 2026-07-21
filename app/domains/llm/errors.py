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


class PseudoNichtErreichbar(PseudoFehler):
    """Der Dienst antwortet nicht.

    Bewusst ein harter Fehler: faellt die Schicht aus, darf NICHT still am Dienst
    vorbei zum Anbieter gesendet werden. Lieber keine Extraktion als eine ungeschuetzte.
    """
