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
import re

from app.domains.interview.extraction import (
    COMPLEXITY_DIMENSIONS,
    analyze_results_options,
    assess_complexity,
    detect_project_type,
    estimate_risk_assessment,
    extract_fields,
    generate_followups,
    generate_suggestion,
    item_label,
    nachweis_begruendungen,
    suggest_missing_items,
)
from app.domains.interview.gap_check import build_followups, find_missing_risks
from app.domains.interview.models import InterviewSession
from app.domains.method.template_structure import (
    build_derived_method,
    build_method_from_mapping,
)
from app.shared.database import SessionLocal

_INTERVIEWABLE = {"free_text", "table"}
# Abschnitte, deren Inhalt durch HERMES verbindlich vorgegeben ist: hier ist der
# Referenzkatalog massgebend, nicht die freie LLM-Erfindung.
CATALOG_FIRST_SECTIONS = {"termine"}

# Abschnitte mit "Haben Sie auch an ... gedacht?"-Ergänzungsangebot, wenn der PL
# selbst Inhalte geliefert hat. Bewusst NICHT dabei: termine (Katalog + Entscheide),
# risiken (eigener Katalog-Gap-Check), kosten (deterministisch aus Kap. 3.1),
# projektorganisation (deterministisch aus Kap. 3.1 + Dauer).
_ERGAENZUNG_SECTIONS = {
    "referenzierte_dokumente", "mitgeltende_unterlagen", "definitionen", "ziele",
    "rahmenbedingungen", "personalaufwand", "sachmittel", "kommunikation",
}
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
    def __init__(self, method_service, catalog_service, llm_client=None, rag=None,
                 projekt_service=None):
        self.methods = method_service
        self.catalogs = catalog_service
        self.llm = llm_client
        self.rag = rag  # RAG-Wissenskorpus (optional); None/inaktiv -> kein Grounding
        # Projekt-Service (optional): erlaubt, die Interviewstruktur aus einer
        # hochgeladenen Kundenvorlage abzuleiten. Ohne ihn / ohne Vorlage bleibt
        # alles exakt wie mit der kanonischen HERMES-Methode.
        self.projekt = projekt_service
        self._derived_cache = {}  # vorlage_id -> abgeleitete Methode

    def _effective_method(self, session):
        """Massgebliche Methode für diese Session: kanonische HERMES-Methode –
        oder, wenn das Projekt eine Word-Vorlage hinterlegt hat, die daraus
        abgeleitete Struktur (Kapitel der Vorlage treiben das Interview).

        'Live': es zählt stets die aktuell aufgelöste Vorlage (Projekt > Org).
        Erkannte Kapitel behalten ihre kanonische ID – bereits Beantwortetes
        bleibt darum erhalten, auch wenn die Vorlage gewechselt wird.
        """
        canonical = self.methods.get(session.method_id)
        ergebnis_id = getattr(session, "ergebnis_id", None)
        if self.projekt is None or not ergebnis_id:
            return canonical
        projekt = self.projekt.projekt_for_ergebnis(ergebnis_id)
        if projekt is None:
            return canonical
        vorlage = self.projekt.resolve_methoden_vorlage(projekt)
        if vorlage is None:
            return canonical
        # Cache-Schlüssel enthält die Zuordnung – wird sie bearbeitet, greift
        # sofort die neue Struktur.
        mapping_json = getattr(vorlage, "mapping_json", None)
        cache_key = (vorlage.id, mapping_json or "")
        cached = self._derived_cache.get(cache_key)
        if cached is not None:
            return cached
        try:
            if mapping_json:
                mapping = json.loads(mapping_json)
                method = build_method_from_mapping(canonical, mapping)
            else:
                method, _ = build_derived_method(vorlage.data, canonical)
        except Exception:  # noqa: BLE001 – bei jedem Zweifel die sichere Kanon-Struktur
            return canonical
        self._derived_cache[cache_key] = method
        return method

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

    def link_ergebnis(self, session_id, ergebnis_id):
        """Verknüpft eine PIA mit ihrem Ergebnis-Knoten in der Projektstruktur."""
        db = SessionLocal()
        s = db.get(InterviewSession, int(session_id))
        if s is None:
            return None
        s.ergebnis_id = int(ergebnis_id)
        db.commit()
        return s

    def all_sessions(self):
        return SessionLocal().query(InterviewSession).order_by(
            InterviewSession.created_at.desc()
        ).all()

    def session_for_ergebnis(self, ergebnis_id):
        """PIA-Session zu einem Ergebnis-Knoten (oder None)."""
        if not ergebnis_id:
            return None
        return SessionLocal().query(InterviewSession).filter(
            InterviewSession.ergebnis_id == int(ergebnis_id)
        ).first()

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
        # GARANTIE: die Komplexitäts-Abfrage zur Ausgangslage darf nie ausfallen –
        # weder nach einem LLM-Fehler beim Submit noch nach dem Bearbeiten-Pfad.
        self._ensure_complexity_followups(session, answers)
        # Ebenso den Projekttyp nachholen, falls die Erkennung beim Submit scheiterte.
        self._ensure_project_type(session, answers)
        sections = self._interviewable_sections(self._effective_method(session))
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
        sections = self._interviewable_sections(self._effective_method(session))
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

    def submit_answer(self, session_id, raw_text, tarife=None):
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
        extracted = self._extract(section, raw_text, self._vocabularies(self._effective_method(session)))

        # Ergebnisse/Termine: die kanonischen HERMES-Lieferergebnisse sind verbindlich.
        # Liefert der PL nichts, werden sie deterministisch aus dem Katalog gesetzt
        # (statt eines generischen Vorschlags-Angebots), damit darauf die
        # Beschaffungs-/Prototyp-Entscheidungen aufsetzen koennen.
        if section["id"] == "termine" and self._is_empty(extracted):
            catalog = self._catalog_suggestion(session.project_type_id, section)
            if catalog:
                _assign_termine_dates(catalog, session.start_datum, self._complexity_factor(answers),
                                      ziel_wochen=self._phase_dauer_wochen(answers))
                extracted = catalog

        entry = {
            "raw_text": raw_text,
            "extracted": extracted,
            "complete": self._is_complete(section, extracted),
        }

        # Deterministische HERMES-Korrekturen (Kosten nur Initialisierung,
        # Pflichtrollen im Personalaufwand) auch bei direkt diktierten Angaben.
        if not self._is_empty(extracted):
            self._postprocess_section(section, entry, answers, tarife)
            entry["complete"] = self._is_complete(section, entry["extracted"])

        # Nach der Ausgangslage: Projekttyp ableiten – aus dem bereinigten Text
        # (nicht dem rohen Diktat), das klassifiziert zuverlässiger.
        if section["id"] == "ausgangslage" and not session.project_type_id:
            text = extracted.get("text") if isinstance(extracted, dict) else None
            pt = self._detect_type(text or raw_text)
            if pt:
                self._set_project_type(session, pt)

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

    def reprocess(self, session_id, tarife=None):
        """Wendet die deterministischen HERMES-Korrekturen erneut auf die bereits
        gespeicherten Antworten an – ohne neues Interview.

        Damit wirken Verbesserungen an der Aufbereitung (Pflicht-/Ergebnisrollen,
        externe Expertise, Kosten, Termine samt genannter Phasendauer, Projekt-
        organisation) sofort auf eine bestehende Session, statt erst beim nächsten
        kompletten Durchlauf. Kein LLM-Aufruf für bereits gefüllte Felder.
        Gibt die Liste der berührten Abschnitts-IDs zurück.
        """
        session = self.get_session(session_id)
        answers = self._answers(session)
        method = self._effective_method(session)
        changed = []

        for section in self._interviewable_sections(method):
            sid = section.get("id")
            entry = answers.get(sid)
            if not isinstance(entry, dict):
                continue
            # Ein LEERER Tabellenabschnitt wird NICHT uebersprungen: gerade dort
            # muessen die verbindlichen HERMES-Zeilen nachgetragen werden
            # (Pflichtrollen in Kap. 3.1, Pflichtzeilen in Kap. 0.5). Wer hier
            # weitergeht, laesst das Dokument genau da unvollstaendig, wo die
            # Methode am meisten vorschreibt.
            if self._is_empty(entry.get("extracted")) and section.get("type") != "table":
                continue
            # Termine: Datteln verwerfen und mit Dauer/Komplexität neu setzen –
            # sonst greift die genannte Phasendauer nicht auf bestehende Termine.
            if sid == "termine" and isinstance(entry.get("extracted"), list):
                for r in entry["extracted"]:
                    if isinstance(r, dict):
                        r.pop("termin", None)
                _assign_termine_dates(entry["extracted"], session.start_datum,
                                      self._complexity_factor(answers),
                                      ziel_wochen=self._phase_dauer_wochen(answers))
            self._postprocess_section(section, entry, answers, tarife)
            entry["complete"] = self._is_complete(section, entry["extracted"])
            changed.append(sid)

        # Projektorganisation (Kap. 6) aus dem korrigierten Personalaufwand neu ableiten.
        org_entry = answers.get("projektorganisation")
        if isinstance(org_entry, dict) and not self._is_empty(
                (answers.get("personalaufwand") or {}).get("extracted")):
            org = self._build_projektorganisation(answers, session.start_datum)
            if org:
                org_entry["extracted"] = org
                if "projektorganisation" not in changed:
                    changed.append("projektorganisation")

        self._persist_answers(session, answers)
        return changed

    def answer_followup(self, session_id, risk_id, accepted, raw_text=None, tarife=None):
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
                    elif followup.get("type") == "expertise":
                        # Thema der externen Fachexpertise bei der Rolle festhalten.
                        self._apply_expertise_thema(answers, raw_text if accepted else None)
                    elif followup.get("type") == "rag_dauer":
                        # Vergleichs-Dauer übernehmen (oder eigene diktierte Dauer) und
                        # Termine/PT/Kosten deterministisch neu ableiten.
                        wochen = None
                        if accepted:
                            wochen = ((_parse_dauer_wochen(raw_text) if raw_text else None)
                                      or followup.get("dauer_wochen"))
                        if wochen:
                            answers["_dauer_wochen"] = wochen
                            self._persist_answers(session, answers)
                            self.reprocess(session_id, tarife)
                            return self.current_state(session)
                    elif accepted:
                        section = self._section_by_id(self._effective_method(session), sid)
                        if section and followup.get("type") == "offer":
                            self._fill_from_suggestion(session, section, section_answer, answers)
                        elif section and followup.get("type") == "ergaenzung":
                            self._apply_ergaenzung(section, section_answer, followup, answers)
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
        context = self._with_corpus_context(context, session, section, answers)
        vocabularies = self._vocabularies(self._effective_method(session))

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
            _assign_termine_dates(suggestion, session.start_datum, self._complexity_factor(answers),
                                  ziel_wochen=self._phase_dauer_wochen(answers))

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

    def _with_corpus_context(self, context, session, section, answers):
        """Reichert den Vorschlags-Kontext um ähnliche Passagen aus dem RAG-Korpus an
        (vergleichbare frühere PIAs). Mandantengetrennt: geteilter Basiskorpus + eigene
        Org. Ohne aktives RAG unverändert."""
        if not (self.rag and self.rag.available):
            return context
        ausgangslage = self._section_text_from_answers(answers, "ausgangslage")
        query = f"{section.get('title', '')}\n{ausgangslage}".strip()
        if not query:
            return context
        try:
            hits = self.rag.search(query, org_id=getattr(session, "org_id", None),
                                   top_k=4, ergebnistyp="PIA")
        except Exception:
            return context
        if not hits:
            return context
        import logging
        logging.getLogger(__name__).info(
            "RAG-Grounding: %d Korpus-Treffer für Abschnitt '%s' (org=%s)",
            len(hits), section.get("id"), getattr(session, "org_id", None),
        )
        lines = []
        for h in hits:
            snippet = " ".join((h.get("text") or "").split())
            if len(snippet) > 400:
                snippet = snippet[:400] + " …"
            absatz = h.get("abschnitt") or ""
            quelle = h.get("projekt", "?") + (f" / {absatz}" if absatz else "")
            lines.append(f"- [{quelle}] {snippet}")
        return context + (
            "\n\nVergleichbare frühere PIAs (anonymisiert, nur als Anhaltspunkt – "
            "Platzhalter wie [Person_x]/[Org_x] sind anonymisiert und dürfen NICHT "
            "übernommen werden; nicht abschreiben, nur fachlich inspirieren lassen):\n"
            + "\n".join(lines)
        )

    def _postprocess_section(self, section, section_answer, answers, tarife=None):
        """Deterministische HERMES-Korrekturen nach dem Befüllen eines Abschnitts.

        - Kosten: nur die Phase Initialisierung behalten (nie Konzept/Realisierung/…).
        - Personalaufwand: Pflichtrollen aus den Lieferergebnissen sicherstellen
          (Beschaffungsanalyse -> Anwendervertreter, Prototyp -> Entwickler).
        """
        sid = section.get("id")
        rows = section_answer.get("extracted")
        # Bei einem TABELLEN-Abschnitt ist eine fehlende oder unbrauchbare
        # Extraktion eine LEERE Tabelle – kein Grund, die deterministischen
        # HERMES-Korrekturen zu überspringen. Genau daran fehlten in Kap. 3.1
        # die Pflichtrollen: lieferte das Modell keine Liste, lief
        # `_ensure_base_roles` nie, und Kap. 5 erbte den Mangel, weil es aus
        # 3.1 abgeleitet wird. Was HERMES verbindlich vorgibt, darf nicht
        # davon abhängen, ob ein Modell etwas extrahiert hat.
        if not isinstance(rows, list) and section.get("type") == "table":
            rows = []
            section_answer["extracted"] = rows
        if not isinstance(rows, list):
            return
        self._ensure_pflichtzeilen(section, rows)
        if sid in ("referenzierte_dokumente", "mitgeltende_unterlagen"):
            # Niemals Fundstellen/Nummern erfinden: SR-/kantonale Nummern kennt das LLM nicht
            # zuverlässig. Spalte 'Nummer/Link' deterministisch leeren – nur der Name bleibt.
            # Verifizierte Fundstellen liefert später die Rechtsgrundlagenanalyse (echter Abruf).
            for r in rows:
                if isinstance(r, dict) and "link" in r:
                    r["link"] = ""
        elif sid == "rahmenbedingungen":
            section_answer["extracted"] = self._strip_duration_caps(rows)
        elif sid == "kosten":
            section_answer["extracted"] = self._kosten_breakdown(rows, answers, tarife)
        elif sid == "personalaufwand":
            self._ensure_base_roles(rows)
            self._ensure_deliverable_roles(rows, answers)
            self._ensure_external_experts(rows, answers,
                                          section_answer.get("raw_text", ""))
            self._ensure_role_pt(rows, answers)
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
    def _strip_duration_caps(rows):
        """Entfernt selbst erfundene Maximaldauer-Vorgaben der Initialisierung aus den
        Rahmenbedingungen (z.B. 'innerhalb von max. 4 Monaten abzuschliessen'). Die Dauer
        ergibt sich aus Komplexität und Terminplan, nicht aus einer pauschalen Obergrenze."""
        import re as _re
        cap = _re.compile(r"maximal|innerhalb von|abzuschliess|abgeschloss", _re.I)
        unit = _re.compile(r"monat|woche", _re.I)
        out = []
        for r in rows:
            if isinstance(r, dict):
                txt = f"{r.get('vorgaben', '')} {r.get('beschreibung', '')}"
                if cap.search(txt) and unit.search(txt):
                    continue  # Dauer-Deckel -> verwerfen
            out.append(r)
        # Nr. fortlaufend neu vergeben, damit keine Lücke entsteht.
        for i, r in enumerate(out, 1):
            if isinstance(r, dict) and "nr" in r:
                r["nr"] = f"{i:02d}"
        return out

    @staticmethod
    def _kosten_breakdown(rows, answers, tarife=None):
        """Leitet die Initialisierungskosten KONSISTENT aus dem Personalaufwand (Kap. 3.1)
        ab – dieser ist die einzige Quelle für die intern/extern-Zuordnung. So kann das
        Kostenblatt nicht mehr externe Posten ausweisen, die im Personalaufwand fehlen.

        Personalkosten = PT × Tagessatz (intern gebündelt, extern je externer Rolle).
        Sachmittel-/Materialpositionen aus den extrahierten Kostenzeilen bleiben erhalten;
        frei erfundene Personalkostenzeilen werden verworfen. Spätere Phasen (Konzept/…)
        fallen weg (HERMES: der PIA budgetiert nur die Initialisierung). Zwischensummen +
        Total werden deterministisch ergänzt.
        """
        import re as _re
        # Massgebliche Tagessätze (CHF/PT): aus den hinterlegten Kostensätzen (Projekt
        # übersteuert Org), sonst Standard. Externe Fachleute teurer als interne.
        tarife = tarife or {}
        TAGESSATZ_INTERN = int(tarife.get("intern") or 1200)
        TAGESSATZ_EXTERN = int(tarife.get("extern") or 1800)
        later = ("konzept", "realisierung", "einführung", "einfuehrung", "abschluss", "umsetzung")
        personal_kw = ("personal", "fachexpert", "experte", "beratung", "tagessatz",
                       "projektleiter", "auftraggeber", "isds", "entwickler", "anwendervertreter")

        def num(val, money=True):
            pat = r"\d[\d'’.\s]*" if money else r"\d+"
            m = _re.search(pat, str(val))
            if not m:
                return None
            digits = _re.sub(r"[^\d]", "", m.group())
            return int(digits) if digits else None

        # 1) Personalkosten aus Kap. 3.1 (intern gebündelt, extern je Rolle).
        personal = (answers.get("personalaufwand") or {}).get("extracted") or []
        intern_pt = 0
        extern_personal = []  # (label, betrag)
        for p in personal:
            if not isinstance(p, dict):
                continue
            rolle = str(p.get("rolle", "")).strip()
            pt = num(p.get("aufwand"), money=False)
            if not rolle or not pt:
                continue
            if "extern" in rolle.lower():
                extern_personal.append((rolle, pt * TAGESSATZ_EXTERN))
            else:
                intern_pt += pt

        # 2) Sachmittel-/Materialpositionen aus den Kostenzeilen übernehmen;
        #    Personal- und Summenzeilen sowie spätere Phasen verwerfen.
        material_intern, material_extern = [], []
        for r in rows:
            if not isinstance(r, dict):
                continue
            label = str(r.get("phase", "")).strip()
            low = label.lower()
            if not label or any(w in low for w in later):
                continue
            if "summe" in low or "total" in low:
                continue
            if any(w in low for w in personal_kw):           # Personalzeile -> kommt aus 3.1
                continue
            amt = num(r.get("betrag"))
            item = {"phase": label, "_amt": amt,
                    "betrag": str(amt) if amt is not None else str(r.get("betrag", "")).strip()}
            (material_extern if "extern" in low else material_intern).append(item)

        # 3) Nichts Auswertbares -> unverändert lassen.
        if intern_pt == 0 and not extern_personal and not any(
                i["_amt"] is not None for i in material_intern + material_extern):
            return rows

        intern_items = []
        if intern_pt > 0:
            cost = intern_pt * TAGESSATZ_INTERN
            intern_items.append({"phase": "Interne Personalkosten (gem. Kap. 3.1)",
                                 "_amt": cost, "betrag": str(cost)})
        intern_items += material_intern
        extern_items = [{"phase": lbl, "_amt": amt, "betrag": str(amt)}
                        for lbl, amt in extern_personal] + material_extern

        out = []

        def emit(group, summenlabel):
            s = 0
            for i in group:
                out.append({"phase": i["phase"], "betrag": i["betrag"]})
                s += i.get("_amt") or 0
            if group:
                out.append({"phase": summenlabel, "betrag": str(s)})
            return s

        s_int = emit(intern_items, "Summe interne Kosten")
        s_ext = emit(extern_items, "Summe externe Kosten")
        out.append({"phase": "Total Initialisierung", "betrag": str(s_int + s_ext)})
        return out

    @staticmethod
    def _ensure_pflichtzeilen(section, rows):
        """Zeilen, die die Methode verbindlich vorgibt, sicherstellen.

        Welche das sind, steht in `method.yaml` (`pflichtzeilen`) – der Code
        weiss nichts über ihren Inhalt. Erkannt wird eine Zeile am Wert der
        ERSTEN Spalte; ist sie schon da, bleibt sie unangetastet, denn was der
        Projektleiter gesagt hat, schlägt die Vorgabe.
        """
        pflicht = section.get("pflichtzeilen") or []
        if not pflicht:
            return
        spalten = section.get("columns") or []
        if not spalten:
            return
        schluessel = spalten[0].get("id")

        def vorhanden(wert):
            return any(str(r.get(schluessel, "")).strip().lower() == wert.lower()
                       for r in rows if isinstance(r, dict))

        for zeile in pflicht:
            wert = str(zeile.get(schluessel, "")).strip()
            if wert and not vorhanden(wert):
                rows.append(dict(zeile))

    @staticmethod
    def _ensure_base_roles(rows):
        """Projektleiter und Auftraggeber sind in der Phase Initialisierung IMMER
        besetzt – auch wenn das LLM sie nicht aus dem Diktat extrahiert hat. Sonst
        bliebe im Extremfall nur eine ergänzte Rolle (z.B. externe Fachexpertise)
        übrig. Sie führen die Tabelle an (vor abgeleiteten/externen Rollen)."""
        def has(*keys):
            return any(any(k in str(r.get("rolle", "")).lower() for k in keys)
                       for r in rows if isinstance(r, dict))
        fehlend = []
        if not has("projektleiter", "projektleitung"):
            fehlend.append({"rolle": "Projektleiter", "name": "", "aufwand": ""})
        if not has("auftraggeber"):
            fehlend.append({"rolle": "Auftraggeber", "name": "", "aufwand": ""})
        rows[:0] = fehlend

    @staticmethod
    def _ensure_deliverable_roles(rows, answers):
        """Stellt die für die geplanten Lieferergebnisse zuständigen Rollen sicher:
        Schutzbedarfsanalyse → ISDS-Verantwortliche/r, Beschaffungsanalyse →
        Anwendervertreter, Prototyp → Entwickler. Nur, wenn das Ergebnis geplant ist."""
        termine = (answers.get("termine") or {}).get("extracted") or []
        text = " ".join(
            f"{r.get('ergebnis','')} {r.get('abnahme','')}"
            for r in termine if isinstance(r, dict)
        ).lower()

        def has_role(*keys):
            return any(any(k in str(r.get("rolle", "")).lower() for k in keys)
                       for r in rows if isinstance(r, dict))

        # (Auslöser im Ergebnis-Text, Rolle, Erkennungs-Stichwort der Rolle)
        for ausloeser, rolle, rollen_kw in (
            (("schutzbedarf",),                 "ISDS-Verantwortliche/r", ("isds",)),
            (("beschaffungsanalyse", "anwendervertreter"), "Anwendervertreter", ("anwendervertreter",)),
            (("prototyp", "entwickler"),        "Entwickler",             ("entwickler",)),
        ):
            if any(a in text for a in ausloeser) and not has_role(*rollen_kw):
                rows.append({"rolle": rolle, "name": "", "aufwand": ""})

    def _ensure_role_pt(self, rows, answers):
        """Schätzt fehlende PT je Rolle: FTE-Last × Arbeitstage/Monat × Dauer × Komplexität.
        Je komplexer/länger die Phase, desto grösser der Aufwand (vom PL genannte Werte
        bleiben unangetastet). Diese PT sind die einzige Quelle für die Monatsverteilung
        in Kap. 5 und die Personalkosten in Kap. 3.3 – so sind 3.1/4.1/5 konsistent."""
        monate = self._phase_monate(answers)
        faktor = self._complexity_factor(answers)
        for r in rows:
            if not isinstance(r, dict):
                continue
            # Vom PL genannte PT bleiben; automatisch geschätzte (Marke _pt_auto) werden
            # bei geänderter Dauer/Komplexität neu skaliert – so bleibt 3.1 konsistent.
            if str(r.get("aufwand", "")).strip() and not r.get("_pt_auto"):
                continue
            pt = round(_rollen_last(r.get("rolle", "")) * _ARBEITSTAGE_PRO_MONAT * monate * faktor)
            if pt > 0:
                r["aufwand"] = str(pt)
                r["_pt_auto"] = True

    def _externe_expertise_signal(self, answers, extra_text=""):
        """True, wenn Ausgangslage/Komplexität ODER der Personalschritt selbst den
        Bedarf an externer Fachexpertise signalisieren."""
        txt = ((self.composed_ausgangslage(answers) or "") + " " + (extra_text or "")).lower()
        return "extern" in txt and any(w in txt for w in (
            "know-how", "knowhow", "fachexpert", "expertise", "einkauf", "kompensier",
            "beratung", "berater", "engpass", "spezialist",
        ))

    def _externe_rolle(self, rows):
        for r in rows:
            if isinstance(r, dict) and "extern" in str(r.get("rolle", "")).lower():
                return r
        return None

    def _ensure_external_experts(self, rows, answers, section_text=""):
        """Erzwingt eine Rolle für externe Fachexpertise, wenn Ausgangslage/Komplexität
        oder der Personalschritt fehlendes internes Know-how bzw. den Einkauf externer
        Expertise signalisieren."""
        if not self._externe_expertise_signal(answers, section_text):
            return
        if self._externe_rolle(rows) is not None:
            return
        rows.append({"rolle": "Externe Fachexpertise", "name": "", "aufwand": ""})

    def _apply_expertise_thema(self, answers, thema):
        """Hält das erfragte Thema bei der Rolle 'Externe Fachexpertise' fest
        (z.B. 'Externe Fachexpertise (Sicherheit)'). Ohne Thema bleibt die Rolle
        bestehen – sie wird nie stillschweigend entfernt."""
        thema = (thema or "").strip().rstrip(".")
        pa = answers.get("personalaufwand") or {}
        rows = pa.get("extracted")
        if not isinstance(rows, list):
            return
        rolle = self._externe_rolle(rows)
        if rolle is None:
            rolle = {"rolle": "Externe Fachexpertise", "name": "", "aufwand": ""}
            rows.append(rolle)
        if thema:
            rolle["rolle"] = f"Externe Fachexpertise ({thema})"
        pa["extracted"] = rows
        answers["personalaufwand"] = pa

    def _build_projektorganisation(self, answers, start_datum):
        """Leitet Kap. 6 deterministisch aus Personalaufwand (3.1) und Dauer ab:
        je Rolle der Gesamt-PT auf die Initialisierungsmonate verteilt (in PT),
        sodass die Monatssumme mit Kap. 3.1 übereinstimmt."""
        personal = (answers.get("personalaufwand") or {}).get("extracted")
        if not isinstance(personal, list) or not personal:
            return None
        months = self._phase_monate(answers, start_datum)
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

    def _phase_monate(self, answers, start_datum=None, cap=9):
        """Monate der Phase Initialisierung – bevorzugt die vom PL genannte Dauer,
        sonst die Termin-Spanne. Gemeinsame Basis für PT-Schätzung (Kap. 3.1) und die
        Monatsverteilung (Kap. 5), damit beide dieselbe Phasenlänge verwenden."""
        w = self._phase_dauer_wochen(answers)
        if w and w > 0:
            return min(max(1, round(w / _WOCHEN_PRO_MONAT)), cap)
        return self._initialisierung_monate(answers, start_datum, cap)

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
        # Ausgangslage INKL. der (bestätigten) Komplexitätseinschätzung – damit die
        # dort verfeinerten Einsichten (z.B. "externes Know-how nötig", hohe
        # Organisationskomplexität) in ALLE nachgelagerten Vorschläge einfliessen
        # (Personalaufwand, Kosten, Sachmittel, Risiken ...), nicht erst ins Dokument.
        ausg = self.composed_ausgangslage(answers)
        if ausg:
            parts.append(f"ausgangslage: {ausg}")
        ziele = answers.get("ziele")
        if ziele:
            extracted = ziele.get("extracted")
            if isinstance(extracted, dict) and extracted.get("text"):
                parts.append(f"ziele: {extracted['text']}")
            elif isinstance(extracted, list) and extracted:
                joined = "; ".join(
                    str(r.get("beschreibung") or next(iter(r.values()), "")) for r in extracted
                )
                parts.append(f"ziele: {joined}")
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

    def build_nachweis(self, session, answers, mit_llm=True):
        """Erstellt je Abschnitt einen Herkunfts-/Begruendungseintrag.

        Herkunft wird deterministisch aus dem Entstehungsweg abgeleitet (vom
        Projektleiter diktiert vs. von HERMES PIA generiert/ergaenzt), die
        Begruendung per LLM formuliert (mit deterministischem Fallback).
        Rueckgabe: [{"abschnitt", "herkunft", "begruendung"}].

        `mit_llm=False` laesst den Modellaufruf weg und nutzt nur die
        deterministischen Begruendungen. Fuer das DOKUMENT ist die
        ausformulierte Fassung richtig; als EVIDENZ in der Pruefung ist die
        deterministische sogar die bessere - sie ist belegbar statt formuliert,
        und der Schritt braucht keine Modellzeit.
        """
        entries = []
        for s in self._effective_method(session).get("sections", []):
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
            herkunft = self._herkunft(raw, accepted)
            # Die Ausgangslage enthält die Komplexitätseinschätzung – eine HERMES-PIA-
            # Beurteilung, die im Interview bestätigt/ergänzt/widerlegt wurde. Transparent als
            # kombinierte Herkunft ausweisen (statt fälschlich „nur Interview, ohne Ergänzung").
            if (s.get("id") == "ausgangslage"
                    and (answers.get("ausgangslage") or {}).get("komplexitaet")):
                herkunft = "Projektleiter + HERMES PIA"
            entries.append({
                "abschnitt": s.get("title", s.get("id")),
                "herkunft": herkunft,
                "pl_eingabe": raw,
                "inhalt": self._inhalt_summary(extracted),
            })

        context = self._suggestion_context(session, answers) if mit_llm else ""
        begr = (nachweis_begruendungen(self.llm, entries, context)
                if (self.llm and mit_llm) else {})

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
            f.get("type") in ("offer", "decision", "ai", "catalog", "ergaenzung")
            for f in accepted
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

    def _vocabularies(self, method):
        return method.get("vocabularies", {})

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

    def _section_by_id(self, method, sid):
        for s in method.get("sections", []):
            if s.get("id") == sid:
                return s
        return None

    def _apply_ergaenzung(self, section, section_answer, followup, answers):
        """Übernimmt die angebotenen 'Haben Sie auch an ...'-Zeilen in den Abschnitt
        (inkl. Nachbearbeitung, z.B. Fundstellen-Blanking bei Referenzierte/Mitgeltende)."""
        if section.get("type") != "table":
            return
        rows = section_answer.get("extracted")
        if not isinstance(rows, list):
            rows = []
            section_answer["extracted"] = rows
        col_ids = {c["id"] for c in section.get("columns", []) if c.get("id") != "nr"}
        for r in followup.get("rows") or []:
            if isinstance(r, dict):
                row = {k: v for k, v in r.items() if k in col_ids and str(v).strip()}
                if row:
                    rows.append(row)
        self._postprocess_section(section, section_answer, answers)

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

    def _interviewable_sections(self, method):
        return [s for s in method.get("sections", []) if s.get("type") in _INTERVIEWABLE]

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

    def _set_project_type(self, session, project_type_id):
        db = SessionLocal()
        s = db.get(InterviewSession, session.id)
        s.project_type_id = project_type_id
        db.commit()
        session.project_type_id = project_type_id

    def _ensure_project_type(self, session, answers):
        """Selbstheilung: holt die Projekttyp-Erkennung nach, falls sie beim Submit
        scheiterte (dann bleibt project_type_id leer statt falsch geraten)."""
        if session.project_type_id or not self.llm:
            return
        entry = answers.get("ausgangslage")
        if not entry or self._is_empty(entry.get("extracted")):
            return
        pt = self._detect_type(self._section_text_from_answers(answers, "ausgangslage"))
        if pt:
            self._set_project_type(session, pt)

    def _ensure_complexity_followups(self, session, answers):
        """Selbstheilung: erzeugt die Komplexitäts-Followups zur Ausgangslage nach,
        falls sie fehlen (LLM-Fehler beim Submit oder Bearbeiten-Pfad, der keine
        Followups baut). Läuft höchstens einmal erfolgreich – danach existieren
        die Followups bzw. die Komplexitätsdaten und die Bedingung greift nie mehr."""
        entry = answers.get("ausgangslage")
        if not entry or not self.llm:
            return False
        if self._is_empty(entry.get("extracted")):
            return False
        if entry.get("komplexitaet"):
            return False                       # bereits beantwortet/verarbeitet
        if any(f.get("type") == "complexity" for f in entry.get("followups", [])):
            return False                       # bereits gestellt (egal welcher Status)
        text = self._section_text_from_answers(answers, "ausgangslage")
        assessed = assess_complexity(self.llm, text)
        if not assessed:
            return False                       # LLM erneut gescheitert -> nächster Aufruf probiert wieder
        followups = entry.setdefault("followups", [])
        for i, a in enumerate(assessed):
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
        self._persist_answers(session, answers)
        return True

    def _extract(self, section, raw_text, vocabularies=None):
        if not raw_text or not raw_text.strip():
            return {"text": ""} if section.get("type") == "free_text" else []
        if not self.llm:
            return {"text": raw_text} if section.get("type") == "free_text" else []
        return extract_fields(self.llm, section, raw_text, vocabularies or {})

    def _detect_type(self, text):
        """Projekttyp aus dem Ausgangslage-Text (None, wenn nicht erkennbar –
        NIE stilles Raten; die Erkennung wird beim nächsten Seitenaufbau nachgeholt)."""
        if not self.llm or not (text or "").strip():
            return None
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
        section = self._section_by_id(self._effective_method(session), section_id)
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
        # Ausgangslage nachbearbeitet: Projekttyp NEU erkennen – eine frühere
        # (evtl. auf halbem Text beruhende) Einstufung wird korrigiert.
        if section_id == "ausgangslage":
            pt = self._detect_type(text)
            if pt and pt != session.project_type_id:
                self._set_project_type(session, pt)
        return True

    # ------------------------------------------------------------------ #
    # Preview-Daten für die Live-Vorschau                                  #
    # ------------------------------------------------------------------ #

    def preview_data(self, session):
        """Gibt alle beantworteten Abschnitte mit ihrem Inhalt zurück."""
        answers = self._answers(session)
        sections = self._interviewable_sections(self._effective_method(session))
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
        sections = self._interviewable_sections(self._effective_method(session))
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
            "current_version": session.doc_version or "0.0",
            "changelog": changelog,
            "changed_sections": changed,
        }

    def record_version_bump(self, session_id, bump_type, projektleiter, bemerkungen):
        """Speichert einen Versionseintrag und gibt die neue Version zurück."""
        import json as _json
        from datetime import date as _date
        session = self.get_session(session_id)
        old = session.doc_version or "0.0"
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

        # Beratender Dauer-Vorschlag aus vergleichbaren Projekten (RAG): nur wenn der
        # PL keine Dauer genannt hat und der Korpus einen Vergleichswert liefert.
        if section["id"] == "termine":
            vgl = self._rag_dauer_vorschlag(session, answers)
            if vgl:
                monate = max(1, round(vgl["median_wochen"] / _WOCHEN_PRO_MONAT))
                followups.append({
                    "risk_id": "rag_dauer",
                    "frage": f"Sie haben keine Phasendauer genannt. Vergleichbare Projekte "
                             f"planten im Median {monate} Monate für die Initialisierung "
                             f"(aus {vgl['n_projekte']} Projekt(en)). Übernehmen, eigene "
                             f"Dauer nennen (sprechen) oder ignorieren?",
                    "type": "rag_dauer",
                    "status": "pending",
                    "dauer_wochen": vgl["median_wochen"],
                })

        # "Haben Sie auch an ... gedacht?": hat der PL selbst Inhalte geliefert,
        # prüft HERMES PIA gegen die typischen Positionen des Abschnitts und bietet
        # die fehlenden EINMAL gesammelt zur Ergänzung an – statt sie still wegzulassen.
        if (self.llm and section.get("type") == "table"
                and section["id"] in _ERGAENZUNG_SECTIONS
                and not self._is_empty(extracted)):
            context = self._suggestion_context(session, answers)
            missing = suggest_missing_items(self.llm, section, context, extracted,
                                            self._vocabularies(self._effective_method(session)))
            if missing:
                namen = ", ".join(f"«{item_label(r)}»" for r in missing if item_label(r))
                followups.append({
                    "risk_id": f"ergaenzung_{section['id']}",
                    "frage": f"Haben Sie auch an {namen} gedacht? "
                             f"Soll ich diese Position(en) ergänzen?",
                    "type": "ergaenzung",
                    "status": "pending",
                    "rows": missing,
                })

        # Externe Fachexpertise: signalisiert der PL Bedarf, aber ohne Thema, fragt
        # HERMES PIA aktiv nach – statt die Rolle mit «Thema offen» stehen zu lassen.
        if section["id"] == "personalaufwand" and \
                self._externe_expertise_signal(answers, raw_text):
            rolle = self._externe_rolle(extracted or [])
            offen = rolle is None or not str(rolle.get("name", "")).strip()
            # kein Thema in Klammern hinter der Rollenbezeichnung erfasst?
            if rolle is not None and "(" in str(rolle.get("rolle", "")):
                offen = False
            if offen:
                followups.append({
                    "risk_id": "expertise_personalaufwand",
                    "frage": "Sie brauchen externe Fachexpertise – wofür genau? "
                             "(z.B. Architektur, Sicherheit, Beschaffung). "
                             "Ich halte das Thema bei der Rolle fest.",
                    "type": "expertise",
                    "status": "pending",
                })

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

    def _phase_dauer_wochen(self, answers):
        """Massgebliche Phasendauer (Wochen) oder None. Priorität: explizit bestätigter
        Wert (z.B. aus dem RAG-Dauer-Vorschlag) vor der aus Ausgangslage/Terminen
        erkannten, vom PL genannten Dauer."""
        explizit = (answers or {}).get("_dauer_wochen")
        if explizit:
            try:
                return float(explizit)
            except (TypeError, ValueError):
                pass
        text = " ".join(filter(None, (
            self.composed_ausgangslage(answers),
            (answers.get("ausgangslage") or {}).get("raw_text"),
            (answers.get("termine") or {}).get("raw_text"),
        )))
        return _parse_dauer_wochen(text)

    def _rag_dauer_vorschlag(self, session, answers):
        """Beratender Dauer-Vorschlag aus vergleichbaren Projekten (RAG): nur wenn der
        PL keine Dauer genannt hat UND der Korpus vergleichbare Projekte mit
        hinterlegter Initialisierungs-Dauer liefert. Sonst None."""
        if not (self.rag and getattr(self.rag, "available", False)):
            return None
        if self._phase_dauer_wochen(answers):
            return None  # PL-Angabe hat Vorrang – nicht nachfragen
        query = self.composed_ausgangslage(answers) or \
            (answers.get("ausgangslage") or {}).get("raw_text") or ""
        if not query.strip():
            return None
        return self.rag.vergleichbare_dauer_wochen(
            query, org_id=getattr(session, "org_id", None))

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
        raw_text = (raw_text or "").strip()
        if raw_text and self.llm:
            # Der PL hat gesprochen (bestätigt/ergänzt/relativiert): die Dimension SAUBER neu
            # einschätzen lassen – niemals den Rohtext (Spracherkennung, ungeschliffen) wörtlich
            # übernehmen, und NEUTRAL formulieren (der PL verfasst die Ausgangslage selbst – keine
            # Aussagen über ihn in dritter Person; der Pushback steht im Interview + Nachweis).
            base = self._section_text_from_answers(answers, "ausgangslage")
            hint = next((h for n, h in COMPLEXITY_DIMENSIONS if n == dim), "")
            # Die RICHTUNG der Rückmeldung muss in die Neubewertung einfliessen –
            # ein Widerspruch soll die Stufe senken können (sonst bleibt «umsichtig
            # nicht untertreiben» stärker als der Einwand). Nur die FORMULIERUNG
            # bleibt neutral (keine Aussagen über den Projektleiter im Dokument).
            if refuted:
                haltung = ("Diese Einschätzung wurde im Interview BESTRITTEN – sie wird als "
                           "zu hoch bzw. unzutreffend beurteilt. Senke die Stufe, sofern die "
                           "folgende Begründung das stützt.")
            else:
                haltung = "Diese Einschätzung wurde im Interview bestätigt und ergänzt."
            combined = (f"{base}\n\nBisherige Einschätzung «{dim}» ({stufe}): {einsch}\n"
                        f"{haltung}\n"
                        f"Ergänzende Aussage dazu (mündlich erfasst, ggf. ungeschliffen): {raw_text}\n"
                        f"Bewerte die Dimension neu und arbeite die Aussage als Sachverhalt ein – "
                        f"ohne den Projektleiter oder seine Haltung in dritter Person zu erwähnen.")
            re_assessed = assess_complexity(self.llm, combined, [(dim, hint)])
            if re_assessed:
                stufe = re_assessed[0]["stufe"]
                einsch = re_assessed[0]["einschaetzung"]
        elif refuted:
            # Widerlegt ohne gesprochene Begründung: Stufe mechanisch senken und die
            # (jetzt zurückgewiesene) Detail-Einschätzung durch eine kurze, klare Notiz
            # ersetzen – sonst widerspricht der ausführliche Text der gesenkten Stufe.
            stufe = {"hoch": "mittel", "mittel": "gering", "gering": "gering"}.get(stufe, "gering")
            einsch = ("Wird als nicht (wesentlich) zutreffend eingeschätzt und daher tiefer "
                      "eingeordnet.")
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

