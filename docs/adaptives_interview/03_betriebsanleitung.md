# Adaptives Interview – Betriebsanleitung

## Datenwege zu externen Diensten

HERMES PIA übermittelt Text an drei Arten externer Dienste. Welcher Weg gilt, steht in
`/health` unter `datenwege` und als Banner in der Oberfläche – so, wie er tatsächlich ist.

| Weg | Was geht hinaus | Modi |
|---|---|---|
| Sprachmodell (`llm`) | Gesprächsbeiträge, Stand, RAG-Passagen in Prompts | schutzschicht · direkt · aus |
| Embeddings (`embeddings`) | beim Indexieren der Korpustext, bei der Suche die Anfrage aus dem Gespräch | schutzschicht · direkt · aus |
| Spracherkennung (`stt`) | Audio des Diktats | direkt · aus – **nicht über die Schutzschicht geführt (offener Punkt)** |

**Schutzschicht – Integrationsstelle für das spätere Standardwerkzeug.** Je Dienst eine
anbieterkompatible Basis-URL: `SCHUTZSCHICHT_LLM_URL` (Anthropic-kompatibel, `/v1/messages`)
und `SCHUTZSCHICHT_EMBEDDING_URL` (Voyage-kompatibel, `/v1/embeddings`). Ohne Einzelangabe
werden beide aus `PSEUDO_BASIS_URL` abgeleitet (`<basis>/anthropic`, `<basis>/voyage`).
Mitgesendet werden die Kontext-Kopfzeilen `X-Pseudo-Anwendung`, `-Mandant`, `-Projekt`.
Welches Werkzeug dahinter steht, ist bewusst nicht festgelegt.

**Direkt – nur ausdrücklich.** Sprachmodell: `PSEUDO_UMGEHEN=1` + `ANTHROPIC_API_KEY`.
Embeddings: `EMBEDDING_DIREKT=1` + `VOYAGE_API_KEY`. Ein Schlüssel allein schaltet nichts
um; ein Schalter ohne Schlüssel ergibt «aus» mit Grund.

**Keine Umgehung.** Ist eine Schutzschicht konfiguriert, gilt sie für alle Wege; die
Direktschalter sind dann wirkungslos (Warnung im Log und in `/health`). Fällt die
Schutzschicht aus, gibt es einen Fehler – nie einen Wechsel zum Anbieter.

**RAG im Direktmodus** verwendet nur Korpusteile mit `extern_freigegeben` – der Bestand
(ohne dieses Kennzeichen) bleibt erhalten und unberührt, wird in diesem Modus aber nicht
durchsucht. Grund: gefundene Passagen gehen in die Prompts an das Sprachmodell.

**Daten im Direktmodus (Freigabe 15.10.2026):** nur dev; nur synthetische, geeignet
öffentliche oder bereinigte und ausdrücklich zur externen Verarbeitung freigegebene Daten –
für zu indexierende Dokumente, Suchanfragen und mitgesendeten Gesprächskontext. Keine
vertraulichen oder personenbezogenen Projektunterlagen.

### Schlüssel

Schlüssel nie ins Repository und nicht in die geteilte `~/methodos/.env` (die laden alle
Stufen). Stufeneigene Schlüssel gehören in `~/.hermes-env/<stufe>.env` auf dem Server
(z.B. `~/.hermes-env/dev.env` mit `VOYAGE_API_KEY=…`, Rechte `600`). `hermes_ctl.sh` lädt
diese Datei nur für ihre Stufe und nach der geteilten Datei; `git reset` berührt sie nie.
Nach jeder Änderung die Stufe neu starten (`bash ~/bin/hermes/hermes_ctl.sh start dev`) –
der laufende Prozess liest Umgebungsvariablen nur beim Start.

**Befund (15.10.2026, nur Variablennamen gelesen):** `PSEUDO_UMGEHEN` steht in der
geteilten `~/methodos/.env`, die alle Stufen laden. Ob der Direktmodus auf test, int und prod
wirkt, hängt vom Wert ab. Empfehlung: `PSEUDO_UMGEHEN=1` aus der geteilten Datei entfernen
und nur in `~/.hermes-env/dev.env` setzen.

## Schalter

| Variable | Wirkung | Standard |
|---|---|---|
| `INTERVIEW_ADAPTIV` | `1`: neue Aufträge starten im adaptiven Interview. `0`: neue Aufträge starten im bisherigen Ablauf. Setzt **weder** bestehende adaptive Sessions **noch** das Schema zurück – dafür gibt es den Rückweg unten. | `1` |
| `EMBEDDING_DIREKT` | Embeddings direkt an Voyage (nur mit `VOYAGE_API_KEY`). In `hermes_ctl.sh` nur für dev gesetzt. | `0` |
| `VOYAGE_MODEL` | Embedding-Modell. Treffer eines anderen Modells werden nicht verglichen (AT12). | `voyage-3` |
| LLM-Konfiguration | unverändert; das Laufzeitmodell ist konfigurierbar und nicht an das Entwicklungsmodell gebunden. | – |

