"""Beweist: ein akzeptierter Vorschlag landet in den Abschnittsdaten."""
from app.config import get_config
from app.domains.catalog.service import CatalogService
from app.domains.interview.service import InterviewService
from app.domains.method.service import MethodService


def _interview():
    cfg = get_config()
    return InterviewService(MethodService(cfg.METHODS_DIR), CatalogService(cfg.CATALOGS_DIR))


def _risiken_section(svc):
    return svc._section_by_id("hermes_pia", "risiken")


def test_accepted_catalog_risk_is_added_as_row():
    svc = _interview()
    section = _risiken_section(svc)
    assert section is not None

    section_answer = {"extracted": [{"beschreibung": "Beschaffungsrisiko"}]}
    followup = {"risk_id": "r_akzeptanz", "vorschlag": "Geringe Akzeptanz der Anwender"}

    svc._apply_followup(section, section_answer, followup, raw_text=None)

    rows = section_answer["extracted"]
    assert len(rows) == 2
    assert rows[1]["beschreibung"] == "Geringe Akzeptanz der Anwender"


def test_dictated_refinement_overrides_suggestion():
    svc = _interview()
    section = _risiken_section(svc)

    section_answer = {"extracted": []}
    followup = {"risk_id": "r_akzeptanz", "vorschlag": "Geringe Akzeptanz der Anwender"}

    svc._apply_followup(section, section_answer, followup,
                        raw_text="Widerstand der Fachabteilung gegen den neuen Prozess")

    rows = section_answer["extracted"]
    assert len(rows) == 1
    assert rows[0]["beschreibung"] == "Widerstand der Fachabteilung gegen den neuen Prozess"


def test_free_text_followup_appends_to_text():
    svc = _interview()
    section = {"id": "ausgangslage", "type": "free_text"}
    section_answer = {"extracted": {"text": "Bestehender Text."}}
    followup = {"risk_id": "ai_ausgangslage_0", "vorschlag": "Ergaenzender Hinweis."}

    svc._apply_followup(section, section_answer, followup, raw_text=None)

    assert section_answer["extracted"]["text"] == "Bestehender Text.\nErgaenzender Hinweis."
