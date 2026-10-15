# Adaptives Interview – Abschlussbericht

Auftrag: `HERMES-PIA_Entwicklerprompt_v1.0.md`, Referenz `PIA_HERMESPIA.docx`
(SHA-256 `2b02548e…700e9d`, unverändert). Branch `feature/pia-adaptives-interview`.
Entscheide des Auftraggebers vom 15.10.2026 eingearbeitet (Direktzugang Embeddings auf dev,
Push/Merge/dev, D-030).

Kennzeichnung in diesem Bericht:
**[I]** implementiert · **[T]** automatisiert geprüft · **[D]** auf dev tatsächlich
nachgewiesen · **[O]** offen

Stand dieses Berichts: **auf dev ist noch nichts nachgewiesen** – siehe Abschnitt 4.

## 1. Adaptives Interview und PIA

- **[I][T]** Gemeinsamer, versionierter Projektzustand (Aussagen mit Herkunft, Art,
  Bestätigung, Bezug, Entscheid-Charakter; Widersprüche; RAG-Themen; Rückmeldungen),
  Revision je Session, Idempotenz je Anfrage.
- **[I][T]** Adaptive Gesprächsführung: Modell schlägt Operationen vor, versionierte Verträge
  prüfen; Planer mit Prioritäten, Wiederholungsschutz, gespeicherte nächste Aktion.
- **[I][T]** Bestehender RAG als Themenquelle: Modellkompatibilität, Fundstellen mit
  Chunk-ID/Hash/Methoden- und Korpusversion, Übertragungsregeln R1–R5, Sperrmuster, ein
  Beleg je Projekt, Dubletten über den Dokument-Hash.
- **[I][T]** Live-Anzeige «Für den PIA erkannt» ohne Reload, Korrekturen an der Anzeige,
  Revisionsschutz; im echten Chrome 22 von 22 Prüfungen (lokal, Drehbuch-Modell).
- **[I][T]** Abschlussprüfung (Profil 1.1.0 + verbindliche Ausgabeprüfung), «Fertigstellen»
  nur für den geprüften Stand, vorlagentreuer Export ohne Modellaufruf, Kap. 5 über neun
  Monate, berechnete Vorschläge für Terminplan und Monatsverteilung.
- **[I][T]** Bestandsschutz: Umstellung mit Sicherung, Rückfall, Abweisung alter Schreibwege;
  Löschung samt Gesprächsdaten. Pseudonymisierungs-Entscheidungsweg im adaptiven Interview.
- **[I][T]** Kontrollierte Verbesserung (versionierte Rückmeldungen, Freigabe, Kandidaten,
  Baseline-Vergleich).

## 2. Umsetzung der Entscheide vom 15.10.2026

**Datenwege (RAG ohne Pseudonymisierungsdienst):**

- **[I][T]** Sprachmodell und Embeddings haben je einen eigenen Weg: Schutzschicht,
  ausdrücklich direkt oder aus (`app/domains/llm/datenweg.py`). Embeddings hängen nicht mehr
  an der Pseudonymisierung.
- **[I][T]** Integrationsstelle für das spätere Standardwerkzeug: je Dienst eine
  anbieterkompatible Basis-URL (`SCHUTZSCHICHT_LLM_URL`, `SCHUTZSCHICHT_EMBEDDING_URL`).
  Kein Werkzeug ausgewählt oder angebunden, kein eigener Dienst entwickelt.
- **[I][T]** Direkt nur ausdrücklich (Schalter **und** Schlüssel); Schutzschicht gewinnt
  immer; ihr Ausfall ist ein Fehler, nie ein Weg zum Anbieter.
- **[I][T]** Banner und `/health` zeigen den tatsächlichen Weg je Übermittlung, ohne
  Schlüssel.
- **[I][T]** Im Direktmodus durchsucht das RAG nur Korpusteile mit «extern freigegeben»;
  der Bestand bleibt unberührt.
- **[I][T]** dev: `EMBEDDING_DIREKT=1` in der Stufenkonfiguration; Schlüssel aus
  `~/.hermes-env/dev.env` (serverseitig, ausserhalb des Repositorys).
- **[O]** Spracherkennung läuft nicht über die Schutzschicht.

**Korpus:**

- **[I][T]** Bestandsaufnahme nur lesend (`scripts/korpus_bestand.py`,
  `/admin/korpus/bestand`): Dokumente, Chunks, Modelle/Vektorlängen, Korpusstand,
  Kompatibilität.
