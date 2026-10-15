"""Migration bei gleichzeitig startenden Workern.

Auf dev starten zehn Gunicorn-Worker gleichzeitig; jeder führt create_app und
damit die Migration aus. Am 15.10.2026 legten zwei Worker dieselbe neue Spalte
an, einer scheiterte an «duplicate column name», und die Stufe startete nicht.
Dieser Test stellt den Fall nach: Schema VOR dem adaptiven Interview (neue
Spalten und Tabellen entfernt), zehn Prozesse gleichzeitig.

Die Sperre ist eine POSIX-Dateisperre (wie auf dem Server); unter Windows wird
der Test übersprungen.
"""
import sqlite3
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

WURZEL = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(sys.platform.startswith("win"),
                                reason="POSIX-Dateisperre; läuft unter Linux (CI, Server)")

START = textwrap.dedent("""
    import sys
    sys.path.insert(0, {wurzel!r})
    from app.config import Config
    from app.factory import create_app
    class Cfg(Config):
        DATABASE_URL = "sqlite:///" + {db!r}
        SECRET_KEY = "x"
    create_app(Cfg)
""")

NEU = {
    "interview_session": {"modus", "revision", "naechste_aktion_json", "ausstehend_json",
                          "pia_status", "rag_stand_json", "answers_vor_umstellung_json"},
    "corpus_chunks": {"extern_freigegeben", "dokument_hash", "chunk_nr", "methodenversion",
                      "methodenversion_herkunft", "korpus_version"},
}
NEUE_TABELLEN = ("pia_nachricht", "pia_aussage", "pia_konflikt", "pia_rag_thema", "pia_rueckmeldung")


def _starte(db, anzahl):
    skript = START.format(wurzel=str(WURZEL), db=str(db))
    prozesse = [subprocess.Popen([sys.executable, "-c", skript], stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True) for _ in range(anzahl)]
    return [(p.returncode, err) for p, (out, err) in
            ((p, p.communicate(timeout=180)) for p in prozesse)]


def _auf_altes_schema(db):
    con = sqlite3.connect(db)
    for tabelle, neu in NEU.items():
        spalten = [r[1] for r in con.execute(f"PRAGMA table_info({tabelle})") if r[1] not in neu]
        liste = ", ".join(spalten)
        con.execute(f"CREATE TABLE _alt AS SELECT {liste} FROM {tabelle}")
        con.execute(f"DROP TABLE {tabelle}")
        con.execute(f"ALTER TABLE _alt RENAME TO {tabelle}")
    for t in NEUE_TABELLEN:
        con.execute(f"DROP TABLE IF EXISTS {t}")
    con.commit()
    con.close()


def test_zehn_gleichzeitige_starts_migrieren_ohne_fehler(tmp_path):
    db = tmp_path / "stufe.db"
    assert _starte(db, 1)[0][0] == 0                  # heutiges Schema anlegen
    _auf_altes_schema(db)
    ergebnisse = _starte(db, 10)
    fehler = [err for code, err in ergebnisse if code != 0]
    assert not fehler, "\n".join(z for z in fehler[0].splitlines() if "Error" in z)[-800:]
    con = sqlite3.connect(db)
    for tabelle, neu in NEU.items():
        assert neu <= {r[1] for r in con.execute(f"PRAGMA table_info({tabelle})")}
    tabellen = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert set(NEUE_TABELLEN) <= tabellen
