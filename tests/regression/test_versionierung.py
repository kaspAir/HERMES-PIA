"""Beweist: die Versionierung ist EIN Baustein für alle Ergebnisse.

Jedes erzeugte Dokument braucht dasselbe – Nummer, Änderungsprotokoll und die
Angabe, was sich seit der letzten Ausgabe geändert hat. Beim PIA war das im
Interview-Dienst eingebaut; die Rechtsgrundlagenanalyse hätte es kopieren
müssen, die Schutzbedarfs- und die Beschaffungsanalyse danach ebenso. Beim
dritten Mal wäre es dreimal verschieden.

Der Baustein kennt deshalb kein Dokument, nur einen Vertrag: ein Träger hat
doc_version, changelog_json, last_snapshot_json und answers_json.
"""
import json
from datetime import date

import pytest

from app.shared import versionierung


class _Traeger:
    """Irgendein Objekt mit dem Vertrag – mehr braucht der Baustein nicht."""
    def __init__(self, version="0.1", answers=None, snapshot=None, changelog=None):
        self.doc_version = version
        self.answers_json = json.dumps(answers or {}, ensure_ascii=False)
        self.last_snapshot_json = json.dumps(snapshot or {}, ensure_ascii=False)
        self.changelog_json = json.dumps(changelog or [], ensure_ascii=False)


# ---- Die Zählweise ------------------------------------------------------- #

@pytest.mark.parametrize("aktuell,art,erwartet", [
    ("0.1", "minor", "0.2"),
    ("0.1", "patch", "0.1.1"),
    ("0.1.1", "minor", "0.2"),
    ("0.1.1", "patch", "0.1.2"),
    ("1.9", "minor", "1.10"),
    ("0.0", "minor", "0.1"),
])
def test_die_zaehlweise_bleibt_die_des_pia(aktuell, art, erwartet):
    assert versionierung.naechste_version(aktuell, art) == erwartet


def test_unsinnige_versionen_werfen_nicht():
    """Ein kaputter Wert in der Datenbank darf den Download nicht verhindern."""
    assert versionierung.naechste_version(None) == "0.1"
    assert versionierung.naechste_version("") == "0.1"
    assert versionierung.naechste_version("Entwurf") == "0.1"
    # Nur das kaputte Teilstueck wird zu 0 - die uebrigen bleiben, sonst
    # verlöre man eine Historie wegen eines Tippfehlers.
    assert versionierung.naechste_version("1.x.3", "patch") == "1.0.4"


def test_pia_und_baustein_rechnen_gleich():
    """Eine Rechenweise, nicht eine je Dokument."""
    from app.domains.interview.service import _bump_version

    for aktuell in ("0.0", "0.1", "0.1.1", "2.7"):
        for art in ("minor", "patch"):
            assert _bump_version(aktuell, art) == \
                versionierung.naechste_version(aktuell, art)


# ---- Was hat sich geändert? ---------------------------------------------- #

def test_geaenderte_abschnitte_werden_erkannt():
    t = _Traeger(
        answers={"ziele": {"extracted": {"text": "neu"}},
                 "risiken": {"extracted": {"text": "gleich"}}},
        snapshot={"ziele": {"extracted": {"text": "alt"}},
                  "risiken": {"extracted": {"text": "gleich"}}})
    ids = [a["id"] for a in versionierung.geaenderte_abschnitte(t)]
    assert ids == ["ziele"]


def test_auch_tabellen_gelten_als_aenderung():
    """Der PIA verglich nur ``extracted.text`` und übersah damit JEDE Änderung
    in einer Tabelle – eine geänderte Kostenzeile galt als «nichts geändert»."""
    t = _Traeger(
        answers={"kosten": {"extracted": [{"posten": "A", "betrag": "200"}]}},
        snapshot={"kosten": {"extracted": [{"posten": "A", "betrag": "100"}]}})
    assert [a["id"] for a in versionierung.geaenderte_abschnitte(t)] == ["kosten"]


def test_neue_abschnitte_sind_aenderungen():
    t = _Traeger(answers={"ziele": {"extracted": {"text": "x"}}}, snapshot={})
    assert [a["id"] for a in versionierung.geaenderte_abschnitte(t)] == ["ziele"]


