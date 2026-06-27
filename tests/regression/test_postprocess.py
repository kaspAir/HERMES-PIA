"""Beweist: deterministische HERMES-Korrekturen nach dem Befüllen eines Abschnitts."""
from app.config import get_config
from app.domains.catalog.service import CatalogService
from app.domains.interview.service import InterviewService
from app.domains.method.service import MethodService


def _svc():
    cfg = get_config()
    return InterviewService(MethodService(cfg.METHODS_DIR), CatalogService(cfg.CATALOGS_DIR), None)


def test_kosten_nur_initialisierung():
    rows = [
        {"phase": "Initialisierung", "betrag": "85000"},
        {"phase": "Konzept", "betrag": "120000"},
        {"phase": "Realisierung", "betrag": "340000"},
        {"phase": "Einführung", "betrag": "95000"},
        {"phase": "Abschluss", "betrag": "25000"},
    ]
    keep = InterviewService._kosten_initialisierung_only(rows)
    assert len(keep) == 1
    assert keep[0]["phase"] == "Initialisierung"
    assert keep[0]["betrag"] == "85000"


def test_kosten_fallback_wenn_keine_initialisierung():
    rows = [{"phase": "Realisierung", "betrag": "340000"}]
    keep = InterviewService._kosten_initialisierung_only(rows)
    assert keep == [{"phase": "Initialisierung", "betrag": ""}]


def test_personalaufwand_ergaenzt_anwendervertreter_und_entwickler():
    rows = [{"rolle": "Projektleiter", "name": "", "aufwand": "15"}]
    answers = {"termine": {"extracted": [
        {"ergebnis": "Beschaffungsanalyse", "abnahme": "Anwendervertreter"},
        {"ergebnis": "Prototyp: SAP", "abnahme": "Entwickler"},
    ]}}
    InterviewService._ensure_deliverable_roles(rows, answers)
    rollen = [r["rolle"] for r in rows]
    assert "Anwendervertreter" in rollen
    assert "Entwickler" in rollen


def test_personalaufwand_keine_dubletten():
    rows = [
        {"rolle": "Anwendervertreter", "name": "", "aufwand": "4"},
        {"rolle": "Entwickler", "name": "", "aufwand": "8"},
    ]
    answers = {"termine": {"extracted": [
        {"ergebnis": "Beschaffungsanalyse", "abnahme": "Anwendervertreter"},
        {"ergebnis": "Prototyp", "abnahme": "Entwickler"},
    ]}}
    InterviewService._ensure_deliverable_roles(rows, answers)
    assert len(rows) == 2  # nichts dupliziert


def test_personalaufwand_keine_zusatzrollen_ohne_ergebnis():
    rows = [{"rolle": "Projektleiter", "name": "", "aufwand": "15"}]
    answers = {"termine": {"extracted": [
        {"ergebnis": "Studie", "abnahme": "Projektleiter"},
    ]}}
    InterviewService._ensure_deliverable_roles(rows, answers)
    assert [r["rolle"] for r in rows] == ["Projektleiter"]


def test_postprocess_kosten_ueber_dispatch():
    svc = _svc()
    section = svc._section_by_id("hermes_pia", "kosten")
    section_answer = {"extracted": [
        {"phase": "Initialisierung", "betrag": "85000"},
        {"phase": "Konzept", "betrag": "120000"},
    ]}
    svc._postprocess_section(section, section_answer, {})
    assert section_answer["extracted"] == [{"phase": "Initialisierung", "betrag": "85000"}]


def test_projektorganisation_spalten_decken_vorlage_ab():
    """Vorlage hat 9 Monate + Bestätigung -> method.yaml muss 1:1 passen,
    sonst rutscht 'ausstehend' in eine Monatsspalte."""
    svc = _svc()
    section = svc._section_by_id("hermes_pia", "projektorganisation")
    cols = [c["id"] for c in section["columns"]]
    assert cols[0] == "rolle_person"
    assert cols[-1] == "bestaetigung"
    assert [f"monat_{i}" for i in range(1, 10)] == cols[1:-1]
