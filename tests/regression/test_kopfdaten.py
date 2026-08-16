"""Beweist: die Kopfdaten liegen einmal, bestätigt und änderbar.

Die zwölf Angaben, die jedes HERMES-Dokument im Kopf trägt, wurden bei jedem
Dokument neu aus drei Stellen zusammengerechnet. Zwei Folgen sprachen dagegen:

* Die **Anrede** wurde bei jedem Herunterladen neu vom Sprachmodell geschätzt –
  ein Modellaufruf für eine Antwort, die sich nie ändert, und der Name verliess
  das System jedes Mal aufs Neue.
* Eine **falsche Schätzung liess sich nicht richtigstellen.** Bei «Andrea»,
  «Kim» oder «Dominique» rät jedes Modell.

Der Vorrang ist hier bewusst ein anderer als beim Inhalt: dort gewinnt die
verbindlichste Fassung des Auftrags, hier der hinterlegte Datensatz – er ist
der einzige, den ein Mensch bestätigt hat. Damit daraus keine zweite Wahrheit
wird, gibt es den Abgleich.
"""
import pytest

from app.config import Config
from app.domains.dokumentenkopf import kopf as kopfmodul
from app.domains.dokumentenkopf.models import FELDER
from app.domains.dokumentenkopf.service import KopfdatenService
from app.factory import create_app


@pytest.fixture
def app(tmp_path):
    from app.shared.database import SessionLocal

    class _Cfg(Config):
        DATABASE_URL = "sqlite:///" + str(tmp_path / "kd.db").replace("\\", "/")
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
                                     "projektleiter": "Amélie Brèche"})
    return c, app.projekt_service.projekte_for_org(org_id)[0]


def _dienst(erkenner=None):
    return KopfdatenService(erkenne_geschlecht=erkenner)


class _Sitzung:
    project_name = "Ablösung Fachanwendung"
    projektnummer = "001-25"
    created_by = "Amélie Brèche"
    auftraggeber = "Max Mustermann"
    verwaltungseinheit = "Testamt"
    geschaeftsbereich = "Generalsekretariat"
    innenauftragsnummer = "IA-42"


# ---- Anlegen -------------------------------------------------------------- #

def test_die_erstbefuellung_nimmt_was_da_ist(app, projekt):
    _, p = projekt
    svc = _dienst(lambda n: "w" if n.startswith("Am") else "m")
    eintrag = svc.stelle_bereit(p, session=_Sitzung())
    assert eintrag.projektleiter == "Amélie Brèche"
    assert eintrag.auftraggeber == "Max Mustermann"
    assert eintrag.verwaltungseinheit == "Testamt"


def test_die_anrede_wird_beim_anlegen_bestimmt(app, projekt):
    _, p = projekt
    svc = _dienst(lambda n: "w" if n.startswith("Am") else "m")
    eintrag = svc.stelle_bereit(p, session=_Sitzung())
    assert eintrag.projektleiter_anrede == "w"
    assert eintrag.auftraggeber_anrede == "m"


def test_das_dokument_schlaegt_die_sitzung_beim_ANLEGEN(app, projekt):
    """Beim ersten Mal ist die geprüfte Fassung die bessere Quelle."""
    _, p = projekt
    eintrag = _dienst().stelle_bereit(
        p, session=_Sitzung(), aus_dokument={"projektleiter": "Frau Aus Dokument"})
    assert eintrag.projektleiter == "Frau Aus Dokument"


def test_ein_zweiter_aufruf_legt_nichts_neu_an(app, projekt):
    _, p = projekt
    svc = _dienst()
    erst = svc.stelle_bereit(p, session=_Sitzung())
    svc.speichere(p.id, {"projektleiter": "Von Hand geändert"})
    zweit = svc.stelle_bereit(p, session=_Sitzung(),
                              aus_dokument={"projektleiter": "Aus Dokument"})
    assert erst.id == zweit.id
    assert zweit.projektleiter == "Von Hand geändert"     # nicht ueberschrieben


def test_die_anrede_kostet_nur_beim_anlegen_einen_aufruf(app, projekt):
    """Der eigentliche Grund für diese Ablage: sonst fragt jeder Download neu."""
    _, p = projekt
    gefragt = []
    svc = _dienst(lambda n: (gefragt.append(n), "w")[1])
    svc.stelle_bereit(p, session=_Sitzung())
    svc.stelle_bereit(p, session=_Sitzung())
    svc.stelle_bereit(p, session=_Sitzung())
    assert len(gefragt) == 2          # einmal Projektleitung, einmal Auftraggeber


