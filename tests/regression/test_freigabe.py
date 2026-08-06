"""Beweist: die Projektinitialisierungsfreigabe hält ihre Reihenfolge ein.

    Checkliste erzeugen → bewerten → freigeben → Meilenstein → Entscheid

Die Bedingungen stehen im Dienst und nicht in der Oberfläche. Diese Tests
gehen deshalb am Bildschirm vorbei: sie rufen den Dienst direkt auf und
versuchen, die Reihenfolge zu umgehen.
"""
import json

import pytest

from app.config import Config
from app.domains.freigabe import pruefpunkte as pp
from app.domains.freigabe.service import ART, FreigabeFehler
from app.factory import create_app


@pytest.fixture
def app(tmp_path):
    from app.shared.database import SessionLocal

    class _Cfg(Config):
        DATABASE_URL = "sqlite:///" + str(tmp_path / "fg.db").replace("\\", "/")
        SUPERADMIN_EMAIL = "betreiber@test.ch"
        SUPERADMIN_PASSWORD = "pw-super"
        SECRET_KEY = "test-secret"

    SessionLocal.remove()
    application = create_app(_Cfg)
    SessionLocal.remove()
    yield application
    SessionLocal.remove()


@pytest.fixture
def projekt(app):
    auth = app.auth_service
    org = auth.create_org("Org")
    auth.create_user("pl@org.ch", "pw", org_id=org.id, can_read=True, can_write=True)
    org_id = org.id
    c = app.test_client()
    c.post("/login", data={"email": "pl@org.ch", "password": "pw"})
    c.post("/interview/start", data={"project_name": "Ablösung Fachanwendung",
                                     "projektleiter": "Frau Muster"})
    return app.projekt_service.projekte_for_org(org_id)[0]


# ---- Die Bewertung liest Struktur, nicht Bedeutung ------------------------ #

_VOLLSTAENDIG = {
    "ziele": {"extracted": [{"nr": "01", "beschreibung": "Ein Ziel"}]},
    "rahmenbedingungen": {"extracted": [{"nr": "01", "vorgabe": "Eine Vorgabe"}]},
    "vorgaben_methoden": {"extracted": [
        {"titel": "Projektmanagementmethode", "vorgabe": "HERMES"},
        {"titel": "Dokumentenablage", "vorgabe": "Gemäss Vorgabe Stammorganisation"}]},
    "personalaufwand": {"extracted": [
        {"rolle": "Projektleiter", "name": "Frau Muster", "aufwand": "20"},
        {"rolle": "Auftraggeber", "name": "Herr Beispiel", "aufwand": "5"}]},
    "kosten": {"extracted": [{"phase": "Total Initialisierung", "betrag": "25000"}]},
    "projektorganisation": {"extracted": [
        {"rolle_person": "Projektleiter", "bestaetigung": "bestätigt"}]},
    "kommunikation": {"extracted": [{"empfaenger": "Projektausschuss"}]},
    "risiken": {"extracted": [
        {"nr": "01", "beschreibung": "Ein Risiko", "risikozahl": "9",
         "massnahmen": "Frühzeitige Abklärung einleiten. Danach berichten."}]},
}


def test_ein_vollstaendiger_auftrag_erfuellt_was_pruefbar_ist():
    zeilen = pp.generelle_pruefpunkte(_VOLLSTAENDIG, {"freigegeben": True})
    nach_nr = {z["nr"]: z for z in zeilen}
    assert nach_nr["G-02"]["bewertung"] == pp.ERFUELLT
    assert nach_nr["G-03"]["bewertung"] == pp.ERFUELLT
    assert nach_nr["G-06"]["bewertung"] == pp.ERFUELLT


def test_ein_leerer_auftrag_erfuellt_nichts():
    zeilen = pp.generelle_pruefpunkte({}, {})
    verneint = [z["nr"] for z in zeilen if z["bewertung"] == pp.NICHT_ERFUELLT]
    assert set(verneint) == {"G-02", "G-03", "G-04", "G-05", "G-06"}


def test_die_unterschrift_wird_nie_behauptet():
    """G-01 fragt nach einem Vorgang ausserhalb des Systems."""
    for dok in ({}, {"freigabe": True}, {"freigegeben": True}):
        zeile = pp.generelle_pruefpunkte(_VOLLSTAENDIG, dok)[0]
        assert zeile["nr"] == "G-01"
        assert zeile["bewertung"] == pp.ZU_BESTAETIGEN
        assert "nicht feststellen" in zeile["erlaeuterung"]


