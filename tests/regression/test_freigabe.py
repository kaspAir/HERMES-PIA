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
    # Die Meldung nennt jetzt den nächsten Schritt: eine neue Version.
    with pytest.raises(FreigabeFehler, match="neue Version"):
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


# ---- Der Rückweg über die Route ------------------------------------------- #

def test_die_bearbeitete_checkliste_laesst_sich_hochladen(app):
    """«Ich hätte es lieber, wenn diese auch bereits im Entwurfsmodus
    heruntergeladen und bearbeitet wieder hochgeladen werden könnte.»"""
    import base64

    c, p = _angemeldet(app)
    c.post(f"/projekt/{p.id}/freigabe/erzeugen")
    svc = app.freigabe_service

    # Herunterladen im ENTWURF – das ist der Punkt.
    roh = c.get(f"/projekt/{p.id}/freigabe/checkliste/Entwurf.docx").get_data()
    assert svc.checkliste(p.id).status == "entwurf"

    # In Word bearbeiten – hier ersatzweise: alles auf «erfüllt» setzen und
    # erneut erzeugen, so als käme die Datei aus Word zurück.
    from app.domains.freigabe import dokumente
    zeilen = svc.zeilen(svc.checkliste(p.id))
    for z in svc.alle_zeilen(zeilen):
        z["bewertung"] = pp.ERFUELLT
        z["erlaeuterung"] = "in Word geprüft"
    bearbeitet = dokumente.checkliste_docx(zeilen).read()

    antwort = c.post(f"/projekt/{p.id}/freigabe/checkliste/upload",
                     json={"filename": "Checkliste.docx",
                           "data": base64.b64encode(bearbeitet).decode()})
    assert antwort.status_code == 200, antwort.get_data(as_text=True)
    assert antwort.get_json()["geaendert"] > 0

    danach = svc.alle_zeilen(svc.zeilen(svc.checkliste(p.id)))
    assert all(z["bewertung"] == pp.ERFUELLT for z in danach)
    assert all("in Word geprüft" in z["erlaeuterung"] for z in danach)
    assert roh                                    # der Download war ein Dokument


def test_ein_unlesbares_dokument_wird_ehrlich_gemeldet(app):
    """Zwei Stufen: der allgemeine Upload-Prüfer erkennt schon, dass es keine
    Office-Datei ist – erst danach greift die Frage, ob es eine Checkliste
    ist. Beide Meldungen nennen einen nächsten Schritt."""
    import base64

    c, p = _angemeldet(app)
    c.post(f"/projekt/{p.id}/freigabe/erzeugen")

    kaputt = c.post(f"/projekt/{p.id}/freigabe/checkliste/upload",
                    json={"filename": "kaputt.docx",
                          "data": base64.b64encode(b"kein Word").decode()})
    assert kaputt.status_code == 400
    assert "Office-Datei" in kaputt.get_json()["error"]

    # Ein GUELTIGES Word-Dokument, das keine Checkliste ist: hier meldet der
    # Rueckweg selbst, und er nennt die Herkunft als naechsten Schritt.
    from app.domains.freigabe import dokumente
    fremd = dokumente.entscheide_docx([]).read()
    antwort = c.post(f"/projekt/{p.id}/freigabe/checkliste/upload",
                     json={"filename": "fremd.docx",
                           "data": base64.b64encode(fremd).decode()})
    assert antwort.status_code == 200
    assert antwort.get_json()["geaendert"] == 0     # nichts gefunden, nichts geaendert


def test_nach_der_freigabe_nimmt_sie_nichts_mehr_an(app):
    import base64

    from app.domains.freigabe import dokumente

    c, p = _angemeldet(app)
    c.post(f"/projekt/{p.id}/freigabe/erzeugen")
    svc = app.freigabe_service
    zeilen = svc.zeilen(svc.checkliste(p.id))
    for z in svc.alle_zeilen(zeilen):
        z["bewertung"] = pp.ERFUELLT
    svc.speichere_zeilen(p.id, zeilen)
    svc.gib_frei(p.id, "Frau Muster")

    antwort = c.post(f"/projekt/{p.id}/freigabe/checkliste/upload",
                     json={"filename": "C.docx",
                           "data": base64.b64encode(
                               dokumente.checkliste_docx(zeilen).read()).decode()})
    assert antwort.status_code == 409
    assert "nicht mehr ändern" in antwort.get_json()["error"]


# ---- Änderungskontrolle --------------------------------------------------- #
#
# «Aus der Änderungskontrolle haben wir doch auch schon ein Modul gemacht,
# oder (für die RGA)? Die sollten wir schon reinbringen.» – Ja: der Baustein
# `app/shared/versionierung.py` wurde genau dafür herausgelöst. Die Checkliste
# erfüllt seinen Vertrag über eine Eigenschaft `answers_json`, ohne dass das
# Datenmodell seine eigene Sprache aufgibt.

