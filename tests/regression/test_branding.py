"""Org-Branding (Stufe 1): Farben + Logo pro Organisationseinheit im PMO-Bereich."""
import base64

import pytest

from app.config import Config
from app.factory import create_app

_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
_JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 64


@pytest.fixture
def app(tmp_path):
    from app.shared.database import SessionLocal

    db_path = str(tmp_path / "branding.db").replace("\\", "/")

    class _Cfg(Config):
        DATABASE_URL = "sqlite:///" + db_path
        SUPERADMIN_EMAIL = "betreiber@test.ch"
        SUPERADMIN_PASSWORD = "pw-super"
        SECRET_KEY = "test-secret"

    SessionLocal.remove()
    application = create_app(_Cfg)
    SessionLocal.remove()
    yield application
    SessionLocal.remove()


@pytest.fixture
def clients(app):
    """Org-Admin A, Nur-Leser A und Org-Admin B (fremde Organisation)."""
    auth = app.auth_service
    org_a = auth.create_org("Org A")
    org_b = auth.create_org("Org B")
    auth.create_user("admin@a.ch", "pw", role="org_admin", org_id=org_a.id,
                     can_read=True, can_write=True, can_delete=True)
    auth.create_user("leser@a.ch", "pw", org_id=org_a.id,
                     can_read=True, can_write=False, can_delete=False)
    auth.create_user("admin@b.ch", "pw", role="org_admin", org_id=org_b.id,
                     can_read=True, can_write=True, can_delete=True)

    def _client(email):
        c = app.test_client()
        c.post("/login", data={"email": email, "password": "pw"})
        return c

    return {"a": _client("admin@a.ch"), "leser": _client("leser@a.ch"),
            "b": _client("admin@b.ch")}


def _upload_logo(client, filename="logo.png", data=_PNG):
    return client.post("/pmo/branding/logo", json={
        "filename": filename,
        "data": base64.b64encode(data).decode("ascii"),
    })


# ---- Farben ------------------------------------------------------------ #

def test_ohne_branding_keine_css_injektion(clients):
    html = clients["a"].get("/pmo").get_data(as_text=True)
    assert "--color-primary:" not in html


def test_farben_setzen_injiziert_css_variablen(clients):
    r = clients["a"].post("/pmo/branding", data={
        "kopfleiste_farbe": "#112233",
        "akzent_farbe": "#445566",
        "primaer_farbe": "#778899",
    })
    assert r.status_code == 302
    html = clients["a"].get("/pmo").get_data(as_text=True)
    assert "--color-brand: #112233" in html
    assert "--color-accent: #445566" in html
    assert "--color-primary: #778899" in html
    # Fremde Organisation sieht die Farben NICHT
    html_b = clients["b"].get("/pmo").get_data(as_text=True)
    assert "#112233" not in html_b


def test_ungueltige_farbe_gibt_400(clients):
    r = clients["a"].post("/pmo/branding",
                          data={"kopfleiste_farbe": "rot;<script>"})
    assert r.status_code == 400


def test_leser_darf_branding_nicht_aendern(clients):
    assert clients["leser"].post("/pmo/branding",
                                 data={"kopfleiste_farbe": "#112233"}).status_code == 403
    assert _upload_logo(clients["leser"]).status_code == 403
    assert clients["leser"].post("/pmo/branding/reset").status_code == 403


# ---- Logo -------------------------------------------------------------- #

def test_logo_upload_und_auslieferung(clients):
    assert _upload_logo(clients["a"]).status_code == 200
    r = clients["a"].get("/branding/logo")
    assert r.status_code == 200
    assert r.mimetype == "image/png"
    assert r.data == _PNG
    # Kopfleiste referenziert das eigene Logo statt des Standard-Logos
    html = clients["a"].get("/pmo").get_data(as_text=True)
    assert "/branding/logo" in html
    assert "hermes-pia-logo.svg" not in html


def test_jpg_logo_bekommt_jpeg_mimetype(clients):
    assert _upload_logo(clients["a"], "logo.jpg", _JPG).status_code == 200
    assert clients["a"].get("/branding/logo").mimetype == "image/jpeg"


def test_logo_validierung(clients):
    # Falsche Endung
    assert _upload_logo(clients["a"], "logo.svg").status_code == 400
    # Endung ok, aber kein Bild (falsche Magic Bytes)
    assert _upload_logo(clients["a"], "logo.png", b"MZ kein Bild").status_code == 400
    # Zu gross (> 2 MB)
    zu_gross = b"\x89PNG\r\n\x1a\n" + b"\x00" * (2 * 1024 * 1024)
    assert _upload_logo(clients["a"], "logo.png", zu_gross).status_code == 400
    # Leere Daten
    assert _upload_logo(clients["a"], "logo.png", b"").status_code == 400


def test_mandantentrennung_logo(clients):
    _upload_logo(clients["a"])
    # Org B hat kein Logo -> 404, nie das Logo einer fremden Organisation
    assert clients["b"].get("/branding/logo").status_code == 404
    # Org B sieht weiterhin das Standard-Logo
    assert "hermes-pia-logo.svg" in clients["b"].get("/pmo").get_data(as_text=True)


# ---- Reset ------------------------------------------------------------- #

def test_reset_entfernt_farben_und_logo(clients):
    clients["a"].post("/pmo/branding", data={"primaer_farbe": "#778899"})
    _upload_logo(clients["a"])
    r = clients["a"].post("/pmo/branding/reset")
    assert r.status_code == 302
    html = clients["a"].get("/pmo").get_data(as_text=True)
    assert "--color-primary:" not in html
    assert "hermes-pia-logo.svg" in html
    assert clients["a"].get("/branding/logo").status_code == 404