def test_geplante_information_ist_keine_erfolgte():
    """G-05: der Auftrag plant die Kommunikation, er belegt sie nicht."""
    zeile = [z for z in pp.generelle_pruefpunkte(_VOLLSTAENDIG, {})
             if z["nr"] == "G-05"][0]
    assert zeile["bewertung"] == pp.ZU_BESTAETIGEN
    assert "plant sie" in zeile["erlaeuterung"]


def test_jede_bewertung_sagt_worauf_sie_beruht():
    for z in pp.generelle_pruefpunkte(_VOLLSTAENDIG, {"freigegeben": True}):
        assert z["erlaeuterung"].strip(), z["nr"]
        assert z["bewertung"] in (pp.ERFUELLT, pp.TEILWEISE,
                                  pp.NICHT_ERFUELLT, pp.ZU_BESTAETIGEN)


def test_ohne_bestaetigung_der_vorgesetzten_stelle_nur_teilweise():
    ohne = dict(_VOLLSTAENDIG, projektorganisation={"extracted": [
        {"rolle_person": "Projektleiter", "bestaetigung": "ausstehend"}]})
    zeile = [z for z in pp.generelle_pruefpunkte(ohne, {}) if z["nr"] == "G-02"][0]
    assert zeile["bewertung"] == pp.TEILWEISE
    assert "nicht belegt" in zeile["erlaeuterung"]


# ---- Vorschläge sind Vorschläge ------------------------------------------- #

def test_vorschlaege_bleiben_unbewertet():
    for zeile in (pp.organisationsspezifische_vorschlaege(_VOLLSTAENDIG)
                  + pp.projektspezifische_vorschlaege(_VOLLSTAENDIG)):
        assert zeile["bewertung"] == ""
        assert zeile["herkunft"].startswith("Vorschlag")


def test_die_vorschlaege_stammen_aus_dem_auftrag():
    org = pp.organisationsspezifische_vorschlaege(_VOLLSTAENDIG)
    assert any("Dokumentenablage" in z["kriterium"] for z in org)
    prj = pp.projektspezifische_vorschlaege(_VOLLSTAENDIG)
    assert any("Frühzeitige Abklärung einleiten" in z["kriterium"] for z in prj)


def test_ohne_grundlage_gibt_es_keine_vorschlaege():
    assert pp.organisationsspezifische_vorschlaege({}) == []
    assert pp.projektspezifische_vorschlaege({}) == []


# ---- Das Tor -------------------------------------------------------------- #

def test_eine_unbewertete_zeile_ist_kein_stilles_ja():
    zeilen = [{"nr": "P-01", "bewertung": ""}]
    assert not pp.freigabe_moeglich(zeilen)
    assert pp.offene_punkte(zeilen)[0]["nr"] == "P-01"


def test_teilweise_und_zu_bestaetigen_halten_nicht_auf():
    """Sie verlangen eine Entscheidung des Auftraggebers – sie sind kein Nein."""
    assert pp.freigabe_moeglich([{"nr": "G-01", "bewertung": pp.ZU_BESTAETIGEN},
                                 {"nr": "G-04", "bewertung": pp.TEILWEISE}])


def test_nicht_erfuellt_haelt_auf():
    assert not pp.freigabe_moeglich([{"nr": "G-03", "bewertung": pp.NICHT_ERFUELLT}])


# ---- Die Reihenfolge lässt sich nicht umgehen ----------------------------- #

def test_ohne_checkliste_kein_meilenstein(app, projekt):
    with pytest.raises(FreigabeFehler, match="Checkliste freigegeben"):
        app.freigabe_service.erreiche_meilenstein(projekt.id, "pl@org.ch")


def test_ohne_bewertung_keine_freigabe(app, projekt):
    svc = app.freigabe_service
    svc.erzeuge(projekt)
    with pytest.raises(FreigabeFehler, match="offen oder nicht erfüllt"):
        svc.gib_frei(projekt.id, "pl@org.ch")


def test_der_ganze_weg(app, projekt):
    svc = app.freigabe_service
    checkliste = svc.erzeuge(projekt)
    assert checkliste.status == "entwurf"
    assert checkliste.quelle                      # die Herkunft ist vermerkt

    # Alles bewerten – so, wie es die Oberfläche täte.
    zeilen = svc.zeilen(checkliste)
    for z in svc.alle_zeilen(zeilen):
        z["bewertung"] = pp.ERFUELLT
    svc.speichere_zeilen(projekt.id, zeilen)

    svc.gib_frei(projekt.id, "Frau Muster")
    assert svc.checkliste(projekt.id).status == "freigegeben"

    stein = svc.erreiche_meilenstein(projekt.id, "Frau Muster",
                                     entscheidungsdatum="2026-09-01")
    assert stein.status == "erreicht"

    # Der Entscheid steht in der Liste – Zeile 01, wie in der Vorlage.
    entscheide = svc.entscheide(projekt.id)
    assert len(entscheide) == 1
    e = entscheide[0]
    assert e.nr == "01"
    assert e.entscheidungstraeger == "Auftraggeber"
    assert e.entscheidungsdatum == "2026-09-01"
    assert "Checkliste Projektinitialisierungsfreigabe" in e.grundlagen

    # Und die Phase läuft.
    from app.shared.database import SessionLocal
    from app.domains.projekt.models import Phase
    phase = SessionLocal().query(Phase).filter(Phase.projekt_id == projekt.id).first()
    assert phase.status == "laufend"


