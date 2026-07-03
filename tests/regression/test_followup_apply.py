"""Beweist: ein akzeptierter Vorschlag landet in den Abschnittsdaten."""
from app.config import get_config
from app.domains.catalog.service import CatalogService
from app.domains.interview.extraction import analyze_results_options
from app.domains.interview.service import InterviewService
from app.domains.method.service import MethodService


def _interview(llm=None):
    cfg = get_config()
    return InterviewService(MethodService(cfg.METHODS_DIR), CatalogService(cfg.CATALOGS_DIR), llm)


class _ReformLLM:
    """Gibt einen sauber formulierten Text zurück (statt 1:1)."""
    def complete(self, system, messages, max_tokens=1024):
        return '{"text": "Sauber formulierter Behoerdentext."}'


def test_free_text_followup_reformuliert_statt_eins_zu_eins():
    svc = _interview(_ReformLLM())
    section = {"id": "ausgangslage", "type": "free_text", "title": "Ausgangslage"}
    section_answer = {"extracted": {"text": "Bestehender Text."}}
    followup = {"risk_id": "ai_ausgangslage_0", "vorschlag": None, "status": "pending"}
    svc._apply_followup(section, section_answer, followup, raw_text="roh gesprochener Zusatz")
    # Nicht 1:1 angehaengt, sondern durchs LLM reformuliert:
    assert section_answer["extracted"]["text"] == "Sauber formulierter Behoerdentext."
    assert "roh gesprochener" not in section_answer["extracted"]["text"]


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


def test_is_empty_detects_blank_and_filled():
    svc = _interview()
    assert svc._is_empty(None) is True
    assert svc._is_empty([]) is True
    assert svc._is_empty({"text": "  "}) is True
    assert svc._is_empty([{"empfaenger": ""}]) is True
    assert svc._is_empty({"text": "etwas"}) is False
    assert svc._is_empty([{"empfaenger": "Auftraggeber"}]) is False


def test_catalog_suggestion_kommunikation_fallback():
    svc = _interview()
    section = svc._section_by_id("hermes_pia", "kommunikation")
    assert section is not None

    rows = svc._catalog_suggestion("fachanwendung_einfuehrung", section)
    assert rows and len(rows) >= 3
    # Nur Spalten-IDs der method.yaml, keine Katalog-internen Felder wie 'id'/'salience'
    allowed = {c["id"] for c in section["columns"] if c["id"] != "nr"}
    for r in rows:
        assert set(r.keys()) <= allowed
    assert rows[0]["empfaenger"] == "Auftraggeber"


def test_catalog_suggestion_none_when_no_block():
    svc = _interview()
    section = svc._section_by_id("hermes_pia", "sachmittel")
    # Kein 'sachmittel'-Block im Katalog -> kein Fallback
    assert svc._catalog_suggestion("fachanwendung_einfuehrung", section) is None


class _Sess:
    method_id = "hermes_pia"
    project_type_id = "fachanwendung_einfuehrung"
    project_name = "Demo"
    auftraggeber = "Amt X"


class _AnalyzeLLM:
    """Liefert eine Beschaffungs-/Prototyp-Einschätzung als JSON."""
    def complete(self, system, messages, max_tokens=512):
        return (
            '{"beschaffung": {"relevant": true, "frage": "Beschaffung? Ja/Nein"}, '
            '"prototyp": {"relevant": true, "thema": "Suchmaske", '
            '"frage": "Prototyp Suchmaske einplanen?"}}'
        )


def test_analyze_results_options_parst_beide_entscheidungen():
    opts = analyze_results_options(_AnalyzeLLM(), "Wir beschaffen ein neues Fachsystem.")
    assert opts["beschaffung"]["relevant"] is True
    assert opts["beschaffung"]["frage"]
    assert opts["prototyp"]["thema"] == "Suchmaske"


def test_analyze_results_options_ohne_text_oder_llm():
    assert analyze_results_options(_AnalyzeLLM(), "") == {}
    assert analyze_results_options(None, "Text") == {}


def test_decision_followups_bauen_zeilen_mit_abnahme():
    svc = _interview()
    opts = {
        "beschaffung": {"relevant": True, "frage": "Beschaffungsanalyse erstellen?"},
        "prototyp": {"relevant": True, "thema": "Suchmaske", "frage": "Prototyp?"},
    }
    fus = svc._decision_followups(opts, start_datum="2026-01-06")
    assert {f["risk_id"] for f in fus} == {"decision_beschaffung", "decision_prototyp"}
    besch = next(f for f in fus if f["risk_id"] == "decision_beschaffung")
    assert besch["type"] == "decision"
    assert besch["row"]["ergebnis"] == "Beschaffungsanalyse"
    assert besch["row"]["abnahme"] == "Anwendervertreter"
    assert besch["row"]["termin"]  # Liefertermin gesetzt
    proto = next(f for f in fus if f["risk_id"] == "decision_prototyp")
    assert proto["row"]["ergebnis"] == "Prototyp: Suchmaske"
    assert proto["row"]["abnahme"] == "Entwickler"


def test_decision_followup_wird_als_ergebnis_zeile_uebernommen():
    """Bei 'Ja' landet die vorbereitete Zeile ohne diktierten Text in den Terminen."""
    svc = _interview()
    section = svc._section_by_id("hermes_pia", "termine")
    section_answer = {"extracted": [{"ergebnis": "Studie", "termin": "01.02.2026"}]}
    followup = {
        "risk_id": "decision_beschaffung",
        "type": "decision",
        "status": "pending",
        "row": {"ergebnis": "Beschaffungsanalyse", "termin": "01.03.2026",
                "abnahme": "Anwendervertreter", "pruefmethode": "Inhaltliche Pruefung"},
    }
    svc._apply_followup(section, section_answer, followup, raw_text=None)
    rows = section_answer["extracted"]
    assert len(rows) == 2
    besch = next(r for r in rows if r["ergebnis"] == "Beschaffungsanalyse")
    assert besch["abnahme"] == "Anwendervertreter"
    # Abhängigkeit: Beschaffungsanalyse fliesst in die Studie -> davor einsortiert
    assert rows.index(besch) < next(i for i, r in enumerate(rows) if r["ergebnis"] == "Studie")


def test_fill_from_suggestion_appends_not_replaces():
    """Ein proaktiver Vorschlag darf vorhandene Einträge nie überschreiben."""
    svc = _interview()  # ohne LLM -> Katalog-Fallback
    section = svc._section_by_id("hermes_pia", "kommunikation")

    # Abschnitt enthält bereits einen selbst erfassten Eintrag
    section_answer = {"extracted": [{"empfaenger": "Gemeinderat"}]}
    svc._fill_from_suggestion(_Sess(), section, section_answer, {"kommunikation": section_answer})

    rows = section_answer["extracted"]
    # Bestehender Eintrag bleibt erhalten, Katalog-Vorschläge kommen dazu
    assert rows[0]["empfaenger"] == "Gemeinderat"
    assert len(rows) > 1
