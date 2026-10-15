"""Der bestehende RAG als Themenquelle des Interviews.

Zugeordnete Akzeptanzfälle: AT02, AT08, AT09, AT10, AT11, AT12, AT15.

Die Treffer kommen aus einem echten `RagService` mit echter SQLite-Ablage;
nur das Embedding ist ein deterministisches Double. Ein produktiver
Nachweis gegen den Server-Korpus ist damit NICHT erbracht – siehe
docs/adaptives_interview/01_ist_analyse.md, Abschnitt 3.
"""
import json

from app.domains.corpus.service import RagService
from app.domains.interview.adaptiv.planer import naechste_aktion
from app.domains.interview.adaptiv.rag_themen import ThemenQuelle, gesperrt
from app.domains.interview.adaptiv.vollstaendigkeit import bewerte
from tests.regression.adaptiv_hilfen import (  # noqa: F401 – Fixture
    ModellDouble, app, bis_zur_frage, dienst, neu, neue_session, ops,
)

_WORTE = ["migration", "schnittstelle", "datenbestand", "ablösung", "fachanwendung",
          "bewilligung", "stakeholder", "voranalyse", "projektauftrag", "gesuch"]


class WortEmbedder:
    """Deterministische Wortzähl-Vektoren über ein kleines Fachvokabular."""
    available = True

    def __init__(self, model="wort-v1"):
        self.model = model

    def _v(self, t):
        t = (t or "").lower()
        return [float(t.count(w)) for w in _WORTE] + [0.5]

    def embed(self, texte, input_type="document"):
        return [self._v(t) for t in ([texte] if isinstance(texte, str) else texte)]

    def embed_one(self, text, input_type="query"):
        return self._v(text)


MIGRATION = ("1 Ausgangslage\nDie Ablösung der Fachanwendung scheiterte beinahe an der "
             "Migration der Datenbestände. Die Schnittstelle zum Register war nicht "
             "dokumentiert, und [Person_3] von [Org_2] schätzte den Aufwand auf CHF 480'000.")
METHODE = ("2 Vorgehen\nGemäss HERMES 5.1 folgt nach der Voranalyse der Projektauftrag. "
           "Die Voranalyse ist zwingend vor dem Projektauftrag abzuschliessen.")


def _korpus(app, *texte, org_id=None, embedder=None):
    rag = RagService(embedder or WortEmbedder())
    for i, t in enumerate(texte):
        rag.ingest_document(t, projekt=f"Vergleich-{i}", org_id=org_id,
                            methodenversion=None, korpus_version="test-1")
    return rag


def _vorhaben(app, d, sid):
    # Eckdaten sind bekannt – damit ist die wichtigste offene Lücke inhaltlich
    # (Ziele/Risiken), und an ihr muss sich zeigen, ob der Korpus die Frage prägt.
    modell_aussagen = ops(
        neu("Die Fachanwendung für Bewilligungen ist am Ende ihres Lebenszyklus und soll "
            "abgelöst werden; Gesuche werden heute doppelt erfasst", ("ausgangslage", {})),
        neu("Die Ablösung betrifft auch die Datenbestände der letzten zehn Jahre",
            ("ausgangslage", {})),
        neu("Die Initialisierung läuft vom 2. November 2026 bis zum 26. Februar 2027",
            ("eckdaten", {"start_initialisierung": "2026-11-02",
                          "ende_initialisierung": "2027-02-26"})),
    )
    d.llm.aussagen.append(modell_aussagen)
    d.starte(sid)
    d.beitrag(sid, "Unsere Fachanwendung für Bewilligungen muss abgelöst werden. Gesuche "
                   "werden doppelt erfasst. Es geht auch um zehn Jahre Datenbestände.",
              anfrage_id="v1")


# ---- AT08 / AT10 – ein Treffer führt nachweisbar zu einer Frage -------------- #

