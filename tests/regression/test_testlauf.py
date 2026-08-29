"""Beweist: der Testlauf spielt durch, ohne zu fragen — und weist das aus.

Was hier NICHT geprüft wird: ob der erzeugte Inhalt gut ist. Das kann ein
Testlauf grundsätzlich nicht zeigen, weil Frage und Antwort aus derselben
Quelle kommen. Geprüft wird das Zusammenspiel und die Ehrlichkeit: kommt der
Lauf voran, bricht er nicht endlos, und ist hinterher erkennbar, dass kein
Mensch geurteilt hat.
"""
import json

import pytest

from app.config import Config
from app.domains.freigabe import pruefpunkte as pp
from app.domains.testlauf import service as testlauf_modul
from app.domains.testlauf.service import (
    SCHRITTE, TESTLAUF_VERMERK, TestlaufService)
from app.factory import create_app


@pytest.fixture
def app(tmp_path):
    from app.shared.database import SessionLocal

    class _Cfg(Config):
        DATABASE_URL = "sqlite:///" + str(tmp_path / "tl.db").replace("\\", "/")
        SUPERADMIN_EMAIL = "betreiber@test.ch"
        SUPERADMIN_PASSWORD = "pw-super"
        SECRET_KEY = "test-secret"
        TESTLAUF = True

    SessionLocal.remove()
    application = create_app(_Cfg)
    SessionLocal.remove()
    yield application
    SessionLocal.remove()


@pytest.fixture
def angemeldet(app):
    auth = app.auth_service
    org = auth.create_org("Org")
    org_id = org.id
    auth.create_user("pl@org.ch", "pw", org_id=org_id, can_read=True, can_write=True)
    c = app.test_client()
    c.post("/login", data={"email": "pl@org.ch", "password": "pw"})
    return c, org_id


# ---- Das Tor ------------------------------------------------------------- #

def test_ohne_schalter_gibt_es_den_testlauf_nicht(tmp_path):
    """Standardmässig AUS. Ein Knopf, der einen ganzen Auftrag samt Freigabe
    erzeugt, ohne dass jemand gefragt wurde, gehört nicht auf eine Kundenstufe."""
    from app.shared.database import SessionLocal

    class _Cfg(Config):
        DATABASE_URL = "sqlite:///" + str(tmp_path / "aus.db").replace("\\", "/")
        SECRET_KEY = "test-secret"

    SessionLocal.remove()
    anwendung = create_app(_Cfg)
    assert anwendung.testlauf_service is None
    auth = anwendung.auth_service
    org = auth.create_org("Org")
    auth.create_user("pl@org.ch", "pw", org_id=org.id, can_read=True, can_write=True)
    c = anwendung.test_client()
    c.post("/login", data={"email": "pl@org.ch", "password": "pw"})
    assert c.post("/testlauf", data={"ausgangslage": "Etwas"}).status_code == 404
    assert b"Testlauf" not in c.get("/").data
    SessionLocal.remove()


def test_mit_schalter_steht_das_formular_da(angemeldet):
    c, _ = angemeldet
    assert b"Durchspielen" in c.get("/").data


def test_ohne_ausgangslage_beginnt_nichts(angemeldet):
    c, _ = angemeldet
    antwort = c.post("/testlauf", data={"ausgangslage": "   "})
    assert antwort.status_code == 400
    assert "Ausgangslage" in antwort.data.decode("utf-8")


# ---- Der Lauf ------------------------------------------------------------- #

def _lauf(app, org_id, ausgangslage="Eine Fachanwendung ist abzulösen."):
    return app.testlauf_service.starte(
        org_id=org_id, ausgangslage=ausgangslage, projektname="Testlauf",
        projektleiter="Frau Muster", auftraggeber="Herr Beispiel")


def test_der_lauf_legt_sitzung_und_projekt_an(app, angemeldet):
    _, org_id = angemeldet
    lauf = _lauf(app, org_id)
    assert lauf.session_id and lauf.projekt_id
    assert lauf.status == "laeuft" and lauf.schritt == 0
    session = app.interview_service.get_session(lauf.session_id)
    # Die Sitzung hängt am Ergebnis-Knoten – sonst findet der Schritt
    # «Dokument» hinterher nichts, wohin er ablegen könnte.
    assert session.ergebnis_id


def test_die_ausgangslage_ist_das_einzige_vom_menschen(app, angemeldet):
    """Der erste Abschnitt bekommt den Text, jeder weitere wird LEER
    eingereicht – dann bietet HERMES PIA von sich aus einen Vorschlag an."""
    _, org_id = angemeldet
    lauf = _lauf(app, org_id, "Die Fachanwendung X ist am Ende ihres Lebenszyklus.")
    app.testlauf_service.schritt(lauf.id)
    session = app.interview_service.get_session(lauf.session_id)
    answers = json.loads(session.answers_json or "{}")
    text = ((answers.get("ausgangslage") or {}).get("extracted") or {}).get("text", "")
    assert "Lebenszyklus" in text


def test_ein_schritt_bewegt_den_lauf(app, angemeldet):
    _, org_id = angemeldet
    lauf = _lauf(app, org_id)
    zustand = app.testlauf_service.schritt(lauf.id)
    assert zustand["gesamt"] == len(SCHRITTE)
    assert zustand["protokoll"], "jeder Schritt schreibt ins Protokoll"


