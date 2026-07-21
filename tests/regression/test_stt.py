"""Beweist: Speech-to-Text (Meeting mithören) – Transcriber + Route."""
import re
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
        def transcribe(self, audio, filename="s", mimetype="m", language="de", **kw):
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
        def transcribe(self, audio, filename="s", mimetype="m", **kw):
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
        def transcribe(self, audio, filename="s", mimetype="m", **kw):
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
        def transcribe(self, audio, filename="s", mimetype="m", **kw):
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


def test_prompt_und_sprache_werden_gesendet(monkeypatch):
    """Vokabular-Hinweis (prompt) + Sprache landen im Request – hebt die Erkennung
    von Fachbegriffen (z.B. 'Server' statt 'Säure')."""
    gesehen = {}
    def fake_post(url, **kw):
        gesehen.update(kw.get("data") or {})
        return _Resp({"text": "ok"})
    monkeypatch.setattr("app.domains.stt.transcriber.requests.post", fake_post)
    t = Transcriber(api_url="http://stt/x", api_key="k", model="whisper",
                    language="de", prompt="Server, Services, HERMES")
    assert t.transcribe(b"audio") == "ok"
    assert gesehen["prompt"] == "Server, Services, HERMES"
    assert gesehen["language"] == "de"


def test_leere_sprache_wird_nicht_gesendet(monkeypatch):
    """STT_LANGUAGE leer -> Parameter weglassen (manche Anbieter übersetzen sonst)."""
    gesehen = {}
    def fake_post(url, **kw):
        gesehen.update(kw.get("data") or {})
        return _Resp({"text": "ok"})
    monkeypatch.setattr("app.domains.stt.transcriber.requests.post", fake_post)
    t = Transcriber(api_url="http://stt/x", api_key="k", language="", prompt="")
    t.transcribe(b"audio")
    assert "language" not in gesehen and "prompt" not in gesehen


def test_default_prompt_ist_generischer_fliesstext():
    """Der Standard-Prompt muss (a) sauberer Fliesstext sein – Whisper übernimmt den
    Stil – und (b) GENERISCH bleiben: kein Fachgebiet eines einzelnen Mandanten."""
    from app.config import Config
    p = Config.STT_PROMPT
    assert p.endswith(".") and p.count(". ") >= 3      # echte Sätze, nicht Stichwortliste
    assert p[0].isupper()
    for wort in ("Ausgangslage", "Personentagen", "Durchführungsauftrag", "Stakeholder"):
        assert wort in p, f"HERMES-Begriff fehlt: {wort}"
    # Keine projektspezifischen Begriffe im globalen Default (kommen zur Laufzeit dazu)
    for verboten in ("Serverraum", "Cloud", "zügeln", "Juris", "Strafregister"):
        assert verboten not in p, f"zu spezifisch für den Default: {verboten}"


# ---- Projektspezifischer Kontext (generisch je Mandant) ------------------- #

class _FakeSession:
    def __init__(self, name="", answers="{}"):
        self.project_name = name; self.answers_json = answers


def test_kontext_aus_session():
    from app.domains.stt.kontext import kontext_fuer_diktat
    import json as _j
    s = _FakeSession("Juris Fiat Ablösung", _j.dumps({
        "ausgangslage": {"extracted": {"text": "Die Staatsanwaltschaft nutzt VOSTRA."}}}))
    k = kontext_fuer_diktat(s)
    assert "Juris Fiat Ablösung" in k and "VOSTRA" in k


def test_kontext_leer_ohne_session():
    from app.domains.stt.kontext import kontext_fuer_diktat
    assert kontext_fuer_diktat(None) == ""
    assert kontext_fuer_diktat(_FakeSession()) == ""


def test_kontext_wird_gekuerzt():
    from app.domains.stt.kontext import kontext_fuer_diktat
    import json as _j
    lang = "Wort " * 500
    k = kontext_fuer_diktat(_FakeSession("P", _j.dumps(
        {"ausgangslage": {"raw_text": lang}})), max_zeichen=120)
    assert len(k) <= 130 and k.endswith("…")


def test_kontext_wird_an_basis_prompt_angehaengt(monkeypatch):
    gesehen = {}
    def fake_post(url, **kw):
        gesehen.update(kw.get("data") or {}); return _Resp({"text": "ok"})
    monkeypatch.setattr("app.domains.stt.transcriber.requests.post", fake_post)
    t = Transcriber(api_url="http://stt/x", api_key="k", prompt="Basis-Prompt.")
    t.transcribe(b"audio", kontext="Das Projekt heisst Juris Fiat.")
    assert gesehen["prompt"] == "Basis-Prompt. Das Projekt heisst Juris Fiat."


# ---- Nachlauf beim Stoppen (Wortende nicht abschneiden) ------------------- #

def _vorlage(*teile):
    from pathlib import Path
    from app.config import BASE_DIR
    return Path(BASE_DIR, "app", "templates", *teile).read_text(encoding="utf-8")


