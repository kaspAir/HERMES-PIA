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
    """Vorschlag Informationsverzeichnis: Datengruppen des Schutzobjekts + Klassifizierung
    + Personendaten-Hinweis. Ohne LLM: []."""
    if llm is None:
        return {}
    user = (
        f"Ausgangslage/Projekt: {wissen.ausgangslage_text()[:1500]}\n"
        f"Auftraggeber: {(wissen.metadata or {}).get('auftraggeber', '')}\n\n"
        "Liste die wichtigsten INFORMATIONSGRUPPEN, die das IT-Schutzobjekt bearbeitet. "
        "Gib NUR JSON:\n"
        '{"beschreibung":"kurzer Beschrieb des Schutzobjekts (Gegenstand/Zweck)",'
        '"gruppen":[{"gruppe":"","klassifizierung":"Nicht klassifiziert|INTERN|VERTRAULICH|GEHEIM",'
        '"personendaten":"z.B. besonders schützenswerte Personendaten / keine"}]}\n'
        "Max. 8 Gruppen. Keine erfundenen Details – nur was aus dem Kontext folgt."
    )
    try:
        raw = llm.complete(_SYS_INFO, [{"role": "user", "content": user}], max_tokens=1500)
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
