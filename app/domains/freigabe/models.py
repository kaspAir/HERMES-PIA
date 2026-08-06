"""Ablage der Freigabe: Checkliste und Projektentscheid.

Beides sind eigene HERMES-Ergebnisse und keine Felder am
Projektinitialisierungsauftrag. Der Auftrag ist die Vereinbarung; die
Checkliste ist der Nachweis, dass geprüft wurde; der Entscheid ist die
Handlung des Auftraggebers. Drei Dinge, drei Tabellen – wer sie zusammenlegt,
kann später nicht mehr zeigen, worauf die Freigabe beruhte.
"""
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text

from app.shared.database import Base


class FreigabeCheckliste(Base):
    """Eine Checkliste zu einem Entscheid-Meilenstein.

    `art` benennt den Meilenstein (heute nur
    ``projektinitialisierungsfreigabe``); die Tabelle ist so gebaut, dass die
    späteren Entscheide – weiteres Vorgehen, Durchführungsfreigabe – dieselbe
    Ablage benutzen können, ohne dass etwas umgebaut werden muss.
    """
    __tablename__ = "freigabe_checkliste"

    id = Column(Integer, primary_key=True)
    projekt_id = Column(Integer, ForeignKey("projekt.id"), nullable=False, index=True)
    art = Column(String(60), nullable=False, default="projektinitialisierungsfreigabe")
    # Die drei Kapitel als Zeilenlisten: generell (1.1), organisation (1.2),
    # projekt (1.3). Sie liegen zusammen, weil sie zusammen bewertet werden.
    zeilen_json = Column(Text, nullable=True)
    status = Column(String(30), default="entwurf")     # entwurf | freigegeben
    # Worauf die Bewertung beruhte, als sie erzeugt wurde – Arbeitsstand oder
    # hochgeladene Fassung. Ohne diese Angabe ist der Nachweis wertlos.
    quelle = Column(String(40), nullable=True)
    freigegeben_am = Column(DateTime, nullable=True)
    freigegeben_durch = Column(String(200), nullable=True)
    erstellt_am = Column(DateTime, default=datetime.utcnow)
    aktualisiert_am = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Projektentscheid(Base):
    """Eine Zeile der Liste Projektentscheide Steuerung.

    Die Nummer folgt der HERMES-Vorlage (01 = Projektinitialisierungsfreigabe)
    und wird nicht fortlaufend vergeben: sie benennt den Entscheid, sie zählt
    ihn nicht.
    """
    __tablename__ = "projektentscheid"

    id = Column(Integer, primary_key=True)
    projekt_id = Column(Integer, ForeignKey("projekt.id"), nullable=False, index=True)
    nr = Column(String(10), nullable=False)
    entscheid = Column(String(300), nullable=False)
    grundlagen = Column(Text, nullable=True)          # eine Grundlage je Zeile
    entscheidungstraeger = Column(String(120), nullable=True)
    entscheidungsdatum = Column(String(20), nullable=True)   # ISO
    erfasst_am = Column(DateTime, default=datetime.utcnow)
