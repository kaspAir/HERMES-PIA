"""Beweist: das Projektwissen kommt aus dem Interview ODER aus dem Dokument.

Wer einen anderswo geschriebenen, freigabebereiten PIA hochlädt, konnte daraus
eine Präsentation erzeugen – aber keine Rechtsgrundlagenanalyse. Das war eine
willkürliche Grenze: die Analyse braucht den INHALT, nicht die Herkunft des
Inhalts.
"""
import json

from app.domains.ergebnisse import pia_quelle


class _Sitzung:
    def __init__(self, answers=None):
        self.answers_json = json.dumps(answers, ensure_ascii=False) if answers else None


_GEPARST = {
    "ausgangslage": "Der Kanton beabsichtigt eine Systemablösung.",
    "ziele": [{"beschreibung": "Nachfolgelösung evaluieren"}],
    "rahmenbedingungen": [{"vorgabe": "Beschaffungsrechtliche Vorgaben"}],
    "risiken": [],                       # leer – kein Abschnitt
    "projektname": "Testprojekt",        # Metadatum, kein Abschnitt
}


# ---- Aus dem Dokument ---------------------------------------------------- #

def test_das_dokument_wird_zur_abschnittsstruktur():
    a = pia_quelle.aus_dokument(_GEPARST)
    # Text bleibt Text, Tabellen bleiben Zeilenlisten.
    assert a["ausgangslage"]["extracted"]["text"].startswith("Der Kanton")
    assert a["ziele"]["extracted"] == [{"beschreibung": "Nachfolgelösung evaluieren"}]
    assert a["rahmenbedingungen"]["extracted"][0]["vorgabe"].startswith("Beschaffung")


def test_leere_abschnitte_fallen_weg():
    """Ein leerer Abschnitt ist keine Aussage – nachgelagerte Schritte sollen
    «nicht vorhanden» von «leer» trennen können."""
    a = pia_quelle.aus_dokument(_GEPARST)
    assert "risiken" not in a


def test_metadaten_sind_keine_abschnitte():
    assert "projektname" not in pia_quelle.aus_dokument(_GEPARST)


def test_die_rahmenbedingungen_kommen_mit():
    """Sie trugen im gemessenen Fall das Entscheidende – der Parser las sie,
    gab sie aber nicht zurück."""
    from app.domains.praesentation.parser import parse_pia
    import inspect

    quelle = inspect.getsource(parse_pia)
    assert '"rahmenbedingungen"' in quelle
    assert '"referenzierte_dokumente"' in quelle


# ---- Der Vorrang --------------------------------------------------------- #






def test_unlesbare_sitzung_wirft_nichts_um():
    class _Kaputt:
        answers_json = "{kein json"

    assert pia_quelle.aus_session(_Kaputt()) == {}


# ---- Der Anschluss ------------------------------------------------------- #

def test_die_rechtsgrundlagenanalyse_nutzt_beide_quellen():
    from pathlib import Path

    from app.domains.ergebnisse.rechtsgrundlagen import service as svc_modul
    quelle = Path(svc_modul.__file__).read_text(encoding="utf-8")
    abschnitt = quelle[quelle.index("def _pia(self, projekt)"):
                       quelle.index("def projektwissen(self")]
    assert "latest_dokument" in abschnitt
    assert "projektwissen_quelle" in abschnitt


def test_die_herkunft_wird_mitgefuehrt():
    """Ein Abzug von irgendwann ist etwas anderes als der laufende Stand."""
    from app.domains.ergebnisse.projektwissen import Projektwissen

    w = Projektwissen({})
    w.herkunft = "dokument"
    assert w.herkunft == "dokument"


# ---- Der Vorrang folgt der VERBINDLICHKEIT ------------------------------- #
#
# Eine frühere Fassung liess die Interview-Sitzung gewinnen – mit dem
# Argument, sie sei aktueller. Aktueller ist nicht dasselbe wie massgeblich:
# hochgeladen wird die Fassung, die durch Prüfung und Freigabe gegangen ist,
# und sie kann ausserhalb von HERMES PIA überarbeitet worden sein. Das ist
# der Normalfall.

def test_das_freigegebene_dokument_schlaegt_alles():
    a, herkunft = pia_quelle.projektwissen_quelle(
        session=_Sitzung({"ausgangslage": {"extracted": {"text": "Arbeitsstand"}}}),
        dokumente={"freigegeben": b"F", "freigabe": b"B"},
        parser=lambda b: dict(_GEPARST, ausgangslage=f"aus {b.decode()}"))
    assert herkunft == "freigegeben"
    assert a["ausgangslage"]["extracted"]["text"] == "aus F"


def test_freigabebereit_schlaegt_das_interview():
    a, herkunft = pia_quelle.projektwissen_quelle(
        session=_Sitzung({"ausgangslage": {"extracted": {"text": "Arbeitsstand"}}}),
        dokumente={"freigabe": b"B"},
        parser=lambda b: dict(_GEPARST, ausgangslage="aus dem Dokument"))
    assert herkunft == "freigabe"
    assert a["ausgangslage"]["extracted"]["text"] == "aus dem Dokument"


def test_ohne_dokument_traegt_das_interview():
    a, herkunft = pia_quelle.projektwissen_quelle(
        session=_Sitzung({"ausgangslage": {"extracted": {"text": "Arbeitsstand"}}}))
    assert herkunft == "interview"
    assert a["ausgangslage"]["extracted"]["text"] == "Arbeitsstand"


def test_ohne_alles_bleibt_es_leer_ohne_absturz():
    assert pia_quelle.projektwissen_quelle() == ({}, "")


def test_ein_kaputtes_dokument_laesst_die_naechste_quelle_zu():
    """Ein unlesbarer Upload darf den Lauf nicht beenden – aber auch nicht
    dazu führen, dass etwas erfunden wird. Er ist einfach keine Quelle."""
    def nur_freigabe_lesbar(daten):
        if daten == b"kaputt":
            raise ValueError("kein gültiges Word-Dokument")
        return _GEPARST

    a, herkunft = pia_quelle.projektwissen_quelle(
        dokumente={"freigegeben": b"kaputt", "freigabe": b"gut"},
        parser=nur_freigabe_lesbar)
    assert herkunft == "freigabe" and a


def test_die_herkunft_ist_lesbar_benannt():
    """Sie erscheint im Ergebnis – «freigabe» sagt dem Leser nichts."""
    assert pia_quelle.HERKUNFT_TEXT["freigegeben"] == "freigegebenes Dokument"
    assert set(pia_quelle.HERKUNFT_TEXT) >= set(pia_quelle.DOKUMENTARTEN) | {"interview"}


def test_die_rangfolge_steht_an_EINER_stelle():
    """Der Dienst entscheidet sie nicht – er reicht alle Arten durch."""
    from pathlib import Path

    from app.domains.ergebnisse.rechtsgrundlagen import service as svc_modul
    quelle = Path(svc_modul.__file__).read_text(encoding="utf-8")
    abschnitt = quelle[quelle.index("def _pia(self, projekt)"):
                       quelle.index("def projektwissen(self")]
    assert "for art in pia_quelle.DOKUMENTARTEN" in abschnitt
    assert '"freigabe"' not in abschnitt      # keine zweite Rangfolge im Dienst


def test_die_freigegebene_fassung_kann_hochgeladen_werden():
    from pathlib import Path

    from app.config import BASE_DIR
    v = Path(BASE_DIR, "app", "templates", "projekt_detail.html").read_text(
        encoding="utf-8")
    assert "Freigegebene Fassung hochladen" in v
    assert "art=freigegeben" in v