def _bewertet(app, c, p):
    svc = app.freigabe_service
    zeilen = svc.zeilen(svc.checkliste(p.id))
    for z in svc.alle_zeilen(zeilen):
        z["bewertung"] = pp.ERFUELLT
    svc.speichere_zeilen(p.id, zeilen)
    return svc


def test_der_erste_entwurf_ist_version_0_1(app):
    c, p = _angemeldet(app)
    c.post(f"/projekt/{p.id}/freigabe/erzeugen")
    assert app.freigabe_service.checkliste(p.id).doc_version == "0.1"


def test_die_version_steht_auf_der_seite(app):
    c, p = _angemeldet(app)
    c.post(f"/projekt/{p.id}/freigabe/erzeugen")
    html = c.get(f"/projekt/{p.id}/freigabe").get_data(as_text=True)
    assert "Version 0.1" in html
    assert "Änderungskontrolle" in html


def test_eine_neue_version_macht_aus_dem_nachweis_wieder_einen_entwurf(app):
    """Der freigegebene Stand bleibt – die Arbeit läuft auf der nächsten Nummer."""
    c, p = _angemeldet(app)
    c.post(f"/projekt/{p.id}/freigabe/erzeugen")
    svc = _bewertet(app, c, p)
    svc.gib_frei(p.id, "Frau Muster")
    assert svc.checkliste(p.id).status == "freigegeben"

    neu, protokoll = svc.neue_version(p.id, name="Frau Muster",
                                      bemerkungen="Kapitel 1.3 ergänzt.")
    assert neu == "0.2"
    checkliste = svc.checkliste(p.id)
    assert checkliste.status == "entwurf"
    assert checkliste.freigegeben_am is None
    assert protokoll[-1]["bemerkungen"] == "Kapitel 1.3 ergänzt."


def test_nach_der_neuen_version_laesst_sich_wieder_erzeugen(app):
    """«Die Checkliste sollte mehrfach generiert werden können, wenn
    Änderungen durchgeführt worden sind.»"""
    c, p = _angemeldet(app)
    c.post(f"/projekt/{p.id}/freigabe/erzeugen")
    svc = _bewertet(app, c, p)
    svc.gib_frei(p.id, "Frau Muster")
    with pytest.raises(FreigabeFehler, match="neue Version"):
        svc.erzeuge(p)
    svc.neue_version(p.id, name="Frau Muster")
    svc.erzeuge(p)                       # jetzt geht es
    assert svc.checkliste(p.id).doc_version == "0.2"


def test_das_protokoll_wird_fortgeschrieben(app):
    c, p = _angemeldet(app)
    c.post(f"/projekt/{p.id}/freigabe/erzeugen")
    svc = app.freigabe_service
    svc.neue_version(p.id, name="A", bemerkungen="erste Änderung")
    svc.neue_version(p.id, name="B", bemerkungen="zweite Änderung")
    stand = svc.versionsstand(p.id)
    assert stand["current_version"] == "0.3"
    assert [e["version"] for e in stand["changelog"]] == ["0.2", "0.3"]


def test_geaenderte_kapitel_werden_benannt(app):
    """Der Baustein vergleicht den GANZEN Abschnitt, nicht nur einen Text."""
    c, p = _angemeldet(app)
    c.post(f"/projekt/{p.id}/freigabe/erzeugen")
    svc = app.freigabe_service
    svc.neue_version(p.id, name="A")            # Schnappschuss setzen
    assert svc.versionsstand(p.id)["changed_sections"] == []

    zeilen = svc.zeilen(svc.checkliste(p.id))
    zeilen["generell"][0]["bewertung"] = pp.ERFUELLT
    svc.speichere_zeilen(p.id, zeilen)
    geaendert = svc.versionsstand(p.id)["changed_sections"]
    assert [g["number"] for g in geaendert] == ["1.1"]


def test_die_neue_version_ueber_die_route(app):
    c, p = _angemeldet(app)
    c.post(f"/projekt/{p.id}/freigabe/erzeugen")
    html = c.post(f"/projekt/{p.id}/freigabe/version",
                  data={"bemerkungen": "Nach Rückmeldung angepasst."}).get_data(as_text=True)
    assert "Version 0.2 angelegt" in html
    assert "Nach Rückmeldung angepasst." in html


# ---- Fassungen ablegen ---------------------------------------------------- #

