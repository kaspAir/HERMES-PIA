"""Projektstruktur: Instanziierung der Initialisierung, Katalog, Migration."""
import pytest

from app.config import Config
from app.factory import create_app
from app.domains.projekt.reference import (
    ERGEBNISTYPEN,
    ERG_PIA,
    INITIALISIERUNG,
    MODUL_CODES,
    MODUL_STEUERUNG,
)


@pytest.fixture
def app(tmp_path):
    from app.shared.database import SessionLocal

    db_path = str(tmp_path / "struktur.db").replace("\\", "/")

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


def _login(client, email, pw):
    return client.post("/login", data={"email": email, "password": pw})


# ---- Referenz-Katalog ------------------------------------------------- #

def test_katalog_ist_konsistent():
    # Jeder Ergebnistyp verweist auf eines der drei Module und hat Aufgabe + Rolle.
    for typ, info in ERGEBNISTYPEN.items():
        assert info["modul"] in MODUL_CODES, typ
        assert info.get("aufgabe"), typ
        assert info.get("rolle"), typ
    # Die Vorlage hat genau die drei Module und drei Meilensteine.
    assert {m["code"] for m in INITIALISIERUNG["module"]} == MODUL_CODES
    assert len(INITIALISIERUNG["meilensteine"]) == 3


# ---- Instanziierung --------------------------------------------------- #

def test_create_projekt_instanziiert_initialisierung(app):
    svc = app.projekt_service
    p = svc.create_projekt(org_id=1, name="Testprojekt", start_datum="2026-09-01")
    pid = p.id

    phase = svc.phase_initialisierung(pid)
    assert phase is not None and phase.code == "initialisierung"

    module = {m.code for m in svc.module(pid)}
    assert module == MODUL_CODES

    ms = svc.meilensteine(pid)
    codes = [m.code for m in ms]
    assert codes == ["projektinitialisierungsfreigabe", "weiteres_vorgehen",
                     "durchfuehrungsfreigabe"]
    # Projektinitialisierungsfreigabe = Phasenstart = geplanter Starttermin.
    start = ms[0]
    assert start.ist_start == 1 and start.datum == "2026-09-01"


def test_pia_ergebnis_landet_in_projektsteuerung(app):
    svc = app.projekt_service
    p = svc.create_projekt(org_id=1, name="P")
    erg = svc.add_ergebnis(p.id, ERG_PIA, titel="P")

    modul = next(m for m in svc.module(p.id) if m.id == erg.modul_id)
    assert modul.code == MODUL_STEUERUNG
    assert erg.rolle == "Auftraggeber"
    assert erg.aufgabe == "Entscheid Projektinitialisierungsfreigabe treffen"


# ---- Migration bestehender PIAs --------------------------------------- #

def test_backfill_wickelt_bestehende_pia_ein(app):
    svc = app.projekt_service
    iv = app.interview_service

    # Zwei PIAs direkt (am Strukturaufbau vorbei) anlegen -> unverknüpft.
    s1 = iv.start_session(method_id="hermes_pia", project_name="Alt 1", org_id=7)
    s2 = iv.start_session(method_id="hermes_pia", project_name="Alt 2", org_id=7)
    id1, id2 = s1.id, s2.id
    assert iv.get_session(id1).ergebnis_id is None

    n = svc.backfill_sessions(iv.all_sessions())
    assert n == 2

    # Beide sind nun verknüpft, je ein Projekt mit PIA in Projektsteuerung.
    s1 = iv.get_session(id1)
    assert s1.ergebnis_id is not None
    projekte = svc.projekte_for_org(7)
    assert {p.name for p in projekte} == {"Alt 1", "Alt 2"}
    for p in projekte:
        ergs = svc.ergebnisse(p.id)
        assert [e.ergebnistyp for e in ergs] == [ERG_PIA]

    # Idempotent: nochmaliges Backfill wickelt nichts erneut ein.
    assert svc.backfill_sessions(iv.all_sessions()) == 0


# ---- Neue PIA wird beim Anlegen eingewickelt (Route) ------------------ #

def test_interview_start_legt_projekt_an(app):
    auth = app.auth_service
    org = auth.create_org("Org")
    auth.create_user("pl@org.ch", "pw", org_id=org.id,
                     can_read=True, can_write=True, can_delete=False)
    org_id = org.id

    c = app.test_client()
    _login(c, "pl@org.ch", "pw")
    c.post("/interview/start",
           data={"project_name": "Neubau", "projektleiter": "Frau Muster",
                 "start_datum": "2026-10-01"})

    projekte = app.projekt_service.projekte_for_org(org_id)
    assert len(projekte) == 1
    p = projekte[0]
    assert p.name == "Neubau"
    ergs = app.projekt_service.ergebnisse(p.id)
    assert [e.ergebnistyp for e in ergs] == [ERG_PIA]
    # Meilenstein-Start trägt das geplante Startdatum.
    start = app.projekt_service.meilensteine(p.id)[0]
    assert start.datum == "2026-10-01"


# ---- Navigation / UI (Schritt 2) -------------------------------------- #

def _client_mit_projekt(app, can_delete=False):
    """Loggt einen Benutzer ein, legt ein Projekt (+PIA) über die Route an
    und liefert (client, org_id, projekt_id, session_id)."""
    auth = app.auth_service
    org = auth.create_org("Org")
    auth.create_user("pl@org.ch", "pw", org_id=org.id,
                     can_read=True, can_write=True, can_delete=can_delete)
    org_id = org.id
    c = app.test_client()
    _login(c, "pl@org.ch", "pw")
    c.post("/interview/start", data={"project_name": "Baubewilligungen",
                                     "projektleiter": "Frau Muster"})
    p = app.projekt_service.projekte_for_org(org_id)[0]
    erg = app.projekt_service.ergebnisse(p.id)[0]
    session = app.interview_service.session_for_ergebnis(erg.id)
    return c, org_id, p.id, session.id


def test_startseite_listet_projekte(app):
    c, org_id, pid, sid = _client_mit_projekt(app)
    html = c.get("/").get_data(as_text=True)
    assert "Projekte" in html
    assert "Baubewilligungen" in html
    assert f"/projekt/{pid}" in html


def test_projekt_detail_zeigt_struktur(app):
    c, org_id, pid, sid = _client_mit_projekt(app)
    html = c.get(f"/projekt/{pid}").get_data(as_text=True)
    # Drei Module + PIA im richtigen Modul + Meilensteine sichtbar.
    assert "Projektsteuerung" in html
    assert "Projektgrundlagen" in html
    assert "Projektinitialisierungsauftrag" in html
    assert "Projektinitialisierungsfreigabe" in html
    # Link in die PIA (Interview).
    assert f"/interview/{sid}" in html


def test_projekt_detail_fremde_org_verboten(app):
    c, org_id, pid, sid = _client_mit_projekt(app)
    auth = app.auth_service
    other = auth.create_org("Andere")
    auth.create_user("fremd@x.ch", "pw", org_id=other.id, can_read=True)
    cb = app.test_client()
    _login(cb, "fremd@x.ch", "pw")
    assert cb.get(f"/projekt/{pid}").status_code == 403


def test_projekt_loeschen_entfernt_struktur_und_pia(app):
    c, org_id, pid, sid = _client_mit_projekt(app, can_delete=True)
    c.post(f"/projekt/{pid}/delete")
    assert app.projekt_service.get_projekt(pid) is None
    assert app.interview_service.get_session(sid) is None
    assert app.projekt_service.projekte_for_org(org_id) == []
