from sqlalchemy import Column, Integer, String, Text

from app.shared.database import Base
from app.shared.model_mixins import GovernanceMixin


class InterviewSession(Base, GovernanceMixin):
    __tablename__ = "interview_session"

    id = Column(Integer, primary_key=True)
    method_id = Column(String(60), nullable=False)
    # Mandantentrennung: jede PIA gehört einer Organisationseinheit.
    org_id = Column(Integer, nullable=True)
    project_type_id = Column(String(80), nullable=True)
    project_name = Column(String(200), nullable=True)
    projektnummer = Column(String(100), nullable=True)
    auftraggeber = Column(String(200), nullable=True)
    verwaltungseinheit = Column(String(200), nullable=True)
    geschaeftsbereich = Column(String(200), nullable=True)
    innenauftragsnummer = Column(String(100), nullable=True)
    # Geplanter Start der Phase Initialisierung (ISO-Datum); leer -> heute
    start_datum = Column(String(20), nullable=True)
    # Antworten je Abschnitt als JSON-Text (MVP - bewusst simpel).
    answers_json = Column(Text, default="{}")
    # Versionsverwaltung: startet bei 0.0 – der erste generierte PIA ist 0.1.
    doc_version = Column(String(20), default="0.0")
    changelog_json = Column(Text, default="[]")
    # Snapshot beim letzten Download – für Änderungserkennung
    last_snapshot_json = Column(Text, default="{}")
    # Verknüpfung in die Projektstruktur: Ergebnis-Knoten im Modul Projektsteuerung.
    ergebnis_id = Column(Integer, nullable=True)

    # ---- Adaptives Interview (additiv; ältere Sessions bleiben unverändert) ---- #
    # NULL/"abschnitt" = bisheriger abschnittsweiser Ablauf; "adaptiv" = neuer.
    modus = Column(String(20), nullable=True)
    # Zustandsrevision: jede Änderung am gemeinsamen Zustand zählt hoch. Eine
    # verspätete Antwort, die auf einer älteren Revision beruht, überschreibt
    # nichts Neueres (Auftrag Abschnitt 8.3/12).
    revision = Column(Integer, nullable=True, default=0)
    # Gespeicherte nächste Gesprächsaktion: ein Reload zeigt dieselbe Frage.
    naechste_aktion_json = Column(Text, nullable=True)
    # Noch ausstehende Verarbeitungsschritte nach einem Beitrag.
    ausstehend_json = Column(Text, nullable=True)
    # Interner Bearbeitungszustand – NICHT Prüfung, Abnahme oder Freigabe.
    pia_status = Column(String(30), nullable=True)
    # Stand der Themensuche im Korpus (letzte Anfrage, Verfügbarkeit).
    rag_stand_json = Column(Text, nullable=True)
