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

from app.domains.interview.extraction import (
    detect_project_type,
    estimate_risk_assessment,
    extract_fields,
    generate_followups,
    generate_suggestion,
)
from app.domains.interview.gap_check import build_followups, find_missing_risks
from app.domains.interview.models import InterviewSession
from app.shared.database import SessionLocal

_INTERVIEWABLE = {"free_text", "table"}
# Abschnitte, deren Inhalt durch HERMES verbindlich vorgegeben ist: hier ist der
# Referenzkatalog massgebend, nicht die freie LLM-Erfindung.
CATALOG_FIRST_SECTIONS = {"termine"}
_AVAILABLE_PROJECT_TYPES = [
    {
        "id": "fachanwendung_einfuehrung",
        "name": "Einfuehrung einer Fachanwendung",
        "description": (
            "Beschaffung oder Entwicklung und Einfuehrung einer IT-Fachanwendung, "
            "verbunden mit Anpassungen der Aufbau- und Ablauforganisation."
        ),
    },
    {
        "id": "infrastruktur_erneuerung",
        "name": "Erneuerung IT-Infrastruktur",
        "description": (
            "Abloesung oder Erneuerung technischer Infrastruktur (Server, Netzwerk, "
            "Basisdienste) ohne wesentliche fachliche Prozessaenderungen."
        ),
    },
    {
        "id": "organisationsentwicklung",
        "name": "Organisationsentwicklung",
        "description": (
            "Reorganisation, Prozessoptimierung oder Kulturwandel ohne "
            "oder mit untergeordnetem IT-Anteil."
        ),
    },
    {
        "id": "e_government_portal",
        "name": "E-Government / Buergerportal",
        "description": (
            "Digitalisierung von Verwaltungsleistungen fuer Buergerinnen und Buerger "
            "oder Unternehmen; Online-Schalter, eUmzug, eBewilligung o.ae."
        ),
    },
    {
        "id": "basisdienst_plattform",
        "name": "Basisdienst / Plattform",
        "description": (
            "Aufbau oder Weiterentwicklung eines gemeinsam genutzten Basisdienstes "
            "oder einer Plattform (z.B. IAM, Dokumentenmanagement, Datenaustausch)."
        ),
    },
    {
        "id": "betriebsabloesung",
        "name": "Betriebsabloesung / Migration",
        "description": (
            "Migration von Applikationen, Daten oder Betrieb von einem Altsystem "
            "oder Rechenzentrum zu einer neuen Umgebung."
        ),
    },
]


