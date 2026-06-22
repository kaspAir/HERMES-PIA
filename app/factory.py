from flask import Flask
from sqlalchemy import inspect, text

from app.config import get_config
from app.domains.auth.service import AuthService
from app.domains.catalog.service import CatalogService
from app.domains.generation.service import GenerationService
from app.domains.interview.service import InterviewService
from app.domains.llm.client import LLMClient
from app.domains.method.service import MethodService
import app.domains.auth.models      # noqa: F401 – Tabellen registrieren
import app.domains.interview.models  # noqa: F401 – ensures models are registered before create_all
from app.shared.database import Base, SessionLocal, init_engine
from app.shared.errors import register_error_handlers
from app.shared.logging import configure_logging, register_request_logging
from app.shared.version import get_version
from app.web.auth import current_user
from app.web.ui_routes import bp as ui_bp


def _migrate_db(engine):
    """Fügt fehlende Spalten zur interview_session-Tabelle hinzu (SQLite-kompatibel)."""
    inspector = inspect(engine)
    if "interview_session" not in inspector.get_table_names():
        return
    existing = {col["name"] for col in inspector.get_columns("interview_session")}
    new_cols = [
        ("projektnummer",       "VARCHAR(100)"),
        ("auftraggeber",        "VARCHAR(200)"),
        ("verwaltungseinheit",  "VARCHAR(200)"),
        ("doc_version",         "VARCHAR(20)"),
        ("changelog_json",      "TEXT"),
        ("last_snapshot_json",  "TEXT"),
        ("geschaeftsbereich",   "VARCHAR(200)"),
        ("innenauftragsnummer", "VARCHAR(100)"),
        ("start_datum",         "VARCHAR(20)"),
        ("org_id",              "INTEGER"),
    ]
    with engine.connect() as conn:
        for col, dtype in new_cols:
            if col not in existing:
                conn.execute(text(f"ALTER TABLE interview_session ADD COLUMN {col} {dtype}"))
        conn.commit()


def create_app(config_class=None):
    app = Flask(__name__)
    app.config.from_object(config_class or get_config())
    app.secret_key = app.config.get("SECRET_KEY", "dev-only-change-in-prod")

    configure_logging(app)
    register_error_handlers(app)
    register_request_logging(app)

    engine = init_engine(app.config["DATABASE_URL"], echo=app.config.get("SQL_ECHO", False))
    Base.metadata.create_all(engine)
    _migrate_db(engine)

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
    app.generation_service = GenerationService(app.method_service)
    app.auth_service = AuthService()

    # Betreiber-Account (Super-Admin) anlegen, falls per .env konfiguriert.
    app.auth_service.ensure_super_admin(
        app.config.get("SUPERADMIN_EMAIL"), app.config.get("SUPERADMIN_PASSWORD")
    )

    app.register_blueprint(ui_bp)

    # Laufende Code-Version + angemeldeter Benutzer in allen Templates verfügbar.
    app_version = get_version()

    @app.context_processor
    def inject_globals():
        return {"app_version": app_version, "current_user": current_user()}

    @app.teardown_appcontext
    def remove_session(exception=None):
        SessionLocal.remove()

    return app
