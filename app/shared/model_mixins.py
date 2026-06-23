from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String


class GovernanceMixin:
    """Leichte Auditierbarkeit - bewusst einfach gehalten."""

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    version = Column(Integer, default=1)
    created_by = Column(String(120), nullable=True)
    status = Column(String(40), default="in Arbeit")
