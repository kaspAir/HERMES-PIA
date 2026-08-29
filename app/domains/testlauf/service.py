"""Ein Vorhaben einmal ganz durchspielen - ohne Rueckfragen.

WOZU. Ein vollstaendiger Durchgang von Hand kostet eine Stunde: zehn
Abschnitte diktieren, jede Nachfrage beantworten, das Dokument erzeugen und
wieder hochladen, die Kette starten, sieben Schritte abwarten, die Checkliste
bewerten. Wer nach einer Aenderung wissen will, ob noch alles zusammenspielt,
macht das nicht - und merkt den Bruch erst beim Kunden.

WAS ER IST UND WAS NICHT. Der Testlauf folgt IMMER dem eigenen Vorschlag. Das
prueft das Zusammenspiel, nicht die Qualitaet: Frage und Antwort kommen aus
derselben Quelle, also kann kein Missverstaendnis entstehen und keine
Rueckfrage ins Leere laufen. Ein gruener Testlauf sagt «die Kette haelt», er
sagt nichts ueber «der PIA ist gut». Wer das verwechselt, hat einen Pruefer,
der immer zustimmt.

DIE FREIGABE ist der heikle Teil. Die Checkliste laesst sich nicht freigeben,
solange eine Zeile unbewertet oder «nicht erfuellt» ist - und unbewertet sind
die Vorschlaege der Kapitel 1.2 und 1.3 mit Absicht: sie gehoeren denen, die
die Checkliste ausfuellen. Ein Testlauf muss dieses Tor also uebergehen. Er
tut es sichtbar:
jede von ihm gesetzte Bewertung traegt den Vermerk TESTLAUF_VERMERK in der
Erlaeuterung, und der steht danach im erzeugten Word-Dokument. Ein Testlauf,
der sich nicht von einer echten Freigabe unterscheiden liesse, waere eine
Faelschung.

DESHALB ist der Testlauf standardmaessig AUS (Config `TESTLAUF`) und gehoert
nur auf die Entwicklungsstufe.
"""
import io
import json
import logging
from datetime import date, datetime

from app.domains.generation import pia as pia_dokument
from app.domains.projekt.reference import ERG_PIA
from app.domains.testlauf.models import Testlauf
from app.shared.database import SessionLocal

log = logging.getLogger("hermes.testlauf")

TESTLAUF_VERMERK = "TESTLAUF: ohne menschliches Urteil automatisch bestätigt."

DOCX_MIME = ("application/vnd.openxmlformats-officedocument"
             ".wordprocessingml.document")

SCHRITTE = [
    ("interview",        "Interview führen"),
    ("dokument",         "Projektinitialisierungsauftrag erzeugen und ablegen"),
    ("praesentation",    "Präsentation erzeugen"),
    ("projektplan",      "Projektplan erzeugen"),
    ("rechtsgrundlagen", "Rechtsgrundlagenanalyse"),
    ("schutzbedarf",     "Schutzbedarfsanalyse"),
    ("freigabe",         "Checkliste, Freigabe und Meilenstein"),
]

# Obergrenze fuer die Aufrufe EINES Laufs. Nicht geraten, sondern gerechnet:
# rund 12 Abschnitte mit je bis zu 3 Nachfragen, 7 Kettenschritte mit
# stueckweiser Verarbeitung, dazu die uebrigen Schritte - das Doppelte davon
# ist grosszuegig und faengt trotzdem jede Schleife.
HOECHSTZAHL_AUFRUFE = 200


class TestlaufFehler(Exception):
    """Der Lauf kann nicht fortgesetzt werden - mit dem Grund im Text."""


