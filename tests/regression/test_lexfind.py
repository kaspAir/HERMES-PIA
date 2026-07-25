"""Beweist: Live-Recherche über lexfind (Bund + Kantone) mit Offline-Index als Netz.

Alle Tests laufen OHNE Netz (injizierter Öffner). Die echten API-Eigenheiten sind
am 2026-07-25 gegen www.lexfind.ch gemessen und hier als Attrappe nachgebildet:
  * Browser-Kopfzeilen nötig, sonst HTTP 400,
  * `entity_filter` darf NICHT leer sein und nimmt GENAU EINE Sammlung,
  * die Treffer stehen in `texts_of_law_with_matches`, nicht in `results`.
"""
import json
import urllib.error

import pytest

from app.domains.rechtsquellen.lexfind import BUND, KANTON_ENTITY, LexfindClient, entity_ids
from app.domains.rechtsquellen.recherche import RechercheClient


# ---- Attrappe der echten API --------------------------------------------- #

class _Antwort:
    def __init__(self, nutzlast):
        self._n = json.dumps(nutzlast).encode("utf-8")

    def read(self):
        return self._n

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _treffer(sr, titel, entity="CH", url="https://example.ch/x", aktiv=True,
             stichworte=""):
    return {
        "systematic_number": sr, "is_active": aktiv,
        "dta_urls": [{"language": "de", "original_url": url}],
        "entity": {"abbreviation": entity, "name": entity},
        "matches": [{"title_hl": f'<span class="match">{titel}</span>',
                     "keywords_hl": stichworte}],
    }


class _FakeAPI:
    """Bildet die gemessenen Regeln der echten API nach."""
    def __init__(self, je_entity=None, kaputt=False):
        self.je_entity = je_entity or {}
        self.kaputt = kaputt
        self.anfragen = []

    def __call__(self, req, timeout=None):
        url = req.full_url
        if self.kaputt:
            raise urllib.error.URLError("kein Netz")
        if req.get_method() == "POST":
            koerper = json.loads(req.data.decode())
            self.anfragen.append(koerper)
            ents = koerper.get("entity_filter") or []
            # Gemessene Regeln der echten API:
            if len(ents) != 1:
                raise urllib.error.HTTPError(url, 400, "Ungültige Anfrage", {}, None)
            if "Mozilla" not in (req.get_header("User-agent") or ""):
                raise urllib.error.HTTPError(url, 400, "Ungültige Anfrage", {}, None)
            return _Antwort({"id": 1, "session_id": "s"})
        letzte = self.anfragen[-1]
        ent = letzte["entity_filter"][0]
        begriff = letzte["search_text"]
        return _Antwort({"results": [{"language": "de"}],
                         "texts_of_law_with_matches": self.je_entity.get((ent, begriff), [])})


# ---- Client -------------------------------------------------------------- #

def test_findet_bundesgesetz_mit_nummer_link_und_aktualitaet():
    """Der Fall aus der Praxis: StReG soll das Werkzeug SELBER finden."""
    api = _FakeAPI({(BUND, "StReG"): [
        _treffer("330", "Bundesgesetz über das Strafregister-Informationssystem VOSTRA",
                 url="https://www.fedlex.admin.ch/eli/cc/2022/600/de",
                 stichworte="Strafregistergesetz, StReG")]})
    c = LexfindClient(oeffner=api)
    hits = c.suche_mehrere(["StReG"], ebene="bund")["StReG"]
    assert hits[0]["sr"] == "330"
    assert hits[0]["aktiv"] is True
    assert hits[0]["url"].startswith("https://www.fedlex.admin.ch/")
    assert "<span" not in hits[0]["titel"]          # Hervorhebung entfernt


