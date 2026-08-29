"""Rechtsquellen-Recherche: live über lexfind, mit Offline-Index als Netz.

Warum beides:
  * **lexfind** kennt Bund UND alle 26 Kantone, liefert Aktualität und den
    offiziellen Quell-Link – braucht aber Internetzugang vom Host.
  * **Der Offline-SR-Index** (fedlex.py) kennt nur Bundesrecht und keine
    Aktualität, funktioniert dafür immer. Er existiert, weil Fedlex vom
    Infomaniak-Host nachweislich NICHT erreichbar ist.

Reihenfolge: lexfind zuerst; was dort keinen Treffer hat (oder wenn lexfind ganz
ausfällt), wird im Offline-Index nachgeschlagen. Damit wird die Recherche durch
den Netzzugang besser, ohne von ihm abzuhängen – und es wird nie geraten.

`quelle` je Treffer hält fest, woher die Fundstelle stammt ('lexfind' | 'index').
Das gehört ins Nachweis-Protokoll: eine Fundstelle aus dem Offline-Index ist
nicht auf Aktualität geprüft.
"""
import logging

log = logging.getLogger("hermes.recherche")


class RechercheClient:
    def __init__(self, lexfind=None, index=None):
        self.lexfind = lexfind
        self.index = index
        self.letzte_quelle = ""      # 'lexfind' | 'index' | 'keine'

    @property
    def available(self):
        return bool(self.lexfind or self.index)

    def suche_mehrere(self, begriffe, treffer_je_begriff=1, ebene=None, kanton=None):
        """{begriff: [{sr, titel, url, quelle, …}]} – gleiche Form wie die Einzelclients."""
        if not begriffe:
            return {}
        out, live_ok = {}, False

        if self.lexfind is not None:
            try:
                gefunden = self.lexfind.suche_mehrere(
                    begriffe, treffer_je_begriff=treffer_je_begriff,
                    ebene=ebene, kanton=kanton)
                for begriff, hits in gefunden.items():
                    out[begriff] = [{**h, "quelle": "lexfind"} for h in hits]
                live_ok = bool(gefunden)
            except Exception as e:      # noqa: BLE001 – Ausfall darf nie blockieren
                log.warning("lexfind nicht nutzbar, weiche auf den Index aus: %s", e)

        # Lücken (und den Totalausfall) mit dem Offline-Index füllen.
        offen = [b for b in begriffe if b and b not in out]
        if offen and self.index is not None:
            try:
                for begriff, hits in self.index.suche_mehrere(
                        offen, treffer_je_begriff=treffer_je_begriff).items():
                    out[begriff] = [{**h, "quelle": "index", "aktiv": None} for h in hits]
            except Exception as e:      # noqa: BLE001
                log.warning("Offline-Index nicht nutzbar: %s", e)

        self.letzte_quelle = ("lexfind" if live_ok else ("index" if out else "keine"))
        return out

    def suche_kanton(self, begriffe, kanton, treffer_je_begriff=3):
        """Nur die kantonale Sammlung – ohne Netz gibt es hier NICHTS.

        Der Offline-Index kennt ausschliesslich Bundesrecht. Ihn hier als Netz
        einzusetzen hiesse, auf eine kantonale Frage eine Bundesantwort zu geben.
        Ohne lexfind bleibt die Antwort deshalb leer, und der Aufrufer meldet
        ehrlich «nicht prüfbar».
        """
        if self.lexfind is None or not begriffe or not kanton:
            return {}
        try:
            return self.lexfind.suche_kanton(begriffe, kanton, treffer_je_begriff)
        except Exception as e:      # noqa: BLE001 – Ausfall darf nie blockieren
            log.warning("lexfind (kantonal) nicht nutzbar: %s", e)
            return {}
