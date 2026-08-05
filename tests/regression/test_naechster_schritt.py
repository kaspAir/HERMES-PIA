"""Beweist: die Startseite schlägt GENAU EINEN nächsten Schritt vor.

Aus der Benutzerführungs-Richtlinie, Abschnitt 03:

  *«Genau eine Aufgabe wird hervorgehoben. Mehrere gleichrangige Aktionen
  erzeugen dieselbe Lähmung wie keine.»*

  *«Stille als Information.»* – Kein Vorschlag ist eine Aussage, kein Loch.
"""
import pytest

from app.config import Config
from app.domains.projekt.naechster_schritt import (
    begruessung, naechster_schritt, schritte_fuer,
)
from app.factory import create_app


@pytest.fixture
def app(tmp_path):
    from app.shared.database import SessionLocal

    class _Cfg(Config):
        DATABASE_URL = "sqlite:///" + str(tmp_path / "ns.db").replace("\\", "/")
        SUPERADMIN_EMAIL = "betreiber@test.ch"
        SUPERADMIN_PASSWORD = "pw-super"
        SECRET_KEY = "test-secret"

    SessionLocal.remove()
    application = create_app(_Cfg)
    SessionLocal.remove()
    yield application
    SessionLocal.remove()


def _projekt(**kwargs):
    grund = {"projekt_id": 1, "name": "Ablösung Fachanwendung",
             "abschnitte_total": 8, "offene_abschnitte": 0,
             "pruefung_vorhanden": True, "muss_befunde": 0,
             "rga_vorhanden": True}
    grund.update(kwargs)
    return grund


# ---- Genau einer ---------------------------------------------------------- #

def test_ein_fertiges_projekt_erzeugt_keinen_vorschlag():
    vorschlag, weitere, ruhige = naechster_schritt([_projekt()])
    assert vorschlag is None and weitere == [] and ruhige == 1


def test_aus_vielen_offenen_wird_genau_einer_hervorgehoben():
    vorschlag, weitere, _ = naechster_schritt([
        _projekt(projekt_id=1, offene_abschnitte=3, pruefung_vorhanden=False,
                 rga_vorhanden=False),
        _projekt(projekt_id=2, muss_befunde=2),
    ])
    assert vorschlag is not None
    assert len(weitere) >= 1          # der Rest tritt zurück, verschwindet aber nicht


def test_was_die_freigabe_blockiert_kommt_zuerst():
    """Ein Muss-Befund schlägt eine offene Erfassung – er hält die Freigabe auf."""
    vorschlag, _, _ = naechster_schritt([
        _projekt(projekt_id=1, offene_abschnitte=5, pruefung_vorhanden=False,
                 rga_vorhanden=False),
        _projekt(projekt_id=2, muss_befunde=1),
    ])
    assert vorschlag["art"] == "befunde" and vorschlag["projekt_id"] == 2


# ---- Der Aufwand steht VORHER da ------------------------------------------ #

def test_jeder_vorschlag_nennt_ort_und_dauer():
    """«Etappe 4 von 6 · ca. 15 Minuten» entscheidet über anfangen oder zumachen."""
    for zustand in (_projekt(offene_abschnitte=2, pruefung_vorhanden=False),
                    _projekt(muss_befunde=3),
                    _projekt(pruefung_vorhanden=False),
                    _projekt(rga_vorhanden=False)):
        for schritt in schritte_fuer(zustand):
            assert schritt["wo"] and schritt["minuten"] >= 5
            assert schritt["warum"].endswith(".")


def test_die_etappe_wird_aus_dem_stand_gerechnet():
    s = schritte_fuer(_projekt(abschnitte_total=8, offene_abschnitte=3))[0]
    assert s["wo"] == "Etappe 6 von 8"      # fünf erledigt, die sechste ist dran


def test_mehr_offenes_heisst_mehr_zeit():
    wenig = schritte_fuer(_projekt(offene_abschnitte=1))[0]["minuten"]
    viel = schritte_fuer(_projekt(offene_abschnitte=6))[0]["minuten"]
    assert viel > wenig


