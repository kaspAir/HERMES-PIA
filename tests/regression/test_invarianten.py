"""Beweist: die Invarianten-Prüfung (D-Regeln) nach Katalog v0.3.

Zwei Testgruppen, beide gleich wichtig:
  1. Die Regeln FINDEN, was sie finden sollen.
  2. Die Abgrenzungsfälle (Katalog Abschnitt 11) lösen NICHT aus – Fehlalarme
     kosten mehr Vertrauen als eine fehlende Regel.
"""
import json

import pytest

from app.domains.qualitaet import MUSS, pruefe


class _Session:
    start_datum = "01.03.2026"
    doc_version = "0.1"
    changelog_json = json.dumps([{"version": "0.1", "name": "M", "datum": "01.03.2026"}])


def _ids(ergebnis):
    return {b.regel for b in ergebnis.befunde if not b.nicht_pruefbar}


def _vollstaendige_termine():
    """Terminliste ohne Befund: alle Pflichtergebnisse, richtige Reihenfolge,
    genug Abstand zu den Meilensteinen."""
    return [
        {"ergebnis": "Stakeholderliste", "termin": "05.03.2026",
         "abnahme": "Projektleiter", "pruefmethode": "Review"},
        {"ergebnis": "Rechtsgrundlagenanalyse", "termin": "10.03.2026",
         "abnahme": "Projektleiter", "pruefmethode": "Review"},
        {"ergebnis": "Schutzbedarfsanalyse", "termin": "12.03.2026",
         "abnahme": "ISDS-Verantwortlicher", "pruefmethode": "Review"},
        {"ergebnis": "Studie", "termin": "20.03.2026",
         "abnahme": "Projektleiter", "pruefmethode": "Review"},
        {"ergebnis": "Meilenstein Weiteres Vorgehen", "termin": "10.04.2026",
         "abnahme": "Auftraggeber", "pruefmethode": "Formelle Abnahme (Entscheid)"},
        {"ergebnis": "Projektmanagementplan", "termin": "20.04.2026",
         "abnahme": "Projektleiter", "pruefmethode": "Review"},
        {"ergebnis": "Durchführungsauftrag", "termin": "01.05.2026",
         "abnahme": "Projektleiter", "pruefmethode": "Review"},
        {"ergebnis": "Meilenstein Durchführungsfreigabe", "termin": "29.05.2026",
         "abnahme": "Auftraggeber", "pruefmethode": "Formelle Abnahme (Entscheid)"},
    ]


# ---- Grundverhalten ------------------------------------------------------ #

def test_leerer_pia_erzeugt_keine_befunde():
    """Katalog 2.2: geprüft wird gegen den Bearbeitungsstand, nicht gegen ein
    leeres Dokument. Sonst ist die Prüfung ab der ersten Sekunde rot."""
    e = pruefe({})
    assert e.befunde == [] or all(b.nicht_pruefbar for b in e.befunde)
    assert e.ausgabe_moeglich is True


def test_alle_regeln_laufen():
    e = pruefe({})
    assert len(e.geprueft) >= 30
    assert e.uebersprungen == []          # keine Regel ist abgestuerzt


def test_nicht_pruefbare_regeln_sind_sichtbar():
    """Eine Regel ohne Datengrundlage wird AUSGEWIESEN, nicht still uebersprungen -
    sonst glaubt man 33 Regeln zu pruefen und prueft 30."""
    e = pruefe({})
    offen = {b.regel for b in e.offene_regeln}
    assert {"D-008", "D-043", "D-073"} <= offen
    assert all(b.grund for b in e.offene_regeln)


def test_muss_befund_verhindert_die_ausgabe():
    e = pruefe({"ziele": {"extracted": [
        {"kategorie": "Vorgehensziel", "beschreibung": "A",
         "messgroesse": "m", "prioritaet": "Hoch"}]}})
    assert "D-030" in _ids(e)             # Systemziel fehlt
    assert e.ausgabe_moeglich is False


def test_vorbehalt_und_hinweis_blockieren_nicht():
    e = pruefe({"rahmenbedingungen": {"extracted": []}})
    assert "D-033" in _ids(e)
    assert e.ausgabe_moeglich is True


# ---- Konsistenzregeln ---------------------------------------------------- #

def test_d001_pt_gegen_monatsverteilung():
    a = {"personalaufwand": {"extracted": [{"rolle": "Projektleiter", "aufwand": "40"}]},
         "projektorganisation": {"extracted": [
             {"rolle_person": "Projektleiter / M", "monat_1": "10", "monat_2": "10"}]}}
    assert "D-001" in _ids(pruefe(a))


def test_d001_toleranz_verhindert_rundungslaerm():
    """Katalog Abschnitt 11: ohne Toleranz schlaegt die Regel grundlos an."""
    a = {"personalaufwand": {"extracted": [{"rolle": "Projektleiter", "aufwand": "40"}]},
         "projektorganisation": {"extracted": [
             {"rolle_person": "Projektleiter / M", "monat_1": "20", "monat_2": "19.7"}]}}
    assert "D-001" not in _ids(pruefe(a))


