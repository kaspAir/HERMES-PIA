"""Embeddings über Voyage AI – ebenfalls durch die Pseudonymisierungsschicht.

Dieser Weg trägt denselben Text ins Ausland wie der Chat und wird regelmässig
übersehen (ANBINDUNG.md 6.5). Deshalb läuft er über dieselbe Basis-URL; einen
eigenen Voyage-Schlüssel besitzt HERMES PIA nicht mehr.

**Keine Rückersetzung:** zurück kommt ein Vektor. Der erzeugte Vektor ist der
Vektor des *pseudonymisierten* Texts. Das ist gewollt und muss beim Beurteilen
der Trefferqualität mitgedacht werden – und es heisst umgekehrt, dass Korpus und
Suchanfrage konsistent pseudonymisiert sein müssen, sonst sinkt die Trefferquote.

Ohne konfigurierte Basis-URL ist der Client inaktiv: embed() liefert None, und
Aufrufer behandeln das als 'RAG nicht verfügbar'.
"""
import requests

from app.domains.llm.errors import PseudoNichtErreichbar

_BATCH = 64  # Voyage erlaubt mehr; konservativ wegen Token-/Größenlimits.


class VoyageEmbedder:
    def __init__(self, basis_url=None, model="voyage-3", timeout=60,
                 anwendung="hermes-pia", mandant="standard", projekt="korpus"):
        self.basis_url = (basis_url or "").rstrip("/")
        self.model = model
        self.timeout = timeout
        self.anwendung = anwendung
        self.mandant = mandant or ""
        self.projekt = projekt or "korpus"

    @property
    def available(self):
        return bool(self.basis_url)

    def fuer(self, projekt=None, mandant=None):
        """Kurzlebiger Ableger mit Anfragekontext – analog zum LLMClient."""
        return VoyageEmbedder(basis_url=self.basis_url, model=self.model,
                              timeout=self.timeout, anwendung=self.anwendung,
                              mandant=mandant or self.mandant,
                              projekt=str(projekt) if projekt else self.projekt)

    def embed(self, texts, input_type="document"):
        """Bettet eine Liste von Texten ein. Rückgabe: Liste von Vektoren (Listen
        von Floats) in derselben Reihenfolge, oder None wenn nicht konfiguriert."""
        if not self.basis_url:
            return None
        if isinstance(texts, str):
            texts = [texts]
        out = []
        for i in range(0, len(texts), _BATCH):
            batch = texts[i:i + _BATCH]
            try:
                resp = requests.post(
                    f"{self.basis_url}/v1/embeddings",
                    headers={
                        "Content-Type": "application/json",
                        "X-Pseudo-Anwendung": self.anwendung,
                        "X-Pseudo-Mandant": str(self.mandant),
                        "X-Pseudo-Projekt": str(self.projekt),
                    },
                    json={"input": batch, "model": self.model, "input_type": input_type},
                    timeout=self.timeout,
                )
            except requests.RequestException as e:
                # Kein Ausweichweg direkt zu Voyage – sonst ginge der Text
                # ungeschuetzt raus.
                raise PseudoNichtErreichbar(
                    f"Pseudonymisierungsdienst nicht erreichbar ({e.__class__.__name__})."
                ) from e
            resp.raise_for_status()
            data = resp.json().get("data", [])
            # Reihenfolge über 'index' absichern.
            data = sorted(data, key=lambda d: d.get("index", 0))
            out.extend(d["embedding"] for d in data)
        return out

    def embed_one(self, text, input_type="query"):
        vecs = self.embed([text], input_type=input_type)
        return vecs[0] if vecs else None
