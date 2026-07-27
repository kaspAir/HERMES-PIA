"""Beweist: die fachliche Prüfung aus Auftraggeber-Sicht (Stufe 4).

Die vier Abnahmekriterien aus Briefing 5.3 sind einzeln geprüft:
  1. Der Prüfer meldet KEINE Formfehler, welche die Invarianten schon gemeldet haben.
  2. Der Prüfer verändert den PIA NICHT.
  3. Die Ausgabe enthält immer eine Empfehlung, NIE eine Freigabe.
  4. Die fachlichen Befunde tragen einen Kapitelbezug.
"""
import json
from pathlib import Path

import pytest

from app.config import BASE_DIR as BASE_DIR_T
from app.domains.qualitaet import pruefe
from app.domains.qualitaet.auftraggeber import BEREICH, SKILL, pruefe_fachlich

_PROTOKOLL = {
    "gegenstand": {"umfang": "Kap. 1–7", "nicht_geprueft": "Recht"},
    "befunde": [{"kapitel": "Kap. 1", "kriterium": "Vorfestlegung",
                 "feststellung": "Die Lösung ist bereits gesetzt, aber nicht deklariert.",
                 "gewicht": "Muss", "vorschlag": "Vorfestlegung offenlegen."}],
    "gut": ["Die Ausgangslage nennt einen echten Auslöser."],
    "querbezuege": [{"feststellung": "Ziel 2 hat kein Ergebnis.", "gewicht": "Muss"}],
    "evidenz": [{"feststellung": "Kostenwert ohne Ableitung.", "gewicht": "Vorbehalt"}],
    "herausforderung": [{"frage": "Was, wenn die Ablösung scheitert?",
                         "begruendung": "Kein Rückfallszenario benannt."}],
    "empfehlung": "mit vorbehalt", "begruendung": "Zwei offene Punkte.",
    "auflagen": [{"offen": "Vorfestlegung", "wer": "PL", "bis_wann": "vor Freigabe"}],
    "confidence": {"stufe": "mittel", "begrenzung": "Provenienz fehlt."},
}


class _LLM:
    """Merkt sich den System-Prompt und liefert ein festes Protokoll."""
    def __init__(self, antwort=None):
        self.antwort = antwort if antwort is not None else json.dumps(_PROTOKOLL)
        self.system = None
        self.user = None

    def complete(self, system, messages, max_tokens=1024, **kw):
        self.system = system
        self.user = messages[0]["content"]
        return self.antwort


@pytest.fixture
def skills_dir(tmp_path):
    """Der echte Skill liegt im Repo – hier eine Attrappe mit demselben Vertrag."""
    d = tmp_path / "base" / SKILL
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        f'---\nname: {SKILL}\nversion: "1.0"\napplies_to: {BEREICH}\n---\n\n'
        "METHODE-AUFTRAGGEBER\n", encoding="utf-8")
    # Ein Skill eines ANDEREN Bereichs darf nie hereingeraten.
    fremd = tmp_path / "base" / "rechtsgrundlagen-kartierung"
    fremd.mkdir(parents=True)
    (fremd / "SKILL.md").write_text(
        '---\nname: rechtsgrundlagen-kartierung\nversion: "1.0"\n'
        "applies_to: rechtsgrundlagenanalyse\n---\n\nFREMD\n", encoding="utf-8")
    return tmp_path


# ---- Der Skill wird GELADEN, nicht im Code nachgebaut --------------------- #

def test_skill_wird_geladen_und_injiziert(skills_dir):
    llm = _LLM()
    pruefe_fachlich({"ausgangslage": {"extracted": {"text": "A"}}}, llm,
                    skills_dir=skills_dir)
    assert "METHODE-AUFTRAGGEBER" in llm.system
    assert "FREMD" not in llm.system          # applies_to trennt hart


def test_ohne_skill_keine_pruefung(tmp_path):
    """Lieber kein Protokoll als ein im Code nachgebautes."""
    protokoll, versionen, grund = pruefe_fachlich({}, _LLM(), skills_dir=tmp_path)
    assert protokoll is None and versionen == []


def test_ohne_llm_keine_pruefung(skills_dir):
    protokoll, versionen, grund = pruefe_fachlich({}, None, skills_dir=skills_dir)
    assert protokoll is None and versionen == [] and grund


def test_versions_triple_wird_zurueckgegeben(skills_dir):
    _, versionen, _ = pruefe_fachlich({}, _LLM(), skills_dir=skills_dir)
    assert versionen and versionen[0]["name"] == SKILL
    assert versionen[0]["version"] == "1.0"


# ---- Abnahme 1: Formfehler nicht doppelt melden -------------------------- #

def test_invariantenbefunde_gehen_als_datenstruktur_mit(skills_dir):
    """Briefing 5.1: als Datenstruktur, NICHT als Anzeigetext – sonst formuliert
    das Modell sie um und meldet sie doch wieder."""
    invarianten = pruefe({"ziele": {"extracted": [
        {"kategorie": "Vorgehensziel", "beschreibung": "A", "messgroesse": "m",
         "prioritaet": "Hoch"}]}})
    llm = _LLM()
    pruefe_fachlich({}, llm, invarianten=invarianten, skills_dir=skills_dir)

    # Der Prompt enthaelt Nutzdaten UND Schema - nur das erste Objekt lesen.
    eingang, _ = json.JSONDecoder().raw_decode(llm.user[llm.user.index("{"):])
    befunde = eingang["invarianten_befunde"]
    assert "D-030" in befunde["regeln"]           # die Regel-ID geht mit
    assert befunde["muss"] >= 1
    # Der Meldungstext NICHT – sonst waere die Versuchung da, ihn zu wiederholen.
    assert "Systemziel" not in json.dumps(befunde)
    assert "melde sie NICHT erneut" in llm.user


def test_system_prompt_verbietet_doppelmeldung_und_umschreiben(skills_dir):
    llm = _LLM()
    pruefe_fachlich({}, llm, skills_dir=skills_dir)
    assert "NICHT um" in llm.system                  # kein Umschreiben
    assert "NIE eine Freigabe" in llm.system
    assert "NICHT erneut" in llm.system              # keine Doppelmeldung


# ---- Abnahme 3: immer Empfehlung, nie Freigabe --------------------------- #

@pytest.mark.parametrize("gemeldet", ["freigegeben", "FREIGABE ERTEILT", "", "ja"])
def test_unerlaubte_freigabe_wird_zur_empfehlung_zurueckgestuft(skills_dir, gemeldet):
    """Deterministisches Sicherheitsnetz: der Prompt sagt es, aber hier haengt
    eine Governance-Zusage dran – Verlassen ist besser als Vertrauen."""
    p = dict(_PROTOKOLL, empfehlung=gemeldet)
    protokoll, _, _ = pruefe_fachlich({}, _LLM(json.dumps(p)), skills_dir=skills_dir)
    assert protokoll["empfehlung"] == "mit vorbehalt"
    assert protokoll["_hinweis"]


def test_gueltige_empfehlung_bleibt(skills_dir):
    for wert in ("freigebbar", "mit vorbehalt", "nicht freigebbar"):
        p = dict(_PROTOKOLL, empfehlung=wert)
        protokoll, _, _ = pruefe_fachlich({}, _LLM(json.dumps(p)), skills_dir=skills_dir)
        assert protokoll["empfehlung"] == wert


