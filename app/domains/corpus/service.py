"""RAG-Service: pseudonymisierte Ergebnisse einbetten, ablegen und mandanten-
getrennt durchsuchen.

Bewusst infrastrukturarm (passt zu Managed Hosting ohne Docker/Vektor-Server):
Embeddings liegen als JSON in SQLite, die Ähnlichkeit wird per Cosinus in Python
berechnet. Für die aktuelle Korpusgröße (einige Tausend Chunks) ist das schnell
genug; wächst es, tauschen wir nur die Suchschicht, nicht das Schema.
"""
import json
import re

from sqlalchemy import or_

from app.domains.corpus.models import CorpusChunk
from app.shared.database import SessionLocal

_HEADING_RE = re.compile(r'^\s*\d{1,2}(?:\.\d+)*\s+([A-Za-zÄÖÜäöü][^\n]{1,70})$')


def _chunk_text(text, max_chars=1200, min_chars=40):
    """Zerlegt einen Ergebnis-Volltext in abschnittsbewusste Chunks.

    - erkennt nummerierte HERMES-Überschriften (z.B. '1 Ausgangslage') als
      Abschnitt und Schnittgrenze,
    - überspringt Inhaltsverzeichnis-Zeilen (Punktführung),
    - packt Inhalt bis ~max_chars je Chunk.
    Rückgabe: Liste von (abschnitt|None, chunk_text).
    """
    chunks = []
    section = None
    buf, buflen = [], 0

    def flush():
        nonlocal buf, buflen
        t = " ".join(s for s in buf if s).strip()
        if len(t) >= min_chars:
            chunks.append((section, t))
        buf, buflen = [], 0

    for raw in (text or "").splitlines():
        s = raw.strip()
        if not s:
            continue
        if "....." in s or ". . ." in s:  # Inhaltsverzeichnis / Punktführung
            continue
        m = _HEADING_RE.match(s)
        if m and len(s) <= 70:
            flush()
            section = m.group(1).strip()
            buf, buflen = [s], len(s)
            continue
        buf.append(s)
        buflen += len(s) + 1
        if buflen >= max_chars:
            flush()
    flush()
    return chunks


def _cosine(a, b):
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


class RagService:
    def __init__(self, embedder):
        self.embedder = embedder

    @property
    def available(self):
        return bool(self.embedder) and self.embedder.available

    # ---- Ingest ---------------------------------------------------------- #

    def ingest_document(self, raw_text, projekt, org_id=None, ergebnistyp="PIA",
                        skip_if_exists=True):
        """Bettet ein Ergebnis-Dokument als Chunks ein und legt sie ab.

        org_id=None -> geteilter Basiskorpus; sonst Korpus dieser Organisation.
        Rückgabe: Anzahl gespeicherter Chunks (0 wenn kein Embedder / leer / Dublette).
        """
        if not self.available:
            return 0
        if skip_if_exists and self._exists(projekt, org_id, ergebnistyp):
            return 0
        chunks = _chunk_text(raw_text)
        if not chunks:
            return 0
        vectors = self.embedder.embed([c[1] for c in chunks], input_type="document")
        if not vectors or len(vectors) != len(chunks):
            return 0
        db = SessionLocal()
        for (section, ctext), vec in zip(chunks, vectors):
            db.add(CorpusChunk(
                ergebnistyp=ergebnistyp, projekt=projekt, abschnitt=section,
                org_id=org_id, text=ctext, embedding_json=json.dumps(vec),
                model=self.embedder.model,
            ))
        db.commit()
        return len(chunks)

    def _exists(self, projekt, org_id, ergebnistyp):
        db = SessionLocal()
        q = db.query(CorpusChunk).filter(
            CorpusChunk.projekt == projekt,
            CorpusChunk.ergebnistyp == ergebnistyp,
        )
        q = q.filter(CorpusChunk.org_id.is_(None)) if org_id is None \
            else q.filter(CorpusChunk.org_id == org_id)
        return db.query(q.exists()).scalar()

    # ---- Suche ----------------------------------------------------------- #

    def search(self, query, org_id=None, top_k=5, ergebnistyp=None, min_score=0.0):
        """Ähnlichste Chunks zum Query. Sichtbar: geteilter Basiskorpus (org_id NULL)
        UND der Korpus des aktuellen Mandanten – nie der anderer Organisationen."""
        if not self.available or not (query or "").strip():
            return []
        qvec = self.embedder.embed_one(query, input_type="query")
        if not qvec:
            return []
        db = SessionLocal()
        q = db.query(CorpusChunk)
        if org_id is None:
            q = q.filter(CorpusChunk.org_id.is_(None))
        else:
            q = q.filter(or_(CorpusChunk.org_id.is_(None), CorpusChunk.org_id == org_id))
        if ergebnistyp:
            q = q.filter(CorpusChunk.ergebnistyp == ergebnistyp)

        scored = []
        for r in q.all():
            if not r.embedding_json:
                continue
            score = _cosine(qvec, json.loads(r.embedding_json))
            if score >= min_score:
                scored.append((score, r))
        scored.sort(key=lambda t: t[0], reverse=True)
        return [{
            "score": round(score, 4),
            "projekt": r.projekt,
            "abschnitt": r.abschnitt,
            "ergebnistyp": r.ergebnistyp,
            "org_id": r.org_id,
            "text": r.text,
        } for score, r in scored[:top_k]]

    def count(self, org_id="__all__", ergebnistyp=None):
        db = SessionLocal()
        q = db.query(CorpusChunk)
        if org_id != "__all__":
            q = q.filter(CorpusChunk.org_id.is_(None)) if org_id is None \
                else q.filter(CorpusChunk.org_id == org_id)
        if ergebnistyp:
            q = q.filter(CorpusChunk.ergebnistyp == ergebnistyp)
        return q.count()
