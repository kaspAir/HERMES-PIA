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
