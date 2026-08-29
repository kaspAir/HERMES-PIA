"""Führt die OFFLINE-Grundwahrheitsfälle in der Testsuite mit.

Die 900 übrigen Tests prüfen, ob der Code tut, was er soll. Sie sagen nichts
darüber, ob das ERGEBNIS stimmt — und genau dort lagen die Fehler der letzten
Wochen. Sie fielen auf, weil ein Mensch ein Dokument anschaute, nicht weil
etwas rot wurde.

Die Online-Fälle laufen hier NICHT mit: sie fragen die amtlichen Sammlungen und
gehören nicht in eine Suite, die bei jedem Commit läuft. Sie werden auf Abruf
geprüft:

    python tools/grundwahrheit.py

Diese Trennung ist die eigentliche Entscheidung. Nähme man die Online-Fälle
hinein, würde die Suite bei jeder Netzstörung rot und wäre nach einer Woche
abgeschaltet — und die Prüfung, die den Kontakt zur Welt hält, wäre weg.
"""
import sys
from pathlib import Path

import pytest

from app.config import BASE_DIR

sys.path.insert(0, str(Path(BASE_DIR)))
from tools.grundwahrheit import lade_dateien, laufe   # noqa: E402


def test_offline_faelle_erreichen_ihre_sollwerte():
    zeilen, abweichungen, geprueft = laufe("offline")
    schlimm = [t for art, t in zeilen if art in ("abweichung", "fehler")]
    assert not schlimm, "\n".join(schlimm)
    assert geprueft > 0, "es wurde kein einziger Fall geprüft"


def test_jede_falldatei_nennt_ihre_art():
    """«offline» oder «online» – ohne die Angabe liefe ein Netzfall in der Suite."""
    for name, daten in lade_dateien():
        assert daten.get("art") in ("offline", "online"), name


def test_jeder_fall_traegt_eine_erwartung():
    """Ein Fall ohne Sollwert prüft nichts – er dokumentiert nur einen Lauf."""
    for name, daten in lade_dateien():
        for fall in daten.get("faelle") or []:
            assert fall.get("name"), f"{name}: Fall ohne Namen"
            erwartet = fall.get("erwartet") or {}
            assert erwartet, f"{name}: «{fall.get('name')}» ohne Erwartung"
            assert any(erwartet.get(k) for k in
                       ("zustand", "muss_melden", "darf_nicht_melden")), \
                f"{name}: «{fall['name']}» erwartet nichts Prüfbares"


def test_online_faelle_werden_hier_nicht_ausgefuehrt():
    """Absichtserklärung als Test: die Suite bleibt netzfrei."""
    online = [n for n, d in lade_dateien("online")]
    assert online, "es gibt keine Online-Fälle mehr – wurde etwas gelöscht?"
    zeilen, _, geprueft = laufe("offline")
    namen = " ".join(t for _, t in zeilen)
    assert "fedlex" not in namen.lower()