def test_unbekanntes_gewicht_wird_zum_hinweis(skills_dir):
    p = dict(_PROTOKOLL, befunde=[{"kapitel": "K", "kriterium": "x",
                                   "feststellung": "y", "gewicht": "kritisch",
                                   "vorschlag": "z"}])
    protokoll, _, _ = pruefe_fachlich({}, _LLM(json.dumps(p)), skills_dir=skills_dir)
    assert protokoll["befunde"][0]["gewicht"] == "Hinweis"


# ---- Abnahme 4: Kapitelbezug --------------------------------------------- #

def test_befunde_tragen_einen_kapitelbezug(skills_dir):
    protokoll, _, _ = pruefe_fachlich({}, _LLM(), skills_dir=skills_dir)
    assert all(b.get("kapitel") for b in protokoll["befunde"])


def test_unlesbare_antwort_ergibt_kein_protokoll(skills_dir):
    """Nichts erfinden: lieber kein Protokoll als ein geratenes."""
    protokoll, versionen, grund = pruefe_fachlich({}, _LLM("kein JSON"), skills_dir=skills_dir)
    assert protokoll is None and versionen        # Versionen trotzdem bekannt


# ---- Abnahme 2: der Pruefer veraendert den PIA NICHT --------------------- #

@pytest.fixture
def app(tmp_path):
    from app.config import Config
    from app.factory import create_app
    from app.shared.database import SessionLocal

    class _Cfg(Config):
        DATABASE_URL = "sqlite:///" + str(tmp_path / "f.db").replace("\\", "/")
        SECRET_KEY = "x"
        PSEUDO_BASIS_URL = ""

    SessionLocal.remove()
    anwendung = create_app(_Cfg)
    SessionLocal.remove()
    yield anwendung
    SessionLocal.remove()


def _angemeldet(app):
    auth = app.auth_service
    org = auth.create_org("Org")
    auth.create_user("u@o.ch", "pw", role="org_admin", org_id=org.id,
                     can_read=True, can_write=True, can_delete=True)
    c = app.test_client()
    c.post("/login", data={"email": "u@o.ch", "password": "pw"})
    ort = c.post("/interview/start",
                 data={"project_name": "P", "projektleiter": "X"}).headers["Location"]
    return c, int(ort.rstrip("/").split("/")[-1])


def test_pruefer_veraendert_den_pia_nicht(app, monkeypatch):
    """Die tragende Invariante der Stufe: wer prueft, erzeugt nicht."""
    from app.domains.interview.models import InterviewSession
    from app.shared.database import SessionLocal

    c, sid = _angemeldet(app)
    inhalt = json.dumps({"ausgangslage": {"extracted": {"text": "Originaltext."}}})
    db = SessionLocal()
    s = db.get(InterviewSession, sid)
    s.answers_json = inhalt
    db.commit()

    app.interview_service.llm = _LLM()
    monkeypatch.setattr("app.domains.qualitaet.auftraggeber.load_skills",
                        lambda *a, **kw: _bundle())
    _lauf_durch(c, sid)

    db2 = SessionLocal()
    assert db2.get(InterviewSession, sid).answers_json == inhalt   # unveraendert


def _mit_inhalt(sid):
    """Ohne Inhalt wird ein Kapitel uebersprungen (kein Befund) – das ist richtig,
    macht aber jeden Test wirkungslos, der Befunde erwartet."""
    from app.domains.interview.models import InterviewSession
    from app.shared.database import SessionLocal
    db = SessionLocal()
    s = db.get(InterviewSession, sid)
    s.answers_json = json.dumps({
        "ausgangslage": {"extracted": {"text": "Die Lösung steht bereits fest."}},
        "ziele": {"extracted": [{"kategorie": "Systemziel", "beschreibung": "A",
                                 "messgroesse": "m", "prioritaet": "Hoch"}]},
    })
    db.commit()
    return sid


def _lauf_id(sid):
    from app.domains.qualitaet.service import letzte_fachpruefung
    return letzte_fachpruefung(sid).id


def _lauf_durch(c, sid, max_schritte=20):
    """Startet den Lauf und arbeitet alle Schritte ab – wie es der Browser tut."""
    c.post(f"/interview/{sid}/fachpruefung")
    pid = _lauf_id(sid)
    for _ in range(max_schritte):
        r = c.post(f"/interview/{sid}/fachpruefung/schritt", data={"pruefung_id": pid})
        if r.status_code != 200 or r.get_json().get("fertig"):
            return r
    raise AssertionError("Lauf wurde nicht fertig")


def _bundle():
    from app.domains.skills.loader import SkillBundle
    return SkillBundle(text="METHODE-AUFTRAGGEBER",
                       versions=[{"name": SKILL, "version": "1.0", "scope": "base"}])


def test_protokoll_wird_angezeigt_mit_empfehlung(app, monkeypatch):
    c, sid = _angemeldet(app)
    _mit_inhalt(sid)
    app.interview_service.llm = _LLM()
    monkeypatch.setattr("app.domains.qualitaet.auftraggeber.load_skills",
                        lambda *a, **kw: _bundle())
    _lauf_durch(c, sid)
    seite = c.get(f"/interview/{sid}/fachpruefung").get_data(as_text=True)
    assert "Empfehlung an den Auftraggeber" in seite
    assert "keine Freigabe" in seite
    assert "Kap. 1" in seite                       # Kapitelbezug sichtbar
    assert "Vorfestlegung offenlegen" in seite     # Vorschlag wird ANGEZEIGT


def test_widerspruch_wird_festgehalten_und_befund_bleibt(app, monkeypatch):
    """Briefing 5.1: die Ablehnung wird festgehalten – nicht wegdiskutiert."""
    c, sid = _angemeldet(app)
    _mit_inhalt(sid)
    app.interview_service.llm = _LLM()
    monkeypatch.setattr("app.domains.qualitaet.auftraggeber.load_skills",
                        lambda *a, **kw: _bundle())
    _lauf_durch(c, sid)

    from app.domains.qualitaet.service import letzte_fachpruefung
    zeile = letzte_fachpruefung(sid)
    c.post(f"/interview/{sid}/fachpruefung/widerspruch",
           data={"pruefung_id": zeile.id, "befund": "0",
                 "begruendung": "Bewusst so entschieden."})

    seite = c.get(f"/interview/{sid}/fachpruefung").get_data(as_text=True)
    assert "Bewusst so entschieden." in seite
    assert "Die Lösung ist bereits gesetzt" in seite   # der Befund BLEIBT stehen


# ---- Unerwartete Fehler sind lesbar, nicht nackt ------------------------- #

def test_unerwarteter_fehler_nennt_klasse_und_meldung(app):
    """Vorher endete jeder unbehandelte Fehler als nacktes «Internal Server
    Error» – man musste erst ins Serverlog, um zu wissen, wonach man sucht."""
    class _Kaputt:
        def complete(self, *a, **kw):
            raise RuntimeError("etwas ging schief")

    c, sid = _angemeldet(app)
    app.interview_service.llm = _Kaputt()

    def _explodiert(*a, **kw):
        raise ValueError("Testfehler mit Aussage")

    import app.web.ui_routes as routen
    original = routen.starte_fachpruefung
    routen.starte_fachpruefung = _explodiert
    try:
        # Wie ein Browser: dann HTML mit lesbarer Meldung.
        r = c.post(f"/interview/{sid}/fachpruefung",
                   headers={"Accept": "text/html,application/xhtml+xml"})
        # Wie ein Client ohne HTML-Wunsch: dann JSON mit denselben Angaben.
        j = c.post(f"/interview/{sid}/fachpruefung", headers={"Accept": "application/json"})
    finally:
        routen.starte_fachpruefung = original

    assert r.status_code == 500
    seite = r.get_data(as_text=True)
    assert "ValueError" in seite
    assert "Testfehler mit Aussage" in seite
    assert "nichts verloren" in seite

    assert j.status_code == 500
    assert j.get_json()["error"] == "ValueError"


