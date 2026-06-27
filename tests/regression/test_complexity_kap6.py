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


def test_composed_ausgangslage_haengt_komplexitaet_an():
    svc = _svc()
    answers = {"ausgangslage": {"extracted": {"text": "Die Ausgangslage."},
                                "komplexitaet": {"Technologie": {"stufe": "hoch", "einschaetzung": "Neuartig."}}}}
    text = svc.composed_ausgangslage(answers)
    assert "Die Ausgangslage." in text
    assert "Komplexitätseinschätzung" in text and "Technologie" in text and "hoch" in text


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


# --- assess_complexity Parsing -------------------------------------------- #

def test_assess_complexity_parst_array():
    out = assess_complexity(_ReassessLLM(), "Eine Ausgangslage.")
    assert out and out[0]["dimension"] == "Technologie" and out[0]["stufe"] == "hoch"
    assert assess_complexity(None, "x") == []
