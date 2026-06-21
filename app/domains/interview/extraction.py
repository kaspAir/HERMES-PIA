"""LLM-gestuetzte Extraktion: gesprochener/getippter Text -> strukturierte PIA-Felder.

Verantwortung: Das LLM formuliert und extrahiert.
Es entscheidet NICHT, ob eine Luecke vorliegt - das ist Sache des gap_check.
"""
import json
import re

# Verbindliche HERMES-2022-Vorgaben, die in jeden generierenden Prompt einfliessen.
# Stand: offizielles HERMES-2022-Referenzhandbuch (Phase Initialisierung).
HERMES_RULES = (
    "Verbindliche HERMES-2022-Vorgaben (immer einhalten):\n"
    "- Das Mandat fuer die Loesungsentstehung heisst 'Durchfuehrungsauftrag' - "
    "NIEMALS 'Projektauftrag' (den Begriff gibt es in HERMES 2022 nicht).\n"
    "- Die Phase Initialisierung hat KEINEN Phasenbericht "
    "(Phasenberichte entstehen erst ab der Phase Konzept).\n"
    "- Lieferergebnisse der Initialisierung sind: Stakeholderliste, Studie, "
    "Rechtsgrundlagenanalyse, Schutzbedarfsanalyse, Beschaffungsanalyse (sofern "
    "Beschaffung), Projektmanagementplan und Durchfuehrungsauftrag.\n"
    "- Die drei Entscheidaufgaben enden je mit einem Meilenstein: "
    "Projektinitialisierungsfreigabe, Entscheid 'Weiteres Vorgehen', Durchfuehrungsfreigabe.\n"
    "- Verantwortlichkeiten werden auf Rollenebene angegeben "
    "(z.B. Auftraggeber, Projektleiter), nicht mit Personennamen."
)


def _vocab_values(col, vocabularies):
    """Loest den Vokabular-Verweis einer Spalte in die erlaubten Werte auf.

    In der method.yaml steht `vocabulary: zielkategorie` (ein NAME). Die echten
    Werte liegen unter `vocabularies[name]`. Ohne diese Aufloesung wuerde der
    Name als String zeichenweise zerlegt (z, i, e, l, ...) und das LLM ein
    einzelnes Zeichen waehlen.
    """
    vocab = col.get("vocabulary")
    if isinstance(vocab, str):
        return list((vocabularies or {}).get(vocab, []))
    if isinstance(vocab, list):
        return vocab
    return []


def extract_fields(llm_client, section, raw_text, vocabularies=None):
    if section.get("type") == "free_text":
        return _extract_free_text(llm_client, section["title"], raw_text)
    if section.get("type") == "table":
        return _extract_table(llm_client, section["title"], section.get("columns", []),
                              raw_text, vocabularies or {})
    return {}


def detect_project_type(llm_client, available_types, ausgangslage_text):
    types_desc = "\n".join(
        f"- {t['id']}: {t['description']}" for t in available_types
    )
    system = (
        "Du bist ein HERMES-2022-Klassifizierungs-Assistent. "
        "Antworte ausschliesslich mit validem JSON, keine weiteren Erklaerungen."
    )
    user = (
        f"Klassifiziere dieses Vorhaben anhand der Ausgangslage.\n\n"
        f"Verfuegbare Projekttypen:\n{types_desc}\n\n"
        f"Ausgangslage: {ausgangslage_text}\n\n"
        f"Rueckgabe als JSON: {{\"project_type_id\": \"...\", \"confidence\": 0.0}}"
    )
    try:
        raw = llm_client.complete(system, [{"role": "user", "content": user}], max_tokens=256)
        result = _parse_json(raw) or {}
        pt = result.get("project_type_id", "")
        known = {t["id"] for t in available_types}
        return pt if pt in known else available_types[0]["id"]
    except Exception:
        return available_types[0]["id"]


def detect_gender(llm_client, name):
    """Schaetzt das Geschlecht aus einem Namen: 'w', 'm' oder 'u' (unbekannt)."""
    if not name or not name.strip() or llm_client is None:
        return "u"
    system = (
        "Du bestimmst das wahrscheinliche Geschlecht anhand eines Vornamens. "
        "Antworte ausschliesslich mit validem JSON, keine Erklaerungen."
    )
    user = (
        f"Name: {name}\n"
        f'Rueckgabe als JSON: {{"geschlecht": "w"}} fuer weiblich, '
        f'{{"geschlecht": "m"}} fuer maennlich, {{"geschlecht": "u"}} wenn unklar.'
    )
    try:
        raw = llm_client.complete(system, [{"role": "user", "content": user}], max_tokens=64)
        g = (_parse_json(raw) or {}).get("geschlecht", "u")
        return g if g in ("w", "m", "u") else "u"
    except Exception:
        return "u"