def test_http_fehler_bleiben_http_fehler(app):
    """Der Auffang-Handler darf 404/403 nicht in 500 verwandeln."""
    c, _ = _angemeldet(app)
    assert c.get("/interview/99999").status_code in (403, 404)


# ---- Worker-Timeout: der teuerste Aufruf der Anwendung -------------------- #
#
# Auf dev hat gunicorn den Worker ERSCHOSSEN (WORKER TIMEOUT, --timeout 120),
# waehrend die Pruefung auf das Modell wartete. Dann greift keine Fehlerseite
# mehr - der Prozess stirbt. Also muss der Aufruf VORHER aufgeben.

def test_zeitlimit_liegt_unter_dem_worker_limit():
    from pathlib import Path

    from app.config import BASE_DIR
    from app.domains.qualitaet.auftraggeber import ZEITLIMIT

    ctl = Path(BASE_DIR, "deploy", "hermes_ctl.sh").read_text(encoding="utf-8")
    import re
    worker = int(re.search(r"--timeout (\d+)", ctl).group(1))
    assert ZEITLIMIT < worker, (
        f"Das Zeitlimit der Pruefung ({ZEITLIMIT}s) muss unter dem "
        f"gunicorn-Worker-Limit ({worker}s) liegen - sonst stirbt der Prozess, "
        f"bevor eine Fehlerseite erscheinen kann.")
    assert worker - ZEITLIMIT >= 20        # Luft fuers Rendern


def test_pruefung_gibt_ihr_zeitlimit_mit(skills_dir):
    gesehen = {}

    class _Merkt:
        def complete(self, system, messages, max_tokens=1024, timeout=None):
            gesehen.update(max_tokens=max_tokens, timeout=timeout)
            return json.dumps(_PROTOKOLL)

    pruefe_fachlich({}, _Merkt(), skills_dir=skills_dir)
    from app.domains.qualitaet.auftraggeber import MAX_TOKENS, ZEITLIMIT
    assert gesehen["timeout"] == ZEITLIMIT
    assert gesehen["max_tokens"] == MAX_TOKENS


def test_zeitueberschritt_nennt_die_ursache(monkeypatch):
    """«nicht erreichbar» waere falsch - der Aufruf kam an, er dauerte zu lange."""
    import requests

    from app.domains.llm.client import LLMClient
    from app.domains.llm.errors import PseudoNichtErreichbar

    def _zu_lange(*a, **kw):
        raise requests.Timeout("read timed out")

    monkeypatch.setattr("app.domains.llm.client.requests.post", _zu_lange)
    with pytest.raises(PseudoNichtErreichbar) as e:
        LLMClient(basis_url="http://x/anthropic").complete("s", [], timeout=95)
    assert "95 Sekunden" in str(e.value)
    assert "nicht erreichbar" not in str(e.value)


# ---- Die drei Fehlschlaege sind unterscheidbar ---------------------------- #
#
# Vorher fuehrten «kein Skill», «kein JSON» und «abgeschnitten» zur selben
# nichtssagenden Meldung - man konnte nicht handeln, ohne nachzufragen.

def test_fehlender_skill_nennt_den_erwarteten_ort(tmp_path):
    _, _, grund = pruefe_fachlich({}, _LLM(), skills_dir=tmp_path)
    assert SKILL in grund and "skills/base" in grund


def test_abgeschnittene_antwort_wird_als_solche_erkannt(skills_dir):
    """Der haeufigste Fall, wenn das Token-Budget nicht reicht."""
    halb = '{"gegenstand":{"umfang":"a"},"befunde":[{"kapitel":"Kap. 1","fest'
    _, _, grund = pruefe_fachlich({}, _LLM(halb), skills_dir=skills_dir)
    assert "unvollständig" in grund
    # Der Grund benennt die Sache, ohne Implementierungsbegriff.
    assert "Token" not in grund


def test_kein_json_nennt_den_anfang_der_antwort(skills_dir):
    _, _, grund = pruefe_fachlich({}, _LLM("Das kann ich nicht beurteilen."),
                                  skills_dir=skills_dir)
    assert "nicht auswertbar" in grund


def test_grund_erscheint_auf_der_fehlerseite(app, monkeypatch):
    c, sid = _angemeldet(app)
    _mit_inhalt(sid)
    app.interview_service.llm = _LLM("Kein JSON hier.")
    monkeypatch.setattr("app.domains.qualitaet.auftraggeber.load_skills",
                        lambda *a, **kw: _bundle())
    c.post(f"/interview/{sid}/fachpruefung")
    r = c.post(f"/interview/{sid}/fachpruefung/schritt",
               data={"pruefung_id": _lauf_id(sid)})
    assert r.status_code == 502
    assert "nicht auswertbar" in r.get_json()["fehler"]


# ---- Eine gekuerzte Pruefung darf nie vollstaendig aussehen -------------- #
#
# Die Ausgabelaenge ist TECHNISCH begrenzt (Zeit/Token). Das ist nicht die
# Proportionalitaet der Methode - dort folgt die Laenge dem Befund. Wird die
# Grenze erreicht, MUSS die Pruefung das sagen.

def test_erreichte_obergrenze_wird_gemeldet(skills_dir):
    p = dict(_PROTOKOLL, weitere_befunde=12, weitere_fragen=3)
    protokoll, _, _ = pruefe_fachlich({}, _LLM(json.dumps(p)), skills_dir=skills_dir)
    assert protokoll["weitere_befunde"] == 12
    assert protokoll["weitere_fragen"] == 3


def test_kuerzung_eines_kapitels_ist_auf_der_seite_sichtbar(app, monkeypatch):
    """Kapitelweise entfaellt die Gesamt-Obergrenze. Reisst ein EINZELNES Kapitel
    sein Budget, muss das trotzdem sichtbar sein."""
    c, sid = _angemeldet(app)
    _mit_inhalt(sid)
    p = dict(_PROTOKOLL, weitere_befunde=12)
    app.interview_service.llm = _LLM(json.dumps(p))
    monkeypatch.setattr("app.domains.qualitaet.auftraggeber.load_skills",
                        lambda *a, **kw: _bundle())
    _lauf_durch(c, sid)
    seite = c.get(f"/interview/{sid}/fachpruefung").get_data(as_text=True)
    assert "Prüfung ist gekürzt" in seite
    # Die Zahl ist die SUMME ueber die Kapitel - nicht die eines einzelnen.
    import re as _re
    assert _re.search(r"\d+ weitere Befunde", seite)


def test_ohne_kuerzung_kein_warnhinweis(app, monkeypatch):
    c, sid = _angemeldet(app)
    app.interview_service.llm = _LLM()          # weitere_befunde fehlt -> 0
    monkeypatch.setattr("app.domains.qualitaet.auftraggeber.load_skills",
                        lambda *a, **kw: _bundle())
    _lauf_durch(c, sid)
    seite = c.get(f"/interview/{sid}/fachpruefung").get_data(as_text=True)
    assert "gekürzt" not in seite


