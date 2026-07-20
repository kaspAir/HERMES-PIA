"""Speech-to-Text über einen OpenAI-kompatiblen /audio/transcriptions-Endpoint.

Bewusst anbieter-flexibel: Durch Setzen von STT_API_URL/-KEY/-MODEL lässt sich
OpenAI, Groq, Azure-OpenAI oder eine CH-gehostete Whisper-Instanz nutzen (wichtig
für Behördendaten / Datenresidenz). Ohne Key ist die Funktion inaktiv
(available=False) – das Deployment bleibt gefahrlos.

Zwei Antwort-Stile werden AUTOMATISCH erkannt:
  * SYNCHRON  – die Antwort enthält direkt den Text ("text"): OpenAI & Co.
  * ASYNCHRON – die Antwort enthält eine "batch_id" (z.B. Infomaniak AI Services,
    betrieben in Schweizer Rechenzentren). Dann wird `/results/{batch_id}` gepollt
    und der Text von dort bzw. von `/results/{batch_id}/download` geholt.
"""
import logging
import time

import requests

log = logging.getLogger("hermes.stt")

_FERTIG = {"done", "finished", "success", "succeeded", "completed", "complete", "ok"}
_FEHLER = {"error", "failed", "failure", "canceled", "cancelled"}
# Eindeutige Transkript-Felder: Inhalt wird IMMER als Text akzeptiert (ein Diktat
# darf auch schlicht "ok" lauten).
_TEXT_KEYS = ("text", "transcription", "transcript")
# Mehrdeutige Felder: hier koennte auch Steuerinformation stehen -> filtern.
_TEXT_KEYS_GENERISCH = ("output", "result")
_KEIN_TEXT = _FERTIG | _FEHLER | {"pending", "processing", "running", "queued", "waiting"}
# Whisper wertet nur den Anfang des Prompts aus (~224 Tokens); alles darüber ist
# wirkungslos. Konservativ begrenzen, damit der generische Teil nie verdrängt wird.
_PROMPT_MAX = 900


def _entpacke(d):
    """Infomaniak & Co. verschachteln die Nutzdaten oft unter 'data'."""
    while isinstance(d, dict) and isinstance(d.get("data"), (dict, list)):
        d = d["data"]
    return d


def _status(d):
    d = _entpacke(d)
    if isinstance(d, dict):
        for k in ("status", "state"):
            v = d.get(k)
            if isinstance(v, str):
                return v.strip().lower()
    return ""


def _text_aus(d):
    """Sucht den Transkript-Text tolerant in einer (verschachtelten) Antwort."""
    d = _entpacke(d)
    kandidaten = [d] if isinstance(d, dict) else (d if isinstance(d, list) else [])
    for eintrag in kandidaten:
        if not isinstance(eintrag, dict):
            continue
        for k in _TEXT_KEYS:                     # eindeutig -> immer akzeptieren
            v = eintrag.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        for k in _TEXT_KEYS_GENERISCH:           # mehrdeutig -> Steuerwoerter aussortieren
            v = eintrag.get(k)
            if isinstance(v, str) and v.strip() and v.strip().lower() not in _KEIN_TEXT:
                return v.strip()
        for v in eintrag.values():              # eine Ebene tiefer schauen
            if isinstance(v, (dict, list)):
                t = _text_aus(v)
                if t:
                    return t
    return ""


class Transcriber:
    def __init__(self, api_url=None, api_key=None, model="whisper-1", timeout=45,
                 poll_timeout=100, poll_intervall=2.0, language="de", prompt=""):
        self.api_url = api_url or "https://api.openai.com/v1/audio/transcriptions"
        self.api_key = api_key or ""
        self.model = model
        self.timeout = timeout
        # Budget bewusst UNTER dem Gunicorn-Worker-Timeout (120 s): so kommt im
        # Zweifel eine saubere leere Rueckgabe statt eines abgeschossenen Workers.
        self.poll_timeout = poll_timeout
        self.poll_intervall = poll_intervall
        self.language = language or ""          # leer -> Parameter nicht senden
        self.prompt = prompt or ""              # Vokabular-Hinweis (Fachbegriffe)

    @property
    def available(self):
        return bool(self.api_key)

    @property
    def _headers(self):
        return {"Authorization": f"Bearer {self.api_key}"}

    def _results_url(self, batch_id):
        """…/openai/audio/transcriptions  ->  …/results/{batch_id}"""
        basis = self.api_url.split("/openai/audio/transcriptions")[0].rstrip("/")
        return f"{basis}/results/{batch_id}"

    def transcribe(self, audio_bytes, filename="segment.webm", mimetype="audio/webm",
                   language=None, kontext=""):
        """Transkribiert ein (vollständiges) Audiosegment. Rückgabe: erkannter Text
        ('' wenn kein Key, leer oder Dienst nicht verfügbar).

        `kontext`: projektspezifischer Vokabular-Hinweis (z.B. aus der laufenden
        Session). Wird an den generischen Basis-Prompt angehängt."""
        if not self.api_key or not audio_bytes:
            return ""
        data = {"model": self.model}
        sprache = self.language if language is None else language
        if sprache:
            data["language"] = sprache
        prompt = " ".join(p for p in (self.prompt, (kontext or "").strip()) if p).strip()
        if prompt:                               # Vokabular/Stil vorspannen
            data["prompt"] = prompt[:_PROMPT_MAX]
        resp = requests.post(
            self.api_url, headers=self._headers,
            files={"file": (filename, audio_bytes, mimetype)},
            data=data, timeout=self.timeout,
        )
        resp.raise_for_status()
        try:
            body = resp.json() or {}
        except ValueError:                       # z.B. response_format=text
            return (resp.text or "").strip()

        text = _text_aus(body)
        if text:
            return text                          # synchron (OpenAI & Co.)

        entpackt = _entpacke(body)
        batch_id = entpackt.get("batch_id") if isinstance(entpackt, dict) else None
        if batch_id:
            return self._warte_auf_ergebnis(str(batch_id))
        return ""

    # ---- asynchroner Pfad (z.B. Infomaniak AI Services) ------------------ #
    def _warte_auf_ergebnis(self, batch_id):
        url = self._results_url(batch_id)
        ende = time.monotonic() + self.poll_timeout
        while time.monotonic() < ende:
            try:
                r = requests.get(url, headers=self._headers, timeout=self.timeout)
            except requests.RequestException as e:
                log.warning("STT-Polling fehlgeschlagen: %s", e)
                return ""
            if r.status_code == 200:
                try:
                    body = r.json() or {}
                except ValueError:
                    body = {}
                st = _status(body)
                if st in _FEHLER:
                    log.warning("STT-Auftrag %s fehlgeschlagen (%s)", batch_id, st)
                    return ""
                text = _text_aus(body)
                if text:
                    return text
                if st in _FERTIG:                # fertig, Text separat abholen
                    return self._download(batch_id)
            time.sleep(self.poll_intervall)
        log.warning("STT-Auftrag %s: Zeitbudget (%ss) überschritten", batch_id, self.poll_timeout)
        return ""

    def _download(self, batch_id):
        try:
            r = requests.get(f"{self._results_url(batch_id)}/download",
                             headers=self._headers, timeout=self.timeout)
        except requests.RequestException as e:
            log.warning("STT-Download fehlgeschlagen: %s", e)
            return ""
        if r.status_code != 200:
            return ""
        try:
            return _text_aus(r.json() or {}) or ""
        except ValueError:
            return (r.text or "").strip()        # reiner Text als Antwort
