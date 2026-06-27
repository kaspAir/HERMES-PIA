"""Beweist: ein verspäteter Doppel-Submit auf /answer wirft nicht mehr,
sondern liefert den aktuellen Zustand (Idempotenz)."""
import pytest

from app.config import Config
from app.factory import create_app


@pytest.fixture
def app(tmp_path):
    from app.shared.database import SessionLocal
    db_path = str(tmp_path / "idem.db").replace("\\", "/")

    class _Cfg(Config):
        DATABASE_URL = "sqlite:///" + db_path
        SECRET_KEY = "x"

    SessionLocal.remove()
    application = create_app(_Cfg)
    SessionLocal.remove()
    yield application
    SessionLocal.remove()


def test_submit_answer_doppelt_wirft_nicht(app):
    svc = app.interview_service
    with app.app_context():
        session = svc.start_session(method_id="hermes_pia", project_name="T", org_id=1)
        sid = session.id
        # Alle Abschnitte leer beantworten, bis kein offener Frageabschnitt mehr.
        for _ in range(40):
            st = svc.current_state(svc.get_session(sid))
            if st["phase"] != "question":
                break
            svc.submit_answer(sid, "")
        # Erneuter answer-Submit darf NICHT mehr werfen, sondern den Zustand liefern.
        result = svc.submit_answer(sid, "verspäteter Doppel-Submit")
        assert isinstance(result, dict) and result.get("phase") in ("followup", "complete", "question")


def test_answer_followup_doppelklick_wirft_nicht(app):
    svc = app.interview_service
    with app.app_context():
        session = svc.start_session(method_id="hermes_pia", project_name="T", org_id=1)
        sid = session.id
        # Bereits verarbeitetes / unbekanntes Followup -> kein Fehler, Zustand zurück.
        result = svc.answer_followup(sid, "offer_sachmittel", accepted=True)
        assert isinstance(result, dict) and "phase" in result
