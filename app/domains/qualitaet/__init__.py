"""Invarianten-Prüfung des PIA (Stufe 1 des Umsetzungs-Briefings).

Setzt die D-Kriterien des Qualitätsmodells als CODE um – reproduzierbar, ohne
Sprachmodell, ohne Halluzinationsrisiko. Die F-Kriterien bleiben Sprache und
kommen später als Skill (Stufe 4).

Eigenes Modul: die Prüfung ist vom Erzeugen getrennt (Briefing, Leitplanken).
"""
from app.domains.qualitaet.modell import (
    DATEN, DOK, HINWEIS, MUSS, VORBEHALT, Befund, Pruefergebnis,
)
from app.domains.qualitaet.pruefung import Pruefkontext, pruefe

__all__ = ["pruefe", "Pruefkontext", "Befund", "Pruefergebnis",
           "MUSS", "VORBEHALT", "HINWEIS", "DATEN", "DOK"]
