"""Beweist: was HERMES verbindlich vorgibt, steht im Dokument.

Zwei gemessene Ausfälle am selben erzeugten PIA (BKI Test 8, V0.1):

1. **Kap. 3.1 ohne Pflichtrollen.** In der Tabelle stand einzig
   «Externe Fachexpertise» – Projektleiter und Auftraggeber fehlten, obwohl
   sie in der Initialisierung immer besetzt sind. Kap. 5 erbte den Mangel,
   weil es aus 3.1 abgeleitet wird. Ursache war nicht die Ergänzungslogik
   (die ist nachweislich in Ordnung), sondern dass sie nie lief: lieferte das
   Modell für den Abschnitt keine Liste, brach die Nachbearbeitung vorher ab.

2. **Kap. 0.5 leer.** «Vorgaben, Methoden und Werkzeuge» hatte überhaupt
   keinen Abschnitt in der Methodenbeschreibung. Was nicht beschrieben ist,
   wird nicht befüllt – die Vorlagezeile «MS Office Palette gem. Vorlage»
   blieb stehen, und die Invariantenprüfung meldete das zu Recht (D-004).
"""
import pytest

from app.config import Config
from app.domains.interview.service import InterviewService
from app.factory import create_app


@pytest.fixture
def app(tmp_path):
    from app.shared.database import SessionLocal

    class _Cfg(Config):
        DATABASE_URL = "sqlite:///" + str(tmp_path / "pf.db").replace("\\", "/")
        SUPERADMIN_EMAIL = "betreiber@test.ch"
        SUPERADMIN_PASSWORD = "pw-super"
        SECRET_KEY = "test-secret"

    SessionLocal.remove()
    application = create_app(_Cfg)
    SessionLocal.remove()
    yield application
    SessionLocal.remove()


class _Dienst(InterviewService):
    """Nur die Nachbearbeitung – ohne Datenbank, ohne Modell."""
    def __init__(self):
        self.llm = None


# ---- Kap. 3.1: die Pflichtrollen hängen nicht am Modell ------------------- #

def test_ohne_extraktion_stehen_die_pflichtrollen_trotzdem():
    """Gemessen: das Modell lieferte keine Liste – und 3.1 blieb ohne Rollen."""
    abschnitt = {"id": "personalaufwand", "type": "table",
                 "columns": [{"id": "rolle"}, {"id": "name"}, {"id": "aufwand"}]}
    antwort = {"extracted": None}          # genau der gemessene Fall
    _Dienst()._postprocess_section(abschnitt, antwort, {})
    rollen = [r["rolle"] for r in antwort["extracted"]]
    assert "Projektleiter" in rollen and "Auftraggeber" in rollen


def test_eine_leere_liste_fuehrt_zum_selben_ergebnis():
    abschnitt = {"id": "personalaufwand", "type": "table",
                 "columns": [{"id": "rolle"}]}
    antwort = {"extracted": []}
    _Dienst()._postprocess_section(abschnitt, antwort, {})
    assert len(antwort["extracted"]) >= 2


def test_ein_freitext_wird_nicht_zur_tabelle_umgebogen():
    """Die Rettung gilt nur für Tabellen – ein Fliesstext bleibt Fliesstext."""
    abschnitt = {"id": "ausgangslage", "type": "free_text"}
    antwort = {"extracted": {"text": "Der Kanton beabsichtigt …"}}
    _Dienst()._postprocess_section(abschnitt, antwort, {})
    assert antwort["extracted"] == {"text": "Der Kanton beabsichtigt …"}


# ---- Kap. 0.5: der Abschnitt existiert und trägt seine Pflichtzeile ------- #

def test_kapitel_0_5_ist_beschrieben():
    import yaml

    from app.config import BASE_DIR
    from pathlib import Path

    methode = yaml.safe_load(
        Path(BASE_DIR, "methods", "hermes_pia", "method.yaml").read_text(encoding="utf-8"))
    abschnitte = {s["number"]: s for s in methode["sections"]}
    assert "0.5" in abschnitte, sorted(abschnitte)
    assert abschnitte["0.5"]["title"] == "Vorgaben, Methoden und Werkzeuge"


def test_die_projektmanagementmethode_steht_immer_drin():
    abschnitt = {"id": "vorgaben_methoden", "type": "table",
                 "columns": [{"id": "titel"}, {"id": "vorgabe"}, {"id": "version"}],
                 "pflichtzeilen": [{"titel": "Projektmanagementmethode",
                                    "vorgabe": "HERMES"}]}
    antwort = {"extracted": None}
    _Dienst()._postprocess_section(abschnitt, antwort, {})
    assert antwort["extracted"] == [{"titel": "Projektmanagementmethode",
                                     "vorgabe": "HERMES"}]


