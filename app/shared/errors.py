import logging

from flask import jsonify, render_template, request

log = logging.getLogger("hermes.fehler")


class AppError(Exception):
    status_code = 400


def register_error_handlers(app):
    @app.errorhandler(AppError)
    def handle_app_error(exc):
        return jsonify({"error": str(exc)}), exc.status_code

    @app.errorhandler(404)
    def handle_404(_):
        return jsonify({"error": "not found"}), 404

    @app.errorhandler(Exception)
    def handle_unerwartet(exc):
        """Unerwarteter Fehler – mit BRAUCHBARER Meldung statt nackter Flask-Seite.

        Vorher endete jeder unbehandelte Fehler als «Internal Server Error» ohne
        jede Angabe. Wer ihn sah, musste erst im Serverlog nachsehen, um überhaupt
        zu wissen, wonach er sucht. Fehlerklasse und Meldung stehen deshalb auf
        der Seite; der vollständige Traceback bleibt im Protokoll.
        """
        from werkzeug.exceptions import HTTPException
        # Echte HTTP-Antworten (404, 405, 403 …) durchreichen – kein Absturz.
        if isinstance(exc, HTTPException):
            return exc

        log.exception("Unerwarteter Fehler bei %s %s", request.method, request.path)
        klasse = exc.__class__.__name__
        if request.is_json or not request.accept_mimetypes.accept_html:
            return jsonify({"error": klasse, "meldung": str(exc)[:300]}), 500
        return render_template("fehler.html", klasse=klasse,
                               meldung=str(exc)[:300], pfad=request.path), 500
