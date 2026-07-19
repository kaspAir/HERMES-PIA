"""Rechtsgrundlagenanalyse – Phase A: ehrlicher Entwurf aus dem PIA.

Baut die Abschnitts-Antworten (Seeding aus dem PIA + beratender LLM-Entwurf),
speichert sie als ErgebnisEntwurf und erzeugt das Dokument über die generische
Generierung. Der PIA bleibt unangetastet.
"""
import json
import re

from app.domains.ergebnisse.models import ErgebnisEntwurf
from app.domains.ergebnisse.projektwissen import Projektwissen
from app.domains.ergebnisse.rechtsgrundlagen.grounding import ground_federal
from app.domains.ergebnisse.rechtsgrundlagen.proposals import analysiere
from app.domains.projekt.reference import ERG_PIA
from app.domains.rechtsquellen.fedlex import FedlexClient
from app.shared.database import SessionLocal

METHOD_ID = "rechtsgrundlagenanalyse"

# Datenschutz/Informationssicherheit gehören in die Schutzbedarfsanalyse, NICHT hierher.
_DATENSCHUTZ_KW = ("datenschutz", "isds", "informationssicherheit", "datensicherheit")
# Kantonale/kommunale Erlasse (bei reiner Bundes-Analyse ausblenden).
_KANTONAL_KW = ("kantonal", "kommunal", "submissionsgesetz", "kant.")

# Tabellen-Abschnitte mit ihren Spalten-Schlüsseln (für Leerzeilen-Fallback).
_TABELLEN = {
    "bestehende_rechtsgrundlagen": ("rechtsgrundlage", "beschreibung"),
    "bevorstehende_aenderungen": ("rechtsgrundlage", "beschreibung", "auswirkung"),
    "identifizierte_luecken": ("luecke", "beschreibung"),
    "vorschlaege_deckung": ("luecke", "vorschlag"),
    "product_compliance": ("compliance", "beschreibung"),
}


class RechtsgrundlagenService:
    def __init__(self, interview_service, projekt_service, generation_service,
                 llm=None, fedlex=None):
        self.interview = interview_service
        self.projekte = projekt_service
        self.generation = generation_service
        self.llm = llm
        self.fedlex = fedlex or FedlexClient()   # Phase B: Bundes-Fundstellen (Fedlex)

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

    def _grounding(self, wissen):
        """Verifizierte Bundes-Fundstellen (Fedlex) zu ALLEN genannten Gesetzen – für die
        Links in 0.2/0.3 und die Beschreibung in Kap. 1. {} bei Störung."""
        try:
            return ground_federal(wissen.genannte_rechtsgrundlagen(), wissen.ebene, self.fedlex)
        except Exception:  # noqa: BLE001 – Grounding-Störung darf den Entwurf nicht kippen
            return {}

    @staticmethod
    def _ist_datenschutz(name):
        return any(k in (name or "").lower() for k in _DATENSCHUTZ_KW)

    @staticmethod
    def _ist_kantonal(name):
        return any(k in (name or "").lower() for k in _KANTONAL_KW)

    def _relevante_gesetze(self, wissen):
        """Genannte Gesetze, gefiltert für Kap. 1: Datenschutz/Infosec raus (Schutzbedarfs-
        analyse); bei reiner Bundes-Analyse keine kantonalen/kommunalen Erlasse."""
        ebenen = (wissen.ebene or "").lower()
        nur_bund = "bund" in ebenen and "kanton" not in ebenen and "kommun" not in ebenen
        out = []
        for name in wissen.genannte_rechtsgrundlagen():
            if self._ist_datenschutz(name):
                continue
            if nur_bund and self._ist_kantonal(name):
                continue
            out.append(name)
        return out

    @staticmethod
    def _dokumente(rows, grounded):
        """Referenzierte/Mitgeltende übernehmen; bei Bundes-Treffer SR + Fedlex-Link."""
        out = []
        for r in rows:
            name = str(r.get("name", "")).strip()
            g = grounded.get(name)
            out.append({"name": name,
                        "link": f"SR {g['sr']} – {g['url']}" if g else ""})
        return out or [{"name": "", "link": ""}]

    def _definitionen(self, wissen):
        """Definitionen/Abkürzungen aus dem PIA übernehmen, ergänzt um die Kürzel der
        genannten Gesetze (z.B. StPO, PrHG). Fallback: Standard-Abkürzungen."""
        rows, seen = [], set()

        def add(abk, bedeutung):
            k = abk.lower()
            if abk and k not in seen:
                seen.add(k)
                rows.append({"abkuerzung": abk, "bedeutung": bedeutung})

        for r in wissen.definitionen():
            add(str(r.get("abkuerzung", "")).strip(), str(r.get("bedeutung", "")).strip())
        for abk, bed in (("CHF", "Schweizer Franken"), ("PT", "Personentage"),
                         ("AG", "Auftraggeber"), ("PL", "Projektleiter")):
            add(abk, bed)
        for name in wissen.genannte_rechtsgrundlagen():
            for abk in re.findall(r"\(([A-ZÄÖÜ][A-Za-zÄÖÜäöü./-]{1,12})\)", name):
                add(abk, re.sub(r"\s*\([^)]*\)", "", name).strip())
        return rows or [{"abkuerzung": "", "bedeutung": ""}]

    def _bestehende(self, namen, vorschlag, grounded):
        """Die (gefilterten) relevanten Gesetze aufführen. Bei Bundes-Treffer die
        VERIFIZIERTE Fundstelle (offizieller Titel + SR + Fedlex-Link) als Beschreibung;
        sonst die allgemeine LLM-Beschreibung. Nie eine Fundstelle erfinden."""
        vorschlag = self._bereinige(vorschlag)
        by_name = {r.get("rechtsgrundlage", "").lower(): r for r in vorschlag}
        rows = []
        for name in namen:
            llm_row = by_name.pop(name.lower(), None)
            g = grounded.get(name)
            if g:
                beschreibung = f"{g['titel']} (SR {g['sr']}) – {g['url']}"
            else:
                beschreibung = (llm_row or {}).get("beschreibung", "")
            rows.append({"rechtsgrundlage": name, "beschreibung": beschreibung})
        return rows or [{"rechtsgrundlage": "", "beschreibung": ""}]

    def build_answers(self, wissen):
        grounded = self._grounding(wissen)
        relevante = self._relevante_gesetze(wissen)
        v = analysiere(wissen, self.llm, grounding=grounded, bestehende_namen=relevante)
        return {
            "referenzierte_dokumente": {"extracted": self._dokumente(wissen.referenzierte(), grounded)},
            "mitgeltende_unterlagen": {"extracted": self._dokumente(wissen.mitgeltende(), grounded)},
            "definitionen": {"extracted": self._definitionen(wissen)},
            "bestehende_rechtsgrundlagen": {"extracted": self._bestehende(relevante, v.get("bestehende"), grounded)},
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