- **[I][T]** Synthetischer Korpus (zehn erfundene Vorhaben) mit eigener Korpusversion und
  Freigabe-Kennzeichen; Ladeskript mit Trockenlauf und Token-Grenze.
- **[O] Bestand auf den Stufen nicht geprüft.** Ein SSH-Zugang zum Server wurde mir in
  dieser Sitzung verwehrt (der Host trägt auch die Produktion). Ich nehme über den Bestand
  nichts an.
- **Befund Quellordner** (lokal, ausserhalb des Repositorys): 197 pseudonymisierte Texte
  früherer Aufträge; in 36 Dateien meldet die Klarnamen-Sperre 78 Verdachtsstellen, 12
  Dateien sind praktisch leer. Diese Daten sind für den Direktmodus **nicht** freigegeben und
  wurden nicht übermittelt.

**Sicherung und Rückweg:**

- **[I]** Automatische, konsistente Sicherung der Stufen-Datenbank vor jedem Deploy; ohne
  Sicherung kein Neustart (also keine Migration). **[T]** lokal geprüft (Inhalt,
  Aufbewahrung von 5 Ständen).
- **[I]** Rückweg: Merge auf `develop` rückgängig machen **und** `hermes_ctl.sh
  wiederherstellen dev <sicherung>`; stützt sich nicht auf `INTERVIEW_ADAPTIV`.
  **[O]** `wiederherstellen` nicht lokal durchgespielt (braucht Gunicorn).

**D-030:**

- **[I][T]** Mindestbesetzung beider Zielkategorien ist ein Hinweis. Begründung korrigiert:
  «Die Vorlage sieht Zielkategorien vor, verlangt aber nicht ausdrücklich, dass beide
  Kategorien zwingend vertreten sein müssen.» Die Kategorie je Ziel bleibt Pflicht (D-031,
  K-ZI-2); D-030 prüft nur die Mindestbesetzung. Prompt `aussagen-1.1`: sachgerecht
  kategorisieren, keine Ziele zur Kategorienbesetzung erfinden.

## 3. Automatisierte Tests

**1149 bestanden, 14 übersprungen** (Ausgangslage 972 / 1 Testfehler / 14). Die 14
übersprungenen sind die fachlichen Ende-zu-Ende-Fälle mit Audioaufnahmen
(`tests/e2e/test_fachlich_e2e.py`, 0001–0014), deren Aufnahmen nicht im Repository liegen;
sie sind für diese Änderung nicht gelaufen. Zuordnung AT01–AT26:
`04_anforderungs_test_matrix.md`. Geänderte Erwartungen sind dort mit Grund aufgeführt.

## 4. Auf dev nachgewiesen

**Noch nichts.** Vorbereitet sind:

1. `~/.hermes-env/dev.env` mit `VOYAGE_API_KEY` anlegen (nur serverseitig), dev neu starten.
2. `python scripts/korpus_bestand.py ~/methodos-dev/data/methodos-dev.db` – Bestand dokumentieren.
3. `python scripts/ingest_synthetischer_korpus.py --ausfuehren` – synthetischer Korpus
   (≈ 1'500 Tokens).
4. `python tools/dev_echtlauf.py --ziel ~/nachweis-dev --ausfuehren --preise … --budget-usd 10`
   – vollständiger Fall und Korrektur-/Widerspruchsfall mit echtem Modell und echtem RAG,
   zwei Word-Dateien, Protokolle, Verbrauch.
5. Sichtprüfung in der Oberfläche (Organisation «Synthetik-Nachweis (erfunden)»): Quellen,
   Anzeige «Für den PIA erkannt».

## 5. Offen

- Bestand auf den Stufen, echter RAG-Abruf, echter Interviewdurchlauf, Word-Dateien aus dem
  echten Lauf (Abschnitt 4).
- Herkunft des direkten Sprachmodellwegs auf dev (vermutlich geteilte `.env` → dann auch
  test/int/prod), siehe Betriebsanleitung.
- Render-Prüfung in Word (kein Word/LibreOffice auf dem Entwicklungsrechner).
- Fachliche Abnahme: Abschlussprofil, Übertragungsregeln, Terminlage, Prompts.
- Spracherkennung über eine Schutzschicht.

Diese Entwicklungsfreigabe ist keine fachliche Abnahme.
