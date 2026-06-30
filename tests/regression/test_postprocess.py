"""Beweist: deterministische HERMES-Korrekturen nach dem Befüllen eines Abschnitts."""
from app.config import get_config
from app.domains.catalog.service import CatalogService
from app.domains.interview.service import (
    InterviewService,
    _assign_termine_dates,
    _termin_woche,
)
from app.domains.method.service import MethodService


def _pos(rows, needle):
    for i, r in enumerate(rows):
        if needle.lower() in r["ergebnis"].lower():
            return i
    raise AssertionError(f"{needle} nicht gefunden")


def test_termin_woche_abhaengigkeitsrang():
    # Analysen + Prototyp VOR der Studie, danach die Folgeergebnisse
    assert _termin_woche("Beschaffungsanalyse") < _termin_woche("Studie")
    assert _termin_woche("Schutzbedarfsanalyse") < _termin_woche("Studie")
    assert _termin_woche("Prototyp: Fahrzeug") < _termin_woche("Studie")
    assert _termin_woche("Studie") < _termin_woche("Meilenstein Weiteres Vorgehen")
    assert _termin_woche("Meilenstein Weiteres Vorgehen") < _termin_woche("Projektmanagementplan")
    assert _termin_woche("Projektmanagementplan") < _termin_woche("Durchfuehrungsauftrag")
    assert _termin_woche("Durchfuehrungsauftrag") < _termin_woche("Meilenstein Durchfuehrungsfreigabe")


def test_assign_termine_dates_sortiert_nach_abhaengigkeit():
    rows = [
        {"ergebnis": "Stakeholder-Liste"},
        {"ergebnis": "Studie"},
        {"ergebnis": "Rechtsgrundlagenanalyse"},
        {"ergebnis": "Schutzbedarfsanalyse"},
        {"ergebnis": "Meilenstein Weiteres Vorgehen"},
        {"ergebnis": "Projektmanagementplan"},
        {"ergebnis": "Durchfuehrungsauftrag"},
        {"ergebnis": "Meilenstein Durchfuehrungsfreigabe"},
        {"ergebnis": "Beschaffungsanalyse"},
        {"ergebnis": "Prototyp: SAP"},
    ]
    _assign_termine_dates(rows, "2026-08-03")
    # Studie kommt nach allen einfliessenden Ergebnissen
    studie = _pos(rows, "Studie")
    for vor in ("Rechtsgrundlagen", "Schutzbedarf", "Beschaffungsanalyse", "Prototyp"):
        assert _pos(rows, vor) < studie, f"{vor} muss vor der Studie liegen"
    # Folgekette nach der Studie
    assert studie < _pos(rows, "Weiteres Vorgehen") < _pos(rows, "Projektmanagementplan")
    assert _pos(rows, "Projektmanagementplan") < _pos(rows, "Durchfuehrungsauftrag")
    assert _pos(rows, "Durchfuehrungsauftrag") < _pos(rows, "Durchfuehrungsfreigabe")
    # Alle haben ein Datum
    assert all(r.get("termin") for r in rows)


def _svc():
    cfg = get_config()
    return InterviewService(MethodService(cfg.METHODS_DIR), CatalogService(cfg.CATALOGS_DIR), None)


def _phasen(rows):
    return {r["phase"]: r["betrag"] for r in rows}


def test_kosten_breakdown_summen_und_total():
    # Personalkosten kommen aus Kap. 3.1 (Single Source of Truth); Sachmittel aus den Zeilen.
    answers = {"personalaufwand": {"extracted": [
        {"rolle": "Projektleiter", "aufwand": "50"},                  # 50*1200 = 60000 intern
        {"rolle": "Externe Fachexpertise Signatur", "aufwand": "15"},  # 15*1800 = 27000 extern
    ]}}
    rows = [
        {"phase": "Sachmittel und Lizenzen", "betrag": "8000"},
        {"phase": "Konzept", "betrag": "120000"},  # spätere Phase -> raus
    ]
    out = _phasen(InterviewService._kosten_breakdown(rows, answers))
    # intern = Personal 60000 + Sachmittel 8000 = 68000; extern = 27000; Total = 95000
    assert out["Summe interne Kosten"] == "68000"
    assert out["Summe externe Kosten"] == "27000"
    assert out["Total Initialisierung"] == "95000"
    assert "Konzept" not in out


def test_kosten_breakdown_nur_intern():
    answers = {"personalaufwand": {"extracted": [
        {"rolle": "Projektleiter", "aufwand": "25"},   # 25*1200 = 30000
    ]}}
    out = _phasen(InterviewService._kosten_breakdown([], answers))
    assert out["Summe interne Kosten"] == "30000"
    assert out["Total Initialisierung"] == "30000"
    assert "Summe externe Kosten" not in out


def test_kosten_breakdown_ohne_betraege_unveraendert():
    rows = [{"phase": "Interne Personalkosten", "betrag": ""}]
    out = InterviewService._kosten_breakdown(rows, {})
    assert out == [{"phase": "Interne Personalkosten", "betrag": ""}]


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
    answers = {"personalaufwand": {"extracted": [
        {"rolle": "Projektleiter", "aufwand": "25"},          # 25*1200 = 30000 intern
        {"rolle": "Externe Fachexpertise", "aufwand": "20"},  # 20*1800 = 36000 extern
    ]}}
    section_answer = {"extracted": [
        {"phase": "Sachmittel", "betrag": "14000"},
        {"phase": "Konzept", "betrag": "120000"},  # spätere Phase -> raus
    ]}
    svc._postprocess_section(section, section_answer, answers)
    out = {r["phase"]: r["betrag"] for r in section_answer["extracted"]}
    # intern = 30000 + 14000 = 44000; extern = 36000; Total = 80000
    assert out["Total Initialisierung"] == "80000"
    assert "Konzept" not in out


def test_projektorganisation_spalten_decken_vorlage_ab():
    """Vorlage hat 9 Monate + Bestätigung -> method.yaml muss 1:1 passen,
    sonst rutscht 'ausstehend' in eine Monatsspalte."""
    svc = _svc()
    section = svc._section_by_id("hermes_pia", "projektorganisation")
    cols = [c["id"] for c in section["columns"]]
    assert cols[0] == "rolle_person"
    assert cols[-1] == "bestaetigung"
    assert [f"monat_{i}" for i in range(1, 10)] == cols[1:-1]
