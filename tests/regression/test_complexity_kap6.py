"""Beweist: Komplexitäts-Abfrage steuert Dauer; Kap. 6 wird aus 3.1 + Dauer abgeleitet."""
from app.config import get_config
from app.domains.catalog.service import CatalogService
from app.domains.interview.extraction import assess_complexity
from app.domains.interview.service import (
    InterviewService,
    _distribute_pt,
    _pruefmethode,
)
from app.domains.method.service import MethodService


def _svc(llm=None):
    cfg = get_config()
    return InterviewService(MethodService(cfg.METHODS_DIR), CatalogService(cfg.CATALOGS_DIR), llm)


# --- Komplexitäts-Faktor --------------------------------------------------- #

def test_complexity_factor_steigt_mit_stufe():
    low = {"ausgangslage": {"komplexitaet": {"A": {"stufe": "gering"}, "B": {"stufe": "gering"}}}}
    mid = {"ausgangslage": {"komplexitaet": {"A": {"stufe": "mittel"}}}}
    high = {"ausgangslage": {"komplexitaet": {"A": {"stufe": "hoch"}, "B": {"stufe": "hoch"}}}}
    assert InterviewService._complexity_factor({}) == 1.0
    assert InterviewService._complexity_factor(low) == 1.0
    assert InterviewService._complexity_factor(mid) == 1.4
    assert InterviewService._complexity_factor(high) == 1.8


def test_hoehere_komplexitaet_streckt_termine():
    svc = _svc()
    section = svc._section_by_id("hermes_pia", "termine")
    base = svc._catalog_suggestion("fachanwendung_einfuehrung", section)
    from app.domains.interview.service import _assign_termine_dates

    def last_date(rows):
        return max(rows, key=lambda r: r["termin"])["termin"]

    import copy
    r1 = copy.deepcopy(base); _assign_termine_dates(r1, "2026-01-05", 1.0)
    r2 = copy.deepcopy(base); _assign_termine_dates(r2, "2026-01-05", 1.8)
    # Bei höherer Komplexität liegt der letzte Termin später.
    assert last_date(r2) > last_date(r1)


# --- Komplexitäts-Antworten ------------------------------------------------ #

class _ReassessLLM:
    def complete(self, system, messages, max_tokens=1536):
        return '[{"dimension":"Technologie","stufe":"hoch","einschaetzung":"Neu bewertet."}]'


def test_apply_complexity_bestaetigen_und_widerlegen():
    svc = _svc()
    answers = {"ausgangslage": {"extracted": {"text": "x"}}}
    fu = {"type": "complexity", "dimension": "Politik", "stufe": "hoch", "einschaetzung": "Heikel."}
    svc._apply_complexity(answers, fu, raw_text=None, refuted=False)
    assert answers["ausgangslage"]["komplexitaet"]["Politik"]["stufe"] == "hoch"
    # Widerlegen senkt die Stufe
    svc._apply_complexity(answers, fu, raw_text=None, refuted=True)
    assert answers["ausgangslage"]["komplexitaet"]["Politik"]["stufe"] == "mittel"


def test_apply_complexity_ergaenzen_reassesst():
    svc = _svc(_ReassessLLM())
    answers = {"ausgangslage": {"extracted": {"text": "Basis"}}}
    fu = {"type": "complexity", "dimension": "Technologie", "stufe": "mittel", "einschaetzung": "alt"}
    svc._apply_complexity(answers, fu, raw_text="Es ist eine komplett neue Plattform", refuted=False)
    assert answers["ausgangslage"]["komplexitaet"]["Technologie"]["stufe"] == "hoch"


def test_widerlegen_ohne_text_ersetzt_widerspruechlichen_volltext():
    svc = _svc()
    answers = {"ausgangslage": {"extracted": {"text": "x"}}}
    fu = {"type": "complexity", "dimension": "Politik", "stufe": "mittel",
          "einschaetzung": "Mittleres Konfliktpotenzial bei externen Einreichenden."}
    svc._apply_complexity(answers, fu, raw_text=None, refuted=True)
    res = answers["ausgangslage"]["komplexitaet"]["Politik"]
    assert res["stufe"] == "gering"
    # Der widersprechende Detail-Text ist weg, eine kurze Notiz steht da.
    assert "Konfliktpotenzial" not in res["einschaetzung"]
    assert "nicht" in res["einschaetzung"].lower()


