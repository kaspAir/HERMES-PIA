"""Befunde aus dem ersten echten Lauf auf dev (15.10.2026, echtes Modell,
echte Embeddings, synthetischer Korpus) – festgehalten als Tests.

1. Das Modell lieferte «45 Personentage» statt «45». Die Monatsverteilung
   las nur reine Zahlen und schlug deshalb nichts vor; Kap. 5 blieb leer.
2. Daraufhin bot die Frage einen «Untersuchungsauftrag» an, und das Modell
   machte aus «Ja, mach einen Vorschlag» ein erfundenes Ziel.
3. Bei jeder Suche entstand eine neue Umformulierung desselben Themas aus
   derselben Quelle (acht Fassungen) – dieselbe Frage kam immer wieder.
"""
import json

from app.domains.interview.adaptiv import planer, vorschlaege
from app.domains.interview.adaptiv.models import PiaRagThema
from app.domains.interview.adaptiv.rag_themen import ThemenQuelle
from app.domains.interview.adaptiv.vertraege import abschnittskatalog, pruefe_aussagen_antwort
from app.shared.database import SessionLocal
from tests.regression.adaptiv_hilfen import app, neue_session, neu, ops  # noqa: F401


def test_personentage_mit_einheit_werden_zur_zahl(app):
    katalog = abschnittskatalog(app.method_service.get("hermes_pia"))
    roh = json.dumps(ops(neu("Projektleiter: 45 Personentage",
                             ("personalaufwand", {"rolle": "PL", "aufwand": "45 Personentage"})),
                         neu("Auftraggeber rund 8 Tage",
                             ("personalaufwand", {"rolle": "AG", "aufwand": "ca. 8 Tage"}))))
    erg = pruefe_aussagen_antwort(roh, katalog, {})
    felder = [z["felder"] for op in erg.gueltig for z in op["ziele"]]
    assert felder[0]["aufwand"] == "45"
    assert felder[1]["aufwand"] == "ca. 8 Tage"      # nicht eindeutig -> bleibt, wie gesagt


def test_monatsverteilung_auch_bei_personentagen_mit_einheit():
    answers = {"_eckdaten": {"start_initialisierung": {"wert": "2027-02-01"},
                             "ende_initialisierung": {"wert": "2027-06-30"}},
               "personalaufwand": {"extracted": [{"rolle": "PL", "name": "Kim Muster",
                                                  "aufwand": "45 Personentage"}]}}
    ops_ = vorschlaege.monatsverteilung(answers, {})
    assert len(ops_) == 1 and "45 PT auf 5 Monat(e)" in ops_[0]["inhalt"]


def test_berechenbare_vorschlaege_bieten_keinen_untersuchungsauftrag_an():
    assert set(planer.BERECHENBAR) == set(vorschlaege.FUER_KRITERIUM)
    frage = planer.vorlagenfrage({"aktion": "vorschlag", "kontext": {"kriterium": {
        "id": "K-PO-1", "beschreibung": "Monatsverteilung der Personentage"}}})
    assert "Untersuchungsauftrag" not in frage and "Grundlage" in frage


def test_dieselbe_quelle_zum_selben_kapitel_ergibt_ein_thema(app):
    sid = neue_session(app)
    q = ThemenQuelle(None)
    treffer = [{"chunk_id": 7, "projekt": "Synthetik-01", "text": "Migration …"},
               {"chunk_id": 9, "projekt": "Synthetik-10", "text": "Betrieb …"}]

    def kandidat(thema, quellen, ziele):
        return {"thema": thema, "frage_ansatz": "?", "uebertragbarkeit": "nutzbar", "regel": "R1",
                "begruendung": "", "pia_ziele": ziele, "offene_aspekte": "", "quellen": quellen}
    assert q._ablegen(sid, 1, [kandidat("Datenqualität und Migration", [7], ["ziele"])],
                      treffer, ["Synthetik-01"]) == 1
    # Umformulierung aus derselben Quelle zum selben Kapitel: kein neues Thema.
    assert q._ablegen(sid, 2, [kandidat("Datenmigration früh untersuchen", [7], ["ziele"])],
                      treffer, ["Synthetik-01"]) == 0
    # Dieselbe Quelle, anderes Kapitel – und eine andere Quelle: je ein Thema.
    assert q._ablegen(sid, 3, [kandidat("Migration als Risiko", [7], ["risiken"]),
                               kandidat("Betrieb einbeziehen", [9], ["ziele"])],
                      treffer, ["Synthetik-01", "Synthetik-10"]) == 2
    assert SessionLocal().query(PiaRagThema).filter(PiaRagThema.session_id == sid).count() == 3


def test_bekannte_themen_gehen_an_das_modell(app):
    class Merker:
        def __init__(self):
            self.inhalt = ""

        def complete(self, system, messages, max_tokens=1024, **kw):
            self.inhalt = messages[-1]["content"]
            return json.dumps({"themen": []})

    class Zustand:
        aktive = []
        themen = [{"thema": "Datenqualität und Migration", "status": "gefragt"}]

    m = Merker()
    ThemenQuelle(None)._bewerte([{"chunk_id": 1, "text": "x"}], Zustand(), [], m)
    assert "BEREITS BEKANNTE THEMEN" in m.inhalt and "Datenqualität und Migration" in m.inhalt