Versionierte Fachdaten (Änderungen = neue Version + Commit + regulärer Deploy-Weg):

- `methods/hermes_pia/vorlagenzuordnung.yaml` – Vorlage ↔ Daten (1.0.0)
- `methods/hermes_pia/abschlussprofil.yaml` – wann «bereit» (1.1.0)
- `methods/hermes_pia/rag_uebertragung.yaml` – Übertragungsregeln R1–R5, Sperrmuster
- `app/domains/interview/adaptiv/prompt_texte/*.md` – Prompts mit Version im Kopf
  (`aussagen-1.1`: Ziele sachgerecht kategorisieren, keine Ziele zur Kategorienbesetzung)

## Datenbank, Sicherung und Rückweg

Die Migration ist **additiv** und läuft beim Start (`factory._migrate_db`): neue Spalten an
`interview_session` (`modus`, `revision`, `naechste_aktion_json`, `ausstehend_json`,
`pia_status`, `rag_stand_json`, `answers_vor_umstellung_json`) und `corpus_chunks`
(`extern_freigegeben`, `dokument_hash`, `chunk_nr`, `methodenversion`,
`methodenversion_herkunft`, `korpus_version`), neue Tabellen `pia_nachricht`, `pia_aussage`,
`pia_konflikt`, `pia_rag_thema`, `pia_rueckmeldung`. Nichts wird gelöscht oder umbenannt.

**Sicherung – automatisch vor jedem Deploy.** `hermes_ctl.sh deploy` sichert die
Stufen-Datenbank mit der SQLite-Backup-API (auch im WAL-Betrieb konsistent) **bevor** der
Neustart die Migration ausführt: `<db>.vor-deploy-<commit>-<zeit>`. Schlägt die Sicherung
fehl, bricht der Deploy ab. Behalten werden die letzten 5 Sicherungen. Von Hand:
`bash ~/bin/hermes/hermes_ctl.sh sichern dev <anlass>`.

**Rückweg (stützt sich nicht auf `INTERVIEW_ADAPTIV`).**

1. Code zurück: den Merge auf `develop` rückgängig machen
   (`git revert -m 1 <merge-commit>`, push) – Jenkins deployt den vorherigen Stand und legt
   dabei eine Sicherung des aktuellen Zustands an.
2. Daten zurück: `bash ~/bin/hermes/hermes_ctl.sh wiederherstellen dev <sicherung>` mit der
   Sicherung **vor** dem Deploy des adaptiven Interviews. Der aktuelle Stand wird dabei nicht
   gelöscht, sondern als `<db>.vor-rueckweg-<zeit>` abgelegt; die Stufe startet neu.
3. Folge: Was nach dem Deploy auf dev erfasst wurde, ist im wiederhergestellten Stand nicht
   enthalten (liegt aber in der abgelegten Datei).

Nicht lokal durchgespielt: `wiederherstellen` (braucht Gunicorn). `sichern` ist lokal mit
einer Wegwerf-Datenbank geprüft (Inhalt, Aufbewahrung).

Freigabe: dev (15.10.2026). **Nicht** für test, integration oder main.

## Korpus: Bestand prüfen, synthetisch ergänzen

**Bestand – nur lesend:** `python scripts/korpus_bestand.py ~/methodos-dev/data/methodos-dev.db
--modell voyage-3` (öffnet schreibgeschützt, keine Migration, kein Netz) oder als Betreiber
`/admin/korpus/bestand`. Ausgabe je Bereich: Dokumente, Chunks, Modelle und Vektorlängen,
Korpusversionen und Zeitraum, Methodenversion, extern freigegebene Chunks, Kompatibilität
mit dem vorgesehenen Modell. Bestehende Bestände nicht löschen und nicht neu laden.

**Bestand am 15.10.2026, 17:20:** dev, test, int je 0 Chunks; prod ohne Korpustabelle.

**Synthetischer Korpus – getrennt vom Bestand:** `python scripts/ingest_synthetischer_korpus.py
--trocken`, dann `--ausfuehren`. Zehn erfundene Vorhaben (`tools/korpus_synthetisch.py`),
eigene Korpusversion `synthetisch-<Datum>`, Kennzeichen «extern freigegeben»,
Methodenversion «HERMES 5.1» mit Herkunft «synthetisch erstellt». Geschätzt rund 1'500
Tokens. Dubletten werden übersprungen, Bestand bleibt unverändert.

**Quellordner der pseudonymisierten Aufträge** (lokal, ausserhalb des Repositorys): 197
Texte; die Klarnamen-Sperre meldet in 36 Dateien 78 Verdachtsstellen, 12 Dateien sind
praktisch leer. Für den Direktmodus ungeeignet, solange nicht bereinigt und ausdrücklich zur
externen Verarbeitung freigegeben. Die Zuordnungsdatei Original → Pseudonym im selben Ordner
gehört nie auf einen Server und nie ins Repository.

