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
from app.domains.rechtsquellen.lexfind import LexfindClient
from app.domains.rechtsquellen.recherche import RechercheClient
from app.domains.skills import load_skills
from app.domains.rechtsquellen.kantone import sammlung_link
from app.shared.database import SessionLocal

METHOD_ID = "rechtsgrundlagenanalyse"

# Datenschutz/Informationssicherheit gehören in die Schutzbedarfsanalyse, NICHT hierher.
_DATENSCHUTZ_KW = ("datenschutz", "isds", "informationssicherheit", "datensicherheit")
# Kantonale/kommunale Erlasse (bei reiner Bundes-Analyse ausblenden).
_KANTONAL_KW = ("kantonal", "kommunal", "submissionsgesetz", "kant.")
# Was in Kap. 1 als Rechtsgrundlage zählt (Gesetz/Verordnung/…), und was NICHT
# (Konzepte/Strategien/Dokumentationen sind keine Rechtsgrundlagen).
_LEGAL_TERMS = ("gesetz", "verordnung", "reglement", "recht", "ordnung", "erlass",
                "beschluss", "abkommen", "konkordat", "vereinbarung", "richtlinie",
                "verfassung", "konvention", "übereinkommen", "uebereinkommen", "dekret")
_NICHT_LEGAL = ("betriebskonzept", "konzept", "strategie", "dokumentation", "handbuch")

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
                 llm=None, fedlex=None, recherche=None):
        self.interview = interview_service
        self.projekte = projekt_service
        self.generation = generation_service
        self.llm = llm
        self.fedlex = fedlex or FedlexClient()   # Offline-SR-Index (immer verfügbar)
        # Vorgabe bewusst OHNE Netz: der Service allein telefoniert nie nach aussen.
        # Die Live-Recherche (lexfind) wird in der Factory aus der Konfiguration
        # eingehängt – so entscheidet das Deployment, ob Suchbegriffe den Host
        # verlassen, und Tests bleiben ohne Netzwerk.
        self.recherche = recherche or RechercheClient(lexfind=None, index=self.fedlex)

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

    def _ohne_datenschutz(self, rows):
        """Datenschutz-/Informationssicherheits-Einträge entfernen – sie gehören in die
        Schutzbedarfsanalyse, nicht in die Rechtsgrundlagenanalyse (HERMES-Methodengrenze).
        Deterministisches Sicherheitsnetz zusätzlich zum LLM-Guardrail."""
        return [r for r in (rows or [])
                if not (isinstance(r, dict)
                        and self._ist_datenschutz(" ".join(str(v) for v in r.values())))]

    def _grounding(self, wissen):
        """Verifizierte Bundes-Fundstellen (Fedlex) zu ALLEN genannten Gesetzen – für die
        Links in 0.2/0.3 und die Beschreibung in Kap. 1. {} bei Störung."""
        try:
            return ground_federal(wissen.genannte_rechtsgrundlagen(), wissen.ebene,
                                  self.recherche, kanton=wissen.kanton)
        except Exception:  # noqa: BLE001 – Grounding-Störung darf den Entwurf nicht kippen
            return {}

    def _grounding_names(self, namen, ebene, kanton=None):
        """Verifizierte Fundstellen (live über lexfind, sonst Offline-Index) zu einer
        beliebigen Namensliste – Bund und, wenn gesetzt, der Kanton."""
        try:
            return ground_federal(namen, ebene, self.recherche, kanton=kanton)
        except Exception:  # noqa: BLE001
            return {}

    @staticmethod
    def _ist_datenschutz(name):
        return any(k in (name or "").lower() for k in _DATENSCHUTZ_KW)

    @staticmethod
    def _ist_kantonal(name):
        return any(k in (name or "").lower() for k in _KANTONAL_KW)

    @staticmethod
    def _ist_rechtsgrundlage(name):
        """Kap. 1 führt nur echte Rechtsgrundlagen (Gesetz/Verordnung/…), keine
        Konzepte/Strategien/Dokumentationen (z.B. Betriebskonzept)."""
        n = (name or "").lower()
        if any(t in n for t in _NICHT_LEGAL):
            return False
        return any(t in n for t in _LEGAL_TERMS)

    def _kap1_geeignet(self, name, ebene):
        ebenen = (ebene or "").lower()
        nur_bund = "bund" in ebenen and "kanton" not in ebenen and "kommun" not in ebenen
        if self._ist_datenschutz(name):
            return False
        if nur_bund and self._ist_kantonal(name):
            return False
        return self._ist_rechtsgrundlage(name)

    @staticmethod
    def _ohne_dubletten(namen, grounded):
        """Denselben Erlass nur EINMAL in Kap. 1 aufführen.

        Der PIA und das LLM schreiben denselben Erlass oft verschieden lang –
        gemessen standen «Bundesgesetz über die Verwendung von DNA-Profilen im
        Strafverfahren und zur Identifizierung von unbekannten oder vermissten
        Personen (DNA-Profil-Gesetz)» und dieselbe Bestimmung in der Kurzform
        zweimal untereinander. Ein Namensvergleich erkennt das nicht – die
        verifizierte Fundstelle schon: gleiche Sammlung + gleiche Nummer =
        derselbe Erlass. Behalten wird der zuerst genannte (der ausführlichere
        aus dem PIA), Ungegroundetes bleibt unangetastet.
        """
        out, gesehen = [], set()
        for name in namen:
            g = grounded.get(name)
            if g:
                schluessel = ((g.get("entity") or "CH").upper(), g.get("sr", ""))
                if schluessel in gesehen:
                    continue
                gesehen.add(schluessel)
            out.append(name)
        return out

    def _relevante_gesetze(self, wissen):
        """Aus dem PIA genannte, für Kap. 1 geeignete Rechtsgrundlagen (gefiltert)."""
        return [n for n in wissen.genannte_rechtsgrundlagen()
                if self._kap1_geeignet(n, wissen.ebene)]

    def _kantonslink(self, wissen):
        """Link zur kantonalen Gesetzessammlung, falls Kantonsebene + Kanton gewählt."""
        if "kanton" in (wissen.ebene or "").lower() and wissen.kanton:
            url = sammlung_link(wissen.kanton)
            if url:
                return f"Kantonale Sammlung {wissen.kanton}: {url}"
        return ""

    def _fundstelle(self, name, grounded, kantonslink):
        """Verifizierte Fundstelle bevorzugt; sonst kantonaler Sammlungs-Link für
        kantonale Gesetze; sonst leer. Nie eine Nummer erfinden."""
        g = grounded.get(name)
        if g:
            # 'SR' ist die Systematik des BUNDES. Ein kantonaler Treffer trägt die
            # Nummer seiner eigenen Sammlung – dort wäre 'SR' schlicht falsch.
            ent = (g.get("entity") or "CH").upper()
            praefix = "SR" if ent in ("CH", "") else ent
            return f"{praefix} {g['sr']} – {g['url']}" if g.get("url") \
                else f"{praefix} {g['sr']}"
        if kantonslink and self._ist_rechtsgrundlage(name):
            return kantonslink
        return ""

    def _dokumente(self, rows, grounded, kantonslink=""):
        """Referenzierte/Mitgeltende übernehmen; Bundes-SR-Link bzw. kantonaler
        Sammlungs-Link ergänzen (nur bei echten Rechtsgrundlagen)."""
        out = []
        for r in rows:
            name = str(r.get("name", "")).strip()
            out.append({"name": name, "link": self._fundstelle(name, grounded, kantonslink)})
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

    def _bestehende(self, namen, vorschlag, grounded, kantonslink=""):
        """Die (gefilterten) relevanten Gesetze aufführen. Bei Bundes-Treffer die
        VERIFIZIERTE Fundstelle (offizieller Titel + SR + Fedlex-Link); sonst die
        LLM-Beschreibung, bei Kantonsebene ergänzt um den kantonalen Sammlungs-Link.
        Nie eine Fundstelle erfinden."""
        vorschlag = self._bereinige(vorschlag)
        by_name = {r.get("rechtsgrundlage", "").lower(): r for r in vorschlag}
        rows = []
        for name in namen:
            llm_row = by_name.pop(name.lower(), None)
            g = grounded.get(name)
            if g:
                ent = (g.get("entity") or "CH").upper()
                praefix = "SR" if ent in ("CH", "") else ent
                beschreibung = f"{g['titel']} ({praefix} {g['sr']})"
                if g.get("url"):
                    beschreibung += f" – {g['url']}"
            else:
                beschreibung = (llm_row or {}).get("beschreibung", "")
                if kantonslink:
                    beschreibung = f"{beschreibung} [{kantonslink}]".strip()
            rows.append({"rechtsgrundlage": name, "beschreibung": beschreibung})
        return rows or [{"rechtsgrundlage": "", "beschreibung": ""}]

    def _luecken(self, vorschlag):
        """Lücken übernehmen; wenn KEINE identifiziert wurden, das explizit ausweisen
        (es muss nicht um jeden Preis eine Lücke gefunden werden)."""
        rows = self._bereinige(vorschlag)
        if rows:
            return rows
        return [{"luecke": "Keine Lücke identifiziert",
                 "beschreibung": "Für die im Projekt geplanten Tätigkeiten besteht nach "
                                 "dieser Analyse eine Rechtsgrundlage."}]

    def build_answers(self, wissen, tenant_id=None):
        relevante = self._relevante_gesetze(wissen)
        # Skills laden. Mapping Skill↔Schritt: der Entwurfs-/Kartierungsschritt
        # nutzt NUR die Kartierung – die weiteren Skills der Kette (Gap, Würdigung,
        # Handlungsoptionen) gehören in ihre eigenen, später folgenden Schritte.
        # applies_to sichert zusätzlich, dass nie ein fremder Skill hereinkommt.
        # Ohne Skills-Ordner ist das Bündel leer -> Verhalten wie vor den Skills.
        bundle = load_skills(METHOD_ID, tenant_id=tenant_id,
                             only={"rechtsgrundlagen-kartierung"})
        # LLM ermittelt selbst die einschlägigen Rechtsgrundlagen (auch im PIA nicht
        # genannte, z.B. StReG/StReV) und prüft je Ziel, ob eine Grundlage besteht.
        v = analysiere(wissen, self.llm, bestehende_namen=relevante, skill_bundle=bundle)
        entdeckt = [str(r.get("rechtsgrundlage", "")).strip()
                    for r in (v.get("bestehende") or []) if isinstance(r, dict)]
        # Kap.-1-Kandidaten: PIA-Recht + vom LLM ergänzte, gefiltert (echte Gesetze).
        kap1, gesehen = [], set()
        for name in relevante + entdeckt:
            if name and name.lower() not in gesehen and self._kap1_geeignet(name, wissen.ebene):
                gesehen.add(name.lower())
                kap1.append(name)
        # Alle Namen (PIA-Verweise für 0.2/0.3 + Kap.-1-Recht) einmal gegen Fedlex prüfen.
        alle_namen = list({*wissen.genannte_rechtsgrundlagen(), *kap1})
        grounded = self._grounding_names(alle_namen, wissen.ebene, wissen.kanton)
        kap1 = self._ohne_dubletten(kap1, grounded)
        klink = self._kantonslink(wissen)
        return {
            # Nachweis (Auditierbarkeit): welche Skill-Version(en) diesen Entwurf
            # gesteuert haben. Reservierter Schlüssel – kein Dokumentabschnitt.
            "_skills": bundle.versions,
            "referenzierte_dokumente": {"extracted": self._dokumente(wissen.referenzierte(), grounded, klink)},
            "mitgeltende_unterlagen": {"extracted": self._dokumente(wissen.mitgeltende(), grounded, klink)},
            "definitionen": {"extracted": self._definitionen(wissen)},
            "bestehende_rechtsgrundlagen": {"extracted": self._bestehende(kap1, v.get("bestehende"), grounded, klink)},
            "bevorstehende_aenderungen": {"extracted": self._rows_or_blank(
                v.get("bevorstehende"), _TABELLEN["bevorstehende_aenderungen"])},
            "identifizierte_luecken": {"extracted": self._luecken(v.get("luecken"))},
            "vorschlaege_deckung": {"extracted": self._rows_or_blank(
                v.get("vorschlaege"), _TABELLEN["vorschlaege_deckung"])},
            "product_compliance": {"extracted": self._rows_or_blank(
                self._ohne_datenschutz(v.get("compliance")), _TABELLEN["product_compliance"])},
            "konsequenzen": {"extracted": {"text": (v.get("konsequenzen") or "").strip()}},
            "empfehlung": {"extracted": {"text": (v.get("empfehlung") or "").strip()}},
        }

    def grounding_status(self, projekt):
        """Wie viele Kap.-1-Rechtsgrundlagen sind mit einer Fedlex-Fundstelle verknüpft?
        (Diagnose: 0 trotz Bundesebene => Fedlex vom Host nicht erreichbar.)"""
        entwurf = self.get_entwurf(projekt.id)
        if not entwurf or not entwurf.answers_json:
            return None
        rows = (json.loads(entwurf.answers_json).get("bestehende_rechtsgrundlagen") or {}).get("extracted") or []
        mit = sum(1 for r in rows if "SR " in str(r.get("beschreibung", "")))
        gesamt = sum(1 for r in rows if str(r.get("rechtsgrundlage", "")).strip())
        return {"verknuepft": mit, "gesamt": gesamt}

    # ---- Persistenz ----------------------------------------------------- #
    def get_entwurf(self, projekt_id):
        return SessionLocal().query(ErgebnisEntwurf).filter(
            ErgebnisEntwurf.projekt_id == int(projekt_id),
            ErgebnisEntwurf.ergebnistyp == METHOD_ID,
        ).first()

    def erzeuge_entwurf(self, projekt, ebene=None, kanton=None):
        """Baut den Entwurf aus dem PIA (+ Detailfragen) und speichert ihn."""
        wissen, _ = self.projektwissen(projekt, ebene=ebene, kanton=kanton)
        answers = self.build_answers(wissen, tenant_id=projekt.org_id)
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
            answers = self.build_answers(wissen, tenant_id=projekt.org_id)
        _, session = self._pia(projekt)
        metadata = self._metadata(projekt, session)
        return self.generation.generate(METHOD_ID, answers, metadata)