def test_was_der_projektleiter_gesagt_hat_schlaegt_die_vorgabe():
    """Die Pflichtzeile ergänzt – sie überschreibt nie."""
    abschnitt = {"id": "vorgaben_methoden", "type": "table",
                 "columns": [{"id": "titel"}, {"id": "vorgabe"}],
                 "pflichtzeilen": [{"titel": "Projektmanagementmethode",
                                    "vorgabe": "HERMES"}]}
    antwort = {"extracted": [{"titel": "Projektmanagementmethode",
                              "vorgabe": "HERMES 2022, kantonale Ausprägung"}]}
    _Dienst()._postprocess_section(abschnitt, antwort, {})
    assert len(antwort["extracted"]) == 1
    assert "kantonale" in antwort["extracted"][0]["vorgabe"]


def test_ohne_pflichtzeilen_passiert_nichts():
    abschnitt = {"id": "sachmittel", "type": "table", "columns": [{"id": "bezeichnung"}]}
    antwort = {"extracted": []}
    _Dienst()._postprocess_section(abschnitt, antwort, {})
    assert antwort["extracted"] == []


def test_die_vorlage_findet_das_kapitel_wieder():
    """Ohne Zuordnung im Vorlagen-Verzeichnis bliebe der Abschnitt heimatlos."""
    from app.domains.method.template_structure import _SYNONYME

    assert _SYNONYME["vorgaben, methoden und werkzeuge"] == "vorgaben_methoden"


# ---- Der Link der Vorlage überlebte das Neubeschriften -------------------- #
#
# Gemessen an BKI Test 8 V0.1.1: In Kapitel 0.5 stand vor JEDEM Zelleninhalt
# das Wort «HERMES» – «HERMESHERMES 2022 (…)», «HERMESBundesgesetz über das
# öffentliche Beschaffungswesen …». Die Vorlage hält in dieser Zelle einen
# Hyperlink auf HERMES. Das Neubeschriften entfernte nur <w:r>, nicht
# <w:hyperlink> – der Link blieb stehen, der neue Text kam dahinter, und beim
# Klonen der Zeile vervielfältigte sich der Fehler.

def _zelle_mit_link():
    from lxml import etree

    W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    p = etree.Element(f"{{{W}}}p")
    hl = etree.SubElement(p, f"{{{W}}}hyperlink")
    r = etree.SubElement(hl, f"{{{W}}}r")
    etree.SubElement(r, f"{{{W}}}t").text = "HERMES"
    return p


def test_ein_link_der_vorlage_bleibt_nicht_stehen():
    from app.domains.generation.service import _set_p_text

    p = _zelle_mit_link()
    _set_p_text(p, "HERMES 2022 (Schweizerische Projektmanagementmethode)")
    text = "".join(t.text or "" for t in p.iter(
        "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"))
    assert text == "HERMES 2022 (Schweizerische Projektmanagementmethode)"
    assert "HERMESHERMES" not in text


def test_ein_leerer_wert_loescht_den_link_ebenfalls():
    from app.domains.generation.service import _set_p_text

    p = _zelle_mit_link()
    _set_p_text(p, "")
    assert "".join(t.text or "" for t in p.iter(
        "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t")) == ""


# ---- Leere Tabellen werden nicht übersprungen ----------------------------- #

def test_neu_verarbeiten_ueberspringt_leere_tabellen_nicht(app):
    """Gerade dort muss nachgetragen werden, was die Methode vorschreibt.

    Dieser Test RUFT «Neu verarbeiten» auf, statt Quelltext zu lesen: eine
    frühere Fassung dieser Prüfung hätte den Fehler nicht bemerkt.
    """
    import json

    auth = app.auth_service
    org = auth.create_org("OrgP")
    auth.create_user("pl@p.ch", "pw", org_id=org.id, can_read=True, can_write=True)
    org_id = org.id
    c = app.test_client()
    c.post("/login", data={"email": "pl@p.ch", "password": "pw"})
    c.post("/interview/start", data={"project_name": "Leertest",
                                     "projektleiter": "Frau Muster"})
    projekt = app.projekt_service.projekte_for_org(org_id)[0]
    erg = app.projekt_service.ergebnisse(projekt.id)[0]
    sitzung = app.interview_service.session_for_ergebnis(erg.id)

    # Der gemessene Zustand: der Abschnitt EXISTIERT, ist aber leer.
    from app.domains.interview.models import InterviewSession
    from app.shared.database import SessionLocal
    db = SessionLocal()
    eintrag = db.get(InterviewSession, sitzung.id)
    eintrag.answers_json = json.dumps({"personalaufwand": {"extracted": []}})
    db.commit()

    app.interview_service.reprocess(sitzung.id)

    danach = json.loads(db.get(InterviewSession, sitzung.id).answers_json)
    rollen = [r["rolle"] for r in danach["personalaufwand"]["extracted"]]
    assert "Projektleiter" in rollen and "Auftraggeber" in rollen
