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
- `--graceful-timeout 30`, `--timeout 300` (LLM-Aufrufe; nginx proxy_read_timeout ebenso), `--capture-output`
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

## Pseudonymisierungsschicht (alle KI-Aufrufe)

Seit V0.8.0 besitzt HERMES PIA **keinen eigenen Anbieterschlüssel mehr**. Sämtliche
LLM- *und* Embedding-Aufrufe laufen über den lokalen Pseudonymisierungsdienst; der
Schlüssel liegt dort. Solange die Anwendung einen eigenen Schlüssel hätte, wäre das
Umgehen der Schicht nur verboten, nicht unmöglich – und genau darauf kommt es bei
Verwaltungskunden an.

### Konfiguration (`.env`)

```
PSEUDO_BASIS_URL=http://127.0.0.1:8040
PSEUDO_ANWENDUNG=hermes-pia
PSEUDO_MANDANT=standard
```

Port je Stufe: `8040` develop · `8041` test · `8042` integration · `8043` main.

**`PSEUDO_BASIS_URL` leer = kein LLM.** Die Anwendung arbeitet dann rein
deterministisch weiter (wie früher ohne Anbieterschlüssel). Es gibt bewusst
keinen Ausweichweg direkt zum Anbieter: lieber keine Auswertung als eine
ungeschützte. Ein geratener Standard-Port wäre die schlechtere Vorgabe – er liefe
bei fehlender `.env` stillschweigend ins Leere.

`ANTHROPIC_API_KEY` und `VOYAGE_API_KEY` gehören **entfernt**. Stehen sie noch in
der `.env`, richten sie keinen Schaden mehr an (nichts liest sie), sind aber ein
unnötiges Geheimnis auf der Platte.

### Was der Betrieb sehen muss

| Lage | Anzeige für den Nutzer | HTTP |
|---|---|---|
| Fundstelle unsicher | Rückfrage mit Fundstellen und zwei Schaltflächen | 409 |
| Rückersetzung unsicher | «Antwort zurückgehalten», **kein Text übernommen** | 502 |
| Dienst nicht erreichbar | «Pseudonymisierung nicht erreichbar» | 503 |
| Mandant/Anwendung/Schlüssel falsch | «nicht einsatzbereit» (Konfigurationsfehler) | 500 |

**502 ist eine Schutzabschaltung, kein Netzwerkfehler.** Nicht stillschweigend
wiederholen – der Dienst liefert lieber einen Fehler aus als einen Text, in dem
ein Platzhalter falsch aufgelöst wurde.

Fällt der Dienst aus, steht das Interview. Das ist gewollt. Beim Wiederanfahren
zuerst den Dienst starten, dann HERMES PIA.

### Seed-Korpus neu laden

```
python scripts/ingest_seed_corpus.py "<verzeichnis>" --ersetzen
```

Der Korpus speichert den Chunk-**Text** im Klartext; nur die Einbettung läuft durch
die Schicht. Ein im Text verbliebener Personenname landet also in der Datenbank und
kann über die RAG-Suche in ein neues Projektdokument gelangen. Das Skript prüft
deshalb vorher auf Restmuster (abgekürzter Vorname + Nachname, z.B. `Chr. Dürr`)
und **bricht ab**. Die Prüfung ist bewusst übervorsichtig und meldet auch
Anhang-Aufzählungen mit; sie sperrt nur, sie ersetzt nichts. `--trotzdem` übergeht
sie bewusst und sollte begründet sein.

## Rechtsquellen-Recherche (lexfind, Bund + 26 Kantone)

Seit V0.8.9 sucht die Rechtsgrundlagenanalyse die Fundstellen **live** über
`www.lexfind.ch` – Bund *und* Kantone, mit echter Systematik-Nummer, Aktiv-Status
und offiziellem Quell-Link. Der mitgelieferte Offline-SR-Index bleibt als Netz:
Was live keinen Treffer hat (oder wenn lexfind ausfällt), wird dort nachgeschlagen.
**Geraten wird nie** – ohne Treffer bleibt die Fundstelle leer.

### Konfiguration (`.env`)

```
RECHERCHE_LIVE=1      # 0 = nur Offline-Index (Bundesrecht, ohne Aktualität)
```

### Erreichbarkeit prüfen (WICHTIG)

Beide Quellen sind vom Infomaniak-Host erreichbar (geprüft 2026-07-25: lexfind
HTTP 200). Die frühere Annahme, Fedlex sei dort blockiert, war eine Fehldiagnose –
tatsächlich war die SPARQL-Abfrage kaputt (nackte Regex-Alternation liefert 0
Zeilen). Prüfen lässt sich die Erreichbarkeit je Host so:

