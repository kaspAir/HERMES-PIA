"""Verifikation von Fundstellen auf ARTIKELEBENE – Bund und Kantone.

**Warum das nötig ist.** Die Rechtsgrundlagenanalyse zitiert auf Artikel-,
Absatz- und Litera-Ebene. Geprüft wurde bisher nur der ERLASS gegen die
amtlichen Sammlungen. Eine Artikelangabe sieht damit präziser aus, als sie
belegt ist – und gemessen war sie es auch nicht: für die Vollstreckung von
Bussen stand «StPO Art. 351 ff., insb. Art. 354» im Dokument. Art. 354 StPO
regelt die **Einsprache gegen den Strafbefehl**. Eine falsche Artikelangabe ist
gefährlicher als gar keine.

**Was dieses Modul tut und was nicht.** Es holt die amtliche Überschrift des
zitierten Artikels und gibt sie zurück. Ob die Überschrift zur Behauptung
passt, entscheidet nicht dieses Modul – es liefert den Beleg, an dem sich die
Behauptung messen lässt. Drei Zustände, und sie sind streng zu unterscheiden:

  * ``belegt``          – der Artikel existiert; seine Überschrift liegt vor.
  * ``existiert_nicht`` – der Erlasstext wurde geholt, der Artikel fehlt darin.
  * ``nicht_pruefbar``  – die Quelle war nicht erreichbar oder nicht lesbar.

«Nicht geprüft» und «nicht vorhanden» sind zwei verschiedene Dinge; sie zu
vermischen ist derselbe Fehler, den die Kartierung bei den Lücken vermeidet.

**Die Wege (gemessen, nicht vermutet):**

*Bund* – die ELI-Seite baut ihre Links per JavaScript, dort ist nichts zu
holen. Der naheliegende SPARQL-Verbund über ``ConsolidationAbstract →
isRealizedBy → isEmbodiedBy`` liefert null Treffer. Was trägt: die
Manifestations-URI folgt dem ELI-Muster, und daran hängt die Datei über
``jolux:wasExemplifiedBy``. Die HTML-Fassung enthält stabile Anker
``id="art_36"`` – 197 allein für die Bundesverfassung.

*Kantone* – die Sammlungen sind JavaScript-Seiten, direktes Auslesen scheitert.
Die Lexwork-Plattform (dieselbe wie lexfind) bietet aber ein JSON-API mit einem
``pdf_link`` auf die amtliche Fassung; deren Text ist maschinell lesbar.

**Absätze und Litera** verifiziert dieses Modul NICHT. Die Anker gehen bis zur
Artikelebene; darunter bräuchte es eine Textanalyse, die eine eigene
Fehlerquelle wäre. Ein Zitat «Art. 5 lit. c Ziff. 5» gilt deshalb als auf
Artikelebene belegt – nicht darunter. Das steht so im Ergebnis.
"""
import io
import json
import logging
import re
import urllib.parse
import urllib.request

log = logging.getLogger("hermes.rechtsquellen")

SPARQL = "https://fedlex.data.admin.ch/sparqlendpoint"
_KOPF = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

BELEGT = "belegt"
EXISTIERT_NICHT = "existiert_nicht"
NICHT_PRUEFBAR = "nicht_pruefbar"

# «Art. 36», «Art. 5 Abs. 1 BV», «Art. 351 ff.», «Art. 13a»
_ZITAT = re.compile(
    r"\bArt(?:\.|ikel)\s*(\d+[a-z]?)"
    r"(?:\s*(?:Abs\.\s*\d+[a-z]?))?"
    r"(?:\s*(?:lit\.\s*[a-z]))?"
    r"(?:\s*(?:Ziff\.\s*\d+))?",
    re.IGNORECASE)


def artikelnummern(text):
    """Alle zitierten Artikelnummern eines Textes, in Reihenfolge, ohne Dubletten."""
    raus = []
    for nr in _ZITAT.findall(str(text or "")):
        if nr not in raus:
            raus.append(nr)
    return raus


