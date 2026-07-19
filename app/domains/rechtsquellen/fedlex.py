"""Fedlex-Connector: verknüpft Suchbegriffe mit Bundeserlassen (SR).

Arbeitet OFFLINE gegen einen mitgelieferten SR-Index (data/fedlex_sr_de.json.gz,
einmalig aus dem offiziellen Fedlex-SPARQL geholt – siehe scripts/refresh_fedlex_index.py).
So funktioniert das Grounding auf JEDEM Host, ohne Live-Netzwerk – der Managed-Host
erreicht den Fedlex-Dienst nicht. Liefert echte SR-Nummer + offizieller Titel +
Fedlex-Permalink. Nichts wird geraten: kein Treffer -> keine Fundstelle.
"""
import gzip
import json
import logging
import re
from pathlib import Path

log = logging.getLogger("hermes.fedlex")

_INDEX_PATH = Path(__file__).resolve().parent / "data" / "fedlex_sr_de.json.gz"
_INDEX_CACHE = None


def _load_offline_index():
    """Lädt den mitgelieferten SR-Index (gecacht). Leere Liste, falls Datei fehlt."""
    global _INDEX_CACHE
    if _INDEX_CACHE is None:
        try:
            with gzip.open(_INDEX_PATH, "rt", encoding="utf-8") as f:
                _INDEX_CACHE = json.load(f)
            log.info("Fedlex-SR-Index geladen: %d Erlasse", len(_INDEX_CACHE))
        except Exception as e:  # noqa: BLE001 – ohne Index einfach kein Grounding
            log.warning("Fedlex-SR-Index nicht ladbar: %s", e)
            _INDEX_CACHE = []
    return _INDEX_CACHE


def _sanitize(term):
    """Nur unbedenkliche Zeichen; Bindestrich bleibt (z.B. 'DNA-Profil-Gesetz')."""
    return re.sub(r"[^a-zäöüéèàç0-9 -]", "", (term or "").lower()).strip()


class FedlexClient:
    def __init__(self, index=None):
        # index optional (Tests); sonst wird der mitgelieferte Offline-Index geladen.
        self._index = index

    def _get_index(self):
        if self._index is None:
            self._index = _load_offline_index()
        return self._index

    def suche_mehrere(self, begriffe, treffer_je_begriff=1):
        """{begriff: [{sr, titel, url}]} – je Begriff die Treffer mit der KÜRZESTEN
        SR-Nummer (i.d.R. der Haupterlass). Wortgrenzen, damit 'DSG' nicht in
        'GerichtsstanDSGesetz' matcht. Leeres Dict bei leerer Eingabe/ohne Index."""
        index = self._get_index()
        if not index:
            return {}
        ergebnis = {}
        for original in (begriffe or []):
            t = _sanitize(original)
            if len(t) < 3:
                continue
            wort = re.compile(r"\b" + re.escape(t) + r"\b", re.IGNORECASE)
            passend = [e for e in index if wort.search(e.get("titel", ""))]
            passend.sort(key=lambda e: (len(e.get("sr", "")), e.get("sr", "")))
            if passend:
                ergebnis[original] = [
                    {"sr": e["sr"], "titel": e["titel"], "url": e.get("url", "")}
                    for e in passend[:treffer_je_begriff]
                ]
        return ergebnis
