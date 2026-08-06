"""Ermittelt die laufende Code-Version fuer die Anzeige im Browser.

Liest den aktuellen Git-Commit aus dem Repo (SHA, Datum, Subject). Da der
Deploy per `git reset --hard origin/<zweig>` arbeitet, ist .git auf dem Server
vorhanden – der kurze SHA laesst sich direkt mit GitHub abgleichen.

Wird einmal je Prozess ermittelt und zwischengespeichert; nach einem Deploy
startet Gunicorn neu, also ist der Wert immer aktuell.

**Warum die Produktversion aus der Commit-Nachricht kommt.** Sie stand hier
frueher als von Hand gepflegte Konstante. Vier Freigaben lang wurde die neue
Nummer nur in die Commit-Nachricht geschrieben und die Konstante vergessen –
das Abzeichen meldete V0.29.0, waehrend der Code von V0.32.1 lief. Es meldete
damit nicht etwa Unsinn, sondern genau das, was im Quelltext stand: zwei
Quellen fuer dieselbe Tatsache, und gepflegt wurde die andere.

Jetzt gibt es nur noch EINE Quelle – den Marker ``V<x.y.z>`` in der
Commit-Nachricht, der bei jeder Freigabe ohnehin gesetzt wird. Die Konstante
bleibt als Rueckfallwert fuer den Fall, dass kein Git-Repo danebenliegt (etwa
bei einer Auslieferung als Archiv). Sie kann dann veralten, aber sie kann die
Anzeige nicht mehr still verfaelschen, solange ein Repo da ist.
"""
import re
import subprocess
from pathlib import Path

# Rueckfallwert OHNE Git-Repo. Die massgebliche Nummer steht in der
# Commit-Nachricht (Marker "V<x.y.z>"), nicht hier.
PRODUCT_VERSION = "0.32.2"

# Der Marker, wie er in den Commit-Betreffzeilen steht: "... + V0.32.1".
_MARKER = re.compile(r"\bV(\d+\.\d+\.\d+)\b")

# So weit wird rueckwaerts gesucht, wenn die neuesten Nachrichten keinen
# Marker tragen (etwa nach Zwischencommits ohne Freigabe).
_TIEFE = 50

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


def produktversion_aus(betreffzeilen):
    """Die juengste Versionsnummer aus einer Liste von Commit-Betreffzeilen.

    Rein und ohne Git, damit sie sich pruefen laesst. Gibt ``""`` zurueck,
    wenn keine Zeile einen Marker traegt – dann greift der Rueckfallwert.
    """
    for zeile in betreffzeilen or []:
        treffer = _MARKER.search(zeile or "")
        if treffer:
            return treffer.group(1)
    return ""


def get_version():
    """Gibt {product, sha, date, subject} des laufenden Commits zurueck (gecacht)."""
    global _cache
    if _cache is None:
        verlauf = _git("log", f"-{_TIEFE}", "--format=%s").splitlines()
        _cache = {
            "product": produktversion_aus(verlauf) or PRODUCT_VERSION,
            "sha": _git("rev-parse", "--short", "HEAD") or "unbekannt",
            "date": _git("log", "-1", "--format=%cd", "--date=format:%Y-%m-%d %H:%M"),
            "subject": _git("log", "-1", "--format=%s"),
        }
    return _cache
