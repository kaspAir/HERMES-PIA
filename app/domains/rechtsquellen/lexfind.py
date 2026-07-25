"""Live-Recherche über lexfind.ch – Bund UND alle 26 Kantone.

Ergänzt den Offline-SR-Index (fedlex.py), der nur Bundesrecht kennt und keine
Aktualität mitliefert. lexfind aggregiert Bund, Kantone und Gemeindeerlasse und
gibt je Treffer die echte Systematik-Nummer, den Aktiv-Status und den OFFIZIELLEN
Quell-Link (fedlex.admin.ch, bgs.zg.ch, …) zurück.

Bewusst dieselbe Schnittstelle wie FedlexClient (`suche_mehrere`), damit beide
austauschbar im bestehenden Grounding stecken.

**Deterministisch, nicht modellgesteuert.** Die Suchbegriffe bestimmt die
Anwendung (aus Gesetzesnamen abgeleitet), nicht das Sprachmodell. Zwei Gründe:
  1. Nachvollziehbarkeit – jede Fundstelle stammt aus einer protokollierbaren
     Abfrage, nichts wird geraten ([[feedback_no_hallucination]]).
  2. Datenschutz – ein Werkzeugaufruf, dessen Suchtext das Modell frei füllt,
     könnte Projektinhalte an einen externen Dienst tragen und würde damit die
     Pseudonymisierungsschicht umgehen. Hier verlassen nur Rechtsbegriffe den Host.

Gemessen 2026-07-25: Die API verlangt Browser-Kopfzeilen und einen NICHT leeren
`entity_filter` – sonst 400 «Ungültige Anfrage». Die eigentlichen Treffer stehen
in `texts_of_law_with_matches`, nicht in `results` (dort steht nur eine
Sprachstatistik).

Vorbehalt: undokumentierte Frontend-API ohne zugesicherte Stabilität/Terms. Für
den Produktivbetrieb ist ein sanktionierter Zugang bei lexfind/Sitrox zu klären.
Fällt sie aus, liefert der Client leer – der Aufrufer fällt auf den Offline-Index
zurück. Es wird NIE geraten.
"""
import json
import logging
import re
import time
import urllib.error
import urllib.request

log = logging.getLogger("hermes.lexfind")

_BASIS = "https://www.lexfind.ch/api/frontend/v1/de"
# Ohne diese Kopfzeilen antwortet die API mit 400 (Frontend-API, Bot-Schutz).
_KOPF = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
    "Referer": "https://www.lexfind.ch/",
}

# Entity-IDs, gemessen am 2026-07-25 über /entities/extended. Fest hinterlegt:
# spart je Suche einen Zusatzaufruf und funktioniert auch, wenn der Endpunkt
# langsam ist. Die Zuordnung ist stabil (Kantone ändern sich nicht).
BUND = 27
KANTON_ENTITY = {
    "aargau": 1, "ag": 1, "appenzell innerrhoden": 2, "ai": 2,
    "appenzell ausserrhoden": 3, "ar": 3, "bern": 4, "be": 4,
    "basel-landschaft": 5, "baselland": 5, "bl": 5, "basel-stadt": 6, "bs": 6,
    "freiburg": 7, "fribourg": 7, "fr": 7, "genf": 8, "genève": 8, "ge": 8,
    "glarus": 9, "gl": 9, "graubünden": 10, "graubuenden": 10, "gr": 10,
    "jura": 11, "ju": 11, "luzern": 12, "lu": 12, "neuenburg": 13,
    "neuchâtel": 13, "ne": 13, "nidwalden": 14, "nw": 14, "obwalden": 15,
    "ow": 15, "st. gallen": 16, "st.gallen": 16, "sankt gallen": 16, "sg": 16,
    "schaffhausen": 17, "sh": 17, "solothurn": 18, "so": 18, "schwyz": 19,
    "sz": 19, "thurgau": 20, "tg": 20, "tessin": 21, "ticino": 21, "ti": 21,
    "uri": 22, "ur": 22, "waadt": 23, "vaud": 23, "vd": 23, "wallis": 24,
    "valais": 24, "vs": 24, "zug": 25, "zg": 25, "zürich": 26, "zuerich": 26,
    "zh": 26,
}


def entity_ids(ebene=None, kanton=None):
    """Welche Sammlungen durchsucht werden.

    Bundesrecht gilt in jedem Kanton – es wird DESHALB immer mitgesucht, auch bei
    rein kantonaler Ebene (gleiche Logik wie beim Fedlex-Grounding)."""
    ids = [BUND]
    kid = KANTON_ENTITY.get((kanton or "").strip().lower())
    if kid:
        ids.append(kid)
    return ids


def _entfrage_hervorhebung(text):
    """lexfind markiert Treffer mit <span class="match">…</span>."""
    return re.sub(r"<[^>]+>", "", text or "").strip()