# Vom PL genannte Phasendauer aus dem Diktat erkennen ("neun Monate", "6 Wochen").
_ZAHLWORT = {
    "ein": 1, "eine": 1, "eins": 1, "zwei": 2, "drei": 3, "vier": 4, "fünf": 5,
    "fuenf": 5, "sechs": 6, "sieben": 7, "acht": 8, "neun": 9, "zehn": 10, "elf": 11,
    "zwölf": 12, "zwoelf": 12, "achtzehn": 18, "zwanzig": 20, "vierundzwanzig": 24,
}
_DAUER_RE = re.compile(r"(\d{1,2}|[a-zäöü]+)\s*(monat|woche)", re.IGNORECASE)
_DAUER_KONTEXT = ("phase", "initialisier", "dauer", "eingeplant", "geplant", "vorgesehen")
_WOCHEN_PRO_MONAT = 4.345
_MAX_TERMIN_RANG = 9  # Rang der Durchführungsfreigabe = Phasenende

# PT-Schätzung: FTE-Anteil je Rolle während der Phase Initialisierung. Der Aufwand
# skaliert mit Dauer (Monate) und Komplexität – je komplexer/länger, desto grösser.
_ARBEITSTAGE_PRO_MONAT = 20
_ROLLEN_LAST = (
    ("projektleiter", 0.40),
    ("auftraggeber", 0.05),
    ("extern", 0.35),
    ("isds", 0.15),
    ("anwendervertreter", 0.15),
    ("entwickler", 0.25),
)
_ROLLEN_LAST_DEFAULT = 0.15


