"""Beweist: das Versionsabzeichen zeigt die Version, die wirklich läuft.

Gemessener Ausfall: das Abzeichen meldete «HERMES PIA V0.29.0 · 74bfbab»,
während der Code von V0.32.1 lief. Der SHA stimmte, die Produktversion nicht.

Die Ursache war keine Fehlfunktion, sondern eine zweite Quelle: die Nummer
stand als von Hand gepflegte Konstante im Quelltext UND als Marker in der
Commit-Nachricht. Vier Freigaben lang wurde nur die Nachricht gepflegt. Das
Abzeichen zeigte getreu, was im Quelltext stand – nur war das nicht die
Wahrheit.

Das Abzeichen ist die einzige Stelle, an der jemand ablesen kann, welcher
Stand läuft. Zeigt es die falsche Zahl, ist jede Prüfung «ist der Fehler
behoben?» wertlos.
"""
from app.shared.version import PRODUCT_VERSION, produktversion_aus


def test_der_marker_wird_aus_der_commit_nachricht_gelesen():
    assert produktversion_aus(
        ["fix(docx): Vorlage-Hyperlink ueberschrieb keinen Text mehr + V0.32.1"]
    ) == "0.32.1"


def test_die_juengste_nachricht_gewinnt():
    """`git log` liefert absteigend – die erste Zeile ist die neueste."""
    assert produktversion_aus([
        "feat(freigabe): Phase eroeffnet + V0.32.0",
        "fix(pia): Pflichtrollen + V0.31.0",
        "feat(ux): Leitfrage + V0.30.0",
    ]) == "0.32.0"


def test_zwischencommits_ohne_marker_werden_uebersprungen():
    """Nicht jede Änderung ist eine Freigabe – dann gilt die letzte davor."""
    assert produktversion_aus([
        "docs: Kommentar praezisiert",
        "chore: Tippfehler",
        "feat(freigabe): Phase eroeffnet + V0.32.0",
    ]) == "0.32.0"


def test_ohne_marker_bleibt_es_leer():
    """Leer heisst: der Rückfallwert greift – nicht: irgendeine Zahl raten."""
    assert produktversion_aus(["chore: nichts freigegeben"]) == ""
    assert produktversion_aus([]) == ""
    assert produktversion_aus(None) == ""


def test_eine_versionsaehnliche_zahl_ohne_V_zaehlt_nicht():
    """«HERMES 2022» oder «Python 3.9.2» sind keine Produktversionen."""
    assert produktversion_aus(["chore: HERMES 2022 verankert"]) == ""
    assert produktversion_aus(["chore: Python 3.9.2 geprueft"]) == ""


def test_der_rueckfallwert_ist_eine_gueltige_nummer():
    """Ohne Git-Repo wird er angezeigt – dann muss er wenigstens Form haben."""
    teile = PRODUCT_VERSION.split(".")
    assert len(teile) == 3 and all(t.isdigit() for t in teile)


def test_das_abzeichen_erscheint_auf_jeder_seite():
    from pathlib import Path

    from app.config import BASE_DIR

    vorlage = Path(BASE_DIR, "app", "templates", "base.html").read_text(encoding="utf-8")
    assert "app_version.product" in vorlage
    assert "app_version.sha" in vorlage
