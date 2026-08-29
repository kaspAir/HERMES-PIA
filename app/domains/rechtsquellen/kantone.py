"""Kuratierte Linksammlung der offiziellen kantonalen Gesetzessammlungen.

Es gibt für die Kantone keinen einheitlichen, maschinenlesbaren Gesamt-Index wie
Fedlex (Bund). Deshalb: pro Kanton der Link zur offiziellen systematischen
Gesetzessammlung. Kantonale Gesetze werden in der Rechtsgrundlagenanalyse mit
diesem Link versehen (statt einer erfundenen Nummer). URLs am 2026-07-19 per HTTP
verifiziert (TI blockt Bots, URL stimmt; SZ ohne direkte Sammlungs-URL -> Kanton).
"""

KANTON_SAMMLUNG = {
    "AG": {"name": "Aargau", "url": "https://gesetzessammlungen.ag.ch/"},
    "AI": {"name": "Appenzell Innerrhoden", "url": "https://ai.clex.ch/"},
    "AR": {"name": "Appenzell Ausserrhoden", "url": "https://ar.clex.ch/"},
    "BE": {"name": "Bern", "url": "https://www.belex.sites.be.ch/"},
    "BL": {"name": "Basel-Landschaft", "url": "https://bl.clex.ch/"},
    "BS": {"name": "Basel-Stadt", "url": "https://www.gesetzessammlung.bs.ch/"},
    "FR": {"name": "Freiburg", "url": "https://bdlf.fr.ch/"},
    "GE": {"name": "Genf", "url": "https://www.ge.ch/legislation-genevoise"},
    "GL": {"name": "Glarus", "url": "https://gesetze.gl.ch/"},
    "GR": {"name": "Graubünden", "url": "https://www.gr-lex.gr.ch/"},
    "JU": {"name": "Jura", "url": "https://rsju.jura.ch/"},
    "LU": {"name": "Luzern", "url": "https://srl.lu.ch/"},
    "NE": {"name": "Neuenburg", "url": "https://rsn.ne.ch/"},
    "NW": {"name": "Nidwalden", "url": "https://gesetze.nw.ch/"},
    "OW": {"name": "Obwalden", "url": "https://gdb.ow.ch/"},
    "SG": {"name": "St. Gallen", "url": "https://www.gesetzessammlung.sg.ch/"},
    "SH": {"name": "Schaffhausen", "url": "https://rechtsbuch.sh.ch/"},
    "SO": {"name": "Solothurn", "url": "https://bgs.so.ch/"},
    "SZ": {"name": "Schwyz", "url": "https://www.sz.ch/"},
    "TG": {"name": "Thurgau", "url": "https://www.rechtsbuch.tg.ch/"},
    "TI": {"name": "Tessin", "url": "https://www3.ti.ch/CAN/RLeggi/"},
    "UR": {"name": "Uri", "url": "https://www.ur.ch/dienstleistungen/3876"},
    "VD": {"name": "Waadt", "url": "https://prestations.vd.ch/pub/blv-publication/"},
    "VS": {"name": "Wallis", "url": "https://lex.vs.ch/"},
    "ZG": {"name": "Zug", "url": "https://bgs.zg.ch/"},
    "ZH": {"name": "Zürich",
           "url": "https://www.zh.ch/de/politik-staat/gesetze-beschluesse/gesetzessammlung.html"},
}


# Amtssprachen je Kanton, in der Reihenfolge, in der gesucht werden soll.
# Angabe vom Nutzer, mit der Sprachenkarte der Schweiz abgeglichen. Sie steht
# hier und nicht im Messskript, weil sie das Verhalten bestimmt: Wer einen
# Genfer Erlass mit einem deutschen Begriff sucht, findet ihn nicht - die
# lateinischen Kantone fuehren ihre Gesetze nur in ihrer Sprache.
KANTON_SPRACHEN = {
    # Hauptsprache Franzoesisch
    "GE": ("fr",), "VD": ("fr",), "NE": ("fr",), "JU": ("fr",),
    "FR": ("fr", "de"),          # zweisprachig, Hauptsprache Franzoesisch
    # Zweisprachig, Hauptsprache Deutsch
    "BE": ("de", "fr"), "VS": ("de", "fr"),
    # Hauptsprache Italienisch
    "TI": ("it",),
    # Dreisprachig, Hauptsprache Deutsch
    "GR": ("de", "it", "rm"),
}
# Alle uebrigen Kantone: Deutsch.
STANDARDSPRACHEN = ("de",)


# Bundesrecht erscheint dreisprachig (DE / FR / IT). Alle drei Fassungen sind
# gleichermassen verbindlich - und ihre Auslegung kann auseinandergehen. Fuer
# die Fundstellenpruefung heisst das: Es genuegt nicht, einen Artikel zu
# belegen; es muss dastehen, WELCHE Sprachfassung geprueft wurde. Englische
# Fassungen gibt es, sie sind aber nicht verbindlich und bleiben aussen vor.
BUND_SPRACHEN = ("de", "fr", "it")


def sprachen(kanton_code):
    """Amtssprachen eines Kantons, wichtigste zuerst."""
    return KANTON_SPRACHEN.get((kanton_code or "").upper(), STANDARDSPRACHEN)


def sprachen_fuer_namen(name):
    """Dieselbe Auskunft ueber den Kantonsnamen statt das Kuerzel."""
    gesucht = (name or "").strip().lower()
    for code, eintrag in KANTON_SAMMLUNG.items():
        if eintrag["name"].lower() == gesucht or code.lower() == gesucht:
            return sprachen(code)
    return STANDARDSPRACHEN


def sammlung_link(kanton_code):
    """Link zur offiziellen Gesetzessammlung eines Kantons – oder None."""
    eintrag = KANTON_SAMMLUNG.get((kanton_code or "").upper())
    return eintrag["url"] if eintrag else None
