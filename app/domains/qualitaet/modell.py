"""Befund und Gewichtung der Invarianten-Prüfung.

Setzt den Invarianten-Katalog v0.3 um. Die Gewichte bestimmen die Wirkung:
  Muss      -> Ausgabe/Freigabe nicht möglich, bis behoben
  Vorbehalt -> Ausgabe möglich; der offene Sachverhalt wird als Auflage geführt
  Hinweis   -> wird gemeldet, ohne zu blockieren
"""
from dataclasses import dataclass, field

MUSS = "Muss"
VORBEHALT = "Vorbehalt"
HINWEIS = "Hinweis"

# Reihenfolge für die Anzeige: das Blockierende zuerst.
_RANG = {MUSS: 0, VORBEHALT: 1, HINWEIS: 2}

DATEN = "Daten"      # Prüfung auf den strukturierten Angaben
DOK = "Dok"          # Prüfung am erzeugten Dokument


@dataclass(frozen=True)
class Befund:
    regel: str                 # z.B. "D-001"
    gewicht: str               # MUSS | VORBEHALT | HINWEIS
    ebene: str                 # DATEN | DOK
    meldung: str
    fundstelle: str = ""       # Kapitel/Zeile – wo es zu beheben ist
    # Eine Regel, die mangels Datenfeld (noch) nicht laufen kann, wird als
    # solche AUSGEWIESEN statt still übersprungen. Sonst glaubt man, 33 Regeln
    # zu prüfen, und prüft in Wahrheit 28.
    nicht_pruefbar: bool = False
    grund: str = ""            # warum nicht prüfbar

    def __str__(self):
        ort = f" [{self.fundstelle}]" if self.fundstelle else ""
        return f"{self.regel} ({self.gewicht}){ort}: {self.meldung}"


@dataclass
class Pruefergebnis:
    befunde: list = field(default_factory=list)
    geprueft: list = field(default_factory=list)      # Regel-IDs, die gelaufen sind
    uebersprungen: list = field(default_factory=list)  # Regel-IDs ohne Datengrundlage

    # ---- Auswertung ------------------------------------------------------ #
    def nach_gewicht(self, gewicht):
        return [b for b in self.befunde if b.gewicht == gewicht and not b.nicht_pruefbar]

    @property
    def muss(self):
        return self.nach_gewicht(MUSS)

    @property
    def vorbehalte(self):
        return self.nach_gewicht(VORBEHALT)

    @property
    def hinweise(self):
        return self.nach_gewicht(HINWEIS)

    @property
    def offene_regeln(self):
        """Regeln, die mangels Datenfeld nicht geprüft werden konnten."""
        return [b for b in self.befunde if b.nicht_pruefbar]

    @property
    def ausgabe_moeglich(self):
        """Muss-Befunde verhindern die Ausgabe – Vorbehalte und Hinweise nicht."""
        return not self.muss

    def sortiert(self):
        return sorted(self.befunde,
                      key=lambda b: (b.nicht_pruefbar, _RANG.get(b.gewicht, 9), b.regel))

    def zusammenfassung(self):
        return {
            "muss": len(self.muss),
            "vorbehalt": len(self.vorbehalte),
            "hinweis": len(self.hinweise),
            "nicht_pruefbar": len(self.offene_regeln),
            "geprueft": len(self.geprueft),
            "ausgabe_moeglich": self.ausgabe_moeglich,
        }