```bash
curl -s -o /dev/null -w 'lexfind: HTTP %{http_code}\n' -m 15 \
  https://www.lexfind.ch/api/frontend/v1/de/categories
```

`HTTP 200` → live nutzbar. Alles andere (000/403/timeout) → `RECHERCHE_LIVE=0`
setzen; die Analyse läuft dann unverändert mit dem Offline-Index weiter.

### Eigenheiten der API (gemessen 2026-07-25)

- Braucht Browser-Kopfzeilen (`User-Agent`, `Referer`), sonst HTTP 400.
- `entity_filter` darf **nicht leer** sein und nimmt **genau eine** Sammlung –
  Bund und Kanton werden deshalb getrennt abgefragt und zusammengeführt.
- Die Treffer stehen in `texts_of_law_with_matches` (nicht in `results`).

### Vorbehalt

Undokumentierte Frontend-API ohne zugesicherte Stabilität oder Nutzungsbedingungen.
Für den Produktivbetrieb ist ein sanktionierter Zugang bei lexfind/Sitrox zu
klären. Ändert sie sich, fällt die Analyse automatisch auf den Offline-Index
zurück – sie bricht nicht.

**Datenschutz:** Es verlassen nur **Rechtsbegriffe** (aus Gesetzesnamen abgeleitet)
den Host, nie Projekttext. Die Suchbegriffe bestimmt die Anwendung, nicht das
Sprachmodell – ein modellgesteuerter Werkzeugaufruf könnte Projektinhalte an den
externen Dienst tragen und würde die Pseudonymisierungsschicht umgehen.

## Pseudonymisierung vorübergehend abschalten (nur Entwicklung)

Wird an der **Fachlichkeit** gearbeitet (PIA-Inhalte, Prompts, Dokumentaufbau),
steht die Schicht im Weg: jeder unsichere Name unterbricht mit einer Rückfrage.
Für diesen Fall gibt es den **Direktmodus** – die Aufrufe gehen dann *ohne*
Pseudonymisierung an den Anbieter.

```
PSEUDO_BASIS_URL=
PSEUDO_UMGEHEN=1
ANTHROPIC_API_KEY=sk-...
```

**Beide** Bedingungen müssen erfüllt sein: `PSEUDO_UMGEHEN=1` *und* ein Schlüssel.
Ein vergessener Schlüssel in der `.env` allein schaltet die Schicht **nicht** ab –
das wäre genau der Unfall, den es zu verhindern gilt. Ist `PSEUDO_BASIS_URL`
gesetzt, gewinnt immer die Schicht, auch mit Schlüssel.

Sichtbar ist der Zustand an drei Stellen: ein nicht wegklickbares Banner im
Interview, `/health` meldet `"modus": "direkt (AUS)"`, und beim Start steht eine
Warnung im Log.

### Zurückschalten

```
PSEUDO_UMGEHEN=0
PSEUDO_BASIS_URL=http://127.0.0.1:8040
```

Danach die Stufe **neu starten** – der Prozess friert die Umgebungsvariablen beim
Start ein.

⚠️ **Nur mit Testdaten.** Im Direktmodus verlassen Namen und Fallbezüge den Host
ungeschützt. Auf test (Kundenumgebung), integration und Produktion hat er nichts
zu suchen.

## Baseline der Invarianten-Prüfung

Ausgangsmessung, gegen die spätere Verbesserungen gemessen werden
(Invarianten-Katalog Abschnitt 13). Läuft **nur über die in HERMES PIA erzeugten
PIAs** – dort liegen die strukturierten Daten vor, also greifen beide Prüfebenen.
Der Altbestand bleibt bewusst draussen: er ist überwiegend HERMES 5.1, eine
Messung darauf zeigt die Methodengeneration statt der Regelgüte.

Auf dem Server, je Stufe:

```bash
cd ~/methodos-dev && ../venv/bin/python scripts/baseline_invarianten.py
```

Mit CSV für den Vorher/Nachher-Vergleich:

```bash
cd ~/methodos-dev && ../venv/bin/python scripts/baseline_invarianten.py --csv ~/baseline-$(date +%F).csv
```

Die Auswertung nennt je Regel, wie oft sie ausgelöst hat und in wie vielen PIAs.
**Regeln, die nie oder immer auslösen, sind Kandidaten zur Überarbeitung** – die
einen tragen nichts bei, die anderen sind zu scharf oder zeigen einen echten
Systemfehler.

