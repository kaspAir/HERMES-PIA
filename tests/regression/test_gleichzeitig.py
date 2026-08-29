"""Beweist: mehrere Prozesse dürfen gleichzeitig in die Datenbank schreiben.

Solange dev mit EINEM Worker lief, konnte gleichzeitiges Schreiben gar nicht
vorkommen — und deshalb stand hier nichts. Mit mehreren Workern ist es der
Normalfall: das Interview schreibt bei jeder Antwort, die Kette bei jedem
Schritt, der Testlauf bei jedem Protokolleintrag.

SQLite bringt von Haus aus `journal_mode=delete` mit (ein Schreiber sperrt alle
Leser) und wartet nur 5 s auf eine Sperre. Danach fliegt «database is locked» —
mitten in einem Interview, das eine Stunde Arbeit war.
"""
import os
import sqlite3
import threading

from sqlalchemy import text

from app.shared.database import init_engine


def _erzeuge(pfad):
    engine = init_engine("sqlite:///" + str(pfad).replace("\\", "/"))
    with engine.begin() as c:
        c.execute(text("CREATE TABLE probe (id INTEGER PRIMARY KEY, wert TEXT)"))
    return engine


def test_die_datenbank_steht_auf_gleichzeitigkeit(tmp_path):
    """WAL und ein echtes Wartelimit — beide nötig, keines reicht allein."""
    engine = _erzeuge(tmp_path / "a.db")
    with engine.connect() as c:
        assert c.execute(text("PRAGMA journal_mode")).scalar() == "wal"
        assert c.execute(text("PRAGMA busy_timeout")).scalar() == 30000


def test_lesen_waehrend_geschrieben_wird(tmp_path):
    """Mit dem voreingestellten «delete»-Journal sperrt ein offener Schreib-
    vorgang JEDEN Leser aus. Unter WAL läuft beides nebeneinander."""
    pfad = tmp_path / "b.db"
    engine = _erzeuge(pfad)

    # Ein Schreibvorgang, der offen bleibt – wie ein Worker mitten im Commit.
    schreiber = engine.connect()
    trans = schreiber.begin()
    schreiber.execute(text("INSERT INTO probe (wert) VALUES ('offen')"))
    try:
        # Ein ZWEITER Prozess-artiger Zugang, der gleichzeitig lesen will.
        leser = sqlite3.connect(str(pfad), timeout=5)
        assert leser.execute("SELECT count(*) FROM probe").fetchone()[0] == 0
        leser.close()
    finally:
        trans.commit()
        schreiber.close()

    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM probe")).scalar() == 1


def test_viele_schreiber_verlieren_nichts(tmp_path):
    """Zehn gleichzeitige Schreiber – so viele, wie dev jetzt Worker hat.

    Ohne Wartelimit bricht das mit «database is locked» ab, und die Zählung
    unten bleibt unter 10. Das ist der eigentliche Beweis: es geht nicht darum,
    dass es schnell ist, sondern dass nichts verloren geht.
    """
    pfad = tmp_path / "c.db"
    engine = _erzeuge(pfad)
    fehler = []

    def schreibe(nr):
        try:
            # Eigene Verbindung je Thread – wie ein eigener Worker-Prozess.
            with engine.begin() as c:
                c.execute(text("INSERT INTO probe (wert) VALUES (:w)"),
                          {"w": f"worker-{nr}"})
        except Exception as e:      # noqa: BLE001 – der Grund gehört in den Bericht
            fehler.append(f"{e.__class__.__name__}: {e}")

    faeden = [threading.Thread(target=schreibe, args=(i,)) for i in range(10)]
    for f in faeden:
        f.start()
    for f in faeden:
        f.join(timeout=60)

    assert not fehler, f"Schreibfehler: {fehler[:3]}"
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM probe")).scalar() == 10


def test_ohne_die_einstellungen_faellt_es_auseinander(tmp_path):
    """Die Gegenprobe: dieselbe Lage OHNE WAL und mit kurzem Wartelimit.

    Sie belegt, dass die beiden Einstellungen etwas tun — sonst wäre der Test
    oben grün, weil das Problem nie bestand, und niemand wüsste es."""
    pfad = str(tmp_path / "d.db")
    anlage = sqlite3.connect(pfad)
    anlage.execute("PRAGMA journal_mode=delete")
    anlage.execute("CREATE TABLE probe (id INTEGER PRIMARY KEY, wert TEXT)")
    anlage.commit()
    anlage.close()

    sperrer = sqlite3.connect(pfad, timeout=30)
    sperrer.execute("BEGIN EXCLUSIVE")
    sperrer.execute("INSERT INTO probe (wert) VALUES ('sperre')")
    try:
        zweiter = sqlite3.connect(pfad, timeout=0.2)
        try:
            zweiter.execute("INSERT INTO probe (wert) VALUES ('zweiter')")
            zweiter.commit()
            gescheitert = False
        except sqlite3.OperationalError as e:
            gescheitert = "locked" in str(e) or "busy" in str(e)
        finally:
            zweiter.close()
    finally:
        sperrer.rollback()
        sperrer.close()

    assert gescheitert, ("Ohne WAL und Wartelimit MUSS der zweite Schreiber "
                         "scheitern – sonst prüft der Test oben nichts.")
    os.path.exists(pfad)
