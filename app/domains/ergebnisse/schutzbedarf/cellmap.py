"""Zell-Zuordnung für das BACS-Schutzbedarfs-Template (P041-Hi01_V5.1.1).

Nur EINGABEZELLEN. Formelzellen sind hier NICHT aufgeführt und werden nie geschrieben.
Zusätzlich schreibt der Service in Tab 2/4 nur Zellen, die im Template eine Dropdown-
Validierung tragen (doppelte Absicherung gegen versehentliches Überschreiben).
"""

TEMPLATE_DATEI = "P041-Hi01-Schutzbedarfsanalyse.xlsx"

TAB_DECKBLATT = "1. Deckblatt - Informationen"
TAB_INFOVERZEICHNIS = "2. Informationsverzeichnis"
TAB_AUSWIRKUNGEN = "3. Beurteilung Auswirkungen"
TAB_ERHEBUNG = "4. Erhebung Schutzbedarf"

# Deckblatt: Feld -> Zelle (Eingabespalte D bzw. gemergte B-Region beim Beschrieb).
DECKBLATT = {
    "schutzobjektname":    "D6",
    "interne_bezeichnung": "D7",
    "amt":                 "D9",
    "klassifizierung":     "D10",   # Dropdown
    "geschaeftsprozesse":  "D11",
    "zugriff":             "D12",
    "involvierte":         "D13",
    "isv":                 "D15",   # Informationssicherheitsverantwortliche/-r
    "geografisch":         "D18",
    "beschreibung":        "B22",   # gemergt B22:F22
}
KLASSIFIZIERUNG_WERTE = ("Nicht klassifiziert", "INTERN", "VERTRAULICH", "GEHEIM")

# Informationsverzeichnis: Datenzeilen 6..15.
INFO_ZEILEN = range(6, 16)
INFO_SPALTEN = {"gruppe": "B", "klassifizierung": "C", "personendaten": "D", "risiko": "E"}
# Gültige Dropdown-Werte (nur diese werden geschrieben – sonst leer lassen).
INFO_KLASS_WERTE = ("Nicht bekannt", "Nicht klassifiziert", "Klassifizierung: Intern",
                    "Klassifizierung: Vertraulich", "Klassifizierung: Geheim")
INFO_RISIKO_WERTE = ("Keine Personendaten",
                     "Personendaten werden bearbeitet - Risikovorprüfung ergibt kein hohes Risiko",
                     "Personendaten werden bearbeitet - Risikovorprüfung ergibt hohe Risiken")

# Tab 3 Beurteilung Auswirkungen: je Informationsgruppe der Auswirkungstext je Grundwert.
AUSWIRKUNG_SPALTE = {"vertraulichkeit": "C", "verfuegbarkeit": "D",
                     "integritaet": "E", "nachvollziehbarkeit": "F"}

# Tab 4 Erhebung Schutzbedarf: die 4 Grundwerte je Spalte.
GRUNDWERT_SPALTE = {
    "vertraulichkeit":    "C",
    "verfuegbarkeit":     "D",
    "integritaet":        "E",
    "nachvollziehbarkeit": "F",
}
TRIFFT_ZU = "Trifft zu"
TRIFFT_NICHT_ZU = "Trifft nicht zu"
