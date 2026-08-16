"""Kopfdaten pflegen und mit hochgeladenen Dokumenten abgleichen.

Der Vorrang ist hier ein anderer als beim INHALT, und das mit Absicht:

* Beim Inhalt gewinnt die verbindlichste Fassung des Auftrags – sie ist durch
  Prüfung und Freigabe gegangen.
* Bei den Kopfdaten gewinnt der **hinterlegte Datensatz**, denn er ist der
  einzige, den ein Mensch bestätigt hat. Eine Namensschreibweise oder eine
  Anrede ist nichts, was eine Freigabe beschliesst.

Damit daraus keine zweite Wahrheit wird, gibt es den Abgleich: weicht ein
hochgeladenes Dokument ab, wird das gezeigt und gefragt. Nicht still
überschrieben, und – genauso wichtig – nicht still übergangen.
"""
import logging

from app.domains.dokumentenkopf.models import FELDER, Kopfdaten
from app.shared.database import SessionLocal

log = logging.getLogger("hermes.dokumentenkopf")

# Wie die Felder heissen, wenn ein Mensch sie liest.
BESCHRIFTUNG = {
    "projektname": "Projektname",
    "projektnummer": "Projektnummer",
    "projektleiter": "Projektleitung",
    "auftraggeber": "Auftraggeber/in",
    "verwaltungseinheit": "Verwaltungseinheit",
    "geschaeftsbereich": "Geschäftsbereich",
    "innenauftragsnummer": "Innenauftragsnr.",
    "klassifizierung": "Klassifizierung",
    "projektleiter_anrede": "Anrede der Projektleitung",
    "auftraggeber_anrede": "Anrede der auftraggebenden Person",
}


class KopfdatenFehler(Exception):
    """Eine Bedingung ist nicht erfuellt - mit einem Grund im Text."""


