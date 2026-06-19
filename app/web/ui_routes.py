from flask import Blueprint, current_app, jsonify, redirect, render_template, request, url_for

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
    project_name = request.form.get("project_name", "").strip() or "Unbenanntes Projekt"
    session = current_app.interview_service.start_session(
        method_id="hermes_pia",
        project_name=project_name,
        created_by=request.form.get("created_by", ""),
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
    method = current_app.method_service.get(session.method_id)
    return render_template(
        "interview.html",
        session=session,
        state=state,
        sections=sections,
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


@bp.get("/demo/followups")
def demo_followups():
    entered = ["Verzoegerung durch oeffentliche Beschaffung"]
    followups = current_app.interview_service.followups_for_risks(
        "fachanwendung_einfuehrung", entered
    )
    return jsonify({"erfasst": entered, "nachfragen": followups})
