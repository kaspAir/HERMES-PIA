"""Entscheid zu einer Fundstelle der Pseudonymisierungsschicht.

Der Klartext (`muster`) wird MITGESCHICKT, nicht beim Dienst nachgeschlagen --
der speichert ihn nicht. Er wird dort gegen einen HMAC geprueft; wer den Klartext
nicht kennt, kann den Befund nicht entscheiden (ANBINDUNG.md 5).
"""
import requests

from app.domains.llm.errors import PseudoNichtErreichbar

ERSETZEN = "ersetzen"        # echter Personenbezug
FREIGEBEN = "freigeben"      # Fehlalarm: Firmen- oder Systemname


def entscheide(basis_url, befund_id, entscheid, muster, begruendung="", urheber="",
               timeout=20):
    """Sendet den Entscheid. Rueckgabe: (ok, meldung)."""
    if entscheid not in (ERSETZEN, FREIGEBEN):
        return False, f"Unbekannter Entscheid: {entscheid}"
    url = f"{(basis_url or '').rstrip('/')}/pseudo/v1/befunde/{befund_id}/entscheid"
    try:
        resp = requests.post(url, json={
            "entscheid": entscheid,
            "muster": muster,
            "begruendung": begruendung,
            "urheber": urheber,
        }, timeout=timeout)
    except requests.RequestException as e:
        raise PseudoNichtErreichbar(
            f"Pseudonymisierungsdienst nicht erreichbar ({e.__class__.__name__})."
        ) from e
    if resp.status_code == 200:
        return True, ""
    try:
        fehler = (resp.json() or {}).get("error", {}) or {}
    except ValueError:
        fehler = {}
    # Haeufigster Fall: der Klartext passt nicht zum Befund (400 muster_passt_nicht).
    return False, fehler.get("message") or f"HTTP {resp.status_code}"