def test_apply_complexity_gesprochenes_wird_nie_woertlich_uebernommen():
    """Auch beim Widerlegen mit Sprache: sauber neu formuliert, kein Rohtext."""
    svc = _svc(_ReassessLLM())
    answers = {"ausgangslage": {"extracted": {"text": "Basis"}}}
    fu = {"type": "complexity", "dimension": "Technologie", "stufe": "hoch", "einschaetzung": "alt"}
    roh = "das stimmt so nicht ganz äh es ist eigentlich einfacher judis vier"
    svc._apply_complexity(answers, fu, raw_text=roh, refuted=True)
    res = answers["ausgangslage"]["komplexitaet"]["Technologie"]
    assert roh not in res["einschaetzung"]
    assert "relativiert:" not in res["einschaetzung"]
    assert res["einschaetzung"] == "Neu bewertet."  # vom LLM sauber formuliert


def test_suggestion_context_enthaelt_komplexitaet():
    """Die Komplexitätseinschätzung muss in den Vorschlags-Kontext fliessen,
    damit Personalaufwand/Kosten/... sie sehen (nicht erst im Dokument)."""
    svc = _svc()
    sess = type("S", (), {"project_name": "P", "project_type_id": "x", "auftraggeber": "A"})()
    answers = {"ausgangslage": {"extracted": {"text": "Basis."},
                                "komplexitaet": {"Technologie": {"stufe": "hoch",
                                                                 "einschaetzung": "Neuartig."}}}}
    ctx = svc._suggestion_context(sess, answers)
    assert "Komplexitätseinschätzung" in ctx and "Technologie" in ctx


def test_externe_fachexpertise_wird_ergaenzt():
    svc = _svc()
    rows = [{"rolle": "Projektleiter", "name": "", "aufwand": "12"}]
    answers = {"ausgangslage": {"extracted": {"text": "Digitalisierung."}, "komplexitaet": {
        "Ressourcen": {"stufe": "mittel",
                       "einschaetzung": "Das fehlende interne Know-how muss durch externe "
                                        "Fachexperten kompensiert werden."}}}}
    svc._ensure_external_experts(rows, answers)
    assert any("extern" in r["rolle"].lower() for r in rows)


def test_keine_externe_ohne_signal():
    svc = _svc()
    rows = [{"rolle": "Projektleiter", "name": "", "aufwand": "12"}]
    answers = {"ausgangslage": {"extracted": {"text": "Ein einfaches rein internes Vorhaben."}}}
    svc._ensure_external_experts(rows, answers)
    assert all("extern" not in r["rolle"].lower() for r in rows)


def test_externe_nicht_dupliziert():
    svc = _svc()
    rows = [{"rolle": "Externe Beratung", "name": "", "aufwand": "5"}]
    answers = {"ausgangslage": {"extracted": {"text": "x"}, "komplexitaet": {
        "R": {"stufe": "hoch", "einschaetzung": "extern einkaufen, fehlendes Know-how"}}}}
    svc._ensure_external_experts(rows, answers)
    assert sum("extern" in r["rolle"].lower() for r in rows) == 1


def test_composed_ausgangslage_haengt_komplexitaet_an():
    svc = _svc()
    answers = {"ausgangslage": {"extracted": {"text": "Die Ausgangslage."},
                                "komplexitaet": {"Technologie": {"stufe": "hoch", "einschaetzung": "Neuartig."}}}}
    text = svc.composed_ausgangslage(answers)
    assert "Die Ausgangslage." in text
    assert "Komplexitätseinschätzung" in text and "Technologie – hoch" in text
    # Sauberer Block: eine Zeile je Dimension (Zeilenumbruch vorhanden)
    assert "\n" in text


def test_preview_zeigt_komplexitaet_in_ausgangslage():
    import json
    svc = _svc()
    answers = {"ausgangslage": {"extracted": {"text": "Basis."},
                                "komplexitaet": {"Technologie": {"stufe": "hoch", "einschaetzung": "Neuartig."}}}}
    sess = type("S", (), {"method_id": "hermes_pia", "answers_json": json.dumps(answers)})()
    pv = svc.preview_data(sess)
    ausg = next(x for x in pv if x["id"] == "ausgangslage")
    assert "Komplexitätseinschätzung" in ausg["content"]
    assert "Technologie – hoch" in ausg["content"]