class TestlaufService:
    """Treibt den Lauf, Schritt fuer Schritt.

    Ein Aufruf = eine Arbeitseinheit, nie mehr. Dieselbe Regel wie bei der
    Rechtsgrundlagen-Kette, aus demselben Grund: zwei Modellaufrufe in einer
    Anfrage rissen dort das Zeitlimit, und dann ist der ganze Schritt verloren.
    Die Oberflaeche ruft so lange nach, bis «fertig» kommt.
    """

    def __init__(self, interview_service, projekt_service, generation_service,
                 praesentation_service, rechtsgrundlagen_service,
                 schutzbedarf_service, freigabe_service):
        self.interview = interview_service
        self.projekte = projekt_service
        self.generation = generation_service
        self.praesentation = praesentation_service
        self.rechtsgrundlagen = rechtsgrundlagen_service
        self.schutzbedarf = schutzbedarf_service
        self.freigabe = freigabe_service

    # ---- Anlegen -------------------------------------------------------- #

    def starte(self, org_id, ausgangslage, projektname, projektleiter,
               auftraggeber=None, verwaltungseinheit=None, ebene=None,
               kanton=None, start_datum=None):
        """Legt Sitzung, Projekt und Lauf an. Fuehrt noch nichts aus."""
        if not (ausgangslage or "").strip():
            raise TestlaufFehler("Ohne Ausgangslage gibt es nichts zu erzählen.")

        session = self.interview.start_session(
            method_id="hermes_pia", project_name=projektname or "Testlauf",
            org_id=org_id, auftraggeber=auftraggeber,
            verwaltungseinheit=verwaltungseinheit, start_datum=start_datum,
            created_by=projektleiter or "",
        )
        projekt = self.projekte.create_projekt(
            org_id=org_id, name=session.project_name, auftraggeber=auftraggeber,
            verwaltungseinheit=verwaltungseinheit, start_datum=start_datum,
            created_by=projektleiter or "",
        )
        ergebnis = self.projekte.add_ergebnis(projekt.id, ERG_PIA,
                                              created_by=projektleiter or "")
        self.interview.link_ergebnis(session.id, ergebnis.id)

        db = SessionLocal()
        lauf = Testlauf(org_id=org_id, projekt_id=projekt.id, session_id=session.id,
                        ausgangslage=ausgangslage.strip(), ebene=ebene,
                        kanton=kanton, schritt=0, status="laeuft")
        db.add(lauf)
        db.commit()
        db.refresh(lauf)
        return lauf

    def hole(self, lauf_id):
        return SessionLocal().get(Testlauf, int(lauf_id))

    def laeufe_for_org(self, org_id):
        db = SessionLocal()
        return (db.query(Testlauf).filter(Testlauf.org_id == org_id)
                .order_by(Testlauf.id.desc()).all())

    # ---- Zustand -------------------------------------------------------- #

    @staticmethod
    def zustand(lauf):
        i = lauf.schritt or 0
        return {
            "id": lauf.id, "schritt": i, "gesamt": len(SCHRITTE),
            "fertig": lauf.status != "laeuft",
            "status": lauf.status,
            "naechstes": SCHRITTE[i][1] if i < len(SCHRITTE) else "",
            "protokoll": json.loads(lauf.protokoll_json or "[]"),
            "projekt_id": lauf.projekt_id, "session_id": lauf.session_id,
        }

    @staticmethod
    def _notiere(db, lauf, text):
        eintraege = json.loads(lauf.protokoll_json or "[]")
        eintraege.append({"zeit": datetime.utcnow().isoformat(timespec="seconds"),
                          "schritt": SCHRITTE[min(lauf.schritt or 0,
                                                  len(SCHRITTE) - 1)][1],
                          "text": text})
        lauf.protokoll_json = json.dumps(eintraege, ensure_ascii=False)
        db.commit()

    # ---- Der Treiber ---------------------------------------------------- #

    def schritt(self, lauf_id):
        """EINE Arbeitseinheit. Rueckgabe: der Zustand fuer die Oberflaeche."""
        db = SessionLocal()
        lauf = db.get(Testlauf, int(lauf_id))
        if lauf is None:
            raise TestlaufFehler("Diesen Testlauf gibt es nicht.")
        if lauf.status != "laeuft":
            return self.zustand(lauf)

        lauf.aufrufe = (lauf.aufrufe or 0) + 1
        if lauf.aufrufe > HOECHSTZAHL_AUFRUFE:
            lauf.status = "gescheitert"
            lauf.beendet_am = datetime.utcnow()
            self._notiere(db, lauf, f"Abgebrochen nach {HOECHSTZAHL_AUFRUFE} "
                                    "Aufrufen – ein Schritt kam nicht voran.")
            return self.zustand(lauf)
        db.commit()

        index = lauf.schritt or 0
        if index >= len(SCHRITTE):
            lauf.status = "fertig"
            lauf.beendet_am = datetime.utcnow()
            db.commit()
            return self.zustand(lauf)

        _schluessel, name = SCHRITTE[index]
        arbeit = getattr(self, f"_schritt_{_schluessel}")
        try:
            fertig, meldung = arbeit(lauf)
        except Exception as e:      # noqa: BLE001 – der Grund gehört ins Protokoll
            log.exception("Testlauf %s: Schritt «%s» abgestürzt", lauf.id, name)
            # NICHT abbrechen: ein gescheiterter Schritt ist ein Befund, kein
            # Grund, die uebrigen ungeprueft zu lassen. Genau dafuer ist der
            # Lauf da.
            self._notiere(db, lauf, f"GESCHEITERT: {e.__class__.__name__}: {e}")
            fertig, meldung = True, ""

        if meldung:
            self._notiere(db, lauf, meldung)
        if fertig:
            lauf.schritt = index + 1
            if lauf.schritt >= len(SCHRITTE):
                lauf.status = "fertig"
                lauf.beendet_am = datetime.utcnow()
            db.commit()
        return self.zustand(db.get(Testlauf, lauf.id))

    # ---- Die Schritte --------------------------------------------------- #

    def _schritt_interview(self, lauf):
        """Eine Frage beantworten oder eine Nachfrage annehmen.

        Die Ausgangslage kommt vom Menschen - sie ist das Einzige, was er
        beisteuert. Fuer jeden weiteren Abschnitt wird LEER eingereicht: dann
        bietet HERMES PIA von sich aus einen Vorschlag an, und der wird
        angenommen. Genau das ist «den eigenen Vorschlaegen folgen» - kein
        Sonderweg, sondern der Weg, den die Oberflaeche auch anbietet.
        """
        session = self.interview.get_session(lauf.session_id)
        zustand = self.interview.current_state(session)
        phase = zustand.get("phase")

        if phase == "question":
            abschnitt = zustand["section"]
            ist_ausgangslage = abschnitt.get("id") == "ausgangslage"
            text = lauf.ausgangslage if ist_ausgangslage else ""
            self.interview.submit_answer(lauf.session_id, text)
            woher = "aus der Beschreibung" if ist_ausgangslage else "leer eingereicht"
            return False, f"«{abschnitt.get('title')}» {woher}."

        if phase == "followup":
            nachfrage = zustand["followup"]
            self.interview.answer_followup(
                lauf.session_id, nachfrage.get("risk_id"), accepted=True)
            frage = (nachfrage.get("frage") or "").strip()
            return False, f"Nachfrage angenommen: {frage[:120]}"

        return True, "Interview vollständig."

    def _schritt_dokument(self, lauf):
        """Den PIA erzeugen und als freigabebereite Fassung ablegen.

        Ohne diesen Schritt haetten Praesentation und Projektplan nichts zu
        lesen: beide beruhen auf der HOCHGELADENEN Fassung, nicht auf dem
        Arbeitsstand. Der Testlauf nimmt der Projektleitung genau diesen
        Umweg ab - Word oeffnen, pruefen, wieder hochladen.
        """
        from app.domains.qualitaet.service import pruefe_session

        session = self.interview.get_session(lauf.session_id)
        buf, answers = pia_dokument.erzeuge(session, self.interview,
                                            self.generation, self.projekte)
        daten = buf.getvalue()

        # Die verbindliche Pruefung laeuft mit, blockiert aber NICHT. Ein
        # Muss-Befund ist hier das Wertvollste am ganzen Lauf: er zeigt, was
        # der Download der Projektleitung verweigern wuerde.
        vermerk = ""
        try:
            try:
                from docx import Document
                dokument = Document(io.BytesIO(daten))
            except Exception:      # noqa: BLE001 – Dok-Ebene ist optional
                dokument = None
            ergebnis = pruefe_session(session, answers=answers, dokument=dokument)
            if not ergebnis.ausgabe_moeglich:
                muss = [b.regel for b in ergebnis.befunde
                        if getattr(b, "gewicht", "") == "Muss"]
                vermerk = (" ACHTUNG: Der Download wäre blockiert – "
                           f"Muss-Befund(e) {', '.join(sorted(set(muss))) or '?'}.")
        except Exception as e:      # noqa: BLE001 – Pruefung darf den Lauf nicht kippen
            vermerk = f" (Prüfung nicht durchgeführt: {e.__class__.__name__})"

        ergebnis_id = session.ergebnis_id
        if not ergebnis_id:
            raise TestlaufFehler("Zur Sitzung gehört kein Ergebnis-Knoten.")
        name = f"{date.today():%Y-%m-%d}_Testlauf_PIA.docx"
        self.projekte.add_dokument(ergebnis_id, name, daten, art="freigabe",
                                   mimetype=DOCX_MIME, uploaded_by="Testlauf")
        return True, (f"{len(daten) // 1024} KB erzeugt und als freigabebereite "
                      f"Fassung abgelegt.{vermerk}")

    def _pia_fassung(self, lauf):
        session = self.interview.get_session(lauf.session_id)
        dok = self.projekte.latest_dokument(session.ergebnis_id, art="freigabe")
        if dok is None:
            raise TestlaufFehler("Es liegt keine freigabebereite Fassung vor.")
        return dok

    def _schritt_praesentation(self, lauf):
        dok = self._pia_fassung(lauf)
        projekt = self.projekte.get_projekt(lauf.projekt_id)
        vorlage = self.projekte.resolve_vorlage(projekt)
        buf = self.praesentation.generate_from_docx(
            dok.data, template_bytes=vorlage.data if vorlage else None,
            fallback_name=projekt.name, datum=date.today().strftime("%d.%m.%Y"))
        return True, f"{len(buf.getvalue()) // 1024} KB Präsentation erzeugt."

    def _schritt_projektplan(self, lauf):
        from app.domains.praesentation import projektplan
        from app.domains.praesentation.parser import parse_pia

        dok = self._pia_fassung(lauf)
        projekt = self.projekte.get_projekt(lauf.projekt_id)
        eintraege = projektplan.plan_eintraege(parse_pia(dok.data).get("termine"))
        if not eintraege:
            # Kein Absturz, sondern ein Befund: der PIA traegt keine datierten
            # Termine. Genau das soll ein Testlauf sichtbar machen.
            return True, ("KEIN PLAN: der erzeugte PIA enthält keine datierten "
                          "Termine (Kapitel «Ergebnisse und Termine»).")
        name = projekt.name or "Projekt"
        excel = projektplan.build_excel(eintraege, name)
        xml = projektplan.build_msproject_xml(eintraege, name)
        return True, (f"{len(eintraege)} Planzeilen – Excel {len(excel) // 1024} KB, "
                      f"MS-Project {len(xml) // 1024} KB.")

    def _schritt_rechtsgrundlagen(self, lauf):
        """Die Kette starten und je Aufruf EINEN ihrer Schritte fahren."""
        projekt = self.projekte.get_projekt(lauf.projekt_id)
        entwurf = self.rechtsgrundlagen.get_entwurf(projekt.id)
        if entwurf is None or (entwurf.lauf_status or "") not in ("laufend", "fertig"):
            self.rechtsgrundlagen.starte_kette(projekt, ebene=lauf.ebene,
                                               kanton=lauf.kanton)
            return False, (f"Kette gestartet (Ebene «{lauf.ebene or 'nicht gesetzt'}», "
                           f"Kanton «{lauf.kanton or 'nicht gesetzt'}»).")
        zustand, grund = self.rechtsgrundlagen.kette_schritt(projekt)
        if zustand is None:
            raise TestlaufFehler(grund or "Der Kettenschritt ist fehlgeschlagen.")
        if zustand.get("fertig"):
            return True, "Rechtsgrundlagenanalyse fertig."
        return False, (f"Schritt {zustand.get('schritt')}/{zustand.get('gesamt')} – "
                       f"als Nächstes: {zustand.get('naechstes')}")

    def _schritt_schutzbedarf(self, lauf):
        projekt = self.projekte.get_projekt(lauf.projekt_id)
        self.schutzbedarf.erzeuge_entwurf(projekt)
        return True, "Schutzbedarfsanalyse erzeugt."

    def _schritt_freigabe(self, lauf):
        """Checkliste erzeugen, offene Punkte vermerken, freigeben, Meilenstein.

        Der einzige Schritt, der ein Tor UEBERGEHT. Er tut es sichtbar: jede
        Bewertung, die hier gesetzt wird, traegt den Vermerk in ihrer
        Erlaeuterung - und der steht danach im Word-Dokument.
        """
        from app.domains.freigabe import pruefpunkte

        projekt = self.projekte.get_projekt(lauf.projekt_id)
        self.freigabe.erzeuge(projekt)

        checkliste = self.freigabe.checkliste(projekt.id)
        zeilen = self.freigabe.zeilen(checkliste)
        gesetzt = 0
        for _kapitel, liste in zeilen.items():
            for zeile in liste:
                if not isinstance(zeile, dict):
                    continue
                bewertung = str(zeile.get("bewertung") or "").strip()
                if bewertung and bewertung not in pruefpunkte.BLOCKIEREND:
                    continue
                zeile["bewertung"] = pruefpunkte.ERFUELLT
                alt = str(zeile.get("erlaeuterung") or "").strip()
                zeile["erlaeuterung"] = f"{TESTLAUF_VERMERK} {alt}".strip()
                gesetzt += 1
        self.freigabe.speichere_zeilen(projekt.id, zeilen)
        self.freigabe.gib_frei(projekt.id, "Testlauf")
        self.freigabe.erreiche_meilenstein(projekt.id, "Testlauf")
        return True, (f"{gesetzt} Prüfpunkt(e) automatisch bestätigt, Checkliste "
                      "freigegeben, Meilenstein erreicht und Entscheid "
                      "nachgetragen.")
