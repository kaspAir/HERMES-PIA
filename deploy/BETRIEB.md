# Betrieb & Stabilität – HERMES PIA

Auf dem Managed Hosting (Infomaniak, kein Docker/systemd) läuft je Umgebung ein
Gunicorn-Prozess. Damit ein abgestürzter Prozess **nicht** bis zum nächsten
Jenkins-Build unerreichbar bleibt, überwacht ein **Cron-Watchdog** alle
Umgebungen und startet sie bei Bedarf automatisch neu.

## Ein Skript für alles: `deploy/hermes_ctl.sh`

Single Source of Truth, wie eine Umgebung gestartet/geprüft wird. Wird vom
Jenkins-Deploy per SSH-stdin ausgeführt und installiert sich dabei nach
`~/bin/hermes/hermes_ctl.sh`; von dort ruft der Cron den Watchdog auf.

| Umgebung | Branch | Port | Verzeichnis      |
|----------|--------|------|------------------|
| prod     | main   | 8000 | `~/methodos`      |
| test     | test   | 8001 | `~/methodos-test` |
| int      | integration | 8002 | `~/methodos-int` |
| dev      | develop| 8003 | `~/methodos-dev` |

### Befehle (auf dem Server)

```bash
bash ~/bin/hermes/hermes_ctl.sh health dev     # /health prüfen (Exit 0/1)
bash ~/bin/hermes/hermes_ctl.sh start dev      # eine Umgebung PID-sicher neu starten
bash ~/bin/hermes/hermes_ctl.sh watchdog       # alle Umgebungen prüfen/heilen (Cron macht das)
```

## Watchdog

- Cron-Eintrag (beim Deploy automatisch gesetzt): alle 2 Minuten
  `*/2 * * * * /bin/bash ~/bin/hermes/hermes_ctl.sh watchdog`.
- Prüft je ausgerollte Umgebung `http://127.0.0.1:<port>/health`. Fällt sie aus
  (mit einem Bestätigungs-Retry gegen transiente Aussetzer), wird sie neu
  gestartet. Ein **Deploy-Marker** (`~/tmp/hermes-deploying-<env>`) hält den
  Watchdog während eines laufenden Deploys von der Umgebung fern (stale nach
  15 Min). Bewusst KEINE `flock`-Sperre um den Start: ein per `nohup` gestarteter
  Gunicorn würde ein geerbtes Lock-FD dauerhaft halten und den nächsten Deploy
  blockieren – Lock-FDs werden beim Daemon-Start daher geschlossen (`8>&- 9>&-`).
- **Log:** `~/logs/watchdog.log` – hier steht, wann/warum neu gestartet wurde.
  Das ist zugleich die beste Spur, um die eigentliche Absturzursache zu finden.

## Gunicorn-Härtung

- `--max-requests 800 --max-requests-jitter 200`: Worker werden regelmässig
  recycelt → begrenzt Speicherwachstum aus der Docx/Pptx-Erzeugung (häufige
  Absturzursache bei langlaufenden Prozessen).
- `--graceful-timeout 30`, `--timeout 120` (LLM-Aufrufe), `--capture-output`
  (Tracebacks landen in `logs/error.log`).

## Sicherheitsprinzipien (unverändert)

- Kill nur, wenn `/proc/PID/cmdline` wirklich `gunicorn` enthält.
- Nie blind `kill $(cat PID)`, nie `pkill -f` (würde die SSH-Deploy-Sitzung
  treffen). `fuser -k <port>/tcp` nur als zweites Netz.
- Promotion bleibt streng sequenziell; test ist Kunden-Umgebung.

## Rechtsquellen aktualisieren (Fedlex-SR-Index)

Das Grounding der Rechtsgrundlagenanalyse nutzt einen OFFLINE mitgelieferten
Fedlex-Index (`app/domains/rechtsquellen/data/fedlex_sr_de.json.gz`), weil der
Deploy-Host `fedlex.data.admin.ch` NICHT erreicht.

Aktualisieren (= der "Update-Button"): Jenkins-Job **"Rechtsquellen aktualisieren"**
(Pipeline aus `Jenkinsfile.rechtsquellen`, "Build Now"). Laeuft auf dem Build-Agent
(hat Internet), holt den Index neu (`scripts/refresh_fedlex_index.py`), committet ihn
nach `develop`. Job braucht eine Git-Credential mit Push-Recht.

Die kantonalen Gesetzessammlungen sind eine statische Linksammlung
(`app/domains/rechtsquellen/kantone.py`) – kein Abruf noetig; bei URL-Aenderung
eines Kantons dort anpassen.

## Transkription (STT) auf Schweizer Infrastruktur

Der Transcriber ist anbieter-flexibel und erkennt SYNCHRONE (OpenAI & Co.) wie
ASYNCHRONE Endpoints (Antwort mit `batch_id`) automatisch. Fuer Infomaniak
AI Services (Whisper, Rechenzentren in der Schweiz, OpenAI-kompatibel) genuegt
Konfiguration – kein Code:

    STT_API_URL = https://api.infomaniak.com/1/ai/<PRODUCT_ID>/openai/audio/transcriptions
    STT_API_KEY = <Infomaniak AI-Token>
    STT_MODEL   = whisper

PRODUCT_ID via `GET /1/ai` ermitteln. Der asynchrone Ablauf (POST -> batch_id ->
Polling `/1/ai/<PRODUCT_ID>/results/<batch_id>` -> ggf. `/download`) laeuft
automatisch; die Poll-URL wird aus STT_API_URL abgeleitet. Zeitbudget:
`poll_timeout` (Default 180 s). Bei Stoerung/Timeout wird ehrlich "" geliefert.

Zuerst auf dev testen (echtes Diktat), dann promoten.

### STT-Qualitaet steuern (Fachvokabular)

Whisper laesst sich mit einem Vokabular-Hinweis vorspannen – das behebt typische
Fehler wie "Saeure" statt "Server/Services":

    STT_PROMPT   = Diktat zu einem HERMES-Projekt ... Server, Services, Kunden, ISDS, ...
    STT_LANGUAGE = de        # leer lassen, falls der Anbieter 'language' als
                             # UEBERSETZUNGS-Ziel deutet (Infomaniak-Doku!)

Beide sind optional; Defaults stehen in app/config.py. Das Warte-Budget des
asynchronen Pfads liegt bei 100 s – bewusst UNTER dem Gunicorn-Worker-Timeout (120 s).