def test_kanton_wird_mitdurchsucht_und_getrennt_abgefragt():
    """Bund UND Kanton zusammen ergaeben 400 – es MUSS einzeln abgefragt werden."""
    api = _FakeAPI({
        (BUND, "Datenschutzgesetz"): [_treffer("235.1", "Bundesgesetz über den Datenschutz")],
        (KANTON_ENTITY["nidwalden"], "Datenschutzgesetz"): [
            _treffer("232.1", "Gesetz über den Datenschutz", entity="NW")],
    })
    c = LexfindClient(oeffner=api)
    hits = c.suche_mehrere(["Datenschutzgesetz"], treffer_je_begriff=2,
                           ebene="kanton", kanton="Nidwalden")["Datenschutzgesetz"]
    assert [h["entity"] for h in hits] == ["CH", "NW"]      # Bundesrecht zuerst
    assert {h["sr"] for h in hits} == {"235.1", "232.1"}
    # Jede Anfrage trug genau EINE Sammlung.
    assert all(len(a["entity_filter"]) == 1 for a in api.anfragen)


def test_bundesrecht_wird_auch_bei_kantonsebene_gesucht():
    """Bundesrecht gilt in jedem Kanton."""
    assert entity_ids("kanton", "Zug") == [BUND, KANTON_ENTITY["zug"]]
    assert entity_ids("bund", None) == [BUND]
    assert entity_ids("kanton", "Gibtsnicht") == [BUND]     # unbekannt -> kein Raten


def test_ausfall_liefert_leer_statt_zu_raten():
    c = LexfindClient(oeffner=_FakeAPI(kaputt=True))
    assert c.suche_mehrere(["StReG"], ebene="bund") == {}
    assert "URLError" in c.letzter_fehler


def test_treffer_ohne_nummer_werden_verworfen():
    """Ohne Systematik-Nummer ist es keine belegbare Fundstelle."""
    api = _FakeAPI({(BUND, "X"): [{"systematic_number": "", "matches": [{"title_hl": "Etwas"}]}]})
    assert LexfindClient(oeffner=api).suche_mehrere(["X"], ebene="bund") == {}


def test_zwischenspeicher_spart_wiederholte_abfragen():
    api = _FakeAPI({(BUND, "StReG"): [_treffer("330", "Strafregistergesetz")]})
    c = LexfindClient(oeffner=api)
    c.suche("StReG", entities=[BUND])
    c.suche("StReG", entities=[BUND])
    assert len(api.anfragen) == 1                    # freundlich zur fremden API


# ---- Zusammenspiel live + offline ---------------------------------------- #

class _Index:
    """Offline-SR-Index (kennt nur Bundesrecht, keine Aktualitaet)."""
    def __init__(self, daten=None):
        self.daten = daten or {}
        self.gefragt = []

    def suche_mehrere(self, begriffe, treffer_je_begriff=1, **_):
        self.gefragt.append(list(begriffe))
        return {b: self.daten[b] for b in begriffe if b in self.daten}


def test_lexfind_hat_vorrang_index_fuellt_die_luecken():
    api = _FakeAPI({(BUND, "StReG"): [
        _treffer("330", "Strafregistergesetz", stichworte="StReG")]})
    index = _Index({"AltesGesetz": [{"sr": "111", "titel": "Alt", "url": "u"}]})
    r = RechercheClient(lexfind=LexfindClient(oeffner=api), index=index)
    out = r.suche_mehrere(["StReG", "AltesGesetz"], ebene="bund")
    assert out["StReG"][0]["quelle"] == "lexfind"
    assert out["AltesGesetz"][0]["quelle"] == "index"
    assert index.gefragt == [["AltesGesetz"]]        # nur die Luecke nachgeschlagen


def test_ohne_netz_uebernimmt_der_offline_index():
    """Genau der Zustand auf dem Infomaniak-Host, falls lexfind dort blockiert ist."""
    index = _Index({"DSG": [{"sr": "235.1", "titel": "DSG", "url": "u"}]})
    r = RechercheClient(lexfind=LexfindClient(oeffner=_FakeAPI(kaputt=True)), index=index)
    out = r.suche_mehrere(["DSG"], ebene="bund")
    assert out["DSG"][0]["sr"] == "235.1"
    assert out["DSG"][0]["quelle"] == "index"
    assert out["DSG"][0]["aktiv"] is None            # Index kennt keine Aktualitaet
    assert r.letzte_quelle == "index"