def test_eine_freigegebene_checkliste_wird_nicht_mehr_veraendert(app, projekt):
    svc = app.freigabe_service
    checkliste = svc.erzeuge(projekt)
    zeilen = svc.zeilen(checkliste)
    for z in svc.alle_zeilen(zeilen):
        z["bewertung"] = pp.ERFUELLT
    svc.speichere_zeilen(projekt.id, zeilen)
    svc.gib_frei(projekt.id, "Frau Muster")

    with pytest.raises(FreigabeFehler, match="nicht mehr ändern"):
        svc.speichere_zeilen(projekt.id, zeilen)
    with pytest.raises(FreigabeFehler, match="bereits freigegeben"):
        svc.erzeuge(projekt)


def test_der_meilenstein_wird_nicht_zweimal_erreicht(app, projekt):
    svc = app.freigabe_service
    checkliste = svc.erzeuge(projekt)
    zeilen = svc.zeilen(checkliste)
    for z in svc.alle_zeilen(zeilen):
        z["bewertung"] = pp.ERFUELLT
    svc.speichere_zeilen(projekt.id, zeilen)
    svc.gib_frei(projekt.id, "Frau Muster")
    svc.erreiche_meilenstein(projekt.id, "Frau Muster")
    with pytest.raises(FreigabeFehler, match="bereits als erreicht"):
        svc.erreiche_meilenstein(projekt.id, "Frau Muster")
    assert len(svc.entscheide(projekt.id)) == 1     # kein zweiter Eintrag


def test_menschliche_bewertungen_ueberleben_ein_neues_erzeugen(app, projekt):
    """Kapitel 1.1 wird neu gerechnet, 1.2 und 1.3 gehören den Menschen."""
    svc = app.freigabe_service
    checkliste = svc.erzeuge(projekt)
    zeilen = svc.zeilen(checkliste)
    zeilen["projekt"] = [{"nr": "P-01", "pruefpunkt": "Eigener Punkt",
                          "kriterium": "Selbst formuliert?", "bewertung": pp.ERFUELLT,
                          "erlaeuterung": "", "verantwortlich": "", "datum": ""}]
    svc.speichere_zeilen(projekt.id, zeilen)

    danach = svc.zeilen(svc.erzeuge(projekt))
    assert danach["projekt"][0]["pruefpunkt"] == "Eigener Punkt"
    assert danach["projekt"][0]["bewertung"] == pp.ERFUELLT


def test_die_checkliste_ist_projektbezogen(app, projekt):
    """Kein Nachweis darf zu einem anderen Projekt gehören."""
    svc = app.freigabe_service
    svc.erzeuge(projekt)
    eintrag = svc.checkliste(projekt.id)
    assert eintrag.projekt_id == projekt.id
    assert eintrag.art == ART
    assert json.loads(eintrag.zeilen_json).keys() >= {"generell", "organisation", "projekt"}


# ---- Über die Oberfläche -------------------------------------------------- #
#
# Frühere Tests dieses Projekts lasen Quelltext statt ihn auszuführen und
# liessen drei Laufzeitfehler durch. Diese hier rufen die Seiten wirklich auf.

def _angemeldet(app):
    auth = app.auth_service
    org = auth.create_org("Org2")
    auth.create_user("chef@org.ch", "pw", org_id=org.id, can_read=True, can_write=True)
    org_id = org.id
    c = app.test_client()
    c.post("/login", data={"email": "chef@org.ch", "password": "pw"})
    c.post("/interview/start", data={"project_name": "Zweites Projekt",
                                     "projektleiter": "Herr Beispiel"})
    return c, app.projekt_service.projekte_for_org(org_id)[0]


def test_die_seite_laesst_sich_oeffnen(app):
    c, p = _angemeldet(app)
    html = c.get(f"/projekt/{p.id}/freigabe").get_data(as_text=True)
    assert "Darf die Phase Initialisierung beginnen?" in html
    assert "Checkliste ist noch nicht erstellt" in html
    assert "10 Minuten" in html            # Aufwand steht vorher da


