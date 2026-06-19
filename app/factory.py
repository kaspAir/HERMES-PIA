from flask import Flask

from app.config import get_config
from app.domains.catalog.service import CatalogService
from app.domains.interview.service import InterviewService
from app.domains.llm.client import LLMClient
from app.domains.method.service import MethodService
from app.shared.database import SessionLocal, init_engine
from app.shared.errors import register_error_handlers
from app.shared.logging import configure_logging, register_request_logging
from app.web.ui_routes import bp as ui_bp


def create_app(config_class=None):
    app = Flask(__name__)
    app.config.from_object(config_class or get_config())

    configure_logging(app)
    register_error_handlers(app)
    register_request_logging(app)

    init_engine(app.config["DATABASE_URL"], echo=app.config.get("SQL_ECHO", False))

    # Services aus der Konfiguration aufbauen ("Konfiguration vor Programmierung").
    app.method_service = MethodService(app.config["METHODS_DIR"])
    app.catalog_service = CatalogService(app.config["CATALOGS_DIR"])
    llm_client = LLMClient(
        api_key=app.config.get("ANTHROPIC_API_KEY"),
        model=app.config.get("LLM_MODEL"),
    )
    app.interview_service = InterviewService(
        app.method_service, app.catalog_service, llm_client
    )

    app.register_blueprint(ui_bp)

    @app.teardown_appcontext
    def remove_session(exception=None):
        SessionLocal.remove()

    return app
