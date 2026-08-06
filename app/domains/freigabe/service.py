"""Der Ablauf der Projektinitialisierungsfreigabe.

Die Reihenfolge ist keine Bequemlichkeit, sondern die Methode:

    Checkliste erzeugen  →  bewerten und ergänzen  →  Checkliste freigeben
                         →  Meilenstein erreicht   →  Entscheid nachtragen
                         →  Phase Initialisierung läuft

Jeder Schritt hat eine Bedingung, und die Bedingungen stehen HIER, im Code –
nicht in einer Oberfläche, die man umgehen kann, und nicht in einem Hinweis,
den man überlesen kann. Der Meilenstein lässt sich nicht erreichen, solange
die Checkliste nicht freigegeben ist; die Checkliste lässt sich nicht
freigeben, solange ein Prüfpunkt unbewertet oder nicht erfüllt ist.
"""
import json
import logging
from datetime import date, datetime

from app.domains.ergebnisse import pia_quelle
from app.domains.freigabe import pruefpunkte
from app.domains.freigabe.models import FreigabeCheckliste, Projektentscheid
from app.domains.projekt.models import Meilenstein, Phase
from app.shared.database import SessionLocal

log = logging.getLogger("hermes.freigabe")

ART = "projektinitialisierungsfreigabe"

# Zeile 01 der Liste Projektentscheide Steuerung, wörtlich nach der Vorlage.
ENTSCHEID_NR = "01"
ENTSCHEID_TEXT = ("Entscheid Projektinitialisierungsfreigabe bestätigt bzw. "
                  "freigeben (Phase Initialisierung)")
ENTSCHEID_GRUNDLAGEN = ("Projektinitialisierungsauftrag",
                        "Checkliste Projektinitialisierungsfreigabe")
ENTSCHEIDUNGSTRAEGER = "Auftraggeber"


class FreigabeFehler(Exception):
    """Eine Bedingung des Ablaufs ist nicht erfüllt – mit einem Grund im Text."""


