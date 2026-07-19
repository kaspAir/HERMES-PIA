"""Fedlex-Connector: sucht Bundeserlasse (SR) über den offiziellen SPARQL-Endpunkt.

Liefert zu Suchbegriffen echte, verifizierbare Fundstellen (SR-Nummer, Titel,
Fedlex-Permalink). Bei Netzwerk-/Endpunkt-/Parsingfehlern -> leeres Ergebnis:
es wird NIE eine Fundstelle geraten.
"""
import logging
import re

import requests

log = logging.getLogger("hermes.fedlex")

ENDPOINT = "https://fedlex.data.admin.ch/sparqlendpoint"
# Manche Endpunkte/Proxys weisen den Default-Python-User-Agent ab.
_HEADERS = {
    "Accept": "application/sparql-results+json",
    "User-Agent": "HERMES-PIA/1.0 (+https://hermespia.ch)",
}

# Deutsche Sprach-URI in den Fedlex-Daten.
_LANG_DE = "http://publications.europa.eu/resource/authority/language/DEU"

_SPARQL = """PREFIX jolux: <http://data.legilux.public.lu/resource/ontology/jolux#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
SELECT DISTINCT ?sr ?title ?cons WHERE {{
  ?cons a jolux:ConsolidationAbstract ;
        jolux:classifiedByTaxonomyEntry/skos:notation ?sr ;
        jolux:isRealizedBy ?expr .
  ?expr jolux:language <%s> ;
        jolux:title ?title .
  FILTER(REGEX(LCASE(STR(?title)), "{muster}"))
}} LIMIT {limit}""" % _LANG_DE


def _permalink(cons_uri):
    """Wandelt die Daten-URI in den öffentlichen Fedlex-Permalink (deutsch)."""
    if not cons_uri:
        return ""
    return cons_uri.replace("fedlex.data.admin.ch", "www.fedlex.admin.ch") + "/de"


def _sanitize(term):
    """Nur unbedenkliche Zeichen in den Regex-Filter lassen (kein Injection-Risiko).
    Bindestrich bleibt erhalten (z.B. 'DNA-Profil-Gesetz')."""
    return re.sub(r"[^a-zäöüéèàç0-9 -]", "", (term or "").lower()).strip()


class FedlexClient:
    def __init__(self, endpoint=ENDPOINT, timeout=20):
        self.endpoint = endpoint
        self.timeout = timeout

    # Für Tests überschreibbar: liefert die rohen SPARQL-Bindings.
    def _fetch(self, sparql):
        r = requests.get(
            self.endpoint, params={"query": sparql},
            headers=_HEADERS, timeout=self.timeout,
        )
        r.raise_for_status()
        return r.json().get("results", {}).get("bindings", [])

    def suche_mehrere(self, begriffe, treffer_je_begriff=1, limit=200):
        """Ein SPARQL-Aufruf für mehrere Begriffe (Regex-Alternation).

        Rückgabe: {begriff: [{sr, titel, url}]} – je Begriff die Treffer mit der
        KÜRZESTEN SR-Nummer (i.d.R. der Haupterlass, nicht die Ausführungsverordnung).
        Leeres Dict bei Störung – nie geraten.
        """
        terms = [t for t in {_sanitize(b) for b in (begriffe or [])} if len(t) >= 3]
        if not terms:
            return {}
        muster = "(" + "|".join(re.escape(t) for t in terms) + ")"
        try:
            bindings = self._fetch(_SPARQL.format(muster=muster, limit=limit))
            log.info("Fedlex-Abfrage ok: %d Begriffe, %d Roh-Treffer", len(terms), len(bindings))
        except Exception as e:  # noqa: BLE001 – jede Störung -> keine Treffer (kein Raten)
            log.warning("Fedlex nicht erreichbar/Abfrage fehlgeschlagen (%s): %s",
                        type(e).__name__, e)
            return {}

        # Alle Treffer sammeln, je SR nur einmal.
        eintraege = {}
        for b in bindings:
            sr = (b.get("sr") or {}).get("value", "").strip()
            titel = (b.get("title") or {}).get("value", "").strip()
            uri = (b.get("cons") or {}).get("value", "")
            if sr and titel and sr not in eintraege:
                eintraege[sr] = {"sr": sr, "titel": titel, "url": _permalink(uri)}

        # Treffer den Originalbegriffen zuordnen – mit WORTGRENZEN, damit z.B. 'DSG'
        # nicht faelschlich in 'GerichtsstanDSGesetz' matcht.
        ergebnis = {}
        for original in (begriffe or []):
            t = _sanitize(original)
            if len(t) < 3:
                continue
            wort = re.compile(r"\b" + re.escape(t) + r"\b", re.IGNORECASE)
            passend = [e for e in eintraege.values() if wort.search(e["titel"])]
            passend.sort(key=lambda e: (len(e["sr"]), e["sr"]))
            if passend:
                ergebnis[original] = passend[:treffer_je_begriff]
        return ergebnis
