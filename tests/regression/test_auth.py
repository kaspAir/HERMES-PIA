"""Sicherheit: Anmeldepflicht, Mandantentrennung, granulare Rechte."""
import pytest

from app.config import Config
from app.factory import create_app


@pytest.fixture
def app(tmp_path):
    from app.shared.database import SessionLocal

    db_path = str(tmp_path / "auth.db").replace("\\", "/")

    class _Cfg(Config):
        DATABASE_URL = "sqlite:///" + db_path
        SUPERADMIN_EMAIL = "betreiber@test.ch"
        SUPERADMIN_PASSWORD = "pw-super"
        SECRET_KEY = "test-secret"

    SessionLocal.remove()          # evtl. anhängende Session der Vor-Engine lösen
    application = create_app(_Cfg)
    SessionLocal.remove()          # scoped_session an die neue Engine binden
    yield application
    SessionLocal.remove()


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


def test_passwort_aendern_und_admin_reset(app):
    auth = app.auth_service
    org = auth.create_org("Org")
    auth.create_user("admin@org.ch", "pw", role="org_admin", org_id=org.id,
                     can_read=True, can_write=True, can_delete=True)
    u = auth.create_user("user@org.ch", "altpasswort", org_id=org.id, can_read=True)

    # Selbstbedienung: falsches altes Passwort wird abgelehnt
    assert auth.change_password(u.id, "falsch", "neupasswort1") is False
    assert auth.change_password(u.id, "altpasswort", "neupasswort1") is True
    assert auth.authenticate("user@org.ch", "neupasswort1") is not None

    # Org-Admin setzt das Passwort über die Route zurück
    ca = app.test_client()
    _login(ca, "admin@org.ch", "pw")
    ca.post(f"/admin/benutzer/{u.id}/passwort", data={"new_password": "resetpw12"})
    assert auth.authenticate("user@org.ch", "resetpw12") is not None


def test_org_admin_kann_fremde_org_nicht_zuruecksetzen(app):
    auth = app.auth_service
    org_a = auth.create_org("A")
    org_b = auth.create_org("B")
    auth.create_user("admin@a.ch", "pw", role="org_admin", org_id=org_a.id,
                     can_read=True, can_write=True, can_delete=True)
    victim = auth.create_user("u@b.ch", "originalpw", org_id=org_b.id, can_read=True)

    ca = app.test_client()
    _login(ca, "admin@a.ch", "pw")
    ca.post(f"/admin/benutzer/{victim.id}/passwort", data={"new_password": "hijack123"})

    # Passwort der fremden Organisation bleibt unverändert
    assert auth.authenticate("u@b.ch", "originalpw") is not None
    assert auth.authenticate("u@b.ch", "hijack123") is None