def test_der_lauf_bricht_nicht_endlos(app, angemeldet, monkeypatch):
    """Ein Schritt, der seinen Zustand nicht bewegt, liefe sonst ewig."""
    _, org_id = angemeldet
    monkeypatch.setattr(testlauf_modul, "HOECHSTZAHL_AUFRUFE", 3)
    lauf = _lauf(app, org_id)
    # Ein Schritt, der nie fertig wird.
    monkeypatch.setattr(TestlaufService, "_schritt_interview",
                        lambda self, l: (False, "dreht sich"))
    for _ in range(6):
        zustand = app.testlauf_service.schritt(lauf.id)
    assert zustand["status"] == "gescheitert"
    assert any("Abgebrochen" in e["text"] for e in zustand["protokoll"])


def test_ein_gescheiterter_schritt_stoppt_den_lauf_nicht(app, angemeldet, monkeypatch):
    """Ein Absturz ist ein Befund, kein Grund, die übrigen Schritte
    ungeprüft zu lassen. Genau dafür ist der Lauf da."""
    _, org_id = angemeldet
    lauf = _lauf(app, org_id)

    def kracht(self, l):
        raise RuntimeError("etwas ging schief")

    monkeypatch.setattr(TestlaufService, "_schritt_interview", kracht)
    zustand = app.testlauf_service.schritt(lauf.id)
    assert zustand["schritt"] == 1, "der Lauf geht zum nächsten Schritt weiter"
    assert any("GESCHEITERT" in e["text"] for e in zustand["protokoll"])


# ---- Die Ehrlichkeit ------------------------------------------------------ #

def test_die_freigabe_weist_sich_als_testlauf_aus(app, angemeldet):
    """Der einzige Schritt, der ein Tor übergeht: die Checkliste lässt sich
    nicht freigeben, solange eine Zeile unbewertet oder «nicht erfüllt» ist.
    Ein Testlauf, der sich hinterher nicht von einer echten Freigabe
    unterscheiden liesse, wäre eine Fälschung."""
    _, org_id = angemeldet
    lauf = _lauf(app, org_id)
    dienst = app.testlauf_service
    projekt = app.projekt_service.get_projekt(lauf.projekt_id)

    fertig, meldung = dienst._schritt_freigabe(lauf)
    assert fertig and "bestätigt" in meldung

    checkliste = app.freigabe_service.checkliste(projekt.id)
    assert checkliste.status == "freigegeben"
    assert app.freigabe_service.meilenstein(projekt.id).status == "erreicht"

    zeilen = app.freigabe_service.alle_zeilen(app.freigabe_service.zeilen(checkliste))
    gesetzte = [z for z in zeilen if TESTLAUF_VERMERK in (z.get("erlaeuterung") or "")]
    assert gesetzte, "jede automatisch gesetzte Bewertung trägt den Vermerk"
    assert all(z.get("bewertung") == pp.ERFUELLT for z in gesetzte)


def test_bereits_bewertete_zeilen_bleiben_unberuehrt(app, angemeldet):
    """Was ein Mensch bewertet hat, überschreibt der Testlauf nicht."""
    _, org_id = angemeldet
    lauf = _lauf(app, org_id)
    projekt = app.projekt_service.get_projekt(lauf.projekt_id)
    app.freigabe_service.erzeuge(projekt)
    zeilen = app.freigabe_service.zeilen(app.freigabe_service.checkliste(projekt.id))
    zeilen["projekt"] = [{"nr": "P-01", "pruefpunkt": "Von Hand",
                          "bewertung": pp.TEILWEISE, "erlaeuterung": "geprüft"}]
    app.freigabe_service.speichere_zeilen(projekt.id, zeilen)

    app.testlauf_service._schritt_freigabe(lauf)
    danach = app.freigabe_service.zeilen(app.freigabe_service.checkliste(projekt.id))
    von_hand = danach["projekt"][0]
    assert von_hand["bewertung"] == pp.TEILWEISE
    assert von_hand["erlaeuterung"] == "geprüft"


def test_ein_fremder_lauf_ist_nicht_einsehbar(app, angemeldet):
    """Mandantentrennung gilt auch für Testläufe."""
    c, org_id = angemeldet
    lauf_id = _lauf(app, org_id).id
    andere_id = app.auth_service.create_org("Andere").id
    app.auth_service.create_user("x@andere.ch", "pw", org_id=andere_id,
                                 can_read=True, can_write=True)
    fremd = app.test_client()
    fremd.post("/login", data={"email": "x@andere.ch", "password": "pw"})
    assert fremd.get(f"/testlauf/{lauf_id}").status_code == 404
    assert fremd.post(f"/testlauf/{lauf_id}/schritt").status_code == 404


def test_der_schritt_antwortet_immer_json(app, angemeldet, monkeypatch):
    """Sonst bekommt der Browser eine HTML-Fehlerseite, an der er scheitert."""
    c, org_id = angemeldet
    lauf_id = _lauf(app, org_id).id

    def kracht(self, lauf_id):
        raise RuntimeError("kaputt")

    monkeypatch.setattr(TestlaufService, "schritt", kracht)
    antwort = c.post(f"/testlauf/{lauf_id}/schritt")
    assert antwort.status_code == 500
    assert "kaputt" in antwort.get_json()["fehler"]