def test_d001_summiert_mehrfach_besetzte_rollen():
    """Mehrere Anwendervertreter werden ueber alle Instanzen summiert."""
    a = {"personalaufwand": {"extracted": [
             {"rolle": "Anwendervertreter", "aufwand": "10"},
             {"rolle": "Anwendervertreter", "aufwand": "10"}]},
         "projektorganisation": {"extracted": [
             {"rolle_person": "Anwendervertreter / A", "monat_1": "20"}]}}
    assert "D-001" not in _ids(pruefe(a))


def test_d072_risikozahl():
    a = {"risiken": {"extracted": [{"beschreibung": "R", "ew": "Hoch", "ag": "Mittel",
                                    "risikozahl": "4", "massnahmen": "M",
                                    "verantwortung": "Projektleiter", "termin": "laufend"}]}}
    assert "D-072" in _ids(pruefe(a))
    a["risiken"]["extracted"][0]["risikozahl"] = "6"
    assert "D-072" not in _ids(pruefe(a))


def test_d054_reihenfolge_und_d055_reviewzeit():
    a = {"termine": {"extracted": [
        {"ergebnis": "Studie", "termin": "05.03.2026", "abnahme": "Projektleiter",
         "pruefmethode": "Review"},
        {"ergebnis": "Rechtsgrundlagenanalyse", "termin": "20.03.2026",
         "abnahme": "Projektleiter", "pruefmethode": "Review"},
        {"ergebnis": "Meilenstein Weiteres Vorgehen", "termin": "06.03.2026",
         "abnahme": "Auftraggeber", "pruefmethode": "Entscheid"}]}}
    ids = _ids(pruefe(a))
    assert "D-054" in ids and "D-055" in ids


def test_d056_aufwand_passt_nicht_in_die_phasendauer():
    a = {"personalaufwand": {"extracted": [{"rolle": "Projektleiter", "aufwand": "300"}]}}
    assert "D-056" in _ids(pruefe(a, phasendauer_monate=3))
    assert "D-056" not in _ids(pruefe(a, phasendauer_monate=24))


# ---- Abgrenzungsfälle (Katalog Abschnitt 11) ----------------------------- #
#
# Diese Faelle sind LEGITIM. Wer sie nicht beruecksichtigt, erzeugt Fehlalarme -
# und Fehlalarme kosten mehr Vertrauen als eine fehlende Regel.

def test_abgrenzung_meilenstein_braucht_keine_pruefmethode_aber_eine_entscheidform():
    """Meilensteinzeilen haben eine Entscheidrolle statt einer Pruefmethode -
    aber leer bleiben duerfen sie trotzdem nicht."""
    mit = {"termine": {"extracted": [
        {"ergebnis": "Meilenstein Weiteres Vorgehen", "termin": "01.04.2026",
         "abnahme": "Auftraggeber", "pruefmethode": "Formelle Abnahme (Entscheid)"}]}}
    assert "D-052" not in _ids(pruefe(mit))
    ohne = {"termine": {"extracted": [
        {"ergebnis": "Meilenstein Weiteres Vorgehen", "termin": "01.04.2026",
         "abnahme": "Auftraggeber", "pruefmethode": ""}]}}
    befunde = [b for b in pruefe(ohne).befunde if b.regel == "D-052"]
    assert befunde and "Entscheidform" in befunde[0].meldung


def test_abgrenzung_kein_phasenbericht_gefordert():
    """In der Initialisierung entsteht KEIN Phasenbericht – D-050 darf ihn nicht
    verlangen."""
    e = pruefe({"termine": {"extracted": _vollstaendige_termine()}})
    fehlend = " ".join(b.meldung for b in e.befunde if b.regel == "D-050")
    assert "Phasenbericht" not in fehlend


def test_abgrenzung_projektinitialisierungsfreigabe_wird_nicht_verlangt():
    """Sie ist der geplante START der Phase, kein Ergebnis daraus."""
    e = pruefe({"termine": {"extracted": _vollstaendige_termine()}})
    fehlend = " ".join(b.meldung for b in e.befunde if b.regel in ("D-050", "D-051"))
    assert "Projektinitialisierungsfreigabe" not in fehlend


def test_abgrenzung_beschaffungsanalyse_nur_wenn_beschaffung_vorgesehen():
    """D-050 ist eine BEDINGTE Regel."""
    ohne = pruefe({"termine": {"extracted": _vollstaendige_termine()}},
                  beschaffung_vorgesehen=False)
    assert not [b for b in ohne.befunde
                if b.regel == "D-050" and "Beschaffung" in b.meldung]
    mit = pruefe({"termine": {"extracted": _vollstaendige_termine()}},
                 beschaffung_vorgesehen=True)
    assert [b for b in mit.befunde
            if b.regel == "D-050" and "Beschaffung" in b.meldung]


