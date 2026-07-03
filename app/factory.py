from flask import Flask
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from app.config import get_config
from app.domains.auth.service import AuthService
from app.domains.catalog.service import CatalogService
from app.domains.generation.service import GenerationService
from app.domains.interview.service import InterviewService
from app.domains.llm.client import LLMClient
from app.domains.method.service import MethodService
import app.domains.auth.models      # noqa: F401 – Tabellen registrieren
import app.domains.interview.models  # noqa: F401 – ensures models are registered before create_all
import app.domains.corpus.models     # noqa: F401 – RAG-Korpus-Tabelle registrieren
import app.domains.projekt.models     # noqa: F401 – Projektstruktur-Tabellen registrieren
from app.domains.corpus.embeddings import VoyageEmbedder
from app.domains.corpus.service import RagService
from app.domains.projekt.service import ProjektService
from app.domains.stt.transcriber import Transcriber
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
        ("ergebnis_id",         "INTEGER"),
    ]
    with engine.connect() as conn:
        for col, dtype in new_cols:
            if col not in existing:
                conn.execute(text(f"ALTER TABLE interview_session ADD COLUMN {col} {dtype}"))
        conn.commit()


def _backfill_projekte(app):
    """Wickelt bestehende PIAs einmalig in die Projektstruktur ein.

    Über mehrere Gunicorn-Worker/Neustarts hinweg läuft das genau einmal: der
    Marker wird atomar über den Primärschlüssel beansprucht; wer ihn nicht
    setzen kann, überspringt die Migration.
    """
    from app.domains.interview.models import InterviewSession
    from app.domains.projekt.models import MigrationFlag

    db = SessionLocal()
    try:
        db.add(MigrationFlag(key="backfill_projekte_v1"))
        db.commit()
    except IntegrityError:
        db.rollback()
        return  # bereits durch einen anderen Worker/Boot erledigt
    unlinked = db.query(InterviewSession).filter(
        InterviewSession.ergebnis_id.is_(None)
    ).all()
    if unlinked:
        n = app.projekt_service.backfill_sessions(unlinked)
        app.logger.info("Projekt-Backfill: %s bestehende PIA(s) eingewickelt.", n)


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
    app.rag_service = RagService(VoyageEmbedder(
        api_key=app.config.get("VOYAGE_API_KEY"),
        model=app.config.get("VOYAGE_MODEL", "voyage-3"),
    ))
    app.interview_service = InterviewService(
        app.method_service, app.catalog_service, llm_client, rag=app.rag_service
    )
    app.generation_service = GenerationService(app.method_service)
    app.projekt_service = ProjektService()
    app.auth_service = AuthService()
    app.transcriber = Transcriber(
        api_url=app.config.get("STT_API_URL"),
        api_key=app.config.get("STT_API_KEY"),
        model=app.config.get("STT_MODEL", "whisper-1"),
    )

    # Betreiber-Account (Super-Admin) anlegen, falls per .env konfiguriert.
    app.auth_service.ensure_super_admin(
        app.config.get("SUPERADMIN_EMAIL"), app.config.get("SUPERADMIN_PASSWORD")
    )

    # Bestehende PIAs einmalig in die Projektstruktur einwickeln.
    _backfill_projekte(app)

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
