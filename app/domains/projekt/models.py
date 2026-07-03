"""Datenmodell der Projektstruktur (HERMES).

Hierarchie:  Projekt > Phase > Modul > Ergebnis  (+ Meilensteine je Phase).

Bewusst zukunftsoffen gehalten:
* Phasen/Module/Ergebnisse sind Daten-Zeilen, keine hartcodierten Enums – damit
  später Konzept/Realisierung/Einführung (und weitere Module/Szenarien) ohne
  Code-Umbau dazukommen.
* Portfolios liegen in Zukunft *über* dem Projekt (n:m via Link-Tabelle); das
  Projekt bleibt die stabile Wurzel und trägt die Mandanten-Zugehörigkeit (org_id).

Das eigentliche PIA-Artefakt bleibt die `InterviewSession`; sie verweist über
`ergebnis_id` auf ihren Knoten in dieser Struktur (Modul Projektsteuerung).
"""
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String

from app.shared.database import Base
from app.shared.model_mixins import GovernanceMixin


class Projekt(Base, GovernanceMixin):
    __tablename__ = "projekt"

    id = Column(Integer, primary_key=True)
    # Mandantentrennung: ein Projekt gehört einer Organisationseinheit.
    org_id = Column(Integer, ForeignKey("organisation.id"), nullable=True, index=True)
    name = Column(String(200), nullable=False)
    projektnummer = Column(String(100), nullable=True)
    auftraggeber = Column(String(200), nullable=True)
    verwaltungseinheit = Column(String(200), nullable=True)
    geschaeftsbereich = Column(String(200), nullable=True)
    innenauftragsnummer = Column(String(100), nullable=True)
    # Geplanter Start = Meilenstein Projektinitialisierungsfreigabe (ISO-Datum).
    start_datum = Column(String(20), nullable=True)


class Phase(Base):
    __tablename__ = "phase"

    id = Column(Integer, primary_key=True)
    projekt_id = Column(Integer, ForeignKey("projekt.id"), nullable=False, index=True)
    code = Column(String(40), nullable=False)        # z.B. "initialisierung"
    name = Column(String(120), nullable=False)
    reihenfolge = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


class Modul(Base):
    __tablename__ = "modul"

    id = Column(Integer, primary_key=True)
    phase_id = Column(Integer, ForeignKey("phase.id"), nullable=False, index=True)
    code = Column(String(40), nullable=False)        # projektsteuerung | projektfuehrung | projektgrundlagen
    name = Column(String(120), nullable=False)
    reihenfolge = Column(Integer, default=0)


class Ergebnis(Base, GovernanceMixin):
    __tablename__ = "ergebnis"

    id = Column(Integer, primary_key=True)
    modul_id = Column(Integer, ForeignKey("modul.id"), nullable=False, index=True)
    ergebnistyp = Column(String(60), nullable=False)  # z.B. "projektinitialisierungsauftrag"
    titel = Column(String(200), nullable=True)
    # Aufgabe + verantwortliche Rolle aus dem Referenz-Katalog gespiegelt (für Anzeige).
    aufgabe = Column(String(200), nullable=True)
    rolle = Column(String(80), nullable=True)


class Meilenstein(Base):
    __tablename__ = "meilenstein"

    id = Column(Integer, primary_key=True)
    phase_id = Column(Integer, ForeignKey("phase.id"), nullable=False, index=True)
    code = Column(String(60), nullable=False)         # projektinitialisierungsfreigabe | ...
    name = Column(String(120), nullable=False)
    modul_code = Column(String(40), nullable=True)    # zugehöriges Modul
    rolle = Column(String(80), nullable=True)
    datum = Column(String(20), nullable=True)         # ISO; PI-Freigabe = start_datum
    ist_start = Column(Integer, default=0)            # 1 = Phasenstart (= Projektstart)
    reihenfolge = Column(Integer, default=0)
    status = Column(String(40), default="offen")


class MigrationFlag(Base):
    """Einmal-Marker für Daten-Migrationen – verhindert Mehrfach-Ausführung
    über mehrere Gunicorn-Worker/Neustarts hinweg (atomar via Primärschlüssel)."""
    __tablename__ = "migration_flag"

    key = Column(String(80), primary_key=True)
    applied_at = Column(DateTime, default=datetime.utcnow)
