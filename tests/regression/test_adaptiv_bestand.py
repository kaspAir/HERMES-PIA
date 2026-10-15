"""Bestandsschutz: bestehende Sessions, Umstellung, Rückfallweg, Löschung.

Zugeordneter Akzeptanzfall: AT23 – bestehende Sessions und Ergebnis-
Schnittstellen bleiben benutzbar; Migration und Rückfall sind nachgewiesen;
Herkunft und Bestätigung alter Daten werden nicht erfunden.
"""
import json

import pytest

from app.domains.ergebnisse import pia_quelle
from app.domains.interview.adaptiv.models import PiaAussage, PiaNachricht, PiaRueckmeldung
from app.shared.database import SessionLocal
from tests.regression.adaptiv_hilfen import ModellDouble, app, dienst  # noqa: F401

# Ein Stand des bisherigen Ablaufs – erfunden, im Format von answers_json.
ALT = {
    "ausgangslage": {"raw_text": "…", "complete": True,
                     "extracted": {"text": "Das Beispielamt erfasst Gesuche doppelt."}},
    "ziele": {"complete": True, "extracted": [
        {"nr": "01", "kategorie": "Systemziel", "beschreibung": "Gesuche nur einmal erfassen",
         "messgroesse": "Keine Doppelerfassung", "prioritaet": "Hoch"}]},
    "risiken": {"complete": True, "extracted": [
        {"nr": "PR01", "beschreibung": "Fachleute kaum verfügbar", "ew": "Hoch = 3",
         "ag": "Mittel = 2", "risikozahl": "6", "massnahmen": "Früh planen"}]},
    "kosten": {"complete": True, "extracted": [
        {"phase": "Total Initialisierung", "betrag": "12000"}]},
}


@pytest.fixture
def bestand(app):
    org = app.auth_service.create_org("Beispielamt").id
    s = app.interview_service.start_session(method_id="hermes_pia", project_name="Bestand",
                                            org_id=org, created_by="Kim Muster",
                                            auftraggeber="Robin Beispiel")
    db = SessionLocal()
    sess = db.get(type(s), s.id)
    sess.answers_json = json.dumps(ALT, ensure_ascii=False)
    db.commit()
    return {"org": org, "sid": s.id, "d": dienst(app, ModellDouble())}


def _aussagen(sid):
    return SessionLocal().query(PiaAussage).filter(PiaAussage.session_id == sid).all()


def test_at23_umstellung_sichert_den_alten_stand(app, bestand):
    vorher = app.interview_service.get_session(bestand["sid"]).answers_json
    bestand["d"].umstellen(bestand["sid"])
    s = app.interview_service.get_session(bestand["sid"])
    assert s.modus == "adaptiv"
    assert s.answers_vor_umstellung_json == vorher


def test_at23_herkunft_und_bestaetigung_werden_nicht_erfunden(app, bestand):
    bestand["d"].umstellen(bestand["sid"])
    aussagen = [a for a in _aussagen(bestand["sid"]) if a.status == "aktiv"]
    assert aussagen
    assert {a.herkunft for a in aussagen} == {"altbestand"}
    assert {a.art for a in aussagen} == {"uebernommen"}
    assert not any(a.bestaetigt for a in aussagen)
    # Berechnete Kosten sind keine Angabe – sie werden neu berechnet.
    assert not any("12000" in a.inhalt for a in aussagen)


def test_at23_inhalte_bleiben_im_dokument(app, bestand):
    bestand["d"].umstellen(bestand["sid"])
    answers = json.loads(app.interview_service.get_session(bestand["sid"]).answers_json)
    assert "doppelt" in answers["ausgangslage"]["extracted"]["text"]
    ziele = [z for z in answers["ziele"]["extracted"] if z.get("_herkunft") == "altbestand"]
    assert ziele and ziele[0]["beschreibung"] == "Gesuche nur einmal erfassen"
    risiko = answers["risiken"]["extracted"][0]
    assert risiko["risikozahl"] == "6" and risiko["nr"] == "PR01"