def test_ganz_ohne_quellen_wird_nichts_erfunden():
    r = RechercheClient(lexfind=None, index=None)
    assert r.suche_mehrere(["StReG"]) == {}
    assert r.letzte_quelle == "keine"


# ---- Darstellung im Dokument --------------------------------------------- #

@pytest.mark.parametrize("entity,sr,erwartet", [
    ("CH", "330", "SR 330"),
    ("NW", "232.1", "NW 232.1"),      # 'SR' waere fuer Kantonsrecht schlicht falsch
])
def test_fundstelle_beschriftet_die_sammlung_korrekt(entity, sr, erwartet):
    from app.domains.ergebnisse.rechtsgrundlagen.service import RechtsgrundlagenService
    dienst = RechtsgrundlagenService.__new__(RechtsgrundlagenService)
    text = dienst._fundstelle("G", {"G": {"sr": sr, "url": "https://x", "entity": entity}}, "")
    assert text.startswith(erwartet)


# ---- Kein Netz ohne ausdrueckliche Konfiguration -------------------------- #

def test_service_telefoniert_von_sich_aus_nicht_nach_aussen():
    """Ein direkt gebauter Service macht NIE Netzaufrufe – sonst haetten Tests
    (und ueberraschte Deployments) stillen Internetverkehr."""
    from app.domains.ergebnisse.rechtsgrundlagen.service import RechtsgrundlagenService
    svc = RechtsgrundlagenService(None, None, None, llm=None, fedlex=_Index())
    assert svc.recherche.lexfind is None


def test_konfiguration_schaltet_die_live_recherche(tmp_path):
    """RECHERCHE_LIVE entscheidet – das Deployment, nicht der Code."""
    from app.config import Config
    from app.factory import create_app
    from app.shared.database import SessionLocal

    def _app(live):
        class _Cfg(Config):
            DATABASE_URL = "sqlite:///" + str(tmp_path / f"r{live}.db").replace("\\", "/")
            SECRET_KEY = "x"
            RECHERCHE_LIVE = live
        SessionLocal.remove()
        a = create_app(_Cfg)
        SessionLocal.remove()
        return a

    assert _app(False).rechtsgrundlagen_service.recherche.lexfind is None
    assert _app(True).rechtsgrundlagen_service.recherche.lexfind is not None


# ---- Trefferpruefung: der Befund aus dem echten Dokument ------------------ #
#
# Im erzeugten Dokument standen falsche Fundstellen MIT offiziellem Link:
#   «Kantonales Beschaffungsrecht»  -> SR 784.10 = Fernmeldegesetz
#   «Kantonale Datenschutzgesetzgebung» -> SR 128.1 (Bundesverordnung)
# Ursache: lexfind ist eine Volltextsuche und liefert IMMER etwas; der erste
# Treffer wurde ungeprueft uebernommen. Falsche Fundstellen sind schlimmer als
# gar keine.

from app.domains.rechtsquellen.lexfind import passt_zum_begriff


@pytest.mark.parametrize("begriff,titel,stichworte,erwartet", [
    # Die gemessenen Fehlgriffe -> muessen abgelehnt werden
    ("Beschaffungsrecht", "Fernmeldegesetz", "", False),
    ("Datenschutzgesetzgebung", "Verordnung über die Informationssicherheit", "", False),
    ("Archivgesetz", "Gesetz über den Datenschutz", "", False),
    # Richtige Treffer -> muessen durchgehen
    ("Datenschutzgesetzgebung", "Gesetz über den Datenschutz", "", True),
    ("Beschaffungsrecht", "Verordnung über das öffentliche Beschaffungswesen", "", True),
    ("Strafprozessordnung", "Schweizerische Strafprozessordnung", "", True),
    # Abkuerzung nur als ganzes Wort - und ueber die Stichworte
    ("StReG", "Bundesgesetz über das Strafregister-Informationssystem",
     "Strafregistergesetz, StReG", True),
    ("DSG", "Fernmeldegesetz", "", False),
])
def test_treffer_wird_gegen_den_begriff_geprueft(begriff, titel, stichworte, erwartet):
    assert passt_zum_begriff(begriff, titel, stichworte) is erwartet