def test_diktat_nimmt_nach_dem_stopp_noch_stille_auf():
    """Wer auf Stopp klickt, tut das direkt nach dem letzten Wort. Ohne Nachlauf
    schneidet Whisper das Wortende ab – das darf nicht dem Mandanten aufgebuerdet
    werden ('bitte kurz nachschweigen'), sondern muss die Anwendung leisten."""
    interview = _vorlage("interview.html")
    zuordnung = _vorlage("partials", "methoden_zuordnung.html")
    # Der Nachlauf ist gross genug, dass ein ausklingendes Wort sicher drin ist.
    for text in (interview, zuordnung):
        assert int(re.search(r"NACHLAUF_MS\s*=\s*(\d+)", text).group(1)) >= 1000
    # ... und das Schliessen des Recorders haengt tatsaechlich an diesem Timer.
    assert "setTimeout(hardStop, NACHLAUF_MS)" in interview
    assert "}, NACHLAUF_MS);" in zuordnung


def test_weiter_wartet_auch_waehrend_des_nachlaufs():
    """Sonst ginge die Antwort ab, bevor das letzte Segment ueberhaupt aufgenommen ist."""
    assert "if (nachlauf || sending || sendQueue.length)" in _vorlage("interview.html")


# ---- Prompt-Echo und Wiederholungsschleife ------------------------------- #
#
# Echter Befund vom 21.07.2026: Whisper gab den mitgeschickten Kontextsatz
# «Das Projekt heisst BKI Test 4.» dreimal als Transkript aus, ohne dass er je
# gesprochen wurde. Das ist eine Folge des Vokabular-Hinweises (V0.7.6) und
# gehoert deterministisch entfernt, bevor der Text im Antwortfeld landet.

_ECHT = ("unser chef, herr buergi moechte, dass wir alle unsere services, die auf "
         "unserem internen server in unserem eigenen rechenzentrum das projekt heisst "
         "bki test 4 unemployen. das projekt heisst bki test 4 unemployen. "
         "das projekt heisst bki test 4 unemployen. "
         "der arbeiterin bessere verkaufsargumente hat.")
_PROMPT = ("Dies ist ein Diktat zu einem Projekt der oeffentlichen Verwaltung nach "
           "HERMES 2022. Das Projekt heisst BKI Test 4.")


def test_prompt_echo_wird_entfernt():
    from app.domains.stt.nachbearbeitung import bereinige
    sauber = bereinige(_ECHT, _PROMPT)
    assert "das projekt heisst bki test 4" not in sauber.lower()


def test_echtes_diktat_ueberlebt_den_schnitt():
    """Das Echo klebt an echter Sprache. Wer den ganzen Satz verwirft, verliert
    das Diktat - genau das war der erste, zu scharfe Versuch."""
    from app.domains.stt.nachbearbeitung import bereinige
    sauber = bereinige(_ECHT, _PROMPT)
    assert "herr buergi" in sauber
    assert "rechenzentrum" in sauber
    assert "verkaufsargumente" in sauber


def test_wiederholungsschleife_kollabiert():
    from app.domains.stt.nachbearbeitung import bereinige
    assert bereinige("Ein Satz. Ein Satz. Ein Satz. Noch einer.", "") == \
        "Ein Satz. Noch einer."


def test_ohne_prompt_wird_nichts_als_echo_entfernt():
    """Sagt jemand denselben Satz wirklich, bleibt er stehen."""
    from app.domains.stt.nachbearbeitung import bereinige
    assert bereinige("Das Projekt heisst BKI Test 4.", "") == \
        "Das Projekt heisst BKI Test 4."


def test_kurze_uebereinstimmungen_gelten_nicht_als_echo():
    """Sonst faellt jedes 'Ja.' oder 'Das Projekt.' dem Filter zum Opfer."""
    from app.domains.stt.nachbearbeitung import bereinige
    assert "Wir migrieren" in bereinige("Wir migrieren die Dienste.", "Das Projekt.")


def test_nie_alles_wegwerfen():
    """Ein leeres Feld sieht aus wie ein Aufnahmefehler und laesst den Nutzer
    ratlos zurueck - dann lieber das Rohtranskript zeigen."""
    from app.domains.stt.nachbearbeitung import bereinige
    assert bereinige("Das Projekt heisst BKI Test 4.", _PROMPT).strip() != ""


def test_transcriber_bereinigt_die_antwort(monkeypatch):
    """Die Bereinigung haengt am Transcriber, nicht an der Route - sonst greift
    sie beim generischen Diktat (Bemerkungsfelder) nicht."""
    monkeypatch.setattr("app.domains.stt.transcriber.requests.post",
                        lambda *a, **kw: _Resp({"text": _ECHT}))
    t = Transcriber(api_url="http://stt/x", api_key="k",
                    prompt="Dies ist ein Diktat nach HERMES 2022.")
    ergebnis = t.transcribe(b"audio", kontext="Das Projekt heisst BKI Test 4.")
    assert "das projekt heisst bki test 4" not in ergebnis.lower()
    assert "herr buergi" in ergebnis
