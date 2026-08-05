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

def test_die_interview_sitzung_schlaegt_das_dokument():
    """Wer in HERMES PIA arbeitet, hat den aktuelleren Stand; ein
    hochgeladenes Dokument ist ein Abzug von irgendwann."""
    sitzung = _Sitzung({"ausgangslage": {"extracted": {"text": "aus dem Interview"}}})
    a, herkunft = pia_quelle.projektwissen_quelle(
        session=sitzung, dokument_bytes=b"x", parser=lambda b: _GEPARST)
    assert herkunft == "interview"
    assert a["ausgangslage"]["extracted"]["text"] == "aus dem Interview"


def test_ohne_sitzung_traegt_das_dokument():
    a, herkunft = pia_quelle.projektwissen_quelle(
        session=None, dokument_bytes=b"x", parser=lambda b: _GEPARST)
    assert herkunft == "dokument"
    assert a["ausgangslage"]["extracted"]["text"].startswith("Der Kanton")


def test_leere_sitzung_zaehlt_nicht_als_quelle():
    a, herkunft = pia_quelle.projektwissen_quelle(
        session=_Sitzung(), dokument_bytes=b"x", parser=lambda b: _GEPARST)
    assert herkunft == "dokument" and a


def test_ohne_beides_bleibt_es_leer_ohne_absturz():
    assert pia_quelle.projektwissen_quelle() == ({}, "")


def test_ein_kaputtes_dokument_wirft_nichts_um():
    """Ein unlesbarer Upload darf den Lauf nicht beenden – er ist einfach
    keine Quelle."""
    def kaputt(daten):
        raise ValueError("kein gültiges Word-Dokument")

    assert pia_quelle.projektwissen_quelle(
        dokument_bytes=b"x", parser=kaputt) == ({}, "")


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
