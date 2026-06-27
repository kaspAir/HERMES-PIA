"""Wissenskorpus (RAG): pseudonymisierte Projektergebnisse als durchsuchbare Chunks.

Mandantenmodell:
- org_id = NULL  -> geteilter Basiskorpus (Seed-PIAs, für alle Instanzen sichtbar)
- org_id = <X>   -> Korpus EINER Organisation (eigene freigegebene Ergebnisse)
Beim Retrieval gilt: org_id IS NULL OR org_id = <aktueller Mandant> -> kein
Überlaufen von Org-Inhalten in fremde Korpora.

Erweiterbar: `ergebnistyp` ist heute 'PIA'; spätere pseudonymisierte Ergebnisse
(Stakeholderliste, Rechtsgrundlagenanalyse, ...) kommen mit eigenem Typ ins selbe
Schema, ohne Migration.
"""
from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text

from app.shared.database import Base


class CorpusChunk(Base):
    __tablename__ = "corpus_chunks"

    id = Column(Integer, primary_key=True)
    ergebnistyp = Column(String(50), default="PIA", nullable=False)
    projekt = Column(String(300), nullable=True)      # Quelle/Pseudonym (z.B. Dateiname)
    abschnitt = Column(String(200), nullable=True)    # erkannte HERMES-Überschrift, falls vorhanden
    org_id = Column(Integer, nullable=True)            # NULL = geteilter Basiskorpus
    text = Column(Text, nullable=False)
    embedding_json = Column(Text, nullable=True)       # JSON-Liste von Floats
    model = Column(String(80), nullable=True)          # verwendetes Embedding-Modell
    created_at = Column(DateTime, default=datetime.utcnow)