def _hol(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:   # noqa: S310
        return r.read()


def _text_aus_html(html):
    ohne = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", ohne)


class ArtikelPruefer:
    """Holt die amtliche Artikelüberschrift – Bund über Fedlex, Kantone über
    die Lexwork-Sammlungen.

    Ohne Netz (``oeffner=None`` und keine Vorgabe) ist der Prüfer INAKTIV und
    meldet ``nicht_pruefbar``: er erfindet nie einen Beleg. Tests laufen
    deshalb ohne Netzwerk.
    """

    def __init__(self, aktiv=False, oeffner=None, timeout=30):
        self.aktiv = bool(aktiv)
        self._oeffner = oeffner or _hol
        self.timeout = timeout
        self._texte = {}          # Quelle -> Volltext (einmal je Lauf holen)

    # ---- Bund ------------------------------------------------------------ #
    def _fedlex_datei(self, eli):
        """Die neueste deutschsprachige HTML-Fassung eines Erlasses.

        Die gezielte Abfrage über das ELI-Muster ist der einzige Weg, der
        Treffer liefert – der Verbund über die Ontologie-Kette nicht.
        """
        frage = (
            "PREFIX jolux: <http://data.legilux.public.lu/resource/ontology/jolux#> "
            "SELECT ?file WHERE { ?mani jolux:wasExemplifiedBy ?file . "
            f'FILTER(STRSTARTS(STR(?mani), "https://fedlex.data.admin.ch/eli/{eli}/")) '
            'FILTER(CONTAINS(STR(?mani), "/de/html")) } ORDER BY DESC(?mani) LIMIT 1')
        daten = urllib.parse.urlencode({"query": frage}).encode()
        req = urllib.request.Request(SPARQL, data=daten, headers=dict(
            _KOPF, **{"Accept": "application/sparql-results+json"}), method="POST")
        with urllib.request.urlopen(req, timeout=self.timeout) as r:   # noqa: S310
            treffer = json.loads(r.read())["results"]["bindings"]
        return treffer[0]["file"]["value"] if treffer else None

    # ---- Kanton ---------------------------------------------------------- #
    @staticmethod
    def _kantons_api(url):
        """Aus dem Sammlungs-Link die JSON-Adresse der Lexwork-Plattform."""
        m = re.match(r"(https?://[^/]+)/(?:app|data)/([a-z]{2})/texts_of_law/([^/?#]+)",
                     str(url or ""))
        return f"{m.group(1)}/api/{m.group(2)}/texts_of_law/{m.group(3)}" if m else None

    def _kantons_text(self, url):
        api = self._kantons_api(url)
        if not api:
            return None
        meta = json.loads(self._oeffner(api, self.timeout))["text_of_law"]
        pdf = meta.get("pdf_link") or ""
        if not pdf:
            return None
        if pdf.startswith("/"):
            pdf = re.match(r"(https?://[^/]+)", api).group(1) + pdf
        from pypdf import PdfReader
        leser = PdfReader(io.BytesIO(self._oeffner(pdf, self.timeout)))
        return " ".join((s.extract_text() or "") for s in leser.pages)

    # ---- Gemeinsam ------------------------------------------------------- #
    def _volltext(self, quelle):
        """Der Erlasstext – einmal je Lauf geholt und behalten."""
        if quelle in self._texte:
            return self._texte[quelle]
        text = None
        try:
            eli = re.search(r"/eli/((?:cc|oc)/[^/]+/[^/]+)", str(quelle or ""))
            if eli:
                datei = self._fedlex_datei(eli.group(1))
                if datei:
                    text = self._oeffner(datei, self.timeout).decode("utf-8", "replace")
            else:
                text = self._kantons_text(quelle)
        except Exception as e:      # noqa: BLE001 – nicht erreichbar ist ein Zustand
            log.warning("Erlasstext nicht abrufbar (%s): %s", quelle, e)
            text = None
        self._texte[quelle] = text
        return text

    def pruefe(self, quelle, artikel):
        """(Zustand, Überschrift) für EINEN Artikel eines Erlasses."""
        if not self.aktiv:
            return NICHT_PRUEFBAR, ""
        if not quelle or not artikel:
            return NICHT_PRUEFBAR, ""
        text = self._volltext(quelle)
        if not text:
            return NICHT_PRUEFBAR, ""
        # Bund: der Anker ist eindeutig. Kanton: die Fundstelle im Fliesstext.
        m = re.search(r'id="art_%s"(.{0,300})' % re.escape(artikel), text, re.DOTALL)
        roh = m.group(1) if m else None
        if roh is None:
            m = re.search(r"\bArt\.\s*%s\b(.{0,200})" % re.escape(artikel), text,
                          re.DOTALL)
            roh = m.group(1) if m else None
        if roh is None:
            return EXISTIERT_NICHT, ""
        klar = _text_aus_html(roh).replace("&nbsp;", " ").strip(" >")
        # ZUERST die Artikelnummer abstreifen, DANN am Beginn des Normtextes
        # trennen. Umgekehrt schneidet der Punkt von «Art.» die Überschrift ab -
        # gemessen blieb von «Art. 36 Einschränkungen von Grundrechten» das Wort
        # «Art» übrig.
        kopf = re.sub(r"^Art(?:\.|ikel)\s*\S+\s*", "", klar).strip()
        # Der Normtext beginnt mit der Absatznummer «1» (Fedlex) bzw. einem
        # Satzanfang; die Überschrift steht davor.
        kopf = re.split(r"\s+1\s+(?=[A-ZÄÖÜ])|\s+\d\s+", kopf, maxsplit=1)[0]
        kopf = kopf.strip(" .")
        # Nicht jeder Artikel hat eine Sachueberschrift - Art. 106 StGB etwa
        # beginnt direkt mit dem Normtext. Dann ist der ANFANG DES TEXTES die
        # ehrliche Auskunft; als «Ueberschrift» ausgegeben waere er irrefuehrend.
        if not kopf or kopf[0].isdigit():
            volltext = _text_aus_html(roh).replace("&nbsp;", " ")
            volltext = re.sub(r"^\s*>?\s*Art(?:\.|ikel)\s*\S+\s*", "", volltext)
            return BELEGT, "[Wortlaut] " + volltext.strip()[:200]
        return BELEGT, kopf[:160]

    def pruefe_fundstelle(self, quelle, zitat):
        """Alle Artikel EINES Zitats. Rückgabe: Liste von Befunden."""
        raus = []
        for nr in artikelnummern(zitat):
            zustand, kopf = self.pruefe(quelle, nr)
            raus.append({"artikel": nr, "zustand": zustand, "ueberschrift": kopf,
                         "quelle": quelle})
        return raus
