"""Embeddings über Voyage AI – über die Schutzschicht ODER ausdrücklich direkt.

Dieser Weg trägt denselben Text ins Ausland wie der Chat und wird regelmässig
übersehen (ANBINDUNG.md 6.5): beim Indexieren den Korpustext, bei der Suche die
Anfrage aus dem Gespräch. Welcher Weg gilt, bestimmt `app.domains.llm.datenweg`
aus der Konfiguration – nicht dieser Client.

Zwei Betriebsarten:

- **schutzschicht** (`basis_url`): Anfragen an die anbieterkompatible Basis-URL
  der vorgeschalteten Schutzschicht, mit Kontext-Kopfzeilen (Anwendung,
  Mandant, Projekt). Der Anbieterschlüssel liegt dort, nicht hier. Zurück kommt
  der Vektor des *pseudonymisierten* Texts – Korpus und Suchanfrage müssen
  deshalb konsistent über denselben Weg laufen.
- **direkt** (`api_key`): Anfragen direkt an Voyage, ohne Pseudonymisierung.
  Nur, wenn das ausdrücklich konfiguriert ist (EMBEDDING_DIREKT=1).

Fällt der konfigurierte Weg aus, gibt es einen Fehler – nie einen Wechsel auf
den anderen Weg. Ohne Weg ist der Client inaktiv: embed() liefert None, und
Aufrufer behandeln das als «RAG nicht verfügbar».
"""
import time

import requests

from app.domains.llm.errors import PseudoNichtErreichbar

_BATCH = 64  # Voyage erlaubt mehr; konservativ wegen Token-/Größenlimits.
VOYAGE_URL = "https://api.voyageai.com/v1/embeddings"


class EmbeddingDienstNichtErreichbar(RuntimeError):
    """Der direkt angebundene Embedding-Dienst antwortet nicht."""


class VoyageEmbedder:
    def __init__(self, basis_url=None, model="voyage-3", timeout=60,
                 anwendung="hermes-pia", mandant="standard", projekt="korpus",
                 api_key=None):
        self.basis_url = (basis_url or "").rstrip("/")
        # Ein Schlüssel wirkt NUR ohne Schutzschicht – ist eine konfiguriert,
        # geht nichts an ihr vorbei.
        self.api_key = None if self.basis_url else (api_key or None)
        self.model = model
        self.timeout = timeout
        self.anwendung = anwendung
        self.mandant = mandant or ""
        self.projekt = projekt or "korpus"
        # Wie viele Tokens der Dienst gemeldet hat – für die Kostenkontrolle.
        self.tokens = 0
        # Bei Ratenbegrenzung (429): im Gespräch kurz warten, beim Laden länger
        # (das Ladeskript setzt die Werte hoch).
        self.wiederholungen = 2
        self.wartezeit = 5

    @property
    def modus(self):
        if self.basis_url:
            return "schutzschicht"
        return "direkt" if self.api_key else "aus"

    @property
    def available(self):
        return self.modus != "aus"

    def fuer(self, projekt=None, mandant=None):
        """Kurzlebiger Ableger mit Anfragekontext – analog zum LLMClient."""
        return VoyageEmbedder(basis_url=self.basis_url, model=self.model,
                              timeout=self.timeout, anwendung=self.anwendung,
                              mandant=mandant or self.mandant,
                              projekt=str(projekt) if projekt else self.projekt,
                              api_key=self.api_key)

    def _anfrage(self, batch, input_type):
        body = {"input": batch, "model": self.model, "input_type": input_type}
        if self.basis_url:
            try:
                return requests.post(
                    f"{self.basis_url}/v1/embeddings",
                    headers={"Content-Type": "application/json",
                             "X-Pseudo-Anwendung": self.anwendung,
                             "X-Pseudo-Mandant": str(self.mandant),
                             "X-Pseudo-Projekt": str(self.projekt)},
                    json=body, timeout=self.timeout)
            except requests.RequestException as e:
                # Kein Ausweichweg direkt zu Voyage – sonst ginge der Text
                # ungeschuetzt raus.
                raise PseudoNichtErreichbar(
                    f"Schutzschicht nicht erreichbar ({e.__class__.__name__}).") from e
        try:
            # Direktmodus: Kontext-Kopfzeilen gehen NICHT an den Anbieter.
            return requests.post(VOYAGE_URL,
                                 headers={"Content-Type": "application/json",
                                          "Authorization": f"Bearer {self.api_key}"},
                                 json=body, timeout=self.timeout)
        except requests.RequestException as e:
            raise EmbeddingDienstNichtErreichbar(
                f"Embedding-Dienst nicht erreichbar ({e.__class__.__name__}).") from e

    def embed(self, texts, input_type="document"):
        """Bettet eine Liste von Texten ein. Rückgabe: Liste von Vektoren (Listen
        von Floats) in derselben Reihenfolge, oder None wenn nicht konfiguriert."""
        if not self.available:
            return None
        if isinstance(texts, str):
            texts = [texts]
        out = []
        for i in range(0, len(texts), _BATCH):
            batch = texts[i:i + _BATCH]
            resp = self._anfrage(batch, input_type)
            # Ratenbegrenzung des Anbieters (HTTP 429): warten und DENSELBEN Weg
            # erneut versuchen – nie auf einen anderen Weg ausweichen.
            for versuch in range(self.wiederholungen):
                if getattr(resp, "status_code", 200) != 429:
                    break
                warte = resp.headers.get("Retry-After") if getattr(resp, "headers", None) else None
                try:
                    sekunden = float(warte) if warte else self.wartezeit * (2 ** versuch)
                except ValueError:
                    sekunden = self.wartezeit * (2 ** versuch)
                time.sleep(min(sekunden, 60))
                resp = self._anfrage(batch, input_type)
            resp.raise_for_status()
            antwort = resp.json()
            self.tokens += int((antwort.get("usage") or {}).get("total_tokens") or 0)
            data = sorted(antwort.get("data", []), key=lambda d: d.get("index", 0))
            out.extend(d["embedding"] for d in data)
        return out

    def embed_one(self, text, input_type="query"):
        vecs = self.embed([text], input_type=input_type)
        return vecs[0] if vecs else None
