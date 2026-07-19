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


def sammlung_link(kanton_code):
    """Link zur offiziellen Gesetzessammlung eines Kantons – oder None."""
    eintrag = KANTON_SAMMLUNG.get((kanton_code or "").upper())
    return eintrag["url"] if eintrag else None
