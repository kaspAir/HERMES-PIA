"""Beweist: alle KI-Aufrufe laufen durch die Pseudonymisierungsschicht.

Die Abnahmekriterien stehen in docs/ANBINDUNG.md Abschnitt 9. Der wichtigste Test
hier ist `test_blockiert_schlaegt_durch_generischen_except_faenger`: die Extraktion
faengt jede Ausnahme ab, um bei LLM-Ausfaellen nicht zu blockieren. Wuerde der
409-Fall dort mitgefangen, waere die Anbindung wertlos -- der Nutzer saehe ein
stilles Ersatzergebnis statt der Rueckfrage.
"""
import pytest

from app.domains.llm.client import LLMClient
from app.domains.llm.errors import (
    PseudoNichtErreichbar,
    PseudonymisierungBlockiert,
    RueckersetzungUnvollstaendig,
)
from app.domains.llm.kontext import aktueller_kontext, pseudo_kontext


class _Resp:
    def __init__(self, payload, status=200, headers=None):
        self._p = payload
        self.status_code = status
        self.headers = headers or {}

    def json(self):
        return self._p

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError(f"HTTP {self.status_code}")


_BLOCK = {
    "type": "error",
    "error": {
        "type": "pseudonymisierung_blockiert",
        "message": "1 Fundstelle(n) erfordern eine Entscheidung.",
        "pseudo": {
            "vorgang_id": "vg_1",
            "befunde": [{
                "befund_id": "bf_1", "kategorie": "person_name",
                "auszug": "Wir sprachen mit Vogt.", "treffer": "Vogt",
                "ort": {"feld": "messages[0].content", "von": 17, "bis": 21},
                "sicherheit": 0.61, "band": "unsicher",
                "grund": "kein_kontextanker_anrede", "vorschlag": "ersetzen",
                "moegliche_entscheide": ["ersetzen", "freigeben"],
            }],
        },
    },
}


# ---- Kriterium 1: kein eigener Anbieterschluessel mehr -------------------- #

def test_kein_anthropic_key_und_kein_direkter_anbieterpfad():
    """Solange die Anwendung einen eigenen Schluessel besaesse, waere das Umgehen
    der Schicht nur verboten, nicht unmoeglich."""
    from pathlib import Path

    from app.config import BASE_DIR, Config

    assert not hasattr(Config, "ANTHROPIC_API_KEY")
    assert not hasattr(Config, "VOYAGE_API_KEY")

    for rel in ("app/domains/llm/client.py", "app/domains/corpus/embeddings.py"):
        quelle = Path(BASE_DIR, rel).read_text(encoding="utf-8")
        assert "api.anthropic.com" not in quelle
        assert "api.voyageai.com" not in quelle
        assert "x-api-key" not in quelle


def test_ohne_dienst_kein_llm_client():
    """Nicht konfiguriert heisst inaktiv - nicht 'localhost raten' und auch nicht
    'ersatzweise direkt zum Anbieter'."""
    from app.config import Config
    from app.factory import create_app
    from app.shared.database import SessionLocal

    class _Cfg(Config):
        DATABASE_URL = "sqlite:///:memory:"
        SECRET_KEY = "x"
        PSEUDO_BASIS_URL = ""

    SessionLocal.remove()
    app = create_app(_Cfg)
    SessionLocal.remove()
    assert app.interview_service.llm is None


# ---- Pflicht-Kopfzeilen (Kriterium 5) ------------------------------------ #

def test_pflichtkopfzeilen_werden_gesendet(monkeypatch):
    gesehen = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        gesehen["url"] = url
        gesehen["headers"] = headers
        return _Resp({"content": [{"text": "ok"}]}, headers={"X-Pseudo-Status": "aktiv"})

    monkeypatch.setattr("app.domains.llm.client.requests.post", fake_post)
    c = LLMClient(basis_url="http://127.0.0.1:8040/anthropic", mandant="42")
    assert c.complete("sys", [{"role": "user", "content": "hi"}], projekt="session-137") == "ok"

    assert gesehen["url"] == "http://127.0.0.1:8040/anthropic/v1/messages"
    h = gesehen["headers"]
    assert h["X-Pseudo-Anwendung"] == "hermes-pia"
    assert h["X-Pseudo-Mandant"] == "42"
    assert h["X-Pseudo-Projekt"] == "session-137"
    assert "x-api-key" not in h            # der Schluessel liegt im Dienst
    assert c.letzter_status == "aktiv"


