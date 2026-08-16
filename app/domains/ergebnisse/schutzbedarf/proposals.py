"""Beratende Vorschläge für die Schutzbedarfsanalyse (aus dem PIA-Kontext).

Ohne LLM: nur das deterministische Seeding greift (keine Beurteilung). Die
Beurteilung (Tab 4) ist ein VORSCHLAG – die/der ISDS-Verantwortliche entscheidet.
"""
import json
import re
from app.domains.llm.errors import PseudoFehler


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


def deckblatt_und_gruppen(wissen, llm):
    """Vorschlag Deckblatt-Zusatzfelder + Informationsgruppen (Verzeichnis). Bewusst OHNE
    Auswirkungstexte (die kommen separat), damit die Antwort kompakt und zuverlässig bleibt.
    Dropdown-Felder in den exakten Vorlage-Formulierungen. Ohne LLM: {}."""
    if llm is None:
        return {}
    user = (
        f"Ausgangslage/Projekt: {wissen.ausgangslage_text()[:1600]}\n"
        f"Auftraggeber: {(wissen.metadata or {}).get('auftraggeber', '')}\n\n"
        "Erstelle einen Vorschlag zur Schutzbedarfsanalyse. Gib NUR JSON:\n"
        '{"beschreibung":"Gegenstand/Zweck des IT-Schutzobjekts (1-2 Sätze)",'
        '"geschaeftsprozesse":"unterstützte Geschäftsprozesse (kurz)",'
        '"zugriff":"wer hat Zugriff (Personen/Gruppen/Rollen, kurz)",'
        '"geografisch":"geographische Rahmenbedingungen (z.B. Datenhaltung nur in CH)",'
        '"gruppen":[{"gruppe":"Informationsgruppe",'
        '"klassifizierung":"GENAU einer von: Nicht klassifiziert | Klassifizierung: Intern | '
        'Klassifizierung: Vertraulich | Klassifizierung: Geheim",'
        '"personendaten":"Art der Personendaten (kurz)",'
        '"risiko":"GENAU einer von: Keine Personendaten | Personendaten werden bearbeitet - '
        "Risikovorprüfung ergibt kein hohes Risiko | Personendaten werden bearbeitet - "
        'Risikovorprüfung ergibt hohe Risiken"}]}\n'
        "Max. 6 Gruppen, kurze Texte. Nur was aus dem Kontext folgt."
    )
    try:
        raw = llm.complete(_SYS_INFO, [{"role": "user", "content": user}], max_tokens=2000)
    except PseudoFehler:
        raise                    # MUSS durchschlagen (ANBINDUNG.md 6.2)
    except Exception:  # noqa: BLE001
        return {}
    return _parse_json(raw) or {}


def auswirkungen(wissen, gruppen_namen, llm):
    """Vorschlag Tab 3: je Informationsgruppe die Auswirkung bei Verletzung der vier
    Grundwerte. Rückgabe: {gruppenname_lower: {vertraulichkeit,verfuegbarkeit,
    integritaet,nachvollziehbarkeit}}. Ohne LLM/Gruppen: {}."""
    if llm is None or not gruppen_namen:
        return {}
    liste = "\n".join(f"  - {n}" for n in gruppen_namen)
    user = (
        f"Schutzobjekt/Ausgangslage: {wissen.ausgangslage_text()[:1200]}\n"
        "Informationsgruppen:\n" + liste + "\n\n"
        "Beschreibe je Gruppe die AUSWIRKUNG (kurz, sachlich), wenn die Informationen: "
        "(a) offengelegt, (b) längere Zeit nicht verfügbar, (c) unautorisiert verändert, "
        "(d) nicht nachvollziehbar zugeordnet werden. Gib NUR JSON:\n"
        '{"gruppen":[{"gruppe":"","vertraulichkeit":"","verfuegbarkeit":"",'
        '"integritaet":"","nachvollziehbarkeit":""}]}'
    )
    try:
        raw = llm.complete(_SYS_INFO, [{"role": "user", "content": user}], max_tokens=2500)
    except PseudoFehler:
        raise                    # MUSS durchschlagen (ANBINDUNG.md 6.2)
    except Exception:  # noqa: BLE001
        return {}
    data = _parse_json(raw) or {}
    out = {}
    for g in data.get("gruppen", []):
        name = str(g.get("gruppe", "")).strip().lower()
        if name:
            out[name] = {k: str(g.get(k, "")).strip() for k in
                         ("vertraulichkeit", "verfuegbarkeit", "integritaet", "nachvollziehbarkeit")}
    return out


def anforderungen(wissen, fragen, llm):
    """Vorschlag Tab 5 (Erhebung Anforderungen): Verfügbarkeit (Servicezeit/Wartung/
    Verfügbarkeit) + Ja/Nein-Antworten auf die Sicherheits-/Datenschutz-Fragen.
    `fragen`: [(zeile, text)]. Ohne LLM: {}."""
    if llm is None:
        return {}
    liste = "\n".join(f"  Zeile {z}: {str(t)[:180]}" for z, t in fragen)
    user = (
        f"Schutzobjekt/Ausgangslage: {wissen.ausgangslage_text()[:1300]}\n\n"
        "Verfügbarkeits-Anforderungen (mit Leistungserbringer abzustimmen) vorschlagen "
        "und die folgenden Ja/Nein-Fragen KONSERVATIV beantworten (im Zweifel 'Nein'), "
        "als VORSCHLAG zur Prüfung:\n" + liste + "\n\n"
        "Gib NUR JSON:\n"
        '{"servicezeit":"z.B. Bürozeiten Mo-Fr / 7x24","wartung":"z.B. ausserhalb Servicezeit",'
        '"verfuegbarkeit":"z.B. 99.5%","fragen":[{"zeile":9,"antwort":"Ja|Nein","bemerkung":""}]}'
    )
    try:
        raw = llm.complete(_SYS_INFO, [{"role": "user", "content": user}], max_tokens=1500)
    except PseudoFehler:
        raise                    # MUSS durchschlagen (ANBINDUNG.md 6.2)
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
    except PseudoFehler:
        raise                    # MUSS durchschlagen (ANBINDUNG.md 6.2)
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