def _extract_free_text(llm_client, section_title, raw_text):
    system = (
        "Du bist ein erfahrener Projektmanagement-Berater und verfasst offizielle "
        "Projektdokumente nach HERMES 2022 fuer Schweizer Behoerden. "
        "Dein Ziel: sachliche, praezise Behördentexte auf Hochdeutsch. "
        "Antworte ausschliesslich mit validem JSON, keine weiteren Erklaerungen.\n\n"
        + HERMES_RULES
    )
    user = (
        f"Schreibe den folgenden muendlichen Beitrag als formellen Sachtext "
        f"fuer den PIA-Abschnitt \"{section_title}\" um.\n\n"
        f"Anforderungen:\n"
        f"- Sachlicher Behördenstil (klar, vollständig, neutral)\n"
        f"- Vollständige Sätze; Aufzählungen nur wenn inhaltlich passend\n"
        f"- Füllwörter, Versprecher und Wiederholungen entfernen\n"
        f"- Ich-Formulierungen in sachliche Aussagen umwandeln\n"
        f"- Alle genannten Fakten beibehalten, keine Informationen erfinden\n"
        f"- Angemessene Länge: weder kürzen noch aufblähen\n\n"
        f"Beitrag: {raw_text}\n\n"
        f"Rueckgabe als JSON: {{\"text\": \"...\"}}"
    )
    try:
        raw = llm_client.complete(system, [{"role": "user", "content": user}], max_tokens=512)
        return _parse_json(raw) or {"text": raw_text}
    except Exception:
        return {"text": raw_text}


def _extract_table(llm_client, section_title, columns, raw_text, vocabularies=None):
    col_parts = []
    for c in columns:
        if c["id"] == "nr":
            continue
        label = c.get("label", c["id"])
        values = _vocab_values(c, vocabularies)
        if values:
            col_parts.append(f"{c['id']} ({label}) [erlaubte Werte: {', '.join(values)}]")
        else:
            col_parts.append(f"{c['id']} ({label})")
    col_desc = "\n".join(f"  - {p}" for p in col_parts)

    system = (
        "Du bist ein Projektmanagement-Assistent fuer HERMES 2022. "
        "Extrahiere strukturierte Tabelleneintraege aus muendlichen Antworten. "
        "Antworte ausschliesslich mit einem validen JSON-Array, keine weiteren Erklaerungen.\n\n"
        + HERMES_RULES
    )
    user = (
        f"Extrahiere die Eintraege fuer den PIA-Abschnitt \"{section_title}\" "
        f"aus diesem Beitrag.\n\n"
        f"Felder je Eintrag:\n{col_desc}\n\n"
        f"Beitrag: {raw_text}\n\n"
        f"Rueckgabe als JSON-Array. Felder ohne Information mit leerem String befuellen."
    )
    try:
        raw = llm_client.complete(system, [{"role": "user", "content": user}], max_tokens=1024)
        result = _parse_json(raw)
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            for v in result.values():
                if isinstance(v, list):
                    return v
        return []
    except Exception:
        return []


def generate_followups(llm_client, section, raw_text):
    """
    KI-gestützte Vollständigkeitsprüfung einer Antwort.
    Gibt 0-2 konkrete Nachfragen zurück wenn etwas Wichtiges fehlt.
    Gibt [] zurück wenn die Antwort ausreichend ist.
    """
    interview = section.get("interview", {})
    if not interview or not raw_text or not raw_text.strip():
        return []

    intent = interview.get("intent", "")
    completeness = interview.get("completeness", [])
    criteria_text = "\n".join(f"  - {c}" for c in completeness) or "  - (keine spezifischen Kriterien)"

    system = (
        "Du bist ein erfahrener HERMES-2022-Projektberater. "
        "Du führst ein Interview mit einem Projektleiter. "
        "Prüfe ob seine Antwort die wichtigen Aspekte des Abschnitts abdeckt. "
        "Sei sparsam: stelle NUR eine Nachfrage wenn wirklich etwas Wichtiges fehlt. "
        "Wenn die Antwort ausreichend ist, gib ein leeres Array zurück. "
        "Antworte ausschliesslich mit validem JSON.\n\n"
        + HERMES_RULES
    )
    user = (
        f"Abschnitt: \"{section['title']}\"\n"
        f"Ziel: {intent}\n"
        f"Vollständigkeitskriterien:\n{criteria_text}\n\n"
        f"Antwort des Projektleiters:\n{raw_text}\n\n"
        f"Generiere 0-2 Nachfragen wenn wichtige Aspekte fehlen. "
        f"Keine Nachfragen wenn die Antwort die Kriterien erfüllt.\n\n"
        f'Rückgabe als JSON: {{"followups": [{{"frage": "...", "vorschlag": null}}]}}'
    )
    try:
        raw = llm_client.complete(system, [{"role": "user", "content": user}], max_tokens=512)
        result = _parse_json(raw) or {}
        items = result.get("followups", [])
        return [f for f in items if isinstance(f, dict) and f.get("frage")]
    except Exception:
        return []


