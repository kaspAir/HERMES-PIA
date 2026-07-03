"""Beweist: 'Projektauftrag' wird an der Quelle zu 'Durchführungsauftrag' korrigiert."""
from app.domains.interview.extraction import extract_fields, fix_hermes_terms, generate_suggestion


class _LLM:
    def __init__(self, payload):
        self.payload = payload

    def complete(self, system, messages, max_tokens=1024):
        return self.payload


def test_fix_hermes_terms_rekursiv():
    data = {"text": "Im Projektauftrag verankern", "rows": [{"x": "Steuerungsausschuss"}]}
    fixed = fix_hermes_terms(data)
    assert fixed["text"] == "Im Durchführungsauftrag verankern"
    assert fixed["rows"][0]["x"] == "Projektausschuss"
    # Genitiv ebenfalls
    assert fix_hermes_terms("des Projektauftrags") == "des Durchführungsauftrags"


def test_extract_free_text_korrigiert_begriff():
    llm = _LLM('{"text": "Der Projektauftrag wird erstellt."}')
    section = {"type": "free_text", "title": "Ausgangslage"}
    out = extract_fields(llm, section, "roh")
    assert out["text"] == "Der Durchführungsauftrag wird erstellt."
    assert "Projektauftrag" not in out["text"]


def test_suggestion_table_korrigiert_begriff():
    llm = _LLM('[{"massnahmen": "Im Projektauftrag verankern"}]')
    section = {"type": "table", "title": "Risiken",
               "columns": [{"id": "massnahmen", "label": "Massnahmen"}]}
    out = generate_suggestion(llm, section, "kontext")
    assert out and "Durchführungsauftrag" in out[0]["massnahmen"]
    assert "Projektauftrag" not in out[0]["massnahmen"]
