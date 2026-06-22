"""Web-seitige Authentifizierung: aktueller Benutzer, Login-Schutz, Rechteprüfung."""
from functools import wraps

from flask import abort, current_app, g, redirect, session, url_for


def current_user():
    """Aktuell angemeldeter Benutzer (pro Request gecacht)."""
    if not hasattr(g, "_current_user"):
        uid = session.get("user_id")
        g._current_user = current_app.auth_service.get_user(uid) if uid else None
    return g._current_user


def login_user(user):
    session["user_id"] = user.id


def logout_user():
    session.pop("user_id", None)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_user() is None:
            return redirect(url_for("ui.login"))
        return view(*args, **kwargs)
    return wrapped


def roles_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user = current_user()
            if user is None:
                return redirect(url_for("ui.login"))
            if user.role not in roles:
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator


def permission_required(perm):
    """perm: 'read' | 'write' | 'delete' – prüft can_<perm> des Benutzers."""
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user = current_user()
            if user is None:
                return redirect(url_for("ui.login"))
            if not getattr(user, f"can_{perm}", False):
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator
