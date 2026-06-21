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


def test_projektleiter_name_autofilled_in_personalaufwand():
    gs = GenerationService(MethodService(get_config().METHODS_DIR))
    sa = {"personalaufwand": {"extracted": [
        {"rolle": "Auftraggeber", "aufwand": "3"},
        {"rolle": "Projektleiter", "aufwand": "20"},
        {"rolle": "PL", "aufwand": "5"},
    ]}}
    buf = gs.generate("hermes_pia", sa,
                      {"projektname": "Test", "projektleiter": "Helene Digital"})
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

    joined = {r[0]: r[1] for r in rows if len(r) >= 2}
    assert joined.get("Projektleiter") == "Helene Digital"
    assert joined.get("PL") == "Helene Digital"
    assert joined.get("Auftraggeber", "") == ""  # andere Rollen unberührt
