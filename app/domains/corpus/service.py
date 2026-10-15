"""RAG-Service: pseudonymisierte Ergebnisse einbetten, ablegen und mandanten-
getrennt durchsuchen.

Bewusst infrastrukturarm (passt zu Managed Hosting ohne Docker/Vektor-Server):
Embeddings liegen als JSON in SQLite, die Ähnlichkeit wird per Cosinus in Python
berechnet. Für die aktuelle Korpusgröße (einige Tausend Chunks) ist das schnell
genug; wächst es, tauschen wir nur die Suchschicht, nicht das Schema.
"""
import hashlib
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
    def __init__(self, embedder, nur_extern_freigegeben=None):
        self.embedder = embedder
        # Im Direktmodus gehen gefundene Passagen ungeschützt an den Anbieter
        # (Themenbewertung, Vorschlags-Grounding). Dann gilt nur, was
        # ausdrücklich zur externen Verarbeitung freigegeben ist. Ohne Angabe
        # folgt die Regel dem Modus des Embedders.
        if nur_extern_freigegeben is None:
            nur_extern_freigegeben = getattr(embedder, "modus", None) == "direkt"
        self.nur_extern_freigegeben = bool(nur_extern_freigegeben)

    @property
    def available(self):
        return bool(self.embedder) and self.embedder.available

    # ---- Ingest ---------------------------------------------------------- #

    def ingest_document(self, raw_text, projekt, org_id=None, ergebnistyp="PIA",
                        skip_if_exists=True, init_dauer_wochen=None,
                        methodenversion=None, methodenversion_herkunft=None,
                        korpus_version=None, extern_freigegeben=False):
        """Bettet ein Ergebnis-Dokument als Chunks ein und legt sie ab.

        org_id=None -> geteilter Basiskorpus; sonst Korpus dieser Organisation.
        `init_dauer_wochen`: geplante Dauer der Phase Initialisierung (Wochen) dieses
        Projekts – wird strukturiert je Chunk abgelegt und dient neuen Projekten als
        Vergleichswert. `methodenversion` samt `methodenversion_herkunft` (woher die
        Angabe stammt) und `korpus_version` machen jeden Treffer nachweisbar.
        Rückgabe: Anzahl gespeicherter Chunks (0 bei leer/Dublette).
        """
        if not self.available:
            return 0
        if skip_if_exists and self._exists(projekt, org_id, ergebnistyp):
            return 0
        dok_hash = hashlib.sha256((raw_text or "").encode("utf-8")).hexdigest()
        # Derselbe Text unter anderem Projektnamen ist eine Dublette: er würde
        # sonst als «zweites Vergleichsprojekt» seine eigene Aussage bestätigen
        # (Auftrag 13: keine unkontrollierte Rückspeisung, Duplikaterkennung).
        if self._hash_vorhanden(dok_hash, org_id):
            return 0
        chunks = _chunk_text(raw_text)
        if not chunks:
            return 0
        vectors = self.embedder.embed([c[1] for c in chunks], input_type="document")
        if not vectors or len(vectors) != len(chunks):
            return 0
        dauer = int(init_dauer_wochen) if init_dauer_wochen else None
        db = SessionLocal()
        for nr, ((section, ctext), vec) in enumerate(zip(chunks, vectors)):
            db.add(CorpusChunk(
                ergebnistyp=ergebnistyp, projekt=projekt, abschnitt=section,
                org_id=org_id, text=ctext, embedding_json=json.dumps(vec),
                model=self.embedder.model, init_dauer_wochen=dauer,
                dokument_hash=dok_hash, chunk_nr=nr,
                methodenversion=methodenversion,
                methodenversion_herkunft=methodenversion_herkunft,
                korpus_version=korpus_version,
                extern_freigegeben=bool(extern_freigegeben),
            ))
        db.commit()
        return len(chunks)

    def vergleichbare_dauer_wochen(self, query, org_id=None, top_k=8, min_score=0.35):
        """Median der Initialisierungs-Dauer (Wochen) ähnlicher Projekte, oder None.

        Aggregiert je Projekt (nicht je Chunk), damit ein Projekt mit vielen Treffern
        nicht überzählt. Grundlage für einen beratenden Dauer-Vorschlag."""
        treffer = self.search(query, org_id=org_id, top_k=top_k, min_score=min_score)
        je_projekt = {}
        for t in treffer:
            w = t.get("init_dauer_wochen")
            if w and w > 0:
                je_projekt.setdefault(t.get("projekt") or f"_{len(je_projekt)}", int(w))
        werte = sorted(je_projekt.values())
        if not werte:
            return None
        n = len(werte)
        median = werte[n // 2] if n % 2 else (werte[n // 2 - 1] + werte[n // 2]) / 2
        return {"median_wochen": round(median), "n_projekte": n}

    def _hash_vorhanden(self, dok_hash, org_id):
        """Liegt derselbe Text schon im geteilten oder im eigenen Korpus?"""
        db = SessionLocal()
        q = db.query(CorpusChunk).filter(CorpusChunk.dokument_hash == dok_hash)
        q = q.filter((CorpusChunk.org_id.is_(None)) | (CorpusChunk.org_id == org_id))             if org_id is not None else q.filter(CorpusChunk.org_id.is_(None))
        return db.query(q.exists()).scalar()

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
        return self.search_mit_bericht(query, org_id, top_k, ergebnistyp, min_score)[0]

    def search_mit_bericht(self, query, org_id=None, top_k=5, ergebnistyp=None,
                           min_score=0.0):
        """(Treffer, Bericht) – der Bericht sagt, was verglichen wurde und was nicht.

        Verglichen werden NUR Chunks, die mit demselben Embedding-Modell erzeugt
        wurden wie die Anfrage. Gleiche Vektorlänge allein beweist keine
        Vergleichbarkeit: zwei Modelle können gleich lange, aber völlig anders
        gemeinte Vektoren liefern (Auftrag 6.3). Übersprungene Chunks werden
        gezählt, nicht verschwiegen.
        """
        bericht = {"modell": getattr(self.embedder, "model", None), "verglichen": 0,
                   "inkompatibel": 0, "ohne_vektor": 0, "nicht_freigegeben": 0,
                   "nur_extern_freigegeben": self.nur_extern_freigegeben}
        if not self.available or not (query or "").strip():
            return [], bericht
        qvec = self.embedder.embed_one(query, input_type="query")
        if not qvec:
            return [], bericht
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
            if self.nur_extern_freigegeben and not r.extern_freigegeben:
                bericht["nicht_freigegeben"] += 1
                continue
            if not r.embedding_json:
                bericht["ohne_vektor"] += 1
                continue
            if r.model and bericht["modell"] and r.model != bericht["modell"]:
                bericht["inkompatibel"] += 1
                continue
            vec = json.loads(r.embedding_json)
            if len(vec) != len(qvec):
                bericht["inkompatibel"] += 1
                continue
            bericht["verglichen"] += 1
            score = _cosine(qvec, vec)
            if score >= min_score:
                scored.append((score, r))
        scored.sort(key=lambda t: t[0], reverse=True)
        treffer = []
        for score, r in scored[:top_k]:
            # Zweite Absicherung der Mandantentrennung – unabhängig vom Filter oben.
            if r.org_id is not None and r.org_id != org_id:
                continue
            treffer.append({
                "chunk_id": r.id,
                "score": round(score, 4),
                "projekt": r.projekt,
                "abschnitt": r.abschnitt,
                "ergebnistyp": r.ergebnistyp,
                "org_id": r.org_id,
                "text": r.text,
                "init_dauer_wochen": r.init_dauer_wochen,
                "dokument_hash": r.dokument_hash,
                "chunk_nr": r.chunk_nr,
                "methodenversion": r.methodenversion,
                "methodenversion_herkunft": r.methodenversion_herkunft,
                "korpus_version": r.korpus_version,
                "modell": r.model,
            })
        return treffer, bericht

    def chunk(self, chunk_id, org_id=None):
        """Eine Passage für die Quellenansicht – nur, wenn der Mandant sie sehen darf."""
        db = SessionLocal()
        r = db.get(CorpusChunk, int(chunk_id))
        if r is None or (r.org_id is not None and r.org_id != org_id):
            return None
        return {"chunk_id": r.id, "projekt": r.projekt, "abschnitt": r.abschnitt,
                "text": r.text, "methodenversion": r.methodenversion,
                "methodenversion_herkunft": r.methodenversion_herkunft,
                "dokument_hash": r.dokument_hash, "korpus_version": r.korpus_version}

    def count(self, org_id="__all__", ergebnistyp=None):
        db = SessionLocal()
        q = db.query(CorpusChunk)
        if org_id != "__all__":
            q = q.filter(CorpusChunk.org_id.is_(None)) if org_id is None \
                else q.filter(CorpusChunk.org_id == org_id)
        if ergebnistyp:
            q = q.filter(CorpusChunk.ergebnistyp == ergebnistyp)
        return q.count()