def test_das_modell_wird_zur_meldung_der_kuerzung_angehalten(skills_dir):
    llm = _LLM()
    pruefe_fachlich({}, llm, skills_dir=skills_dir)
    assert "weitere_befunde" in llm.user
    assert "NIE wie eine vollständige aussehen" in llm.user
    assert "höchstens" in llm.user          # die Grenze steht wirklich drin


# ---- Kapitelweiser Lauf -------------------------------------------------- #
#
# Ein einziger grosser Aufruf riss das Worker-Zeitlimit und erzwang eine
# kuenstliche Obergrenze. Kapitelweise ist jeder Schritt kurz - und die Laenge
# des Protokolls folgt wieder dem BEFUND.

def test_jeder_schritt_bleibt_weit_unter_dem_worker_limit():
    from pathlib import Path
    import re as _re

    from app.config import BASE_DIR
    from app.domains.qualitaet.auftraggeber import KAPITEL_ZEITLIMIT

    from app.domains.llm.client import VERBINDUNGSLIMIT

    ctl = Path(BASE_DIR, "deploy", "hermes_ctl.sh").read_text(encoding="utf-8")
    worker = int(_re.search(r"--timeout (\d+)", ctl).group(1))
    # Die Regel sagt, was sie meint: Verbinden + Lesen + Vor-/Nacharbeit muss
    # der Worker aushalten. Ein «mal zwei» hätte das Zeitlimit unnötig
    # eingeschnürt, sobald das Budget mitwächst.
    assert VERBINDUNGSLIMIT + KAPITEL_ZEITLIMIT + 15 <= worker


def test_lauf_geht_schrittweise_und_meldet_fortschritt(app, monkeypatch):
    from app.domains.qualitaet.auftraggeber import schritte
    c, sid = _angemeldet(app)
    _mit_inhalt(sid)
    app.interview_service.llm = _LLM()
    monkeypatch.setattr("app.domains.qualitaet.auftraggeber.load_skills",
                        lambda *a, **kw: _bundle())

    c.post(f"/interview/{sid}/fachpruefung")
    pid = _lauf_id(sid)
    gesamt = len(schritte())

    erster = c.post(f"/interview/{sid}/fachpruefung/schritt",
                    data={"pruefung_id": pid}).get_json()
    assert erster["schritt"] == 1 and erster["gesamt"] == gesamt
    assert erster["fertig"] is False
    assert erster["naechstes"]                 # der Name des naechsten Schritts

    for _ in range(gesamt):
        z = c.post(f"/interview/{sid}/fachpruefung/schritt",
                   data={"pruefung_id": pid}).get_json()
        if z["fertig"]:
            break
    assert z["fertig"] is True


def test_leere_kapitel_werden_uebersprungen_ohne_aufruf(app, monkeypatch):
    """Bearbeitungsstand statt leeres Dokument – und spart einen LLM-Aufruf."""
    from app.domains.qualitaet.auftraggeber import pruefe_kapitel

    class _Zaehlt:
        aufrufe = 0
        def complete(self, *a, **kw):
            _Zaehlt.aufrufe += 1
            return json.dumps({"befunde": [], "gut": []})

    monkeypatch.setattr("app.domains.qualitaet.auftraggeber.load_skills",
                        lambda *a, **kw: _bundle())
    teil, _, grund = pruefe_kapitel({}, _Zaehlt(), 0)
    assert teil["uebersprungen"] is True
    assert _Zaehlt.aufrufe == 0
    assert grund == ""


def test_ein_gescheiterter_schritt_verliert_die_bisherigen_nicht(app, monkeypatch):
    """Der Lauf ist fortsetzbar – sonst faengt man nach jedem Aussetzer von vorn an."""
    c, sid = _angemeldet(app)
    _mit_inhalt(sid)
    monkeypatch.setattr("app.domains.qualitaet.auftraggeber.load_skills",
                        lambda *a, **kw: _bundle())
    app.interview_service.llm = _LLM()
    c.post(f"/interview/{sid}/fachpruefung")
    pid = _lauf_id(sid)
    c.post(f"/interview/{sid}/fachpruefung/schritt", data={"pruefung_id": pid})

    app.interview_service.llm = _LLM("kaputt")          # zweiter Schritt scheitert
    r = c.post(f"/interview/{sid}/fachpruefung/schritt", data={"pruefung_id": pid})
    assert r.status_code == 502

    from app.domains.qualitaet.service import letzte_fachpruefung
    zeile = letzte_fachpruefung(sid)
    assert zeile.schritt == 1                          # der erste bleibt erledigt
    assert json.loads(zeile.teilbefunde_json)          # sein Ergebnis auch


# ---- Der Nachweis darf die Kapitelschritte nicht belasten ---------------- #
#
# Gemessener Befund auf dev: «laeuft seit 120 s / Verbindung unterbrochen» -
# exakt das Worker-Limit. Ursache war NICHT das Modell, sondern build_nachweis:
# ein eigener LLM-Aufruf (4096 Token, 90 s), den die Route VOR JEDEM der neun
# Schritte machte. Zusammen mit dem Kapitelaufruf sprengte das die 120 s - und
# war achtmal umsonst.

def test_nachweis_wird_nur_im_syntheseschritt_geholt(app, monkeypatch):
    from app.domains.qualitaet.auftraggeber import GRUPPEN
    c, sid = _angemeldet(app)
    _mit_inhalt(sid)
    app.interview_service.llm = _LLM()
    monkeypatch.setattr("app.domains.qualitaet.auftraggeber.load_skills",
                        lambda *a, **kw: _bundle())

    aufrufe = {"n": 0}
    echt = app.interview_service.build_nachweis

    def _gezaehlt(*a, **kw):
        aufrufe["n"] += 1
        return echt(*a, **kw)

    monkeypatch.setattr(app.interview_service, "build_nachweis", _gezaehlt)

    c.post(f"/interview/{sid}/fachpruefung")
    pid = _lauf_id(sid)
    # Alle Kapitelschritte: KEIN Nachweis-Aufruf.
    for _ in range(len(GRUPPEN)):
        c.post(f"/interview/{sid}/fachpruefung/schritt", data={"pruefung_id": pid})
    assert aufrufe["n"] == 0, "Der Nachweis darf die Kapitelschritte nicht belasten"

    # Auch die Konsolidierung braucht ihn nicht.
    c.post(f"/interview/{sid}/fachpruefung/schritt", data={"pruefung_id": pid})
    assert aufrufe["n"] == 0

    # Erst der Nachweisschritt holt ihn - genau einmal.
    c.post(f"/interview/{sid}/fachpruefung/schritt", data={"pruefung_id": pid})
    assert aufrufe["n"] == 1


def test_ein_schritt_macht_hoechstens_einen_llm_aufruf(app, monkeypatch):
    """Sonst summieren sich die Zeitlimits und das Worker-Limit faellt."""
    c, sid = _angemeldet(app)
    _mit_inhalt(sid)
    monkeypatch.setattr("app.domains.qualitaet.auftraggeber.load_skills",
                        lambda *a, **kw: _bundle())

    class _Zaehlt(_LLM):
        n = 0
        def complete(self, *a, **kw):
            _Zaehlt.n += 1
            return json.dumps(_PROTOKOLL)

    app.interview_service.llm = _Zaehlt()
    c.post(f"/interview/{sid}/fachpruefung")
    pid = _lauf_id(sid)
    _Zaehlt.n = 0
    c.post(f"/interview/{sid}/fachpruefung/schritt", data={"pruefung_id": pid})
    assert _Zaehlt.n == 1


