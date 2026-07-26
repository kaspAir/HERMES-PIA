"""Ablage der fachlichen Prüfung (Stufe 4).

Bewusst eine EIGENE Tabelle und nicht ein Feld an der InterviewSession: der
Prüfer schreibt nichts in den PIA (Briefing 5.1). Das Protokoll liegt daneben,
nicht darin.
"""
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text

from app.shared.database import Base


class PiaPruefung(Base):
    """Ein Prüfprotokoll aus Auftraggeber-Sicht zu einem PIA-Stand."""
    __tablename__ = "pia_pruefung"

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("interview_session.id"),
                        nullable=False, index=True)
    # Auf welchen Stand sich die Prüfung bezieht – ein Protokoll altert mit dem PIA.
    pia_version = Column(String(20), nullable=True)
    protokoll_json = Column(Text, nullable=True)      # A–E, strukturiert
    empfehlung = Column(String(40), nullable=True)    # freigebbar | vorbehalt | nein
    # Versions-Triple (Briefing 5.2): Methode / Ground-Truth / Mandanten-Delta.
    skill_versionen_json = Column(Text, nullable=True)
    # Begründete Ablehnungen des Nutzers je Befund (Briefing 5.1, Widerspruch).
    widersprueche_json = Column(Text, nullable=True)
    erstellt_am = Column(DateTime, default=datetime.utcnow)

    # ---- Kapitelweiser Lauf ------------------------------------------- #
    # Die Prüfung läuft in Schritten: je Kapitel ein kurzer Aufruf, am Schluss
    # eine Synthese. So bleibt JEDER Schritt weit unter dem Worker-Zeitlimit,
    # und die Ausgabelänge muss nicht künstlich gedeckelt werden.
    status = Column(String(20), default="laufend")     # laufend | fertig
    schritt = Column(Integer, default=0)               # nächster offener Schritt
    teilbefunde_json = Column(Text, nullable=True)     # je Kapitel gesammelt