def test_nachweisfelder_zaehlen_nicht_als_inhalt():
    """Felder mit führendem Unterstrich tragen Herkunft und Protokoll – sie
    sind kein Dokumentinhalt und dürfen keine Version auslösen."""
    t = _Traeger(answers={"_skills": [{"name": "x"}], "_kette": {"a": 1}},
                 snapshot={})
    assert versionierung.geaenderte_abschnitte(t) == []


def test_beschriftung_und_reihenfolge_folgen_dem_dokument():
    t = _Traeger(answers={"risiken": {"extracted": {"text": "r"}},
                          "ziele": {"extracted": {"text": "z"}}},
                 snapshot={})
    abschnitte = [{"id": "ziele", "number": "2", "title": "Ziele"},
                  {"id": "risiken", "number": "8", "title": "Risiken"}]
    raus = versionierung.geaenderte_abschnitte(t, abschnitte)
    assert [a["number"] for a in raus] == ["2", "8"]
    assert raus[0]["title"] == "Ziele"


def test_ohne_beschriftung_dient_die_kennung_als_titel():
    """So funktioniert der Baustein auch für Ergebnisse ohne Methodenmodell."""
    t = _Traeger(answers={"eigenes_kapitel": {"extracted": {"text": "x"}}})
    assert versionierung.geaenderte_abschnitte(t)[0]["title"] == "eigenes_kapitel"


# ---- Eintragen ----------------------------------------------------------- #

def test_eintragen_setzt_version_protokoll_und_schnappschuss():
    t = _Traeger(version="0.2", answers={"ziele": {"extracted": {"text": "neu"}}})
    neu, protokoll = versionierung.eintragen(
        t, art="minor", name="A. Muster", bemerkungen="Ziele geschärft",
        heute=date(2026, 7, 27))

    assert neu == "0.3" and t.doc_version == "0.3"
    assert protokoll[-1] == {"version": "0.3", "name": "A. Muster",
                             "datum": "27.07.2026",
                             "bemerkungen": "Ziele geschärft"}
    # Ab jetzt gilt alles Weitere wieder als Änderung.
    assert t.last_snapshot_json == t.answers_json
    assert versionierung.geaenderte_abschnitte(t) == []


def test_das_protokoll_waechst_und_verliert_nichts():
    t = _Traeger(version="0.1", changelog=[{"version": "0.1", "name": "",
                                            "datum": "01.01.2026",
                                            "bemerkungen": "Erstfassung"}])
    versionierung.eintragen(t, heute=date(2026, 7, 27))
    protokoll = json.loads(t.changelog_json)
    assert [e["version"] for e in protokoll] == ["0.1", "0.2"]


def test_stand_liefert_alles_zusammen():
    t = _Traeger(version="0.4", answers={"ziele": {"extracted": {"text": "x"}}})
    s = versionierung.stand(t)
    assert s["current_version"] == "0.4"
    assert s["changelog"] == []
    assert [a["id"] for a in s["changed_sections"]] == ["ziele"]


# ---- Der Anschluss der Rechtsgrundlagenanalyse --------------------------- #

def test_der_entwurf_traegt_den_vertrag():
    """Ohne diese Felder könnte der Baustein die Analyse nicht bedienen."""
    from app.domains.ergebnisse.models import ErgebnisEntwurf

    spalten = {c.name for c in ErgebnisEntwurf.__table__.columns}
    assert {"doc_version", "changelog_json", "last_snapshot_json",
            "answers_json"} <= spalten


def test_die_seite_ist_dokumentneutral():
    """Sie wird von PIA UND Rechtsgrundlagenanalyse benutzt – ein fest
    eingebautes «PIA» hätte die zweite Nutzung verhindert."""
    from pathlib import Path

    from app.config import BASE_DIR
    v = Path(BASE_DIR, "app", "templates", "version_bump.html").read_text(
        encoding="utf-8")
    assert "{{ dokumentname }}" in v
    assert "{{ titel }}" in v
    assert "PIA herunterladen" not in v
    assert "interview_workspace" not in v

@pytest.fixture
def app(tmp_path):
    from app.config import Config
    from app.factory import create_app
    from app.shared.database import SessionLocal

    class _Cfg(Config):
        DATABASE_URL = "sqlite:///" + str(tmp_path / "v.db").replace("\\", "/")
        SECRET_KEY = "x"
        PSEUDO_BASIS_URL = ""

    SessionLocal.remove()
    anwendung = create_app(_Cfg)
    SessionLocal.remove()
    yield anwendung
    SessionLocal.remove()


