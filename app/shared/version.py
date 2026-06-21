"""Ermittelt die laufende Code-Version fuer die Anzeige im Browser.

Liest den aktuellen Git-Commit aus dem Repo (SHA, Datum, Subject). Da der
Deploy per `git reset --hard origin/test` arbeitet, ist .git auf dem Server
vorhanden – der kurze SHA laesst sich direkt mit GitHub abgleichen.

Wird einmal je Prozess ermittelt und zwischengespeichert; nach einem Deploy
startet Gunicorn neu, also ist der Wert immer aktuell.
"""
import subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_cache = None


def _git(*args):
    try:
        out = subprocess.check_output(
            ["git", "-C", str(_ROOT), *args],
            stderr=subprocess.DEVNULL,
            timeout=3,
        )
        return out.decode("utf-8", "replace").strip()
    except Exception:
        return ""


def get_version():
    """Gibt {sha, date, subject} des laufenden Commits zurueck (gecacht)."""
    global _cache
    if _cache is None:
        _cache = {
            "sha": _git("rev-parse", "--short", "HEAD") or "unbekannt",
            "date": _git("log", "-1", "--format=%cd", "--date=format:%Y-%m-%d %H:%M"),
            "subject": _git("log", "-1", "--format=%s"),
        }
    return _cache