def test_unpassende_treffer_erscheinen_nicht_im_ergebnis():
    """Ende zu Ende: der Fernmeldegesetz-Fehlgriff darf nicht durchkommen."""
    api = _FakeAPI({(BUND, "Beschaffungsrecht"): [
        _treffer("784.10", "Fernmeldegesetz"),
        _treffer("172.056.11", "Verordnung über das öffentliche Beschaffungswesen"),
    ]})
    hits = LexfindClient(oeffner=api).suche_mehrere(["Beschaffungsrecht"], ebene="bund")
    assert hits["Beschaffungsrecht"][0]["sr"] == "172.056.11"


def test_nur_falsche_treffer_ergeben_leer_statt_falsch():
    api = _FakeAPI({(BUND, "Beschaffungsrecht"): [_treffer("784.10", "Fernmeldegesetz")]})
    assert LexfindClient(oeffner=api).suche_mehrere(["Beschaffungsrecht"], ebene="bund") == {}


# ---- Ebenen-Schutz -------------------------------------------------------- #

def test_kantonaler_name_bekommt_keine_bundesfundstelle():
    """«Kantonale Datenschutzgesetzgebung» mit einer SR-Nummer zu belegen ist per
    Definition falsch - egal wie gut der Treffer aussieht."""
    from app.domains.ergebnisse.rechtsgrundlagen.grounding import ground_federal

    class _Quelle:
        def suche_mehrere(self, begriffe, treffer_je_begriff=1, **_):
            return {b: [{"sr": "235.1", "titel": "Bundesgesetz über den Datenschutz",
                         "url": "u", "entity": "CH"}] for b in begriffe}

    assert ground_federal(["Kantonale Datenschutzgesetzgebung"], "kanton", _Quelle()) == {}
    # Ohne den Zusatz «kantonal» ist derselbe Treffer korrekt.
    assert ground_federal(["Datenschutzgesetz"], "bund", _Quelle()) != {}


def test_generische_klammerbegriffe_werden_nicht_gesucht():
    """«Verordnung» als Suchbegriff wuerde auf JEDE Verordnung passen und die
    Trefferpruefung aushebeln."""
    from app.domains.ergebnisse.rechtsgrundlagen.grounding import suchbegriffe
    begriffe = suchbegriffe("Irgendein Erlass (Gesetz/Verordnung)")
    assert "Verordnung" not in begriffe and "Gesetz" not in begriffe
    # Aussagekraeftige Klammerinhalte bleiben erhalten.
    assert "Submissionsgesetz" in suchbegriffe("Beschaffung (Submissionsgesetz/-verordnung)")


# ---- Erlassform: Verordnung ist nicht das Gesetz -------------------------- #
#
# Gemessener Befund: «Verordnung über das Strafregister (StReV)» wurde mit SR 330
# belegt – das ist das GESETZ (StReG); die Verordnung ist SR 331. Ursache war die
# Auswahl «kürzeste Nummer gewinnt»: zu fast jedem Sachgebiet gibt es beides, und
# das Gesetz traegt immer die kuerzere Nummer.

class _BeideErlasse:
    """Liefert zu 'Strafregister' Gesetz UND Verordnung – wie die echte API."""
    def suche_mehrere(self, begriffe, treffer_je_begriff=1, **_):
        return {b: [
            {"sr": "330", "titel": "Bundesgesetz über das Strafregister-Informationssystem",
             "url": "u330", "entity": "CH"},
            {"sr": "331", "titel": "Verordnung über das Strafregister-Informationssystem",
             "url": "u331", "entity": "CH"},
        ] for b in begriffe}


def test_verordnung_bekommt_die_verordnung_nicht_das_gesetz():
    from app.domains.ergebnisse.rechtsgrundlagen.grounding import ground_federal
    g = ground_federal(["Bundesgesetz über das Strafregister (StReG)",
                        "Verordnung über das Strafregister (StReV)"], "bund", _BeideErlasse())
    assert g["Bundesgesetz über das Strafregister (StReG)"]["sr"] == "330"
    assert g["Verordnung über das Strafregister (StReV)"]["sr"] == "331"


