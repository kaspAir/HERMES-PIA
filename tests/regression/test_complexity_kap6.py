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


def test_kosten_leitet_intern_extern_aus_personalaufwand_ab():
    """Kosten dürfen keine externen Posten ausweisen, die im Personalaufwand fehlen.
    Personalkosten werden aus Kap. 3.1 abgeleitet; Sachmittel bleiben erhalten."""
    svc = _svc()
    answers = {"personalaufwand": {"extracted": [
        {"rolle": "Projektleiter", "name": "X", "aufwand": "20"},
        {"rolle": "Entwickler", "name": "", "aufwand": "10"},
        {"rolle": "Externe Fachexpertise Cloud", "name": "", "aufwand": "10"},
    ]}}
    # Frei erfundene externe Personalzeilen (Datenschutz, Entwickler) + eine Sachmittelzeile.
    rows = [{"phase": "Externe Fachexpertise Datenschutz und Recht (extern)", "betrag": "14000"},
            {"phase": "Externe Fachexpertise Entwickler/Prototyp (extern)", "betrag": "18000"},
            {"phase": "Sachmittel und Lizenzen", "betrag": "6000"}]
    out = svc._kosten_breakdown(rows, answers)
    labels = [r["phase"] for r in out]

    # Genau EINE externe Position – die externe Rolle aus Kap. 3.1 (Cloud, 10 PT * 1800).
    assert any("Externe Fachexpertise Cloud" in l for l in labels)
    assert not any("Datenschutz" in l for l in labels)
    assert not any("Prototyp" in l for l in labels)
    extern_summe = next(r["betrag"] for r in out if r["phase"] == "Summe externe Kosten")
    assert extern_summe == str(10 * 1800)

    # Interne Personalkosten aus 30 PT (20 PL + 10 Entwickler), Sachmittel erhalten.
    intern_personal = next(r["betrag"] for r in out if "Interne Personalkosten" in r["phase"])
    assert intern_personal == str(30 * 1200)
    assert any("Sachmittel" in l for l in labels)

    # Summen + Total vorhanden und stimmig.
    assert any(l == "Summe interne Kosten" for l in labels)
    total = next(r["betrag"] for r in out if r["phase"] == "Total Initialisierung")
    assert int(total) == 30 * 1200 + 6000 + 10 * 1800


def test_nachweis_ausgangslage_herkunft_kombiniert_bei_komplexitaet():
    """Sobald die Ausgangslage eine Komplexitätseinschätzung trägt, ist die Herkunft
    transparent kombiniert (Projektleiter + HERMES PIA), nicht nur 'Interview'."""
    svc = _svc()  # ohne LLM -> Fallback-Begründung, Herkunft deterministisch
    sess = type("S", (), {"method_id": "hermes_pia", "project_name": "P",
                          "project_type_id": "x", "auftraggeber": "A"})()
    title = svc._section_by_id("hermes_pia", "ausgangslage").get("title")
    answers = {"ausgangslage": {"raw_text": "Diktat", "extracted": {"text": "Basis."},
                                "komplexitaet": {"Technologie": {"stufe": "hoch",
                                                                 "einschaetzung": "X."}}}}
    nw = svc.build_nachweis(sess, answers)
    ausg = next(e for e in nw if e["abschnitt"] == title)
    assert ausg["herkunft"] == "Projektleiter + HERMES PIA"


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


# --- Garantie: Komplexitäts-Abfrage wird nachgeholt (Selbstheilung) -------- #

import pytest


@pytest.fixture
def app(tmp_path):
    from app.config import Config
    from app.factory import create_app
    from app.shared.database import SessionLocal

    db_path = str(tmp_path / "cx.db").replace("\\", "/")

    class _Cfg(Config):
        DATABASE_URL = "sqlite:///" + db_path
        SECRET_KEY = "x"

    SessionLocal.remove()
    application = create_app(_Cfg)
    SessionLocal.remove()
    yield application
    SessionLocal.remove()


class _CountingAssessLLM:
    def __init__(self):
        self.calls = 0

    def complete(self, system, messages, max_tokens=1536):
        self.calls += 1
        return '[{"dimension":"Technologie","stufe":"hoch","einschaetzung":"T."}]'


def _session_mit_ausgangslage_ohne_followups(app, followups=None, komplexitaet=None):
    svc = app.interview_service
    session = svc.start_session(method_id="hermes_pia", project_name="P", org_id=1)
    entry = {"raw_text": "diktat", "extracted": {"text": "Die Ausgangslage."},
             "complete": True, "followups": followups or []}
    if komplexitaet:
        entry["komplexitaet"] = komplexitaet
    svc._persist_answers(session, {"ausgangslage": entry})
    return svc, svc.get_session(session.id)