def test_erzeugen_und_anzeigen_ueber_die_route(app):
    c, p = _angemeldet(app)
    c.post(f"/projekt/{p.id}/freigabe/erzeugen")
    html = c.get(f"/projekt/{p.id}/freigabe").get_data(as_text=True)
    assert "1.1 Generelle Prüfpunkte" in html
    assert "G-01" in html and "G-06" in html
    assert "unterschrieben vor?" in html


def test_die_route_gibt_ohne_bewertung_nicht_frei(app):
    c, p = _angemeldet(app)
    c.post(f"/projekt/{p.id}/freigabe/erzeugen")
    html = c.post(f"/projekt/{p.id}/freigabe/geben").get_data(as_text=True)
    assert "offen oder nicht erfüllt" in html
    assert app.freigabe_service.checkliste(p.id).status == "entwurf"


def test_die_route_setzt_den_meilenstein_nicht_vorbei_an_der_checkliste(app):
    c, p = _angemeldet(app)
    c.post(f"/projekt/{p.id}/freigabe/erzeugen")
    html = c.post(f"/projekt/{p.id}/freigabe/meilenstein",
                  data={"datum": "2026-09-01"}).get_data(as_text=True)
    assert "erst als erreicht gelten" in html
    assert app.freigabe_service.meilenstein(p.id).status != "erreicht"
    assert app.freigabe_service.entscheide(p.id) == []


def test_bewerten_und_freigeben_ueber_das_formular(app):
    c, p = _angemeldet(app)
    c.post(f"/projekt/{p.id}/freigabe/erzeugen")
    svc = app.freigabe_service
    zeilen = svc.zeilen(svc.checkliste(p.id))
    daten = {}
    for kapitel, liste in zeilen.items():
        for i, _ in enumerate(liste):
            daten[f"bewertung-{kapitel}-{i}"] = pp.ERFUELLT
            daten[f"erlaeuterung-{kapitel}-{i}"] = "geprüft"
    c.post(f"/projekt/{p.id}/freigabe/speichern", data=daten)
    html = c.post(f"/projekt/{p.id}/freigabe/geben").get_data(as_text=True)
    assert "freigegeben" in html.lower()
    assert svc.checkliste(p.id).status == "freigegeben"

    html = c.post(f"/projekt/{p.id}/freigabe/meilenstein",
                  data={"datum": "2026-09-01"}).get_data(as_text=True)
    assert "Liste Projektentscheide Steuerung" in html
    assert "Entscheid Projektinitialisierungsfreigabe" in html
    assert svc.meilenstein(p.id).status == "erreicht"


def test_der_einstieg_steht_auf_der_projektseite(app):
    c, p = _angemeldet(app)
    html = c.get(f"/projekt/{p.id}").get_data(as_text=True)
    assert f"/projekt/{p.id}/freigabe" in html
    assert "Freigabe der Phase" in html


# ---- Die Word-Ausgabe über die Route -------------------------------------- #

_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def test_die_checkliste_laesst_sich_herunterladen(app):
    c, p = _angemeldet(app)
    c.post(f"/projekt/{p.id}/freigabe/erzeugen")
    html = c.get(f"/projekt/{p.id}/freigabe").get_data(as_text=True)
    assert "Checkliste Projektinitialisierungsfreigabe (.docx)" in html

    antwort = c.get(f"/projekt/{p.id}/freigabe/checkliste/Test.docx")
    assert antwort.status_code == 200
    assert antwort.mimetype == _DOCX
    assert len(antwort.get_data()) > 10_000        # ein echtes Dokument


def test_ohne_checkliste_gibt_es_nichts_herunterzuladen(app):
    c, p = _angemeldet(app)
    assert c.get(f"/projekt/{p.id}/freigabe/checkliste/Test.docx").status_code == 404


def test_der_dateiname_traegt_datum_und_projektname(app):
    c, p = _angemeldet(app)
    c.post(f"/projekt/{p.id}/freigabe/erzeugen")
    html = c.get(f"/projekt/{p.id}/freigabe").get_data(as_text=True)
    assert "_Checkliste_Projektinitialisierungsfreigabe.docx" in html