def test_abgrenzung_externe_rolle_rechnet_extern():
    """Externe Rollen haben keinen internen Kostensatz."""
    a = {"personalaufwand": {"extracted": [
             {"rolle": "Projektleiter", "aufwand": "10"},
             {"rolle": "Externe Expertise", "aufwand": "10"}]},
         "kosten": {"extracted": [
             {"phase": "Personalkosten intern", "betrag": "12000"},
             {"phase": "Personalkosten extern", "betrag": "18000"},
             {"phase": "Total", "betrag": "30000"}]}}
    assert "D-002" not in _ids(pruefe(a, tarife={"intern": 1200, "extern": 1800}))


def test_abgrenzung_vollstaendige_terminliste_ohne_befund():
    """Der Positivfall: ein korrekt gefuellter Abschnitt loest NICHTS aus."""
    e = pruefe({"termine": {"extracted": _vollstaendige_termine()}})
    fuer_41 = {b.regel for b in e.befunde
               if b.regel in ("D-050", "D-051", "D-052", "D-053", "D-054", "D-055")}
    assert fuer_41 == set(), [str(b) for b in e.befunde]


def test_abgrenzung_rollenbezeichnungen_sind_keine_personennamen():
    """D-007 ist nur ein Hinweis - eine korrekte Rolle darf nie melden."""
    a = {"termine": {"extracted": [
        {"ergebnis": "Studie", "termin": "01.04.2026", "abnahme": "ISDS-Verantwortlicher",
         "pruefmethode": "Review"}]}}
    assert "D-007" not in _ids(pruefe(a))


def test_abgrenzung_mandantenrolle_wird_akzeptiert():
    a = {"termine": {"extracted": [
        {"ergebnis": "Studie", "termin": "01.04.2026", "abnahme": "Amtsleitung JVOG",
         "pruefmethode": "Review"}]}}
    assert "D-053" not in _ids(pruefe(a, zusatzrollen=["Amtsleitung JVOG"]))


def test_abgrenzung_gleichstand_der_zielarten_meldet_nicht():
    """D-032 meldet nur den umgekehrten Fall, NICHT Gleichstand."""
    a = {"ziele": {"extracted": [
        {"kategorie": "Systemziel", "beschreibung": "A", "messgroesse": "m",
         "prioritaet": "Hoch"},
        {"kategorie": "Vorgehensziel", "beschreibung": "B", "messgroesse": "m",
         "prioritaet": "Hoch"}]}}
    ids = _ids(pruefe(a))
    assert "D-032" not in ids and "D-030" not in ids


# ---- Einbindung: laufend Hinweis, vor der Ausgabe verbindlich ------------ #

@pytest.fixture
def app(tmp_path):
    from app.config import Config
    from app.factory import create_app
    from app.shared.database import SessionLocal

    class _Cfg(Config):
        DATABASE_URL = "sqlite:///" + str(tmp_path / "q.db").replace("\\", "/")
        SECRET_KEY = "x"
        PSEUDO_BASIS_URL = ""

    SessionLocal.remove()
    anwendung = create_app(_Cfg)
    SessionLocal.remove()
    yield anwendung
    SessionLocal.remove()


def _pia_mit_muss_befund(app):
    """Legt eine Session an, deren Zieltabelle einen Muss-Befund ausloest."""
    auth = app.auth_service
    org = auth.create_org("Org")
    auth.create_user("u@o.ch", "pw", role="org_admin", org_id=org.id,
                     can_read=True, can_write=True, can_delete=True)
    c = app.test_client()
    c.post("/login", data={"email": "u@o.ch", "password": "pw"})
    ort = c.post("/interview/start",
                 data={"project_name": "P", "projektleiter": "X"}).headers["Location"]
    sid = int(ort.rstrip("/").split("/")[-1])

    from app.shared.database import SessionLocal
    from app.domains.interview.models import InterviewSession
    db = SessionLocal()
    s = db.query(InterviewSession).get(sid)
    s.answers_json = json.dumps({"ziele": {"extracted": [
        {"kategorie": "Vorgehensziel", "beschreibung": "A", "messgroesse": "m",
         "prioritaet": "Hoch"}]}})
    db.commit()
    return c, sid


def test_ausgabe_wird_bei_muss_befund_verhindert(app):
    """Briefing 4.1: Muss-Befunde verhindern die Ausgabe."""
    c, sid = _pia_mit_muss_befund(app)
    r = c.get(f"/interview/{sid}/download/PIA.docx")
    assert r.status_code == 409
    seite = r.get_data(as_text=True)
    assert "nicht ausgabefähig" in seite
    assert "D-030" in seite                      # die Regel wird benannt


def test_interview_zeigt_die_befunde_laufend_als_hinweis(app):
    c, sid = _pia_mit_muss_befund(app)
    seite = c.get(f"/interview/{sid}").get_data(as_text=True)
    assert "Qualitätsprüfung" in seite
    assert "D-030" in seite


def test_notausgang_liefert_das_dokument_trotzdem(app):
    """Fuer die Entwicklung – im Alltag sollen die Befunde behoben werden."""
    c, sid = _pia_mit_muss_befund(app)
    r = c.get(f"/interview/{sid}/download/PIA.docx?trotzdem=1")
    assert r.status_code == 200
    assert r.headers["Content-Type"].startswith("application/vnd.openxml")
