"""Der Interview-Loop: der Kern von HERMES PIA.

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
    COMPLEXITY_DIMENSIONS,
    analyze_results_options,
    assess_complexity,
    detect_project_type,
    estimate_risk_assessment,
    extract_fields,
    generate_followups,
    generate_suggestion,
    nachweis_begruendungen,
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

        # Idempotent: ein verspäteter Doppel-Submit (z.B. weil das Verarbeiten der
        # Ausgangslage durch die Komplexitäts-Analyse einige Sekunden dauert) wird
        # ignoriert – der aktuelle Zustand (Nachfrage/nächste Frage) wird zurückgegeben.
        if state["phase"] != "question":
            return state

        section = state["section"]
        extracted = self._extract(section, raw_text, self._vocabularies(session.method_id))

        # Ergebnisse/Termine: die kanonischen HERMES-Lieferergebnisse sind verbindlich.
        # Liefert der PL nichts, werden sie deterministisch aus dem Katalog gesetzt
        # (statt eines generischen Vorschlags-Angebots), damit darauf die
        # Beschaffungs-/Prototyp-Entscheidungen aufsetzen koennen.
        if section["id"] == "termine" and self._is_empty(extracted):
            catalog = self._catalog_suggestion(session.project_type_id, section)
            if catalog:
                _assign_termine_dates(catalog, session.start_datum, self._complexity_factor(answers))
                extracted = catalog

        entry = {
            "raw_text": raw_text,
            "extracted": extracted,
            "complete": self._is_complete(section, extracted),
        }

        # Deterministische HERMES-Korrekturen (Kosten nur Initialisierung,
        # Pflichtrollen im Personalaufwand) auch bei direkt diktierten Angaben.
        if not self._is_empty(extracted):
            self._postprocess_section(section, entry, answers)
            entry["complete"] = self._is_complete(section, entry["extracted"])

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
        # + Beschaffungs-/Prototyp-Entscheidung bei den Ergebnissen/Terminen.
        entry["followups"] = self._build_followups(section, extracted, raw_text, session, answers)

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
                    # Komplexitäts-Einschätzung: bestätigen / ergänzen / widerlegen –
                    # auch ein 'Widerlegen' (nicht accepted) wird verarbeitet.
                    if followup.get("type") == "complexity":
                        self._apply_complexity(answers, followup, raw_text, refuted=not accepted)
                    elif accepted:
                        section = self._section_by_id(session.method_id, sid)
                        if section and followup.get("type") == "offer":
                            self._fill_from_suggestion(session, section, section_answer, answers)
                        elif section:
                            self._apply_followup(section, section_answer, followup, raw_text)
                    self._persist_answers(session, answers)
                    return self.current_state(session)

        # Idempotent: ein verspäteter Doppel-Klick trifft ein bereits verarbeitetes
        # (nicht mehr 'pending') Followup – kein Fehler, einfach aktuellen Zustand liefern.
        return self.current_state(session)

    def _fill_from_suggestion(self, session, section, section_answer, answers):
        """Erzeugt einen proaktiven Vorschlag (LLM, sonst Katalog) und übernimmt ihn."""
        context = self._suggestion_context(session, answers)
        vocabularies = self._vocabularies(session.method_id)

        # Für Abschnitte mit verbindlicher HERMES-Vorgabe (Ergebnisse/Termine)
        # ist der Katalog massgebend – das LLM darf hier nicht frei erfinden.
        catalog_first = section.get("id") in CATALOG_FIRST_SECTIONS

        suggestion = None
        # Projektorganisation (Kap. 6) wird deterministisch aus dem Personalaufwand
        # (Kap. 3.1) und der Initialisierungsdauer abgeleitet – in PT pro Monat, sodass
        # die Summe je Rolle mit Kap. 3.1 übereinstimmt (kein freier LLM-Vorschlag).
        if section.get("id") == "projektorganisation":
            suggestion = self._build_projektorganisation(answers, session.start_datum)
        if not suggestion and catalog_first:
            suggestion = self._catalog_suggestion(session.project_type_id, section)
        if not suggestion and self.llm and section.get("id") != "projektorganisation":
            suggestion = generate_suggestion(self.llm, section, context, vocabularies)
        # Fallback auf den Referenzkatalog, wenn das LLM nichts Brauchbares liefert.
        if not suggestion:
            suggestion = self._catalog_suggestion(session.project_type_id, section)

        if not suggestion:
            return

        # Ergebnisse/Termine: Liefertermine nach Abhängigkeitsrang × Komplexität.
        if section.get("id") == "termine" and isinstance(suggestion, list):
            _assign_termine_dates(suggestion, session.start_datum, self._complexity_factor(answers))

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

        self._postprocess_section(section, section_answer, answers)

    def _postprocess_section(self, section, section_answer, answers):
        """Deterministische HERMES-Korrekturen nach dem Befüllen eines Abschnitts.

        - Kosten: nur die Phase Initialisierung behalten (nie Konzept/Realisierung/…).
        - Personalaufwand: Pflichtrollen aus den Lieferergebnissen sicherstellen
          (Beschaffungsanalyse -> Anwendervertreter, Prototyp -> Entwickler).
        """
        sid = section.get("id")
        rows = section_answer.get("extracted")
        if not isinstance(rows, list):
            return
        if sid == "kosten":
            section_answer["extracted"] = self._kosten_initialisierung_only(rows)
        elif sid == "personalaufwand":
            self._ensure_deliverable_roles(rows, answers)
        elif sid == "risiken":
            for r in rows:
                if not isinstance(r, dict):
                    continue
                # Fehlende Bewertung (EW/AG) und Massnahme per LLM schätzen, damit
                # die Risikozahl berechenbar ist und die Zeile vollständig wird.
                if self.llm and (not r.get("ew") or not r.get("ag")):
                    est = estimate_risk_assessment(self.llm, r.get("beschreibung", "") or "")
                    for k in ("ew", "ag", "massnahmen"):
                        if not r.get(k) and est.get(k):
                            r[k] = est[k]
                if not str(r.get("verantwortung", "")).strip():
                    r["verantwortung"] = "Projektleiter"
                if not str(r.get("termin", "")).strip():
                    r["termin"] = "laufend"

    @staticmethod
    def _kosten_initialisierung_only(rows):
        """Behält ausschliesslich die Initialisierungs-Kosten (HERMES-Vorgabe)."""
        keep = [r for r in rows
                if isinstance(r, dict) and "initial" in str(r.get("phase", "")).lower()]
        if keep:
            return keep
        # Keine als Initialisierung erkannte Zeile -> einen leeren Initialisierungs-
        # Eintrag setzen (Betrag durch den PL zu ergänzen), statt fremde Phasen zu zeigen.
        return [{"phase": "Initialisierung", "betrag": ""}]

    @staticmethod
    def _ensure_deliverable_roles(rows, answers):
        """Stellt sicher, dass Anwendervertreter (bei Beschaffungsanalyse) und
        Entwickler (bei Prototyp) im Personalaufwand vertreten sind."""
        termine = (answers.get("termine") or {}).get("extracted") or []
        text = " ".join(
            f"{r.get('ergebnis','')} {r.get('abnahme','')}"
            for r in termine if isinstance(r, dict)
        ).lower()

        def has_role(key):
            return any(key in str(r.get("rolle", "")).lower()
                       for r in rows if isinstance(r, dict))

        if "anwendervertreter" in text or "beschaffungsanalyse" in text:
            if not has_role("anwendervertreter"):
                rows.append({"rolle": "Anwendervertreter", "name": "", "aufwand": ""})
        if "entwickler" in text or "prototyp" in text:
            if not has_role("entwickler"):
                rows.append({"rolle": "Entwickler", "name": "", "aufwand": ""})

    def _build_projektorganisation(self, answers, start_datum):
        """Leitet Kap. 6 deterministisch aus Personalaufwand (3.1) und Dauer ab:
        je Rolle der Gesamt-PT auf die Initialisierungsmonate verteilt (in PT),
        sodass die Monatssumme mit Kap. 3.1 übereinstimmt."""
        personal = (answers.get("personalaufwand") or {}).get("extracted")
        if not isinstance(personal, list) or not personal:
            return None
        months = self._initialisierung_monate(answers, start_datum)
        rows = []
        for p in personal:
            if not isinstance(p, dict):
                continue
            rolle = str(p.get("rolle", "")).strip()
            if not rolle:
                continue
            verteilung = _distribute_pt(self._parse_pt(p.get("aufwand")), months)
            row = {"rolle_person": rolle, "bestaetigung": "ausstehend"}
            for i in range(1, 10):
                val = verteilung[i - 1] if i - 1 < len(verteilung) else 0
                row[f"monat_{i}"] = str(val) if val else ""
            rows.append(row)
        return rows or None

    @staticmethod
    def _parse_pt(value):
        import re as _re
        m = _re.search(r"\d+", str(value or ""))
        return int(m.group()) if m else 0

    @staticmethod
    def _initialisierung_monate(answers, start_datum, cap=9):
        """Anzahl Monate der Initialisierung aus der Termin-Spanne (Start bis letzter Termin)."""
        from datetime import date as _date
        termine = (answers.get("termine") or {}).get("extracted") or []
        dates = []
        for r in termine:
            if isinstance(r, dict) and r.get("termin"):
                try:
                    d, m, y = str(r["termin"]).split(".")
                    dates.append(_date(int(y), int(m), int(d)))
                except (ValueError, TypeError):
                    pass
        try:
            start = _date.fromisoformat(start_datum) if start_datum else None
        except (ValueError, TypeError):
            start = None
        if not dates:
            return min(3, cap)
        if start is None:
            start = min(dates)
        days = (max(dates) - start).days
        return min(max(1, -(-days // 30)), cap)  # ceil(days/30)

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
        # Geplante Lieferergebnisse (Kap. 4.1) mit Abnahme-Rolle in den Kontext geben –
        # daraus leitet das LLM u.a. die noetigen Rollen im Personalaufwand ab.
        termine = (answers.get("termine") or {}).get("extracted")
        if isinstance(termine, list) and termine:
            erg = "; ".join(
                f"{r.get('ergebnis','')} (Abnahme: {r.get('abnahme','')})".strip()
                for r in termine if isinstance(r, dict) and r.get("ergebnis")
            )
            if erg:
                parts.append(f"Geplante Lieferergebnisse mit Abnahme-Rolle: {erg}")
        return "\n".join(parts) or "(noch keine weiteren Angaben)"

    # ------------------------------------------------------------------ #
    # Nachweis / Herkunft der Angaben (Transparenz-Anhang)                 #
    # ------------------------------------------------------------------ #

    def build_nachweis(self, session, answers):
        """Erstellt je Abschnitt einen Herkunfts-/Begruendungseintrag.

        Herkunft wird deterministisch aus dem Entstehungsweg abgeleitet (vom
        Projektleiter diktiert vs. von HERMES PIA generiert/ergaenzt), die
        Begruendung per LLM formuliert (mit deterministischem Fallback).
        Rueckgabe: [{"abschnitt", "herkunft", "begruendung"}].
        """
        entries = []
        for s in self.methods.sections(session.method_id):
            if s.get("type") not in _INTERVIEWABLE:
                continue
            ans = answers.get(s.get("id"))
            if not ans:
                continue
            extracted = ans.get("extracted")
            if self._is_empty(extracted):
                continue
            raw = (ans.get("raw_text") or "").strip()
            accepted = [f for f in (ans.get("followups") or [])
                        if f.get("status") == "accepted"]
            entries.append({
                "abschnitt": s.get("title", s.get("id")),
                "herkunft": self._herkunft(raw, accepted),
                "pl_eingabe": raw,
                "inhalt": self._inhalt_summary(extracted),
            })

        context = self._suggestion_context(session, answers)
        begr = nachweis_begruendungen(self.llm, entries, context) if self.llm else {}

        result = []
        for e in entries:
            b = (begr.get(e["abschnitt"]) or "").strip() or self._fallback_begruendung(e["herkunft"])
            result.append({
                "abschnitt": e["abschnitt"],
                "herkunft": e["herkunft"],
                "begruendung": b,
            })
        return result

    @staticmethod
    def _herkunft(raw, accepted):
        has_pl = bool(raw)
        has_combined = (not has_pl) or any(
            f.get("type") in ("offer", "decision", "ai", "catalog") for f in accepted
        )
        if has_pl and not has_combined:
            return "Projektleiter (Interview)"
        if has_pl and has_combined:
            return "Projektleiter + HERMES PIA"
        return "HERMES PIA (kombiniert)"

    @staticmethod
    def _inhalt_summary(extracted, limit=300):
        if isinstance(extracted, dict):
            t = (extracted.get("text") or "").strip()
        elif isinstance(extracted, list):
            parts = []
            for r in extracted:
                if isinstance(r, dict):
                    main = next((str(v) for v in r.values() if str(v).strip()), "")
                    if main:
                        parts.append(main)
            t = "; ".join(parts)
        else:
            t = ""
        return (t[:limit] + "…") if len(t) > limit else t

    @staticmethod
    def _fallback_begruendung(herkunft):
        if herkunft == "Projektleiter (Interview)":
            return ("Beruht auf den Angaben des Projektleiters im Interview, sprachlich in "
                    "die PIA-Form gebracht.")
        if herkunft == "Projektleiter + HERMES PIA":
            return ("Teils auf Angaben des Projektleiters, teils von HERMES PIA ergaenzt "
                    "(Standard-Lieferergebnisse bzw. Vorschlaege aus Ausgangslage und "
                    "HERMES-2022-Standard).")
        return ("Von HERMES PIA aus Ausgangslage, Projekttyp und dem HERMES-2022-Standard fuer "
                "die Phase Initialisierung abgeleitet, da der Projektleiter dazu keine eigenen "
                "Angaben machte.")

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
        row_data = followup.get("row") or {}
        # Entscheidungs-Followups (Beschaffung/Prototyp) tragen ihren Inhalt in
        # `row` und brauchen keinen diktierten Text – darum nicht früh aussteigen,
        # solange entweder ein Vorschlag oder eine vorbereitete Zeile vorliegt.
        if not suggestion and not row_data:
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
            # Strukturierte Felder aus dem Katalog / der Entscheidung (z.B.
            # ergebnis/abnahme bzw. ew/ag/massnahmen) übernehmen; die Hauptspalte
            # nur überschreiben, wenn ein diktierter Text vorliegt.
            new_row = {k: v for k, v in row_data.items() if k in cols and v}
            if suggestion:
                new_row[target] = suggestion
            if not new_row:
                return

            # Risiken: fehlende Eintrittswahrscheinlichkeit / Auswirkungsgrad /
            # Massnahmen per LLM schätzen (Katalog liefert sie nicht für alle Typen).
            if section.get("id") == "risiken" and self.llm \
                    and (not new_row.get("ew") or not new_row.get("ag")):
                est = estimate_risk_assessment(self.llm, new_row.get("beschreibung", "") or suggestion)
                for k in ("ew", "ag", "massnahmen"):
                    if k in cols and not new_row.get(k) and est.get(k):
                        new_row[k] = est[k]

            rows.append(new_row)
            # Ergebnisse/Termine nach dem Einfügen wieder in Abhängigkeitsreihenfolge
            # bringen (z.B. Beschaffungsanalyse/Prototyp gehören vor die Studie).
            if section.get("id") == "termine":
                _sort_termine_rows(rows)
        elif section.get("type") == "free_text":
            if not suggestion:
                return
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
                if sid == "ausgangslage":
                    content = self.composed_ausgangslage(answers)
                else:
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

    def _build_followups(self, section, extracted, raw_text, session, answers):
        followups = []
        project_type_id = session.project_type_id

        # KI-Vollständigkeitsprüfung für alle Abschnitte mit interview-Definition.
        # Ausnahme Ausgangslage: dort übernimmt die strukturierte Komplexitäts-Abfrage
        # (siehe unten) die Vertiefung.
        if self.llm and section.get("interview") and section["id"] != "ausgangslage":
            ai_items = generate_followups(self.llm, section, raw_text)
            for i, f in enumerate(ai_items):
                followups.append({
                    "risk_id": f"ai_{section['id']}_{i}",
                    "frage": f["frage"],
                    "vorschlag": f.get("vorschlag"),
                    "type": "ai",
                    "status": "pending",
                })

        # Deterministischer Katalog-Gap-Check für Risiken – aber NUR, wenn der PL
        # bereits Risiken genannt hat (dann ergänzen wir typische, die fehlen).
        # Bei leeren Risiken würde der Gap-Check das normale Vorschlags-Angebot
        # unterdrücken; dann sollen die Risiken wie jeder andere Abschnitt per
        # LLM (Initialisierungs-Scope) vorgeschlagen werden. Zudem sind die
        # Katalog-Risiken typischerweise Umsetzungs-/Migrationsrisiken.
        if (section.get("gap_check") and project_type_id and section["id"] == "risiken"
                and not self._is_empty(extracted)):
            risk_texts = [r.get("beschreibung", "") for r in (extracted or [])]
            catalog_items = self.followups_for_risks(project_type_id, risk_texts)
            for f in catalog_items:
                followups.append(dict(f, type="catalog", status="pending"))

        # Ergebnisse/Termine: aus der Ausgangslage ableiten, ob eine
        # Beschaffungsanalyse und/oder ein Prototyp eingeplant werden sollen,
        # und dem PL je eine Entscheidungsfrage (Ja/Nein) vorlegen.
        if section["id"] == "termine" and self.llm:
            ausgangslage = self._section_text_from_answers(answers, "ausgangslage")
            opts = analyze_results_options(self.llm, ausgangslage)
            factor = self._complexity_factor(answers)
            followups.extend(self._decision_followups(opts, session.start_datum, factor))

        # Ausgangslage: Komplexität aus verschiedenen Blickwinkeln einschätzen lassen,
        # damit daraus (verlängerte) Dauern für die Ergebnisse abgeleitet werden.
        if section["id"] == "ausgangslage" and self.llm:
            ausgangslage = self._section_text_from_answers(answers, "ausgangslage") or raw_text
            for i, a in enumerate(assess_complexity(self.llm, ausgangslage)):
                followups.append({
                    "risk_id": f"complexity_{i}",
                    "frage": f"Komplexität «{a['dimension']}» – meine Einschätzung: "
                             f"{a['stufe']}. {a['einschaetzung']} "
                             f"Bestätigen, ergänzen (sprechen) oder widerlegen?",
                    "type": "complexity",
                    "status": "pending",
                    "dimension": a["dimension"],
                    "stufe": a["stufe"],
                    "einschaetzung": a["einschaetzung"],
                })

        return followups

    @staticmethod
    def _complexity_factor(answers):
        """Aggregiert die Komplexitäts-Stufen zu einem Dauer-Faktor (>= 1)."""
        komplex = ((answers or {}).get("ausgangslage") or {}).get("komplexitaet") or {}
        if not komplex:
            return 1.0
        weights = {"gering": 1, "mittel": 2, "hoch": 3}
        vals = [weights.get(str(v.get("stufe") if isinstance(v, dict) else v).lower(), 2)
                for v in komplex.values()]
        avg = sum(vals) / len(vals) if vals else 2
        # gering -> 1.0, mittel -> 1.4, hoch -> 1.8
        return round(1.0 + (avg - 1) * 0.4, 2)

    def _decision_followups(self, opts, start_datum, factor=1.0):
        """Baut die Entscheidungs-Followups für Beschaffungsanalyse / Prototyp.

        Bei 'Ja' (akzeptiert) wird die hinterlegte `row` als zusätzliches
        Lieferergebnis in die Tabelle 'Ergebnisse und Termine' übernommen.
        """
        out = []
        b = opts.get("beschaffung") or {}
        if b.get("frage"):
            out.append({
                "risk_id": "decision_beschaffung",
                "frage": b["frage"],
                "type": "decision",
                "status": "pending",
                "row": {
                    "ergebnis": "Beschaffungsanalyse",
                    "termin": _single_termin(start_datum, "Beschaffungsanalyse", factor),
                    "abnahme": "Anwendervertreter",
                    "pruefmethode": "Inhaltliche Prüfung",
                },
            })
        p = opts.get("prototyp") or {}
        if p.get("frage"):
            thema = (p.get("thema") or "").strip()
            ergebnis = f"Prototyp: {thema}" if thema else "Prototyp"
            out.append({
                "risk_id": "decision_prototyp",
                "frage": p["frage"],
                "type": "decision",
                "status": "pending",
                "row": {
                    "ergebnis": ergebnis,
                    "termin": _single_termin(start_datum, ergebnis, factor),
                    "abnahme": "Entwickler",
                    "pruefmethode": "Inhaltliche Prüfung",
                },
            })
        return out

    @staticmethod
    def _section_text_from_answers(answers, section_id):
        entry = (answers or {}).get(section_id) or {}
        extracted = entry.get("extracted")
        if isinstance(extracted, dict):
            return extracted.get("text", "") or entry.get("raw_text", "")
        return entry.get("raw_text", "")

    def _apply_complexity(self, answers, followup, raw_text, refuted=False):
        """Übernimmt die Antwort auf eine Komplexitäts-Einschätzung (bestätigt /
        ergänzt / widerlegt) in die Ausgangslage; daraus folgt der Dauer-Faktor."""
        entry = answers.get("ausgangslage")
        if not entry:
            return
        komplex = entry.setdefault("komplexitaet", {})
        dim = followup.get("dimension") or "Allgemein"
        stufe = followup.get("stufe", "mittel")
        einsch = followup.get("einschaetzung", "")
        if refuted:
            stufe = {"hoch": "mittel", "mittel": "gering", "gering": "gering"}.get(stufe, "gering")
            zusatz = f": {raw_text.strip()}" if raw_text else ""
            einsch = f"{einsch} (vom Projektleiter relativiert{zusatz})"
        elif raw_text and self.llm:
            # Ergänzt: die Dimension mit der gesprochenen Zusatzinfo neu einschätzen.
            base = self._section_text_from_answers(answers, "ausgangslage")
            combined = f"{base}\n\nErgänzung des Projektleiters zu «{dim}»: {raw_text.strip()}"
            hint = next((h for n, h in COMPLEXITY_DIMENSIONS if n == dim), "")
            re_assessed = assess_complexity(self.llm, combined, [(dim, hint)])
            if re_assessed:
                stufe = re_assessed[0]["stufe"]
                einsch = re_assessed[0]["einschaetzung"]
        komplex[dim] = {"stufe": stufe, "einschaetzung": einsch}

    def composed_ausgangslage(self, answers):
        """Ausgangslage-Text inkl. Komplexitätseinschätzung als sauberer Block
        (eine Zeile je Dimension). Wird in Vorschau und Dokument gleich dargestellt."""
        base = self._section_text_from_answers(answers, "ausgangslage")
        komplex = (answers.get("ausgangslage") or {}).get("komplexitaet") or {}
        if not komplex:
            return base
        zeilen = [f"{dim} – {v.get('stufe', '')}: {v.get('einschaetzung', '')}".strip()
                  for dim, v in komplex.items() if isinstance(v, dict)]
        if not zeilen:
            return base
        block = "Komplexitätseinschätzung der Initialisierung:\n" + "\n".join(zeilen)
        return f"{base}\n\n{block}" if base else block


# ------------------------------------------------------------------ #
# Modul-Hilfsfunktionen                                                #
# ------------------------------------------------------------------ #

def _termin_woche(ergebnis, default=5):
    """Wochen-Rang eines Initialisierungs-Ergebnisses nach HERMES-Abhängigkeiten.

    Die Reihenfolge bildet die Pfeilrichtungen der HERMES-Modulübersicht ab:
    Rechtsgrundlagen-/Schutzbedarfs-/Beschaffungsanalyse und Prototyp fliessen in
    die STUDIE -> danach Entscheid 'Weiteres Vorgehen' -> Projektmanagementplan ->
    (aus Studie + PM-Plan) Durchführungsauftrag -> Entscheid 'Durchführungsfreigabe'.
    """
    t = (ergebnis or "").lower()
    if "stakeholder" in t:
        return 2
    if "rechtsgrundlagen" in t:
        return 3
    if "schutzbedarf" in t:
        return 3
    if "beschaffung" in t:
        return 3
    if "prototyp" in t:
        return 4
    if "studie" in t:
        return 5
    if "weiteres vorgehen" in t:
        return 6
    if "managementplan" in t:
        return 7
    if "durchf" in t and "auftrag" in t:
        return 8
    if "durchf" in t and "freigabe" in t:
        return 9
    return default


def _sort_termine_rows(rows):
    """Sortiert Lieferergebnisse stabil nach ihrem HERMES-Abhängigkeitsrang."""
    if isinstance(rows, list):
        rows.sort(key=lambda r: _termin_woche(r.get("ergebnis", "")) if isinstance(r, dict) else 99)
    return rows


def _distribute_pt(total, months):
    """Verteilt PT möglichst gleichmässig auf die Monate (Rest vorne), Summe = total."""
    if months <= 0 or total <= 0:
        return []
    base, rem = divmod(total, months)
    return [base + (1 if i < rem else 0) for i in range(months)]


def _pruefmethode(ergebnis):
    """Standard-Prüfmethode je Ergebnis (Meilensteine: Entscheid, sonst inhaltlich)."""
    t = (ergebnis or "").lower()
    if "meilenstein" in t or "entscheid" in t or "freigabe" in t:
        return "Formelle Abnahme (Entscheid)"
    return "Inhaltliche Prüfung"


def _termin_datum(start_datum_str, weeks):
    from datetime import date as _date, timedelta as _timedelta
    try:
        base = _date.fromisoformat(start_datum_str) if start_datum_str else _date.today()
    except (ValueError, TypeError):
        base = _date.today()
    return (base + _timedelta(weeks=round(weeks))).strftime("%d.%m.%Y")


def _single_termin(start_datum_str, ergebnis, factor=1.0):
    """Liefertermin für ein Zusatz-Ergebnis (Beschaffungsanalyse/Prototyp), nach Rang."""
    return _termin_datum(start_datum_str, _termin_woche(ergebnis) * factor)


def _assign_termine_dates(rows, start_datum_str, factor=1.0):
    """Setzt je Ergebnis Liefertermin (nach HERMES-Abhängigkeitsrang × Komplexitäts-
    faktor) und Prüfmethode, und sortiert die Zeilen in Abhängigkeitsreihenfolge.

    `factor` >= 1 streckt die Dauern bei höherer Komplexität (die Phase Initialisierung
    wird erfahrungsgemäss zu kurz geplant).
    """
    for r in rows:
        if not isinstance(r, dict):
            continue
        if not r.get("termin"):
            r["termin"] = _termin_datum(start_datum_str, _termin_woche(r.get("ergebnis", "")) * factor)
        if not r.get("pruefmethode"):
            r["pruefmethode"] = _pruefmethode(r.get("ergebnis", ""))
    _sort_termine_rows(rows)
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
