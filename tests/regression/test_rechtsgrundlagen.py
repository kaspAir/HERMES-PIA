"""Beweist: Rechtsgrundlagenanalyse (Phase A) – Seeding aus PIA, beratender Entwurf,
Befüllung ins HERMES-Template. Modular, ohne den PIA zu berühren."""
import json

import pytest
from docx import Document

from app.config import Config
from app.domains.ergebnisse.projektwissen import Projektwissen
from app.domains.ergebnisse.rechtsgrundlagen.service import RechtsgrundlagenService
from app.factory import create_app


_PIA = {
    "ausgangslage": {"extracted": {"text": "Ablösung des Justizsystems Juris Fiat."}},
    "referenzierte_dokumente": {"extracted": [
        {"nr": "01", "name": "Schweizerische Strafprozessordnung (StPO)", "link": ""},
        {"nr": "02", "name": "Bundesgesetz über die Produktehaftpflicht (PrHG)", "link": ""},
        {"nr": "03", "name": "Bundesgesetz über den Datenschutz (DSG)", "link": ""},  # -> Schuban
    ]},
    "mitgeltende_unterlagen": {"extracted": [
        {"name": "Kantonales Beschaffungsrecht (Submissionsgesetz)", "link": ""}]},  # kantonal
    "ziele": {"extracted": [{"beschreibung": "Verfahrensschritte im System abbilden"}]},
}


class _FakeLLM:
    def __init__(self, payload):
        self._payload = payload

    def complete(self, system, messages, max_tokens=1024):
        return json.dumps(self._payload)


class _FakeFedlex:
    """Kein Netzwerk: liefert die vorgegebene {Suchbegriff: [Treffer]}-Zuordnung."""
    def __init__(self, mapping=None):
        self._m = mapping or {}

    def suche_mehrere(self, begriffe, **kw):
        return self._m


# ---- Modul-Logik (kein DB, kein echter LLM) ------------------------------- #

def test_seeding_ohne_llm_uebernimmt_pia_gesetze():
    wissen = Projektwissen(_PIA, ebene="kanton", kanton="ZH")
    svc = RechtsgrundlagenService(None, None, None, llm=None, fedlex=_FakeFedlex())
    answers = svc.build_answers(wissen)
    namen = [r["rechtsgrundlage"] for r in answers["bestehende_rechtsgrundlagen"]["extracted"]]
    assert "Schweizerische Strafprozessordnung (StPO)" in namen
    # Datenschutzgesetz gehört in die Schutzbedarfsanalyse -> hier NICHT
    assert "Bundesgesetz über den Datenschutz (DSG)" not in namen
    # Ohne LLM keine Beschreibung erfunden
    assert all(r.get("beschreibung", "") == ""
               for r in answers["bestehende_rechtsgrundlagen"]["extracted"])
    # 0.4 Definitionen: enthält die Kürzel der genannten Gesetze
    abk = [r["abkuerzung"] for r in answers["definitionen"]["extracted"]]
    assert "StPO" in abk and "PrHG" in abk
    assert answers["konsequenzen"]["extracted"]["text"] == ""


def test_datenschutz_und_ebene_filter():
    svc = RechtsgrundlagenService(None, None, None, llm=None, fedlex=_FakeFedlex())
    # Nur Bund: kantonale Gesetze fallen weg; Datenschutz immer weg
    namen_bund = [r["rechtsgrundlage"] for r in
                  svc.build_answers(Projektwissen(_PIA, ebene="bund"))
                  ["bestehende_rechtsgrundlagen"]["extracted"]]
    assert "Schweizerische Strafprozessordnung (StPO)" in namen_bund
    assert "Kantonales Beschaffungsrecht (Submissionsgesetz)" not in namen_bund   # kantonal, nur Bund
    assert "Bundesgesetz über den Datenschutz (DSG)" not in namen_bund            # Datenschutz -> Schuban
    # Bund + Kanton: kantonales Gesetz wieder dabei
    namen_beide = [r["rechtsgrundlage"] for r in
                   svc.build_answers(Projektwissen(_PIA, ebene="bund,kanton"))
                   ["bestehende_rechtsgrundlagen"]["extracted"]]
    assert "Kantonales Beschaffungsrecht (Submissionsgesetz)" in namen_beide


def test_llm_vorschlag_wird_gemergt_und_pia_bleibt_fuehrend():
    wissen = Projektwissen(_PIA, ebene="bund")
    svc = RechtsgrundlagenService(None, None, None, fedlex=_FakeFedlex(), llm=_FakeLLM({
        "bestehende": [{"rechtsgrundlage": "Schweizerische Strafprozessordnung (StPO)",
                        "beschreibung": "Regelt das Strafverfahren."}],
        "luecken": [{"luecke": "Fehlende Grundlage", "beschreibung": "für neue Bearbeitung"}],
        "konsequenzen": "Rechtliches Risiko ohne Anpassung.",
        "empfehlung": "Rechtsgrundlage vor Realisierung schaffen.",
    }))
    answers = svc.build_answers(wissen)
    best = {r["rechtsgrundlage"]: r.get("beschreibung", "")
            for r in answers["bestehende_rechtsgrundlagen"]["extracted"]}
    assert best["Schweizerische Strafprozessordnung (StPO)"] == "Regelt das Strafverfahren."
    assert "Bundesgesetz über die Produktehaftpflicht (PrHG)" in best   # weiteres Bundesgesetz
    luecken = answers["identifizierte_luecken"]["extracted"]
    assert luecken and luecken[0]["luecke"] == "Fehlende Grundlage"
    assert answers["konsequenzen"]["extracted"]["text"].startswith("Rechtliches Risiko")