def test_projekt_kommt_aus_dem_anfragekontext(monkeypatch):
    """Der Client ist ein App-weites Singleton; der Kontext haengt an der Anfrage."""
    gesehen = {}
    monkeypatch.setattr("app.domains.llm.client.requests.post",
                        lambda url, headers=None, json=None, timeout=None:
                        (gesehen.update(headers), _Resp({"content": [{"text": "ok"}]}))[1])
    c = LLMClient(basis_url="http://x/anthropic", mandant="vorgabe")
    with pseudo_kontext(projekt=137, mandant="7"):
        c.complete("s", [])
    assert gesehen["X-Pseudo-Projekt"] == "137"
    assert gesehen["X-Pseudo-Mandant"] == "7"


def test_kontext_leckt_nicht_nach_aussen():
    """Sonst truege eine Anfrage den Mandanten der vorherigen - Zuordnungen
    landeten im falschen Topf."""
    with pseudo_kontext(projekt=1, mandant="a"):
        assert aktueller_kontext() == ("1", "a")
    assert aktueller_kontext() == ("", "")


# ---- Fehlerabbildung ------------------------------------------------------ #

def test_409_wird_zu_blockiert(monkeypatch):
    monkeypatch.setattr("app.domains.llm.client.requests.post",
                        lambda *a, **kw: _Resp(_BLOCK, status=409))
    c = LLMClient(basis_url="http://x/anthropic")
    with pytest.raises(PseudonymisierungBlockiert) as e:
        c.complete("s", [])
    assert e.value.vorgang_id == "vg_1"
    assert e.value.befunde[0]["treffer"] == "Vogt"


def test_502_wird_zu_schutzabschaltung(monkeypatch):
    monkeypatch.setattr("app.domains.llm.client.requests.post",
                        lambda *a, **kw: _Resp(
                            {"error": {"type": "rueckersetzung_unvollstaendig",
                                       "message": "Leckverdacht"}}, status=502))
    c = LLMClient(basis_url="http://x/anthropic")
    with pytest.raises(RueckersetzungUnvollstaendig):
        c.complete("s", [])


def test_dienst_weg_faellt_nicht_auf_den_anbieter_zurueck(monkeypatch):
    import requests

    def kaputt(*a, **kw):
        raise requests.ConnectionError("refused")

    monkeypatch.setattr("app.domains.llm.client.requests.post", kaputt)
    with pytest.raises(PseudoNichtErreichbar):
        LLMClient(basis_url="http://x/anthropic").complete("s", [])


# ---- Kriterium 3: DER Test (die Falle aus ANBINDUNG.md 6.2) --------------- #

@pytest.mark.parametrize("aufruf", [
    lambda llm: __import__("app.domains.interview.extraction", fromlist=["x"])
    .estimate_risk_assessment(llm, "Ein Risiko."),
    lambda llm: __import__("app.domains.interview.extraction", fromlist=["x"])
    .assess_complexity(llm, "Eine Ausgangslage."),
    lambda llm: __import__("app.domains.interview.extraction", fromlist=["x"])
    .detect_gender(llm, "Andrea Muster"),
    lambda llm: __import__("app.domains.interview.extraction", fromlist=["x"])
    .generate_followups(llm, {"id": "ziele", "title": "Ziele",
                              "interview": {"intent": "Ziele erheben"}}, "Text."),
])
def test_blockiert_schlaegt_durch_generischen_except_faenger(aufruf):
    """Jede dieser Funktionen hat ein `except Exception:`, das LLM-Ausfaelle
    absichtlich verschluckt. Der Blockierfall darf dort NICHT haengenbleiben."""
    class _Blockiert:
        def complete(self, *a, **kw):
            raise PseudonymisierungBlockiert(befunde=[{"treffer": "Vogt"}], vorgang_id="vg")

    with pytest.raises(PseudonymisierungBlockiert):
        aufruf(_Blockiert())


def test_gewoehnlicher_llm_ausfall_wird_weiterhin_verschluckt():
    """Die Gegenprobe: an der bisherigen Nachsicht gegenueber echten Ausfaellen
    darf sich nichts geaendert haben."""
    from app.domains.interview.extraction import estimate_risk_assessment

    class _Kaputt:
        def complete(self, *a, **kw):
            raise RuntimeError("Modell gerade weg")

    assert estimate_risk_assessment(_Kaputt(), "Ein Risiko.") == {}