# ---- Die Reihenfolge der Methode ------------------------------------------ #

def test_geprueft_wird_erst_wenn_die_angaben_stehen():
    """Eine Prüfung halbfertiger Angaben erzeugt Befunde, die sich selbst erledigen."""
    arten = [s["art"] for s in schritte_fuer(
        _projekt(offene_abschnitte=4, pruefung_vorhanden=False, rga_vorhanden=False))]
    assert "pruefung" not in arten and "rechtsgrundlagen" not in arten
    assert arten == ["interview"]


def test_offene_befunde_erscheinen_auch_neben_offenen_angaben():
    """Sie hängen nicht an der Vollständigkeit – sie stehen bereits fest."""
    arten = [s["art"] for s in schritte_fuer(
        _projekt(offene_abschnitte=2, muss_befunde=1))]
    assert "befunde" in arten


def test_eine_laufende_analyse_wird_nicht_nochmals_vorgeschlagen():
    assert not schritte_fuer(_projekt(rga_vorhanden=False, rga_laeuft=True))


# ---- Sprache -------------------------------------------------------------- #

def test_die_texte_nennen_das_projekt_beim_namen():
    s = schritte_fuer(_projekt(offene_abschnitte=1))[0]
    assert "Ablösung Fachanwendung" in s["titel"]


def test_einzahl_und_mehrzahl_stimmen():
    einer = schritte_fuer(_projekt(muss_befunde=1))[0]["warum"]
    mehrere = schritte_fuer(_projekt(muss_befunde=4))[0]["warum"]
    assert "1 Punkt müssen" not in einer and einer.startswith("1 Punkt ")
    assert mehrere.startswith("4 Punkte ")


def test_kein_implementierungsbegriff_im_nutzertext():
    """Aus der Richtlinie, Abschnitt 07: keine Systemsprache in der Oberfläche."""
    verboten = ("JSON", "Session", "Entwurf-ID", "null", "Objekt", "Validierung")
    for zustand in (_projekt(offene_abschnitte=2, pruefung_vorhanden=False,
                             rga_vorhanden=False),
                    _projekt(muss_befunde=2)):
        for s in schritte_fuer(zustand):
            text = " ".join([s["titel"], s["wo"], s["warum"]])
            assert not any(w in text for w in verboten), text


def test_die_begruessung_verortet_in_der_zeit():
    assert begruessung(8) == "Guten Morgen"
    assert begruessung(14) == "Guten Tag"
    assert begruessung(21) == "Guten Abend"


# ---- Robustheit ----------------------------------------------------------- #

def test_ohne_projekte_bleibt_alles_leer_ohne_absturz():
    assert naechster_schritt([]) == (None, [], 0)
    assert naechster_schritt(None) == (None, [], 0)
    assert schritte_fuer(None) == []


def test_ohne_bekannte_abschnitte_wird_nichts_behauptet():
    """Ein Vorschlag aus Unkenntnis behauptet, die Erfassung sei fertig.

    Gemessen: ohne jede Angabe schlug das Modul «fachlich prüfen lassen» und
    «Rechtsgrundlagen klären» vor – für ein Projekt, von dem es nichts wusste.
    """
    assert schritte_fuer({"projekt_id": 7, "name": "Neu"}) == []
    assert schritte_fuer(None) == []


# ---- Die Startseite zeigt ihn wirklich ------------------------------------ #
#
# Ein Rechenmodul, das niemand aufruft, hilft nicht. Diese Tests RENDERN die
# Seite – Modulfehler und Vorlagefehler fallen hier auf, nicht erst im Betrieb.

def _client_mit_projekt(app):
    auth = app.auth_service
    org = auth.create_org("Org")
    auth.create_user("pl@org.ch", "pw", org_id=org.id,
                     can_read=True, can_write=True)
    org_id = org.id
    c = app.test_client()
    c.post("/login", data={"email": "pl@org.ch", "password": "pw"})
    c.post("/interview/start", data={"project_name": "Baubewilligungen",
                                     "projektleiter": "Frau Muster"})
    return c, app.projekt_service.projekte_for_org(org_id)[0]


