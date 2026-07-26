"""Beweist: die Betriebsskripte sind syntaktisch gesund.

Auslöser (26.07.2026): eine Kommentarzeile MITTEN in einem mit `\` fortgesetzten
gunicorn-Aufruf hat den gesamten Rest des Befehls auskommentiert – `--timeout`,
die Logdateien, die Ausgabeumleitung und das abschliessende `&`. Folgen:

  * gunicorn lief im VORDERGRUND → der Deploy-SSH kam nie zurück → der
    Jenkins-Lauf hing bis zum 20-Minuten-Timeout und wurde abgebrochen.
  * gunicorn lief mit seinem STANDARD-Timeout von 30 s statt der 300 s aus dem
    Skript → jeder Prüfschritt über 30 s riss den Worker, was in der Anwendung
    wie eine geheimnisvolle Hosting-Grenze aussah.

Der Fehler ist im Shell-Skript unsichtbar (kein Syntaxfehler) und kostete
Stunden an der falschen Stelle. Diese Tests fangen ihn beim Bauen ab.
"""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from app.config import BASE_DIR

SKRIPTE = sorted(Path(BASE_DIR, "deploy").glob("*.sh"))


def test_es_gibt_ueberhaupt_skripte():
    assert SKRIPTE


@pytest.mark.parametrize("pfad", SKRIPTE, ids=lambda p: p.name)
def test_kein_kommentar_in_einer_fortgesetzten_zeile(pfad):
    """`... \` + nächste Zeile beginnt mit `#` → der Rest des Befehls ist weg."""
    zeilen = pfad.read_text(encoding="utf-8").splitlines()
    for nr, zeile in enumerate(zeilen[:-1], start=1):
        if not zeile.rstrip().endswith("\\"):
            continue
        naechste = zeilen[nr].strip()
        assert not naechste.startswith("#"), (
            f"{pfad.name}:{nr + 1} – Kommentar in einer mit \ fortgesetzten "
            f"Zeile. Alles danach wird stillschweigend auskommentiert. "
            f"Kommentar VOR den Befehl setzen."
        )


@pytest.mark.parametrize("pfad", SKRIPTE, ids=lambda p: p.name)
def test_shell_syntax_ist_gueltig(pfad):
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("bash nicht verfügbar")
    p = subprocess.run([bash, "-n", str(pfad)], capture_output=True, text=True)
    assert p.returncode == 0, p.stderr


def test_gunicorn_startet_im_hintergrund_und_mit_zeitlimit():
    """Die drei Eigenschaften, die der auskommentierte Rest mitgenommen hat."""
    text = Path(BASE_DIR, "deploy", "hermes_ctl.sh").read_text(encoding="utf-8")
    m = re.search(r"nohup gunicorn run:app(.*?)\n\s*echo \$!", text, re.DOTALL)
    assert m, "gunicorn-Startbefehl nicht gefunden"
    befehl = m.group(1)
    assert "--timeout" in befehl, "ohne --timeout gilt gunicorns Standard von 30 s"
    assert "--error-logfile" in befehl, "ohne Logdatei ist eine Störung nicht lesbar"
    assert befehl.rstrip().endswith("&"), (
        "ohne & laeuft gunicorn im Vordergrund – der Deploy-SSH kehrt nie zurück")
