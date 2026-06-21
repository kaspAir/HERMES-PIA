import json
from datetime import date

from flask import Blueprint, current_app, jsonify, redirect, render_template, request, send_file, url_for

bp = Blueprint("ui", __name__)


@bp.get("/health")
def health():
    return jsonify({"status": "ok", "service": "methodos"})


@bp.get("/")
def index():
    method = current_app.method_service.get("hermes_pia")
    sessions = current_app.interview_service.all_sessions()
    return render_template("index.html", method=method, sessions=sessions)


@bp.post("/interview/start")
def interview_start():
    def _get(name, fallback=""):
        return request.form.get(name, "").strip() or fallback

    session = current_app.interview_service.start_session(
        method_id="hermes_pia",
        project_name=_get("project_name", "Unbenanntes Projekt"),
        projektnummer=_get("projektnummer") or None,
        auftraggeber=_get("auftraggeber") or None,
        verwaltungseinheit=_get("verwaltungseinheit") or None,
        created_by=_get("projektleiter") or None,
    )
    return redirect(url_for("ui.interview_workspace", session_id=session.id))


@bp.get("/interview/<int:session_id>")
def interview_workspace(session_id):
    svc = current_app.interview_service
    session = svc.get_session(session_id)
    if not session:
        return "Session nicht gefunden", 404
    state = svc.current_state(session)
    sections = svc.section_summary(session)
    preview = svc.preview_data(session)
    method = current_app.method_service.get(session.method_id)
    return render_template(
        "interview.html",
        session=session,
        state=state,
        sections=sections,
        preview=preview,
        method=method,
    )


@bp.post("/interview/<int:session_id>/answer")
def interview_answer(session_id):
    raw_text = request.form.get("raw_text", "").strip()
    svc = current_app.interview_service
    try:
        svc.submit_answer(session_id, raw_text)
    except ValueError as e:
        return str(e), 400
    return redirect(url_for("ui.interview_workspace", session_id=session_id))


@bp.post("/interview/<int:session_id>/followup")
def interview_followup(session_id):
    risk_id = request.form.get("risk_id", "")
    accepted = request.form.get("accepted", "0") == "1"
    raw_text = request.form.get("raw_text", "").strip() or None
    svc = current_app.interview_service
    try:
        svc.answer_followup(session_id, risk_id, accepted, raw_text)
    except ValueError as e:
        return str(e), 400
    return redirect(url_for("ui.interview_workspace", session_id=session_id))


@bp.post("/interview/<int:session_id>/edit/<section_id>")
def interview_edit(session_id, section_id):
    """Setzt einen Abschnitt zurück, damit er neu beantwortet werden kann."""
    current_app.interview_service.reset_section(session_id, section_id)
    return redirect(url_for("ui.interview_workspace", session_id=session_id))


# ---- Versionsverwaltung ----

@bp.get("/interview/<int:session_id>/version")
def interview_version(session_id):
    svc = current_app.interview_service
    session = svc.get_session(session_id)
    if not session:
        return "Session nicht gefunden", 404
    info = svc.version_info(session)
    return render_template("version_bump.html", session=session, info=info)


def _safe_filename(name_part):
    cleaned = "".join(c if c.isalnum() or c in " -_" else "_" for c in name_part).strip()
    return cleaned.replace(" ", "_")


@bp.post("/interview/<int:session_id>/version")
def interview_version_post(session_id):
    svc = current_app.interview_service
    session = svc.get_session(session_id)
    if not session:
        return "Session nicht gefunden", 404

    bump_type  = request.form.get("bump_type", "minor")
    bemerkungen = request.form.get("bemerkungen", "").strip()

    new_version, _ = svc.record_version_bump(
        session_id,
        bump_type=bump_type,
        projektleiter=session.created_by or "",
        bemerkungen=bemerkungen,
    )

    # Dateiname in den URL-Pfad legen, damit der Browser den Download korrekt
    # benennt – auch wenn der PHP-Proxy den Content-Disposition-Header entfernt.
    safe_name = _safe_filename(session.project_name or "Projekt")
    filename = f"{safe_name}_PIA_v{new_version}.docx"
    return redirect(url_for("ui.interview_download", session_id=session_id, filename=filename))


@bp.get("/interview/<int:session_id>/download/<path:filename>")
def interview_download(session_id, filename):
    """Generiert den PIA aus dem aktuellen Stand und liefert ihn als Download.

    Der Dateiname steht im URL-Pfad (filename), damit der Browser ihn auch dann
    übernimmt, wenn ein Proxy den Content-Disposition-Header verwirft.
    """
    svc = current_app.interview_service
    gen = current_app.generation_service
    session = svc.get_session(session_id)
    if not session:
        return "Session nicht gefunden", 404

    answers = json.loads(session.answers_json or "{}")
    changelog = json.loads(session.changelog_json or "[]")

    name_part = session.project_name or "Projekt"
    name_display = f"{name_part} / {session.projektnummer}" if session.projektnummer else name_part

    metadata = {
        "projektname":        name_display,
        "projektleiter":      session.created_by or "",
        "auftraggeber":       session.auftraggeber or "",
        "autor":              session.created_by or "",   # Autor = Projektleiter
        "verwaltungseinheit": session.verwaltungseinheit or "",
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


@bp.get("/demo/followups")
def demo_followups():
    entered = ["Verzoegerung durch oeffentliche Beschaffung"]
    followups = current_app.interview_service.followups_for_risks(
        "fachanwendung_einfuehrung", entered
    )
    return jsonify({"erfasst": entered, "nachfragen": followups})
