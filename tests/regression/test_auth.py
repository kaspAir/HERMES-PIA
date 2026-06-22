"""Sicherheit: Anmeldepflicht, Mandantentrennung, granulare Rechte."""
import pytest

from app.config import Config
from app.factory import create_app


@pytest.fixture
def app(tmp_path):
    db_path = str(tmp_path / "auth.db").replace("\\", "/")

    class _Cfg(Config):
        DATABASE_URL = "sqlite:///" + db_path
        SUPERADMIN_EMAIL = "betreiber@test.ch"
        SUPERADMIN_PASSWORD = "pw-super"
        SECRET_KEY = "test-secret"

    return create_app(_Cfg)


def _login(client, email, pw):
    return client.post("/login", data={"email": email, "password": pw})


def test_login_erforderlich(app):
    r = app.test_client().get("/")
    assert r.status_code == 302 and "/login" in r.headers["Location"]


def test_super_admin_kommt_in_org_verwaltung(app):
    c = app.test_client()
    _login(c, "betreiber@test.ch", "pw-super")
    assert c.get("/admin/organisationen").status_code == 200


def test_mandantentrennung_und_rechte(app):
    auth = app.auth_service
    org_a = auth.create_org("Org A")
    org_b = auth.create_org("Org B")
    auth.create_user("a@a.ch", "pw", role="org_admin", org_id=org_a.id,
                     can_read=True, can_write=True, can_delete=True)
    auth.create_user("b@b.ch", "pw", role="org_admin", org_id=org_b.id,
                     can_read=True, can_write=True, can_delete=True)
    auth.create_user("leser@a.ch", "pw", org_id=org_a.id,
                     can_read=True, can_write=False, can_delete=False)

    # Org-Admin A legt eine PIA an
    ca = app.test_client()
    _login(ca, "a@a.ch", "pw")
    loc = ca.post("/interview/start",
                  data={"project_name": "P", "projektleiter": "X"}).headers["Location"]
    sid = int(loc.rstrip("/").split("/")[-1])

    # Fremde Organisation darf NICHT zugreifen
    cb = app.test_client()
    _login(cb, "b@b.ch", "pw")
    assert cb.get(f"/interview/{sid}").status_code == 403

    # Nur-Lesen darf ansehen, aber NICHT starten oder löschen
    cr = app.test_client()
    _login(cr, "leser@a.ch", "pw")
    assert cr.get(f"/interview/{sid}").status_code == 200
    assert cr.post("/interview/start",
                   data={"project_name": "Y", "projektleiter": "Z"}).status_code == 403
    assert cr.post(f"/interview/{sid}/delete").status_code == 403
