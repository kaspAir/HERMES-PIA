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


def ground_federal(namen, ebene=None, client=None, kanton=None):
    """{name -> {sr, titel, url}} für die als Bundeserlass auffindbaren Gesetze.

    Wird IMMER versucht (der Offline-Index kostet kein Netzwerk): Bundesrecht (z.B.
    StGB/StPO) gilt in jedem Kanton – auch bei rein kantonaler Ebene sollen die
    Bundesgesetze ihre echte SR-Fundstelle bekommen. `ebene` bleibt nur aus
    Kompatibilität. Leeres Dict, wenn kein Client / kein Treffer."""
    if not client or not namen:
        return {}
    begriffe_je_name = {n: suchbegriffe(n) for n in namen}
    alle = [t for terms in begriffe_je_name.values() for t in terms]
    if not alle:
        return {}
    # ebene/kanton steuern bei der Live-Recherche, WELCHE Sammlungen durchsucht
    # werden (Bund + ggf. der Kanton). Der Offline-Index ignoriert sie.
    treffer = client.suche_mehrere(alle, ebene=ebene, kanton=kanton)
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
