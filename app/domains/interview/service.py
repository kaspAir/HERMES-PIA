"""Der Interview-Loop: der Kern von Methodos.

Ablauf je Abschnitt:
  1. Frage stellen  (aus method.yaml: interview.questions)
  2. Antwort aufnehmen (frei, gesprochen oder getippt)
  3. LLM extrahiert strukturierte Felder
  4. Vollstaendigkeitspruefung (method.yaml: interview.completeness)
  5. Bei gap_check-Abschnitten: deterministischer Abgleich gegen Katalog,
     Nachfragen einspeisen wenn typische Eintraege fehlen.

Klare Aufgabentrennung:
  - gap_check.py  entscheidet, ob eine Luecke vorliegt  (deterministisch)
  - extraction.py  formuliert und extrahiert            (LLM)
  - Diese Klasse   steuert den Dialog                   (Zustand + Logik)
"""
import json

from app.domains.interview.extraction import detect_project_type, extract_fields
from app.domains.interview.gap_check import build_followups, find_missing_risks
from app.domains.interview.models import InterviewSession
from app.shared.database import SessionLocal

_INTERVIEWABLE = {"free_text", "table"}
_AVAILABLE_PROJECT_TYPES = [
    {
        "id": "fachanwendung_einfuehrung",
        "name": "Einfuehrung einer Fachanwendung",
        "description": (
            "Beschaffung oder Entwicklung und Einfuehrung einer IT-Fachanwendung, "
            "verbunden mit Anpassungen der Aufbau- und Ablauforganisation."
        ),
    }
]