## Testlauf (nur Entwicklungsstufe)

Ein Vorhaben ohne Rückfragen durchspielen: Ausgangslage beschreiben, HERMES PIA
erzeugt Auftrag, Präsentation, Projektplan, Rechtsgrundlagenanalyse,
Schutzbedarfsanalyse sowie Checkliste und Liste Projektentscheide — und folgt
dabei immer dem eigenen Vorschlag.

**NICHT in die `.env` eintragen.** `~/methodos/.env` (`SHARED_ENV`) wird von
JEDER Stufe geladen — prod, test, int und dev. Ein `TESTLAUF=1` dort schaltet
den Testlauf auf der Kundenumgebung und in der Produktion gleich mit ein.

Die Einstellung steht deshalb im `dev`-Zweig von `hp_config` in
`deploy/hermes_ctl.sh` (`HP_EXTRA_ENV="TESTLAUF=1"`), also dort, wo die Stufe
schon bekannt ist. Sie wird NACH der geteilten Datei gesetzt und kann sie
übersteuern; `hp_config` setzt sie zu Beginn jedes Aufrufs zurück, damit keine
Stufe erbt, was für eine andere gedacht war. Zu tun ist also nichts ausser
deployen.

**Warum nur dev.** Der Testlauf erzeugt eine freigegebene Checkliste und einen
erreichten Meilenstein, ohne dass ein Mensch geurteilt hat. Auf einer
Kundenstufe wäre das ein Weg, Nachweise zu erzeugen, die keine sind. Ist der
Schalter aus, gibt es den Dienst gar nicht — die Routen antworten mit 404, und
das Formular erscheint nicht.

Jede vom Testlauf gesetzte Bewertung trägt den Vermerk «TESTLAUF: ohne
menschliches Urteil automatisch bestätigt.» in der Erläuterung; er steht danach
im erzeugten Word-Dokument.

**Was er zeigt und was nicht.** Frage und Antwort kommen aus derselben Quelle.
Ein grüner Lauf sagt «die Kette hält» — er sagt nichts über die Qualität des
Inhalts. Das Wertvollste am Lauf ist sein Protokoll: dort steht, welcher Schritt
gescheitert wäre und ob der Download der Projektleitung wegen eines
Muss-Befunds verweigert würde.


## Worker und gleichzeitiges Schreiben

| Stufe | Worker | Warum |
|-------|--------|-------|
| prod  | 2 | unveraendert |
| test  | 3 | unveraendert |
| int   | 1 | unveraendert |
| dev   | **10** | dort wird gearbeitet, dort darf es ruckeln |

**Warum mehr Worker als Kerne.** Der Host hat vier Kerne. Fuer Rechenarbeit
waeren zehn Worker unsinnig — diese Anwendung wartet aber fast nur: ein Aufruf
ans Sprachmodell darf 90 s dauern, und in dieser Zeit tut der Worker nichts
ausser aufs Netz zu horchen. Mit einem einzigen Worker legt genau das die ganze
Stufe lahm; jeder Reload landet in der Warteschlange und sieht aus wie ein
Absturz.

**Was dabei zu beobachten ist.** Die Grenze ist der Speicher, nicht die
Rechenzeit: jeder Worker traegt die volle Anwendung. Auf dem geteilten Host
laufen vier Stufen — nimmt dev zu viel, trifft der OOM-Killer irgendeinen
Prozess, im schlimmsten Fall die Produktion. Nach dem Deploy einmal messen:

```bash
ps -o rss=,cmd= -C gunicorn | awk '{s+=$1} END {print s/1024 " MB gesamt"}'
free -m
```

Wird es eng, ist die naechste Stufe nicht «weniger Worker», sondern
`--threads`: zehn Threads in zwei Workern geben dieselbe Gleichzeitigkeit fuer
zwei Prozess-Abbilder statt zehn.

**Was mit den Workern zwingend zusammengehoert.** SQLite bringt von Haus aus
`journal_mode=delete` mit (ein Schreiber sperrt ALLE Leser) und wartet nur 5 s
auf eine Sperre. Bei einem Worker faellt das nie auf, weil gleichzeitiges
Schreiben unmoeglich ist. Ab zwei Workern ist es der Normalfall — und dann
bricht ein Interview mit «database is locked» ab. `app/shared/database.py`
stellt deshalb **WAL** und ein Wartelimit von **30 s** ein. Wer die Worker
erhoeht, ohne das zu haben, tauscht Haenger gegen Datenverlust.
