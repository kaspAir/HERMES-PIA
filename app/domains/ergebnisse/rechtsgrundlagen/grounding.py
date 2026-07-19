"""Grounding der im PIA genannten Bundesgesetze gegen Fedlex (Phase B, Bund).

Ordnet jedem Gesetzesnamen – sofern Bundesebene und auffindbar – die verifizierte
Fundstelle zu (SR-Nummer, offizieller Titel, Fedlex-Permalink). Nichts wird geraten:
ohne Treffer bleibt das Gesetz ungegroundet.
"""
import re

# Generische Bestandteile von Gesetzesnamen, die als Suchbegriff untauglich sind.
_GENERISCH = {
    "bundesgesetz", "gesetz", "verordnung", "reglement", "bundesbeschluss",
    "über", "ueber", "den", "die", "das", "der", "vom", "und", "zur", "zum",
    "von", "im", "in", "betreffend", "schweizerische", "schweizerisches",
    "schweizerischen", "kantonale", "kantonales", "kantonaler", "eidgenössische",
    "richtlinie", "strategie", "konzept", "verwendung", "identifizierung",
}


def ist_bund(ebene):
    return "bund" in (ebene or "").lower()


def suchbegriffe(name):
    """Kandidaten-Suchbegriffe aus einem Gesetzesnamen: Abkürzung(en) in Klammern
    plus das längste signifikante Wort."""
    terms = []
    for abk in re.findall(r"\(([^)]+)\)", name or ""):
        abk = abk.strip()
        if 2 <= len(abk) <= 14:
            terms.append(abk)
    woerter = re.findall(r"[A-Za-zÄÖÜäöü-]{5,}", name or "")
    signifikant = [w for w in woerter if w.lower() not in _GENERISCH]
    if signifikant:
        terms.append(max(signifikant, key=len))
    return terms


def ground_federal(namen, ebene, client):
    """{name -> {sr, titel, url}} für die auf Bundesebene auffindbaren Gesetze.
    Leeres Dict, wenn nicht Bundesebene / kein Client / kein Treffer."""
    if not client or not ist_bund(ebene) or not namen:
        return {}
    begriffe_je_name = {n: suchbegriffe(n) for n in namen}
    alle = [t for terms in begriffe_je_name.values() for t in terms]
    if not alle:
        return {}
    treffer = client.suche_mehrere(alle)          # {begriff: [{sr,titel,url}]}
    out = {}
    for name, terms in begriffe_je_name.items():
        kandidaten = {}
        for t in terms:
            for hit in treffer.get(t, []):
                kandidaten[hit["sr"]] = hit
        best = sorted(kandidaten.values(), key=lambda k: (len(k["sr"]), k["sr"]))
        if best:
            out[name] = best[0]
    return out
