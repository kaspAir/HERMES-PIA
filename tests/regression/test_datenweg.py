"""Datenwege zu externen KI-Diensten: Schutzschicht, ausdrücklich direkt, aus.

Entscheid vom 15.10.2026: Direktzugang für Embeddings auf dev; die
Pseudonymisierung kommt später über ein Standardwerkzeug. Daraus folgen die
Regeln, die hier geprüft werden:

- Embedding-Anbindung und Schutzschicht sind getrennt; eine Integrationsstelle
  für die spätere Schutzschicht deckt Sprachmodell UND Embeddings ab.
- Direkt nur ausdrücklich (Schalter + Schlüssel); ein Schlüssel allein schaltet
  nichts um.
- Keine automatische Umgehung: ist eine Schutzschicht konfiguriert, gilt sie,
  und ihr Ausfall führt zu einem Fehler, nicht zum Anbieter.
- Anzeige und /health weisen den tatsächlichen Modus aus – ohne Schlüssel.
- Im Direktmodus verwendet das RAG nur zur externen Verarbeitung freigegebene
  Korpusteile.
"""
import json

import pytest
import requests

from app.config import Config
from app.domains.corpus.embeddings import VOYAGE_URL, EmbeddingDienstNichtErreichbar, VoyageEmbedder
from app.domains.corpus.service import RagService
from app.domains.llm import datenweg
from app.domains.llm.errors import PseudoNichtErreichbar
from app.factory import create_app
from tools.synthetische_faelle import WortEmbedder


# ---- Bestimmung der Wege --------------------------------------------------------- #

def test_ohne_konfiguration_ist_alles_aus():
    w = datenweg.bestimme({})
    assert w["llm"]["modus"] == w["embeddings"]["modus"] == "aus"


def test_direkt_nur_mit_schalter_und_schluessel():
    assert datenweg.bestimme({"VOYAGE_API_KEY": "k"})["embeddings"]["modus"] == "aus"
    w = datenweg.bestimme({"EMBEDDING_DIREKT": "1"})
    assert w["embeddings"]["modus"] == "aus" and "VOYAGE_API_KEY fehlt" in w["embeddings"]["grund"]
    assert datenweg.bestimme({"EMBEDDING_DIREKT": "1", "VOYAGE_API_KEY": "k"}
                             )["embeddings"]["modus"] == "direkt"


def test_embeddings_und_sprachmodell_sind_getrennt_schaltbar():
    w = datenweg.bestimme({"EMBEDDING_DIREKT": "1", "VOYAGE_API_KEY": "k"})
    assert w["embeddings"]["modus"] == "direkt" and w["llm"]["modus"] == "aus"
    w = datenweg.bestimme({"PSEUDO_UMGEHEN": "1", "ANTHROPIC_API_KEY": "k"})
    assert w["llm"]["modus"] == "direkt" and w["embeddings"]["modus"] == "aus"


def test_schutzschicht_gewinnt_und_der_konflikt_wird_ausgewiesen():
    w = datenweg.bestimme({"PSEUDO_BASIS_URL": "http://schutz", "PSEUDO_UMGEHEN": "1",
                           "ANTHROPIC_API_KEY": "k", "EMBEDDING_DIREKT": "1",
                           "VOYAGE_API_KEY": "k"})
    assert w["llm"]["modus"] == w["embeddings"]["modus"] == "schutzschicht"
    assert w["llm"]["url"] == "http://schutz/anthropic"
    assert w["embeddings"]["url"] == "http://schutz/voyage"
    assert w["hinweise"] and "wirkungslos" in w["hinweise"][0]


def test_integrationsstelle_je_dienst_einzeln_setzbar():
    """Ein späteres Standardwerkzeug muss nicht unser URL-Schema haben."""
    w = datenweg.bestimme({"SCHUTZSCHICHT_LLM_URL": "https://tool/llm",
                           "SCHUTZSCHICHT_EMBEDDING_URL": "https://tool/emb"})
    assert w["llm"] == {"modus": "schutzschicht", "url": "https://tool/llm", "schluessel": None}
    assert w["embeddings"]["url"] == "https://tool/emb"


def test_teilweise_schutzschicht_oeffnet_keinen_direktweg():
    """Ist nur für Embeddings eine Schutzschicht da, wird das Sprachmodell
    nicht still direkt angebunden – es bleibt aus."""
    w = datenweg.bestimme({"SCHUTZSCHICHT_EMBEDDING_URL": "https://tool/emb",
                           "PSEUDO_UMGEHEN": "1", "ANTHROPIC_API_KEY": "k"})
    assert w["llm"]["modus"] == "aus"


def test_oeffentliche_sicht_enthaelt_keine_schluessel():
    w = datenweg.oeffentlich(datenweg.bestimme(
        {"EMBEDDING_DIREKT": "1", "VOYAGE_API_KEY": "geheim-123"}))
    assert "geheim-123" not in json.dumps(w)
    assert w["embeddings"]["text"].startswith("DIREKT")


# ---- Embedding-Client --------------------------------------------------------------- #

class _Antwort:
    def __init__(self, n=1):
        self._n = n

    def raise_for_status(self):
        pass

    def json(self):
        return {"data": [{"index": i, "embedding": [0.1, 0.2]} for i in range(self._n)],
                "usage": {"total_tokens": 7}}


