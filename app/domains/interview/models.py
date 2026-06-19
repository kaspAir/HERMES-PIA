from sqlalchemy import Column, Integer, String, Text

from app.shared.database import Base
from app.shared.model_mixins import GovernanceMixin


class InterviewSession(Base, GovernanceMixin):
    __tablename__ = "interview_session"

    id = Column(Integer, primary_key=True)
    method_id = Column(String(60), nullable=False)
    project_type_id = Column(String(80), nullable=True)
    project_name = Column(String(200), nullable=True)
    projektnummer = Column(String(100), nullable=True)
    auftraggeber = Column(String(200), nullable=True)
    verwaltungseinheit = Column(String(200), nullable=True)
    # Antworten je Abschnitt als JSON-Text (MVP - bewusst simpel).
    answers_json = Column(Text, default="{}")
    # Versionsverwaltung
    doc_version = Column(String(20), default="0.1")
    changelog_json = Column(Text, default="[]")
    # Snapshot beim letzten Download – für Änderungserkennung
    last_snapshot_json = Column(Text, default="{}")