def test_at08_rag_thema_fuehrt_zu_einer_kontextgerechten_frage(app):
    rag = _korpus(app, MIGRATION)
    modell = ModellDouble(themen=[{"themen": [{
        "thema": "Datenmigration und Schnittstellen", "regel": "R1",
        "uebertragbarkeit": "nutzbar", "begruendung": "Ablösung mit Altdaten",
        "frage_ansatz": "Welche Datenbestände und Schnittstellen sollen wir in der "
                        "Initialisierung untersuchen, damit der Umfang der Ablösung abschätzbar wird?",
        "pia_ziele": ["ziele", "risiken"], "quellen": []}]}])
    sid = neue_session(app)
    d = dienst(app, modell, themen=ThemenQuelle(rag))
    _vorhaben(app, d, sid)
    # Die Quelle muss eine der GEZEIGTEN Passagen sein: das Double liest sie
    # aus dem Aufruf, wie es ein Modell täte.
    cid = rag.search_mit_bericht("migration datenbestand", top_k=1)[0][0]["chunk_id"]
    modell.themen[0]["themen"][0]["quellen"] = [cid]

    ansicht = bis_zur_frage(d, sid)
    z = d.zustand.lade(sid)
    assert len(z.themen) == 1
    thema = z.themen[0]
    assert thema["quellen"][0]["chunk_id"] == cid
    assert thema["quellen"][0]["methodenversion"] == "HERMES 5.1"
    assert "nicht je Dokument geprüft" in thema["quellen"][0]["methodenversion_herkunft"]
    # Die Frage MUSS aus dem Thema entstehen – ohne Bedingung. Eine frühere
    # Fassung prüfte das nur «falls» der Planer das Thema wählte, und verdeckte
    # damit, dass er es nie wählte: RAG-Themen standen neben den Lücken statt
    # in ihnen.
    assert ansicht["frage"].get("unterart") == "rag"
    assert ansicht["frage"]["abschnitt"] in ("ziele", "risiken")
    assert "Vergleichsprojekt" in ansicht["frage"]["begruendung"]
    frage = [m for m in z.nachrichten if m["rolle"] == "system"][-1]
    assert frage["bezug"]["thema_id"] == thema["id"]
    assert frage["bezug"]["quellen"] == [cid]
    assert d.zustand.lade(sid).themen[0]["status"] == "gefragt"


def test_at10_mehrere_chunks_eines_projekts_sind_ein_beleg(app):
    lang = MIGRATION + "\n" + "\n".join(
        f"{i} Abschnitt\nDie Migration der Datenbestände und die Schnittstelle bleiben "
        f"anspruchsvoll, Ablösung Fachanwendung Teil {i}." for i in range(2, 6))
    rag = _korpus(app, lang)
    treffer, _ = rag.search_mit_bericht("migration datenbestand schnittstelle", top_k=8)
    assert len(treffer) > 1 and len({t["projekt"] for t in treffer}) == 1
    quelle = ThemenQuelle(rag)
    kand = quelle.pruefe(json.dumps({"themen": [{
        "thema": "Datenmigration", "regel": "R1", "uebertragbarkeit": "nutzbar",
        "frage_ansatz": "Was ist zu untersuchen?", "pia_ziele": ["risiken"],
        "quellen": [t["chunk_id"] for t in treffer]}]}), treffer, {"risiken"})
    sid = neue_session(app)
    quelle._ablegen(sid, 1, kand, treffer, ["Vergleich-0"])
    thema = dienst(app).zustand.lade(sid).themen[0]
    assert len(thema["quellen"]) == len(treffer)
    assert thema["n_projekte"] == 1                 # nicht len(treffer)


def test_at10_erfundene_quellen_werden_verworfen(app):
    rag = _korpus(app, MIGRATION)
    treffer, _ = rag.search_mit_bericht("migration", top_k=3)
    kand = ThemenQuelle(rag).pruefe(json.dumps({"themen": [{
        "thema": "Datenmigration", "regel": "R1", "uebertragbarkeit": "nutzbar",
        "frage_ansatz": "…", "pia_ziele": ["risiken"], "quellen": [99999]}]}),
        treffer, {"risiken"})
    assert kand == []


# ---- AT09 – Versionsgrenze ------------------------------------------------------ #

