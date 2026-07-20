"""Projektspezifischer Vokabular-Hinweis fürs Diktat.

Der generische HERMES-Basis-Prompt (STT_PROMPT) gilt für ALLE Mandanten – er darf
kein Fachgebiet enthalten. Das projektspezifische Vokabular (Systemnamen, Fachwörter,
Behörden, Helvetismen) kommt stattdessen zur Laufzeit aus der Session: aus dem
Projektnamen und dem bereits Diktierten. So lernt die Erkennung die Begriffe des
jeweiligen Vorhabens, ohne dass jemand etwas konfigurieren muss – und beim zweiten
Abschnitt ist sie besser als beim ersten.
"""
import json

_ABSCHNITTE = ("ausgangslage", "ziele", "rahmenbedingungen")


def _text_eines_abschnitts(entry):
    if not isinstance(entry, dict):
        return ""
    extracted = entry.get("extracted")
    if isinstance(extracted, dict) and extracted.get("text"):
        return str(extracted["text"])
    return str(entry.get("raw_text") or "")


def kontext_fuer_diktat(session, max_zeichen=420):
    """Kurzer, projektspezifischer Kontextsatz – oder '' wenn nichts bekannt ist."""
    if session is None:
        return ""
    teile = []
    name = (getattr(session, "project_name", "") or "").strip()
    if name:
        teile.append(f"Das Projekt heisst {name}.")
    try:
        answers = json.loads(getattr(session, "answers_json", "") or "{}")
    except (ValueError, TypeError):
        answers = {}
    if isinstance(answers, dict):
        for sid in _ABSCHNITTE:
            t = " ".join(_text_eines_abschnitts(answers.get(sid)).split())
            if t:
                teile.append(t)
    kontext = " ".join(teile).strip()
    if len(kontext) <= max_zeichen:
        return kontext
    gekuerzt = kontext[:max_zeichen]
    schnitt = gekuerzt.rfind(" ")               # nicht mitten im Wort abschneiden
    return (gekuerzt[:schnitt] if schnitt > 40 else gekuerzt).rstrip() + " …"
