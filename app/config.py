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

    # LLM – ausschliesslich über die Pseudonymisierungsschicht.
    # HERMES PIA hat bewusst KEINEN eigenen Anbieterschlüssel mehr: der liegt im
    # Dienst. Solange die Anwendung einen eigenen Schlüssel besitzt, ist das
    # Umgehen der Schicht nur verboten, nicht unmöglich – und genau darauf kommt
    # es bei Verwaltungskunden an (ANBINDUNG.md 6.4).
    LLM_MODEL = _env("HERMESPIA_LLM_MODEL", "METHODOS_LLM_MODEL", default="claude-sonnet-4-6")

    # Pseudonymisierungsdienst. Nur über 127.0.0.1 erreichbar; Port je Stufe:
    # 8040 develop · 8041 test · 8042 integration · 8043 main.
    # Vorgabe bewusst LEER = kein LLM: ohne Dienst gibt es keinen Weg zum Anbieter.
    # Ein geratener Standard-Port würde bei fehlender .env stillschweigend ins
    # Leere laufen, statt die Fehlkonfiguration sichtbar zu machen.
    PSEUDO_BASIS_URL = os.environ.get("PSEUDO_BASIS_URL", "")
    PSEUDO_ANWENDUNG = os.environ.get("PSEUDO_ANWENDUNG", "hermes-pia")
    # Mandant INNERHALB der Anwendung. Es gibt bewusst keinen Standard im Dienst –
    # ein Vertipper darf nicht dazu führen, dass Zuordnungen im falschen Topf
    # landen. Sobald Organisationen durchgängig sind, tritt die org_id an die Stelle.
    PSEUDO_MANDANT = os.environ.get("PSEUDO_MANDANT", "standard")

    # Betreiber-Account (Super-Admin) – via .env / Umgebungsvariablen setzen.
    # Neuer Name HERMESPIA_*, alter Name METHODOS_* bleibt als Fallback gültig.
    SUPERADMIN_EMAIL = _env("HERMESPIA_SUPERADMIN_EMAIL", "METHODOS_SUPERADMIN_EMAIL")
    SUPERADMIN_PASSWORD = _env("HERMESPIA_SUPERADMIN_PASSWORD", "METHODOS_SUPERADMIN_PASSWORD")

    # RAG / Wissenskorpus (Voyage-Embeddings). Der Schlüssel liegt – wie beim Chat –
    # im Pseudonymisierungsdienst; ohne dessen Basis-URL bleibt das RAG inaktiv.
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
    # Vokabular- UND Stil-Hinweis fuer Whisper ("initial prompt").
    # WICHTIG, zwei Punkte:
    #  1. Bewusst sauber geschriebener deutscher FLIESSTEXT (Grossschreibung,
    #     Satzzeichen, Schweizer "ss") - Whisper uebernimmt den STIL des Prompts.
    #     Eine Stichwortliste fuehrt zu kleingeschriebener, zerhackter Ausgabe.
    #  2. Bewusst NUR generische HERMES-Methodenbegriffe, KEIN Fachgebiet. Das
    #     projektspezifische Vokabular kommt zur Laufzeit aus der Session dazu
    #     (siehe app/domains/stt/kontext.py) - so passt es fuer jeden Mandanten.
    STT_PROMPT = os.environ.get("STT_PROMPT", (
        "Dies ist ein Diktat zu einem Projekt der öffentlichen Verwaltung nach "
        "HERMES 2022. Besprochen werden die Ausgangslage, die Ziele, die "
        "Rahmenbedingungen, die Abgrenzungen, Risiken, Termine und der Aufwand in "
        "Personentagen. Beteiligt sind der Auftraggeber, die Projektleiterin und "
        "weitere Stakeholder. Ergebnisse der Phase Initialisierung sind unter anderem "
        "die Studie, die Rechtsgrundlagenanalyse, die Schutzbedarfsanalyse, die "
        "Beschaffungsanalyse und der Durchführungsauftrag."
    ))


def get_config():
    return Config
