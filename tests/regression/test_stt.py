"""Beweist: Speech-to-Text (Meeting mithören) – Transcriber + Route."""
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
               data=b"audiobytes", content_type="audio/webm")
    assert r.status_code == 200
    assert r.get_json()["text"] == "transkribierter text"


def test_transcribe_route_inaktiv_ohne_key(app):
    c, sid = _setup_session(app)   # Default-Transcriber ohne Key
    r = c.post(f"/interview/{sid}/transcribe",
               data=b"x", content_type="audio/webm")
    assert r.status_code == 200
    body = r.get_json()
    assert body["text"] == "" and body["error"]


def test_transcribe_route_json_base64(app):
    """Bevorzugter Transportweg: Base64-Audio in JSON (Text-Body, proxy-verträglich)."""
    import base64

    captured = {}

    class _Fake:
        available = True
        def transcribe(self, audio, filename="s", mimetype="m"):
            captured["audio"] = audio
            captured["mimetype"] = mimetype
            return "diktierter text"

    app.transcriber = _Fake()
    c, sid = _setup_session(app)
    r = c.post(f"/interview/{sid}/transcribe",
               json={"audio": base64.b64encode(b"audiobytes").decode(),
                     "mime": "audio/webm;codecs=opus"})
    assert r.status_code == 200
    assert r.get_json()["text"] == "diktierter text"
    assert captured["audio"] == b"audiobytes"           # korrekt decodiert
    assert captured["mimetype"] == "audio/webm;codecs=opus"


def test_transcribe_route_json_ohne_audio(app):
    class _Fake:
        available = True
        def transcribe(self, audio, filename="s", mimetype="m"):
            return "x"

    app.transcriber = _Fake()
    c, sid = _setup_session(app)
    # Leeres/kaputtes Base64 -> 400 "Keine Audiodaten", kein Crash.
    r = c.post(f"/interview/{sid}/transcribe", json={"audio": ""})
    assert r.status_code == 400
    r = c.post(f"/interview/{sid}/transcribe", json={"audio": "%%%nicht-base64%%%"})
    assert r.status_code == 400


def test_generische_transcribe_route(app):
    """Session-unabhaengiges Diktat (z.B. Bemerkungsfelder) fuer schreibberechtigte
    Nutzer; Nur-Leser sind gesperrt."""
    import base64

    class _Fake:
        available = True
        def transcribe(self, audio, filename="s", mimetype="m"):
            return "bemerkung diktiert"

    app.transcriber = _Fake()
    auth = app.auth_service
    org = auth.create_org("Org2")
    auth.create_user("w@o.ch", "pw", role="org_admin", org_id=org.id,
                     can_read=True, can_write=True, can_delete=True)
    auth.create_user("r@o.ch", "pw", org_id=org.id, can_read=True, can_write=False)

    cw = app.test_client()
    cw.post("/login", data={"email": "w@o.ch", "password": "pw"})
    r = cw.post("/transcribe",
                json={"audio": base64.b64encode(b"aud").decode(), "mime": "audio/webm"})
    assert r.status_code == 200 and r.get_json()["text"] == "bemerkung diktiert"

    cr = app.test_client()
    cr.post("/login", data={"email": "r@o.ch", "password": "pw"})
    assert cr.post("/transcribe", json={"audio": "x"}).status_code == 403


# ---- Asynchroner Anbieter (z.B. Infomaniak AI Services, CH) ---------------- #

class _Resp:
    def __init__(self, payload, status=200, text=""):
        self._p = payload; self.status_code = status; self.text = text
    def raise_for_status(self):
        if self.status_code >= 400: raise AssertionError("HTTP %s" % self.status_code)
    def json(self):
        if self._p is None: raise ValueError("kein JSON")
        return self._p


def test_transcriber_asynchron_batch_id_polling(monkeypatch):
    """POST liefert nur eine batch_id -> es wird gepollt, bis der Text da ist."""
    gesehen = {}
    monkeypatch.setattr("app.domains.stt.transcriber.requests.post",
                        lambda url, **kw: _Resp({"data": {"batch_id": "b-1"}}))
    folge = [ _Resp({"data": {"status": "processing"}}),
              _Resp({"data": {"status": "done", "text": "Diktierter Text."}}) ]
    def fake_get(url, **kw):
        gesehen["url"] = url
        return folge.pop(0)
    monkeypatch.setattr("app.domains.stt.transcriber.requests.get", fake_get)
    monkeypatch.setattr("app.domains.stt.transcriber.time.sleep", lambda s: None)
    t = Transcriber(api_url="https://api.infomaniak.com/1/ai/76791/openai/audio/transcriptions",
                    api_key="k", model="whisper", poll_intervall=0)
    assert t.transcribe(b"audio") == "Diktierter Text."
    assert gesehen["url"] == "https://api.infomaniak.com/1/ai/76791/results/b-1"


def test_transcriber_asynchron_download_fallback(monkeypatch):
    """Status 'done' ohne Text -> Text wird über /download geholt (auch als Klartext)."""
    monkeypatch.setattr("app.domains.stt.transcriber.requests.post",
                        lambda url, **kw: _Resp({"batch_id": "b-2"}))
    def fake_get(url, **kw):
        if url.endswith("/download"):
            return _Resp(None, text="Text aus dem Download.")
        return _Resp({"data": {"status": "finished"}})
    monkeypatch.setattr("app.domains.stt.transcriber.requests.get", fake_get)
    monkeypatch.setattr("app.domains.stt.transcriber.time.sleep", lambda s: None)
    t = Transcriber(api_url="https://api.infomaniak.com/1/ai/9/openai/audio/transcriptions",
                    api_key="k", poll_intervall=0)
    assert t.transcribe(b"audio") == "Text aus dem Download."


def test_transcriber_asynchron_fehlerstatus_liefert_leer(monkeypatch):
    monkeypatch.setattr("app.domains.stt.transcriber.requests.post",
                        lambda url, **kw: _Resp({"batch_id": "b-3"}))
    monkeypatch.setattr("app.domains.stt.transcriber.requests.get",
                        lambda url, **kw: _Resp({"data": {"status": "error"}}))
    monkeypatch.setattr("app.domains.stt.transcriber.time.sleep", lambda s: None)
    t = Transcriber(api_url="https://api.infomaniak.com/1/ai/9/openai/audio/transcriptions",
                    api_key="k", poll_intervall=0)
    assert t.transcribe(b"audio") == ""       # ehrlich leer statt geraten
