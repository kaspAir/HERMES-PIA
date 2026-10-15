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
