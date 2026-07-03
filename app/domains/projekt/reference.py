"""HERMES-Referenz-Katalog (die Methode) – Quelle der Struktur.

Hier steht *einmal*, wie die Phase Initialisierung aufgebaut ist (Module,
Meilensteine) und in welchem Modul / unter welcher Aufgabe / mit welcher Rolle
ein Ergebnistyp abgelegt wird. Kein `if` in der Logik – neue Ergebnistypen
werden hier eingetragen und landen automatisch im richtigen Modul.

Stand: Phase Initialisierung gemäss HERMES-Referenzhandbuch (Modul/Aufgabe/Rolle
je Ergebnis). Aktuell *erstellt* wird nur der Projektinitialisierungsauftrag;
die übrigen Typen sind bereits korrekt zugeordnet, damit sie sich später ohne
Umbau einstecken lassen.
"""

# ---- Module der Phase Initialisierung -------------------------------- #
MODUL_STEUERUNG = "projektsteuerung"
MODUL_FUEHRUNG = "projektfuehrung"
MODUL_GRUNDLAGEN = "projektgrundlagen"

# ---- Rollen ---------------------------------------------------------- #
ROLLE_AUFTRAGGEBER = "Auftraggeber"
ROLLE_PROJEKTLEITER = "Projektleiter"
ROLLE_ISDS = "ISDS-Verantwortlicher"
ROLLE_ANWENDERVERTRETER = "Anwendervertreter"
ROLLE_ENTWICKLER = "Entwickler"

# ---- Ergebnistypen (Konstanten für die heute genutzten) -------------- #
ERG_PIA = "projektinitialisierungsauftrag"

# ---- Phasen-Vorlage: Initialisierung --------------------------------- #
# Wird beim Anlegen eines Projekts instanziiert (Phase + Module + Meilensteine).
INITIALISIERUNG = {
    "code": "initialisierung",
    "name": "Initialisierung",
    "module": [
        {"code": MODUL_STEUERUNG, "name": "Projektsteuerung"},
        {"code": MODUL_FUEHRUNG, "name": "Projektführung"},
        {"code": MODUL_GRUNDLAGEN, "name": "Projektgrundlagen"},
    ],
    # Drei Entscheid-Meilensteine. Projektinitialisierungsfreigabe = Phasenstart
    # = geplanter Starttermin des Projekts (ist_start).
    "meilensteine": [
        {"code": "projektinitialisierungsfreigabe", "name": "Projektinitialisierungsfreigabe",
         "modul": MODUL_STEUERUNG, "rolle": ROLLE_AUFTRAGGEBER, "ist_start": True},
        {"code": "weiteres_vorgehen", "name": "Weiteres Vorgehen",
         "modul": MODUL_GRUNDLAGEN, "rolle": ROLLE_PROJEKTLEITER},
        {"code": "durchfuehrungsfreigabe", "name": "Durchführungsfreigabe",
         "modul": MODUL_STEUERUNG, "rolle": ROLLE_AUFTRAGGEBER},
    ],
}

