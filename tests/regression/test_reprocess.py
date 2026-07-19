"""Beweist: 'Neu verarbeiten' wendet die deterministischen HERMES-Korrekturen
erneut auf eine bestehende Session an – ohne neues Interview.

Motivation: ein erneuter Download derselben Session zeigt nur die eingefrorenen
Antworten. Verbesserungen an der Aufbereitung (Rollen, Termine/Dauer) sollen sich
auf eine bestehende Test-Session anwenden lassen, statt alles neu einlesen zu müssen.
"""
import json
from datetime import date

import pytest

from app.config import Config
from app.factory import create_app


@pytest.fixture
def app(tmp_path):
    from app.shared.database import SessionLocal
    db_path = str(tmp_path / "reproc.db").replace("\\", "/")

    class _Cfg(Config):
        DATABASE_URL = "sqlite:///" + db_path
        SECRET_KEY = "x"

    SessionLocal.remove()
    application = create_app(_Cfg)
    SessionLocal.remove()
    yield application
    SessionLocal.remove()


def _seed(svc, sid, answers):
    svc._persist_answers(svc.get_session(sid), answers)


def test_reprocess_ergaenzt_rollen_und_wendet_dauer_an(app):
    svc = app.interview_service
    with app.app_context():
        session = svc.start_session(method_id="hermes_pia", project_name="T",
                                    org_id=1, start_datum="2026-01-05")
        sid = session.id
        # Eingefrorener Zustand wie im BKI-Test: Personalaufwand nur mit externer
        # Expertise, Termine ohne Berücksichtigung der genannten 9 Monate.
        answers = {
            "termine": {
                "raw_text": "Wir haben neun Monate für die Phase Initialisierung eingeplant.",
                "extracted": [
                    {"ergebnis": "Stakeholder-Liste", "termin": "01.02.2026"},
                    {"ergebnis": "Schutzbedarfsanalyse", "termin": "08.02.2026"},
                    {"ergebnis": "Studie", "termin": "01.03.2026"},
                    {"ergebnis": "Meilenstein Durchführungsfreigabe", "termin": "15.03.2026"},
                ],
                "complete": True, "followups": [],
            },
            "personalaufwand": {
                "raw_text": "Möglichst viel intern, aber externe Expertise nötig.",
                "extracted": [{"rolle": "Externe Fachexpertise", "name": "", "aufwand": ""}],
                "complete": True, "followups": [],
            },
        }
        _seed(svc, sid, answers)

        changed = svc.reprocess(sid)
        assert "personalaufwand" in changed and "termine" in changed

        neu = svc._answers(svc.get_session(sid))

        # 1) Pflichtrollen wurden ergänzt (PL/AG voran, ISDS aus Schutzbedarfsanalyse).
        rollen = " ".join(r["rolle"].lower() for r in neu["personalaufwand"]["extracted"])
        for erwartet in ("projektleiter", "auftraggeber", "isds"):
            assert erwartet in rollen, f"Rolle fehlt nach reprocess: {erwartet}"
        assert neu["personalaufwand"]["extracted"][0]["rolle"] == "Projektleiter"

        # 2) Phasenende folgt der genannten Dauer (~9 Monate), nicht mehr ~3.
        last = neu["termine"]["extracted"][-1]["termin"]  # nach Rang sortiert
        d, m, y = map(int, last.split("."))
        tage = (date(y, m, d) - date(2026, 1, 5)).days
        assert 250 <= tage <= 290, f"Phasenende ~9 Monate erwartet, war {tage} Tage"


def test_reprocess_ist_idempotent(app):
    """Zweimal 'Neu verarbeiten' darf keine Rollen doppeln oder Termine verschieben."""
    svc = app.interview_service
    with app.app_context():
        session = svc.start_session(method_id="hermes_pia", project_name="T",
                                    org_id=1, start_datum="2026-01-05")
        sid = session.id
        _seed(svc, sid, {
            "personalaufwand": {
                "raw_text": "", "complete": True, "followups": [],
                "extracted": [{"rolle": "Externe Fachexpertise", "name": "", "aufwand": ""}],
            },
        })
        svc.reprocess(sid)
        erste = svc._answers(svc.get_session(sid))["personalaufwand"]["extracted"]
        svc.reprocess(sid)
        zweite = svc._answers(svc.get_session(sid))["personalaufwand"]["extracted"]
        rollen_1 = [r["rolle"] for r in erste]
        rollen_2 = [r["rolle"] for r in zweite]
        assert rollen_1 == rollen_2, "reprocess muss idempotent sein"
        assert len(rollen_2) == len(set(rollen_2)), "keine doppelten Rollen"
