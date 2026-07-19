"""Beweist: die Kapitel-Bearbeitung (GET /interview/<id>/edit/<section>) wirft
keinen 500 mehr. Regression: die Route übergab die method_id (String) statt der
Methode (dict) an _section_by_id -> AttributeError -> Internal Server Error."""
import pytest

from app.config import Config
from app.factory import create_app


@pytest.fixture
def app(tmp_path):
    from app.shared.database import SessionLocal
    db_path = str(tmp_path / "edit.db").replace("\\", "/")

    class _Cfg(Config):
        DATABASE_URL = "sqlite:///" + db_path
        SECRET_KEY = "x"

    SessionLocal.remove()
    application = create_app(_Cfg)
    SessionLocal.remove()
    yield application
    SessionLocal.remove()


@pytest.fixture
def client(app):
    auth = app.auth_service
    org = auth.create_org("Org A")
    org_id = int(org.id)
    auth.create_user("a@a.ch", "pw", role="org_admin", org_id=org_id,
                     can_read=True, can_write=True, can_delete=True)
    c = app.test_client()
    c.post("/login", data={"email": "a@a.ch", "password": "pw"})
    return c, app, org_id


def test_edit_freitext_kapitel_kein_500(client):
    c, app, org_id = client
    with app.app_context():
        s = app.interview_service.start_session(
            method_id="hermes_pia", project_name="T", org_id=org_id)
        sid = s.id
    # Ausgangslage ist ein Freitext-Kapitel -> Bearbeitungsformular, kein Fehler.
    r = c.get(f"/interview/{sid}/edit/ausgangslage")
    assert r.status_code == 200


def test_edit_tabellen_kapitel_setzt_zurueck(client):
    c, app, org_id = client
    with app.app_context():
        s = app.interview_service.start_session(
            method_id="hermes_pia", project_name="T", org_id=org_id)
        sid = s.id
    # Termine ist ein Tabellen-Kapitel -> Reset + Redirect (302), kein 500.
    r = c.get(f"/interview/{sid}/edit/termine", follow_redirects=False)
    assert r.status_code in (302, 303)