def test_direkter_embedding_aufruf_geht_an_voyage_ohne_kontextkoepfe(monkeypatch):
    gesehen = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        gesehen.update(url=url, headers=headers)
        return _Antwort()
    monkeypatch.setattr("app.domains.corpus.embeddings.requests.post", fake_post)
    e = VoyageEmbedder(api_key="k")
    assert e.modus == "direkt" and e.embed_one("Frage") == [0.1, 0.2]
    assert gesehen["url"] == VOYAGE_URL
    assert gesehen["headers"]["Authorization"] == "Bearer k"
    assert not [k for k in gesehen["headers"] if k.startswith("X-Pseudo")]
    assert e.tokens == 7


def test_ausfall_der_schutzschicht_fuehrt_nie_zum_anbieter(monkeypatch):
    aufrufe = []

    def fake_post(url, **kw):
        aufrufe.append(url)
        raise requests.ConnectionError("weg")
    monkeypatch.setattr("app.domains.corpus.embeddings.requests.post", fake_post)
    e = VoyageEmbedder(basis_url="http://schutz/voyage", api_key="k")
    assert e.modus == "schutzschicht"
    with pytest.raises(PseudoNichtErreichbar):
        e.embed(["Text"])
    assert aufrufe == ["http://schutz/voyage/v1/embeddings"]      # kein zweiter Versuch


def test_ausfall_im_direktmodus_ist_ein_fehler(monkeypatch):
    def fake_post(url, **kw):
        raise requests.Timeout("langsam")
    monkeypatch.setattr("app.domains.corpus.embeddings.requests.post", fake_post)
    with pytest.raises(EmbeddingDienstNichtErreichbar):
        VoyageEmbedder(api_key="k").embed(["Text"])


# ---- RAG im Direktmodus -------------------------------------------------------------- #

@pytest.fixture
def leere_app(tmp_path):
    from app.shared.database import SessionLocal

    class Cfg(Config):
        DATABASE_URL = "sqlite:///" + str(tmp_path / "dw.db").replace("\\", "/")
        SECRET_KEY = "x"
        EMBEDDING_DIREKT = True
        VOYAGE_API_KEY = "test-schluessel"
    SessionLocal.remove()
    app = create_app(Cfg)
    yield app
    SessionLocal.remove()


def test_fabrik_bindet_embeddings_ausdruecklich_direkt_an(leere_app):
    assert leere_app.rag_service.embedder.modus == "direkt"
    assert leere_app.rag_service.nur_extern_freigegeben is True
    h = leere_app.test_client().get("/health").get_json()
    assert h["datenwege"]["embeddings"]["modus"] == "direkt"
    assert "test-schluessel" not in json.dumps(h)


def test_direktmodus_durchsucht_nur_freigegebene_korpusteile(leere_app):
    with leere_app.app_context():
        offen = RagService(WortEmbedder(), nur_extern_freigegeben=False)
        offen.ingest_document("1 Ausgangslage\nMigration der Datenbestände war schwierig. " * 3,
                              projekt="Bestand-nicht-freigegeben")
        offen.ingest_document("1 Ausgangslage\nDie Migration der Schnittstellen verzögerte. " * 3,
                              projekt="Synthetisch-freigegeben", extern_freigegeben=True)
        direkt = RagService(WortEmbedder(), nur_extern_freigegeben=True)
        treffer, bericht = direkt.search_mit_bericht("Migration", top_k=5)
        assert {t["projekt"] for t in treffer} == {"Synthetisch-freigegeben"}
        assert bericht["nicht_freigegeben"] >= 1
        # Der Bestand bleibt unangetastet und in der Schutzschicht nutzbar.
        assert {t["projekt"] for t in offen.search("Migration", top_k=5)} == {
            "Bestand-nicht-freigegeben", "Synthetisch-freigegeben"}


def test_banner_nennt_den_direkten_embedding_weg(leere_app):
    org = leere_app.auth_service.create_org("Musteramt").id
    leere_app.auth_service.create_user("pl@m.example", "pw", org_id=org,
                                       can_read=True, can_write=True)
    c = leere_app.test_client()
    c.post("/login", data={"email": "pl@m.example", "password": "pw"})
    c.post("/interview/start", data={"project_name": "P", "projektleiter": "X"})
    sid = leere_app.interview_service.sessions_for_org(org)[0].id
    seite = c.get(f"/interview/{sid}").get_data(as_text=True)
    assert "Ohne Pseudonymisierung (Direktmodus)" in seite
    assert "Korpus- und Suchtexte" in seite
    assert "nur aus" in seite and "freigegebenen Korpusteilen" in seite


def test_ratenbegrenzung_wartet_und_wiederholt_denselben_weg(monkeypatch):
    """Voyage begrenzt Anfragen je Minute (429). Warten und erneut – nie
    auf einen anderen Weg ausweichen."""
    class Antwort429(_Antwort):
        status_code = 429
        headers = {"Retry-After": "1"}

    antworten = [Antwort429(), Antwort429(), _Antwort()]
    urls, pausen = [], []

    def fake_post(url, **kw):
        urls.append(url)
        return antworten.pop(0)
    monkeypatch.setattr("app.domains.corpus.embeddings.requests.post", fake_post)
    monkeypatch.setattr("app.domains.corpus.embeddings.time.sleep", pausen.append)
    e = VoyageEmbedder(api_key="k")
    assert e.embed(["x"]) == [[0.1, 0.2]]
    assert urls == [VOYAGE_URL] * 3 and pausen == [1.0, 1.0]