def test_erlassform_wird_erkannt():
    from app.domains.ergebnisse.rechtsgrundlagen.grounding import erlassform
    assert erlassform("Verordnung über das Strafregister") == "verordnung"
    assert erlassform("Bundesgesetz über das Strafregister") == "gesetz"
    assert erlassform("Konkordat über den Vollzug") == "konkordat"   # eigene Form
    assert erlassform("Kantonale ICT-Strategie") == ""      # keine Praeferenz


# ---- Dubletten ------------------------------------------------------------ #

def test_derselbe_erlass_erscheint_nur_einmal():
    """PIA und LLM schreiben denselben Erlass unterschiedlich lang; der
    Namensvergleich erkennt das nicht, die Fundstelle schon."""
    from app.domains.ergebnisse.rechtsgrundlagen.service import RechtsgrundlagenService
    lang = ("Bundesgesetz über die Verwendung von DNA-Profilen im Strafverfahren "
            "und zur Identifizierung von unbekannten oder vermissten Personen (DNA-Profil-Gesetz)")
    kurz = "Bundesgesetz über die Verwendung von DNA-Profilen im Strafverfahren (DNA-Profil-Gesetz)"
    grounded = {lang: {"sr": "363", "entity": "CH"}, kurz: {"sr": "363", "entity": "CH"}}
    out = RechtsgrundlagenService._ohne_dubletten([lang, kurz, "StPO"], grounded)
    assert out == [lang, "StPO"]        # der zuerst genannte bleibt


def test_ungegroundete_namen_bleiben_alle_stehen():
    """Ohne Fundstelle laesst sich Gleichheit nicht belegen – dann nichts entfernen."""
    from app.domains.ergebnisse.rechtsgrundlagen.service import RechtsgrundlagenService
    out = RechtsgrundlagenService._ohne_dubletten(["A", "B"], {})
    assert out == ["A", "B"]


def test_verschiedene_erlasse_bleiben_getrennt():
    from app.domains.ergebnisse.rechtsgrundlagen.service import RechtsgrundlagenService
    grounded = {"G": {"sr": "330", "entity": "CH"}, "V": {"sr": "331", "entity": "CH"},
                "K": {"sr": "330", "entity": "NW"}}      # gleiche Nummer, andere Sammlung
    assert RechtsgrundlagenService._ohne_dubletten(["G", "V", "K"], grounded) == ["G", "V", "K"]


# ---- Erlassform-Woerter sind keine Suchbegriffe --------------------------- #

def test_konkordat_ist_kein_suchbegriff():
    """Gemessen: «(Konkordat)» aus dem Justizvollzugskonkordat traf NW 912.5
    «Interkantonale Vereinbarung ueber die computergestuetzte Zusammenarbeit» –
    ein voellig anderer Erlass, der «Konkordat» nur als Stichwort fuehrt."""
    from app.domains.ergebnisse.rechtsgrundlagen.grounding import suchbegriffe
    b = suchbegriffe("Justizvollzugskonkordat der Nordwest- und Innerschweiz (Konkordat)")
    assert "Konkordat" not in b
    assert "Justizvollzugskonkordat" in b        # der spezifische Name bleibt


@pytest.mark.parametrize("form", ["Konkordat", "Vereinbarung", "Abkommen", "Beschluss",
                                  "Weisung", "Dekret", "Verfassung"])
def test_erlassformen_fallen_als_suchbegriff_weg(form):
    from app.domains.ergebnisse.rechtsgrundlagen.grounding import suchbegriffe
    assert form not in suchbegriffe(f"Irgendein Spezialerlass ({form})")


# ---- Dubletten ohne Fundstelle ------------------------------------------- #