# ---- Die Routen werden AUFGERUFEN, nicht nur geschrieben ----------------- #
#
# Zwei Fehler hintereinander an neu gebauten Routen und Schritten – ein
# NameError und ein AttributeError – gingen durch die ganze Suite, weil kein
# Test sie ausführte. Beide waren beim ersten Klick sofort sichtbar. Diese
# Tests rufen die Seiten wirklich auf.

def _projekt_mit_entwurf(app):
    """Ein angemeldeter Client, ein Projekt und ein Entwurf mit Inhalt."""
    from app.domains.ergebnisse.models import ErgebnisEntwurf
    from app.domains.projekt.models import Projekt
    from app.shared.database import SessionLocal

    auth = app.auth_service
    org = auth.create_org("Org")
    org_id = org.id                      # die Sitzung wird zwischendurch geleert
    auth.create_user("a@b.ch", "pw", role="org_admin", org_id=org_id,
                     can_read=True, can_write=True, can_delete=True)
    c = app.test_client()
    c.post("/login", data={"email": "a@b.ch", "password": "pw"})

    db = SessionLocal()
    projekt = Projekt(name="Testprojekt", org_id=org_id)
    db.add(projekt)
    db.commit()
    db.add(ErgebnisEntwurf(
        projekt_id=projekt.id, ergebnistyp="rechtsgrundlagenanalyse",
        doc_version="0.1",
        answers_json=json.dumps({"konsequenzen": {"extracted": {"text": "x"}}})))
    db.commit()
    projekt_id = projekt.id
    db.add(ErgebnisEntwurf(
        projekt_id=projekt_id, ergebnistyp="rechtsgrundlagenanalyse",
        doc_version="0.1",
        answers_json=json.dumps({"konsequenzen": {"extracted": {"text": "x"}}})))
    db.commit()
    return c, projekt_id


def test_die_versionsseite_der_rga_laesst_sich_oeffnen(app):
    """Gemessen: «AttributeError: 'User' object has no attribute 'get'» beim
    ersten Klick. current_user() liefert ein Objekt, kein Wörterbuch."""
    c, projekt_id = _projekt_mit_entwurf(app)
    r = c.get(f"/projekt/{projekt_id}/rechtsgrundlagen/version")
    assert r.status_code == 200, r.get_data(as_text=True)[:300]
    text = r.get_data(as_text=True)
    assert "Rechtsgrundlagenanalyse herunterladen" in text
    assert "0.1" in text


def test_der_versionseintrag_erhoeht_und_leitet_zum_download(app):
    c, projekt_id = _projekt_mit_entwurf(app)
    r = c.post(f"/projekt/{projekt_id}/rechtsgrundlagen/version",
               data={"bump_type": "minor", "bemerkungen": "Erste Fassung"})
    assert r.status_code in (302, 303), r.get_data(as_text=True)[:300]
    assert "_Rechtsgrundlagenanalyse_V0.2.docx" in r.headers["Location"]

    # Und der Eintrag steht im Protokoll, mit Urheber.
    from app.domains.ergebnisse.models import ErgebnisEntwurf
    from app.shared.database import SessionLocal
    zeile = SessionLocal().query(ErgebnisEntwurf).filter(
        ErgebnisEntwurf.projekt_id == projekt_id).first()
    assert zeile.doc_version == "0.2"
    protokoll = json.loads(zeile.changelog_json)
    assert protokoll[-1]["bemerkungen"] == "Erste Fassung"
    assert protokoll[-1]["name"] == "a@b.ch"


def test_ohne_entwurf_bleibt_die_seite_bedienbar(app):
    """Wer die Seite vor der ersten Erzeugung öffnet, darf keinen Absturz
    sehen."""
    from app.domains.projekt.models import Projekt
    from app.shared.database import SessionLocal

    auth = app.auth_service
    org = auth.create_org("Org2")
    org_id = org.id
    auth.create_user("c@d.ch", "pw", role="org_admin", org_id=org_id,
                     can_read=True, can_write=True, can_delete=True)
    c = app.test_client()
    c.post("/login", data={"email": "c@d.ch", "password": "pw"})
    db = SessionLocal()
    p = Projekt(name="Leer", org_id=org_id)
    db.add(p)
    db.commit()
    pid = p.id

    assert c.get(f"/projekt/{pid}/rechtsgrundlagen/version").status_code == 200
