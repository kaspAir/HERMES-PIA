"""Pseudonymisierung im adaptiven Interview.

Der Entscheidungsweg ist derselbe wie im bisherigen Interview: hält die
Pseudonymisierung einen Beitrag an, geht NICHTS an das Modell; der Beitrag
bleibt gespeichert; die Projektleitung entscheidet je Fundstelle; danach wird
derselbe Beitrag unverändert verarbeitet. Es gibt kein «trotzdem senden».

Zugeordnet: Auftrag Abschnitt 12 (vorhandene Datenschutzfunktionen
erhalten), AT24 (Sicherheit).
"""
import json

import pytest

from app.domains.interview.adaptiv.models import PiaAussage, PiaNachricht
from app.domains.llm.kontext import aktueller_kontext
from app.shared.database import SessionLocal
from tests.regression.adaptiv_hilfen import ModellDouble, app, neu, ops  # noqa: F401
from tests.regression.test_pseudonymisierung import _BlockierenderLLM


class _MerktKontext(ModellDouble):
    def __init__(self):
        super().__init__()
        self.kontexte = []

    def complete(self, system, messages, max_tokens=1024, **kw):
        self.kontexte.append(aktueller_kontext())
        return super().complete(system, messages, max_tokens, **kw)


@pytest.fixture
def umgebung(app):
    org = app.auth_service.create_org("Musteramt").id
    app.auth_service.create_user("pl@muster.example", "pw", org_id=org,
                                 can_read=True, can_write=True)
    c = app.test_client()
    c.post("/login", data={"email": "pl@muster.example", "password": "pw"})
    c.post("/interview/start", data={"project_name": "Ablösung", "projektleiter": "Sam Muster"})
    sid = app.interview_service.sessions_for_org(org)[0].id
    return {"c": c, "sid": sid}


def _beitrag(c, sid, text, anfrage="a-1"):
    return c.post(f"/interview/{sid}/beitrag", data=json.dumps({"text": text, "anfrage_id": anfrage}),
                  content_type="application/json")


def test_adaptive_route_setzt_mandant_und_projekt(app, umgebung):
    merker = _MerktKontext()
    app.adaptiv_service.llm = merker
    _beitrag(umgebung["c"], umgebung["sid"], "Eine Ausgangslage.")
    assert merker.kontexte
    for projekt, mandant in merker.kontexte:
        assert projekt and mandant


def test_blockierter_beitrag_bleibt_gespeichert_und_nichts_wird_uebernommen(app, umgebung):
    app.adaptiv_service.llm = _BlockierenderLLM()
    r = _beitrag(umgebung["c"], umgebung["sid"], "Wir sprachen mit Vogt.")
    assert r.status_code == 200
    daten = r.get_json()
    assert "angehalten" in daten["fehler"] and daten["blockiert_nachricht"]
    m = SessionLocal().get(PiaNachricht, daten["blockiert_nachricht"])
    assert m.status == "blockiert" and m.text == "Wir sprachen mit Vogt."
    assert SessionLocal().query(PiaAussage).filter(
        PiaAussage.session_id == umgebung["sid"]).count() == 0


def test_erneut_verarbeiten_fuehrt_ueber_die_entscheidungsseite(app, umgebung):
    c, sid = umgebung["c"], umgebung["sid"]
    app.adaptiv_service.llm = _BlockierenderLLM()
    nid = _beitrag(c, sid, "Wir sprachen mit Vogt.").get_json()["blockiert_nachricht"]
    url = f"/interview/{sid}/nachricht/{nid}/verarbeiten"

    # Noch blockiert: die Entscheidungsseite mit Fundstelle und Replay-Ziel.
    seite = c.post(url)
    assert seite.status_code == 409
    html = seite.get_data(as_text=True)
    assert "Vogt" in html and url in html and "trotzdem" not in html.lower()

    # Nach dem Entscheid läuft derselbe Aufruf durch – ohne neue Nachricht.
    app.adaptiv_service.llm = ModellDouble(aussagen=[ops(neu(
        "Das Team sprach mit der Fachstelle", ("ausgangslage", {})))])
    vorher = SessionLocal().query(PiaNachricht).filter(PiaNachricht.session_id == sid).count()
    r = c.post(url)
    assert r.status_code == 302
    db = SessionLocal()
    assert db.get(PiaNachricht, nid).status == "verarbeitet"
    assert db.query(PiaNachricht).filter(PiaNachricht.session_id == sid,
                                         PiaNachricht.rolle == "benutzer").count() == 1
    assert db.query(PiaNachricht).filter(PiaNachricht.session_id == sid).count() == vorher
    assert db.query(PiaAussage).filter(PiaAussage.session_id == sid).count() == 1
    # Ein verarbeiteter Beitrag wird nicht ein zweites Mal ausgewertet.
    assert c.post(url).status_code == 409


def test_fremder_mandant_kann_nicht_erneut_verarbeiten(app, umgebung):
    app.adaptiv_service.llm = _BlockierenderLLM()
    nid = _beitrag(umgebung["c"], umgebung["sid"], "Text").get_json()["blockiert_nachricht"]
    fremd = app.auth_service.create_org("Fremdamt").id
    app.auth_service.create_user("x@fremd.example", "pw", org_id=fremd,
                                 can_read=True, can_write=True)
    c2 = app.test_client()
    c2.post("/login", data={"email": "x@fremd.example", "password": "pw"})
    assert c2.post(f"/interview/{umgebung['sid']}/nachricht/{nid}/verarbeiten").status_code == 403
