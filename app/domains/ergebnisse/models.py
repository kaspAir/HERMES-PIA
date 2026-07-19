"""Datenmodell der abgeleiteten Initialisierungs-Ergebnisse.

Getrennt von der PIA-`InterviewSession`: der Entwurf eines Ergebnisses (z.B. der
Rechtsgrundlagenanalyse) wird hier abgelegt, der PIA bleibt unberührt.
"""
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text

from app.shared.database import Base


class ErgebnisEntwurf(Base):
    """Aus dem PIA abgeleiteter Entwurf eines Initialisierungs-Ergebnisses.

    Ein Eintrag je (Projekt, Ergebnistyp). `answers_json` hält die befüllten
    Abschnitte im gleichen Format wie eine Interview-Session (section_id →
    {extracted: ...}), sodass die generische Generierung sie ins Template füllt.
    """
    __tablename__ = "ergebnis_entwurf"

    id = Column(Integer, primary_key=True)
    projekt_id = Column(Integer, ForeignKey("projekt.id"), nullable=False, index=True)
    ergebnistyp = Column(String(60), nullable=False)   # = method_id, z.B. 'rechtsgrundlagenanalyse'
    # Querschnittliche Fakten (kanonisches Projektwissen), von anderen Ergebnissen erbbar.
    ebene = Column(String(40), nullable=True)          # 'bund' | 'kanton' | 'kommune' (CSV möglich)
    kanton = Column(String(60), nullable=True)
    answers_json = Column(Text, nullable=True)
    doc_version = Column(String(20), default="0.1")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
