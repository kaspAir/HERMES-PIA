"""Testorakel für die fachlichen E2E-Fälle (Testkonzept §10).

Weil echte LLM-Antworten variieren, prüfen die E2E-Fälle nicht ein exaktes
Golden-Dokument, sondern INVARIANTEN gegen die HERMES-Spezifikation. Diese
Funktionen sind rein und deterministisch – so lässt sich das Orakel selbst
zuverlässig testen, während der Datenfluss (Audio→STT→LLM) auf Promotion läuft.
"""
import re

# Nicht-HERMES-Begriffe, die im erzeugten PIA NICHT vorkommen dürfen
# (das Postprocessing korrigiert sie – ihr Auftreten wäre ein echter Regress).
FORBIDDEN_TERMS = {
    "Projektauftrag":      "Durchführungsauftrag",
    "Steuerungsausschuss": "Projektausschuss",
    "Lenkungsausschuss":   "Projektausschuss",
    "Steuerungsgremium":   "Projektausschuss",
    "Phasenbericht":       "(in der Initialisierung nicht vorgesehen)",
}


def hermes_term_violations(text):
    """Liste der gefundenen Nicht-HERMES-Begriffe (leere Liste = konform).

    'Durchführungsauftrag' enthält 'auftrag', aber nicht 'Projektauftrag' – der
    Substring-Test trifft also nur den echten Fehlbegriff.
    """
    t = text or ""
    return [f"«{wrong}» statt «{right}»"
            for wrong, right in FORBIDDEN_TERMS.items() if wrong in t]


def erfundene_fundstelle(text):
    """Heuristik gegen halluzinierte Gesetzes-Fundstellen (SR/NG mit Nummer).

    Der Kern soll Nummern-Fundstellen leer lassen statt zu erfinden; ein Muster
    wie 'NG 236.1' oder 'SR 172.010' im Fliesstext ist ein Warnsignal.
    """
    return bool(re.search(r"\b(SR|NG)\s?\d{1,4}(\.\d+)+\b", text or ""))


ALLOWED_PROJECT_TYPES = {
    "basisdienst_plattform", "betriebsabloesung", "e_government_portal",
    "fachanwendung_einfuehrung", "infrastruktur_erneuerung",
    "organisationsentwicklung",
}


def projekttyp_ist_gueltig(project_type_id):
    """Der Projekttyp ist entweder None (bewusst offen) oder ein bekannter Typ –
    NIE ein geratener/erfundener Wert."""
    return project_type_id is None or project_type_id in ALLOWED_PROJECT_TYPES
