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
    t_p = _projekt.set(str(projekt) if projekt else _projekt.get())
    t_m = _mandant.set(str(mandant) if mandant else _mandant.get())
    try:
        yield
    finally:
        _projekt.reset(t_p)
        _mandant.reset(t_m)