# ---- End-to-End: Entwurf aus PIA-Session -> .docx ------------------------- #

@pytest.fixture
def app(tmp_path):
    from app.shared.database import SessionLocal
    db_path = str(tmp_path / "rga.db").replace("\\", "/")

    class _Cfg(Config):
        DATABASE_URL = "sqlite:///" + db_path
        SECRET_KEY = "x"

    SessionLocal.remove()
    application = create_app(_Cfg)
    SessionLocal.remove()
    yield application
    SessionLocal.remove()


def _projekt_mit_pia(app):
    from app.domains.interview.models import InterviewSession
    from app.shared.database import SessionLocal
    ps = app.projekt_service
    projekt = ps.create_projekt(org_id=1, name="BKI Test 2", auftraggeber="Monika Musterfrau")
    erg = ps.add_ergebnis(projekt.id, "projektinitialisierungsauftrag", created_by="Helene Digital")
    db = SessionLocal()
    db.add(InterviewSession(
        method_id="hermes_pia", project_name="BKI Test 2", org_id=1,
        created_by="Helene Digital", auftraggeber="Monika Musterfrau",
        ergebnis_id=erg.id, answers_json=json.dumps(_PIA)))
    db.commit()
    return projekt.id


def test_entwurf_und_docx_end_to_end(app):
    with app.app_context():
        pid = _projekt_mit_pia(app)
        svc = app.rechtsgrundlagen_service
        projekt = app.projekt_service.get_projekt(pid)

        entwurf = svc.erzeuge_entwurf(projekt, ebene="kanton", kanton="ZH")
        assert entwurf.answers_json and entwurf.kanton == "ZH"

        doc = Document(svc.generate_docx(projekt))
        cells = " ".join(c.text for t in doc.tables for row in t.rows for c in row.cells)
        # Aus dem PIA übernommenes (Nicht-Datenschutz-)Gesetz steht im Dokument
        assert "Schweizerische Strafprozessordnung (StPO)" in cells
        # Titel/Kapitel des Templates vorhanden
        volltext = "\n".join(p.text for p in doc.paragraphs)
        assert "Bestehende Rechtsgrundlagen" in volltext
        assert "Empfehlung" in volltext


# ---- Phase B: Fedlex-Grounding (ohne Netzwerk) ---------------------------- #

def test_fedlex_parsing_gemockt():
    from app.domains.rechtsquellen.fedlex import FedlexClient
    client = FedlexClient()
    client._fetch = lambda sparql: [
        {"sr": {"value": "312.0"}, "title": {"value": "Schweizerische Strafprozessordnung vom 5. Oktober 2007 (StPO)"},
         "cons": {"value": "https://fedlex.data.admin.ch/eli/cc/2010/267"}},
        {"sr": {"value": "312.1"}, "title": {"value": "Jugendstrafprozessordnung (JStPO)"},
         "cons": {"value": "https://fedlex.data.admin.ch/eli/cc/2010/226"}},
    ]
    res = client.suche_mehrere(["Strafprozessordnung"])
    hit = res["Strafprozessordnung"][0]
    assert hit["sr"] == "312.0"                       # kürzeste SR = Haupterlass
    assert hit["url"] == "https://www.fedlex.admin.ch/eli/cc/2010/267/de"


def test_suchbegriffe_aus_gesetzesname():
    from app.domains.ergebnisse.rechtsgrundlagen.grounding import suchbegriffe
    t = suchbegriffe("Bundesgesetz über den Datenschutz (DSG)")
    assert "DSG" in t and "Datenschutz" in t
    assert "Bundesgesetz" not in t                    # generisch -> nicht als Begriff


def test_ground_federal_nur_bei_bund():
    from app.domains.ergebnisse.rechtsgrundlagen.grounding import ground_federal
    fake = _FakeFedlex({"StPO": [{"sr": "312.0", "titel": "StPO …", "url": "u"}]})
    namen = ["Schweizerische Strafprozessordnung (StPO)"]
    assert ground_federal(namen, "kanton", fake) == {}        # nicht Bund -> kein Grounding
    g = ground_federal(namen, "bund", fake)
    assert g["Schweizerische Strafprozessordnung (StPO)"]["sr"] == "312.0"


def test_service_reichert_referenzierte_und_bestehende_mit_fundstelle_an():
    fake = _FakeFedlex({
        "StPO": [{"sr": "312.0", "titel": "Schweizerische Strafprozessordnung vom 5. Oktober 2007 (StPO)",
                  "url": "https://www.fedlex.admin.ch/eli/cc/2010/267/de"}],
    })
    wissen = Projektwissen(_PIA, ebene="bund")
    svc = RechtsgrundlagenService(None, None, None, llm=None, fedlex=fake)
    answers = svc.build_answers(wissen)
    # Referenzierte: der StPO-Eintrag bekommt SR + Fedlex-Link
    ref = next(r for r in answers["referenzierte_dokumente"]["extracted"]
               if "Strafprozessordnung" in r["name"])
    assert "SR 312.0" in ref["link"] and "fedlex.admin.ch" in ref["link"]
    # Bestehende Rechtsgrundlagen: verifizierter Titel + SR + Link als Beschreibung
    best = next(r for r in answers["bestehende_rechtsgrundlagen"]["extracted"]
                if "Strafprozessordnung" in r["rechtsgrundlage"])
    assert "SR 312.0" in best["beschreibung"] and "fedlex.admin.ch" in best["beschreibung"]
