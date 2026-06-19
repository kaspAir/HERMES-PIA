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
        "Du bist ein Projektmanagement-Assistent fuer HERMES 2022. "
        "Wandle muendliche Antworten in praezise, sachliche Dokumentationstexte um. "
        "Antworte ausschliesslich mit validem JSON, keine weiteren Erklaerungen."
    )
    user = (
        f"Schreibe den folgenden muendlichen Beitrag als klaren Sachtext "
        f"fuer den PIA-Abschnitt \"{section_title}\" um. "
        f"Alle genannten Fakten beibehalten, Fuellwoerter und Versprecher entfernen.\n\n"
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
