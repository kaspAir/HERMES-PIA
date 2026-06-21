"""HERMES-2022-Korrektheit: richtige Begriffe und Verantwortlichkeiten."""
from io import BytesIO

from docx import Document
from docx.oxml.ns import qn

from app.config import get_config
from app.domains.catalog.service import CatalogService
from app.domains.generation.service import GenerationService
from app.domains.interview import extraction
from app.domains.method.service import MethodService

_TYPES = [
    "fachanwendung_einfuehrung", "basisdienst_plattform", "betriebsabloesung",
    "e_government_portal", "infrastruktur_erneuerung", "organisationsentwicklung",
]


def _catalogs():
    return CatalogService(get_config().CATALOGS_DIR)


def test_termine_uses_durchfuehrungsauftrag_not_projektauftrag():
    cs = _catalogs()
    for t in _TYPES:
        rows = cs.get(t).get("termine") or []
        ergebnisse = [r.get("ergebnis", "") for r in rows]
        assert "Durchführungsauftrag" in ergebnisse, f"{t}: Durchführungsauftrag fehlt"
        assert not any("Projektauftrag" in e for e in ergebnisse), f"{t}: Projektauftrag!"


def test_initialisierung_has_no_phasenbericht():
    cs = _catalogs()
    for t in _TYPES:
        rows = cs.get(t).get("termine") or []
        assert not any("Phasenbericht" in r.get("ergebnis", "") for r in rows), t


def test_termine_matches_template_results_and_roles():
    # Kanonische Vorlage (Abschnitt 4.1): 8 Ergebnisse mit Abnahme-Rollen.
    rows = _catalogs().get("fachanwendung_einfuehrung").get("termine") or []
    by_ergebnis = {r["ergebnis"]: r.get("abnahme") for r in rows}
    assert len(rows) == 8
    assert by_ergebnis.get("Studie") == "Projektleiter"
    assert by_ergebnis.get("Schutzbedarfsanalyse") == "ISDS-Verantwortlicher"
    assert by_ergebnis.get("Durchführungsauftrag") == "Projektleiter"
    # Die zwei Entscheid-Meilensteine der Ergebnistabelle
    meilensteine = [r for r in rows if "Meilenstein" in r["ergebnis"]]
    assert len(meilensteine) == 2
    durchf = next(r for r in meilensteine if "Durchführungsfreigabe" in r["ergebnis"])
    assert durchf["abnahme"] == "Auftraggeber"


def test_no_projektauftrag_term_in_any_catalog():
    cs = _catalogs()
    for t in _TYPES:
        blob = str(cs.get(t))
        assert "Projektauftrag" not in blob, f"{t} enthält noch 'Projektauftrag'"


def test_hermes_rules_injected_into_prompts():
    # Die verbindlichen Regeln müssen im Modul definiert sein und die Kernbegriffe nennen.
    assert "Durchfuehrungsauftrag" in extraction.HERMES_RULES
    assert "KEINEN Phasenbericht" in extraction.HERMES_RULES


def _personalaufwand_rows(buf):
    doc = Document(buf)
    rows = []
    cur = ""
    for el in doc.element.body:
        tag = el.tag.split("}")[-1]
        if tag == "p":
            pPr = el.find(qn("w:pPr"))
            ps = pPr.find(qn("w:pStyle")) if pPr is not None else None
            style = ps.get(qn("w:val")) if ps is not None else ""
            txt = "".join(t.text or "" for t in el.iter(qn("w:t"))).strip()
            if style.startswith("Hberschrift") and txt:
                cur = txt
        elif tag == "tbl" and "Personalaufwand" in cur:
            for r in el.findall(qn("w:tr")):
                rows.append(["".join(t.text or "" for t in c.iter(qn("w:t")))
                             for c in r if c.tag == qn("w:tc")])
            break
    return {r[0]: r[1] for r in rows if len(r) >= 2}


