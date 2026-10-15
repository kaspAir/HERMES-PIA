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

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text

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
    # Strukturierte Kennzahl: geplante Dauer der Phase Initialisierung (Wochen).
    # Wird beim Ingest je Dokument gesetzt und dient als Vergleichswert für neue
    # Projekte (beratender Dauer-Vorschlag), statt sie später aus Freitext zu raten.
    init_dauer_wochen = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # ---- Nachweis (additiv, 15.10.2026) ----------------------------------- #
    # Damit ein Verweis tatsächlich zur verwendeten Passage führt (Auftrag 6.3).
    # NULL heisst «nicht erfasst» – für Bestandschunks wird nichts erfunden.
    dokument_hash = Column(String(64), nullable=True)    # SHA-256 des Quelltexts
    chunk_nr = Column(Integer, nullable=True)            # Position im Dokument
    # Methodenversion der Quelle UND woher diese Angabe stammt. Unbekannt
    # bleibt unbekannt; sie wird nicht pauschal zu HERMES 2022 umetikettiert.
    methodenversion = Column(String(40), nullable=True)
    methodenversion_herkunft = Column(String(120), nullable=True)
    korpus_version = Column(String(40), nullable=True)   # Ingest-/Indexstand
    # Ausdrücklich zur externen Verarbeitung OHNE Schutzschicht freigegeben
    # (synthetisch, geeignet öffentlich oder bereinigt UND freigegeben). Nur
    # solche Passagen verwendet das RAG im Direktmodus – sie gehen dort
    # ungeschützt an den Sprachmodell-Anbieter. Bestand: NULL = nicht freigegeben.
    extern_freigegeben = Column(Boolean, nullable=True, default=False)