def test_nach_dem_meilenstein_wird_die_liste_sofort_bezogen(app):
    """«Sobald der Meilenstein erreicht ist, soll die Liste automatisch
    befüllt und heruntergeladen werden» – mit dem Datum des Entscheids."""
    c, p = _angemeldet(app)
    c.post(f"/projekt/{p.id}/freigabe/erzeugen")
    svc = app.freigabe_service
    zeilen = svc.zeilen(svc.checkliste(p.id))
    daten = {f"bewertung-{k}-{i}": pp.ERFUELLT
             for k, liste in zeilen.items() for i, _ in enumerate(liste)}
    c.post(f"/projekt/{p.id}/freigabe/speichern", data=daten)
    c.post(f"/projekt/{p.id}/freigabe/geben")

    html = c.post(f"/projekt/{p.id}/freigabe/meilenstein",
                  data={"datum": "2026-09-01"}).get_data(as_text=True)
    assert "wird jetzt heruntergeladen" in html
    assert "/freigabe/entscheide/" in html
    assert "window.location.href" in html          # der Bezug startet von selbst

    antwort = c.get(f"/projekt/{p.id}/freigabe/entscheide/Liste.docx")
    assert antwort.status_code == 200 and antwort.mimetype == _DOCX


def test_das_bezogene_register_traegt_das_entscheidungsdatum(app):
    import io as _io

    from docx import Document

    from app.domains.freigabe import dokumente as dk
    from app.domains.generation.service import _row_cells, _tc_text

    c, p = _angemeldet(app)
    c.post(f"/projekt/{p.id}/freigabe/erzeugen")
    svc = app.freigabe_service
    zeilen = svc.zeilen(svc.checkliste(p.id))
    daten = {f"bewertung-{k}-{i}": pp.ERFUELLT
             for k, liste in zeilen.items() for i, _ in enumerate(liste)}
    c.post(f"/projekt/{p.id}/freigabe/speichern", data=daten)
    c.post(f"/projekt/{p.id}/freigabe/geben")
    c.post(f"/projekt/{p.id}/freigabe/meilenstein", data={"datum": "2026-09-01"})

    roh = c.get(f"/projekt/{p.id}/freigabe/entscheide/L.docx").get_data()
    tbl = dk._tabelle_nach(Document(_io.BytesIO(roh)), "Projektentscheide Steuerung")
    zeilen_txt = [[_tc_text(z) for z in _row_cells(r)]
                  for r in tbl if r.tag == dk.W_TR]
    eins = [z for z in zeilen_txt if z and z[0] == "01"][0]
    assert eins[4] == "01.09.2026"
    assert eins[3] == "Auftraggeber"


# ---- Ein Zustand gehört als Satz dagesagt --------------------------------- #

def test_der_erreichte_meilenstein_steht_als_text_da(app):
    """Rückmeldung: «Den grünen Rand sieht man kaum.» Farbe allein trägt
    keine Aussage – und wer sie nicht sieht, sieht nichts."""
    c, p = _angemeldet(app)
    c.post(f"/projekt/{p.id}/freigabe/erzeugen")
    svc = app.freigabe_service
    zeilen = svc.zeilen(svc.checkliste(p.id))
    daten = {f"bewertung-{k}-{i}": pp.ERFUELLT
             for k, liste in zeilen.items() for i, _ in enumerate(liste)}
    c.post(f"/projekt/{p.id}/freigabe/speichern", data=daten)
    c.post(f"/projekt/{p.id}/freigabe/geben")

    vorher = c.get(f"/projekt/{p.id}").get_data(as_text=True)
    assert "Noch nicht freigegeben" in vorher

    c.post(f"/projekt/{p.id}/freigabe/meilenstein", data={"datum": "2026-09-01"})
    nachher = c.get(f"/projekt/{p.id}").get_data(as_text=True)
    assert "Freigegeben am" in nachher
    assert "2026-09-01" in nachher
    assert "meilenstein-erreicht" in nachher       # der Rand bleibt als zweites Signal


def test_der_geplante_start_wird_nicht_mit_der_freigabe_verwechselt(app):
    """Zwei verschiedene Daten – sie müssen sich unterscheiden lassen.

    Gemessen im Bildschirmfoto: der Meilenstein zeigte «2026-09-01 · Start»,
    freigegeben wurde aber am 06.08.2026. Ohne Beschriftung liest man das eine
    als das andere.
    """
    from app.domains.projekt.models import Meilenstein
    from app.shared.database import SessionLocal

    c, p = _angemeldet(app)
    db = SessionLocal()
    stein = app.freigabe_service.meilenstein(p.id)
    db.get(Meilenstein, stein.id).datum = "2026-09-01"
    db.commit()

    html = c.get(f"/projekt/{p.id}").get_data(as_text=True)
    assert "geplanter Start" in html


def test_ohne_datum_steht_das_auch_da(app):
    c, p = _angemeldet(app)
    assert "Datum offen" in c.get(f"/projekt/{p.id}").get_data(as_text=True)
