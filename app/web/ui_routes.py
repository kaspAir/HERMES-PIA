import json
from datetime import date

from flask import (
    Blueprint, abort, current_app, jsonify, redirect, render_template, request,
    send_file, url_for,
)

from app.domains.auth.models import ROLE_ORG_ADMIN, ROLE_SUPER_ADMIN
from app.web.auth import (
    current_user, login_required, login_user, logout_user, permission_required,
    roles_required,
)

bp = Blueprint("ui", __name__)


@bp.get("/health")
def health():
    return jsonify({"status": "ok", "service": "methodos"})


# ---- Mandantentrennung: Session laden + Zugriff prüfen ---------------- #

def _load_session(session_id):
    """Lädt eine PIA und stellt sicher, dass sie zur Organisation des
    angemeldeten Benutzers gehört (Super-Admin darf alle)."""
    session = current_app.interview_service.get_session(session_id)
    if not session:
        abort(404)
    user = current_user()
    if user is None:
        abort(401)
    if not user.is_super_admin and session.org_id != user.org_id:
        abort(403)
    return session


# ---- Authentifizierung ----------------------------------------------- #

@bp.get("/login")
def login():
    if current_user():
        return redirect(url_for("ui.index"))
    return render_template("login.html")


@bp.post("/login")
def login_post():
    email = request.form.get("email", "").strip()
    password = request.form.get("password", "")
    user = current_app.auth_service.authenticate(email, password)
    if not user:
        return render_template("login.html", error="E-Mail oder Passwort falsch.",
                               email=email), 401
    login_user(user)
    return redirect(url_for("ui.index"))


@bp.post("/logout")
def logout():
    logout_user()
    return redirect(url_for("ui.login"))


@bp.get("/passwort")
@login_required
def password_change():
    return render_template("passwort.html")


@bp.post("/passwort")
@login_required
def password_change_post():
    user = current_user()
    old = request.form.get("old_password", "")
    new = request.form.get("new_password", "")
    confirm = request.form.get("confirm_password", "")
    if len(new) < 8:
        return render_template("passwort.html",
                               error="Das neue Passwort muss mindestens 8 Zeichen haben."), 400
    if new != confirm:
        return render_template("passwort.html",
                               error="Die beiden Passwörter stimmen nicht überein."), 400
    if not current_app.auth_service.change_password(user.id, old, new):
        return render_template("passwort.html",
                               error="Das aktuelle Passwort ist nicht korrekt."), 400
    return render_template("passwort.html", success="Ihr Passwort wurde geändert.")


# ---- Startseite ------------------------------------------------------- #

@bp.get("/")
@login_required
def index():
    user = current_user()
    if user.is_super_admin:
        return redirect(url_for("ui.admin_orgs"))
    method = current_app.method_service.get("hermes_pia")
    sessions = current_app.interview_service.sessions_for_org(user.org_id)
    return render_template("index.html", method=method, sessions=sessions)


@bp.post("/interview/start")
@permission_required("write")
def interview_start():
    def _get(name, fallback=""):
        return request.form.get(name, "").strip() or fallback

    user = current_user()
    project_name = _get("project_name")
    projektleiter = _get("projektleiter")
    if not project_name or not projektleiter:
        method = current_app.method_service.get("hermes_pia")
        sessions = current_app.interview_service.sessions_for_org(user.org_id)
        return render_template("index.html", method=method, sessions=sessions,
                               error="Projektname und Projektleiter/in sind erforderlich.",
                               form=request.form), 400

    session = current_app.interview_service.start_session(
        method_id="hermes_pia",
        project_name=project_name,
        org_id=user.org_id,
        projektnummer=_get("projektnummer") or None,
        auftraggeber=_get("auftraggeber") or None,
        verwaltungseinheit=_get("verwaltungseinheit") or None,
        geschaeftsbereich=_get("geschaeftsbereich") or None,
        innenauftragsnummer=_get("innenauftragsnummer") or None,
        start_datum=_get("start_datum") or None,
        created_by=projektleiter,
    )
    return redirect(url_for("ui.interview_workspace", session_id=session.id))


@bp.get("/interview/<int:session_id>")
@permission_required("read")
def interview_workspace(session_id):
    svc = current_app.interview_service
    session = _load_session(session_id)
    state = svc.current_state(session)
    sections = svc.section_summary(session)
    preview = svc.preview_data(session)
    method = current_app.method_service.get(session.method_id)
    return render_template(
        "interview.html",
        session=session, state=state, sections=sections, preview=preview, method=method,
    )