def test_zeitlimit_ist_ein_gesamtlimit_kein_doppeltes(monkeypatch):
    """In requests gilt ein SKALARES Zeitlimit getrennt fuer Verbindung UND Lesen.
    60 werden so zu 120 - genau dort schiesst gunicorn den Worker ab. Deshalb
    muss ein PAAR uebergeben werden, dessen Summe unter dem Worker-Limit bleibt."""
    from pathlib import Path
    import re as _re

    from app.config import BASE_DIR
    from app.domains.llm.client import LLMClient
    from app.domains.qualitaet.auftraggeber import KAPITEL_ZEITLIMIT

    gesehen = {}

    def _merkt(url, headers=None, json=None, timeout=None):
        gesehen["t"] = timeout

        class _R:
            status_code = 200
            headers = {}
            text = ""

            def json(self):
                return {"content": [{"text": "ok"}]}
        return _R()

    monkeypatch.setattr("app.domains.llm.client.requests.post", _merkt)
    LLMClient(basis_url="http://x/anthropic").complete("s", [], timeout=KAPITEL_ZEITLIMIT)

    assert isinstance(gesehen["t"], tuple), "Zeitlimit muss (Verbindung, Lesen) sein"
    ctl = Path(BASE_DIR, "deploy", "hermes_ctl.sh").read_text(encoding="utf-8")
    worker = int(_re.search(r"--timeout (\d+)", ctl).group(1))
    assert sum(gesehen["t"]) < worker, (
        f"Summe der Zeitlimits {sum(gesehen['t'])}s erreicht das Worker-Limit "
        f"{worker}s – der Prozess stirbt, bevor eine Meldung erscheint.")


# ---- Kein multipart: der Hosting-Proxy laesst ihn nicht durch ------------- #
#
# Gemessener Befund: der Worker hing 120 s in request.form -> _load_form_data,
# also beim LESEN des Rumpfes. Ursache war `new FormData()` im Browser
# (multipart). Derselbe Proxy hatte schon das Diktat blockiert, bis es auf JSON
# umgestellt wurde.

def test_browser_sendet_kein_multipart():
    from pathlib import Path

    from app.config import BASE_DIR
    vorlage = Path(BASE_DIR, "app", "templates", "fachpruefung.html").read_text(
        encoding="utf-8")
    assert "new FormData()" not in vorlage, (
        "FormData erzeugt einen multipart-Rumpf – den laesst der Hosting-Proxy "
        "nicht durch, der Server haengt dann beim Lesen bis zum Worker-Timeout.")
    assert "URLSearchParams" in vorlage


@pytest.mark.parametrize("wie", ["formular", "json"])
def test_schritt_nimmt_formular_und_json(app, monkeypatch, wie):
    """Beide proxytauglichen Transportwege muessen funktionieren."""
    c, sid = _angemeldet(app)
    _mit_inhalt(sid)
    app.interview_service.llm = _LLM()
    monkeypatch.setattr("app.domains.qualitaet.auftraggeber.load_skills",
                        lambda *a, **kw: _bundle())
    c.post(f"/interview/{sid}/fachpruefung")
    pid = _lauf_id(sid)

    if wie == "formular":
        r = c.post(f"/interview/{sid}/fachpruefung/schritt",
                   data={"pruefung_id": pid},
                   content_type="application/x-www-form-urlencoded")
    else:
        r = c.post(f"/interview/{sid}/fachpruefung/schritt",
                   json={"pruefung_id": pid})
    assert r.status_code == 200
    assert r.get_json()["schritt"] == 1






def test_gescheiterter_schritt_kann_wiederholt_werden():
    """Der Lauf ist fortsetzbar – das muss die Oberflaeche auch anbieten,
    statt den Nutzer zum Neuladen zu zwingen."""
    from pathlib import Path

    from app.config import BASE_DIR
    vorlage = Path(BASE_DIR, "app", "templates", "fachpruefung.html").read_text(
        encoding="utf-8")
    assert "lauf-wiederholen" in vorlage
    assert "bereits geprüften Kapitel bleiben erhalten" in vorlage


# ---- Die EINE Regel, die den Lauf traegt --------------------------------- #

def test_je_schritt_hoechstens_ein_modellaufruf(app, monkeypatch):
    """Gemessen: der Syntheseschritt machte ZWEI Aufrufe (Nachweis +
    Gesamtwuerdigung) und riss nach 121 s das Worker-Zeitlimit. Seither hat der
    Nachweis einen eigenen Schritt. Diese Regel darf nie wieder brechen."""
    from app.domains.qualitaet import service as svc
    from app.domains.qualitaet.auftraggeber import GRUPPEN, schritte

    assert schritte()[len(GRUPPEN) + 1] == "Herkunft der Angaben"
    assert schritte()[-1] == "Gesamtwürdigung"

    quelle = Path(svc.__file__).read_text(encoding="utf-8")
    # Im Syntheseschritt darf der Nachweis nur noch GELESEN werden.
    nach_nachweisschritt = quelle.split("# Letzter Schritt")[1]
    assert "nachweis_fn(" not in nach_nachweisschritt


def test_zeitlimit_und_worker_limit_passen_zusammen():
    """Das Lese-Zeitlimit muss samt Verbindungsaufbau in das Worker-Limit
    passen – sonst stirbt der Prozess, und dann greift keine Fehlerseite."""
    import re as _re

    from app.config import BASE_DIR
    from app.domains.llm.client import VERBINDUNGSLIMIT
    from app.domains.qualitaet.auftraggeber import KAPITEL_ZEITLIMIT

    ctl = Path(BASE_DIR, "deploy", "hermes_ctl.sh").read_text(encoding="utf-8")
    worker = int(_re.search(r"--timeout (\d+)", ctl).group(1))
    assert VERBINDUNGSLIMIT + KAPITEL_ZEITLIMIT + 15 <= worker



    nginx = Path(BASE_DIR, "deploy", "nginx-hermespia.conf").read_text(encoding="utf-8")
    for wert in _re.findall(r"proxy_read_timeout (\d+)s", nginx):
        assert int(wert) >= worker - 60


def test_budget_ist_grosszuegig_und_eine_einzige_zahl():
    """Drei Anlaeufe an dieser Stelle waren drei zu viel. `max_tokens` ist eine
    Obergrenze, keine Reservation – ein grosszuegiger Wert kostet nichts."""
    from app.domains.qualitaet import auftraggeber as ag

    assert ag.SCHRITT_TOKENS >= 16000
    assert ag.KAPITEL_TOKENS == ag.SYNTHESE_TOKENS == ag.SCHRITT_TOKENS
    quelle = Path(ag.__file__).read_text(encoding="utf-8")
    assert "def kapitel_budget" not in quelle    # keine Rechnerei mehr


def _laufender_lauf(app, monkeypatch=None):
    """Ein gestarteter Prueflauf – (client, session_id, pruefung_id)."""
    c, sid = _angemeldet(app)
    _mit_inhalt(sid)
    app.interview_service.llm = _LLM()
    c.post(f"/interview/{sid}/fachpruefung")
    return c, sid, _lauf_id(sid)