# ---- Embedding-Weg (ANBINDUNG.md 6.5) ------------------------------------ #

def test_embeddings_laufen_ebenfalls_ueber_den_dienst(monkeypatch):
    """Dieser Weg traegt denselben Text ins Ausland wie der Chat."""
    from app.domains.corpus.embeddings import VoyageEmbedder

    gesehen = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        gesehen["url"] = url
        gesehen["headers"] = headers
        return _Resp({"data": [{"index": 0, "embedding": [0.1, 0.2]}]})

    monkeypatch.setattr("app.domains.corpus.embeddings.requests.post", fake_post)
    e = VoyageEmbedder(basis_url="http://127.0.0.1:8040/voyage", mandant="42")
    assert e.embed(["Text"]) == [[0.1, 0.2]]
    assert gesehen["url"] == "http://127.0.0.1:8040/voyage/v1/embeddings"
    assert gesehen["headers"]["X-Pseudo-Mandant"] == "42"


def test_embedder_ohne_dienst_ist_inaktiv():
    from app.domains.corpus.embeddings import VoyageEmbedder
    e = VoyageEmbedder(basis_url="")
    assert e.available is False and e.embed(["x"]) is None


# ---- Klarnamen-Sperre der Seed-Ingestion --------------------------------- #
#
# Der Korpus speichert den Chunk-TEXT im Klartext; nur die Einbettung laeuft durch
# die Schicht. Ein im Text verbliebener Name landet also in der Datenbank und kann
# ueber die RAG-Suche in ein neues Projektdokument gelangen.

def _guard():
    import importlib.util
    import sys
    from pathlib import Path

    from app.config import BASE_DIR
    spec = importlib.util.spec_from_file_location(
        "_ingest_seed", Path(BASE_DIR, "scripts", "ingest_seed_corpus.py"))
    modul = importlib.util.module_from_spec(spec)
    sys.modules["_ingest_seed"] = modul
    spec.loader.exec_module(modul)
    return modul._klarnamen_verdacht


def test_sperre_erkennt_abgekuerzten_vornamen_mit_nachnamen():
    """Genau die Form, die ohne Anrede-Anker durch die Erkennung faellt
    (der Dienst kennt diese Luecke, ANBINDUNG.md 10)."""
    verdacht = _guard()("Besprechung mit Chr. Straumann vom 04.07.2019.")
    assert "Chr. Straumann" in verdacht


def test_sperre_meldet_keine_aufzaehlung_und_kein_zum_beispiel():
    """Sonst schlaegt sie bei fast jedem Dokument an und wird abgeschaltet –
    eine Sperre, die nur noch genervt weggeklickt wird, schuetzt nichts."""
    v = _guard()("Dies gilt z. B. Anhang C sowie u. a. Vorlagen und Mio. Franken.")
    assert v == set()


def test_sperre_ist_bewusst_uebervorsichtig():
    """'Anhang B. Betrieb' ist von 'Kollege B. Betrieb' nicht unterscheidbar –
    also meldet die Sperre auch das. Das ist gewollt: ein uebersehener Name ist
    draussen und kommt nicht zurueck, ein Fehlalarm kostet nur einen Blick.
    Sie SPERRT nur, sie ersetzt nicht – entschieden wird von Hand."""
    assert _guard()("Siehe Anhang B. Betriebshandbuch.") != set()


# ---- Kriterium 3 + 4: der Blockierweg ueber die Weboberflaeche ------------ #

@pytest.fixture
def app(tmp_path):
    from app.config import Config
    from app.factory import create_app
    from app.shared.database import SessionLocal

    db = str(tmp_path / "p.db").replace("\\", "/")

    class _Cfg(Config):
        DATABASE_URL = "sqlite:///" + db
        SECRET_KEY = "x"
        PSEUDO_BASIS_URL = "http://127.0.0.1:8040"

    SessionLocal.remove()
    anwendung = create_app(_Cfg)
    SessionLocal.remove()
    yield anwendung
    SessionLocal.remove()


def _angemeldet(app):
    auth = app.auth_service
    org = auth.create_org("Org")
    auth.create_user("u@o.ch", "pw", role="org_admin", org_id=org.id,
                     can_read=True, can_write=True, can_delete=True)
    c = app.test_client()
    c.post("/login", data={"email": "u@o.ch", "password": "pw"})
    ort = c.post("/interview/start",
                 data={"project_name": "P", "projektleiter": "X"}).headers["Location"]
    return c, int(ort.rstrip("/").split("/")[-1])


class _BlockierenderLLM:
    """Verhaelt sich wie der Dienst bei einer unsicheren Fundstelle."""
    def complete(self, *a, **kw):
        raise PseudonymisierungBlockiert(
            befunde=_BLOCK["error"]["pseudo"]["befunde"], vorgang_id="vg_1")


def test_blockierter_aufruf_zeigt_dem_nutzer_die_fundstellen(app):
    """Kriterium 3: sichtbare Rueckfrage statt stillem Ersatzergebnis."""
    app.interview_service.llm = _BlockierenderLLM()
    c, sid = _angemeldet(app)

    r = c.post(f"/interview/{sid}/answer",
               data={"raw_text": "Wir sprachen mit Vogt."})

    assert r.status_code == 409                  # nicht 302 auf die naechste Frage
    seite = r.get_data(as_text=True)
    assert "Vogt" in seite                       # die Fundstelle steht da
    assert "Fehlalarm" in seite and "Personenbezug" in seite
    assert "trotzdem" not in seite.lower()       # es gibt kein 'trotzdem senden'
    # Der Originaltext wird gehalten, damit er unveraendert wiederholt werden kann
    # (der Dienst speichert ihn bewusst nicht).
    assert "Wir sprachen mit Vogt." in seite


def test_entscheid_wird_gesendet_und_aufruf_wiederholt(app, monkeypatch):
    """Kriterium 4: nach 'freigeben' laeuft derselbe Aufruf durch."""
    gesendet = {}

    def fake_entscheide(basis, befund_id, entscheid, muster, begruendung="", urheber="",
                        timeout=20):
        gesendet.update(befund_id=befund_id, entscheid=entscheid, muster=muster,
                        begruendung=begruendung, basis=basis)
        return True, ""

    monkeypatch.setattr("app.web.ui_routes.entscheide", fake_entscheide)
    c, sid = _angemeldet(app)

    r = c.post("/pseudo/entscheide", data={
        "ziel": f"/interview/{sid}/answer", "methode": "POST",
        "befund_id": "bf_1",
        "entscheid__bf_1": "freigeben",
        "muster__bf_1": "Vogt",
        "begruendung__bf_1": "Name der Fachanwendung",
        "orig__raw_text": "Wir sprachen mit Vogt.",
    })

    assert r.status_code == 200
    assert gesendet["entscheid"] == "freigeben"
    assert gesendet["muster"] == "Vogt"          # Klartext geht MIT (HMAC-Pruefung)
    assert gesendet["basis"] == "http://127.0.0.1:8040"
    # Die Wiederholung traegt exakt den urspruenglichen Rumpf.
    seite = r.get_data(as_text=True)
    assert f'action="/interview/{sid}/answer"' in seite
    assert 'name="raw_text"' in seite and "Wir sprachen mit Vogt." in seite


def test_unentschiedener_befund_bleibt_blockiert(app, monkeypatch):
    monkeypatch.setattr("app.web.ui_routes.entscheide",
                        lambda *a, **kw: (True, ""))
    c, sid = _angemeldet(app)
    r = c.post("/pseudo/entscheide", data={
        "ziel": f"/interview/{sid}/answer", "methode": "POST",
        "befund_id": "bf_1",                     # ohne entscheid__bf_1
        "orig__raw_text": "Text",
    })
    assert r.status_code == 400
    assert "blockiert" in r.get_data(as_text=True).lower()


def test_get_aufruf_wird_als_get_wiederholt(app, monkeypatch):
    """Die Praesentation wird per GET erzeugt - ein POST-Replay liefe in 405."""
    monkeypatch.setattr("app.web.ui_routes.entscheide", lambda *a, **kw: (True, ""))
    c, _ = _angemeldet(app)
    r = c.post("/pseudo/entscheide", data={
        "ziel": "/projekt/1/ergebnis/2/praesentation/x.pptx", "methode": "GET",
        "befund_id": "bf_1", "entscheid__bf_1": "ersetzen", "muster__bf_1": "Vogt",
    })
    assert r.status_code == 302
    assert r.headers["Location"].endswith("/praesentation/x.pptx")