@bp.post("/interview/<int:session_id>/answer")
@permission_required("write")
def interview_answer(session_id):
    _load_session(session_id)
    raw_text = request.form.get("raw_text", "").strip()
    try:
        current_app.interview_service.submit_answer(session_id, raw_text)
    except ValueError as e:
        return str(e), 400
    return redirect(url_for("ui.interview_workspace", session_id=session_id))


@bp.post("/interview/<int:session_id>/followup")
@permission_required("write")
def interview_followup(session_id):
    _load_session(session_id)
    risk_id = request.form.get("risk_id", "")
    accepted = request.form.get("accepted", "0") == "1"
    raw_text = request.form.get("raw_text", "").strip() or None
    try:
        current_app.interview_service.answer_followup(session_id, risk_id, accepted, raw_text)
    except ValueError as e:
        return str(e), 400
    return redirect(url_for("ui.interview_workspace", session_id=session_id))


@bp.post("/interview/<int:session_id>/delete")
@permission_required("delete")
def interview_delete(session_id):
    _load_session(session_id)
    current_app.interview_service.delete_session(session_id)
    return redirect(url_for("ui.index"))


@bp.get("/interview/<int:session_id>/edit/<section_id>")
@permission_required("write")
def interview_edit(session_id, section_id):
    """Bearbeiten: Freitext mit vorgeladenem Inhalt; Tabellen werden zurückgesetzt."""
    svc = current_app.interview_service
    session = _load_session(session_id)
    section = svc._section_by_id(session.method_id, section_id)
    if not section:
        return "Abschnitt nicht gefunden", 404
    if section.get("type") == "free_text":
        return render_template("edit_section.html", session=session, section=section,
                               text=svc.section_text(session, section_id))
    svc.reset_section(session_id, section_id)
    return redirect(url_for("ui.interview_workspace", session_id=session_id))


@bp.post("/interview/<int:session_id>/edit/<section_id>")
@permission_required("write")
def interview_edit_save(session_id, section_id):
    """Speichert den bearbeiteten Freitext und lässt ihn neu formulieren."""
    _load_session(session_id)
    raw_text = request.form.get("raw_text", "").strip()
    current_app.interview_service.update_free_text(session_id, section_id, raw_text)
    return redirect(url_for("ui.interview_workspace", session_id=session_id))


# ---- Versionsverwaltung ---------------------------------------------- #

@bp.get("/interview/<int:session_id>/version")
@permission_required("write")
def interview_version(session_id):
    svc = current_app.interview_service
    session = _load_session(session_id)
    info = svc.version_info(session)
    return render_template("version_bump.html", session=session, info=info)


def _safe_filename(name_part):
    cleaned = "".join(c if c.isalnum() or c in " -_" else "_" for c in name_part).strip()
    return cleaned.replace(" ", "_")


@bp.post("/interview/<int:session_id>/version")
@permission_required("write")
def interview_version_post(session_id):
    svc = current_app.interview_service
    session = _load_session(session_id)

    bump_type = request.form.get("bump_type", "minor")
    bemerkungen = request.form.get("bemerkungen", "").strip()
    new_version, _ = svc.record_version_bump(
        session_id, bump_type=bump_type,
        projektleiter=session.created_by or "", bemerkungen=bemerkungen,
    )

    safe_name = _safe_filename(session.project_name or "Projekt")
    filename = f"{safe_name}_PIA_v{new_version}.docx"
    return redirect(url_for("ui.interview_download", session_id=session_id, filename=filename))


@bp.get("/interview/<int:session_id>/download/<path:filename>")
@permission_required("read")
def interview_download(session_id, filename):
    """Generiert den PIA aus dem aktuellen Stand und liefert ihn als Download."""
    svc = current_app.interview_service
    gen = current_app.generation_service
    session = _load_session(session_id)

    answers = json.loads(session.answers_json or "{}")
    changelog = json.loads(session.changelog_json or "[]")

    name_part = session.project_name or "Projekt"
    name_display = f"{name_part} / {session.projektnummer}" if session.projektnummer else name_part

    pl_weiblich = ag_weiblich = False
    if getattr(svc, "llm", None):
        from app.domains.interview.extraction import detect_gender
        pl_weiblich = detect_gender(svc.llm, session.created_by or "") == "w"
        ag_weiblich = detect_gender(svc.llm, session.auftraggeber or "") == "w"

    metadata = {
        "projektname":        name_display,
        "projektleiter":      session.created_by or "",
        "auftraggeber":       session.auftraggeber or "",
        "projektleiter_weiblich": pl_weiblich,
        "auftraggeber_weiblich":  ag_weiblich,
        "autor":              session.created_by or "",
        "verwaltungseinheit": session.verwaltungseinheit or "",
        "geschaeftsbereich":  session.geschaeftsbereich or "",
        "innenauftragsnummer": session.innenauftragsnummer or "",
        "projektnummer":      session.projektnummer or "",
        "datum":              date.today().strftime("%d.%m.%Y"),
        "version":            session.doc_version or "0.1",
        "status":             "in Arbeit",
        "klassifizierung":    "Nicht klassifiziert",
    }

    buf = gen.generate(session.method_id, answers, metadata, changelog=changelog)
    return send_file(
        buf,
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        as_attachment=True,
        download_name=filename,
    )