def test_dublette_ohne_fundstelle_wird_ueber_den_namen_erkannt():
    """«Kantonales Beschaffungsrecht (…)» und dasselbe mit «NW» standen als zwei
    Zeilen da; ohne Fundstelle greift der Nummernvergleich nicht."""
    from app.domains.ergebnisse.rechtsgrundlagen.service import RechtsgrundlagenService
    a = "Kantonales Beschaffungsrecht (Submissionsgesetz/-verordnung)"
    b = "Kantonales Beschaffungsrecht NW (Submissionsgesetz/-verordnung)"
    assert RechtsgrundlagenService._ohne_dubletten([a, b], {}) == [a]


def test_gesetz_und_verordnung_gelten_nicht_als_dublette():
    """Der Vergleich ist exakt, nicht unscharf - sonst verschwaende die Verordnung."""
    from app.domains.ergebnisse.rechtsgrundlagen.service import RechtsgrundlagenService
    g = "Bundesgesetz über das Strafregister"
    v = "Verordnung über das Strafregister"
    assert RechtsgrundlagenService._ohne_dubletten([g, v], {}) == [g, v]


# ---- Konkordat ist weder Gesetz noch Verordnung --------------------------- #
#
# Gemessen: «Konkordat ueber den Vollzug von Strafen und Massnahmen» war mit dem
# kantonalen «Gesetz ueber den Straf- und Massnahmenvollzug» (NW 273.3) belegt.
# Ein Konkordat ist eine eigene Erlassform - dieselbe Verwechslung droht bei
# IVoeB (Vereinbarung) und BoeB (Bundesgesetz).

def test_konkordat_ist_eine_eigene_erlassform():
    from app.domains.ergebnisse.rechtsgrundlagen.grounding import erlassform
    assert erlassform("Konkordat über den Vollzug von Strafen") == "konkordat"
    assert erlassform("Interkantonale Vereinbarung über das Beschaffungswesen") == "konkordat"
    assert erlassform("Gesetz über den Straf- und Massnahmenvollzug") == "gesetz"
    assert erlassform("Verordnung über das Strafregister") == "verordnung"


class _NurKantonalesGesetz:
    def suche_mehrere(self, begriffe, treffer_je_begriff=1, **_):
        return {b: [{"sr": "273.3", "titel": "Gesetz über den Straf- und Massnahmenvollzug",
                     "url": "u", "entity": "NW"}] for b in begriffe}


def test_konkordat_bekommt_nicht_das_kantonale_gesetz():
    """Formfremde Treffer werden VERWORFEN, nicht bloss hinten einsortiert -
    sonst bleibt der falsche Treffer stehen, wenn er der einzige ist."""
    from app.domains.ergebnisse.rechtsgrundlagen.grounding import ground_federal
    g = ground_federal(["Konkordat über den Vollzug von Strafen und Massnahmen"],
                       "kanton", _NurKantonalesGesetz(), kanton="Nidwalden")
    assert g == {}          # ehrlich leer statt falsch belegt


def test_vereinbarung_und_bundesgesetz_werden_getrennt():
    """IVoeB und BoeB heissen fast gleich - nur die Erlassform unterscheidet sie."""
    from app.domains.ergebnisse.rechtsgrundlagen.grounding import ground_federal

    class _Beide:
        def suche_mehrere(self, begriffe, treffer_je_begriff=1, **_):
            return {b: [
                {"sr": "172.056.1", "titel": "Bundesgesetz über das öffentliche "
                                             "Beschaffungswesen", "url": "u", "entity": "CH"},
                {"sr": "612.2", "titel": "Interkantonale Vereinbarung über das "
                                         "öffentliche Beschaffungswesen", "url": "u",
                 "entity": "NW"},
            ] for b in begriffe}

    g = ground_federal(["Bundesgesetz über das öffentliche Beschaffungswesen (BöB)",
                        "Interkantonale Vereinbarung über das öffentliche "
                        "Beschaffungswesen (IVöB)"], "kanton", _Beide(), kanton="Nidwalden")
    assert g["Bundesgesetz über das öffentliche Beschaffungswesen (BöB)"]["sr"] == "172.056.1"
    assert g["Interkantonale Vereinbarung über das öffentliche "
             "Beschaffungswesen (IVöB)"]["sr"] == "612.2"