class FreigabeService:
    def __init__(self, projekt_service, interview_service, parser=None,
                 kopfdaten_service=None):
        self.projekt_service = projekt_service
        self.interview_service = interview_service
        self._parser = parser
        self.kopfdaten = kopfdaten_service

    # ---- Lesen ---------------------------------------------------------- #

    def checkliste(self, projekt_id):
        return SessionLocal().query(FreigabeCheckliste).filter(
            FreigabeCheckliste.projekt_id == int(projekt_id),
            FreigabeCheckliste.art == ART,
        ).first()

    @staticmethod
    def zeilen(checkliste):
        """Die drei Kapitel als Wörterbuch – immer alle drei Schlüssel."""
        leer = {"generell": [], "organisation": [], "projekt": []}
        if checkliste is None or not checkliste.zeilen_json:
            return leer
        try:
            geladen = json.loads(checkliste.zeilen_json)
        except ValueError:
            log.warning("Checkliste %s ist nicht lesbar.", checkliste.id)
            return leer
        leer.update({k: v for k, v in geladen.items() if k in leer})
        return leer

    @staticmethod
    def alle_zeilen(zeilen):
        return (zeilen.get("generell") or []) + (zeilen.get("organisation") or []) \
            + (zeilen.get("projekt") or [])

    def entscheide(self, projekt_id):
        return SessionLocal().query(Projektentscheid).filter(
            Projektentscheid.projekt_id == int(projekt_id)
        ).order_by(Projektentscheid.nr).all()

    def meilenstein(self, projekt_id):
        return SessionLocal().query(Meilenstein).join(
            Phase, Meilenstein.phase_id == Phase.id
        ).filter(Phase.projekt_id == int(projekt_id),
                 Meilenstein.code == ART).first()

    # ---- Erzeugen ------------------------------------------------------- #

    def projektwissen(self, projekt):
        """Der Auftrag, auf den sich die Prüfung stützt – samt Herkunft.

        Dieselbe Quelle wie bei jedem abgeleiteten Ergebnis: was hochgeladen
        und freigegeben wurde, schlägt den Arbeitsstand im Interview. Die
        Checkliste soll auf der Fassung fussen, die wirklich gilt.
        """
        dokumente = {}
        for ergebnis in self.projekt_service.ergebnisse(projekt.id):
            for art in pia_quelle.DOKUMENTARTEN:
                dok = self.projekt_service.latest_dokument(ergebnis.id, art=art)
                if dok is not None and art not in dokumente:
                    dokumente[art] = dok.data
            sitzung = self.interview_service.session_for_ergebnis(ergebnis.id)
            if sitzung is not None:
                break
        else:
            sitzung = None
        wissen, kopfangaben, herkunft = pia_quelle.quelle(
            session=sitzung, dokumente=dokumente, parser=self._parser)
        return wissen, herkunft, dokumente, sitzung, kopfangaben

    def _geschlecht(self, name):
        """Anrede aus dem Vornamen – derselbe Weg wie beim PIA.

        Ohne Sprachmodell bleibt es bei «unbekannt», und die Vorlage behält
        ihre Doppelform. Geraten wird nichts.
        """
        from app.domains.interview.extraction import detect_gender

        return detect_gender(getattr(self.interview_service, "llm", None), name)

    def dokument_kontext(self, projekt, methode=None, version="", status="in Arbeit",
                         datum=""):
        """(Kopfangaben, Abschnitte, Projektwissen) für die Word-Ausgabe.

        Der Kopf jedes Dokuments und die Kapitel 0.2 bis 0.5 sind für alle
        Ergebnisse eines Projekts dieselben – sie stammen aus derselben
        Quelle wie die Bewertung selbst.
        """
        from app.domains.dokumentenkopf import kopf as kopfmodul

        wissen, _, _, sitzung, aus_dokument = self.projektwissen(projekt)
        # Die HINTERLEGTEN Kopfdaten fuehren - sie sind die einzigen, die ein
        # Mensch bestaetigt hat. Weicht das hochgeladene Dokument ab, zeigt das
        # der Abgleich; still ueberschrieben wird nichts.
        hinterlegt = {}
        if self.kopfdaten is not None:
            eintrag = self.kopfdaten.stelle_bereit(
                projekt, session=sitzung, aus_dokument=aus_dokument)
            hinterlegt = self.kopfdaten.als_wörterbuch(eintrag)
        angaben = kopfmodul.metadaten(projekt=projekt, session=sitzung,
                                      version=version, status=status, datum=datum,
                                      vorrang=hinterlegt or aus_dokument,
                                      erkenne_geschlecht=self._geschlecht)
        abschnitte = (methode or {}).get("sections") or []
        return angaben, abschnitte, wissen

    def erzeuge(self, projekt):
        """Checkliste anlegen oder neu bewerten.

        Bereits eingetragene Bewertungen der Kapitel 1.2 und 1.3 bleiben
        erhalten – sie stammen von Menschen. Kapitel 1.1 wird neu gerechnet,
        denn es beruht auf dem Auftrag, und der kann sich geändert haben.
        """
        checkliste = self.checkliste(projekt.id)
        if checkliste is not None and checkliste.status == "freigegeben":
            raise FreigabeFehler(
                "Die Checkliste ist bereits freigegeben und wird nicht neu "
                "bewertet. Ein Nachweis, der sich nachträglich ändert, ist "
                "kein Nachweis.")

        wissen, herkunft, dokumente, _, _ = self.projektwissen(projekt)
        vorhanden = self.zeilen(checkliste)
        neu = {
            "generell": pruefpunkte.generelle_pruefpunkte(
                wissen, {k: True for k in dokumente}),
            "organisation": (vorhanden.get("organisation")
                             or pruefpunkte.organisationsspezifische_vorschlaege(wissen)),
            "projekt": (vorhanden.get("projekt")
                        or pruefpunkte.projektspezifische_vorschlaege(wissen)),
        }

        db = SessionLocal()
        if checkliste is None:
            checkliste = FreigabeCheckliste(projekt_id=projekt.id, art=ART)
            db.add(checkliste)
        checkliste.zeilen_json = json.dumps(neu, ensure_ascii=False, indent=2)
        # Die Herkunft steht IMMER da. Auch «nichts vorhanden» ist eine
        # Auskunft – ohne sie liesse sich später nicht sagen, ob die Prüfung
        # auf einem leeren Auftrag beruhte oder auf einem ungeprüften.
        checkliste.quelle = (pia_quelle.HERKUNFT_TEXT.get(herkunft)
                             or "kein Projektinitialisierungsauftrag vorhanden")
        checkliste.status = "entwurf"
        db.commit()
        return checkliste

    def speichere_zeilen(self, projekt_id, zeilen):
        """Bewertungen aus der Oberfläche übernehmen – nur solange Entwurf."""
        checkliste = self.checkliste(projekt_id)
        if checkliste is None:
            raise FreigabeFehler("Für dieses Projekt gibt es noch keine Checkliste.")
        if checkliste.status == "freigegeben":
            raise FreigabeFehler("Die Checkliste ist freigegeben und lässt sich "
                                 "nicht mehr ändern.")
        db = SessionLocal()
        eintrag = db.get(FreigabeCheckliste, checkliste.id)
        eintrag.zeilen_json = json.dumps(zeilen, ensure_ascii=False, indent=2)
        db.commit()
        return eintrag

    # ---- Das Tor -------------------------------------------------------- #

    def gib_frei(self, projekt_id, durch):
        """Checkliste freigeben – nur wenn kein Punkt offen oder verneint ist."""
        checkliste = self.checkliste(projekt_id)
        if checkliste is None:
            raise FreigabeFehler("Für dieses Projekt gibt es noch keine Checkliste.")
        if checkliste.status == "freigegeben":
            raise FreigabeFehler("Die Checkliste ist bereits freigegeben.")
        offen = pruefpunkte.offene_punkte(self.alle_zeilen(self.zeilen(checkliste)))
        if offen:
            nummern = ", ".join(str(z.get("nr", "?")) for z in offen)
            raise FreigabeFehler(
                f"{len(offen)} Prüfpunkt{'e sind' if len(offen) != 1 else ' ist'} "
                f"noch offen oder nicht erfüllt: {nummern}. "
                "Bewerten Sie sie, bevor Sie freigeben.")
        db = SessionLocal()
        eintrag = db.get(FreigabeCheckliste, checkliste.id)
        eintrag.status = "freigegeben"
        eintrag.freigegeben_am = datetime.utcnow()
        eintrag.freigegeben_durch = durch or ""
        db.commit()
        return eintrag

    def erreiche_meilenstein(self, projekt_id, durch, entscheidungsdatum=None):
        """Meilenstein erreichen, Entscheid nachtragen, Phase eröffnen.

        Die drei gehören zusammen: ein erreichter Meilenstein ohne
        nachgetragenen Entscheid wäre eine Behauptung ohne Beleg.
        """
        checkliste = self.checkliste(projekt_id)
        if checkliste is None or checkliste.status != "freigegeben":
            raise FreigabeFehler(
                "Der Meilenstein Projektinitialisierungsfreigabe kann erst als "
                "erreicht gelten, wenn die Checkliste freigegeben ist.")
        stein = self.meilenstein(projekt_id)
        if stein is None:
            raise FreigabeFehler("Der Meilenstein ist für dieses Projekt nicht angelegt.")
        if stein.status == "erreicht":
            raise FreigabeFehler("Der Meilenstein ist bereits als erreicht vermerkt.")

        datum = entscheidungsdatum or date.today().isoformat()
        db = SessionLocal()
        eintrag = db.get(Meilenstein, stein.id)
        eintrag.status = "erreicht"
        phase = db.get(Phase, eintrag.phase_id)
        if phase is not None:
            phase.status = "laufend"
        db.add(Projektentscheid(
            projekt_id=int(projekt_id),
            nr=ENTSCHEID_NR,
            entscheid=ENTSCHEID_TEXT,
            grundlagen="\n".join(ENTSCHEID_GRUNDLAGEN),
            entscheidungstraeger=ENTSCHEIDUNGSTRAEGER,
            entscheidungsdatum=datum,
        ))
        db.commit()
        return eintrag
