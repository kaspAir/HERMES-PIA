"""Kern-Engine Kundenvorlage: Kapitel auslesen + auf HERMES-Abschnitte mappen.

Prüft das Risikostück von Stufe 2 isoliert: erkennt die Engine die Kapitel einer
HERMES-Varianten-Vorlage (umbenannt, umsortiert, mit Zusatzkapiteln) verlässlich?
"""
from io import BytesIO

from docx import Document

from app.config import Config
from app.domains.method.template_structure import (
    build_derived_method,
    extract_headings,
    match_canonical,
)
from app.shared.config_loader import load_method


def _canonical():
    return load_method(Config.METHODS_DIR, "hermes_pia")


def _docx(headings):
    """Baut eine .docx mit den gegebenen (level, text)-Überschriften + etwas Text."""
    doc = Document()
    for level, text in headings:
        doc.add_heading(text, level=level)
        doc.add_paragraph("Platzhaltertext.")
    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


def test_extract_headings_liest_reihenfolge():
    data = _docx([(1, "Ausgangslage"), (1, "Ziele"), (2, "Unterpunkt")])
    heads = extract_headings(data)
    assert [h["text"] for h in heads] == ["Ausgangslage", "Ziele", "Unterpunkt"]
    assert heads[0]["level"] == 1 and heads[2]["level"] == 2


def test_extract_headings_robust_bei_muell():
    assert extract_headings(b"kein zip") == []
    assert extract_headings(b"") == []


def test_match_canonical_exakt_und_umlaut():
    sects = _canonical()["sections"]
    assert match_canonical("Ausgangslage", sects) == "ausgangslage"
    # führende Kapitelnummer wird ignoriert
    assert match_canonical("1 Ausgangslage", sects) == "ausgangslage"
    assert match_canonical("2.1 Ziele der Phase Initialisierung", sects) == "ziele"


def test_match_canonical_synonyme():
    sects = _canonical()["sections"]
    assert match_canonical("Ausgangssituation", sects) == "ausgangslage"
    assert match_canonical("Zielsetzung", sects) == "ziele"
    assert match_canonical("Budget", sects) == "kosten"
    assert match_canonical("Risikoanalyse", sects) == "risiken"


def test_match_canonical_unbekannt_gibt_none():
    sects = _canonical()["sections"]
    assert match_canonical("Datenschutzkonzept", sects) is None
    assert match_canonical("", sects) is None


def test_build_derived_erkennt_umbenannte_und_umsortierte_kapitel():
    # HERMES-Variante: umbenannt (Ausgangssituation/Zielsetzung/Budget),
    # umsortiert (Risiken vor Kosten) und ein Zusatzkapitel.
    data = _docx([
        (1, "Ausgangssituation"),
        (1, "Zielsetzung"),
        (1, "Datenschutzkonzept"),   # Zusatzkapitel -> generisch
        (1, "Risikoanalyse"),
        (1, "Budget"),
    ])
    method, report = build_derived_method(data, _canonical())

    reihenfolge = [s["id"] for s in method["sections"]]
    # Struktur der Vorlage bestimmt die Reihenfolge (Risiken vor Kosten!)
    assert reihenfolge == [
        "ausgangslage", "ziele", "custom_datenschutzkonzept", "risiken", "kosten",
    ]
    assert [m["section_id"] for m in report["matched"]] == \
        ["ausgangslage", "ziele", "risiken", "kosten"]
    assert report["generic"][0]["section_id"] == "custom_datenschutzkonzept"

    # Erkannte Kapitel behalten die volle kanonische Definition (Intelligenz!)
    kosten = next(s for s in method["sections"] if s["id"] == "kosten")
    assert kosten["type"] == "table"
    # Generisches Kapitel ist Fliesstext mit abgeleiteten Fragen
    ds = next(s for s in method["sections"] if s["id"] == "custom_datenschutzkonzept")
    assert ds["type"] == "free_text" and ds["generic"] is True
    assert len(ds["interview"]["questions"]) >= 1


def test_build_derived_meldet_fehlende_kanonische_kapitel():
    data = _docx([(1, "Ausgangslage"), (1, "Ziele")])
    _, report = build_derived_method(data, _canonical())
    # In der Vorlage fehlende Pflicht-/Inhaltskapitel werden gemeldet
    assert "risiken" in report["missing_canonical"]
    assert "personalaufwand" in report["missing_canonical"]
    assert "ausgangslage" not in report["missing_canonical"]


def test_container_und_strukturueberschriften_werden_uebersprungen():
    # Nachbildung der echten HERMES-Struktur: Titel, Inhaltsverzeichnis,
    # Container-L1 ("Einleitung", "Ressourcenbedarf") mit L2-Inhaltskapiteln,
    # Protokoll am Schluss.
    data = _docx([
        (1, "Projektinitialisierungsauftrag"),   # Dokumenttitel
        (1, "Inhaltsverzeichnis"),               # strukturell
        (1, "Einleitung"),                       # Container (nächstes L2)
        (2, "Referenzierte Dokumente"),
        (1, "Ausgangslage"),
        (1, "Ressourcenbedarf"),                 # Container
        (2, "Personalaufwand"),
        (2, "Kosten (in CHF inkl. MwSt.)"),
        (1, "Risiken"),
        (1, "Dokument-Protokoll"),               # strukturell
    ])
    method, report = build_derived_method(data, _canonical())
    ids = [s["id"] for s in method["sections"]]

    assert ids == [
        "referenzierte_dokumente", "ausgangslage",
        "personalaufwand", "kosten", "risiken",
    ]
    # Weder Titel/Verzeichnis/Protokoll noch Container werden zu Kapiteln
    assert report["generic"] == []
    uebersprungen = {s["heading"] for s in report["skipped"]}
    assert {"Projektinitialisierungsauftrag", "Inhaltsverzeichnis",
            "Einleitung", "Ressourcenbedarf", "Dokument-Protokoll"} <= uebersprungen


def test_build_derived_nutzt_question_gen_mit_fallback():
    data = _docx([(1, "Spezialkapitel")])

    # LLM-Ersatz liefert eigene Fragen
    method, _ = build_derived_method(
        data, _canonical(), question_gen=lambda t: [f"Frage zu {t}?"])
    sec = method["sections"][0]
    assert sec["interview"]["questions"] == ["Frage zu Spezialkapitel?"]

    # Fällt der Generator aus, greift der deterministische Fallback
    method2, _ = build_derived_method(
        data, _canonical(), question_gen=lambda t: (_ for _ in ()).throw(RuntimeError()))
    assert len(method2["sections"][0]["interview"]["questions"]) >= 1
