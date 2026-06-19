"""LLM-gestuetzte Extraktion: gesprochener/getippter Text -> strukturierte PIA-Felder.

Verantwortung: Das LLM formuliert und extrahiert.
Es entscheidet NICHT, ob eine Luecke vorliegt - das ist Sache des gap_check.
"""
import json
import re


def extract_fields(llm_client, section, raw_text):
    if section.get("type") == "free_text":
        return _extract_free_text(llm_client, section["title"], raw_text)
    if section.get("type") == "table":
        return _extract_table(llm_client, section["title"], section.get("columns", []), raw_text)
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


def _extract_free_text(llm_client, section_title, raw_text):
    system = (
        "Du bist ein erfahrener Projektmanagement-Berater und verfasst offizielle "
        "Projektdokumente nach HERMES 2022 fuer Schweizer Behoerden. "
        "Dein Ziel: sachliche, praezise Behördentexte auf Hochdeutsch. "
        "Antworte ausschliesslich mit validem JSON, keine weiteren Erklaerungen."
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


def _extract_table(llm_client, section_title, columns, raw_text):
    col_parts = []
    for c in columns:
        if c["id"] == "nr":
            continue
        label = c.get("label", c["id"])
        vocab = c.get("vocabulary", [])
        if vocab:
            col_parts.append(f"{c['id']} ({label}) [erlaubte Werte: {', '.join(vocab)}]")
        else:
            col_parts.append(f"{c['id']} ({label})")
    col_desc = "\n".join(f"  - {p}" for p in col_parts)

    system = (
        "Du bist ein Projektmanagement-Assistent fuer HERMES 2022. "
        "Extrahiere strukturierte Tabelleneintraege aus muendlichen Antworten. "
        "Antworte ausschliesslich mit einem validen JSON-Array, keine weiteren Erklaerungen."
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
        "Antworte ausschliesslich mit validem JSON."
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
