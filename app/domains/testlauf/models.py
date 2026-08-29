"""Ablage eines Testlaufs.

Eigene Tabelle, nicht ein Feld am Projekt: ein Testlauf ist ein Vorgang mit
Verlauf, nicht eine Eigenschaft. Und weil er ausweisen muss, dass die
Ergebnisse OHNE menschliches Urteil entstanden sind, braucht er ein Protokoll,
das bleibt - auch wenn der Lauf laengst durch ist.
"""
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text

from app.shared.database import Base


class Testlauf(Base):
    __tablename__ = "testlauf"

    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, nullable=True, index=True)
    projekt_id = Column(Integer, ForeignKey("projekt.id"), nullable=True, index=True)
    session_id = Column(Integer, nullable=True, index=True)

    ausgangslage = Column(Text, nullable=False)
    ebene = Column(String(60), nullable=True)
    kanton = Column(String(60), nullable=True)

    # Wo der Lauf steht: Index in SCHRITTE. Ein Schritt kann mehrere Aufrufe
    # brauchen (das Interview braucht einen je Abschnitt und Nachfrage).
    schritt = Column(Integer, default=0)
    status = Column(String(20), default="laeuft")     # laeuft | fertig | gescheitert
    # Ein Zaehler gegen die Endlosschleife. Kein Schoenheitsfehler, sondern
    # noetig: ein Schritt, der seinen Zustand nicht bewegt, liefe sonst ewig.
    aufrufe = Column(Integer, default=0)
    protokoll_json = Column(Text, default="[]")

    erstellt_am = Column(DateTime, default=datetime.utcnow)
    beendet_am = Column(DateTime, nullable=True)
