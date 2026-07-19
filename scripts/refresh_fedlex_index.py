"""Aktualisiert den mitgelieferten Fedlex-SR-Index (data/fedlex_sr_de.json.gz).

Holt EINMALIG alle deutschen Bundeserlasse (SR-Nummer, Titel, Permalink) vom
offiziellen Fedlex-SPARQL-Endpunkt und speichert sie komprimiert. Zur Laufzeit
arbeitet HERMES PIA dann OFFLINE gegen diese Datei (der Managed-Host erreicht
Fedlex nicht). Aufruf:  python scripts/refresh_fedlex_index.py
"""
import gzip
import json
import sys
from pathlib import Path

import requests

ENDPOINT = "https://fedlex.data.admin.ch/sparqlendpoint"
OUT = Path(__file__).resolve().parent.parent / "app/domains/rechtsquellen/data/fedlex_sr_de.json.gz"

_QUERY = """PREFIX jolux: <http://data.legilux.public.lu/resource/ontology/jolux#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
SELECT ?sr (SAMPLE(?title) AS ?t) (SAMPLE(?cons) AS ?c) WHERE {
  ?cons a jolux:ConsolidationAbstract ;
        jolux:classifiedByTaxonomyEntry/skos:notation ?sr ;
        jolux:isRealizedBy ?expr .
  ?expr jolux:language <http://publications.europa.eu/resource/authority/language/DEU> ;
        jolux:title ?title .
} GROUP BY ?sr"""


def main():
    r = requests.get(
        ENDPOINT, params={"query": _QUERY},
        headers={"Accept": "application/sparql-results+json", "User-Agent": "HERMES-PIA/1.0"},
        timeout=180,
    )
    r.raise_for_status()
    rows = r.json()["results"]["bindings"]
    index = []
    for b in rows:
        sr = b["sr"]["value"].strip()
        titel = b["t"]["value"].strip()
        uri = b.get("c", {}).get("value", "")
        url = uri.replace("fedlex.data.admin.ch", "www.fedlex.admin.ch") + "/de" if uri else ""
        if sr and titel:
            index.append({"sr": sr, "titel": titel, "url": url})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(OUT, "wt", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False)
    print(f"Fedlex-SR-Index aktualisiert: {len(index)} Erlasse -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