def test_projektleiter_und_auftraggeber_name_autofilled():
    gs = GenerationService(MethodService(get_config().METHODS_DIR))
    sa = {"personalaufwand": {"extracted": [
        {"rolle": "Projektleiter", "aufwand": "20"},
        {"rolle": "Auftraggeber", "aufwand": "3"},
        {"rolle": "IT-Architekt", "aufwand": "5"},
    ]}}
    buf = gs.generate("hermes_pia", sa, {
        "projektname": "Test",
        "projektleiter": "Markus Stein", "auftraggeber": "Hans Meier",
    })
    joined = _personalaufwand_rows(buf)
    assert joined.get("Projektleiter") == "Markus Stein"
    assert joined.get("Auftraggeber") == "Hans Meier"
    assert joined.get("IT-Architekt", "") == ""  # andere Rollen unberührt


def test_gendered_rolle_for_female_projektleiterin():
    gs = GenerationService(MethodService(get_config().METHODS_DIR))
    sa = {"personalaufwand": {"extracted": [
        {"rolle": "Projektleiter", "aufwand": "20"},
        {"rolle": "Auftraggeber", "aufwand": "3"},
    ]}}
    buf = gs.generate("hermes_pia", sa, {
        "projektname": "Test",
        "projektleiter": "Helene Digital", "projektleiter_weiblich": True,
        "auftraggeber": "Hans Meier", "auftraggeber_weiblich": False,
    })
    joined = _personalaufwand_rows(buf)
    assert joined.get("Projektleiterin") == "Helene Digital"
    assert joined.get("Auftraggeber") == "Hans Meier"


def test_steuerungsausschuss_wird_zu_projektausschuss():
    from app.domains.generation.service import _fix_hermes_terms
    assert _fix_hermes_terms("Steuerungsausschuss") == "Projektausschuss"
    assert _fix_hermes_terms("Lenkungsausschuss informiert") == "Projektausschuss informiert"
    # Im generierten Dokument darf der Begriff nicht auftauchen.
    gs = GenerationService(MethodService(get_config().METHODS_DIR))
    data = {"kommunikation": {"extracted": [{"empfaenger": "Steuerungsausschuss"}]}}
    from docx import Document as _Doc
    blob = _Doc(gs.generate("hermes_pia", data, {"projektname": "X"}))
    text = "".join(t.text or "" for t in blob.element.body.iter(qn("w:t")))
    assert "Steuerungsausschuss" not in text
    assert "Projektausschuss" in text


def test_risk_estimate_fills_missing_ew_ag():
    from app.domains.interview.service import InterviewService

    class _LLM:
        def complete(self, system, messages, max_tokens=1024):
            return '{"ew":"Mittel","ag":"Hoch","massnahmen":"Rollback-Plan"}'

    ms = MethodService(get_config().METHODS_DIR)
    sections = {s["id"]: s for s in ms.get("hermes_pia")["sections"]}
    svc = InterviewService(ms, _catalogs(), _LLM())
    # Infrastruktur-Katalog liefert kein ew/ag -> wird per LLM geschätzt.
    fup = next(f for f in svc.followups_for_risks("infrastruktur_erneuerung", [])
               if f["risk_id"] == "r_verfuegbarkeit_migration")
    sa = {"extracted": []}
    svc._apply_followup(sections["risiken"], sa, dict(fup, status="pending"), None)
    row = sa["extracted"][0]
    assert row.get("ew") == "Mittel" and row.get("ag") == "Hoch"
    assert row.get("massnahmen")


def test_risikozahl_mapping_und_ew_ag_uebernahme():
    from app.domains.generation.service import _risk_num
    assert _risk_num("Tief") == 1 and _risk_num("Mittel") == 2 and _risk_num("Hoch") == 3
    assert _risk_num("3") == 3  # numerisch weiterhin möglich

    # Akzeptiertes Katalog-Risiko bringt EW/AG/Massnahmen mit
    cs = _catalogs()
    ms = MethodService(get_config().METHODS_DIR)
    from app.domains.interview.service import InterviewService
    svc = InterviewService(ms, cs, None)
    sections = {s["id"]: s for s in ms.get("hermes_pia")["sections"]}
    fup = next(f for f in svc.followups_for_risks("fachanwendung_einfuehrung", [])
               if f["risk_id"] == "r_datenschutz")
    sa = {"extracted": []}
    svc._apply_followup(sections["risiken"], sa, dict(fup, status="pending"), None)
    row = sa["extracted"][0]
    assert row.get("ew") and row.get("ag")
    assert row.get("massnahmen")
