"""Die Invarianten-Prüfung – Stufe 1 des Umsetzungs-Briefings.

Führt die D-Regeln aus und liefert eine Befundliste, gruppiert nach
Muss / Vorbehalt / Hinweis. Läuft OHNE Sprachmodell und ist reproduzierbar.

Die Prüfung ist bewusst vom Erzeugen getrennt (Briefing, Leitplanken): dieses
Modul kennt den Interview-Service nicht und ändert nichts – es liest und urteilt.
"""
import json
import logging

from app.domains.qualitaet import katalog as K
from app.domains.qualitaet.dokument import pruefe_dokument
from app.domains.qualitaet.modell import Pruefergebnis
from app.domains.qualitaet.regeln import REGELN

log = logging.getLogger("hermes.qualitaet")


class Pruefkontext:
    """Alles, was die Regeln über einen PIA wissen müssen – an einer Stelle.

    Was das Datenmodell (noch) nicht führt, meldet `hat_feld` als fehlend; die
    betroffene Regel weist sich dann als «nicht prüfbar» aus, statt still zu
    schweigen.
    """

    # Felder aus Katalog Abschnitt 12, die das Datenmodell heute NICHT führt.
    FEHLENDE_FELDER = {
        "ziel_ergebnis_zuordnung", "ergebnis_projektspezifisch",
        "mitarbeitende_rollen", "loesung_vorbestimmt", "evidenz_je_angabe",
        "kostensatz_status",
    }

    def __init__(self, answers, session=None, tarife=None, zusatzrollen=None,
                 mindestabstand=None, beschaffung_vorgesehen=None,
                 phasendauer_monate=None, vorhandene_felder=None):
        self.answers = answers or {}
        self.session = session
        self.tarife = tarife or {}
        self.zusatzrollen = zusatzrollen or []
        self.mindestabstand = (K.MINDESTABSTAND_ARBEITSTAGE if mindestabstand is None
                               else mindestabstand)
        self._vorhanden = set(vorhandene_felder or ())

        self.phasenstart = getattr(session, "start_datum", None) if session else None
        self.deckblatt_version = getattr(session, "doc_version", None) if session else None
        self.changelog = self._changelog(session)
        self.changelog_version = (self.changelog[-1].get("version")
                                  if self.changelog else None)
        self.phasendauer_monate = phasendauer_monate
        # Beschaffung: ausdrücklich gesetzt, sonst aus der Terminliste erschlossen
        # (D-050 ist eine BEDINGTE Regel – Katalog Abschnitt 11).
        self.beschaffung_vorgesehen = (self._beschaffung_erkannt()
                                       if beschaffung_vorgesehen is None
                                       else beschaffung_vorgesehen)

    # ---- abgeleitete Angaben -------------------------------------------- #
    @staticmethod
    def _changelog(session):
        roh = getattr(session, "changelog_json", None) if session else None
        if not roh:
            return None
        try:
            daten = json.loads(roh)
            return daten if isinstance(daten, list) else None
        except (ValueError, TypeError):
            return None

    def _beschaffung_erkannt(self):
        eintrag = self.answers.get("termine") or {}
        rows = eintrag.get("extracted") if isinstance(eintrag, dict) else None
        text = " ".join(str(r.get("ergebnis", "")) for r in (rows or [])
                        if isinstance(r, dict)).lower()
        return "beschaffung" in text

    @property
    def phasenende(self):
        """Letzter Termin der Ergebnisliste – solange die Phase kein eigenes
        Enddatum führt (Katalog Abschnitt 12)."""
        eintrag = self.answers.get("termine") or {}
        rows = eintrag.get("extracted") if isinstance(eintrag, dict) else None
        from app.domains.qualitaet.regeln import _datum
        termine = [_datum(r.get("termin")) for r in (rows or []) if isinstance(r, dict)]
        termine = [t for t in termine if t]
        return max(termine) if termine else None

    @property
    def phasendauer_arbeitstage(self):
        if not self.phasendauer_monate:
            return None
        return int(round(self.phasendauer_monate * 4.345 * K.ARBEITSTAGE_PRO_WOCHE))

    def hat_feld(self, name):
        """Führt das Datenmodell dieses Feld schon?"""
        if name in self._vorhanden:
            return True
        return name not in self.FEHLENDE_FELDER


def pruefe(answers, session=None, tarife=None, dokument=None, standardtext=None,
           zusatzrollen=None, mindestabstand=None, beschaffung_vorgesehen=None,
           phasendauer_monate=None, vorhandene_felder=None):
    """Führt die Invarianten-Prüfung durch.

    `answers`   strukturierte Abschnittsdaten (Ebene «Daten»)
    `dokument`  optional ein python-docx-Document (Ebene «Dok»)

    Rückgabe: Pruefergebnis mit Befunden, gruppierbar nach Gewicht.
    """
    ctx = Pruefkontext(answers, session=session, tarife=tarife,
                       zusatzrollen=zusatzrollen, mindestabstand=mindestabstand,
                       beschaffung_vorgesehen=beschaffung_vorgesehen,
                       phasendauer_monate=phasendauer_monate,
                       vorhandene_felder=vorhandene_felder)
    ergebnis = Pruefergebnis()

    for fn in REGELN:
        try:
            gefunden = list(fn(ctx) or [])
        except Exception as e:      # noqa: BLE001 – eine kaputte Regel darf die
            # Prüfung nicht kippen; sie faellt aus und sagt es.
            log.exception("Regel %s fehlgeschlagen", fn.rid)
            ergebnis.uebersprungen.append(fn.rid)
            continue
        ergebnis.geprueft.append(fn.rid)
        ergebnis.befunde.extend(gefunden)

    if dokument is not None:
        ergebnis.befunde.extend(pruefe_dokument(dokument, standardtext=standardtext))
        ergebnis.geprueft.extend(["D-003", "D-004", "D-005", "D-011", "D-081"])
        if standardtext:
            ergebnis.geprueft.append("D-020")

    return ergebnis
