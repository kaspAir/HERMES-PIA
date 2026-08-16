"""Anfragebezogener Pseudonymisierungs-Kontext (Mandant + Projekt).

Der `LLMClient` wird einmal beim App-Start erzeugt und kennt keinen Anfrage-
kontext. Mandant und Projekt gehoeren aber je Aufruf mitgegeben (ANBINDUNG.md 6.3).

Sie durch die gesamte Extraktionskette zu reichen haette rund zwanzig Signaturen
im PIA-Kern veraendert -- an Code, der laeuft und nicht angefasst werden soll.
Stattdessen ein `ContextVar`: er ist pro Thread UND pro asynchronem Task getrennt,
kann also zwischen parallelen Anfragen NICHT lecken -- anders als ein Attribut auf
dem gemeinsamen Client.

    with pseudo_kontext(projekt=session.id, mandant=org_id):
        ...beliebig tief verschachtelte LLM-Aufrufe...

Ist kein Kontext gesetzt, greifen die Vorgaben des Clients. Ein LEERER Mandant
fuehrt im Dienst bewusst zu HTTP 400 -- es gibt keinen Standard-Mandanten, damit
ein Vertipper nicht dazu fuehrt, dass Zuordnungen im falschen Topf landen.
"""
from contextlib import contextmanager
from contextvars import ContextVar

_projekt = ContextVar("pseudo_projekt", default="")
_mandant = ContextVar("pseudo_mandant", default="")


def aktueller_kontext():
    """(projekt, mandant) -- leere Zeichenketten, wenn nichts gesetzt ist."""
    return _projekt.get(), _mandant.get()


@contextmanager
def pseudo_kontext(projekt=None, mandant=None):
    marken = setze_kontext(projekt, mandant)
    try:
        yield
    finally:
        loese_kontext(marken)


# Fuer Aufrufer, die keinen `with`-Block aufspannen koennen -- namentlich Flasks
# before_request/teardown_request. Die Marken MUESSEN zurueckgegeben werden,
# sonst traegt der naechste Aufruf auf demselben Thread den alten Mandanten.
def setze_kontext(projekt=None, mandant=None):
    return (_projekt.set(str(projekt) if projekt else _projekt.get()),
            _mandant.set(str(mandant) if mandant else _mandant.get()))


def loese_kontext(marken):
    t_p, t_m = marken
    _projekt.reset(t_p)
    _mandant.reset(t_m)


def projekt_schluessel(view_args):
    """Konsistenzrahmen aus den Routenparametern ableiten.

    Bewusst das PROJEKT vor der Session: dieselbe Person soll im PIA und in der
    daraus abgeleiteten Rechtsgrundlagenanalyse denselben Platzhalter bekommen.
    Nur wenn kein Projekt in der Route steht, traegt die Session den Rahmen.
    """
    if not view_args:
        return ""
    for schluessel, praefix in (("projekt_id", "projekt"),
                                ("session_id", "session")):
        wert = view_args.get(schluessel)
        if wert:
            return f"{praefix}-{wert}"
    return ""