def test_replay_nur_auf_anwendungseigene_ziele(app, monkeypatch):
    """Sonst waere die Seite eine offene Weiterleitung."""
    monkeypatch.setattr("app.web.ui_routes.entscheide", lambda *a, **kw: (True, ""))
    c, _ = _angemeldet(app)
    for ziel in ("https://example.com/x", "//example.com/x"):
        r = c.post("/pseudo/entscheide", data={
            "ziel": ziel, "methode": "GET",
            "befund_id": "b", "entscheid__b": "ersetzen", "muster__b": "V",
        })
        assert r.status_code == 400


def test_502_zeigt_fehler_und_uebernimmt_keinen_text(app):
    """Kriterium 6."""
    class _Leck:
        def complete(self, *a, **kw):
            raise RueckersetzungUnvollstaendig("Platzhalter nicht aufloesbar")

    app.interview_service.llm = _Leck()
    c, sid = _angemeldet(app)
    r = c.post(f"/interview/{sid}/answer", data={"raw_text": "Ein Text."})
    assert r.status_code == 502
    seite = r.get_data(as_text=True)
    assert "zurückgehalten" in seite or "zurueckgehalten" in seite


# ---- Der Fehler vom 21.07.: 'Fehlende Kopfzeile: X-Pseudo-Projekt' -------- #
#
# Der Kontext hing an vier dekorierten Interview-Methoden. Die Ergebnis-Module
# (Rechtsgrundlagen, Schutzbedarf, Praesentation) und der Nachweis liefen daran
# vorbei -> Kopfzeile leer -> der Dienst antwortete zu Recht mit 400.
# Jetzt setzt eine Anfrage-Bindung den Kontext fuer JEDE Route.

class _MerktKontext:
    """Haelt fest, welchen Kontext der Aufruf tatsaechlich gesehen haette."""
    def __init__(self):
        self.gesehen = []

    def complete(self, *a, **kw):
        self.gesehen.append(aktueller_kontext())
        return "{}"


def test_jede_route_setzt_den_kontext(app):
    """Nicht nur die vier frueher dekorierten Interview-Einstiegspunkte."""
    merker = _MerktKontext()
    app.interview_service.llm = merker
    c, sid = _angemeldet(app)

    c.post(f"/interview/{sid}/answer", data={"raw_text": "Eine Ausgangslage."})

    assert merker.gesehen, "es wurde gar kein LLM-Aufruf ausgeloest"
    for projekt, mandant in merker.gesehen:
        assert projekt, "X-Pseudo-Projekt waere leer -> HTTP 400 kontext_fehlt"
        assert mandant, "X-Pseudo-Mandant waere leer -> HTTP 400 kontext_fehlt"


def test_kontext_wird_aus_der_route_abgeleitet():
    from app.domains.llm.kontext import projekt_schluessel
    # Das Projekt hat Vorrang: dieselbe Person soll im PIA und in der daraus
    # abgeleiteten Rechtsgrundlagenanalyse denselben Platzhalter bekommen.
    assert projekt_schluessel({"projekt_id": 5, "ergebnis_id": 9}) == "projekt-5"
    assert projekt_schluessel({"session_id": 137}) == "session-137"
    assert projekt_schluessel({}) == ""
    assert projekt_schluessel(None) == ""


def test_kontext_wird_nach_der_anfrage_zurueckgesetzt(app):
    """Sonst truege die naechste Anfrage auf demselben Thread den fremden
    Mandanten - Zuordnungen landeten im falschen Topf."""
    c, sid = _angemeldet(app)
    c.get(f"/interview/{sid}")
    assert aktueller_kontext() == ("", "")


