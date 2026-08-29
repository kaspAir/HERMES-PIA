"""Beweist: was je Stufe verschieden sein muss, steht nicht in der geteilten Datei.

`hermes_ctl.sh` lädt für JEDE Stufe dieselbe `~/methodos/.env` (`SHARED_ENV`).
Ein `TESTLAUF=1` dort hätte den Testlauf auf der Kundenumgebung und in der
Produktion gleich mit eingeschaltet — und dort erzeugt er eine freigegebene
Checkliste samt erreichtem Meilenstein, ohne dass ein Mensch geurteilt hat.
Also einen Weg zu Nachweisen, die keine sind.

Die Einstellung gehört deshalb in die Stufenkonfiguration, wo die Stufe schon
bekannt ist. Geprüft wird der Skripttext und nicht sein Verhalten: welche
Datei eine Zeile lädt, sieht man ihr nicht an, und genau daran ist die erste
Fassung dieser Anweisung gescheitert.
"""
import re
from pathlib import Path

import pytest

PFAD = Path(__file__).resolve().parents[2] / "deploy" / "hermes_ctl.sh"

pytestmark = pytest.mark.skipif(not PFAD.exists(), reason="Betriebsskript fehlt")


def _stufenblock(umgebung):
    """Die Zeilen des `case`-Zweigs einer Stufe – ohne Kommentare."""
    text = PFAD.read_text(encoding="utf-8")
    anfang = re.search(rf"^\s*{umgebung}\)", text, re.M)
    assert anfang, f"Kein case-Zweig für «{umgebung}»"
    rest = text[anfang.start():]
    ende = rest.index(";;")
    return "\n".join(z for z in rest[:ende].splitlines()
                     if not z.strip().startswith("#"))


def test_der_testlauf_ist_auf_dev_eingeschaltet():
    assert 'HP_EXTRA_ENV="TESTLAUF=1"' in _stufenblock("dev")


@pytest.mark.parametrize("umgebung", ["prod", "test", "int"])
def test_keine_kundenstufe_schaltet_ihn_ein(umgebung):
    """Auf int arbeitet der Kunde, auf prod läuft der Betrieb."""
    assert "TESTLAUF" not in _stufenblock(umgebung)


def test_jede_stufe_setzt_die_zusatzumgebung_zurueck():
    """Der Watchdog ruft `hp_config` mehrfach im selben Prozess auf — erst dev,
    dann int. Ohne Zurücksetzen trüge int weiter, was für dev gedacht war."""
    text = PFAD.read_text(encoding="utf-8")
    funktion = text[text.index("hp_config()"):]
    funktion = funktion[:funktion.index("\n}")]
    assert re.search(r'HP_EXTRA_ENV=""', funktion.split("case")[0]), (
        "Das Zurücksetzen muss VOR dem case stehen, sonst greift es nicht "
        "für die Zweige, die nichts setzen.")


def test_das_stufenspezifische_kommt_nach_der_geteilten_datei():
    """Sonst könnte die geteilte Datei die Stufeneinstellung übersteuern —
    also genau das, was hier verhindert werden soll."""
    text = PFAD.read_text(encoding="utf-8")
    assert text.index('. "$SHARED_ENV"') < text.index("export $HP_EXTRA_ENV")


def test_die_geteilte_datei_wird_wirklich_von_allen_geladen():
    """Die Gegenprobe zur Begründung: gäbe es je Stufe eine eigene .env, wäre
    die ganze Vorsicht oben unnötig — und dieser Test würde es zeigen."""
    text = PFAD.read_text(encoding="utf-8")
    zeilen = [z for z in text.splitlines() if "SHARED_ENV=" in z
              and not z.strip().startswith("#")]
    assert len(zeilen) == 1, "Es gibt genau EINE gemeinsame Datei für alle Stufen"
    assert "methodos/.env" in zeilen[0]
