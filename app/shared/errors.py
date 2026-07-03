from flask import jsonify


class AppError(Exception):
    status_code = 400


def register_error_handlers(app):
    @app.errorhandler(AppError)
    def handle_app_error(exc):
        return jsonify({"error": str(exc)}), exc.status_code

    @app.errorhandler(404)
    def handle_404(_):
        return jsonify({"error": "not found"}), 404
