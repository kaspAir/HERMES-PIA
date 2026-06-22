import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


class Config:
    DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///methodos.db")
    SQL_ECHO = os.environ.get("SQL_ECHO", "0") == "1"
    DEBUG = os.environ.get("FLASK_DEBUG", "0") == "1"
    SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "dev-only-change-in-prod")

    # Wo Methoden-Modelle und Kataloge liegen (Konfiguration vor Programmierung).
    METHODS_DIR = BASE_DIR / "methods"
    CATALOGS_DIR = BASE_DIR / "catalogs"

    # LLM
    ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
    LLM_MODEL = os.environ.get("METHODOS_LLM_MODEL", "claude-sonnet-4-6")

    # Betreiber-Account (Super-Admin) – via .env / Umgebungsvariablen setzen.
    SUPERADMIN_EMAIL = os.environ.get("METHODOS_SUPERADMIN_EMAIL", "")
    SUPERADMIN_PASSWORD = os.environ.get("METHODOS_SUPERADMIN_PASSWORD", "")


def get_config():
    return Config