class InterviewService:
    def __init__(self, method_service, catalog_service, llm_client=None):
        self.methods = method_service
        self.catalogs = catalog_service
        self.llm = llm_client

    # ------------------------------------------------------------------ #
    # Session-Lifecycle                                                    #
    # ------------------------------------------------------------------ #

    def start_session(self, method_id, project_name, created_by=None,
                      projektnummer=None, auftraggeber=None, verwaltungseinheit=None,
                      geschaeftsbereich=None, innenauftragsnummer=None, start_datum=None,
                      org_id=None):
        session = InterviewSession(
            method_id=method_id,
            project_name=project_name,
            org_id=org_id,
            projektnummer=projektnummer,
            auftraggeber=auftraggeber,
            verwaltungseinheit=verwaltungseinheit,
            geschaeftsbereich=geschaeftsbereich,
            innenauftragsnummer=innenauftragsnummer,
            start_datum=start_datum,
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

    def sessions_for_org(self, org_id):
        """PIAs einer Organisationseinheit (Mandantentrennung)."""
        return SessionLocal().query(InterviewSession).filter(
            InterviewSession.org_id == org_id
        ).order_by(InterviewSession.created_at.desc()).all()

    def delete_session(self, session_id):
        """Löscht eine Session (PIA) endgültig. Archivierung folgt später mit
        Benutzerverwaltung."""
        db = SessionLocal()
        s = db.get(InterviewSession, int(session_id))
        if s is None:
            return False
        db.delete(s)
        db.commit()
        return True

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
        extracted = self._extract(section, raw_text, self._vocabularies(session.method_id))

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

        # Nachfragen: KI für alle Abschnitte + Katalog-Gap-Check für Risiken
        entry["followups"] = self._build_followups(section, extracted, raw_text, session.project_type_id)

        # Hat der PL nichts geliefert und entstand auch keine andere Nachfrage,
        # bietet HERMES PIA proaktiv einen Vorschlag an ("Soll ich einen machen?").
        if self.llm and not entry["followups"] and self._is_empty(extracted):
            entry["followups"].append({
                "risk_id": f"offer_{section['id']}",
                "frage": f"Für \"{section['title']}\" liegt noch nichts vor. "
                         f"Soll ich aus dem bisherigen Projektkontext einen Vorschlag erstellen?",
                "type": "offer",
                "status": "pending",
            })

        answers[section["id"]] = entry
        self._persist_answers(session, answers)
        return self.current_state(session)

    def answer_followup(self, session_id, risk_id, accepted, raw_text=None):
        """Nimmt ein nachgefragtes Risiko auf oder markiert es als bewusst weggelassen.

        Beim Aufnehmen ('accepted') wird der Vorschlag – oder die vom
        Projektleiter diktierte Ergaenzung – in die Abschnittsdaten uebernommen,
        sodass er im Dokument und in der Live-Vorschau erscheint.
        """
        session = self.get_session(session_id)
        answers = self._answers(session)

        for sid, section_answer in answers.items():
            for followup in section_answer.get("followups", []):
                if followup.get("risk_id") == risk_id and followup.get("status") == "pending":
                    followup["status"] = "accepted" if accepted else "dismissed"
                    if raw_text:
                        followup["raw_text"] = raw_text
                    if accepted:
                        section = self._section_by_id(session.method_id, sid)
                        if section and followup.get("type") == "offer":
                            self._fill_from_suggestion(session, section, section_answer, answers)
                        elif section:
                            self._apply_followup(section, section_answer, followup, raw_text)
                    self._persist_answers(session, answers)
                    return self.current_state(session)

        raise ValueError(f"Kein offenes Followup fuer Risiko '{risk_id}'")

    def _fill_from_suggestion(self, session, section, section_answer, answers):
        """Erzeugt einen proaktiven Vorschlag (LLM, sonst Katalog) und übernimmt ihn."""
        context = self._suggestion_context(session, answers)
        vocabularies = self._vocabularies(session.method_id)

        # Für Abschnitte mit verbindlicher HERMES-Vorgabe (Ergebnisse/Termine)
        # ist der Katalog massgebend – das LLM darf hier nicht frei erfinden.
        catalog_first = section.get("id") in CATALOG_FIRST_SECTIONS

        suggestion = None
        if catalog_first:
            suggestion = self._catalog_suggestion(session.project_type_id, section)
        if not suggestion and self.llm:
            suggestion = generate_suggestion(self.llm, section, context, vocabularies)
        # Fallback auf den Referenzkatalog, wenn das LLM nichts Brauchbares liefert.
        if not suggestion:
            suggestion = self._catalog_suggestion(session.project_type_id, section)

        if not suggestion:
            return

        # Ergebnisse/Termine: Liefertermine relativ zum Start der Initialisierung
        # berechnen (Startdatum aus dem Formular, sonst heute).
        if section.get("id") == "termine" and isinstance(suggestion, list):
            _assign_termine_dates(suggestion, session.start_datum)

        # Anhängen statt ersetzen: vorhandene Einträge dürfen nie verloren gehen,
        # auch wenn der Vorschlag versehentlich für einen gefüllten Abschnitt käme.
        if section.get("type") == "table" and isinstance(suggestion, list):
            existing = section_answer.get("extracted")
            if not isinstance(existing, list):
                existing = []
            existing.extend(suggestion)
            section_answer["extracted"] = existing
        elif section.get("type") == "free_text" and isinstance(suggestion, dict):
            existing = section_answer.get("extracted")
            old_text = existing.get("text", "") if isinstance(existing, dict) else ""
            new_text = suggestion.get("text", "")
            section_answer["extracted"] = {
                "text": f"{old_text}\n{new_text}".strip() if old_text else new_text
            }

    def _suggestion_context(self, session, answers):
        """Baut einen Kurzkontext aus dem bisher Bekannten für die LLM-Vorschläge."""
        parts = []
        if session.project_name:
            parts.append(f"Projektname: {session.project_name}")
        if session.project_type_id:
            parts.append(f"Projekttyp: {session.project_type_id}")
        if session.auftraggeber:
            parts.append(f"Auftraggeber: {session.auftraggeber}")
        for sid in ("ausgangslage", "ziele"):
            entry = answers.get(sid)
            if not entry:
                continue
            extracted = entry.get("extracted")
            if isinstance(extracted, dict) and extracted.get("text"):
                parts.append(f"{sid}: {extracted['text']}")
            elif isinstance(extracted, list) and extracted:
                joined = "; ".join(
                    str(r.get("beschreibung") or next(iter(r.values()), "")) for r in extracted
                )
                parts.append(f"{sid}: {joined}")
        return "\n".join(parts) or "(noch keine weiteren Angaben)"

    def _vocabularies(self, method_id):
        return self.methods.get(method_id).get("vocabularies", {})

    def _catalog_suggestion(self, project_type_id, section):
        """Liest einen Vorschlag aus dem Referenzkatalog (Fallback)."""
        # Falls der Projekttyp (noch) nicht erkannt wurde, trotzdem einen
        # sinnvollen Standard-Katalog heranziehen, damit Vorschläge nie leer sind.
        if not project_type_id:
            project_type_id = _AVAILABLE_PROJECT_TYPES[0]["id"]
        catalog = self.catalogs.get(project_type_id) or {}
        entries = catalog.get(section["id"])
        if not entries or not isinstance(entries, list):
            return None
        col_ids = {c["id"] for c in section.get("columns", []) if c.get("id") != "nr"}
        rows = []
        for e in entries:
            row = {k: v for k, v in e.items() if k in col_ids}
            if row:
                rows.append(row)
        return rows or None

    def _section_by_id(self, method_id, sid):
        for s in self.methods.sections(method_id):
            if s.get("id") == sid:
                return s
        return None

    def _apply_followup(self, section, section_answer, followup, raw_text):
        """Uebernimmt einen akzeptierten Vorschlag in die Abschnittsdaten."""
        suggestion = (raw_text or "").strip() or (followup.get("vorschlag") or "").strip()
        if not suggestion:
            return

        if section.get("type") == "table":
            rows = section_answer.get("extracted")
            if not isinstance(rows, list):
                rows = []
                section_answer["extracted"] = rows
            cols = [c["id"] for c in section.get("columns", []) if c.get("id") != "nr"]
            if not cols:
                return
            # Hauptspalte: 'beschreibung' bevorzugt, sonst erste Nicht-Nr-Spalte
            target = "beschreibung" if "beschreibung" in cols else cols[0]
            # Strukturierte Felder aus dem Katalog (z.B. ew/ag/massnahmen)
            # übernehmen; Hauptspalte ggf. mit diktiertem Text überschreiben.
            row_data = followup.get("row") or {}
            new_row = {k: v for k, v in row_data.items() if k in cols and v}
            new_row[target] = suggestion

            # Risiken: fehlende Eintrittswahrscheinlichkeit / Auswirkungsgrad /
            # Massnahmen per LLM schätzen (Katalog liefert sie nicht für alle Typen).
            if section.get("id") == "risiken" and self.llm \
                    and (not new_row.get("ew") or not new_row.get("ag")):
                est = estimate_risk_assessment(self.llm, new_row.get("beschreibung", "") or suggestion)
                for k in ("ew", "ag", "massnahmen"):
                    if k in cols and not new_row.get(k) and est.get(k):
                        new_row[k] = est[k]

            rows.append(new_row)
        elif section.get("type") == "free_text":
            extracted = section_answer.get("extracted")
            if not isinstance(extracted, dict):
                extracted = {"text": ""}
                section_answer["extracted"] = extracted
            existing = extracted.get("text", "")
            combined = f"{existing}\n{suggestion}".strip() if existing else suggestion
            # Antwort auf eine Rückfrage NICHT 1:1 übernehmen, sondern den
            # gesamten Abschnitt neu sauber formulieren lassen.
            if self.llm:
                result = extract_fields(self.llm, section, combined)
                combined = (result or {}).get("text") or combined
            extracted["text"] = combined

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

    def _extract(self, section, raw_text, vocabularies=None):
        if not raw_text or not raw_text.strip():
            return {"text": ""} if section.get("type") == "free_text" else []
        if not self.llm:
            return {"text": raw_text} if section.get("type") == "free_text" else []
        return extract_fields(self.llm, section, raw_text, vocabularies or {})

    def _detect_type(self, text):
        if not self.llm:
            return _AVAILABLE_PROJECT_TYPES[0]["id"]
        return detect_project_type(self.llm, _AVAILABLE_PROJECT_TYPES, text)

    def _is_empty(self, extracted):
        if not extracted:
            return True
        if isinstance(extracted, dict):
            return not (extracted.get("text") or "").strip()
        if isinstance(extracted, list):
            return not any(
                any(str(v).strip() for v in row.values())
                for row in extracted if isinstance(row, dict)
            )
        return False

    def _is_complete(self, section, extracted):
        criteria = section.get("interview", {}).get("completeness", [])
        if not criteria:
            return True
        if section.get("type") == "free_text":
            return bool(extracted and extracted.get("text", "").strip())
        return bool(extracted)

    # ------------------------------------------------------------------ #
    # Abschnitt-Reset für Nachbearbeitung                                  #
    # ------------------------------------------------------------------ #

    def reset_section(self, session_id, section_id):
        """Setzt einen Abschnitt zurück, damit er neu beantwortet werden kann."""
        session = self.get_session(session_id)
        answers = self._answers(session)
        if section_id in answers:
            del answers[section_id]
            self._persist_answers(session, answers)

    def section_text(self, session, section_id):
        """Aktuell formulierter Freitext eines Abschnitts (zum Vorladen beim Bearbeiten)."""
        entry = self._answers(session).get(section_id) or {}
        extracted = entry.get("extracted")
        if isinstance(extracted, dict):
            return extracted.get("text", "") or entry.get("raw_text", "")
        return ""

    def update_free_text(self, session_id, section_id, raw_text):
        """Übernimmt den bearbeiteten Freitext und lässt ihn neu sauber formulieren."""
        session = self.get_session(session_id)
        section = self._section_by_id(session.method_id, section_id)
        if not section or section.get("type") != "free_text":
            return False
        text = raw_text or ""
        if self.llm and text.strip():
            result = extract_fields(self.llm, section, text)
            text = (result or {}).get("text") or text
        answers = self._answers(session)
        entry = answers.get(section_id) or {}
        entry["extracted"] = {"text": text}
        entry["raw_text"] = raw_text
        entry["complete"] = bool(text.strip())
        answers[section_id] = entry
        self._persist_answers(session, answers)
        return True

    # ------------------------------------------------------------------ #
    # Preview-Daten für die Live-Vorschau                                  #
    # ------------------------------------------------------------------ #

    def preview_data(self, session):
        """Gibt alle beantworteten Abschnitte mit ihrem Inhalt zurück."""
        answers = self._answers(session)
        sections = self._interviewable_sections(session.method_id)
        result = []
        for s in sections:
            sid = s["id"]
            if sid not in answers:
                continue
            entry = answers[sid]
            sect_type = s.get("type", "free_text")
            if sect_type == "free_text":
                content = (entry.get("extracted") or {}).get("text") or entry.get("raw_text", "")
                result.append({"id": sid, "number": s["number"], "title": s["title"],
                                "type": "free_text", "content": content})
            elif sect_type == "table":
                rows = entry.get("extracted") or []
                cols = [c for c in s.get("columns", []) if c.get("id") != "nr"]
                result.append({"id": sid, "number": s["number"], "title": s["title"],
                                "type": "table", "columns": cols, "rows": rows})
        return result

    # ------------------------------------------------------------------ #
    # Versionsverwaltung                                                   #
    # ------------------------------------------------------------------ #

    def version_info(self, session):
        """Gibt aktuelle Version und Changelog zurück."""
        import json as _json
        changelog = _json.loads(session.changelog_json or "[]")
        snapshot  = _json.loads(session.last_snapshot_json or "{}")
        answers   = self._answers(session)
        # Welche Abschnitte haben sich seit dem letzten Download verändert?
        changed = []
        sections = self._interviewable_sections(session.method_id)
        for s in sections:
            sid = s["id"]
            if sid in answers:
                old = snapshot.get(sid, {})
                new = answers[sid]
                old_txt = (old.get("extracted") or {}).get("text", "") if isinstance(old.get("extracted"), dict) else str(old.get("extracted", ""))
                new_txt = (new.get("extracted") or {}).get("text", "") if isinstance(new.get("extracted"), dict) else str(new.get("extracted", ""))
                if old_txt != new_txt or sid not in snapshot:
                    changed.append({"id": sid, "number": s["number"], "title": s["title"]})
        return {
            "current_version": session.doc_version or "0.1",
            "changelog": changelog,
            "changed_sections": changed,
        }

    def record_version_bump(self, session_id, bump_type, projektleiter, bemerkungen):
        """Speichert einen Versionseintrag und gibt die neue Version zurück."""
        import json as _json
        from datetime import date as _date
        session = self.get_session(session_id)
        old = session.doc_version or "0.1"
        new = _bump_version(old, bump_type)

        entry = {
            "version":     new,
            "name":        projektleiter,
            "datum":       _date.today().strftime("%d.%m.%Y"),
            "bemerkungen": bemerkungen,
        }
        changelog = _json.loads(session.changelog_json or "[]")
        changelog.append(entry)

        db = SessionLocal()
        s = db.get(InterviewSession, session_id)
        s.doc_version = new
        s.changelog_json = _json.dumps(changelog, ensure_ascii=False)
        s.last_snapshot_json = s.answers_json  # Snapshot = aktueller Stand
        db.commit()
        return new, changelog

    def _build_followups(self, section, extracted, raw_text, project_type_id):
        followups = []

        # KI-Vollständigkeitsprüfung für alle Abschnitte mit interview-Definition
        if self.llm and section.get("interview"):
            ai_items = generate_followups(self.llm, section, raw_text)
            for i, f in enumerate(ai_items):
                followups.append({
                    "risk_id": f"ai_{section['id']}_{i}",
                    "frage": f["frage"],
                    "vorschlag": f.get("vorschlag"),
                    "type": "ai",
                    "status": "pending",
                })

        # Deterministischer Katalog-Gap-Check zusätzlich für Risiken
        if section.get("gap_check") and project_type_id and section["id"] == "risiken":
            risk_texts = [r.get("beschreibung", "") for r in (extracted or [])]
            catalog_items = self.followups_for_risks(project_type_id, risk_texts)
            for f in catalog_items:
                followups.append(dict(f, type="catalog", status="pending"))

        return followups


# ------------------------------------------------------------------ #
# Modul-Hilfsfunktionen                                                #
# ------------------------------------------------------------------ #

def _assign_termine_dates(rows, start_datum_str):
    """Setzt je Ergebnis einen Liefertermin relativ zum Initialisierungs-Start.

    Basis: angegebenes Startdatum (ISO), sonst heute. Die Default-Dauern
    (Wochen ab Start) sind Heuristik – später aus Mnemosyne ableitbar.
    """
    from datetime import date as _date, timedelta as _timedelta
    try:
        base = _date.fromisoformat(start_datum_str) if start_datum_str else _date.today()
    except (ValueError, TypeError):
        base = _date.today()
    # An die 8 kanonischen Initialisierungs-Ergebnisse angelehnte Wochen-Offsets.
    wochen = [1, 4, 4, 5, 6, 7, 8, 9]
    for i, r in enumerate(rows):
        if not isinstance(r, dict) or r.get("termin"):
            continue
        w = wochen[i] if i < len(wochen) else (i + 1)
        r["termin"] = (base + _timedelta(weeks=w)).strftime("%d.%m.%Y")
    return rows


def _bump_version(version_str, bump_type):
    """
    bump_type: 'minor' (+0.1) oder 'patch' (+0.0.1)
    '0.1' + minor = '0.2'
    '0.1' + patch = '0.1.1'
    '0.1.1' + minor = '0.2'
    """
    parts = [int(p) for p in str(version_str).split('.')]
    while len(parts) < 3:
        parts.append(0)
    if bump_type == 'minor':
        parts[1] += 1
        parts[2] = 0
    else:
        parts[2] += 1
    if parts[2] == 0:
        return f"{parts[0]}.{parts[1]}"
    return f"{parts[0]}.{parts[1]}.{parts[2]}"
