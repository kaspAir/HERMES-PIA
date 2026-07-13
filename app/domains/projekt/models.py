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

from sqlalchemy import (
    Column, DateTime, ForeignKey, Integer, LargeBinary, String, Text,
)

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


class ErgebnisDokument(Base):
    """Hochgeladene Datei zu einem Ergebnis (z.B. der freigabebereite PIA als .docx).

    Ablage als BLOB in der Datenbank: deploy-sicher (git reset --hard räumt keine
    Dateien weg), Backup = DB-Datei, Mandantentrennung über die Projektstruktur.
    Mehrere Uploads bleiben als Versionen erhalten; der neueste zählt.
    """
    __tablename__ = "ergebnis_dokument"

    id = Column(Integer, primary_key=True)
    ergebnis_id = Column(Integer, ForeignKey("ergebnis.id"), nullable=False, index=True)
    art = Column(String(30), nullable=False, default="freigabe")  # freigabe | ...
    filename = Column(String(255), nullable=False)
    mimetype = Column(String(120), nullable=True)
    size = Column(Integer, default=0)
    data = Column(LargeBinary, nullable=False)
    uploaded_by = Column(String(120), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class PraesentationsVorlage(Base):
    """PPTX-Vorlage für generierte Präsentationen.

    Gilt pro Organisationseinheit (projekt_id NULL) oder pro Projekt; die
    Projekt-Vorlage hat Vorrang. Auch eine leere Präsentation ist eine gültige
    Vorlage (dann zählen Folienmaster/Theme). Neuester Upload je Geltungsbereich zählt.
    """
    __tablename__ = "praesentations_vorlage"

    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, nullable=True, index=True)
    projekt_id = Column(Integer, ForeignKey("projekt.id"), nullable=True, index=True)
    filename = Column(String(255), nullable=False)
    size = Column(Integer, default=0)
    data = Column(LargeBinary, nullable=False)
    uploaded_by = Column(String(120), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class MethodenVorlage(Base):
    """Word-Vorlage (.docx/.dotx), aus deren Kapitelstruktur HERMES PIA das
    Interview ableitet.

    Gilt pro Organisationseinheit (projekt_id NULL) oder pro Projekt; die
    Projekt-Vorlage hat Vorrang. Neuester Upload je Geltungsbereich zählt –
    gleiche Mechanik wie die Präsentationsvorlage.
    """
    __tablename__ = "methoden_vorlage"

    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, nullable=True, index=True)
    projekt_id = Column(Integer, ForeignKey("projekt.id"), nullable=True, index=True)
    filename = Column(String(255), nullable=False)
    size = Column(Integer, default=0)
    data = Column(LargeBinary, nullable=False)
    uploaded_by = Column(String(120), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    # Vom Benutzer bestätigte Kapitel-Zuordnung (JSON-Liste). NULL = noch nicht
    # bestätigt → es gilt die automatische Erkennung.
    mapping_json = Column(Text, nullable=True)


class MigrationFlag(Base):
    """Einmal-Marker für Daten-Migrationen – verhindert Mehrfach-Ausführung
    über mehrere Gunicorn-Worker/Neustarts hinweg (atomar via Primärschlüssel)."""
    __tablename__ = "migration_flag"

    key = Column(String(80), primary_key=True)
    applied_at = Column(DateTime, default=datetime.utcnow)