class LexfindClient:
    def __init__(self, timeout=12, basis=_BASIS, oeffner=None):
        self.timeout = timeout
        self.basis = basis
        # Injizierbar -> Tests belegen den ganzen Weg ohne Netz.
        self._oeffner = oeffner or urllib.request.urlopen
        self._cache = {}          # (begriff, entities) -> Trefferliste
        self.letzter_fehler = ""

    @property
    def available(self):
        return True               # Erreichbarkeit zeigt sich erst beim Aufruf

    # ---- HTTP ------------------------------------------------------------ #
    def _post(self, pfad, koerper):
        req = urllib.request.Request(self.basis + pfad,
                                     data=json.dumps(koerper).encode("utf-8"),
                                     headers=_KOPF, method="POST")
        with self._oeffner(req, timeout=self.timeout) as r:
            return json.loads(r.read().decode("utf-8"))

    def _get(self, pfad):
        req = urllib.request.Request(self.basis + pfad, headers=_KOPF)
        with self._oeffner(req, timeout=self.timeout) as r:
            return json.loads(r.read().decode("utf-8"))

    # ---- Suche ----------------------------------------------------------- #
    def suche(self, begriff, entities=None, treffer=3):
        """Trefferliste zu EINEM Begriff über EINE ODER MEHRERE Sammlungen.

        Gemessen: die API nimmt genau EINE Entity je Anfrage (Bund UND Kanton
        zusammen -> 400). Mehrere Sammlungen werden deshalb einzeln abgefragt und
        hier zusammengeführt. Leere Liste bei Fehler/ohne Treffer – nie geraten."""
        begriff = (begriff or "").strip()
        if not begriff:
            return []
        entities = entities or [BUND]
        if len(entities) > 1:
            zusammen = []
            for eine in entities:
                zusammen.extend(self.suche(begriff, entities=[eine], treffer=treffer))
            return zusammen
        schluessel = (begriff.lower(), tuple(entities))
        if schluessel in self._cache:
            return self._cache[schluessel][:treffer]

        koerper = {
            "search_text": begriff,
            "entity_filter": list(entities),     # genau EINE, und nie leer
            "category_filter": [], "systematic_filter": [],
            "use_global_systematics": False, "direct_search": True,
            "search_in_title": True, "search_in_keywords": True,
            "search_in_content": False, "search_in_systematic_number": False,
            "active_only": True,
        }
        try:
            angelegt = self._post("/fulltext-search", koerper)
            such_id, sitzung = angelegt.get("id"), angelegt.get("session_id", "")
            if not such_id:
                return []
            roh = self._get(f"/fulltext-search/{such_id}"
                            f"?session_id={sitzung}&page_no=1&results_per_page={max(treffer, 5)}")
        except (urllib.error.URLError, OSError, ValueError, TimeoutError) as e:
            # Nicht erreichbar / geändert -> ehrlich leer, Aufrufer weicht aus.
            self.letzter_fehler = f"{e.__class__.__name__}: {e}"
            log.warning("lexfind-Suche '%s' fehlgeschlagen: %s", begriff, e)
            return []

        gefunden = []
        for eintrag in (roh.get("texts_of_law_with_matches") or []):
            sr = (eintrag.get("systematic_number") or "").strip()
            if not sr:
                continue
            titel = ""
            for m in (eintrag.get("matches") or []):
                titel = _entfrage_hervorhebung(m.get("title_hl"))
                if titel:
                    break
            url = ""
            for u in (eintrag.get("dta_urls") or []):
                if u.get("language") == "de" and u.get("original_url"):
                    url = u["original_url"]
                    break
            ent = eintrag.get("entity") or {}
            gefunden.append({
                "sr": sr, "titel": titel, "url": url,
                "aktiv": bool(eintrag.get("is_active")),
                "entity": ent.get("abbreviation") or ent.get("name") or "",
            })
        self._cache[schluessel] = gefunden
        return gefunden[:treffer]

    def suche_mehrere(self, begriffe, treffer_je_begriff=1, ebene=None, kanton=None):
        """{begriff: [{sr, titel, url, …}]} – gleiche Form wie FedlexClient.

        Reihenfolge je Begriff: Bundesrecht zuerst, dann kürzeste Systematik-Nummer
        (i.d.R. der Haupterlass statt einer Ausführungsverordnung). Bundesrecht
        vorn, weil ein unqualifiziert genannter Gesetzesname in aller Regel den
        Bundeserlass meint – der zudem in jedem Kanton gilt."""
        if not begriffe:
            return {}
        ents = entity_ids(ebene, kanton)
        out = {}
        for begriff in dict.fromkeys(b for b in begriffe if b):
            hits = self.suche(begriff, entities=ents, treffer=max(treffer_je_begriff, 3))
            if hits:
                hits = sorted(hits, key=lambda h: (h.get("entity") != "CH",
                                                   len(h["sr"]), h["sr"]))
                out[begriff] = hits[:treffer_je_begriff]
            time.sleep(0.15)      # freundlich zur fremden API
        return out
