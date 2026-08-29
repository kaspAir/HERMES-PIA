from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, scoped_session, sessionmaker

Base = declarative_base()
SessionLocal = scoped_session(sessionmaker(autoflush=False, autocommit=False))

_engine = None


def init_engine(database_url, echo=False):
    """Die Datenbank-Verbindung – bei SQLite auf MEHRERE Prozesse eingestellt.

    Mit einem einzigen Worker ist gleichzeitiges Schreiben unmoeglich, und
    genau darauf stand hier nichts. SQLite bringt von Haus aus
    `journal_mode=delete` mit (ein Schreiber sperrt ALLE Leser) und ein
    Wartelimit von 5 s; danach fliegt «database is locked». Sobald mehr als ein
    Worker laeuft, ist das der Normalfall und nicht die Ausnahme: das Interview
    schreibt bei jeder Antwort, die Kette bei jedem Schritt.

    Deshalb zwei Einstellungen, beide gemessen und beide noetig:
      * WAL – Leser und ein Schreiber koennen gleichzeitig arbeiten.
      * busy_timeout 30 s – ein Schreiber WARTET, statt sofort aufzugeben.
    `synchronous=NORMAL` gehoert zu WAL: volles Durchschreiben je Commit kostet
    bei jedem Interviewschritt eine Plattenumdrehung, ohne dass es hier etwas
    schuetzt, was WAL nicht schon schuetzt.
    """
    global _engine
    ist_sqlite = str(database_url).startswith("sqlite")
    zusatz = {"connect_args": {"timeout": 30}} if ist_sqlite else {}
    _engine = create_engine(database_url, echo=echo, future=True, **zusatz)

    if ist_sqlite:
        @event.listens_for(_engine, "connect")
        def _sqlite_einstellen(verbindung, _satz):   # noqa: ANN001
            zeiger = verbindung.cursor()
            zeiger.execute("PRAGMA journal_mode=WAL")
            zeiger.execute("PRAGMA synchronous=NORMAL")
            zeiger.execute("PRAGMA busy_timeout=30000")
            zeiger.close()

    SessionLocal.configure(bind=_engine)
    return _engine


def get_engine():
    return _engine


@contextmanager
def session_scope():
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
