"""Beweist: das RAG-Grounding reicht ähnliche Korpus-Passagen in den Vorschlags-Prompt."""
from app.config import get_config
from app.domains.catalog.service import CatalogService
from app.domains.interview.service import InterviewService
from app.domains.method.service import MethodService


class _CaptureLLM:
    """Fängt den User-Prompt ab; liefert leeren Vorschlag (Prompt ist das Interessante)."""
    model = "fake"

    def __init__(self):
        self.last_user = None

    def complete(self, system, messages, max_tokens=1024):
        self.last_user = messages[0]["content"]
        return "[]"


class _FakeRag:
    available = True

    def __init__(self):
        self.last_org = "unset"

    def search(self, query, org_id=None, top_k=4, ergebnistyp=None):
        self.last_org = org_id
        return [{
            "score": 0.9, "projekt": "AltesProjekt", "abschnitt": "Risiken",
            "ergebnistyp": "PIA", "org_id": None,
            "text": "KORPUSBEISPIEL: Datenmigration war hier das kritischste Risiko.",
        }]


def _session(org_id=1):
    return type("S", (), {
        "org_id": org_id, "method_id": "hermes_pia",
        "project_type_id": "fachanwendung_einfuehrung",
        "start_datum": None, "project_name": "X", "auftraggeber": "Amt",
    })()


def _svc(llm, rag):
    cfg = get_config()
    return InterviewService(MethodService(cfg.METHODS_DIR), CatalogService(cfg.CATALOGS_DIR), llm, rag=rag)


def test_grounding_reicht_korpus_in_den_prompt():
    llm, rag = _CaptureLLM(), _FakeRag()
    svc = _svc(llm, rag)
    section = svc._section_by_id("hermes_pia", "rahmenbedingungen")
    answers = {"ausgangslage": {"extracted": {"text": "Wir digitalisieren die Gesuchsbearbeitung."}}}
    svc._fill_from_suggestion(_session(org_id=7), section, {"extracted": []}, answers)
    assert "KORPUSBEISPIEL" in (llm.last_user or "")
    assert "anonymisiert" in (llm.last_user or "")
    # Mandant wurde an die Suche durchgereicht
    assert rag.last_org == 7


def test_ohne_rag_kein_grounding_block():
    llm = _CaptureLLM()
    svc = _svc(llm, rag=None)
    section = svc._section_by_id("hermes_pia", "rahmenbedingungen")
    answers = {"ausgangslage": {"extracted": {"text": "Etwas Ausgangslage."}}}
    svc._fill_from_suggestion(_session(), section, {"extracted": []}, answers)
    assert "Vergleichbare frühere PIAs" not in (llm.last_user or "")


def test_inaktives_rag_kein_grounding():
    class _Inactive:
        available = False
        def search(self, *a, **k):
            raise AssertionError("darf nicht aufgerufen werden")
    llm = _CaptureLLM()
    svc = _svc(llm, rag=_Inactive())
    section = svc._section_by_id("hermes_pia", "rahmenbedingungen")
    answers = {"ausgangslage": {"extracted": {"text": "Etwas Ausgangslage."}}}
    svc._fill_from_suggestion(_session(), section, {"extracted": []}, answers)
    assert "Vergleichbare frühere PIAs" not in (llm.last_user or "")
