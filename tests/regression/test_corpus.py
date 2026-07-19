"""Beweist: RAG-Korpus chunked, bettet ein, sucht – und trennt Mandanten sauber."""
import pytest

from app.config import Config
from app.domains.corpus.service import RagService, _chunk_text, _cosine
from app.factory import create_app

_VOCAB = ["risiko", "datenschutz", "stakeholder", "budget", "migration",
          "ausgangslage", "prototyp", "beschaffung", "studie", "termin"]


class FakeEmbedder:
    """Deterministische Bag-of-Words-Vektoren über ein kleines Vokabular."""
    model = "fake"
    available = True

    def _vec(self, t):
        tl = (t or "").lower()
        return [float(tl.count(w)) for w in _VOCAB] + [1.0]

    def embed(self, texts, input_type="document"):
        if isinstance(texts, str):
            texts = [texts]
        return [self._vec(t) for t in texts]

    def embed_one(self, text, input_type="query"):
        return self._vec(text)


@pytest.fixture
def app(tmp_path):
    from app.shared.database import SessionLocal
    db_path = str(tmp_path / "rag.db").replace("\\", "/")

    class _Cfg(Config):
        DATABASE_URL = "sqlite:///" + db_path
        SECRET_KEY = "x"

    SessionLocal.remove()
    application = create_app(_Cfg)
    application.rag_service = RagService(FakeEmbedder())
    SessionLocal.remove()
    yield application
    SessionLocal.remove()


# ---- Chunking ------------------------------------------------------------- #

def test_chunk_text_erkennt_abschnitt_und_ueberspringt_toc():
    text = (
        "1 Ausgangslage ........................................ 2\n"   # TOC -> raus
        "1 Ausgangslage\n"
        "Die heutige Bearbeitung ist papierbasiert und langsam.\n\n"
        "9 Risiken\n"
        "Schluesselpersonen stehen nicht zur Verfuegung.\n"
    )
    chunks = _chunk_text(text, max_chars=1200, min_chars=10)
    abschnitte = [c[0] for c in chunks]
    assert "Ausgangslage" in abschnitte
    assert "Risiken" in abschnitte
    assert not any("....." in c[1] for c in chunks)


def test_cosine_basics():
    assert _cosine([1, 0], [1, 0]) == pytest.approx(1.0)
    assert _cosine([1, 0], [0, 1]) == pytest.approx(0.0)


# ---- Ingest + Suche + Mandantentrennung ----------------------------------- #

def test_ingest_und_suche(app):
    rag = app.rag_service
    with app.app_context():
        n = rag.ingest_document("1 Risiken\nDatenschutz und Risiko sind zentral.",
                                projekt="P1", org_id=None)
        assert n >= 1
        treffer = rag.search("Risiko Datenschutz", org_id=None)
        assert treffer and "Datenschutz" in treffer[0]["text"]
        assert treffer[0]["score"] > 0


def test_mandantentrennung(app):
    rag = app.rag_service
    with app.app_context():
        rag.ingest_document("Geteiltes Wissen ueber Risiko und Datenschutz in der Initialisierung.",
                            projekt="shared", org_id=None)
        rag.ingest_document("Org A interne Notiz ueber Stakeholder und Einbezug der Fachstellen.",
                            projekt="a", org_id=1)
        rag.ingest_document("Org B interne Notiz ueber Budget und Kostenrahmen des Vorhabens.",
                            projekt="b", org_id=2)

        # Org 1 sieht geteilt + eigene, NIE Org 2
        res1 = rag.search("Budget", org_id=1, min_score=-1.0)
        assert all(r["org_id"] in (None, 1) for r in res1)
        assert all(r["projekt"] != "b" for r in res1)

        # Reiner Basiskorpus (org_id=None) sieht nur Geteiltes
        res_shared = rag.search("Stakeholder", org_id=None, min_score=-1.0)
        assert all(r["org_id"] is None for r in res_shared)

        assert rag.count(org_id=None) == 1
        assert rag.count(org_id=1) == 1
        assert rag.count() == 3  # gesamt


def test_ingest_idempotent(app):
    rag = app.rag_service
    with app.app_context():
        doc = "1 Studie\nEine ausfuehrliche Studie zur Migration und Abloesung des Altsystems."
        a = rag.ingest_document(doc, projekt="P", org_id=None)
        b = rag.ingest_document(doc, projekt="P", org_id=None)
        assert a >= 1 and b == 0  # zweiter Lauf überspringt


# ---- Strukturierte Initialisierungs-Dauer (Vergleichswert) ---------------- #

def test_ingest_speichert_init_dauer(app):
    rag = app.rag_service
    with app.app_context():
        rag.ingest_document("Ausgangslage und Studie und Beschaffung und Prototyp im Vorhaben zur Migration.", projekt="D1",
                            org_id=None, init_dauer_wochen=39)
        t = rag.search("Ausgangslage Studie", org_id=None, min_score=-1.0)
        assert t and t[0]["init_dauer_wochen"] == 39


def test_vergleichbare_dauer_median_je_projekt(app):
    rag = app.rag_service
    with app.app_context():
        # Drei vergleichbare Projekte mit 26 / 39 / 52 Wochen -> Median 39
        rag.ingest_document("Ausgangslage Studie Prototyp Beschaffung Stakeholder Migration Budget Termin.", projekt="A",
                            org_id=None, init_dauer_wochen=26)
        rag.ingest_document("Ausgangslage Studie Prototyp Migration Stakeholder Beschaffung Budget Termin.", projekt="B",
                            org_id=None, init_dauer_wochen=39)
        rag.ingest_document("Ausgangslage Studie Prototyp Stakeholder Beschaffung Migration Budget Termin.", projekt="C",
                            org_id=None, init_dauer_wochen=52)
        res = rag.vergleichbare_dauer_wochen("Ausgangslage Studie Prototyp", org_id=None,
                                             min_score=-1.0)
        assert res and res["median_wochen"] == 39 and res["n_projekte"] == 3


def test_vergleichbare_dauer_ohne_daten_none(app):
    rag = app.rag_service
    with app.app_context():
        rag.ingest_document("Ausgangslage Studie Prototyp Beschaffung ohne jede Dauerangabe im Text.", projekt="X", org_id=None)
        assert rag.vergleichbare_dauer_wochen("Ausgangslage", org_id=None,
                                              min_score=-1.0) is None
