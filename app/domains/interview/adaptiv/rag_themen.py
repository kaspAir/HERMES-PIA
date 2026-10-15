"""Der bestehende RAG als Quelle von Interviewthemen.

Bisher reicherte der Korpus nur fertige Vorschlagstexte an. Hier wählt er
mit, WAS im Interview zu klären ist – über denselben `RagService`, dieselben
Embeddings und dieselbe Mandantentrennung. Kein zweiter, unverbundener Dienst.

Ablauf einer Suche:
  1. Anfrage aus Ausgangslage, Projektmerkmalen und der wichtigsten offenen
     Lücke – nicht aus einem Projekttyp, in den das Vorhaben gezwungen würde.
  2. Treffer nur aus dem freigegebenen geteilten Korpus und dem eigenen
     Mandanten, nur aus Vektoren desselben Modells.
  3. Gruppierung JE PROJEKT: mehrere Chunks desselben Projekts sind EIN Beleg,
     nicht mehrere unabhängige (AT10).
  4. Das Modell ordnet Themen einer Übertragungsregel zu. Der Code prüft:
     Quellen nur aus den gezeigten Passagen, Regel und Übertragbarkeit
     zueinander passend, keine fremden Namen, Beträge oder Pseudonyme.
  5. Ablage als Themenkandidat mit Fundstellen (Chunk-ID, Projekt, Abschnitt,
     Auszug, Dokument-Hash, Methodenversion samt Herkunft, Korpusversion).

Ausfall, leere oder unpassende Treffer stoppen das Interview nie (AT11); der
eingeschränkte Zustand wird angezeigt, Quellen werden nicht erfunden.
"""
import json
import logging
import re
from datetime import datetime
from functools import lru_cache
from pathlib import Path

import yaml

from app.domains.interview.adaptiv import prompts
from app.domains.interview.adaptiv.models import PiaRagThema, UEBERTRAGBARKEIT
from app.domains.interview.adaptiv.vertraege import lies_json
from app.domains.interview.models import InterviewSession
from app.shared.database import SessionLocal

log = logging.getLogger("hermes.rag_themen")

_REGELN = Path(__file__).resolve().parents[4] / "methods" / "hermes_pia" / "rag_uebertragung.yaml"