def test_die_startseite_hebt_genau_einen_schritt_hervor(app):
    c, projekt = _client_mit_projekt(app)
    html = c.get("/").get_data(as_text=True)
    assert "Angaben zu «Baubewilligungen» vervollständigen" in html
    assert "Etappe 1 von" in html and "Minuten" in html
    assert html.count('class="btn-primary ns-los"') == 1     # genau EIN Aufruf


def test_die_leere_startseite_nennt_zweck_umfang_und_dauer(app):
    """Aus der Richtlinie: «Jeder leere Zustand nennt Zweck, Umfang, Dauer und
    Einstieg» – statt einer Fläche, die nur mitteilt, dass nichts da ist."""
    auth = app.auth_service
    org = auth.create_org("Leer")
    auth.create_user("neu@org.ch", "pw", org_id=org.id,
                     can_read=True, can_write=True)
    c = app.test_client()
    c.post("/login", data={"email": "neu@org.ch", "password": "pw"})
    html = c.get("/").get_data(as_text=True)
    assert "Noch kein Projekt begonnen." in html
    assert "acht Abschnitten" in html          # Umfang
    assert "einer Stunde" in html              # Dauer
    assert "Projektname" in html               # Einstieg


# ---- Leere Zustände und Meldungen ----------------------------------------- #
#
# Aus der Richtlinie, Abschnitt 08: «Jede Meldung nennt einen nächsten Schritt.
# Jeder leere Zustand nennt Zweck, Umfang, Dauer und Einstieg.» Mechanisch
# prüfbar ist davon nur die Rückfallrichtung: die Sackgassen-Sätze, die wir
# ersetzt haben, dürfen nicht zurückkommen.

_SACKGASSEN = (
    "Noch keine Abschnitte erfasst.",
    "Noch keine Ergebnisse erfasst.",
    "Keine Änderungen seit dem letzten Download erkannt.",
    "Netzwerkfehler beim Upload.",
    "Datei konnte nicht gelesen werden.",
    "Upload fehlgeschlagen.",
)


def test_keine_meldung_endet_in_der_sackgasse():
    from pathlib import Path

    from app.config import BASE_DIR

    gefunden = []
    for vorlage in Path(BASE_DIR, "app", "templates").glob("*.html"):
        text = vorlage.read_text(encoding="utf-8")
        gefunden += [f"{vorlage.name}: {satz}" for satz in _SACKGASSEN if satz in text]
    assert not gefunden, gefunden


# ---- Gefragt wird in Alltagssprache --------------------------------------- #
#
# Aus der Richtlinie, Abschnitt 07: «Fragen als Frage, Aktionen als Verb,
# Zustände als vollständiger Satz.» Der HERMES-Begriff verschwindet dabei
# nicht – er wird zum Herkunftsvermerk unter der Frage.

def _sections(app):
    return app.method_service.get("hermes_pia")["sections"]


def test_jeder_abschnitt_hat_eine_leitfrage(app):
    ohne = [s["id"] for s in _sections(app) if not s.get("leitfrage")]
    assert not ohne, ohne


def test_die_leitfragen_sind_fragen(app):
    for s in _sections(app):
        assert s["leitfrage"].endswith("?"), s["id"]


def test_das_interview_zeigt_die_frage_und_nennt_die_herkunft(app):
    c, projekt = _client_mit_projekt(app)
    erg = app.projekt_service.ergebnisse(projekt.id)[0]
    sid = app.interview_service.session_for_ergebnis(erg.id).id
    html = c.get(f"/interview/{sid}").get_data(as_text=True)
    assert "Warum machen wir das überhaupt?" in html      # die Frage führt
    assert "Ausgangslage" in html                          # der Begriff bleibt
    assert "Im Dokument: Kapitel" in html
