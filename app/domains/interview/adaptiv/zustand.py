"""Der gemeinsame, versionierte Projektzustand – lesen, sichern, ändern.

Drei Regeln, die alles andere tragen:

1. **Erst sichern, dann verarbeiten.** Ein Beitrag wird gespeichert, BEVOR ein
   Modell aufgerufen wird. Fällt die Verarbeitung aus, ist nichts verloren.
2. **Keine Sperre während eines Modellaufrufs.** Gelesen wird in einer kurzen
   Transaktion, das Modell läuft ohne offene Datenbank, geschrieben wird in
   einer zweiten kurzen Transaktion – gegen den DANN aktuellen Stand.
3. **Jede Änderung zählt die Revision hoch.** Anzeige, offene Punkte und
   Dokumentvorschau beruhen auf derselben Revision; eine verspätete Antwort
   kann einen neueren Stand nicht überschreiben.

Frühere Aussagen werden nie überschrieben: eine Korrektur legt eine neue
Aussage an und markiert die alte als ersetzt. Originalbeiträge bleiben, wie
sie eingegangen sind.
"""
import json
from dataclasses import dataclass, field

from app.domains.interview.adaptiv.models import (
    PiaAussage, PiaKonflikt, PiaNachricht, PiaRagThema, PiaRueckmeldung,
)
from app.domains.interview.models import InterviewSession
from app.shared.database import SessionLocal


# ---- Lesemodell --------------------------------------------------------------- #

@dataclass
class Zustand:
    """Ein Schnappschuss des Zustands auf EINER Revision."""
    session_id: int
    revision: int
    aussagen: list = field(default_factory=list)       # alle, inkl. ersetzt/verworfen
    konflikte: list = field(default_factory=list)
    themen: list = field(default_factory=list)
    nachrichten: list = field(default_factory=list)

    @property
    def aktive(self):
        return [a for a in self.aussagen if a["status"] == "aktiv"]

    def aussage(self, schluessel):
        return next((a for a in self.aussagen if a["schluessel"] == schluessel), None)

    @property
    def offene_konflikte(self):
        return [k for k in self.konflikte if k["status"] == "offen"]

    def fuer_vertrag(self):
        """Was die Prüfung einer Modellantwort über den Zustand wissen muss."""
        return (
            {a["schluessel"]: {"status": a["status"], "art": a["art"]} for a in self.aussagen},
            {k["id"]: k["status"] for k in self.konflikte},
            {t["id"]: t["status"] for t in self.themen},
        )


def _aussage_dict(a):
    return {
        "id": a.id, "schluessel": a.schluessel, "inhalt": a.inhalt, "thema": a.thema or "",
        "art": a.art, "herkunft": a.herkunft, "bestaetigt": bool(a.bestaetigt),
        "beleg": a.beleg, "bezug": a.bezug or "initialisierung", "entscheid": a.entscheid,
        "zurueckgestellt": bool(a.zurueckgestellt),
        "ziele": json.loads(a.ziele_json or "[]"), "status": a.status,
        "ersetzt_durch": a.ersetzt_durch, "ersetzt": a.ersetzt,
        "nachricht_id": a.nachricht_id, "thema_id": a.thema_id,
        "revision_neu": a.revision_neu, "revision_geaendert": a.revision_geaendert,
    }


def _konflikt_dict(k):
    return {"id": k.id, "aussagen": json.loads(k.aussagen_json or "[]"),
            "beschreibung": k.beschreibung, "quelle": k.quelle, "status": k.status,
            "loesung": k.loesung, "revision_erkannt": k.revision_erkannt,
            "revision_geloest": k.revision_geloest}


def _thema_dict(t):
    return {"id": t.id, "thema": t.thema, "frage_ansatz": t.frage_ansatz,
            "uebertragbarkeit": t.uebertragbarkeit, "regel_id": t.regel_id,
            "regel_version": t.regel_version, "begruendung": t.begruendung,
            "pia_ziele": json.loads(t.pia_ziele_json or "[]"),
            "offene_aspekte": t.offene_aspekte,
            "quellen": json.loads(t.quellen_json or "[]"), "n_projekte": t.n_projekte,
            "status": t.status, "revision": t.revision}


