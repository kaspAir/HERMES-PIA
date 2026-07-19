"""Beweist: beratender Dauer-Vorschlag aus vergleichbaren Projekten (RAG) – nur wenn
der PL keine Dauer nennt; beim Übernehmen werden Termine/PT neu skaliert."""
from datetime import date

import pytest

from app.config import Config, get_config
from app.domains.catalog.service import CatalogService
from app.domains.interview.service import InterviewService
from app.domains.method.service import MethodService
from app.factory import create_app


class _FakeRag:
    available = True

    def __init__(self, res):
        self._res = res

    def vergleichbare_dauer_wochen(self, query, org_id=None, **kw):
        return self._res

    def search(self, *a, **k):
        return []


class _Session:
    org_id = None


def _svc(rag=None):
    cfg = get_config()
    return InterviewService(MethodService(cfg.METHODS_DIR),
                            CatalogService(cfg.CATALOGS_DIR), None, rag=rag)


def test_vorschlag_nur_ohne_genannte_dauer():
    svc = _svc(rag=_FakeRag({"median_wochen": 39, "n_projekte": 3}))
    ohne = {"ausgangslage": {"raw_text": "Wir lösen das alte Justizsystem ab."}}
    assert svc._rag_dauer_vorschlag(_Session(), ohne)["median_wochen"] == 39
    # Nennt der PL selbst eine Dauer, hat sie Vorrang -> kein Vorschlag.
    mit = {"ausgangslage": {"raw_text": "Für die Initialisierung planen wir neun Monate."}}
    assert svc._rag_dauer_vorschlag(_Session(), mit) is None


def test_ohne_rag_kein_vorschlag():
    assert _svc(rag=None)._rag_dauer_vorschlag(_Session(), {"ausgangslage": {"raw_text": "x"}}) is None


@pytest.fixture
def app(tmp_path):
    from app.shared.database import SessionLocal
    db_path = str(tmp_path / "ragd.db").replace("\\", "/")

    class _Cfg(Config):
        DATABASE_URL = "sqlite:///" + db_path
        SECRET_KEY = "x"

    SessionLocal.remove()
    application = create_app(_Cfg)
    SessionLocal.remove()
    yield application
    SessionLocal.remove()


def test_uebernahme_skaliert_termine_und_pt(app):
    svc = app.interview_service
    with app.app_context():
        s = svc.start_session(method_id="hermes_pia", project_name="T",
                              org_id=1, start_datum="2026-01-05")
        sid = s.id
        # Zustand: kurze Termine (~3 Monate), PT auto-geschätzt, offener RAG-Vorschlag.
        answers = {
            "termine": {"raw_text": "", "complete": True, "extracted": [
                {"ergebnis": "Stakeholder-Liste", "termin": "01.02.2026"},
                {"ergebnis": "Studie", "termin": "20.02.2026"},
                {"ergebnis": "Meilenstein Durchführungsfreigabe", "termin": "15.03.2026"},
            ], "followups": [{
                "risk_id": "rag_dauer", "type": "rag_dauer", "status": "pending",
                "dauer_wochen": 39,  # ~9 Monate
            }]},
            "personalaufwand": {"raw_text": "", "complete": True, "followups": [],
                                "extracted": [{"rolle": "Projektleiter", "name": "",
                                               "aufwand": "20", "_pt_auto": True}]},
        }
        svc._persist_answers(svc.get_session(sid), answers)

        svc.answer_followup(sid, "rag_dauer", accepted=True)

        neu = svc._answers(svc.get_session(sid))
        assert float(neu["_dauer_wochen"]) == 39
        # Phasenende ~9 Monate nach Start
        last = neu["termine"]["extracted"][-1]["termin"]
        d, m, y = map(int, last.split("."))
        tage = (date(y, m, d) - date(2026, 1, 5)).days
        assert 250 <= tage <= 290, f"~9 Monate erwartet, war {tage}"
        # Auto-PT wurden auf die neue Dauer neu skaliert (grösser als vorher 20)
        pl = next(r for r in neu["personalaufwand"]["extracted"]
                  if "projektleiter" in r["rolle"].lower())
        assert int(pl["aufwand"]) > 20