def test_schrittfehler_kommt_als_json_nicht_als_html(app, monkeypatch):
    """Ein Absturz im Prüfschritt muss als JSON zurückkommen. Kam eine
    HTML-Fehlerseite, scheiterte der Browser am Parsen und meldete
    «Verbindung unterbrochen» – der echte Grund war weg, und die Suche lief
    stundenlang in die falsche Richtung."""
    from app.web import ui_routes

    def _kracht(*a, **kw):
        raise RuntimeError("etwas ging schief")

    monkeypatch.setattr(ui_routes, "fachpruefung_schritt", _kracht)
    client, sid, pid = _laufender_lauf(app)
    r = client.post(f"/interview/{sid}/fachpruefung/schritt",
                    data={"pruefung_id": pid})
    assert r.status_code == 500
    assert r.is_json, "Fehler MUSS JSON sein, nie HTML"
    assert "RuntimeError" in r.get_json()["fehler"]
    assert "etwas ging schief" in r.get_json()["fehler"]


def test_oberflaeche_unterscheidet_serverfehler_von_verbindungsabbruch():
    from app.config import BASE_DIR

    v = Path(BASE_DIR, "app", "templates", "fachpruefung.html").read_text(
        encoding="utf-8")
    # Erst Text lesen, dann parsen – nie direkt r.json() auf die Antwort.
    assert "r.text()" in v
    assert "return r.json()" not in v and ".then(r => r.json())" not in v
    assert "'Accept': 'application/json'" in v
    assert "Der Server meldete einen Fehler (Code " in v


def test_nachweis_blockiert_den_lauf_nie(app, monkeypatch):
    """Der Nachweis ist zusätzliche Evidenz, keine Voraussetzung. Scheitert er,
    läuft die Gesamtwürdigung ohne ihn weiter – der Lauf darf daran nie
    haengenbleiben."""
    from app.domains.qualitaet.auftraggeber import GRUPPEN
    from app.domains.qualitaet.models import PiaPruefung
    from app.shared.database import SessionLocal

    monkeypatch.setattr("app.domains.qualitaet.auftraggeber.load_skills",
                        lambda *a, **kw: _bundle())
    c, sid, pid = _laufender_lauf(app)
    monkeypatch.setattr(
        app.interview_service, "build_nachweis",
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("Nachweis kaputt")))

    db = SessionLocal()
    zeile = db.get(PiaPruefung, pid)
    zeile.schritt = len(GRUPPEN)          # direkt auf den Nachweisschritt
    db.commit()

    z = c.post(f"/interview/{sid}/fachpruefung/schritt",
               data={"pruefung_id": pid})
    assert z.status_code == 200, z.get_data(as_text=True)[:300]
    assert z.get_json()["schritt"] == len(GRUPPEN) + 1


def test_nachweis_der_pruefung_braucht_kein_modell(app, monkeypatch):
    """Der neunte Modellaufruf war die Ursache des Abbruchs nach 30 s – und er
    war überflüssig: als EVIDENZ zählt die deterministisch abgeleitete
    Herkunft, nicht die ausformulierte Prosa."""
    gerufen = []
    monkeypatch.setattr("app.domains.interview.service.nachweis_begruendungen",
                        lambda *a, **kw: gerufen.append(1) or {})
    svc = app.interview_service
    svc.llm = _LLM()
    c, sid = _angemeldet(app)
    _mit_inhalt(sid)
    from app.domains.interview.models import InterviewSession
    from app.shared.database import SessionLocal
    session = SessionLocal().get(InterviewSession, sid)
    answers = json.loads(session.answers_json or "{}")

    eintraege = svc.build_nachweis(session, answers, mit_llm=False)
    assert gerufen == [], "kein Modellaufruf im Prüf-Nachweis"
    assert eintraege and all(e["herkunft"] and e["begruendung"] for e in eintraege)

    # Fürs DOKUMENT bleibt die ausformulierte Fassung erhalten.
    svc.build_nachweis(session, answers)
    assert gerufen == [1]


# ---- Prio 1a: der Eingang wird NIE gekuerzt ------------------------------- #

def test_der_pruefeingang_wird_nie_gekuerzt(skills_dir):
    """Ein beschnittener Eingang macht die Prüfung inhaltlich falsch: das Modell
    hält den Ausschnitt für das Ganze und meldet als «fehlend», was nur nicht
    übergeben wurde. Auch «kürzen und markieren» ist keine Lösung – dann urteilt
    der Prüfer über etwas anderes als das, was vorliegt."""
    from app.domains.qualitaet.auftraggeber import _pia_kompakt, pruefe_kapitel

    langer_text = ("Ein sehr ausführlicher Satz. " * 500).strip()   # ~14 000 Zeichen
    viele_zeilen = [{"rolle": f"R{i}", "pt": str(i)} for i in range(120)]
    answers = {"ausgangslage": {"extracted": {"text": langer_text}},
               "personalaufwand": {"extracted": viele_zeilen}}

    kompakt = _pia_kompakt(answers)
    assert kompakt["ausgangslage"] == langer_text, "Text darf nicht beschnitten werden"
    assert len(kompakt["personalaufwand"]) == 120, "keine Zeile darf wegfallen"

    gesehen = {}

    class _Merkt:
        def complete(self, system, messages, max_tokens=1024, timeout=None, **kw):
            gesehen["user"] = messages[0]["content"]
            return json.dumps({"befunde": [], "gut": []})

    pruefe_kapitel(answers, _Merkt(), 0, skills_dir=skills_dir)
    assert langer_text in gesehen["user"], "der Kapitelinhalt geht vollständig mit"
    assert "VOLLSTÄNDIG übergeben" in gesehen["user"]


def test_kein_abschneiden_im_modul():
    """Wächter gegen die Rückkehr der Beschneidung."""
    from pathlib import Path

    from app.domains.qualitaet import auftraggeber as ag
    quelle = Path(ag.__file__).read_text(encoding="utf-8")
    import re as _re
    treffer = _re.findall(r"ensure_ascii=False\)\[:\d+\]", quelle)
    assert not treffer, f"Eingang wird wieder beschnitten: {treffer}"


# ---- Prio 1b: Konsolidierung --------------------------------------------- #

def test_konsolidierung_ist_ein_eigener_schritt():
    from app.domains.qualitaet.auftraggeber import GRUPPEN, schritte

    s = schritte()
    assert s[len(GRUPPEN)] == "Konsolidierung"
    assert s.index("Konsolidierung") < s.index("Gesamtwürdigung")


def test_konsolidierung_zeigt_auf_nummern_statt_alles_neu_zu_schreiben(skills_dir):
    """Gemessen: alle Befunde neu ausschreiben zu lassen sprengte das Zeitlimit –
    und das Modell haette dabei nur abgeschrieben, was schon dasteht. Es zeigt
    jetzt auf Nummern; das Zusammenfuehren macht der Code."""
    from app.domains.qualitaet.auftraggeber import konsolidiere

    teile = [
        {"kapitel": "Ziele", "befunde": [
            {"kapitel": "Ziele", "feststellung": "Ziel 2 ohne Messgroesse",
             "gewicht": "Muss"}], "gut": []},
        {"kapitel": "Risiken", "befunde": [], "gut": [], "uebersprungen": True},
    ]
    gesehen = {}

    class _Merkt:
        def complete(self, system, messages, max_tokens=1024, timeout=None, **kw):
            gesehen["user"] = messages[0]["content"]
            return json.dumps({"zusammenfassungen": [],
                               "aufgeloeste_widersprueche": [],
                               "geprueft": ["Ziele"], "nicht_geprueft": ["Risiken"]})

    ergebnis, versionen, grund = konsolidiere(teile, _Merkt(), skills_dir=skills_dir)
    assert ergebnis and versionen and not grund
    assert ergebnis["nicht_geprueft"] == ["Risiken"]
    assert len(ergebnis["befunde"]) == 1        # unveraendert uebernommen
    assert '"nr": 0' in gesehen["user"]         # nummeriert uebergeben
    assert "melde NUR, was sich" in gesehen["user"]
    assert "urteilst NICHT neu" in gesehen["user"]


def test_ein_leeres_ergebnis_ist_gueltig(skills_dir):
    """Bei einem sauberen PIA gibt es nichts zusammenzufuehren – das darf den
    Lauf nicht aufhalten."""
    from app.domains.qualitaet.auftraggeber import konsolidiere

    teile = [{"kapitel": "Ziele", "befunde": [
        {"kapitel": "Ziele", "feststellung": "A", "gewicht": "Hinweis"}], "gut": ["gut"]}]

    class _Leer:
        def complete(self, *a, **kw):
            return "{}"

    ergebnis, _, grund = konsolidiere(teile, _Leer(), skills_dir=skills_dir)
    assert not grund and len(ergebnis["befunde"]) == 1
    assert ergebnis["gut"] == ["gut"]


def test_kein_befund_kann_bei_der_zusammenfuehrung_verschwinden():
    """Strukturell garantiert: was das Modell nicht erwaehnt, bleibt stehen.
    Frueher musste ein Sicherheitsnetz das nachtraeglich reparieren."""
    from app.domains.qualitaet.auftraggeber import _wende_zusammenfuehrung_an

    befunde = [
        {"kapitel": "Ziele", "feststellung": "A fehlt", "gewicht": "Muss"},
        {"kapitel": "Termine", "feststellung": "B fehlt", "gewicht": "Vorbehalt"},
        {"kapitel": "Risiken", "feststellung": "C fehlt", "gewicht": "Muss"},
    ]
    # Das Modell erfindet Unsinn: leere Antwort, Unsinnsnummern, Selbstgruppe.
    for delta in ({}, {"zusammenfassungen": [{"nummern": [99]}]},
                  {"zusammenfassungen": [{"nummern": [1]}]},
                  {"zusammenfassungen": [{"nummern": ["x", None]}]}):
        assert len(_wende_zusammenfuehrung_an(befunde, delta)) == 3


def test_zusammenfassen_nimmt_das_schwerste_gewicht():
    """Zwei Kapitel melden dieselbe Sache verschieden schwer – zusammenfassen
    darf nie entschaerfen."""
    from app.domains.qualitaet.auftraggeber import _wende_zusammenfuehrung_an

    befunde = [
        {"kapitel": "Ziele", "feststellung": "Nutzen unbelegt", "gewicht": "Hinweis"},
        {"kapitel": "Ausgangslage", "feststellung": "Nutzen nicht belegt",
         "gewicht": "Muss"},
    ]
    raus = _wende_zusammenfuehrung_an(befunde, {"zusammenfassungen": [
        {"nummern": [0, 1], "feststellung": "Der Nutzen ist nirgends belegt"}]})
    assert len(raus) == 1
    assert raus[0]["gewicht"] == "Muss"
    # Die Herkunft steht im KAPITEL – kein zusätzliches Meta-Feld für den Leser.
    assert raus[0]["kapitel"] == "Ziele / Ausgangslage"
    assert "zusammengefasst_aus" not in raus[0]
    assert raus[0]["feststellung"] == "Der Nutzen ist nirgends belegt"


def test_widerlegter_befund_wird_zurueckgestuft_nicht_geloescht():
    """Wer widerlegt wurde, soll das nachlesen koennen."""
    from app.domains.qualitaet.auftraggeber import _wende_zusammenfuehrung_an

    befunde = [
        {"kapitel": "Termine", "feststellung": "Start fehlt", "gewicht": "Muss",
         "kriterium": "Vollstaendigkeit"},
        {"kapitel": "Ergebnisse", "feststellung": "Start ist genannt",
         "gewicht": "Hinweis"},
    ]
    raus = _wende_zusammenfuehrung_an(befunde, {"aufgeloeste_widersprueche": [
        {"nummern": [0, 1], "worum": "Startdatum", "aufloesung": "Es steht da",
         "gilt": 1}]})
    assert len(raus) == 2, "nichts wird geloescht"
    assert raus[0]["gewicht"] == "Hinweis"
    assert "widerlegt" in raus[0]["kriterium"]


# ---- Kleinigkeiten -------------------------------------------------------- #

def test_auflagen_wiederholen_keine_muss_befunde():
    from app.domains.qualitaet.auftraggeber import baue_protokoll

    gesamt = {"empfehlung": "mit vorbehalt", "auflagen": [
        {"offen": "Vorfestlegung auf die Lösung offenlegen", "wer": "PL"},
        {"offen": "Termin mit dem Amt vereinbaren", "wer": "AG"}]}
    konsolidiert = {"befunde": [
        {"kapitel": "Ausgangslage", "gewicht": "Muss",
         "feststellung": "Die Vorfestlegung auf die Lösung ist nicht offengelegt"}]}
    p = baue_protokoll([], gesamt, konsolidiert=konsolidiert)
    offen = [a["offen"] for a in p["auflagen"]]
    assert "Termin mit dem Amt vereinbaren" in offen
    assert not any("Vorfestlegung" in o for o in offen), "Dublette zum Muss-Befund"


def test_auflagen_ueberschrift_folgt_der_empfehlung():
    from pathlib import Path

    from app.config import BASE_DIR
    v = Path(BASE_DIR, "app", "templates", "fachpruefung.html").read_text(
        encoding="utf-8")
    assert "Zu behebende Punkte" in v
    assert "Auflagen bei Vorbehalt" in v


def test_nutzertexte_ohne_implementierungsbegriffe():
    """«JSON», «Token» und Konsorten gehören ins Protokoll, nicht auf den
    Bildschirm des Projektleiters."""
    from app.domains.qualitaet.auftraggeber import _json_aus

    for roh in ("", "kein Objekt", '{"a": ', '{"a": 1,,}'):
        _, grund = _json_aus(roh)
        for wort in ("JSON", "Token", "Schema", "parse"):
            assert wort.lower() not in grund.lower(), f"{wort!r} in «{grund}»"


def test_befunde_werden_priorisiert_dargestellt():
    """Muss vollständig und zuerst, Vorbehalte gruppiert, Hinweise einklappbar –
    dann trifft eine Kürzung der Darstellung nie einen Muss-Befund."""
    from pathlib import Path

    from app.config import BASE_DIR
    v = Path(BASE_DIR, "app", "templates", "fachpruefung.html").read_text(
        encoding="utf-8")
    assert "equalto', 'Muss'" in v.replace('"', "'")
    assert "<details" in v and "Hinweise" in v
    assert v.index("Muss (") < v.index("Vorbehalte (") < v.index("Hinweise (")


# ---- Die Konsolidierung ist ein Denkschritt, kein Autor ------------------- #

