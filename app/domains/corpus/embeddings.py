"""Embeddings über die Voyage-AI-REST-API (kein zusätzliches pip-Paket nötig).

Ohne API-Key ist der Client inaktiv: embed() liefert dann None, und Aufrufer
behandeln das als 'RAG nicht verfügbar' (Suche/Ingest tun nichts). So bleibt das
Deployment ohne Key gefahrlos.
"""
import requests

API_URL = "https://api.voyageai.com/v1/embeddings"
_BATCH = 64  # Voyage erlaubt mehr; konservativ wegen Token-/Größenlimits.


class VoyageEmbedder:
    def __init__(self, api_key=None, model="voyage-3", timeout=60):
        self.api_key = api_key or ""
        self.model = model
        self.timeout = timeout

    @property
    def available(self):
        return bool(self.api_key)

    def embed(self, texts, input_type="document"):
        """Bettet eine Liste von Texten ein. Rückgabe: Liste von Vektoren (Listen
        von Floats) in derselben Reihenfolge, oder None wenn kein Key gesetzt ist."""
        if not self.api_key:
            return None
        if isinstance(texts, str):
            texts = [texts]
        out = []
        for i in range(0, len(texts), _BATCH):
            batch = texts[i:i + _BATCH]
            resp = requests.post(
                API_URL,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={"input": batch, "model": self.model, "input_type": input_type},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json().get("data", [])
            # Reihenfolge über 'index' absichern.
            data = sorted(data, key=lambda d: d.get("index", 0))
            out.extend(d["embedding"] for d in data)
        return out

    def embed_one(self, text, input_type="query"):
        vecs = self.embed([text], input_type=input_type)
        return vecs[0] if vecs else None
