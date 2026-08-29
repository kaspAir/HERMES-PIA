"""Nachschlagewerte der Invarianten-Prüfung – und die konfigurierbaren Schwellen.

Alles hier ist Konfiguration, keine Logik: Rollenkatalog, Pflichtergebnisse der
Phase Initialisierung, Reihenfolgeregeln, Risikoskala, Platzhaltertexte.

Die Schwellen stammen aus dem Umsetzungs-Briefing (Abschnitt 4.2, «Was vorher zu
entscheiden ist»). Sie sind bewusst hier gebündelt und nicht in den Regeln
verstreut – sie werden sich mit der Praxis ändern.
"""

# ---- Konfigurierbare Schwellen ------------------------------------------- #
# Rundungstoleranzen: ohne sie schlagen D-001/D-002 grundlos an.
TOLERANZ_PT = 0.5              # Personentage
TOLERANZ_KOSTEN = 50.0         # CHF
# D-055: Zeit für Review und Freigabe zwischen Lieferung und Meilenstein.
MINDESTABSTAND_ARBEITSTAGE = 10
# D-056: Umrechnung Phasendauer -> Arbeitstage (5 Tage je Woche).
ARBEITSTAGE_PRO_WOCHE = 5

# ---- Rollenkatalog (D-007, D-040, D-053) --------------------------------- #
# HERMES-2022-Standardrollen. Mandantenspezifische Rollen kommen später aus der
# Organisationskonfiguration dazu – die Prüfung nimmt sie über `zusatzrollen` an.
HERMES_ROLLEN = {
    "auftraggeber", "projektleiter", "projektleiterin", "projektausschuss",
    "qualitäts- und risikomanager", "qualitaets- und risikomanager",
    "isds-verantwortlicher", "isds-verantwortliche", "isds",
    "anwendervertreter", "anwendervertreterin", "fachverantwortlicher",
    "fachverantwortliche", "business analyst", "entwickler", "entwicklerin",
    "it-architekt", "it-architektin", "testverantwortlicher", "testmanager",
    "betriebsverantwortlicher", "projektunterstützung", "projektunterstuetzung",
    "externe expertise", "externer berater", "externe beraterin", "extern",
    "lieferant", "auftragnehmer", "steuerungsgremium ablehnen",  # s.u. D-005
}
# Wörter, die eine Rollenangabe generisch machen (dann ist es KEIN Personenname).
_ROLLENWOERTER = ("leiter", "leiterin", "verantwortlich", "vertreter", "manager",
                  "experte", "expertin", "berater", "beraterin", "analyst",
                  "architekt", "entwickler", "auftraggeber", "ausschuss",
                  "gremium", "team", "stelle", "amt", "abteilung", "extern",
                  "intern", "unterstützung", "unterstuetzung", "isds", "pmo")


def ist_rolle(wert, zusatzrollen=None):
    """Sieht der Wert nach einer Rolle aus (statt nach einem Personennamen)?

    Bewusst grosszügig: D-007 ist nur ein Hinweis. Ein Fehlalarm auf einer
    korrekten Rollenbezeichnung kostet mehr Vertrauen als eine übersehene
    Namensnennung (Katalog Abschnitt 11).
    """
    w = (wert or "").strip().lower()
    if not w:
        return True                       # Leeres prüft eine andere Regel
    if w in HERMES_ROLLEN or w in {z.lower() for z in (zusatzrollen or [])}:
        return True
    return any(t in w for t in _ROLLENWOERTER)


# ---- Pflichtergebnisse der Phase Initialisierung (D-050) ----------------- #
# ACHTUNG (Katalog Abschnitt 11): KEIN Phasenbericht – den gibt es in der
# Initialisierung nicht. Und die Projektinitialisierungsfreigabe ist der START
# der Phase, kein Ergebnis daraus.
PFLICHTERGEBNISSE = [
    ("Stakeholderliste", ("stakeholder",)),
    ("Studie", ("studie",)),
    ("Rechtsgrundlagenanalyse", ("rechtsgrundlagen",)),
    ("Schutzbedarfsanalyse", ("schutzbedarf",)),
    ("Projektmanagementplan", ("projektmanagementplan", "pmp")),
    ("Durchführungsauftrag", ("durchführungsauftrag", "durchfuehrungsauftrag")),
]
# Nur Pflicht, wenn eine Beschaffung vorgesehen ist (bedingte Regel).
BESCHAFFUNG_ERGEBNIS = ("Beschaffungsanalyse", ("beschaffung",))

# ---- Meilensteine (D-051) ------------------------------------------------ #
MEILENSTEINE = [
    ("Weiteres Vorgehen", ("weiteres vorgehen",)),
    ("Durchführungsfreigabe", ("durchführungsfreigabe", "durchfuehrungsfreigabe")),
]
# Diese Zeile gehört NICHT in die Ergebnisliste (Katalog Abschnitt 11).
KEIN_ERGEBNIS = ("projektinitialisierungsfreigabe", "phasenbericht")

# ---- Reihenfolge (D-054) ------------------------------------------------- #
# (vorher, nachher) – jeweils über die Stichwörter oben identifiziert.
REIHENFOLGE = [
    ("rechtsgrundlagen", "studie"),
    ("schutzbedarf", "studie"),
    ("beschaffung", "studie"),
    ("studie", "weiteres vorgehen"),
    ("projektmanagementplan", "durchführungsauftrag"),
    ("durchführungsauftrag", "durchführungsfreigabe"),
]

# ---- Risikoskala (D-072) ------------------------------------------------- #
RISIKO_STUFE = {"tief": 1, "mittel": 2, "hoch": 3}

# ---- Zielarten (D-030, D-031, D-032) ------------------------------------- #
SYSTEMZIEL = ("system",)
VORGEHENSZIEL = ("vorgehen",)

# ---- Vorlagen-Platzhalter (D-003, D-011) --------------------------------- #
PLATZHALTER = (
    "auswählen", "auswaehlen", "wählen sie ein element aus",
    "wahlen sie ein element aus", "projektname / projektnummer",
    "klicken sie hier, um text einzugeben",
)
# «tt.mm.jjjj» ist in den Zeilen fuer Pruefung und Freigabe ZULAESSIG – sie
# werden erst dann ausgefuellt. Im Baseline-Lauf war das die haeufigste
# Fehlmeldung (Katalog Abschnitt 11).
DATUM_PLATZHALTER = "tt.mm.jjjj"
LEERZEILE = "…"                  # nur als ALLEINIGER Zellinhalt ein Befund

# ---- Nicht-HERMES-Begriffe (D-005) --------------------------------------- #
# Begriffe, die NUR in einem Dokument der Initialisierung falsch sind. Die
# Liste Projektentscheide Steuerung fuehrt bewusst das ganze Projekt auf - in
# der Konzept- und Realisierungsphase ist ein Phasenbericht ein richtiges
# HERMES-Ergebnis. Die Regel document-weit anzuwenden hiess, einer Vorlage
# einen Fehler vorzuwerfen, den sie nicht macht.
NUR_INITIALISIERUNG = ("phasenbericht",)

NICHT_HERMES = {
    "steuerungsausschuss": "Projektausschuss",
    "lenkungsausschuss": "Projektausschuss",
    "steuerungsgremium": "Projektausschuss",
    "projektauftrag": "Durchführungsauftrag",
    "phasenbericht": "(in der Initialisierung nicht vorgesehen)",
}


def enthaelt(text, stichwoerter):
    t = (text or "").lower()
    return any(s in t for s in stichwoerter)
