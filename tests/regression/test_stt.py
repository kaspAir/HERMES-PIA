"""Beweist: Speech-to-Text (Meeting mithören) – Transcriber + Route."""
from io import BytesIO

import pytest

from app.config import Config
from app.domains.stt.transcriber import Transcriber
from app.factory import create_app


# ---- Transcriber (Unit) --------------------------------------------------- #

def test_transcriber_ohne_key_inaktiv():
    t = Transcriber(api_key="")
    assert t.available is False
    assert t.transcribe(b"abc") == ""


def test_transcriber_mit_key(monkeypatch):
    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"text": "  Hallo Welt  "}

    captured = {}

    def fake_post(url, headers=None, files=None, data=None, timeout=None):
        captured["url"] = url
        captured["model"] = data.get("model")
        captured["auth"] = headers.get("Authorization")
        return _Resp()

    monkeypatch.setattr("app.domains.stt.transcriber.requests.post", fake_post)
    t = Transcriber(api_url="http://stt/x", api_key="k", model="whisper-1")
    assert t.available is True
    assert t.transcribe(b"audio") == "Hallo Welt"
    assert captured["model"] == "whisper-1"
    assert captured["auth"] == "Bearer k"


# ---- Route ---------------------------------------------------------------- #

@pytest.fixture
def app(tmp_path):
    from app.shared.database import SessionLocal
    db_path = str(tmp_path / "stt.db").replace("\\", "/")

    class _Cfg(Config):
        DATABASE_URL = "sqlite:///" + db_path
        SECRET_KEY = "x"

    SessionLocal.remove()
    application = create_app(_Cfg)
    SessionLocal.remove()
    yield application
    SessionLocal.remove()


def _setup_session(app):
    auth = app.auth_service
    org = auth.create_org("Org")
    auth.create_user("u@org.ch", "pw", role="org_admin", org_id=org.id,
                     can_read=True, can_write=True, can_delete=True)
    c = app.test_client()
    c.post("/login", data={"email": "u@org.ch", "password": "pw"})
    loc = c.post("/interview/start",
                 data={"project_name": "P", "projektleiter": "X"}).headers["Location"]
    sid = int(loc.rstrip("/").split("/")[-1])
    return c, sid


def test_transcribe_route_mit_fake(app):
    class _Fake:
        available = True
        def transcribe(self, audio, filename="s", mimetype="m", language="de"):
            return "transkribierter text"

    app.transcriber = _Fake()
    c, sid = _setup_session(app)
    r = c.post(f"/interview/{sid}/transcribe",
               data={"audio": (BytesIO(b"audiobytes"), "segment.webm")},
               content_type="multipart/form-data")
    assert r.status_code == 200
    assert r.get_json()["text"] == "transkribierter text"


def test_transcribe_route_inaktiv_ohne_key(app):
    c, sid = _setup_session(app)   # Default-Transcriber ohne Key
    r = c.post(f"/interview/{sid}/transcribe",
               data={"audio": (BytesIO(b"x"), "segment.webm")},
               content_type="multipart/form-data")
    assert r.status_code == 200
    body = r.get_json()
    assert body["text"] == "" and body["error"]