def test_die_freigabeversion_wird_abgelegt_und_nicht_zerlegt(app):
    """«Die Freigabeversion und die freigegebene Version sollten auch
    hochgeladen werden können.» – Sie sind Nachweise, keine Eingabe."""
    import base64

    from app.domains.freigabe import dokumente

    c, p = _angemeldet(app)
    c.post(f"/projekt/{p.id}/freigabe/erzeugen")
    svc = app.freigabe_service
    datei = dokumente.checkliste_docx(svc.zeilen(svc.checkliste(p.id))).read()

    antwort = c.post(f"/projekt/{p.id}/freigabe/checkliste/upload?art=freigabe",
                     json={"filename": "CL_v0.1.docx",
                           "data": base64.b64encode(datei).decode()})
    assert antwort.status_code == 200 and antwort.get_json()["abgelegt"] == "freigabe"
    fassungen = svc.fassungen(p.id)
    assert len(fassungen) == 1
    assert fassungen[0].art == "freigabe" and fassungen[0].doc_version == "0.1"
    assert svc.checkliste(p.id).status == "entwurf"     # noch nicht freigegeben


def test_die_freigegebene_fassung_schliesst_ab(app):
    import base64

    from app.domains.freigabe import dokumente

    c, p = _angemeldet(app)
    c.post(f"/projekt/{p.id}/freigabe/erzeugen")
    svc = app.freigabe_service
    datei = dokumente.checkliste_docx(svc.zeilen(svc.checkliste(p.id))).read()
    c.post(f"/projekt/{p.id}/freigabe/checkliste/upload?art=freigegeben",
           json={"filename": "CL_v1.0.docx",
                 "data": base64.b64encode(datei).decode()})
    assert svc.checkliste(p.id).status == "freigegeben"


def test_eine_abgelegte_fassung_laesst_sich_wieder_herunterladen(app):
    import base64

    from app.domains.freigabe import dokumente

    c, p = _angemeldet(app)
    c.post(f"/projekt/{p.id}/freigabe/erzeugen")
    svc = app.freigabe_service
    datei = dokumente.checkliste_docx(svc.zeilen(svc.checkliste(p.id))).read()
    c.post(f"/projekt/{p.id}/freigabe/checkliste/upload?art=freigabe",
           json={"filename": "CL.docx", "data": base64.b64encode(datei).decode()})
    fassung = svc.fassungen(p.id)[0]

    antwort = c.get(f"/projekt/{p.id}/freigabe/fassung/{fassung.id}/CL.docx")
    assert antwort.status_code == 200
    assert antwort.get_data() == datei          # unveraendert, Byte fuer Byte


def test_eine_unbekannte_art_wird_abgewiesen(app):
    import base64

    c, p = _angemeldet(app)
    c.post(f"/projekt/{p.id}/freigabe/erzeugen")
    antwort = c.post(f"/projekt/{p.id}/freigabe/checkliste/upload?art=irgendwas",
                     json={"filename": "X.docx",
                           "data": base64.b64encode(b"PK\x03\x04").decode()})
    assert antwort.status_code == 400


# ---- Lesbarkeit ----------------------------------------------------------- #
#
# Beim Erstellen des Benutzerhandbuchs an den Bildschirmfotos gemessen: die
# Erläuterung war nach zwei Zeilen abgeschnitten («Es wurde keine Fassung des
# Projektinitialisie…»), und der Inhalt nutzte bei den breiten Tabellen nur
# die halbe Fläche. Beides fällt im Bild stärker auf als im Betrieb – aber es
# ist derselbe Bildschirm.

def test_die_erlaeuterung_wird_nicht_abgeschnitten(app):
    """Die Begründung ist das Wertvollste an der Zeile."""
    c, p = _angemeldet(app)
    c.post(f"/projekt/{p.id}/freigabe/erzeugen")
    html = c.get(f"/projekt/{p.id}/freigabe").get_data(as_text=True)
    assert 'rows="2"' not in html.split("erlaeuterung-")[1][:200]
    assert "mitwachsend" in html
    assert "scrollHeight" in html          # das Feld wächst wirklich mit


def test_tabellenseiten_bekommen_mehr_breite(app):
    c, p = _angemeldet(app)
    c.post(f"/projekt/{p.id}/freigabe/erzeugen")
    for pfad in (f"/projekt/{p.id}/freigabe", f"/projekt/{p.id}",
                 f"/projekt/{p.id}/kopfdaten"):
        html = c.get(pfad).get_data(as_text=True)
        assert '<main class="breit">' in html, pfad


def test_der_fliesstext_bleibt_schmal(app):
    """«Breit» heisst nicht randlos – Fliesstext bleibt lesbar."""
    from pathlib import Path

    from app.config import BASE_DIR

    css = Path(BASE_DIR, "app", "static", "css", "app.css").read_text(encoding="utf-8")
    assert "main.breit { max-width: 1240px; }" in css
    assert "main { padding: 32px 28px; max-width: 900px; }" in css
