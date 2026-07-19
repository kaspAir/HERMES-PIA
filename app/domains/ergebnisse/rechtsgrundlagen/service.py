"""Rechtsgrundlagenanalyse – Phase A: ehrlicher Entwurf aus dem PIA.

Baut die Abschnitts-Antworten (Seeding aus dem PIA + beratender LLM-Entwurf),
speichert sie als ErgebnisEntwurf und erzeugt das Dokument über die generische
Generierung. Der PIA bleibt unangetastet.
"""
import json

from app.domains.ergebnisse.models import ErgebnisEntwurf
from app.domains.ergebnisse.projektwissen import Projektwissen
from app.domains.ergebnisse.rechtsgrundlagen.proposals import analysiere
from app.domains.projekt.reference import ERG_PIA
from app.shared.database import SessionLocal

METHOD_ID = "rechtsgrundlagenanalyse"

# Tabellen-Abschnitte mit ihren Spalten-Schlüsseln (für Leerzeilen-Fallback).
_TABELLEN = {
    "bestehende_rechtsgrundlagen": ("rechtsgrundlage", "beschreibung"),
    "bevorstehende_aenderungen": ("rechtsgrundlage", "beschreibung", "auswirkung"),
    "identifizierte_luecken": ("luecke", "beschreibung"),
    "vorschlaege_deckung": ("luecke", "vorschlag"),
    "product_compliance": ("compliance", "beschreibung"),
}