def _nachricht_dict(n):
    return {"id": n.id, "rolle": n.rolle, "art": n.art, "text": n.text, "aktion": n.aktion,
            "begruendung": n.begruendung, "bezug": json.loads(n.bezug_json or "{}"),
            "status": n.status, "fehler": n.fehler, "revision": n.revision,
            "anfrage_id": n.anfrage_id,
            "erstellt_am": n.erstellt_am.isoformat(timespec="seconds") if n.erstellt_am else None}


@dataclass
class Aenderung:
    """Ergebnis einer Anwendung von Operationen."""
    revision: int
    neu: list = field(default_factory=list)            # neue Schlüssel
    geaendert: list = field(default_factory=list)      # bestätigt/korrigiert/verworfen
    verworfen: list = field(default_factory=list)      # [(op, grund)]
    konflikte_neu: list = field(default_factory=list)
    themen_geaendert: list = field(default_factory=list)

    @property
    def leer(self):
        return not (self.neu or self.geaendert or self.konflikte_neu or self.themen_geaendert)


class ZustandService:
    """Lesen und Ändern des gemeinsamen Zustands einer Session."""

    # Liefert die aktuell wirksamen Versionen (Prompts, Regeln, Profil) – vom
    # Dienst gesetzt, damit auch Rückmeldungen aus Operationen sie tragen.
    versionen_fn = None

    # ---- Lesen ------------------------------------------------------------- #

    def lade(self, session_id, mit_nachrichten=True):
        db = SessionLocal()
        try:
            s = db.get(InterviewSession, int(session_id))
            if s is None:
                return None
            z = Zustand(session_id=s.id, revision=s.revision or 0)
            z.aussagen = [_aussage_dict(a) for a in db.query(PiaAussage)
                          .filter(PiaAussage.session_id == s.id).order_by(PiaAussage.id)]
            z.konflikte = [_konflikt_dict(k) for k in db.query(PiaKonflikt)
                           .filter(PiaKonflikt.session_id == s.id).order_by(PiaKonflikt.id)]
            z.themen = [_thema_dict(t) for t in db.query(PiaRagThema)
                        .filter(PiaRagThema.session_id == s.id).order_by(PiaRagThema.id)]
            if mit_nachrichten:
                z.nachrichten = [_nachricht_dict(n) for n in db.query(PiaNachricht)
                                 .filter(PiaNachricht.session_id == s.id).order_by(PiaNachricht.id)]
            return z
        finally:
            db.rollback()       # nur gelesen – keine Sperre offen lassen

    def finde_anfrage(self, session_id, anfrage_id):
        """Die Nachricht zu einer Anfrage-ID (Idempotenz) – oder None."""
        if not anfrage_id:
            return None
        db = SessionLocal()
        n = db.query(PiaNachricht).filter(
            PiaNachricht.session_id == int(session_id),
            PiaNachricht.anfrage_id == str(anfrage_id)).first()
        return _nachricht_dict(n) if n else None

    # ---- Sichern ------------------------------------------------------------ #

    def nachricht(self, session_id, rolle, text, art="beitrag", anfrage_id=None,
                  aktion=None, begruendung=None, bezug=None, status=None, versionen=None):
        """Legt eine Nachricht an und SPEICHERT sie sofort."""
        db = SessionLocal()
        n = PiaNachricht(session_id=int(session_id), rolle=rolle, art=art, text=text,
                         anfrage_id=str(anfrage_id) if anfrage_id else None,
                         aktion=aktion, begruendung=begruendung,
                         bezug_json=json.dumps(bezug or {}, ensure_ascii=False),
                         status=status or ("eingegangen" if rolle == "benutzer" else "verarbeitet"),
                         versionen_json=json.dumps(versionen or {}, ensure_ascii=False))
        db.add(n)
        db.commit()
        db.refresh(n)
        return _nachricht_dict(n)

    def markiere_nachricht(self, nachricht_id, status, fehler=None, revision=None, versionen=None):
        db = SessionLocal()
        n = db.get(PiaNachricht, int(nachricht_id))
        if n is None:
            return
        n.status = status
        if fehler is not None:
            n.fehler = str(fehler)[:1000]
        if revision is not None:
            n.revision = revision
        if versionen is not None:
            n.versionen_json = json.dumps(versionen, ensure_ascii=False)
        db.commit()

    # ---- Ändern ------------------------------------------------------------- #

    def wende_an(self, session_id, ops, nachricht_id=None, nachher=None):
        """Wendet geprüfte Operationen auf den AKTUELLEN Stand an.

        Die Operationen wurden gegen einen Schnappschuss geprüft. Zwischen
        Schnappschuss und Schreiben kann ein anderer Tab etwas geändert haben;
        deshalb wird jeder Bezug hier gegen den frischen Stand nachgeprüft.
        Eine Korrektur einer inzwischen ersetzten Aussage wird verworfen,
        nicht auf die falsche Aussage angewendet.

        `nachher(db, session, aenderung)`: optional, läuft in DERSELBEN
        Transaktion (z.B. Projektion in die Dokumentdaten), damit Zustand und
        Projektion dieselbe Revision tragen.
        """
        db = SessionLocal()
        try:
            s = db.get(InterviewSession, int(session_id))
            if s is None:
                raise ValueError("Session nicht gefunden")
            revision = (s.revision or 0) + 1
            erg = Aenderung(revision=revision)
            vorhanden = {a.schluessel: a for a in db.query(PiaAussage)
                         .filter(PiaAussage.session_id == s.id)}
            naechste = [max([int(k[2:]) for k in vorhanden] or [0]) + 1]

            def neue(inhalt, art, herkunft, bestaetigt, ziele, thema="", bezug=None,
                     entscheid=None, beleg=None, ersetzt=None, zurueck=False, thema_id=None):
                sch = f"A-{naechste[0]:04d}"
                naechste[0] += 1
                a = PiaAussage(session_id=s.id, schluessel=sch, inhalt=inhalt, thema=thema or "",
                               art=art, herkunft=herkunft, bestaetigt=bestaetigt,
                               bezug=bezug or "initialisierung", entscheid=entscheid,
                               beleg=beleg, ziele_json=json.dumps(ziele or [], ensure_ascii=False),
                               status="aktiv", ersetzt=ersetzt, zurueckgestellt=zurueck,
                               nachricht_id=nachricht_id, thema_id=thema_id,
                               revision_neu=revision, revision_geaendert=revision)
                db.add(a)
                vorhanden[sch] = a
                erg.neu.append(sch)
                return a

            def aktiv(sch):
                a = vorhanden.get(sch)
                return a if a is not None and a.status == "aktiv" else None

            for op in ops or []:
                art = op.get("op")
                if art == "neu":
                    neue(op["inhalt"], op["art"], op["herkunft"], op["bestaetigt"],
                         op.get("ziele"), op.get("thema"), op.get("bezug"),
                         op.get("entscheid"), op.get("beleg"), thema_id=op.get("thema_id"))
                elif art == "korrektur":
                    alt = aktiv(op["aussage"])
                    if alt is None:
                        erg.verworfen.append((op, "Aussage inzwischen nicht mehr aktiv"))
                        continue
                    ziele = op.get("ziele") or json.loads(alt.ziele_json or "[]")
                    nach = neue(op["inhalt"], op["art"], op["herkunft"], op["bestaetigt"],
                                ziele, op.get("thema") or alt.thema,
                                op.get("bezug") or alt.bezug,
                                op.get("entscheid") or alt.entscheid,
                                op.get("beleg") or alt.beleg, ersetzt=alt.schluessel)
                    alt.status = "ersetzt"
                    alt.ersetzt_durch = nach.schluessel
                    alt.revision_geaendert = revision
                    erg.geaendert.append(alt.schluessel)
                elif art in ("bestaetigen", "verwerfen", "entscheid"):
                    a = aktiv(op["aussage"])
                    if a is None:
                        erg.verworfen.append((op, "Aussage inzwischen nicht mehr aktiv"))
                        continue
                    if art == "bestaetigen":
                        a.bestaetigt = True
                    elif art == "verwerfen":
                        a.status = "verworfen"
                        if a.herkunft in ("system", "rag"):
                            db.add(PiaRueckmeldung(
                                session_id=s.id, org_id=s.org_id, art="vorschlag_verworfen",
                                bezug=a.schluessel, versionen_json=self._versionen_json(),
                                kontext_json=json.dumps({"inhalt": a.inhalt[:300],
                                                         "art": a.art}, ensure_ascii=False)))
                    else:
                        a.entscheid = op["wert"]
                        a.bestaetigt = True
                    a.revision_geaendert = revision
                    erg.geaendert.append(a.schluessel)
                elif art == "widerspruch":
                    if any(aktiv(x) is None for x in op["aussagen"]):
                        erg.verworfen.append((op, "Aussage inzwischen nicht mehr aktiv"))
                        continue
                    k = PiaKonflikt(session_id=s.id,
                                    aussagen_json=json.dumps(op["aussagen"]),
                                    beschreibung=op["beschreibung"],
                                    quelle=op.get("quelle", "gespraech"),
                                    status="offen", revision_erkannt=revision)
                    db.add(k)
                    db.flush()
                    erg.konflikte_neu.append(k.id)
                elif art == "konflikt_loesen":
                    k = db.get(PiaKonflikt, int(op["konflikt"]))
                    if k is None or k.session_id != s.id or k.status != "offen":
                        erg.verworfen.append((op, "Konflikt nicht mehr offen"))
                        continue
                    k.status = "geloest"
                    k.loesung = op.get("loesung") or (f"Es gilt {op['gilt']}" if op.get("gilt") else "")
                    k.revision_geloest = revision
                    gilt = op.get("gilt")
                    if gilt:
                        for sch in json.loads(k.aussagen_json or "[]"):
                            a = aktiv(sch)
                            if a is not None and sch != gilt:
                                a.status = "ersetzt"
                                a.ersetzt_durch = gilt
                                a.revision_geaendert = revision
                                erg.geaendert.append(sch)
                    erg.geaendert.append(f"K-{k.id}")
                elif art in ("zurueckstellen", "unbekannt"):
                    neue(op.get("inhalt") or op["thema"], "unbekannt", "benutzer", True,
                         op.get("ziele"), op["thema"], zurueck=(art == "zurueckstellen"))
                elif art == "rag_bewerten":
                    t = db.get(PiaRagThema, int(op["thema_id"]))
                    if t is None or t.session_id != s.id:
                        erg.verworfen.append((op, "Thema nicht gefunden"))
                        continue
                    t.status = "bestaetigt" if op.get("passt") else "verworfen"
                    t.revision = revision
                    erg.themen_geaendert.append(t.id)
                    if not op.get("passt"):
                        db.add(PiaRueckmeldung(session_id=s.id, org_id=s.org_id,
                                               art="rag_unpassend", bezug=f"T-{t.id}",
                                               versionen_json=self._versionen_json(),
                                               kontext_json=json.dumps({"thema": t.thema},
                                                                       ensure_ascii=False)))
                elif art == "systemvorschlag":
                    # Vom System erzeugte Vorschläge – unbestätigt, bis der
                    # Benutzer sie übernimmt (Auftrag AT20).
                    neue(op["inhalt"], op.get("art", "systemvorschlag"), op.get("herkunft", "system"),
                         False, op.get("ziele"), op.get("thema"), op.get("bezug"),
                         beleg=op.get("beleg"), thema_id=op.get("thema_id"))
                else:
                    erg.verworfen.append((op, f"unbekannte Operation «{art}»"))

            if erg.leer:
                db.rollback()
                erg.revision = s.revision or 0
                return erg
            s.revision = revision
            db.flush()
            if nachher is not None:
                nachher(db, s, erg)
            db.commit()
            return erg
        except Exception:
            db.rollback()
            raise

    def _versionen_json(self):
        try:
            return json.dumps(self.versionen_fn() if self.versionen_fn else {}, ensure_ascii=False)
        except Exception:      # noqa: BLE001 – Versionsangabe darf nichts verhindern
            return "{}"

    def rueckmeldung(self, session_id, art, bezug=None, kontext=None, versionen=None):
        db = SessionLocal()
        s = db.get(InterviewSession, int(session_id))
        db.add(PiaRueckmeldung(session_id=int(session_id), org_id=getattr(s, "org_id", None),
                               art=art, bezug=bezug,
                               kontext_json=json.dumps(kontext or {}, ensure_ascii=False),
                               versionen_json=json.dumps(versionen or {}, ensure_ascii=False)))
        db.commit()

    # ---- Sessionfelder -------------------------------------------------------- #

    def setze_session(self, session_id, **felder):
        """Setzt Felder der Session (Modus, nächste Aktion, Status …)."""
        db = SessionLocal()
        s = db.get(InterviewSession, int(session_id))
        if s is None:
            return None
        for k, v in felder.items():
            if k.endswith("_json") and not isinstance(v, str) and v is not None:
                v = json.dumps(v, ensure_ascii=False)
            setattr(s, k, v)
        db.commit()
        return s