def test_ersetzung_ohne_korrektursignal_wird_zum_widerspruch(app):
    """4. Befund: «Der Auftraggeber kann höchstens 4 Tage einsetzen» ersetzte still
    die zuvor genannten 10 Tage. Ohne Korrektursignal bleibt beides, der
    Widerspruch ist offen (AT05)."""
    from tests.regression.adaptiv_hilfen import ModellDouble, dienst
    erst = ops(neu("Der Auftraggeber rechnet mit 10 Personentagen",
                   ("personalaufwand", {"rolle": "AG", "aufwand": "10"})))
    ersetzen = ops({"op": "korrektur", "aussage": "A-0001", "art": "benutzerangabe",
                    "quelle": "wortlaut", "inhalt": "Der Auftraggeber setzt höchstens 4 Tage ein",
                    "ziele": [{"abschnitt": "personalaufwand", "felder": {"rolle": "AG", "aufwand": "4"}}]})
    d = dienst(app, ModellDouble(aussagen=[erst, ersetzen]))
    sid = neue_session(app)
    d.starte(sid)
    d.beitrag(sid, "Der Auftraggeber rechnet mit 10 Personentagen.", anfrage_id="w1")
    d.beitrag(sid, "Der Auftraggeber kann höchstens 4 Tage einsetzen.", anfrage_id="w2")
    z = d.zustand.lade(sid, False)
    assert {a["schluessel"]: a["status"] for a in z.aussagen} == {"A-0001": "aktiv", "A-0002": "aktiv"}
    (kf,) = [k for k in z.konflikte if k["status"] == "offen"]
    assert set(kf["aussagen"]) == {"A-0001", "A-0002"}


def test_ersetzung_mit_korrektursignal_bleibt_korrektur(app):
    from tests.regression.adaptiv_hilfen import ModellDouble, dienst
    erst = ops(neu("Der Auftraggeber rechnet mit 10 Personentagen",
                   ("personalaufwand", {"rolle": "AG", "aufwand": "10"})))
    ersetzen = ops({"op": "korrektur", "aussage": "A-0001", "art": "benutzerangabe",
                    "quelle": "wortlaut", "inhalt": "Der Auftraggeber setzt 4 Tage ein",
                    "ziele": [{"abschnitt": "personalaufwand", "felder": {"rolle": "AG", "aufwand": "4"}}]})
    d = dienst(app, ModellDouble(aussagen=[erst, ersetzen]))
    sid = neue_session(app)
    d.starte(sid)
    d.beitrag(sid, "Der Auftraggeber rechnet mit 10 Personentagen.", anfrage_id="k1")
    d.beitrag(sid, "Es gilt: der Auftraggeber setzt 4 Tage ein, nicht 10.", anfrage_id="k2")
    z = d.zustand.lade(sid, False)
    assert {a["schluessel"]: a["status"] for a in z.aussagen} == {"A-0001": "ersetzt", "A-0002": "aktiv"}
    assert not [k for k in z.konflikte if k["status"] == "offen"]


def _kriterium(kid, abschnitt):
    return {"id": kid, "abschnitt": abschnitt, "zustand": "unbekannt", "gewicht": "wesentlich",
            "beschreibung": kid, "aktion": "erkunden", "details": [], "vorlagenfrage": ""}


def test_unbekanntes_wird_hoechstens_einmal_angeboten():
    """5. Befund (Testlauf dev): «weiss ich noch nicht» zum Enddatum – und
    HERMES PIA fragte rund achtmal weiter. Jetzt: ein Angebot, dann offen."""
    aussagen = [{"schluessel": "A-0001", "herkunft": "benutzer", "status": "aktiv", "art": "benutzerangabe",
                 "bestaetigt": True, "ziele": [{"abschnitt": "ausgangslage"}], "entscheid": None}]
    kriterien = [_kriterium("K-ZI-1", "ziele")]
    erst = planer.naechste_aktion(aussagen, [], [], kriterien, [])
    assert erst["aktion"] == "vorschlag" and erst["ziel"] == "K-ZI-1"
    gefragt = [{"rolle": "system", "aktion": "vorschlag", "bezug": {"ziel": "K-ZI-1"}}]
    assert planer.naechste_aktion(aussagen, [], [], kriterien, gefragt)["aktion"] == "abschluss"


def test_eckdaten_werden_nicht_vorgeschlagen():
    aussagen = [{"schluessel": "A-0001", "herkunft": "benutzer", "status": "aktiv", "art": "benutzerangabe",
                 "bestaetigt": True, "ziele": [{"abschnitt": "ausgangslage"}], "entscheid": None}]
    kriterien = [_kriterium("K-ECK-ENDE", "eckdaten")]
    assert planer.naechste_aktion(aussagen, [], [], kriterien, [])["aktion"] == "abschluss"


def test_frage_prompt_verbietet_eigene_werte():
    from app.domains.interview.adaptiv import prompts
    text = prompts.fuelle("frage")
    assert "Schlage NIE selbst Werte vor" in text and "heute" in text