## Echter Nachweis auf dev (Budget USD 10)

```
python tools/dev_echtlauf.py --ziel ~/nachweis-dev
python tools/dev_echtlauf.py --ziel ~/nachweis-dev --ausfuehren \
    --preise in=<USD/Mio>,out=<USD/Mio>,emb=<USD/Mio> --budget-usd 10
```

Auf dem Server in der dev-Umgebung ausführen (venv aktiv, Umgebung wie die Stufe geladen:
geteilte `.env`, dann `~/.hermes-env/dev.env`, `DATABASE_URL` auf die dev-Datenbank). Ohne
`--ausfuehren` nur Prüfung der Voraussetzungen. Preise je Million Tokens gibt der Betreiber an
(aktuelle Preisliste); vor jedem Schritt prüft der Lauf, ob Verbrauch plus Reserve das Budget
überschreiten würde, und endet dann geordnet. Ergebnis: zwei Word-Dateien, Protokolle,
`bericht.json` mit Verbrauch; die Sessions liegen in der Organisation
«Synthetik-Nachweis (erfunden)» und sind in der Oberfläche ansehbar.

## Bestehende Sessions umstellen

- In der bisherigen Oberfläche: «Auf das adaptive Interview umstellen». Die bisherigen
  Dokumentdaten werden gesichert; Angaben erscheinen als «aus früherer Erfassung – noch zu
  bestätigen». Fertigstellen ist erst möglich, wenn sie bestätigt sind.
- Rückweg in der adaptiven Oberfläche: «Zurück zum bisherigen Ablauf» stellt den gesicherten
  Stand wieder her (was seither erfasst wurde, bleibt als Verlauf, gilt aber nicht mehr).

## Aufbewahrung und Löschung

- Gespräch, Aussagen, Widersprüche, RAG-Themen samt gespeicherter Fundstellen-Auszüge und
  Rückmeldungen gehören zum Auftrag und werden **mit ihm gelöscht**.
- Rückmeldungen enthalten nur minimalen Kontext (Frage, Aktion, Versionen) und sind erst
  nach ausdrücklicher Freigabe (`evaluation_interview.py freigeben`) Auswertungsdaten.
- Auswertungen schreiben nur in den angegebenen Ordner; reale Inhalte dort nicht ins
  Repository übernehmen.

## Auswertung und Verbesserung (nur auf ausdrücklichen Anstoss)

```
python tools/evaluation_interview.py freigeben --db <url> --ids 3,7,12
python tools/evaluation_interview.py schwaechen --db <url> --aus <ordner>
python tools/evaluation_interview.py vergleich [--kandidat <ordner>] --aus <ordner>
```

Ein Kandidat ist ein Ordner mit Ersatzdateien (`abschlussprofil.yaml`,
`rag_uebertragung.yaml`, `prompt_texte/*.md`). Urteil: «abgelehnt», sobald eine
Schutzkennzahl schlechter wird; sonst «besser» oder «gleichwertig». Übernahme nur von Hand:
neue Version, Commit, Review, Tests, Deploy. Rückweg: der vorherige Commit.

**Rubrik für die Gesprächsqualität** (für Live-Läufe und fachliche Abnahme; offline nur die
messbaren Anteile):

| Dimension | Frage | Offline gemessen |
|---|---|---|
| Relevanz | Schliesst die Frage eine bestehende Lücke? | Kriterien offen, Fragen bis «bereit» |
| Kontextnutzung | Nutzt die Frage, was schon gesagt wurde? | wiederholte Fragen |
| Neutralität | Kein Suggerieren, keine vorweggenommene Lösung | – (fachlich) |
| Phasenfokus | Bleibt es bei der Initialisierung? | unbestätigte Angaben im Dokument = 0 |
| RAG-Übertragung | Thema statt Befund, Versionsgrenze beachtet | «nicht übernehmen» gefragt = 0, Themen genutzt |
| Aktualität der Anzeige | Stimmt die Anzeige nach jedem Schritt? | UI-Nachweis (Browser) |
| Dokumentqualität | Vorlagentreu, ohne Muss-Befund | Muss-Befunde im Export |

## Nachweise reproduzieren

```
python -X utf8 -m pytest -q
python -X utf8 tools/ui_nachweis_adaptiv.py docs/adaptives_interview/nachweis
python -X utf8 tools/fall_durchspielen.py F-02 out.docx --json out.json --fertigstellen
python -X utf8 tools/evaluation_interview.py vergleich --aus <ordner>
```

Der UI-Nachweis startet Server und kopflosen Chrome im selben Prozess (Chrome unter
`C:\Program Files\Google\Chrome\Application\chrome.exe`, Paket `websocket-client`).