# ===================================================================== #
# Verwaltung: Betreiber (Super-Admin) – Organisationseinheiten          #
# ===================================================================== #

@bp.get("/admin/organisationen")
@roles_required(ROLE_SUPER_ADMIN)
def admin_orgs():
    auth = current_app.auth_service
    orgs = auth.list_orgs()
    org_users = {o.id: auth.list_users(o.id) for o in orgs}
    return render_template("admin_orgs.html", orgs=orgs, org_users=org_users)


@bp.post("/admin/organisationen/neu")
@roles_required(ROLE_SUPER_ADMIN)
def admin_org_create():
    name = request.form.get("name", "").strip()
    if name:
        current_app.auth_service.create_org(name)
    return redirect(url_for("ui.admin_orgs"))


@bp.post("/admin/organisationen/<int:org_id>/admin")
@roles_required(ROLE_SUPER_ADMIN)
def admin_org_admin_create(org_id):
    auth = current_app.auth_service
    email = request.form.get("email", "").strip()
    password = request.form.get("password", "")
    name = request.form.get("name", "").strip()
    if email and password and not auth.get_user_by_email(email):
        auth.create_user(email, password, name=name, role=ROLE_ORG_ADMIN, org_id=org_id,
                         can_read=True, can_write=True, can_delete=True)
    return redirect(url_for("ui.admin_orgs"))


# ===================================================================== #
# Verwaltung: Org-Admin – Benutzer der eigenen Organisationseinheit      #
# ===================================================================== #

@bp.get("/admin/benutzer")
@roles_required(ROLE_ORG_ADMIN)
def admin_users():
    auth = current_app.auth_service
    user = current_user()
    org = auth.get_org(user.org_id)
    users = auth.list_users(user.org_id)
    return render_template("admin_users.html", org=org, users=users)


@bp.post("/admin/benutzer/neu")
@roles_required(ROLE_ORG_ADMIN)
def admin_user_create():
    auth = current_app.auth_service
    user = current_user()
    email = request.form.get("email", "").strip()
    password = request.form.get("password", "")
    name = request.form.get("name", "").strip()
    if email and password and not auth.get_user_by_email(email):
        auth.create_user(
            email, password, name=name, org_id=user.org_id,
            can_read=request.form.get("can_read") == "on",
            can_write=request.form.get("can_write") == "on",
            can_delete=request.form.get("can_delete") == "on",
        )
    return redirect(url_for("ui.admin_users"))


@bp.post("/admin/benutzer/<int:user_id>/rechte")
@roles_required(ROLE_ORG_ADMIN)
def admin_user_permissions(user_id):
    auth = current_app.auth_service
    target = auth.get_user(user_id)
    # Nur Benutzer der eigenen Organisationseinheit verwalten.
    if target and target.org_id == current_user().org_id:
        auth.set_permissions(
            user_id,
            request.form.get("can_read") == "on",
            request.form.get("can_write") == "on",
            request.form.get("can_delete") == "on",
        )
    return redirect(url_for("ui.admin_users"))


@bp.post("/admin/benutzer/<int:user_id>/loeschen")
@roles_required(ROLE_ORG_ADMIN)
def admin_user_delete(user_id):
    auth = current_app.auth_service
    target = auth.get_user(user_id)
    if target and target.org_id == current_user().org_id:
        auth.delete_user(user_id)
    return redirect(url_for("ui.admin_users"))


@bp.post("/admin/benutzer/<int:user_id>/passwort")
@roles_required(ROLE_SUPER_ADMIN, ROLE_ORG_ADMIN)
def admin_reset_password(user_id):
    """Admin setzt das Passwort eines Benutzers zurück.
    Hauptadmin: alle. Org-Admin: nur Benutzer der eigenen Organisation."""
    auth = current_app.auth_service
    actor = current_user()
    target = auth.get_user(user_id)
    new_password = request.form.get("new_password", "")
    if target and new_password:
        allowed = actor.is_super_admin or (
            actor.is_org_admin
            and target.org_id == actor.org_id
            and not target.is_super_admin
        )
        if allowed:
            auth.reset_password(user_id, new_password)
    return redirect(url_for("ui.admin_orgs") if actor.is_super_admin
                    else url_for("ui.admin_users"))