def test_at23_unbestaetigter_altbestand_blockiert_den_abschluss(app, bestand):
    d, sid = bestand["d"], bestand["sid"]
    d.umstellen(sid)
    blocker = d.abschluss(sid, "pruefen")["abschluss"]["blocker"]
    assert any(b["id"] == "ALTBESTAND" for b in blocker)
    alle = [a.schluessel for a in _aussagen(sid) if a.status == "aktiv"]
    d.sammelbestaetigung(sid, alle)
    blocker = d.abschluss(sid, "pruefen")["abschluss"]["blocker"]
    assert not any(b["id"] == "ALTBESTAND" for b in blocker)


def test_at23_rueckfall_stellt_den_alten_stand_wieder_her(app, bestand):
    d, sid = bestand["d"], bestand["sid"]
    vorher = app.interview_service.get_session(sid).answers_json
    d.umstellen(sid)
    d.zurueck_zum_bisherigen_ablauf(sid)
    s = app.interview_service.get_session(sid)
    assert s.modus is None and s.answers_json == vorher
    assert not [a for a in _aussagen(sid) if a.status == "aktiv"]
    # Erneute Umstellung beginnt sauber – keine Verdopplung.
    d.umstellen(sid)
    aktiv = [a for a in _aussagen(sid) if a.status == "aktiv"]
    assert len(aktiv) == len({a.inhalt for a in aktiv})


def test_at23_alte_schreibwege_beschaedigen_keine_adaptive_session(app, bestand):
    d, sid = bestand["d"], bestand["sid"]
    d.umstellen(sid)
    app.auth_service.create_user("pl@beispiel.example", "pw", org_id=bestand["org"],
                                 can_read=True, can_write=True)
    c = app.test_client()
    c.post("/login", data={"email": "pl@beispiel.example", "password": "pw"})
    vorher = app.interview_service.get_session(sid).answers_json
    assert c.post(f"/interview/{sid}/answer", data={"raw_text": "x"}).status_code == 409
    assert c.post(f"/interview/{sid}/reprocess").status_code == 409
    assert c.post(f"/interview/{sid}/followup", data={"risk_id": "r"}).status_code == 409
    assert c.get(f"/interview/{sid}/edit/ziele").status_code == 409
    assert c.post(f"/interview/{sid}/edit/ausgangslage", data={"raw_text": "x"}).status_code == 409
    assert app.interview_service.get_session(sid).answers_json == vorher


def test_at23_umstellung_und_rueckfall_ueber_die_oberflaeche(app, bestand):
    sid = bestand["sid"]
    app.auth_service.create_user("pl2@beispiel.example", "pw", org_id=bestand["org"],
                                 can_read=True, can_write=True)
    c = app.test_client()
    c.post("/login", data={"email": "pl2@beispiel.example", "password": "pw"})
    assert "Auf das adaptive Interview umstellen" in c.get(f"/interview/{sid}").data.decode()
    c.post(f"/interview/{sid}/umstellen")
    seite = c.get(f"/interview/{sid}").data.decode()
    assert 'id="ai-erkannt"' in seite and "Zurück zum bisherigen Ablauf" in seite
    c.post(f"/interview/{sid}/zurueck-zum-bisherigen-ablauf")
    assert app.interview_service.get_session(sid).modus is None


def test_at23_ergebnis_schnittstelle_liest_die_adaptive_projektion(app):
    from tools.fall_durchspielen import spiele_in
    _, sid, _, _ = spiele_in(app, "F-02")
    abschnitte, _, herkunft = pia_quelle.quelle(session=app.interview_service.get_session(sid))
    assert herkunft == "interview"
    assert "Registerdienste" in abschnitte["ausgangslage"]["extracted"]["text"]
    assert any(z.get("kategorie") == "Systemziel" for z in abschnitte["ziele"]["extracted"])


def test_loeschen_entfernt_gespraech_aussagen_und_rueckmeldungen(app, bestand):
    d, sid = bestand["d"], bestand["sid"]
    d.umstellen(sid)
    d.rueckmeldung(sid, "frage_unklar")
    assert _aussagen(sid)
    app.interview_service.delete_session(sid)
    db = SessionLocal()
    for modell in (PiaAussage, PiaNachricht, PiaRueckmeldung):
        assert db.query(modell).filter(modell.session_id == sid).count() == 0
