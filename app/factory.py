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
import app.domains.ergebnisse.models   # noqa: F401 – Ergebnis-Entwuerfe-Tabelle registrieren
import app.domains.qualitaet.models    # noqa: F401 – Pruefprotokoll-Tabelle registrieren
from app.domains.corpus.embeddings import VoyageEmbedder
from app.domains.corpus.service import RagService
from app.domains.praesentation.service import PraesentationService
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

    # methoden_vorlage: bestätigte Kapitel-Zuordnung (nachträglich ergänzt).
    if "methoden_vorlage" in inspector.get_table_names():
        mv_cols = {c["name"] for c in inspector.get_columns("methoden_vorlage")}
        if "mapping_json" not in mv_cols:
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE methoden_vorlage ADD COLUMN mapping_json TEXT"))
                conn.commit()

    # pia_pruefung: kapitelweiser Lauf (nachträglich ergänzt).
    if "pia_pruefung" in inspector.get_table_names():
        pp = {c["name"] for c in inspector.get_columns("pia_pruefung")}
        with engine.connect() as conn:
            for spalte, typ in (("status", "VARCHAR(20)"), ("schritt", "INTEGER"),
                                ("teilbefunde_json", "TEXT"),
                                ("nachschlag", "INTEGER"),
                                ("nachweis_json", "TEXT"),
                                ("konsolidiert_json", "TEXT")):
                if spalte not in pp:
                    conn.execute(text(
                        f"ALTER TABLE pia_pruefung ADD COLUMN {spalte} {typ}"))
            conn.commit()

    # ergebnis_entwurf: Laufzustand der Rechtsgrundlagen-Kette.
    if "ergebnis_entwurf" in inspector.get_table_names():
        ee = {c["name"] for c in inspector.get_columns("ergebnis_entwurf")}
        with engine.connect() as conn:
            for spalte, typ in (("lauf_status", "VARCHAR(20)"),
                                ("lauf_schritt", "INTEGER"),
                                ("lauf_json", "TEXT")):
                if spalte not in ee:
                    conn.execute(text(
                        f"ALTER TABLE ergebnis_entwurf ADD COLUMN {spalte} {typ}"))
            conn.commit()

    # corpus_chunks: strukturierte Initialisierungs-Dauer (nachträglich ergänzt).
    if "corpus_chunks" in inspector.get_table_names():
        cc_cols = {c["name"] for c in inspector.get_columns("corpus_chunks")}
        if "init_dauer_wochen" not in cc_cols:
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE corpus_chunks ADD COLUMN init_dauer_wochen INTEGER"))
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
    # Beide Wege – Chat UND Embeddings – laufen durch die Pseudonymisierungs-
    # schicht; der Anbieterschlüssel liegt dort, nicht hier.
    pseudo_url = (app.config.get("PSEUDO_BASIS_URL") or "").rstrip("/")
    pseudo_anwendung = app.config.get("PSEUDO_ANWENDUNG", "hermes-pia")
    pseudo_mandant = app.config.get("PSEUDO_MANDANT", "standard")
    # Ohne konfigurierten Dienst gibt es KEINEN LLM-Client – nicht etwa einen
    # Ausweichweg zum Anbieter. Die Anwendung arbeitet dann rein deterministisch,
    # genau wie früher ohne Anbieterschlüssel.
    # Direktmodus nur, wenn AUSDRUECKLICH verlangt UND ein Schluessel da ist.
    direkt_key = (app.config.get("ANTHROPIC_API_KEY", "")
                  if app.config.get("PSEUDO_UMGEHEN") else "")
    if pseudo_url:
        llm_client = LLMClient(
            basis_url=f"{pseudo_url}/anthropic",
            model=app.config.get("LLM_MODEL"),
            anwendung=pseudo_anwendung,
            mandant=pseudo_mandant,
        )
    elif direkt_key:
        app.logger.warning(
            "PSEUDONYMISIERUNG ABGESCHALTET (PSEUDO_UMGEHEN=1): LLM-Aufrufe gehen "
            "DIREKT an den Anbieter. Nur fuer die Entwicklung mit Testdaten.")
        llm_client = LLMClient(model=app.config.get("LLM_MODEL"), anbieter_key=direkt_key)
    else:
        llm_client = None
    app.rag_service = RagService(VoyageEmbedder(
        basis_url=f"{pseudo_url}/voyage" if pseudo_url else "",
        model=app.config.get("VOYAGE_MODEL", "voyage-3"),
        anwendung=pseudo_anwendung,
        mandant=pseudo_mandant,
    ) if pseudo_url else None)
    app.projekt_service = ProjektService()
    app.interview_service = InterviewService(
        app.method_service, app.catalog_service, llm_client, rag=app.rag_service,
        projekt_service=app.projekt_service,
    )
    app.generation_service = GenerationService(app.method_service)
    # Abgeleitete Initialisierungs-Ergebnisse (eigene Module, PIA unberührt).
    from app.domains.ergebnisse.rechtsgrundlagen.service import RechtsgrundlagenService
    # Live-Rechtsquellen-Recherche (lexfind: Bund + 26 Kantone). Abschaltbar, weil
    # es eine undokumentierte Fremd-API ist und die Suchbegriffe den Host verlassen.
    # Aus: nur der mitgelieferte Offline-SR-Index (Bundesrecht, ohne Aktualitaet).
    from app.domains.rechtsquellen.fedlex import FedlexClient
    from app.domains.rechtsquellen.lexfind import LexfindClient
    from app.domains.rechtsquellen.recherche import RechercheClient
    _index = FedlexClient()
    _recherche = RechercheClient(
        lexfind=LexfindClient() if app.config.get("RECHERCHE_LIVE") else None,
        index=_index,
    )
    app.rechtsgrundlagen_service = RechtsgrundlagenService(
        app.interview_service, app.projekt_service, app.generation_service, llm=llm_client,
        fedlex=_index, recherche=_recherche,
    )
    from app.domains.ergebnisse.schutzbedarf.service import SchutzbedarfService
    app.schutzbedarf_service = SchutzbedarfService(
        app.interview_service, app.projekt_service, app.config["METHODS_DIR"], llm=llm_client,
    )
    app.praesentation_service = PraesentationService(llm_client)
    app.auth_service = AuthService()
    app.transcriber = Transcriber(
        api_url=app.config.get("STT_API_URL"),
        api_key=app.config.get("STT_API_KEY"),
        model=app.config.get("STT_MODEL", "whisper-1"),
        language=app.config.get("STT_LANGUAGE", "de"),
        prompt=app.config.get("STT_PROMPT", ""),
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
        user = current_user()
        org = app.auth_service.get_org(user.org_id) if user and user.org_id else None
        branding = app.auth_service.get_branding(user.org_id) if user and user.org_id else None
        return {"app_version": app_version, "current_user": user,
                "current_org": org, "current_branding": branding,
                "stt_available": getattr(app.transcriber, "available", False)}

    @app.teardown_appcontext
    def remove_session(exception=None):
        SessionLocal.remove()

    return app