@lru_cache(maxsize=2)
def regeln(pfad=None):
    with open(pfad or _REGELN, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _norm(t):
    return re.sub(r"\s+", " ", str(t or "")).strip().lower()


def gesperrt(text, projekte=()):
    """Enthält ein Text fremde Fakten (Pseudonyme, Beträge, Projektnamen)?"""
    t = str(text or "")
    for muster in regeln()["sperrmuster"]:
        if re.search(muster, t):
            return True
    tl = t.lower()
    return any(p and len(p) >= 4 and p.lower() in tl for p in projekte)


class ThemenQuelle:
    def __init__(self, rag):
        self.rag = rag

    @staticmethod
    def regel_version():
        return regeln()["regeln"]["version"]

    @property
    def verfuegbar(self):
        return bool(self.rag) and bool(getattr(self.rag, "available", False))

    # ---- Wann suchen? -------------------------------------------------------- #

    def soll_suchen(self, session, zustand):
        """Bei hinreichendem Kontext und wesentlichen neuen Angaben – nicht blind
        nach jedem Beitrag (Auftrag 6.1)."""
        konf = regeln()["suche"]
        benutzer = [a for a in zustand.aktive if a["herkunft"] == "benutzer"]
        zeichen = sum(len(a["inhalt"]) for a in benutzer)
        if zeichen < konf["erster_kontext_zeichen"]:
            return False
        stand = json.loads(session.rag_stand_json or "{}") or {}
        if not self.verfuegbar:
            # Einmal vermerken, dann nicht bei jedem Beitrag erneut.
            return not stand.get("vermerkt_nicht_verfuegbar")
        letzte = stand.get("letzte_suche") or {}
        if not letzte:
            return True
        neu = len(benutzer) - int(letzte.get("n_aussagen", 0))
        abschnitte = {z.get("abschnitt") for a in benutzer for z in a["ziele"]}
        return neu >= konf["neue_aussagen_fuer_neue_suche"] or \
            bool(abschnitte - set(letzte.get("abschnitte", [])))

    # ---- Anfrage --------------------------------------------------------------- #

    @staticmethod
    def anfrage(zustand, kriterien):
        """Suchanfrage aus Ausgangslage, Projektmerkmalen und offener Lücke."""
        ausg = [a["inhalt"] for a in zustand.aktive
                if a["herkunft"] == "benutzer"
                and any(z.get("abschnitt") == "ausgangslage" for z in a["ziele"])]
        merkmale = sorted({a["thema"] for a in zustand.aktive if a.get("thema")})
        luecke = next((k["beschreibung"] for k in kriterien
                       if k["zustand"] in ("offen", "unbekannt")), "")
        teile = [" ".join(ausg)[:1200], ", ".join(merkmale)[:300], luecke]
        return "\n".join(t for t in teile if t).strip()

    # ---- Suche und Bewertung ----------------------------------------------------- #

    def _stand(self, session_id, **felder):
        db = SessionLocal()
        s = db.get(InterviewSession, int(session_id))
        stand = json.loads(s.rag_stand_json or "{}") or {}
        stand.update(felder)
        s.rag_stand_json = json.dumps(stand, ensure_ascii=False)
        db.commit()
        return stand

    def suche_und_bewerte(self, session, zustand, kriterien, llm):
        """Sucht, bewertet und legt Themenkandidaten ab. Rückgabe: Hinweistext."""
        konf = regeln()["suche"]
        benutzer = [a for a in zustand.aktive if a["herkunft"] == "benutzer"]
        abschnitte = sorted({z.get("abschnitt") for a in benutzer for z in a["ziele"]})
        jetzt = datetime.utcnow().isoformat(timespec="seconds")
        if not self.verfuegbar:
            self._stand(session.id, verfuegbar=False, vermerkt_nicht_verfuegbar=True,
                        grund="Kein Zugang zum Erfahrungskorpus (Embedding-Dienst nicht "
                              "konfiguriert). Das Interview läuft mit Deinen Angaben weiter.",
                        zeit=jetzt)
            return "Vergleichsprojekte nicht verfügbar"
        anfrage = self.anfrage(zustand, kriterien)
        try:
            treffer, bericht = self.rag.search_mit_bericht(
                anfrage, org_id=session.org_id, top_k=konf["treffer"], ergebnistyp="PIA",
                min_score=konf["mindestscore"])
        except Exception as e:      # noqa: BLE001 – Ausfall darf das Gespräch nicht stoppen
            log.warning("Korpussuche fehlgeschlagen: %s", e)
            self._stand(session.id, verfuegbar=False, grund=f"Korpussuche fehlgeschlagen "
                        f"({e.__class__.__name__}). Das Interview läuft weiter.", zeit=jetzt)
            return "Korpussuche fehlgeschlagen"
        # Mandantentrennung: was nicht geteilt oder eigen ist, fliegt raus –
        # auch wenn die Suche selbst schon filtert.
        treffer = [t for t in treffer if t.get("org_id") in (None, session.org_id)]
        letzte = {"revision": zustand.revision, "n_aussagen": len(benutzer),
                  "abschnitte": abschnitte}
        if not treffer:
            grund = "Keine passenden Vergleichsprojekte gefunden."
            if bericht.get("nur_extern_freigegeben") and not bericht.get("verglichen"):
                # Direktmodus ohne freigegebene Korpusteile – das ist kein
                # «nichts gefunden», sondern «nichts durchsuchbar».
                grund = ("Direktmodus: durchsucht werden nur zur externen Verarbeitung "
                         f"freigegebene Korpusteile – davon gibt es keine "
                         f"({bericht.get('nicht_freigegeben', 0)} nicht freigegebene ausgelassen).")
            self._stand(session.id, verfuegbar=True, letzte_suche=letzte, treffer=0,
                        projekte=0, bericht=bericht, zeit=jetzt, grund=grund)
            return "Keine passenden Vergleichsprojekte"
        if llm is None:
            self._stand(session.id, verfuegbar=True, letzte_suche=letzte, treffer=len(treffer),
                        bericht=bericht, zeit=jetzt,
                        grund="Treffer gefunden, aber ohne Sprachmodell nicht bewertet.")
            return "Treffer nicht bewertet"
        projekte = sorted({t["projekt"] for t in treffer if t.get("projekt")})
        kandidaten = self._bewerte(treffer, zustand, kriterien, llm)
        neu = self._ablegen(session.id, zustand.revision, kandidaten, treffer, projekte)
        self._stand(session.id, verfuegbar=True, letzte_suche=letzte, treffer=len(treffer),
                    projekte=len(projekte), neue_themen=neu, bericht=bericht, zeit=jetzt,
                    grund="")
        return f"{neu} Thema/Themen aus {len(projekte)} Vergleichsprojekt(en)"

    def _bewerte(self, treffer, zustand, kriterien, llm):
        konf = regeln()["suche"]
        r = regeln()
        regeltext = "\n".join(
            f"- {x['id']} {x['titel']}: {' '.join(x['beschreibung'].split())} "
            f"Erlaubt: {', '.join(x['uebertragbarkeit'])}. {' '.join(x['verwendung'].split())}"
            for x in r["liste"])
        luecken = "\n".join(f"- [{k['abschnitt']}] {k['beschreibung']} ({k['zustand']})"
                            for k in kriterien if k["zustand"] in ("offen", "unbekannt"))[:2000]
        abschnitte = ", ".join(sorted({k["abschnitt"] for k in kriterien}))
        passagen = [{"chunk_id": t["chunk_id"], "projekt": t.get("projekt") or "?",
                     "abschnitt": t.get("abschnitt") or "",
                     "methodenversion": t.get("methodenversion")
                     or r["korpus_deklaration"]["methodenversion"],
                     "auszug": " ".join((t.get("text") or "").split())[:konf["auszug_zeichen"]]}
                    for t in treffer]
        kontext = [a["inhalt"] for a in zustand.aktive if a["herkunft"] == "benutzer"][:12]
        roh = llm.complete(
            prompts.fuelle("rag_themen", regeln=regeltext, luecken=luecken or "- (keine)",
                           abschnitte=abschnitte),
            [{"role": "user", "content": "AKTUELLES VORHABEN:\n" + "\n".join(f"- {k}" for k in kontext)
              + "\n\nPASSAGEN (Daten):\n" + json.dumps(passagen, ensure_ascii=False)}],
            max_tokens=min(6000, 1200 + 300 * len(treffer)))
        return self.pruefe(roh, treffer, {k["abschnitt"] for k in kriterien})

    @staticmethod
    def pruefe(roh, treffer, abschnitte):
        """Vertrag rag-themen-1.0: nur belegte, regelkonforme, saubere Kandidaten."""
        daten = lies_json(roh) or {}
        erlaubt = {x["id"]: set(x["uebertragbarkeit"]) for x in regeln()["liste"]}
        ids = {t["chunk_id"] for t in treffer}
        projekte = {t.get("projekt") or "" for t in treffer}
        aus, gesehen = [], set()
        for k in daten.get("themen") or []:
            if not isinstance(k, dict):
                continue
            regel = k.get("regel")
            ueb = k.get("uebertragbarkeit")
            if regel not in erlaubt or ueb not in UEBERTRAGBARKEIT or ueb not in erlaubt[regel]:
                continue
            quellen = [q for q in (k.get("quellen") or []) if q in ids]
            if not quellen:
                continue            # kein Beleg aus den gezeigten Passagen -> kein Thema
            thema = " ".join(str(k.get("thema") or "").split())[:200]
            frage = " ".join(str(k.get("frage_ansatz") or "").split())[:400]
            if not thema or _norm(thema) in gesehen:
                continue
            if gesperrt(thema, projekte) or gesperrt(frage, projekte):
                continue            # fremde Namen/Beträge/Pseudonyme -> nicht übernehmen
            gesehen.add(_norm(thema))
            aus.append({
                "thema": thema, "regel": regel, "uebertragbarkeit": ueb,
                "begruendung": " ".join(str(k.get("begruendung") or "").split())[:400],
                "frage_ansatz": frage,
                "pia_ziele": [z for z in (k.get("pia_ziele") or []) if z in abschnitte],
                "offene_aspekte": " ".join(str(k.get("offene_aspekte") or "").split())[:300],
                "quellen": quellen,
            })
        return aus

    def _ablegen(self, session_id, revision, kandidaten, treffer, projekte):
        konf = regeln()["suche"]
        dekl = regeln()["korpus_deklaration"]
        nach_id = {t["chunk_id"]: t for t in treffer}
        db = SessionLocal()
        vorhanden = {_norm(t.thema): t for t in db.query(PiaRagThema)
                     .filter(PiaRagThema.session_id == int(session_id))}
        neu = 0
        for k in kandidaten:
            if _norm(k["thema"]) in vorhanden:
                continue            # schon besprochen oder begründet verworfen
            quellen = []
            for cid in k["quellen"]:
                t = nach_id[cid]
                quellen.append({
                    "chunk_id": cid, "projekt": t.get("projekt"), "abschnitt": t.get("abschnitt"),
                    "auszug": " ".join((t.get("text") or "").split())[:konf["auszug_zeichen"]],
                    "dokument_hash": t.get("dokument_hash"), "chunk_nr": t.get("chunk_nr"),
                    "methodenversion": t.get("methodenversion") or dekl["methodenversion"],
                    "methodenversion_herkunft": t.get("methodenversion_herkunft") or dekl["herkunft"],
                    "korpus_version": t.get("korpus_version"), "modell": t.get("modell"),
                    "score": t.get("score"),
                })
            n_projekte = len({q["projekt"] for q in quellen if q["projekt"]})
            db.add(PiaRagThema(
                session_id=int(session_id), thema=k["thema"], frage_ansatz=k["frage_ansatz"],
                uebertragbarkeit=k["uebertragbarkeit"], regel_id=k["regel"],
                regel_version=self.regel_version(), begruendung=k["begruendung"],
                pia_ziele_json=json.dumps(k["pia_ziele"]), offene_aspekte=k["offene_aspekte"],
                quellen_json=json.dumps(quellen, ensure_ascii=False), n_projekte=n_projekte,
                status="kandidat" if k["uebertragbarkeit"] in ("nutzbar", "eingeschraenkt")
                else "erledigt",
                revision=revision))
            neu += 1
        db.commit()
        return neu