class RechtsgrundlagenService:
    def __init__(self, interview_service, projekt_service, generation_service, llm=None):
        self.interview = interview_service
        self.projekte = projekt_service
        self.generation = generation_service
        self.llm = llm

    # ---- PIA-Zugriff (nur lesen) ---------------------------------------- #
    def _pia(self, projekt):
        for erg in self.projekte.ergebnisse(projekt.id):
            if erg.ergebnistyp == ERG_PIA:
                s = self.interview.session_for_ergebnis(erg.id)
                if s and s.answers_json:
                    return json.loads(s.answers_json), s
        return {}, None

    def projektwissen(self, projekt, ebene=None, kanton=None):
        pia_answers, session = self._pia(projekt)
        return Projektwissen(pia_answers, ebene=ebene, kanton=kanton), session

    # ---- Entwurf bauen -------------------------------------------------- #
    @staticmethod
    def _bereinige(rows):
        """Nur Zeilen mit Inhalt behalten (leere Vorschläge verwerfen)."""
        out = []
        for r in rows or []:
            if isinstance(r, dict) and any(str(v).strip() for v in r.values()):
                out.append({k: str(v).strip() for k, v in r.items() if str(v).strip()})
        return out

    def _rows_or_blank(self, rows, spalten):
        rows = self._bereinige(rows)
        return rows if rows else [{k: "" for k in spalten}]

    def _bestehende(self, wissen, vorschlag):
        """Genannte Gesetze aus dem PIA garantiert aufführen; LLM-Beschreibung mergen.
        Keine erfundenen Fundstellen."""
        vorschlag = self._bereinige(vorschlag)
        by_name = {r.get("rechtsgrundlage", "").lower(): r for r in vorschlag}
        rows = []
        for name in wissen.genannte_rechtsgrundlagen():
            treffer = by_name.pop(name.lower(), None)
            rows.append({"rechtsgrundlage": name,
                         "beschreibung": (treffer or {}).get("beschreibung", "")})
        rows.extend(by_name.values())          # zusätzliche LLM-Vorschläge anhängen
        return rows or [{"rechtsgrundlage": "", "beschreibung": ""}]

    def build_answers(self, wissen):
        v = analysiere(wissen, self.llm)
        return {
            "referenzierte_dokumente": {"extracted": [
                {"name": r.get("name", ""), "link": ""} for r in wissen.referenzierte()
            ] or [{"name": "", "link": ""}]},
            "mitgeltende_unterlagen": {"extracted": [
                {"name": r.get("name", ""), "link": ""} for r in wissen.mitgeltende()
            ] or [{"name": "", "link": ""}]},
            "bestehende_rechtsgrundlagen": {"extracted": self._bestehende(wissen, v.get("bestehende"))},
            "bevorstehende_aenderungen": {"extracted": self._rows_or_blank(
                v.get("bevorstehende"), _TABELLEN["bevorstehende_aenderungen"])},
            "identifizierte_luecken": {"extracted": self._rows_or_blank(
                v.get("luecken"), _TABELLEN["identifizierte_luecken"])},
            "vorschlaege_deckung": {"extracted": self._rows_or_blank(
                v.get("vorschlaege"), _TABELLEN["vorschlaege_deckung"])},
            "product_compliance": {"extracted": self._rows_or_blank(
                v.get("compliance"), _TABELLEN["product_compliance"])},
            "konsequenzen": {"extracted": {"text": (v.get("konsequenzen") or "").strip()}},
            "empfehlung": {"extracted": {"text": (v.get("empfehlung") or "").strip()}},
        }

    # ---- Persistenz ----------------------------------------------------- #
    def get_entwurf(self, projekt_id):
        return SessionLocal().query(ErgebnisEntwurf).filter(
            ErgebnisEntwurf.projekt_id == int(projekt_id),
            ErgebnisEntwurf.ergebnistyp == METHOD_ID,
        ).first()

    def erzeuge_entwurf(self, projekt, ebene=None, kanton=None):
        """Baut den Entwurf aus dem PIA (+ Detailfragen) und speichert ihn."""
        wissen, _ = self.projektwissen(projekt, ebene=ebene, kanton=kanton)
        answers = self.build_answers(wissen)
        db = SessionLocal()
        row = db.query(ErgebnisEntwurf).filter(
            ErgebnisEntwurf.projekt_id == projekt.id,
            ErgebnisEntwurf.ergebnistyp == METHOD_ID,
        ).first()
        if row is None:
            row = ErgebnisEntwurf(projekt_id=projekt.id, ergebnistyp=METHOD_ID)
            db.add(row)
        row.ebene, row.kanton = ebene, kanton
        row.answers_json = json.dumps(answers, ensure_ascii=False, indent=2)
        db.commit()
        db.refresh(row)
        return row

    # ---- Metadaten (Deckblatt) ------------------------------------------ #
    def _metadata(self, projekt, session):
        from app.domains.interview.extraction import detect_gender
        pl = (session.created_by if session else None) or ""
        ag = projekt.auftraggeber or (session.auftraggeber if session else None) or ""
        pl_g = detect_gender(self.llm, pl) if self.llm else "u"
        ag_g = detect_gender(self.llm, ag) if self.llm else "u"
        return {
            "projektname": projekt.name or "Projekt",
            "projektnummer": projekt.projektnummer or "",
            "verwaltungseinheit": projekt.verwaltungseinheit or "",
            "geschaeftsbereich": projekt.geschaeftsbereich or "",
            "autor": pl, "projektleiter": pl, "auftraggeber": ag,
            "projektleiter_weiblich": pl_g == "w", "auftraggeber_weiblich": ag_g == "w",
            "projektleiter_geschlecht": pl_g, "auftraggeber_geschlecht": ag_g,
            "autor_geschlecht": pl_g,
            "version": "0.1", "status": "in Arbeit", "klassifizierung": "Nicht klassifiziert",
        }

    # ---- Dokument erzeugen ---------------------------------------------- #
    def generate_docx(self, projekt):
        """Erzeugt die .docx aus dem gespeicherten Entwurf (oder baut ihn frisch)."""
        entwurf = self.get_entwurf(projekt.id)
        if entwurf and entwurf.answers_json:
            answers = json.loads(entwurf.answers_json)
        else:
            wissen, _ = self.projektwissen(projekt)
            answers = self.build_answers(wissen)
        _, session = self._pia(projekt)
        metadata = self._metadata(projekt, session)
        return self.generation.generate(METHOD_ID, answers, metadata)