def test_eine_fehlgeschlagene_schaetzung_wirft_nichts_um(app, projekt):
    _, p = projekt

    def kaputt(name):
        raise RuntimeError("Modell nicht erreichbar")

    eintrag = _dienst(kaputt).stelle_bereit(p, session=_Sitzung())
    assert eintrag.projektleiter_anrede == "u"


# ---- Ändern --------------------------------------------------------------- #

def test_die_anrede_laesst_sich_richtigstellen(app, projekt):
    """«Andrea», «Kim», «Dominique» – eine Vermutung, die man nicht
    korrigieren kann, ist schlimmer als eine Lücke."""
    _, p = projekt
    svc = _dienst(lambda n: "m")
    svc.stelle_bereit(p, session=_Sitzung())
    geaendert = svc.speichere(p.id, {"projektleiter_anrede": "w"})
    assert geaendert.projektleiter_anrede == "w"


def test_eine_unbekannte_anrede_wird_nicht_uebernommen(app, projekt):
    _, p = projekt
    svc = _dienst()
    svc.stelle_bereit(p, session=_Sitzung())
    svc.speichere(p.id, {"projektleiter_anrede": "divers"})
    assert svc.lade(p.id).projektleiter_anrede == "u"


def test_ein_geleertes_feld_im_formular_ist_absicht(app, projekt):
    """Anders als beim Rückweg aus Word: wer hier leert, will es leer."""
    _, p = projekt
    svc = _dienst()
    svc.stelle_bereit(p, session=_Sitzung())
    svc.speichere(p.id, {"geschaeftsbereich": ""})
    assert svc.lade(p.id).geschaeftsbereich == ""


# ---- Der Abgleich --------------------------------------------------------- #

def test_ein_abweichendes_dokument_wird_gemeldet(app, projekt):
    _, p = projekt
    svc = _dienst()
    svc.stelle_bereit(p, session=_Sitzung())
    abweichungen = svc.abweichungen(p.id, {"projektleiter": "Frau Neu",
                                           "auftraggeber": "Max Mustermann"})
    assert len(abweichungen) == 1
    a = abweichungen[0]
    assert a["feld"] == "projektleiter"
    assert a["hinterlegt"] == "Amélie Brèche" and a["im_dokument"] == "Frau Neu"
    assert a["beschriftung"] == "Projektleitung"


def test_ein_leeres_feld_im_dokument_ist_keine_abweichung(app, projekt):
    """Es ist eine fehlende Angabe, keine andere Angabe."""
    _, p = projekt
    svc = _dienst()
    svc.stelle_bereit(p, session=_Sitzung())
    assert svc.abweichungen(p.id, {"projektleiter": "", "auftraggeber": None}) == []


def test_ohne_uebernahme_bleibt_alles_stehen(app, projekt):
    """Das ist der Punkt: nicht still überschreiben."""
    _, p = projekt
    svc = _dienst()
    svc.stelle_bereit(p, session=_Sitzung())
    svc.abweichungen(p.id, {"projektleiter": "Frau Neu"})
    assert svc.lade(p.id).projektleiter == "Amélie Brèche"


def test_uebernommen_wird_nur_das_bestaetigte(app, projekt):
    _, p = projekt
    svc = _dienst()
    svc.stelle_bereit(p, session=_Sitzung())
    svc.uebernimm(p.id, {"projektleiter": "Frau Neu", "auftraggeber": "Herr Neu"},
                  ["projektleiter"])
    eintrag = svc.lade(p.id)
    assert eintrag.projektleiter == "Frau Neu"
    assert eintrag.auftraggeber == "Max Mustermann"      # nicht bestaetigt


def test_ein_neuer_name_bekommt_eine_neue_anrede(app, projekt):
    """Die alte Anrede gehörte zum alten Namen – für den neuen ist sie nicht belegt."""
    _, p = projekt
    namen = {"Amélie Brèche": "w", "Herr Neu": "m"}
    svc = _dienst(lambda n: namen.get(n, "u"))
    svc.stelle_bereit(p, session=_Sitzung())
    assert svc.lade(p.id).projektleiter_anrede == "w"
    svc.uebernimm(p.id, {"projektleiter": "Herr Neu"}, ["projektleiter"])
    assert svc.lade(p.id).projektleiter_anrede == "m"


# ---- Der Anschluss an die Dokumente --------------------------------------- #

def test_die_hinterlegte_anrede_wird_nicht_neu_geschaetzt():
    """Ein gepflegter Wert schlägt eine Vermutung – und spart den Aufruf."""
    gefragt = []
    angaben = kopfmodul.metadaten(
        vorrang={"projektleiter": "Dominique Muster", "projektleiter_anrede": "w"},
        erkenne_geschlecht=lambda n: (gefragt.append(n), "m")[1])
    assert angaben["projektleiter_geschlecht"] == "w"
    assert "Dominique Muster" not in gefragt