# ---- Ergebnistyp-Katalog --------------------------------------------- #
# typ -> {name, modul, aufgabe, rolle}. Mehrfach-Ergebnisse (z.B. Durchführungs-
# auftrag wird in Projektführung erarbeitet und in Projektsteuerung entschieden)
# erhalten ein kanonisches Ablage-Modul (Erarbeitung) – feinjustierbar.
ERGEBNISTYPEN = {
    # --- Modul Projektsteuerung (Auftraggeber) ---
    ERG_PIA: {
        "name": "Projektinitialisierungsauftrag", "modul": MODUL_STEUERUNG,
        "aufgabe": "Entscheid Projektinitialisierungsfreigabe treffen",
        "rolle": ROLLE_AUFTRAGGEBER,
    },
    "checkliste_projektinitialisierungsfreigabe": {
        "name": "Checkliste Projektinitialisierungsfreigabe", "modul": MODUL_STEUERUNG,
        "aufgabe": "Entscheid Projektinitialisierungsfreigabe treffen",
        "rolle": ROLLE_AUFTRAGGEBER,
    },
    "liste_projektentscheide_steuerung": {
        "name": "Liste Projektentscheide Steuerung", "modul": MODUL_STEUERUNG,
        "aufgabe": "Projekt steuern", "rolle": ROLLE_AUFTRAGGEBER,
    },
    "checkliste_durchfuehrungsfreigabe": {
        "name": "Checkliste Durchführungsfreigabe", "modul": MODUL_STEUERUNG,
        "aufgabe": "Entscheid Durchführungsfreigabe treffen", "rolle": ROLLE_AUFTRAGGEBER,
    },
    # --- Modul Projektführung (Projektleiter) ---
    "projektmanagementplan": {
        "name": "Projektmanagementplan", "modul": MODUL_FUEHRUNG,
        "aufgabe": "Projektmanagementplan erarbeiten", "rolle": ROLLE_PROJEKTLEITER,
    },
    "arbeitsauftrag": {
        "name": "Arbeitsauftrag", "modul": MODUL_FUEHRUNG,
        "aufgabe": "Projekt führen und kontrollieren", "rolle": ROLLE_PROJEKTLEITER,
    },
    "projektstatusbericht": {
        "name": "Projektstatusbericht", "modul": MODUL_FUEHRUNG,
        "aufgabe": "Projekt führen und kontrollieren", "rolle": ROLLE_PROJEKTLEITER,
    },
    "protokoll": {
        "name": "Protokoll", "modul": MODUL_FUEHRUNG,
        "aufgabe": "Projekt führen und kontrollieren", "rolle": ROLLE_PROJEKTLEITER,
    },
    "stakeholderliste": {
        "name": "Stakeholderliste", "modul": MODUL_FUEHRUNG,
        "aufgabe": "Stakeholder managen und informieren", "rolle": ROLLE_PROJEKTLEITER,
    },
    "stakeholderinteressen": {
        "name": "Stakeholderinteressen", "modul": MODUL_FUEHRUNG,
        "aufgabe": "Stakeholder managen und informieren", "rolle": ROLLE_PROJEKTLEITER,
    },
    "durchfuehrungsauftrag": {
        "name": "Durchführungsauftrag", "modul": MODUL_FUEHRUNG,
        "aufgabe": "Durchführungsauftrag erarbeiten", "rolle": ROLLE_PROJEKTLEITER,
    },
    # --- Modul Projektgrundlagen ---
    "rechtsgrundlagenanalyse": {
        "name": "Rechtsgrundlagenanalyse", "modul": MODUL_GRUNDLAGEN,
        "aufgabe": "Rechtsgrundlagenanalyse erarbeiten", "rolle": ROLLE_PROJEKTLEITER,
    },
    "schutzbedarfsanalyse": {
        "name": "Schutzbedarfsanalyse", "modul": MODUL_GRUNDLAGEN,
        "aufgabe": "Schutzbedarfsanalyse erarbeiten", "rolle": ROLLE_ISDS,
    },
    "studie": {
        "name": "Studie", "modul": MODUL_GRUNDLAGEN,
        "aufgabe": "Studie erarbeiten", "rolle": ROLLE_PROJEKTLEITER,
    },
    "beschaffungsanalyse": {
        "name": "Beschaffungsanalyse", "modul": MODUL_GRUNDLAGEN,
        "aufgabe": "Beschaffungsanalyse erarbeiten", "rolle": ROLLE_ANWENDERVERTRETER,
    },
    "prototyp": {
        "name": "Prototyp", "modul": MODUL_GRUNDLAGEN,
        "aufgabe": "Prototyping durchführen", "rolle": ROLLE_ENTWICKLER,
    },
    "prototypdokumentation": {
        "name": "Prototypdokumentation", "modul": MODUL_GRUNDLAGEN,
        "aufgabe": "Prototyping durchführen", "rolle": ROLLE_ENTWICKLER,
    },
    "liste_projektentscheide_fuehrung": {
        "name": "Liste Projektentscheide Führung", "modul": MODUL_GRUNDLAGEN,
        "aufgabe": "Entscheid Weiteres Vorgehen treffen", "rolle": ROLLE_PROJEKTLEITER,
    },
}

MODUL_CODES = {MODUL_STEUERUNG, MODUL_FUEHRUNG, MODUL_GRUNDLAGEN}


def ergebnistyp_info(typ):
    """Katalog-Eintrag eines Ergebnistyps (oder None)."""
    return ERGEBNISTYPEN.get(typ)
