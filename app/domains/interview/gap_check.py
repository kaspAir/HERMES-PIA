"""Deterministische Lueckenpruefung - das Herzstueck des Nachfrage-Verhaltens.

Idee: Methodos vergleicht die vom Projektleiter eingegebenen Risiken mit den
fuer den Projekttyp TYPISCHEN Risiken aus dem Referenzkatalog. Was typisch ist
(salience hoch), aber im Auftrag fehlt, wird als Luecke zurueckgegeben - mit
einer vorformulierten Nachfrage.

Bewusst OHNE LLM: so ist das Verhalten in einer Live-Demo zuverlaessig und
nachvollziehbar. Das LLM darf die Nachfrage spaeter sprachlich verfeinern,
aber die Erkennung der Luecke bleibt deterministisch.
"""


def _matches(entered_text, schlagworte):
    text = (entered_text or "").lower()
    return any(word.lower() in text for word in schlagworte)


def find_missing_risks(entered_risks, catalog_risks):
    """
    entered_risks: Liste von Strings (Risikobeschreibungen aus dem PIA)
    catalog_risks: Liste von Katalog-Eintraegen (dicts mit schlagworte/nachfrage)

    Rueckgabe: Liste der Katalog-Risiken, die keine Entsprechung im PIA haben.
    """
    blob = " ".join(entered_risks or [])
    missing = []
    for risk in catalog_risks:
        if not _matches(blob, risk.get("schlagworte", [])):
            missing.append(risk)
    return missing


def build_followups(missing_risks):
    """Verwandelt fehlende Risiken in konkrete Nachfragen fuer das Interview.

    'row' traegt die strukturierten Felder (Eintrittswahrscheinlichkeit,
    Auswirkungsgrad, Massnahmen) mit, damit sie beim Aufnehmen direkt in die
    Risikotabelle uebernommen werden koennen.
    """
    return [
        {
            "risk_id": r["id"],
            "frage": r.get("nachfrage", "").strip()
            or f"Das Risiko \"{r['beschreibung']}\" ist typisch - bewusst weggelassen?",
            "vorschlag": r["beschreibung"],
            "row": {
                "beschreibung": r["beschreibung"],
                "ew": r.get("ew", ""),
                "ag": r.get("ag", ""),
                "massnahmen": r.get("massnahmen", ""),
            },
        }
        for r in missing_risks
    ]