def test_ohne_hinterlegte_anrede_wird_geschaetzt():
    angaben = kopfmodul.metadaten(vorrang={"projektleiter": "Amélie Brèche"},
                                  erkenne_geschlecht=lambda n: "w")
    assert angaben["projektleiter_geschlecht"] == "w"


def test_die_klassifizierung_kommt_aus_den_kopfdaten():
    angaben = kopfmodul.metadaten(vorrang={"klassifizierung": "Intern"})
    assert angaben["klassifizierung"] == "Intern"


# ---- Über die Oberfläche -------------------------------------------------- #

def test_die_seite_laesst_sich_oeffnen(app, projekt):
    c, p = projekt
    html = c.get(f"/projekt/{p.id}/kopfdaten").get_data(as_text=True)
    assert "Wer und was steht im Kopf jedes Dokuments?" in html
    assert "Amélie Brèche" in html
    assert "Anrede der Projektleitung" in html


def test_bearbeiten_ueber_das_formular(app, projekt):
    c, p = projekt
    daten = {f: "" for f in FELDER}
    daten.update({"projektleiter": "Frau Korrigiert",
                  "projektleiter_anrede": "w", "auftraggeber_anrede": "m"})
    html = c.post(f"/projekt/{p.id}/kopfdaten", data=daten).get_data(as_text=True)
    assert "gesichert" in html
    eintrag = app.kopfdaten_service.lade(p.id)
    assert eintrag.projektleiter == "Frau Korrigiert"
    assert eintrag.projektleiter_anrede == "w"


def test_der_einstieg_steht_auf_der_projektseite(app, projekt):
    c, p = projekt
    html = c.get(f"/projekt/{p.id}").get_data(as_text=True)
    assert f"/projekt/{p.id}/kopfdaten" in html


def test_die_kopfdaten_erscheinen_im_erzeugten_dokument(app, projekt):
    """Der eigentliche Zweck: was hier steht, steht in jedem Dokument."""
    from docx import Document

    from app.domains.freigabe import dokumente as dk
    from app.domains.generation.service import _p_text

    c, p = projekt
    app.kopfdaten_service.stelle_bereit(p, session=_Sitzung())
    app.kopfdaten_service.speichere(
        p.id, {"projektleiter": "Frau Korrigiert", "projektleiter_anrede": "w",
               "auftraggeber": "Herr Beispiel", "auftraggeber_anrede": "m"})
    c.post(f"/projekt/{p.id}/freigabe/erzeugen")

    roh = c.get(f"/projekt/{p.id}/freigabe/checkliste/K.docx").get_data()
    import io as _io
    doc = Document(_io.BytesIO(roh))
    W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"
    inhalt = "\n".join(_p_text(x) for x in doc.element.body.iter(W))
    assert "ProjektleiterinFrau Korrigiert" in inhalt
    assert "AuftraggeberHerr Beispiel" in inhalt
    assert dk.CHECKLISTE_VORLAGE.exists()


# ---- Kein stilles Nichtstun ----------------------------------------------- #
#
# Beim Bauen gemessen: das Formular speicherte ins Leere, weil der Datensatz
# beim ersten Abschicken noch gar nicht existierte – und die Seite meldete
# trotzdem «gesichert». Eine Änderung, die verschwindet und als erfolgreich
# gemeldet wird, ist schlimmer als eine Fehlermeldung.

def test_speichern_ohne_datensatz_meldet_sich(app, projekt):
    from app.domains.dokumentenkopf.service import KopfdatenFehler

    _, p = projekt
    with pytest.raises(KopfdatenFehler, match="noch keine Kopfdaten"):
        _dienst().speichere(p.id, {"projektleiter": "X"})


def test_uebernehmen_ohne_datensatz_meldet_sich(app, projekt):
    from app.domains.dokumentenkopf.service import KopfdatenFehler

    _, p = projekt
    with pytest.raises(KopfdatenFehler, match="noch keine Kopfdaten"):
        _dienst().uebernimm(p.id, {"projektleiter": "X"}, ["projektleiter"])


def test_das_formular_legt_den_datensatz_bei_bedarf_an(app, projekt):
    """Der Weg über die Oberfläche darf nicht daran scheitern."""
    c, p = projekt
    assert app.kopfdaten_service.lade(p.id) is None
    daten = {f: "" for f in FELDER}
    daten["projektleiter"] = "Direkt gespeichert"
    c.post(f"/projekt/{p.id}/kopfdaten", data=daten)
    assert app.kopfdaten_service.lade(p.id).projektleiter == "Direkt gespeichert"