def test_prompts_betonen_keine_woerter_die_nachnamen_sein_koennen():
    """Der Nutzer musste ueber 'LEER' entscheiden, das er nie diktiert hat.

    Grossgeschriebene Betonungen im Prompt sind fuer die Erkennung nicht von
    Namen zu unterscheiden - «Leer», «Kosten», «Recht», «Bau» sind Schweizer
    Nachnamen. Solche Woerter gehoeren klein geschrieben; Betonung nur bei
    Funktionswoertern (NUR, NICHT, NIEMALS).
    """
    import glob
    import re
    from pathlib import Path

    from app.config import BASE_DIR

    # Grossgeschriebene Woerter, die zugleich Schweizer Nachnamen sind.
    heikel = {"LEER", "KOSTEN", "RECHT", "BAU", "SITZ", "BERG", "STEIN",
              "WINTER", "SOMMER", "FRISCH", "REICH", "JUNG", "KLEIN", "GROSS"}
    for pfad in glob.glob(str(Path(BASE_DIR, "app", "domains", "**", "*.py")),
                          recursive=True):
        text = Path(pfad).read_text(encoding="utf-8")
        # Nur Zeichenketten betrachten (Prompts), nicht Bezeichner/Kommentare.
        for zeichenkette in re.findall(r'"([^"\n]{10,})"', text):
            gefunden = heikel & set(re.findall(r"\b[A-ZÄÖÜ]{3,}\b", zeichenkette))
            assert not gefunden, f"{Path(pfad).name}: {gefunden} im Prompt-Text"


# ---- Der Befund vom 21.07.: Text kam 1:1 statt formuliert zurueck --------- #
#
# Der Client gab bei einer 200-Antwort ohne lesbaren Text schlicht '' zurueck.
# `_extract_free_text` machte daraus `_parse_json('') or {"text": raw_text}` --
# also den ROHTEXT, ohne Ausnahme, ohne Protokolleintrag. Der Projektleiter sah
# sein Diktat unveraendert im Dokument und konnte nicht erkennen, dass gar nichts
# formuliert worden war.

def test_antwort_ohne_text_wird_zum_fehler_statt_zu_leerstring(monkeypatch):
    from app.domains.llm.errors import PseudoAntwortUnlesbar

    monkeypatch.setattr("app.domains.llm.client.requests.post",
                        lambda *a, **kw: _Resp({"id": "msg_1", "content": []}))
    with pytest.raises(PseudoAntwortUnlesbar) as e:
        LLMClient(basis_url="http://x/anthropic").complete("s", [])
    # Die Meldung nennt die Felder der Antwort - sonst raet man beim Diagnostizieren.
    assert "content" in str(e.value) and "id" in str(e.value)


def test_rohtext_landet_nicht_still_im_dokument(monkeypatch):
    """Der eigentliche Schaden: das Diktat als Kapiteltext."""
    from app.domains.interview.extraction import _extract_free_text
    from app.domains.llm.errors import PseudoAntwortUnlesbar

    monkeypatch.setattr("app.domains.llm.client.requests.post",
                        lambda *a, **kw: _Resp({"content": []}))
    llm = LLMClient(basis_url="http://x/anthropic")
    with pytest.raises(PseudoAntwortUnlesbar):
        _extract_free_text(llm, "Ausgangslage", "Wir haben einen Serverraum.")


def test_antwortformen_werden_geduldig_gelesen(monkeypatch):
    """Der Dienst reicht die Anbieterform durch, koennte sie aber leicht anders
    verpacken. Was lesbar ist, soll gelesen werden - nur voellig Unlesbares
    wird zum Fehler."""
    from app.domains.llm.client import _text_aus_antwort

    assert _text_aus_antwort({"content": [{"text": "a"}, {"text": "b"}]}) == "ab"
    assert _text_aus_antwort({"content": "direkt"}) == "direkt"
    assert _text_aus_antwort({"text": "flach"}) == "flach"
    assert _text_aus_antwort({"data": {"content": [{"text": "tief"}]}}) == "tief"
    assert _text_aus_antwort({"id": "msg_1", "content": []}) == ""


def test_unlesbare_antwort_zeigt_dem_nutzer_einen_fehler(app):
    """Kein Dokument mit dem rohen Diktat darin."""
    from app.domains.llm.errors import PseudoAntwortUnlesbar

    class _Stumm:
        def complete(self, *a, **kw):
            raise PseudoAntwortUnlesbar("Die Antwort enthielt keinen Text.")

    app.interview_service.llm = _Stumm()
    c, sid = _angemeldet(app)
    r = c.post(f"/interview/{sid}/answer", data={"raw_text": "Ein Diktat."})
    assert r.status_code == 502
    assert "nicht auswertbar" in r.get_data(as_text=True)
