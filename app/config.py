import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _env(*names, default=""):
    """Erste gesetzte Umgebungsvariable aus 'names'. Erlaubt rückwärtskompatible
    Aliasse (neuer Name zuerst, alter Name als Fallback)."""
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return default


class Config:
    DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///hermespia.db")
    SQL_ECHO = os.environ.get("SQL_ECHO", "0") == "1"
    DEBUG = os.environ.get("FLASK_DEBUG", "0") == "1"
    SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "dev-only-change-in-prod")

    # Wo Methoden-Modelle und Kataloge liegen (Konfiguration vor Programmierung).
    METHODS_DIR = BASE_DIR / "methods"
    CATALOGS_DIR = BASE_DIR / "catalogs"

    # LLM
    ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
    LLM_MODEL = _env("HERMESPIA_LLM_MODEL", "METHODOS_LLM_MODEL", default="claude-sonnet-4-6")

    # Betreiber-Account (Super-Admin) – via .env / Umgebungsvariablen setzen.
    # Neuer Name HERMESPIA_*, alter Name METHODOS_* bleibt als Fallback gültig.
    SUPERADMIN_EMAIL = _env("HERMESPIA_SUPERADMIN_EMAIL", "METHODOS_SUPERADMIN_EMAIL")
    SUPERADMIN_PASSWORD = _env("HERMESPIA_SUPERADMIN_PASSWORD", "METHODOS_SUPERADMIN_PASSWORD")

    # RAG / Wissenskorpus (Voyage-Embeddings über die REST-API, kein neues pip-Paket).
    # Ohne Key bleibt das RAG inaktiv (Ingest/Suche liefern leer) – sicher fürs Deployment.
    VOYAGE_API_KEY = os.environ.get("VOYAGE_API_KEY", "")
    VOYAGE_MODEL = os.environ.get("VOYAGE_MODEL", "voyage-3")

    # Speech-to-Text (Meeting mithören). OpenAI-kompatibler Endpoint -> frei wählbar
    # (OpenAI, Groq, Azure-OpenAI oder self-hosted/CH-gehostete Whisper-Instanz).
    # Ohne Key bleibt die Mithör-Funktion inaktiv.
    STT_API_URL = os.environ.get("STT_API_URL", "https://api.openai.com/v1/audio/transcriptions")
    STT_API_KEY = os.environ.get("STT_API_KEY", "")
    STT_MODEL = os.environ.get("STT_MODEL", "whisper-1")
    # Sprache des Diktats. Leer lassen = Parameter NICHT senden (manche Anbieter
    # deuten 'language' als Ziel-/Uebersetzungssprache statt als Erkennungshilfe).
    STT_LANGUAGE = os.environ.get("STT_LANGUAGE", "de")
    # Vokabular-Hinweis fuer Whisper ("initial prompt"): hebt die Erkennung von
    # Fachbegriffen deutlich (z.B. "Server/Services" statt "Saeure"). Anpassbar.
    STT_PROMPT = os.environ.get("STT_PROMPT", (
        "Diktat zu einem HERMES-Projekt der oeffentlichen Verwaltung. Fachbegriffe: "
        "Server, Serverraum, Services, Kunden, Cloud, Schnittstelle, Applikation, "
        "Fachanwendung, HERMES, Projektinitialisierungsauftrag, Initialisierung, Studie, "
        "Beschaffungsanalyse, Schutzbedarfsanalyse, Rechtsgrundlagenanalyse, ISDS, "
        "Datenschutz, Informationssicherheit, Meilenstein, Auftraggeber, Projektleiter, "
        "Stakeholder, Prototyp, Personentage, Durchfuehrungsauftrag."
    ))


def get_config():
    return Config
