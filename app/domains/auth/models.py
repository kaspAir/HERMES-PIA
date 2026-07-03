"""Datenmodell für Benutzerverwaltung: Organisationseinheiten und Benutzer.

Mandantenfähig: jede PIA gehört einer Organisationseinheit. Rechte werden
granular pro Person vergeben (Lesen / Schreiben / Löschen).
"""
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String

from app.shared.database import Base

# Rollen
ROLE_SUPER_ADMIN = "super_admin"   # Betreiber (BKI): verwaltet Organisationen
ROLE_ORG_ADMIN = "org_admin"       # Admin einer Organisationseinheit
ROLE_MEMBER = "member"             # normaler Benutzer


class Organisation(Base):
    __tablename__ = "organisation"

    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False, unique=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class User(Base):
    __tablename__ = "app_user"

    id = Column(Integer, primary_key=True)
    email = Column(String(200), nullable=False, unique=True)
    name = Column(String(200), nullable=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False, default=ROLE_MEMBER)
    org_id = Column(Integer, ForeignKey("organisation.id"), nullable=True)
    # Granulare CRUD-Rechte auf PIAs der eigenen Organisationseinheit
    can_read = Column(Boolean, default=True, nullable=False)
    can_write = Column(Boolean, default=False, nullable=False)
    can_delete = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    @property
    def is_super_admin(self):
        return self.role == ROLE_SUPER_ADMIN

    @property
    def is_org_admin(self):
        return self.role == ROLE_ORG_ADMIN
