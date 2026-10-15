"""Systemvorschläge, die dem Benutzer Arbeit abnehmen – mit sichtbarer Grundlage.

Deterministisch berechnet, kein Modell. Jeder Vorschlag:
  - nennt seine Berechnungsgrundlage (Feld `beleg`),
  - bleibt UNBESTÄTIGT, bis der Benutzer ihn übernimmt (einzeln oder
    gesammelt) – vorher steht er nicht im Dokument (AT20),
  - entsteht nur, wenn seine Grundlage tatsächlich bekannt ist. Ohne Start-
    und Enddatum gibt es keinen Terminplan, ohne Personentage keine
    Monatsverteilung: keine stillen Standardfristen, kein «heute» (Auftrag 10).

Eine rechnerische Verteilung ist ein Vorschlag, keine zugesagte
Ressourcenplanung; die Bestätigung der Vorgesetzten bleibt offen.
"""
import re
from datetime import date, timedelta

from app.domains.method import vorlagenzuordnung as vz


def _iso(eck, feld):
    e = (eck or {}).get(feld)
    if not e or e.get("unvollstaendig"):
        return None
    try:
        return date.fromisoformat(str(e["wert"]))
    except (ValueError, TypeError):
        return None


def monate_zwischen(start, ende):
    """Angefangene Kalendermonate von start bis ende (mindestens 1)."""
    return max(1, (ende.year - start.year) * 12 + ende.month - start.month + 1)


def _verteile(pt, monate):
    """Ganze PT gleichmässig verteilen; der Rest auf die ersten Monate."""
    basis, rest = divmod(int(round(pt)), monate)
    return [basis + (1 if i < rest else 0) for i in range(monate)]


def monatsverteilung(answers, meta):
    """Vorschlags-Operationen für Kap. 5 – oder [] ohne Grundlage."""
    eck = answers.get("_eckdaten") or {}
    start, ende = _iso(eck, "start_initialisierung"), _iso(eck, "ende_initialisierung")
    if not start or not ende or ende < start:
        return []
    monate = monate_zwischen(start, ende)
    # Rollen, deren Verteilung die Projektleitung selbst angegeben hat, rechnet
    # das System nicht um – deren Angabe gilt.
    eigene = {str(z.get("rolle_person", "")).split("/")[0].strip().lower()
              for z in (answers.get("projektorganisation") or {}).get("extracted") or []
              if z.get("_herkunft") not in ("system", "vorlage", "berechnet")}
    ops = []
    for z in (answers.get("personalaufwand") or {}).get("extracted") or []:
        # Die Zahl, auch wenn sie mit Einheit kommt («45 Personentage») – ein
        # echtes Modell liefert das so, und dann fehlte der Vorschlag ganz.
        m = re.search(r"\d+(?:[.,]\d+)?", str(z.get("aufwand", "")))
        if not m:
            continue
        pt = float(m.group().replace(",", "."))
        if pt <= 0:
            continue
        rolle = z.get("rolle", "")
        if str(rolle).strip().lower() in eigene:
            continue
        name = z.get("name") or ""
        verteilt = _verteile(pt, monate)
        felder = {"rolle_person": f"{rolle} / {name}".strip(" /")}
        felder.update({f"monat_{i + 1}": str(v) for i, v in enumerate(verteilt) if v})
        ops.append({
            "op": "systemvorschlag", "art": "systemvorschlag", "herkunft": "system",
            "inhalt": (f"Vorschlag Monatsverteilung {rolle}: {pt:g} PT auf {monate} Monat(e) "
                       f"({' / '.join(str(v) for v in verteilt)})"),
            "thema": f"Monatsverteilung {rolle}",
            "beleg": (f"Berechnet: Personentage aus Kap. 3.1 gleichmässig auf die Monate "
                      f"{start:%d.%m.%Y} bis {ende:%d.%m.%Y} verteilt. Vorschlag, keine "
                      f"zugesagte Ressourcenplanung."),
            "ziele": [{"abschnitt": "projektorganisation", "felder": felder}],
        })
    return ops


# Relative Lage der Basisergebnisse im Phasenverlauf (Anteil der Dauer). Ein
# Produktentscheid für einen VORSCHLAG, keine HERMES-Vorgabe: die Reihenfolge
# folgt den Abhängigkeiten (Stakeholder vor Studie, Analysen vor der Studie,
# Meilensteine am Ende ihres Abschnitts).
LAGE = {
    "Stakeholder Liste": 0.20,
    "Studie": 0.65,
    "Rechtsgrundlagenanalyse": 0.45,
    "Schutzbedarfsanalyse": 0.45,
    "Meilenstein Weiteres Vorgehen": 0.70,
    "Projektmanagementplan": 0.85,
    "Durchführungsauftrag": 0.95,
    "Meilenstein Durchführungsfreigabe": 1.00,
}
PRUEFMETHODE = {"Meilenstein": "Entscheid Auftraggeber"}


def terminplan(answers):
    """EIN Vorschlag mit Terminen für die Basisergebnisse – oder [] ohne Grundlage."""
    eck = answers.get("_eckdaten") or {}
    start, ende = _iso(eck, "start_initialisierung"), _iso(eck, "ende_initialisierung")
    if not start or not ende or ende <= start:
        return []
    tage = (ende - start).days
    vorhanden = {str(z.get("ergebnis")): z for z in
                 (answers.get("termine") or {}).get("extracted") or []}
    ziele = []
    for ergebnis in vz.basiszeilen("termine"):
        z = vorhanden.get(ergebnis, {})
        if z.get("termin"):
            continue            # was schon terminiert ist, bleibt unangetastet
        kern = next((k for k in LAGE if ergebnis.startswith(k)), None)
        if kern is None:
            continue
        termin = start + timedelta(days=round(tage * LAGE[kern]))
        felder = {"ergebnis": ergebnis, "termin": f"{termin:%d.%m.%Y}"}
        if not z.get("abnahme"):
            felder["abnahme"] = "AG"
        if not z.get("pruefmethode"):
            felder["pruefmethode"] = (PRUEFMETHODE["Meilenstein"] if kern.startswith("Meilenstein")
                                      else "Review")
        ziele.append({"abschnitt": "termine", "felder": felder})
    if not ziele:
        return []
    return [{
        "op": "systemvorschlag", "art": "systemvorschlag", "herkunft": "system",
        "inhalt": f"Vorschlag Terminplan: {len(ziele)} Ergebnisse zwischen "
                  f"{start:%d.%m.%Y} und {ende:%d.%m.%Y} terminiert, Abnahme durch den AG",
        "thema": "Terminplan",
        "beleg": (f"Berechnet aus Start {start:%d.%m.%Y} und Ende {ende:%d.%m.%Y} der "
                  f"Initialisierung nach der Abhängigkeitsfolge der Ergebnisse. Vorschlag zum "
                  f"Anpassen; die Lage der Termine ist ein Produktentscheid von HERMES PIA."),
        "ziele": ziele,
    }]


# Kriterium -> Vorschlagsberechnung
FUER_KRITERIUM = {"K-PO-1": monatsverteilung, "K-TE-1": lambda a, m: terminplan(a)}