def test_konsolidierung_schreibt_keinen_text_fuer_den_leser():
    """Beobachtet: Vorschläge wie «Befund 17 und 30 zu einem einzigen Befund
    zusammenführen» landeten in der Ausgabe. Das sind Redaktionsanweisungen an
    das System, keine Empfehlungen an die Projektleitung – und sie verweisen auf
    Nummern, die der Leser nirgends sieht."""
    from app.domains.qualitaet.auftraggeber import (
        _KONSOLIDIERUNG_SCHEMA, _wende_zusammenfuehrung_an,
    )

    # Der Schritt kann gar keinen Vorschlag mehr liefern.
    assert "vorschlag" not in _KONSOLIDIERUNG_SCHEMA

    befunde = [
        {"kapitel": "Ausgangslage", "gewicht": "Muss",
         "feststellung": "Der Nutzen ist nicht belegt.",
         "vorschlag": "Nutzen mit Zahlen belegen."},
        {"kapitel": "Rahmenbedingungen", "gewicht": "Vorbehalt",
         "feststellung": "Der Nutzen bleibt vage.", "vorschlag": "Konkretisieren."},
    ]
    raus = _wende_zusammenfuehrung_an(befunde, {"zusammenfassungen": [
        {"nummern": [0, 1],
         "feststellung": "Der Nutzen ist weder in der Ausgangslage noch in den "
                         "Rahmenbedingungen belegt."}]})
    assert len(raus) == 1
    # Der Vorschlag stammt aus dem Befund, nie aus der Zusammenführung.
    assert raus[0]["vorschlag"] == "Nutzen mit Zahlen belegen."
    assert raus[0]["kapitel"] == "Ausgangslage / Rahmenbedingungen"


@pytest.mark.parametrize("leck", [
    "Die drei Befunde als zusammenhängenden Komplex kennzeichnen.",
    "Befund 17 und Befund 30 zu einem einzigen Befund zusammenführen",
    "Befund 5 (Muss) bleibt als schwerster Befund leitend",
    "Gewicht: Vorbehalt beibehalten",
])
def test_redaktionsanweisungen_erreichen_den_leser_nie(leck):
    """Deterministisch abgefangen – nicht nur im Prompt verboten."""
    from app.domains.qualitaet.auftraggeber import _wende_zusammenfuehrung_an

    befunde = [
        {"kapitel": "Ziele", "gewicht": "Muss", "feststellung": "Ziel 2 ist unklar.",
         "vorschlag": "Ziel schärfen."},
        {"kapitel": "Termine", "gewicht": "Hinweis", "feststellung": "Termin offen.",
         "vorschlag": "Termin setzen."},
    ]
    raus = _wende_zusammenfuehrung_an(befunde, {"zusammenfassungen": [
        {"nummern": [0, 1], "feststellung": leck}]})
    assert raus[0]["feststellung"] == "Ziel 2 ist unklar."   # Originaltext bleibt


def test_die_ueberlegung_der_konsolidierung_wird_nicht_angezeigt():
    v = Path(BASE_DIR_T, "app", "templates", "fachpruefung.html").read_text(
        encoding="utf-8")
    assert "aufgeloeste_widersprueche" not in v
    assert "zusammengefasst aus" not in v


# ---- «Was gut ist» gehört in die Konsistenzprüfung ------------------------ #

def test_lob_wird_gegen_die_befunde_abgeglichen(skills_dir):
    """Beobachtet, zweimal an derselben Naht: «Was gut ist» lobte einen
    Stopp-Mechanismus, den ein Muss-Befund gleichzeitig als fehlend meldete.
    Beides halb richtig – genau das muss dastehen."""
    from app.domains.qualitaet.auftraggeber import konsolidiere

    teile = [{"kapitel": "Rahmenbedingungen",
              "befunde": [{"kapitel": "Rahmenbedingungen", "gewicht": "Muss",
                           "feststellung": "Kein Stopp-Mechanismus operationalisiert."}],
              "gut": ["RB 3 enthält einen expliziten Stopp-Mechanismus."]}]
    genauer = ("Der Stopp-Vorbehalt ist in den Rahmenbedingungen angelegt, aber "
               "weder terminlich noch als Massnahme ausgestaltet.")
    gesehen = {}

    class _Merkt:
        def complete(self, system, messages, max_tokens=1024, timeout=None, **kw):
            gesehen["user"] = messages[0]["content"]
            return json.dumps({"praezisierte_lobe": [{"nr": 0, "text": genauer}]})

    ergebnis, _, grund = konsolidiere(teile, _Merkt(), skills_dir=skills_dir)
    assert not grund
    assert ergebnis["gut"] == [genauer]
    assert "Was gut ist" in gesehen["user"]          # geht ueberhaupt mit
    assert "beide halb" in gesehen["user"].lower()


def test_ein_lob_kann_nur_genauer_werden_nie_verschwinden(skills_dir):
    from app.domains.qualitaet.auftraggeber import _praezisiere_lob

    gut = ["A ist gut.", "B ist gut."]
    for delta in ({}, {"praezisierte_lobe": [{"nr": 9, "text": "x"}]},
                  {"praezisierte_lobe": [{"nr": 0, "text": ""}]},
                  {"praezisierte_lobe": [{"nr": 0, "text": "Befund 3 zusammenführen"}]}):
        assert _praezisiere_lob(gut, delta) == gut


# ---- Zahlen zählt der Code ----------------------------------------------- #

def test_zahlen_kommen_aus_der_zaehlung_nicht_aus_der_erzaehlung():
    """Gemessen: die Empfehlung sprach von «vier Muss-Befunden», die Überschrift
    zählte sechs. Derselbe Fall wie die Freigabe-Rückstufung – was nachprüfbar
    ist, ermittelt der Code."""
    from app.domains.qualitaet.auftraggeber import baue_protokoll

    befunde = ([{"kapitel": "K", "gewicht": "Muss", "feststellung": f"M{i}"}
                for i in range(6)]
               + [{"kapitel": "K", "gewicht": "Vorbehalt", "feststellung": "V"}])
    gesamt = {"empfehlung": "nicht freigebbar",
              "begruendung": "Es bestehen vier Muss-Befunde auf Kapitelebene sowie "
                             "vier weitere Muss-Befunde auf Ebene Querbezüge.",
              "querbezuege": [{"gewicht": "Muss", "feststellung": "Q"}] * 7}
    p = baue_protokoll([], gesamt, konsolidiert={"befunde": befunde, "gut": []})

    assert p["zaehlung"]["muss"] == 6
    assert p["zaehlung"]["vorbehalt"] == 1
    assert p["zaehlung"]["querbezuege_muss"] == 7
    # Die falsche Zahl steht nicht mehr im Text.
    assert "vier" not in p["begruendung"]
    assert "Muss-Befunde" in p["begruendung"]


def test_die_seite_zeigt_die_gezaehlten_werte():
    v = Path(BASE_DIR_T, "app", "templates", "fachpruefung.html").read_text(
        encoding="utf-8")
    assert "protokoll.zaehlung.muss" in v


def test_synthese_wird_das_zaehlen_untersagt(skills_dir):
    from app.domains.qualitaet.auftraggeber import synthese

    gesehen = {}

    class _Merkt:
        def complete(self, system, messages, max_tokens=1024, timeout=None, **kw):
            gesehen["user"] = messages[0]["content"]
            return json.dumps({"empfehlung": "mit vorbehalt", "begruendung": "x"})

    synthese([], {}, _Merkt(), skills_dir=skills_dir,
             konsolidiert={"befunde": [], "geprueft": ["Ziele"],
                           "nicht_geprueft": ["Risiken"]})
    assert "NENNE KEINE ANZAHLEN" in gesehen["user"]
    assert "Prüfumfang" in gesehen["user"]