def test_at09_alte_methodenpflicht_wird_nicht_uebernommen(app):
    rag = _korpus(app, METHODE)
    treffer, _ = rag.search_mit_bericht("voranalyse projektauftrag", top_k=3)
    quelle = ThemenQuelle(rag)
    # Regel R2 erlaubt nur «nicht_uebernehmen» oder «methodisch_klaeren».
    falsch = quelle.pruefe(json.dumps({"themen": [{
        "thema": "Voranalyse durchführen", "regel": "R2", "uebertragbarkeit": "nutzbar",
        "frage_ansatz": "Wann führst Du die Voranalyse durch?", "pia_ziele": ["termine"],
        "quellen": [treffer[0]["chunk_id"]]}]}), treffer, {"termine"})
    assert falsch == []
    richtig = quelle.pruefe(json.dumps({"themen": [{
        "thema": "Voranalyse aus HERMES 5.1", "regel": "R2", "uebertragbarkeit": "nicht_uebernehmen",
        "frage_ansatz": "", "pia_ziele": ["termine"], "quellen": [treffer[0]["chunk_id"]]}]}),
        treffer, {"termine"})
    sid = neue_session(app)
    quelle._ablegen(sid, 1, richtig, treffer, [])
    d = dienst(app)
    z = d.zustand.lade(sid)
    assert z.themen[0]["status"] == "erledigt"      # wird nie gefragt
    aktion = naechste_aktion(z.aussagen, z.konflikte, z.themen, bewerte(z.aussagen, {}), z.nachrichten)
    assert not str(aktion["ziel"]).startswith("T-")
    # … und erzeugt keine Terminzeile.
    from app.domains.method import vorlagenzuordnung as vz
    assert not any("Voranalyse" in z_ for z_ in vz.basiszeilen("termine"))


# ---- AT11 – RAG-Ausfall ---------------------------------------------------------- #

def test_at11_ohne_embedding_zugang_laeuft_das_interview_weiter(app):
    sid = neue_session(app)
    d = dienst(app, ModellDouble(), themen=ThemenQuelle(RagService(None)))
    _vorhaben(app, d, sid)
    ansicht = bis_zur_frage(d, sid)
    assert ansicht["frage"]["frage"]                          # es geht weiter
    assert ansicht["erkannt"]["rag"]["verfuegbar"] is False
    assert "nicht konfiguriert" in ansicht["erkannt"]["rag"]["grund"]
    assert ansicht["erkannt"]["themen"] == []                 # keine erfundenen Belege


def test_at11_suchfehler_stoppt_das_interview_nicht(app):
    class Kaputt(RagService):
        def search_mit_bericht(self, *a, **kw):
            raise ConnectionError("Embedding-Dienst weg")
    sid = neue_session(app)
    d = dienst(app, ModellDouble(), themen=ThemenQuelle(Kaputt(WortEmbedder())))
    _vorhaben(app, d, sid)
    ansicht = bis_zur_frage(d, sid)
    assert ansicht["frage"]["frage"]
    assert "fehlgeschlagen" in ansicht["erkannt"]["rag"]["grund"]


def test_at11_leere_treffer_erzeugen_keine_themen(app):
    sid = neue_session(app)
    d = dienst(app, ModellDouble(), themen=ThemenQuelle(_korpus(app)))
    _vorhaben(app, d, sid)
    ansicht = bis_zur_frage(d, sid)
    assert ansicht["erkannt"]["themen"] == []
    assert "Keine passenden" in ansicht["erkannt"]["rag"]["grund"]


# ---- AT12 – RAG-Abgrenzung ---------------------------------------------------------- #

def test_at12_fremde_mandanten_bleiben_unzugaenglich(app):
    rag = _korpus(app, MIGRATION, org_id=7)
    eigene, _ = rag.search_mit_bericht("migration", org_id=7)
    fremde, _ = rag.search_mit_bericht("migration", org_id=8)
    geteilt, _ = rag.search_mit_bericht("migration", org_id=None)
    assert eigene and not fremde and not geteilt
    assert rag.chunk(eigene[0]["chunk_id"], org_id=8) is None


def test_at12_namen_betraege_und_pseudonyme_werden_nicht_uebernommen(app):
    assert gesperrt("[Person_3] hat das geschätzt")
    assert gesperrt("Aufwand CHF 480'000")
    assert gesperrt("rund 2,4 Mio für die Umsetzung")
    assert gesperrt("wie bei Vergleich-0", projekte=["Vergleich-0"])
    assert not gesperrt("Welche Datenbestände sind zu untersuchen?")
    rag = _korpus(app, MIGRATION)
    treffer, _ = rag.search_mit_bericht("migration", top_k=2)
    kand = ThemenQuelle(rag).pruefe(json.dumps({"themen": [{
        "thema": "Migration wie bei [Org_2]", "regel": "R1", "uebertragbarkeit": "nutzbar",
        "frage_ansatz": "Rechnest Du auch mit CHF 480'000?", "pia_ziele": ["kosten"],
        "quellen": [treffer[0]["chunk_id"]]}]}), treffer, {"kosten"})
    assert kand == []


