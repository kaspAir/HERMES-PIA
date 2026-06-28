"""Speech-to-Text über einen OpenAI-kompatiblen /audio/transcriptions-Endpoint.

Bewusst anbieter-flexibel: Durch Setzen von STT_API_URL/-KEY/-MODEL lässt sich
OpenAI, Groq, Azure-OpenAI oder eine self-hosted/CH-gehostete Whisper-Instanz
nutzen (wichtig für Behördendaten / Datenresidenz). Ohne Key ist die Funktion
inaktiv (available=False) – das Deployment bleibt gefahrlos.
"""
import requests


class Transcriber:
    def __init__(self, api_url=None, api_key=None, model="whisper-1", timeout=90):
        self.api_url = api_url or "https://api.openai.com/v1/audio/transcriptions"
        self.api_key = api_key or ""
        self.model = model
        self.timeout = timeout

    @property
    def available(self):
        return bool(self.api_key)

    def transcribe(self, audio_bytes, filename="segment.webm", mimetype="audio/webm",
                   language="de"):
        """Transkribiert ein (vollständiges) Audiosegment. Rückgabe: erkannter Text
        ('' wenn kein Key oder leer)."""
        if not self.api_key or not audio_bytes:
            return ""
        files = {"file": (filename, audio_bytes, mimetype)}
        data = {"model": self.model}
        if language:
            data["language"] = language
        resp = requests.post(
            self.api_url,
            headers={"Authorization": f"Bearer {self.api_key}"},
            files=files,
            data=data,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return (resp.json() or {}).get("text", "").strip()