def _rollen_last(rolle):
    r = (rolle or "").lower()
    for kw, load in _ROLLEN_LAST:
        if kw in r:
            return load
    return _ROLLEN_LAST_DEFAULT


def _parse_dauer_wochen(text):
    """Erste plausible Phasendauer als Wochen aus Freitext (oder None).

    Bevorzugt eine Angabe im Umfeld von 'Phase/Initialisierung/Dauer/geplant';
    sonst die erste Monats-, sonst die erste Wochenangabe. Monate → Wochen.
    """
    t = (text or "").lower()
    treffer = []
    for m in _DAUER_RE.finditer(t):
        num_s, unit = m.group(1), m.group(2)
        n = int(num_s) if num_s.isdigit() else _ZAHLWORT.get(num_s)
        if not n or n <= 0:
            continue
        wochen = n * _WOCHEN_PRO_MONAT if unit.startswith("monat") else float(n)
        if not (1 <= wochen <= 156):        # plausibel: bis ~3 Jahre
            continue
        fenster = t[max(0, m.start() - 40):m.end() + 20]
        nah = any(k in fenster for k in _DAUER_KONTEXT)
        treffer.append((nah, unit.startswith("monat"), wochen))
    if not treffer:
        return None
    # Priorität: Kontextnähe, dann Monatsangabe, dann Reihenfolge.
    treffer.sort(key=lambda x: (not x[0], not x[1]))
    return treffer[0][2]


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


def _assign_termine_dates(rows, start_datum_str, factor=1.0, ziel_wochen=None):
    """Setzt je Ergebnis Liefertermin (nach HERMES-Abhängigkeitsrang) und Prüfmethode
    und sortiert die Zeilen in Abhängigkeitsreihenfolge.

    Hat der PL eine **Phasendauer** genannt (`ziel_wochen`), landet das letzte
    Ergebnis (Durchführungsfreigabe) genau am Phasenende, die übrigen anteilig davor –
    seine Planung ist massgebend. Sonst streckt `factor` (>=1) die Dauern nach
    Komplexität (die Phase Initialisierung wird erfahrungsgemäss zu kurz geplant).
    """
    if ziel_wochen and ziel_wochen > 0:
        factor = ziel_wochen / _MAX_TERMIN_RANG
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
    """Die Zaehlweise liegt im geteilten Baustein – EINE Rechenweise fuer alle
    Ergebnisse, nicht eine je Dokument."""
    from app.shared.versionierung import naechste_version
    return naechste_version(version_str, bump_type)