class KopfdatenService:
    def __init__(self, erkenne_geschlecht=None):
        # Die Anrede wird EINMAL geschätzt – beim Anlegen, nicht bei jedem
        # Herunterladen. Danach ist sie ein gepflegter Wert.
        self._erkenner = erkenne_geschlecht

    # ---- Lesen ---------------------------------------------------------- #

    def lade(self, projekt_id):
        return SessionLocal().query(Kopfdaten).filter(
            Kopfdaten.projekt_id == int(projekt_id)).first()

    @staticmethod
    def als_wörterbuch(eintrag):
        """Der Datensatz als schlichtes Wörterbuch – leere Felder fallen weg."""
        if eintrag is None:
            return {}
        raus = {}
        for feld in FELDER + ("projektleiter_anrede", "auftraggeber_anrede"):
            wert = getattr(eintrag, feld, None)
            if wert:
                raus[feld] = str(wert)
        return raus

    # ---- Anlegen -------------------------------------------------------- #

    def stelle_bereit(self, projekt, session=None, aus_dokument=None, durch=""):
        """Den Datensatz anlegen, falls er fehlt – sonst unverändert liefern.

        Die Erstbefüllung nimmt, was da ist: das hochgeladene Dokument vor der
        Interview-Sitzung, denn es ist die geprüfte Fassung. Ab dann führt der
        Datensatz, und Abweichungen laufen über den Abgleich.
        """
        vorhanden = self.lade(projekt.id)
        if vorhanden is not None:
            return vorhanden

        quelle = dict(aus_dokument or {})
        eintrag = Kopfdaten(projekt_id=projekt.id)
        eintrag.projektname = (quelle.get("projektname")
                               or getattr(projekt, "name", "") or "")
        eintrag.projektnummer = (getattr(projekt, "projektnummer", "")
                                 or getattr(session, "projektnummer", "") or "")
        eintrag.projektleiter = (quelle.get("projektleiter")
                                 or getattr(session, "created_by", "") or "")
        eintrag.auftraggeber = (quelle.get("auftraggeber")
                                or getattr(projekt, "auftraggeber", "")
                                or getattr(session, "auftraggeber", "") or "")
        eintrag.verwaltungseinheit = (quelle.get("verwaltungseinheit")
                                      or getattr(projekt, "verwaltungseinheit", "")
                                      or getattr(session, "verwaltungseinheit", "") or "")
        eintrag.geschaeftsbereich = (quelle.get("geschaeftsbereich")
                                     or getattr(projekt, "geschaeftsbereich", "")
                                     or getattr(session, "geschaeftsbereich", "") or "")
        eintrag.innenauftragsnummer = (getattr(projekt, "innenauftragsnummer", "")
                                       or getattr(session, "innenauftragsnummer", "") or "")
        eintrag.klassifizierung = "Nicht klassifiziert"
        eintrag.projektleiter_anrede = self._schaetze(eintrag.projektleiter)
        eintrag.auftraggeber_anrede = self._schaetze(eintrag.auftraggeber)
        eintrag.aktualisiert_durch = durch or ""

        db = SessionLocal()
        db.add(eintrag)
        db.commit()
        return eintrag

    def _schaetze(self, name):
        if not name or self._erkenner is None:
            return "u"
        try:
            return self._erkenner(name) or "u"
        except Exception as e:      # noqa: BLE001 – eine Schätzung darf nichts umwerfen
            log.warning("Anrede für «%s» nicht bestimmbar: %s", name, e)
            return "u"

    # ---- Ändern --------------------------------------------------------- #

    def speichere(self, projekt_id, felder, durch=""):
        """Bearbeitete Kopfdaten übernehmen – auch leere Werte.

        Anders als beim Rückweg aus Word ist eine geleerte Zelle hier eine
        Absicht: wer das Feld im Formular leert, will es leer haben.
        """
        eintrag = self.lade(projekt_id)
        if eintrag is None:
            # Kein stilles Nichtstun: der Aufrufer meldete sonst "gesichert",
            # ohne dass etwas gesichert wurde. Genau so ging eine Aenderung
            # beim Bauen verloren.
            raise KopfdatenFehler(
                "Fuer dieses Projekt sind noch keine Kopfdaten angelegt.")
        db = SessionLocal()
        gespeichert = db.get(Kopfdaten, eintrag.id)
        for feld in FELDER:
            if feld in felder:
                setattr(gespeichert, feld, (felder[feld] or "").strip())
        for feld in ("projektleiter_anrede", "auftraggeber_anrede"):
            wert = (felder.get(feld) or "").strip()
            if wert in ("w", "m", "u"):
                setattr(gespeichert, feld, wert)
        gespeichert.aktualisiert_durch = durch or ""
        db.commit()
        return gespeichert

    # ---- Abgleich ------------------------------------------------------- #

    def abweichungen(self, projekt_id, aus_dokument):
        """Wo das hochgeladene Dokument von den Kopfdaten abweicht.

        Liefert eine Liste ``{feld, beschriftung, hinterlegt, im_dokument}``.
        Verglichen wird nur, was im Dokument auch steht – ein dort leeres Feld
        ist keine Abweichung, sondern eine fehlende Angabe.
        """
        eintrag = self.lade(projekt_id)
        if eintrag is None or not aus_dokument:
            return []
        raus = []
        for feld, wert in (aus_dokument or {}).items():
            if feld not in FELDER or not str(wert or "").strip():
                continue
            hinterlegt = str(getattr(eintrag, feld, "") or "").strip()
            if hinterlegt != str(wert).strip():
                raus.append({
                    "feld": feld,
                    "beschriftung": BESCHRIFTUNG.get(feld, feld),
                    "hinterlegt": hinterlegt,
                    "im_dokument": str(wert).strip(),
                })
        return raus

    def uebernimm(self, projekt_id, aus_dokument, felder, durch=""):
        """Ausgewählte Werte aus dem Dokument übernehmen.

        ``felder``: die Feldnamen, für die die Übernahme bestätigt wurde.
        Ändert sich ein Name, wird die Anrede neu geschätzt – sie gehörte zum
        alten Namen und ist für den neuen nicht belegt.
        """
        eintrag = self.lade(projekt_id)
        if eintrag is None:
            raise KopfdatenFehler(
                "Fuer dieses Projekt sind noch keine Kopfdaten angelegt.")
        db = SessionLocal()
        gespeichert = db.get(Kopfdaten, eintrag.id)
        for feld in felder or ():
            if feld not in FELDER:
                continue
            wert = str((aus_dokument or {}).get(feld, "") or "").strip()
            if not wert:
                continue
            setattr(gespeichert, feld, wert)
            if feld == "projektleiter":
                gespeichert.projektleiter_anrede = self._schaetze(wert)
            elif feld == "auftraggeber":
                gespeichert.auftraggeber_anrede = self._schaetze(wert)
        gespeichert.aktualisiert_durch = durch or ""
        db.commit()
        return gespeichert
