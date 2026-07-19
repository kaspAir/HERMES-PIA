"""Beratende Vorschläge für die Schutzbedarfsanalyse (aus dem PIA-Kontext).

Ohne LLM: nur das deterministische Seeding greift (keine Beurteilung). Die
Beurteilung (Tab 4) ist ein VORSCHLAG – die/der ISDS-Verantwortliche entscheidet.
"""
import json
import re


def _parse_json(raw):
    if not raw:
        return None
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group())
    except (ValueError, TypeError):
        return None


_SYS_INFO = (
    "Du unterstützt eine Schutzbedarfsanalyse nach ISV (Informationssicherheitsverordnung, "
    "Bundesverwaltung Schweiz). Sachlicher Behördenstil, Hochdeutsch. Nur valides JSON."
)


def informationsgruppen(wissen, llm):
    """Vorschlag für Deckblatt-Zusatzfelder + Informationsverzeichnis + Auswirkungen
    (Tab 3) je Gruppe. Dropdown-Werte in den exakten Vorlage-Formulierungen. Ohne LLM: {}."""
    if llm is None:
        return {}
    user = (
        f"Ausgangslage/Projekt: {wissen.ausgangslage_text()[:1600]}\n"
        f"Auftraggeber: {(wissen.metadata or {}).get('auftraggeber', '')}\n\n"
        "Erstelle einen Vorschlag zur Schutzbedarfsanalyse. Gib NUR JSON:\n"
        '{"beschreibung":"Gegenstand/Zweck des IT-Schutzobjekts",'
        '"geschaeftsprozesse":"unterstützte Geschäftsprozesse",'
        '"zugriff":"wer hat Zugriff (Personen/Gruppen/Rollen)",'
        '"geografisch":"geographische Rahmenbedingungen (z.B. Datenhaltung nur in CH)",'
        '"gruppen":[{"gruppe":"Informationsgruppe",'
        '"klassifizierung":"einer von: Nicht klassifiziert | Klassifizierung: Intern | '
        'Klassifizierung: Vertraulich | Klassifizierung: Geheim",'
        '"personendaten":"kurzer Text: Art der Personendaten",'
        '"risiko":"einer von: Keine Personendaten | Personendaten werden bearbeitet - '
        "Risikovorprüfung ergibt kein hohes Risiko | Personendaten werden bearbeitet - "
        'Risikovorprüfung ergibt hohe Risiken",'
        '"ausw_vertraulichkeit":"Auswirkung bei Offenlegung",'
        '"ausw_verfuegbarkeit":"Auswirkung bei längerem Ausfall",'
        '"ausw_integritaet":"Auswirkung bei unautorisierter Veränderung",'
        '"ausw_nachvollziehbarkeit":"Auswirkung wenn Urheberschaft unklar"}]}\n'
        "Max. 8 Gruppen. Kurze, sachliche Texte. Keine erfundenen Details – nur was aus "
        "dem Kontext folgt. Die Dropdown-Felder EXAKT in einer der genannten Formulierungen."
    )
    try:
        raw = llm.complete(_SYS_INFO, [{"role": "user", "content": user}], max_tokens=3000)
    except Exception:  # noqa: BLE001
        return {}
    return _parse_json(raw) or {}


def erhebung(wissen, szenarien, llm):
    """Vorschlag Tab 4: je Schaden-Szenario, welche Grundwerte betroffen sind.

    `szenarien`: [(zeile, text), ...]. Rückgabe: {zeile: [grundwerte]} mit Grundwerten
    aus {vertraulichkeit, verfuegbarkeit, integritaet, nachvollziehbarkeit}. Ohne LLM: {}.
    Konservativ – im Zweifel NICHT betroffen (die/der ISDS-Verantwortliche prüft)."""
    if llm is None or not szenarien:
        return {}
    liste = "\n".join(f"  {z}: {t[:150]}" for z, t in szenarien)
    system = (
        "Du unterstützt eine ISV-Schutzbedarfsanalyse. Für JEDES Schaden-Szenario "
        "beurteilst du KONSERVATIV, bei Verletzung welcher Schutzziele (Grundwerte) es "
        "für DIESES Schutzobjekt zutrifft. Im Zweifel NICHT zutreffend. Es ist ein "
        "VORSCHLAG zur Prüfung. Nur valides JSON."
    )
    user = (
        f"Schutzobjekt/Ausgangslage: {wissen.ausgangslage_text()[:1400]}\n\n"
        "Schaden-Szenarien (Zeile: Text):\n" + liste + "\n\n"
        "Gib NUR JSON: {\"zeilen\":[{\"zeile\":<nr>,\"grundwerte\":[\"vertraulichkeit\","
        "\"verfuegbarkeit\",\"integritaet\",\"nachvollziehbarkeit\"]}]}\n"
        "Nur Szenarien aufführen, die zutreffen; leere grundwerte weglassen."
    )
    try:
        raw = llm.complete(system, [{"role": "user", "content": user}], max_tokens=2500)
    except Exception:  # noqa: BLE001
        return {}
    data = _parse_json(raw) or {}
    out = {}
    gueltig = {"vertraulichkeit", "verfuegbarkeit", "integritaet", "nachvollziehbarkeit"}
    for e in data.get("zeilen", []):
        try:
            z = int(e.get("zeile"))
        except (TypeError, ValueError):
            continue
        gw = [g for g in e.get("grundwerte", []) if g in gueltig]
        if gw:
            out[z] = gw
    return out
