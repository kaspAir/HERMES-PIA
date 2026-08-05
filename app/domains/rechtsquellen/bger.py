"""Zugang zur Rechtsprechung des Bundesgerichts.

**Die tragende Regel: NIE erfinden.** Ein erfundener Bundesgerichtsentscheid ist
der teuerste Fehler, den dieses Produkt machen kann – er sieht aus wie ein
Beleg, wird zitiert und trägt eine Entscheidung, die es nicht gibt. Deshalb ist
die Regel hier keine Bitte an ein Sprachmodell, sondern die Bauform des Moduls:

* Ein Entscheid entsteht ausschliesslich aus einer **Antwort der amtlichen
  Suche**. Es gibt keinen Weg, ein Urteil in dieses Modul hineinzuschreiben.
* Jeder Eintrag trägt seine **amtliche Kennung** (Aktenzeichen bzw. BGE-Nummer),
  sein Datum und die Adresse beim Bundesgericht. Fehlt die Kennung, wird der
  Treffer verworfen – lieber nichts als ein Verweis, den niemand nachschlagen
  kann.
* Ohne Netz ist das Modul **inaktiv** und liefert eine leere Liste. Es gibt
  keinen Ersatzweg und keinen Zwischenspeicher mit Inhalten, die niemand
  geprüft hat.

Gemessen an der amtlichen Suche (search.bger.ch, Eurospider): Die Trefferseite
verweist auf ``highlight_docid``-Kennungen der Form ``aza://<datum>-<az>`` für
Urteile und ``atf://<band>-<teil>-<seite>:de`` für amtlich publizierte
Entscheide (BGE). Beide lassen sich einzeln abrufen.

Was dieses Modul NICHT tut: Es beurteilt nicht, ob ein Entscheid einschlägig
ist. Es liefert, was die amtliche Suche zu einem Suchbegriff zurückgibt – die
Würdigung bleibt Sache der Methode und des Menschen.
"""
import logging
import re
import urllib.parse
import urllib.request

log = logging.getLogger("hermes.rechtsquellen")

BASIS = ("https://search.bger.ch/ext/eurospider/live/de/php/aza/http/index.php")
_KOPF = {"User-Agent": "Mozilla/5.0"}

# aza://17-10-2024-1C_63-2023  ·  atf://151-I-137:de
_AZA = re.compile(r"aza://(\d{2})-(\d{2})-(\d{4})-([0-9][A-Z]_\d+)-(\d{4})")
_ATF = re.compile(r"atf://(\d{2,3})-([IVX]+)-(\d+)")


def _entziffere(docid):
    """(Kennung, Datum) aus einer amtlichen Dokumentkennung – oder (None, None).

    Was sich nicht entziffern laesst, wird verworfen: ein Treffer ohne
    nachschlagbare Kennung ist als Beleg wertlos.
    """
    m = _AZA.search(docid)
    if m:
        tag, monat, jahr, az, azjahr = m.groups()
        return f"{az}/{azjahr}", f"{tag}.{monat}.{jahr}"
    m = _ATF.search(docid)
    if m:
        band, teil, seite = m.groups()
        return f"BGE {band} {teil} {seite}", ""
    return None, None


class BgerClient:
    """Sucht Entscheide über die amtliche Suche des Bundesgerichts.

    ``aktiv=False`` (Vorgabe) heisst: keine Netzzugriffe, leere Ergebnisse.
    Damit laufen Tests ohne Netz, und ein Deployment entscheidet bewusst, ob
    Suchbegriffe den Host verlassen – dieselbe Regel wie bei lexfind.
    """

    def __init__(self, aktiv=False, oeffner=None, timeout=30):
        self.aktiv = bool(aktiv)
        self._oeffner = oeffner or self._hol
        self.timeout = timeout
        self._cache = {}

    @staticmethod
    def _hol(url, timeout=30):
        req = urllib.request.Request(url, headers=_KOPF)
        with urllib.request.urlopen(req, timeout=timeout) as r:   # noqa: S310
            return r.read().decode("utf-8", "replace")

    def _url(self, **params):
        return BASIS + "?" + urllib.parse.urlencode(params)

    def suche(self, begriff, treffer=5):
        """Entscheide zu einem Suchbegriff. Leere Liste bei Fehler oder ohne Netz.

        Rückgabe je Eintrag: kennung, datum, url, fundstelle_geprueft=True.
        Das Feld sagt: diese Kennung stammt aus der amtlichen Suche, nicht aus
        einem Modell.
        """
        begriff = (begriff or "").strip()
        if not self.aktiv or not begriff:
            return []
        if begriff in self._cache:
            return self._cache[begriff][:treffer]
        adresse = self._url(lang="de", type="simple_query", query_words=begriff,
                            mode="and", top_subcollection_aza="all")
        try:
            seite = self._oeffner(adresse, self.timeout)
        except Exception as e:      # noqa: BLE001 – ohne Netz gibt es nichts
            log.warning("BGer-Suche nicht erreichbar (%s): %s", begriff, e)
            return []

        raus, gesehen = [], set()
        for roh in re.findall(r"highlight_docid=([^&\"'>]+)", seite):
            docid = urllib.parse.unquote(roh)
            kennung, datum = _entziffere(docid)
            if not kennung or kennung in gesehen:
                continue
            gesehen.add(kennung)
            raus.append({
                "kennung": kennung,
                "datum": datum,
                "url": self._url(lang="de", type="show_document",
                                 highlight_docid=docid),
                "fundstelle_geprueft": True,
            })
        self._cache[begriff] = raus
        return raus[:treffer]

    def suche_mehrere(self, begriffe, treffer_je_begriff=3):
        """Zu mehreren Begriffen suchen und zusammenführen (ohne Dubletten)."""
        zusammen, gesehen = [], set()
        for b in begriffe or []:
            for e in self.suche(b, treffer=treffer_je_begriff):
                if e["kennung"] in gesehen:
                    continue
                gesehen.add(e["kennung"])
                zusammen.append(dict(e, suchbegriff=b))
        return zusammen