# --- Kapitel 6 aus 3.1 ----------------------------------------------------- #

def test_distribute_pt_summiert_auf_total():
    assert _distribute_pt(15, 3) == [5, 5, 5]
    assert sum(_distribute_pt(8, 3)) == 8
    assert _distribute_pt(0, 3) == []


def test_build_projektorganisation_summe_je_rolle_passt_zu_3_1():
    svc = _svc()
    answers = {
        "personalaufwand": {"extracted": [
            {"rolle": "Projektleiter", "name": "X", "aufwand": "15"},
            {"rolle": "Entwickler", "name": "", "aufwand": "8 PT"},
        ]},
        "termine": {"extracted": [
            {"ergebnis": "Stakeholder-Liste", "termin": "05.01.2026"},
            {"ergebnis": "Durchfuehrungsfreigabe", "termin": "20.03.2026"},
        ]},
    }
    rows = svc._build_projektorganisation(answers, "2026-01-05")
    by_rolle = {r["rolle_person"]: r for r in rows}
    pl = by_rolle["Projektleiter"]
    monate = [int(pl[f"monat_{i}"]) for i in range(1, 10) if pl[f"monat_{i}"]]
    assert sum(monate) == 15  # entspricht Kap. 3.1
    assert pl["bestaetigung"] == "ausstehend"


# --- Prüfmethode & Risiken-Defaults --------------------------------------- #

def test_pruefmethode_meilenstein_vs_inhalt():
    assert "Entscheid" in _pruefmethode("Meilenstein Durchfuehrungsfreigabe")
    assert _pruefmethode("Studie") == "Inhaltliche Prüfung"


def test_postprocess_risiken_setzt_verantwortung_und_termin():
    svc = _svc()
    section = svc._section_by_id("hermes_pia", "risiken")
    sa = {"extracted": [{"beschreibung": "Risiko", "ew": "Mittel", "ag": "Hoch"}]}
    svc._postprocess_section(section, sa, {})
    r = sa["extracted"][0]
    assert r["verantwortung"] == "Projektleiter"
    assert r["termin"] == "laufend"


class _RiskLLM:
    def complete(self, system, messages, max_tokens=256):
        return '{"ew": "Hoch", "ag": "Mittel", "massnahmen": "Frühzeitig einbinden"}'


def test_postprocess_risiken_schaetzt_fehlende_ew_ag():
    svc = _svc(_RiskLLM())
    section = svc._section_by_id("hermes_pia", "risiken")
    sa = {"extracted": [{"beschreibung": "Stakeholder nicht verfügbar"}]}
    svc._postprocess_section(section, sa, {})
    r = sa["extracted"][0]
    assert r["ew"] == "Hoch" and r["ag"] == "Mittel"
    assert r["massnahmen"] and r["verantwortung"] == "Projektleiter"


def test_risiken_gapcheck_nur_bei_eingegebenen_risiken():
    svc = _svc()  # ohne LLM -> Gap-Check isoliert (keine AI-/Komplexitäts-Followups)
    section = svc._section_by_id("hermes_pia", "risiken")
    sess = type("S", (), {"project_type_id": "betriebsabloesung",
                          "start_datum": None, "method_id": "hermes_pia"})()
    # Leere Risiken -> KEIN Gap-Check, damit das normale Vorschlags-Angebot greift
    assert svc._build_followups(section, [], "", sess, {}) == []
    # Eingegebene Risiken -> Gap-Check ergänzt typische fehlende Risiken
    fus = svc._build_followups(section, [{"beschreibung": "Spezielles Einzelrisiko"}], "x", sess, {})
    assert any(f.get("type") == "catalog" for f in fus)


# --- assess_complexity Parsing -------------------------------------------- #

def test_assess_complexity_parst_array():
    out = assess_complexity(_ReassessLLM(), "Eine Ausgangslage.")
    assert out and out[0]["dimension"] == "Technologie" and out[0]["stufe"] == "hoch"
    assert assess_complexity(None, "x") == []
