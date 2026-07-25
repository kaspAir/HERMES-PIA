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
    # Erlassformen sind KEINE Suchbegriffe: sie passen auf beliebige Erlasse
    # derselben Form. Gemessen: «(Konkordat)» aus dem Namen des
    # Justizvollzugskonkordats traf die «Interkantonale Vereinbarung ueber die
    # computergestuetzte Zusammenarbeit» (NW 912.5) – ein voellig anderer Erlass,
    # der «Konkordat» nur als Stichwort fuehrt.
    "konkordat", "vereinbarung", "uebereinkommen", "übereinkommen", "konvention",
    "abkommen", "weisung", "erlass", "dekret", "beschluss", "statut", "ordnung",
    "verfassung",
}


def ist_bund(ebene):
    return "bund" in (ebene or "").lower()


def suchbegriffe(name):
    """Kandidaten-Suchbegriffe aus einem Gesetzesnamen: Abkürzung(en) in Klammern
    plus das längste signifikante Wort."""
    terms = []
    for klammer in re.findall(r"\(([^)]+)\)", name or ""):
        # «(Submissionsgesetz/-verordnung)» -> beide Teile einzeln. Frueher fiel
        # der ganze Klammerinhalt durchs Laengenlimit und ging verloren; seit die
        # Treffer gegen den Begriff geprueft werden, sind laengere Begriffe
        # ungefaehrlich (ein unpassender Treffer wird ohnehin verworfen).
        for teil in re.split(r"[/,;]", klammer):
            teil = teil.strip(" -–—")
            # Generische Teile («Verordnung», «Gesetz») NICHT als Begriff: sie
            # stehen in unzaehligen Titeln und wuerden die Trefferpruefung
            # aushebeln – jede beliebige Verordnung gaelte dann als Fundstelle.
            if 2 <= len(teil) <= 30 and teil.lower() not in _GENERISCH:
                terms.append(teil)
    woerter = re.findall(r"[A-Za-zÄÖÜäöü-]{5,}", name or "")
    signifikant = [w for w in woerter if w.lower() not in _GENERISCH]
    if signifikant:
        terms.append(max(signifikant, key=len))
    return terms


# Namen, die sich selbst als kantonal/kommunal ausweisen. Ein Bundestreffer waere
# dafuer per Definition falsch - gemessen: «Kantonale Datenschutzgesetzgebung»
# bekam SR 128.1 (Bundesverordnung) samt Fedlex-Link.
_EIGENE_EBENE = ("kantonal", "kantons", "kommunal", "gemeinde", "kant.")


def _nennt_eigene_ebene(name):
    return any(w in (name or "").lower() for w in _EIGENE_EBENE)


def erlassform(text):
    """'verordnung' | 'konkordat' | 'gesetz' | '' – die Erlassform.

    Wichtig, weil zu einem Sachgebiet fast immer BEIDES existiert (Strafregister:
    Gesetz SR 330, Verordnung SR 331). Die Auswahl «kürzeste SR-Nummer» trifft bei
    einer Verordnung deshalb systematisch das Gesetz – gemessen: «Verordnung über
    das Strafregister (StReV)» wurde mit SR 330 (dem GESETZ) belegt.
    """
    t = (text or "").lower()
    # 'Verordnung' zuerst prüfen: 'Bundesgesetz ... Verordnung' gibt es nicht,
    # aber 'Verordnung zum Gesetz über ...' sehr wohl.
    if "verordnung" in t or t.startswith("v ") or "reglement" in t:
        return "verordnung"
    # Konkordate/interkantonale Vereinbarungen sind eine EIGENE Form – gemessen
    # wurde «Konkordat über den Vollzug von Strafen und Massnahmen» mit dem
    # kantonalen «Gesetz über den Straf- und Massnahmenvollzug» (NW 273.3)
    # belegt. Trennt zugleich IVöB (Vereinbarung) von BöB (Bundesgesetz).
    if ("konkordat" in t or "vereinbarung" in t or "übereinkommen" in t
            or "uebereinkommen" in t or "konvention" in t or "abkommen" in t):
        return "konkordat"
    if "gesetz" in t or "ordnung" in t:
        return "gesetz"
    return ""


def _form_passt(name, titel):
    """Trägt der Treffer dieselbe Erlassform wie der gesuchte Name?

    Ohne erkennbare Form – im Namen ODER im Titel – keine Aussage (True).
    Sonst muss sie übereinstimmen: eine Verordnung ist nicht das Gesetz, ein
    Konkordat nicht das kantonale Gesetz zum selben Thema."""
    gesucht = erlassform(name)
    if not gesucht:
        return True
    gefunden = erlassform(titel)
    return (not gefunden) or gefunden == gesucht


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
                # Heisst der Erlass selbst «kantonal/kommunal», ist ein Bundes-
                # treffer keine Fundstelle, sondern ein Fehler.
                if _nennt_eigene_ebene(name) and (hit.get("entity") or "CH") == "CH":
                    continue
                # Formfremde Treffer sind keine Fundstelle, sondern ein Fehler.
                # Verwerfen statt hinten einsortieren – sonst bleibt der falsche
                # Treffer stehen, wenn er der einzige ist.
                if not _form_passt(name, hit.get("titel")):
                    continue
                kandidaten[hit["sr"]] = hit
        # Erlassform zuerst, DANN kürzeste Nummer: sonst gewinnt bei einer
        # Verordnung immer das (kürzer nummerierte) Gesetz.
        best = sorted(kandidaten.values(),
                      key=lambda k: (not _form_passt(name, k.get("titel")),
                                     len(k["sr"]), k["sr"]))
        if best:
            out[name] = best[0]
    return out
