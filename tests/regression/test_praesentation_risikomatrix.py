"""Risikomatrix der Präsentation: jedes bewertete Risiko steht in der Matrix.

Befund auf dev (15.10.2026, Testlauf «Einwohnerdienste»): 6 Risiken in der
Tabelle, nur 4 in der Matrix. Der bisherige Ablauf legte die Bewertungen als
nackte Zahlen ab («2», «1»). Die Word-Datei trug diese Zahlen statt der Werte
der Vorlage, der Präsentations-Parser kannte sie nicht und riet über die
Risikozahl – eindeutig nur bei 4 (2×2), nicht bei 3 oder 2. Zwei Risiken
fielen deshalb aus der Matrix.
"""
from app.domains.praesentation.parser import _stufe, parse_pia
from tests.regression.adaptiv_hilfen import app  # noqa: F401

RISIKEN = [
    {"beschreibung": f"Risiko {i}", "ew": ew, "ag": ag, "massnahmen": "M",
     "verantwortung": "PL", "termin": "laufend"}
    for i, (ew, ag) in enumerate([("2", "2"), ("2", "2"), ("2", "2"), ("2", "2"),
                                  ("1", "3"), ("1", "2")], 1)
]


def test_nackte_stufen_werden_gelesen():
    assert [_stufe(x) for x in ("1", "2", "3", "Niedrig = 1", "Tief")] == [1, 2, 3, 1, 1]


def test_alle_sechs_risiken_kommen_in_die_matrix(app):
    buf = app.generation_service.generate(
        "hermes_pia", {"risiken": {"extracted": RISIKEN}}, {"projektname": "Test"})
    risiken = parse_pia(buf.getvalue())["risiken"]
    assert len(risiken) == 6
    platzierbar = [r for r in risiken if r.get("ew") and r.get("ag")]
    assert len(platzierbar) == 6
    assert [(r["ew"], r["ag"]) for r in risiken][-2:] == [(1, 3), (1, 2)]
    # Die Spalten verrutschen nicht mehr (vorher stand der Termin bei den Massnahmen).
    assert all(r["massnahmen"] == "M" for r in risiken)


def test_word_datei_traegt_die_werte_der_vorlage(app):
    import io

    from docx import Document
    buf = app.generation_service.generate(
        "hermes_pia", {"risiken": {"extracted": RISIKEN}}, {"projektname": "Test"})
    d = Document(io.BytesIO(buf.getvalue()))
    from lxml import etree  # noqa: F401
    text = d.element.body.xml
    assert "Niedrig = 1" in text and "Mittel = 2" in text and "Hoch = 3" in text
