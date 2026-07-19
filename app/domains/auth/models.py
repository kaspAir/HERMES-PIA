"""Datenmodell für Benutzerverwaltung: Organisationseinheiten und Benutzer.

Mandantenfähig: jede PIA gehört einer Organisationseinheit. Rechte werden
granular pro Person vergeben (Lesen / Schreiben / Löschen).
"""
from datetime import datetime

from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Integer, LargeBinary, String,
)
from sqlalchemy.orm import deferred

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


class OrgBranding(Base):
    """Erscheinungsbild einer Organisationseinheit (CI/CD): eigenes Logo und
    Farben für die Oberfläche. Gepflegt im PMO-Bereich; ohne Eintrag gilt das
    Standard-Erscheinungsbild."""
    __tablename__ = "org_branding"

    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organisation.id"), nullable=False, unique=True)
    # Hex-Farben (#RRGGBB) für die zentralen CSS-Variablen der Oberfläche.
    kopfleiste_farbe = Column(String(9), nullable=True)   # --color-brand
    akzent_farbe = Column(String(9), nullable=True)       # --color-accent (Titel/Links)
    primaer_farbe = Column(String(9), nullable=True)      # --color-primary (Buttons)
    logo_filename = Column(String(255), nullable=True)
    logo_mimetype = Column(String(60), nullable=True)
    # deferred: das Logo wird nicht bei jedem Seitenaufbau mitgeladen.
    logo_data = deferred(Column(LargeBinary, nullable=True))
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


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
