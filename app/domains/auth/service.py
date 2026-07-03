"""Benutzerverwaltung: Organisationen, Benutzer, Authentifizierung.

Passwörter werden ausschliesslich gehasht gespeichert (werkzeug).
"""
from werkzeug.security import check_password_hash, generate_password_hash

from app.domains.auth.models import (
    ROLE_MEMBER,
    ROLE_ORG_ADMIN,
    ROLE_SUPER_ADMIN,
    Organisation,
    User,
)
from app.shared.database import SessionLocal


class AuthService:
    # ---- Organisationen ------------------------------------------------ #

    def list_orgs(self):
        return SessionLocal().query(Organisation).order_by(Organisation.name).all()

    def get_org(self, org_id):
        return SessionLocal().get(Organisation, int(org_id))

    def create_org(self, name):
        db = SessionLocal()
        org = Organisation(name=(name or "").strip())
        db.add(org)
        db.commit()
        db.refresh(org)
        return org

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
