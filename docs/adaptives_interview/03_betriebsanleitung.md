# Adaptives Interview – Betriebsanleitung

## Schalter und Konfiguration

| Variable | Wirkung | Standard |
|---|---|---|
| `INTERVIEW_ADAPTIV` | `1`: neue Aufträge starten im adaptiven Interview. `0`: neue Aufträge starten im bisherigen Ablauf (Rückfallweg ohne Deploy). Bestehende Sessions behalten ihren Modus in beiden Fällen. | `1` |
| `PSEUDO_BASIS_URL` | Pseudonymisierungsdienst. **Ohne ihn gibt es keine Embeddings und damit kein RAG.** Das Interview läuft dann ohne Vergleichsprojekte weiter und zeigt «Vergleichsprojekte nicht verfügbar». | leer |
| `VOYAGE_MODEL` | Embedding-Modell. Treffer eines anderen Modells werden nicht verglichen (AT12). | `voyage-3` |
| LLM-Konfiguration | unverändert (bestehende Variablen); das Laufzeitmodell ist konfigurierbar und nicht an das Entwicklungsmodell gebunden. | – |

Versionierte Fachdaten (Änderungen = neue Version + Commit + regulärer Deploy-Weg):

- `methods/hermes_pia/vorlagenzuordnung.yaml` – Vorlage ↔ Daten (1.0.0)
- `methods/hermes_pia/abschlussprofil.yaml` – wann «bereit» (1.1.0)
- `methods/hermes_pia/rag_uebertragung.yaml` – Übertragungsregeln R1–R5, Sperrmuster
- `app/domains/interview/adaptiv/prompt_texte/*.md` – Prompts mit Version im Kopf

## Datenbank

Die Migration ist **additiv** und läuft beim Start (`factory._migrate_db`): neue Spalten an
`interview_session` (`modus`, `revision`, `naechste_aktion_json`, `ausstehend_json`,
`pia_status`, `rag_stand_json`, `answers_vor_umstellung_json`) und `corpus_chunks`
(`dokument_hash`, `chunk_nr`, `methodenversion`, `methodenversion_herkunft`,
`korpus_version`), neue Tabellen `pia_nachricht`, `pia_aussage`, `pia_konflikt`,
`pia_rag_thema`, `pia_rueckmeldung`. Nichts wird gelöscht oder umbenannt.

**Vor dem ersten Start auf einer Stufe:** Datenbank sichern. Auf `test` (Kunde) und höher
nur mit ausdrücklicher Freigabe – die Migration ist eine produktive Schemaänderung.
Stufenfolge wie immer: develop → test → integration → main.

## RAG in Betrieb nehmen (offen)

1. Pseudonymisierungsdienst bereitstellen und `PSEUDO_BASIS_URL` setzen (dev zuerst).
2. Prüfen, ob die Stufen-Datenbank bereits Chunks hat; sonst Korpus laden:
   `python scripts/ingest_seed_corpus.py "<verzeichnis>"` – mit Klarnamen-Sperre,
   Duplikaterkennung über den Dokument-Hash und den Nachweisfeldern Methodenversion
   (aus der Korpusdeklaration, ausdrücklich nicht je Dokument geprüft) und Korpusversion.
3. Nachweis: ein Interview auf dev führen; in «Für den PIA erkannt» müssen Themen aus
   Vergleichsprojekten mit «Quelle ansehen» erscheinen.

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