def test_current_state_holt_fehlende_komplexitaet_nach(app):
    """Ausgangslage beantwortet, aber keine Komplexitäts-Followups (LLM-Fehler beim
    Submit oder Bearbeiten-Pfad): current_state MUSS sie nacherzeugen."""
    svc, session = _session_mit_ausgangslage_ohne_followups(app)
    llm = _CountingAssessLLM()
    svc.llm = llm

    state = svc.current_state(session)
    assert state["phase"] == "followup"
    assert state["followup"]["type"] == "complexity"
    # Alle 5 Dimensionen garantiert und persistiert
    fus = svc._answers(session)["ausgangslage"]["followups"]
    assert sum(1 for f in fus if f.get("type") == "complexity") == 5

    # Zweiter Aufruf: nichts Neues, kein weiterer LLM-Call
    svc.current_state(session)
    assert llm.calls == 1
    assert sum(1 for f in svc._answers(session)["ausgangslage"]["followups"]
               if f.get("type") == "complexity") == 5


def test_keine_nachholung_wenn_komplexitaet_vorhanden(app):
    svc, session = _session_mit_ausgangslage_ohne_followups(
        app, komplexitaet={"Technologie": {"stufe": "hoch", "einschaetzung": "X."}})
    llm = _CountingAssessLLM()
    svc.llm = llm
    state = svc.current_state(session)
    assert llm.calls == 0                      # bereits verarbeitet -> kein Re-Ask
    assert state["phase"] == "question"        # weiter zum nächsten Abschnitt


def test_keine_nachholung_wenn_followups_schon_gestellt(app):
    """Auch dismissed/accepted Complexity-Followups verhindern eine erneute Abfrage."""
    svc, session = _session_mit_ausgangslage_ohne_followups(
        app, followups=[{"risk_id": "complexity_0", "type": "complexity",
                         "status": "dismissed", "frage": "?"}])
    llm = _CountingAssessLLM()
    svc.llm = llm
    svc.current_state(session)
    assert llm.calls == 0


def test_update_free_text_fuehrt_zu_nachgeholter_komplexitaet(app):
    """Der Bearbeiten-Pfad (Ausgangslage nachbesprechen) muss in die
    Komplexitäts-Abfrage münden, nicht direkt zum nächsten Abschnitt."""
    svc = app.interview_service
    session = svc.start_session(method_id="hermes_pia", project_name="P", org_id=1)
    sid = session.id
    svc._persist_answers(session, {"ausgangslage": {
        "raw_text": "alt", "extracted": {"text": "Alt."}, "complete": True,
        "followups": []}})
    svc.llm = None                             # Bearbeiten ohne LLM-Reformulierung
    svc.update_free_text(sid, "ausgangslage", "Neuer nachgesprochener Text.")
    svc.llm = _CountingAssessLLM()             # beim nächsten Seitenaufbau verfügbar
    state = svc.current_state(svc.get_session(sid))
    assert state["phase"] == "followup"
    assert state["followup"]["type"] == "complexity"


# --- assess_complexity Parsing -------------------------------------------- #

def test_assess_complexity_parst_array():
    out = assess_complexity(_ReassessLLM(), "Eine Ausgangslage.")
    assert out and out[0]["dimension"] == "Technologie" and out[0]["stufe"] == "hoch"
    assert assess_complexity(None, "x") == []


class _PartialLLM:
    """Liefert nur 2 der 5 Dimensionen – die übrigen müssen ergänzt werden."""
    def complete(self, system, messages, max_tokens=1536):
        return ('[{"dimension": "Technologie", "stufe": "hoch", "einschaetzung": "T."}, '
                '{"dimension": "Recht & Compliance", "stufe": "mittel", "einschaetzung": "R."}]')


def test_assess_complexity_garantiert_alle_dimensionen():
    out = assess_complexity(_PartialLLM(), "Eine Ausgangslage.")
    namen = [o["dimension"] for o in out]
    assert len(out) == 5
    assert "Politik & Stakeholder" in namen          # fehlte im LLM-Output -> ergänzt
    assert next(o for o in out if o["dimension"] == "Technologie")["stufe"] == "hoch"
    assert all(o.get("einschaetzung") for o in out)  # keine leere Einschätzung