def test_at12_inkompatible_embeddings_werden_nicht_verglichen(app):
    alt = _korpus(app, MIGRATION, embedder=WortEmbedder(model="anderes-modell"))
    assert alt.count() == 1
    neu_ = RagService(WortEmbedder(model="wort-v1"))
    treffer, bericht = neu_.search_mit_bericht("migration datenbestand")
    # Gleiche Vektorlänge, anderes Modell: nicht verglichen, aber gezählt.
    assert treffer == []
    assert bericht["inkompatibel"] == 1 and bericht["verglichen"] == 0


# ---- AT02 – gleicher Abschnitt, anderer Kontext -------------------------------------- #

def test_at02_gleicher_abschnitt_unterschiedlicher_kontext(app):
    """Derselbe offene Abschnitt (Risiken) führt je nach Kontext zu
    unterschiedlichen, begründeten Aktionen."""
    def plane(aussagen, konflikte=(), themen=()):
        kr = bewerte(list(aussagen), {}, list(konflikte))
        return naechste_aktion(list(aussagen), list(konflikte), list(themen), kr, [])

    basis = {"schluessel": "A-0001", "inhalt": "Anlass", "thema": "", "art": "benutzerangabe",
             "herkunft": "benutzer", "bestaetigt": True, "bezug": "initialisierung",
             "entscheid": None, "zurueckgestellt": False, "status": "aktiv",
             "ziele": [{"abschnitt": "ausgangslage", "felder": {}}]}
    unbekannt = dict(basis, schluessel="A-0002", art="unbekannt", thema="Risiken",
                     ziele=[{"abschnitt": "risiken", "felder": {}}])
    konflikt = {"id": 1, "aussagen": ["A-0001", "A-0003"], "beschreibung": "Frist 3 oder 6 Monate?",
                "status": "offen", "quelle": "gespraech"}
    thema = {"id": 5, "thema": "Datenmigration", "status": "kandidat", "uebertragbarkeit": "nutzbar",
             "pia_ziele": ["risiken"], "n_projekte": 2, "frage_ansatz": "Untersuchen?", "quellen": []}

    a = plane([basis], konflikte=[konflikt])
    b = plane([basis, unbekannt])
    c = plane([basis], themen=[thema])
    assert a["aktion"] == "widerspruch"
    assert any(k["aktion"] == "vorschlag" and k["abschnitt"] == "risiken"
               for k in __import__("app.domains.interview.adaptiv.planer", fromlist=["x"])
               .kandidaten([basis, unbekannt], [], [], bewerte([basis, unbekannt], {}), []))
    assert b["aktion"] != a["aktion"]
    # Mit einem passenden Thema aus Vergleichsprojekten steht es als
    # begründeter Kandidat bereit – mit Quelle im Entscheidungshinweis.
    from app.domains.interview.adaptiv.planer import kandidaten
    rag_k = [k for k in kandidaten([basis], [], [thema], bewerte([basis], {}), [])
             if k.get("unterart") == "rag"]
    assert rag_k and "Vergleichsprojekt" in rag_k[0]["begruendung"]
    assert c["begruendung"]


# ---- AT15 – keine Scheinsicherheit ------------------------------------------------------ #

def test_at15_herkunft_ist_unterscheidbar_und_ohne_prozente(app):
    sid = neue_session(app)
    d = dienst(app, ModellDouble(aussagen=[ops(
        neu("Gesuche werden doppelt erfasst", ("ausgangslage", {})),
        neu("Es handelt sich um eine Ablösung", ("ausgangslage", {}), quelle="gefolgert"),
        neu("Rund 20 PT", ("personalaufwand", {"rolle": "PL", "aufwand": "20"}), art="schaetzung"),
    )]))
    d.starte(sid)
    ansicht = d.beitrag(sid, "…", anfrage_id="s1")
    texte = {e["inhalt"]: e["status_text"]
             for g in ansicht["erkannt"]["gruppen"] for e in g["eintraege"]}
    texte.update({e["inhalt"]: e["status_text"] for e in ansicht["erkannt"]["offen"]})
    assert texte["Gesuche werden doppelt erfasst"] == "von Dir genannt"
    assert texte["Es handelt sich um eine Ablösung"] == "Interpretation – noch zu bestätigen"
    assert texte["Rund 20 PT"] == "von Dir geschätzt"
    roh = json.dumps(ansicht["erkannt"], ensure_ascii=False)
    assert "%" not in roh and "konfidenz" not in roh.lower()