def generate_suggestion(llm_client, section, context, vocabularies=None):
    """Erzeugt einen proaktiven Vorschlag fuer einen leeren Abschnitt.

    'context' ist ein Kurztext mit dem bisher Bekannten (Projektname, -typ,
    Ausgangslage ...). Das LLM denkt mit; gibt es nichts Brauchbares zurueck,
    faellt der Aufrufer auf den Katalog zurueck.

    Rueckgabe: Liste von Zeilen-Dicts (table) bzw. {"text": ...} (free_text),
    oder None/[] wenn nichts Sinnvolles erzeugt werden konnte.
    """
    if section.get("type") == "table":
        return _suggest_table(llm_client, section, context, vocabularies or {})
    if section.get("type") == "free_text":
        return _suggest_free_text(llm_client, section, context)
    return None


def _suggest_table(llm_client, section, context, vocabularies=None):
    columns = [c for c in section.get("columns", []) if c.get("id") != "nr"]
    col_parts = []
    for c in columns:
        label = c.get("label", c["id"])
        values = _vocab_values(c, vocabularies)
        if values:
            col_parts.append(f"{c['id']} ({label}) [erlaubte Werte: {', '.join(values)}]")
        else:
            col_parts.append(f"{c['id']} ({label})")
    col_desc = "\n".join(f"  - {p}" for p in col_parts)

    system = (
        "Du bist ein erfahrener HERMES-2022-Projektberater fuer Schweizer Behoerden. "
        "Der Projektleiter hat zu diesem Abschnitt noch nichts geliefert und bittet dich "
        "um einen fachlich sinnvollen Erstvorschlag, den er danach pruefen kann. "
        "Stuetze dich auf den Projektkontext und uebliche HERMES-Praxis. "
        "Antworte ausschliesslich mit einem validen JSON-Array, keine Erklaerungen.\n\n"
        + HERMES_RULES
    )
    user = (
        f"PIA-Abschnitt: \"{section['title']}\"\n\n"
        f"Projektkontext:\n{context}\n\n"
        f"Felder je Eintrag:\n{col_desc}\n\n"
        f"Erzeuge 3-6 plausible Eintraege fuer diesen Abschnitt, abgestimmt auf den "
        f"Projektkontext. Felder ohne Information mit leerem String befuellen.\n\n"
        f"Rueckgabe als JSON-Array. Leeres Array, wenn kein sinnvoller Vorschlag moeglich ist."
    )
    try:
        raw = llm_client.complete(system, [{"role": "user", "content": user}], max_tokens=1024)
        result = _parse_json(raw)
        if isinstance(result, list):
            return [r for r in result if isinstance(r, dict) and any(str(v).strip() for v in r.values())]
        if isinstance(result, dict):
            for v in result.values():
                if isinstance(v, list):
                    return [r for r in v if isinstance(r, dict)]
        return []
    except Exception:
        return []


def _suggest_free_text(llm_client, section, context):
    system = (
        "Du bist ein erfahrener HERMES-2022-Projektberater fuer Schweizer Behoerden. "
        "Der Projektleiter hat zu diesem Abschnitt noch nichts geliefert und bittet dich "
        "um einen fachlich sinnvollen Erstentwurf im sachlichen Behoerdenstil. "
        "Antworte ausschliesslich mit validem JSON, keine Erklaerungen.\n\n"
        + HERMES_RULES
    )
    user = (
        f"PIA-Abschnitt: \"{section['title']}\"\n\n"
        f"Projektkontext:\n{context}\n\n"
        f"Schreibe einen knappen, plausiblen Erstentwurf (2-5 Saetze) fuer diesen Abschnitt.\n\n"
        f'Rueckgabe als JSON: {{"text": "..."}}. Leerer Text, wenn kein sinnvoller Entwurf moeglich ist.'
    )
    try:
        raw = llm_client.complete(system, [{"role": "user", "content": user}], max_tokens=512)
        result = _parse_json(raw) or {}
        text = (result.get("text") or "").strip()
        return {"text": text} if text else None
    except Exception:
        return None


def _parse_json(text):
    """Parst JSON robust - auch wenn das LLM Markdown-Code-Fences eingebaut hat."""
    if not text:
        return None
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for pattern in (r"\[[\s\S]*\]", r"\{[\s\S]*\}"):
        m = re.search(pattern, text)
        if m:
            try:
                return json.loads(m.group())
            except json.JSONDecodeError:
                pass
    return None
