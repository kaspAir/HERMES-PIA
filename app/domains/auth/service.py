"""Benutzerverwaltung: Organisationen, Benutzer, Authentifizierung, Branding.

Passwörter werden ausschliesslich gehasht gespeichert (werkzeug).
"""
import re

from werkzeug.security import check_password_hash, generate_password_hash

from app.domains.auth.models import (
    ROLE_MEMBER,
    ROLE_ORG_ADMIN,
    ROLE_SUPER_ADMIN,
    Organisation,
    OrgBranding,
    User,
)
from app.shared.database import SessionLocal

_HEX_FARBE = re.compile(r"#[0-9a-fA-F]{6}$")


class AuthService:
    # ---- Organisationen ------------------------------------------------ #

    def list_orgs(self):
        return SessionLocal().query(Organisation).order_by(Organisation.name).all()

    def get_org(self, org_id):
        return SessionLocal().get(Organisation, int(org_id))

    def create_org(self, name):
        """Legt eine Organisationseinheit an. Idempotent: existiert der Name schon,
        wird die bestehende Einheit zurückgegeben (statt UNIQUE-Fehler -> 500)."""
        db = SessionLocal()
        name = (name or "").strip()
        existing = db.query(Organisation).filter(Organisation.name == name).first()
        if existing:
            return existing
        org = Organisation(name=name)
        db.add(org)
        db.commit()
        db.refresh(org)
        return org

    # ---- Erscheinungsbild (Branding) je Organisationseinheit ----------- #

    def get_branding(self, org_id):
        if not org_id:
            return None
        return SessionLocal().query(OrgBranding).filter(
            OrgBranding.org_id == int(org_id)
        ).first()

    def _branding_or_new(self, db, org_id):
        branding = db.query(OrgBranding).filter(
            OrgBranding.org_id == int(org_id)
        ).first()
        if branding is None:
            branding = OrgBranding(org_id=int(org_id))
            db.add(branding)
        return branding

    def set_branding_farben(self, org_id, kopfleiste=None, akzent=None, primaer=None):
        """Setzt die UI-Farben der Organisationseinheit (Hex #RRGGBB)."""
        werte = {}
        for feld, wert in (("kopfleiste_farbe", kopfleiste),
                           ("akzent_farbe", akzent),
                           ("primaer_farbe", primaer)):
            wert = (wert or "").strip()
            if wert and not _HEX_FARBE.match(wert):
                raise ValueError(f"Ungültige Farbe für {feld}: {wert}")
            werte[feld] = wert or None
        db = SessionLocal()
        branding = self._branding_or_new(db, org_id)
        for feld, wert in werte.items():
            setattr(branding, feld, wert)
        db.commit()
        return branding

    def set_branding_logo(self, org_id, filename, data, mimetype):
        db = SessionLocal()
        branding = self._branding_or_new(db, org_id)
        branding.logo_filename = filename
        branding.logo_data = data
        branding.logo_mimetype = mimetype
        db.commit()
        return branding

    def reset_branding(self, org_id):
        """Setzt das Erscheinungsbild auf den Standard zurück."""
        db = SessionLocal()
        branding = db.query(OrgBranding).filter(
            OrgBranding.org_id == int(org_id)
        ).first()
        if branding is not None:
            db.delete(branding)
            db.commit()
        return True

    # ---- Benutzer ------------------------------------------------------ #

    def get_user(self, user_id):
        if not user_id:
            return None
        return SessionLocal().get(User, int(user_id))

    def get_user_by_email(self, email):
        if not email:
            return None
        return SessionLocal().query(User).filter(
            User.email == email.strip().lower()
        ).first()

    def list_users(self, org_id):
        return SessionLocal().query(User).filter(
            User.org_id == org_id
        ).order_by(User.email).all()

    def create_user(self, email, password, name=None, role=ROLE_MEMBER, org_id=None,
                    can_read=True, can_write=False, can_delete=False):
        db = SessionLocal()
        user = User(
            email=email.strip().lower(),
            name=(name or "").strip() or None,
            password_hash=generate_password_hash(password),
            role=role,
            org_id=org_id,
            can_read=bool(can_read),
            can_write=bool(can_write),
            can_delete=bool(can_delete),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    def set_permissions(self, user_id, can_read, can_write, can_delete):
        db = SessionLocal()
        user = db.get(User, int(user_id))
        if user is None:
            return None
        # Rechte eines Org-Admins/Super-Admins werden nicht beschnitten.
        if user.role == ROLE_MEMBER:
            user.can_read = bool(can_read)
            user.can_write = bool(can_write)
            user.can_delete = bool(can_delete)
            db.commit()
        return user

    def set_role(self, user_id, role):
        """Wechselt die Rolle (member <-> org_admin). Super-Admins bleiben unberührt.
        Beförderung zum Org-Admin setzt volle Rechte."""
        db = SessionLocal()
        user = db.get(User, int(user_id))
        if user is None or user.role == ROLE_SUPER_ADMIN:
            return None
        if role not in (ROLE_MEMBER, ROLE_ORG_ADMIN):
            return user
        user.role = role
        if role == ROLE_ORG_ADMIN:
            user.can_read = user.can_write = user.can_delete = True
        db.commit()
        return user

    def delete_user(self, user_id):
        db = SessionLocal()
        user = db.get(User, int(user_id))
        if user is None or user.role == ROLE_SUPER_ADMIN:
            return False
        db.delete(user)
        db.commit()
        return True

    def change_password(self, user_id, old_password, new_password):
        """Selbstbedienung: setzt ein neues Passwort, wenn das alte stimmt."""
        db = SessionLocal()
        user = db.get(User, int(user_id))
        if user is None or not new_password:
            return False
        if not check_password_hash(user.password_hash, old_password or ""):
            return False
        user.password_hash = generate_password_hash(new_password)
        db.commit()
        return True

    def reset_password(self, user_id, new_password):
        """Admin-Aktion: setzt ein neues Passwort (ohne Prüfung des alten)."""
        db = SessionLocal()
        user = db.get(User, int(user_id))
        if user is None or not new_password:
            return False
        user.password_hash = generate_password_hash(new_password)
        db.commit()
        return True

    # ---- Authentifizierung -------------------------------------------- #

    def authenticate(self, email, password):
        user = self.get_user_by_email(email)
        if user and password and check_password_hash(user.password_hash, password):
            return user
        return None

    def ensure_super_admin(self, email, password):
        """Bootstrap des Betreiber-Accounts (idempotent). Ohne Passwort: nichts tun."""
        if not email or not password:
            return None
        existing = self.get_user_by_email(email)
        if existing:
            return existing
        return self.create_user(
            email, password, name="Betreiber", role=ROLE_SUPER_ADMIN, org_id=None,
            can_read=True, can_write=True, can_delete=True,
        )