class InterviewService:
    def __init__(self, method_service, catalog_service, llm_client=None):
        self.methods = method_service
        self.catalogs = catalog_service
        self.llm = llm_client

    # ------------------------------------------------------------------ #
    # Session-Lifecycle                                                    #
    # ------------------------------------------------------------------ #

    def start_session(self, method_id, project_name, created_by=None):
        session = InterviewSession(
            method_id=method_id,
            project_name=project_name,
            created_by=created_by,
            answers_json="{}",
        )
        db = SessionLocal()
        db.add(session)
        db.commit()
        db.refresh(session)
        return session

    def get_session(self, session_id):
        return SessionLocal().get(InterviewSession, int(session_id))

    def all_sessions(self):
        return SessionLocal().query(InterviewSession).order_by(
            InterviewSession.created_at.desc()
        ).all()

    # ------------------------------------------------------------------ #
    # Zustand                                                              #
    # ------------------------------------------------------------------ #

    def current_state(self, session):
        """Gibt den aktuellen Interviewzustand zurueck (fuer UI und API)."""
        answers = self._answers(session)
        sections = self._interviewable_sections(session.method_id)
        progress = self._progress(answers, sections)

        for section in sections:
            sid = section["id"]
            if sid not in answers:
                return {
                    "phase": "question",
                    "section": section,
                    "progress": progress,
                }
            pending = self._pending_followups(answers[sid])
            if pending:
                return {
                    "phase": "followup",
                    "section": section,
                    "followup": pending[0],
                    "progress": progress,
                }

        return {"phase": "complete", "progress": progress}

    def section_summary(self, session):
        """Gibt alle Abschnitte mit ihrem Status zurueck (fuer Fortschrittsanzeige)."""
        answers = self._answers(session)
        sections = self._interviewable_sections(session.method_id)
        state = self.current_state(session)
        current_id = state.get("section", {}).get("id")

        result = []
        for s in sections:
            sid = s["id"]
            if sid in answers:
                status = "done"
                if self._pending_followups(answers[sid]):
                    status = "followup_pending"
            elif sid == current_id:
                status = "current"
            else:
                status = "pending"
            result.append({"id": sid, "number": s["number"], "title": s["title"], "status": status})
        return result

    # ------------------------------------------------------------------ #
    # Antwortverarbeitung                                                  #
    # ------------------------------------------------------------------ #

    def submit_answer(self, session_id, raw_text):
        """Verarbeitet die Antwort des Projektleiters auf die aktuelle Frage."""
        session = self.get_session(session_id)
        answers = self._answers(session)
        state = self.current_state(session)

        if state["phase"] != "question":
            raise ValueError("Kein offener Frageabschnitt")

        section = state["section"]
        extracted = self._extract(section, raw_text)

        entry = {
            "raw_text": raw_text,
            "extracted": extracted,
            "complete": self._is_complete(section, extracted),
        }

        # Nach der Ausgangslage: Projekttyp aus dem Text ableiten
        if section["id"] == "ausgangslage" and not session.project_type_id:
            pt = self._detect_type(raw_text)
            if pt:
                db = SessionLocal()
                s = db.get(InterviewSession, session.id)
                s.project_type_id = pt
                db.commit()
                session.project_type_id = pt

        # Gap-Check bei markierten Abschnitten
        if section.get("gap_check") and session.project_type_id:
            entry["followups"] = self._gap_followups(section, extracted, session.project_type_id)

        answers[section["id"]] = entry
        self._persist_answers(session, answers)
        return self.current_state(session)

    def answer_followup(self, session_id, risk_id, accepted, raw_text=None):
        """Nimmt ein nachgefragtes Risiko auf oder markiert es als bewusst weggelassen."""
        session = self.get_session(session_id)
        answers = self._answers(session)

        for section_answer in answers.values():
            for followup in section_answer.get("followups", []):
                if followup.get("risk_id") == risk_id and followup.get("status") == "pending":
                    followup["status"] = "accepted" if accepted else "dismissed"
                    if raw_text:
                        followup["raw_text"] = raw_text
                    self._persist_answers(session, answers)
                    return self.current_state(session)

        raise ValueError(f"Kein offenes Followup fuer Risiko '{risk_id}'")

    # ------------------------------------------------------------------ #
    # Bestehende oeffentliche API (Rueckwaertskompatibilitaet / Tests)    #
    # ------------------------------------------------------------------ #

    def followups_for_risks(self, project_type_id, entered_risk_texts):
        catalog_risks = self.catalogs.salient_risks(project_type_id)
        missing = find_missing_risks(entered_risk_texts, catalog_risks)
        return build_followups(missing)

    # ------------------------------------------------------------------ #
    # Interne Hilfsmethoden                                                #
    # ------------------------------------------------------------------ #

    def _interviewable_sections(self, method_id):
        return [s for s in self.methods.sections(method_id) if s.get("type") in _INTERVIEWABLE]

    def _answers(self, session):
        return json.loads(session.answers_json or "{}")

    def _persist_answers(self, session, answers):
        db = SessionLocal()
        s = db.get(InterviewSession, session.id)
        s.answers_json = json.dumps(answers, ensure_ascii=False, indent=2)
        db.commit()

    def _progress(self, answers, sections):
        done = sum(1 for s in sections if s["id"] in answers)
        return {"done": done, "total": len(sections)}

    def _pending_followups(self, section_answer):
        return [f for f in section_answer.get("followups", []) if f.get("status") == "pending"]

    def _extract(self, section, raw_text):
        if not raw_text or not raw_text.strip():
            return {"text": ""} if section.get("type") == "free_text" else []
        if not self.llm:
            return {"text": raw_text} if section.get("type") == "free_text" else []
        return extract_fields(self.llm, section, raw_text)

    def _detect_type(self, text):
        if not self.llm:
            return _AVAILABLE_PROJECT_TYPES[0]["id"]
        return detect_project_type(self.llm, _AVAILABLE_PROJECT_TYPES, text)

    def _is_complete(self, section, extracted):
        criteria = section.get("interview", {}).get("completeness", [])
        if not criteria:
            return True
        if section.get("type") == "free_text":
            return bool(extracted and extracted.get("text", "").strip())
        return bool(extracted)

    def _gap_followups(self, section, extracted, project_type_id):
        if section["id"] == "risiken":
            risk_texts = [r.get("beschreibung", "") for r in (extracted or [])]
            followups = self.followups_for_risks(project_type_id, risk_texts)
            return [dict(f, status="pending") for f in followups]
        return []
