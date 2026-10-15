# Adaptives Interview – Abschlussbericht

Auftrag: `HERMES-PIA_Entwicklerprompt_v1.0.md`, Referenz `PIA_HERMESPIA.docx`
(SHA-256 `2b02548e…700e9d`, unverändert). Branch `feature/pia-adaptives-interview`.
Entscheide des Auftraggebers vom 15.10.2026 eingearbeitet (Direktzugang Embeddings auf dev,
Push/Merge/dev, D-030).

Kennzeichnung in diesem Bericht:
**[I]** implementiert · **[T]** automatisiert geprüft · **[D]** auf dev tatsächlich
nachgewiesen · **[O]** offen

Stand dieses Berichts: V0.43.3 auf dev; echter RAG- und Interviewnachweis erbracht (synthetischer Korpus) – siehe Abschnitt 4.

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
- **[D] Bestand auf allen Stufen geprüft** (15.10.2026, 17:20, schreibgeschützt, nur
  Zählwerte): dev, test und int haben die Korpustabelle, aber **0 Chunks**; prod hat **keine
  Korpustabelle**. Es gibt nirgends einen Bestand, der zu erhalten wäre; eine
  Kompatibilitätsprüfung vorhandener Embeddings entfällt deshalb.
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

Alle Läufe mit **echtem Sprachmodell** (`claude-sonnet-4-6`, direkt), **echten Embeddings**
(`voyage-3`, direkt) und dem **synthetischen Korpus** (10 erfundene Vorhaben, 30 Chunks,
extern freigegeben). Der simulierte Projektleiter antwortet aus einem festen Antwortbuch;
Fragen, Aussagen und Themen erzeugt das Modell. Ergebnisse unter `nachweis-dev/lauf-1..3/`.

- **[D] Deploy** V0.43.0 → V0.43.3 über das Jenkins-Deploy-Skript, jedes Mal mit Sicherung
  vorab. Vorfall bei V0.43.0 (parallele Migration) siehe unten.
- **[D] Datenwege** laut `/health`: Sprachmodell und Embeddings «direkt», Spracherkennung
  «aus». Banner in der Oberfläche entsprechend.
- **[D] Korpus geladen:** 1'270 Embedding-Tokens; Bestandsaufnahme danach: 10 Dokumente,
  30 Chunks, einheitlich `voyage-3`/1024, Korpusversion `synthetisch-2026-10-15`.
- **[D] Echter RAG-Abruf mit Quellen:** je Suche 30 Chunks verglichen, 0 inkompatibel;
  Themen tragen ihre Fundstellen (Projekt, Abschnitt, Auszug, Korpusversion); die
  HERMES-5.1-Methodenaussage wurde als «nicht übernehmen» eingeordnet.
- **[D] Vollständiger Durchlauf (Lauf 2, Fall A):** offener Einstieg → Fragen aus Lücken und
  Vergleichsprojekten → berechnete Vorschläge (Terminplan, Monatsverteilung 73 PT auf fünf
  Monate) übernommen → Abschlussprüfung ohne Blocker → fertiggestellt. Word-Datei ohne
  Dokumentbefund; Kap. 5 stimmt mit Kap. 3.1 überein.
- **[D] Korrektur und Widerspruch (Lauf 3, Fall B):** ausdrückliche Korrektur ersetzt das
  Startdatum, Vorschläge rechnen nach; «höchstens 4 Tage» gegen «10 Tage» wird ein offener
  Widerspruch mit Rückfrage, «Es gilt …» löst ihn. Word-Datei als Entwurf mit Anhang
  «Offene Punkte».
- **[D] Kosten Läufe 1–3:** Lauf 1 USD 1.25, Lauf 2 USD 0.71, Lauf 3 USD 0.15 (gerechnet mit
  bewusst hoch angesetzten Preisen 5/25/0.20 USD je Mio Tokens).

- **[D] Echte Erfahrungen im Korpus (Freigabe des Auftraggebers vom 15.10.2026 für die
  «sicheren» PIAs):** 149 Dateien ohne Treffer der Klarnamen-Sperre, davon 137 geladen
  (12 Textdubletten übersprungen) → 1'594 Chunks, neutrale Kennungen statt Dateinamen,
  Kennzeichen «extern freigegeben», Korpusversion `seed-2026-10-15`. Gesamtbestand dev:
  147 Dokumente, 1'624 Chunks, einheitlich `voyage-3`/1024.
- **[D] Lauf 4 – Fall A gegen den echten Korpus:** 1'624 Chunks verglichen, 0 inkompatibel;
  14 Themen aus 4+ früheren Aufträgen; Abschlussprüfung ohne Blocker, fertiggestellt;
  Word-Datei ohne Dokumentbefund, keine Pseudonym-Platzhalter und keine Korpus-Kennungen im
  Dokument. Kosten USD 0.72. **Protokoll und Word-Datei liegen bewusst NICHT im
  Repository** (öffentlich; das Protokoll enthält Auszüge aus echten PIAs), sondern beim
  Auftraggeber lokal.
- **Beobachtung für die fachliche Abnahme (Lauf 4):** Ein Teil der Themen betrifft die
  Struktur früherer PIAs statt des Vorhabens (z.B. «Risikobewertung mit EW, AG und
  Massnahmen», «Sachmittel für die Initialisierung», «Kommunikation während der
  Initialisierung»). Ein Thema verortet Rechtsgrundlagen- und Schutzbedarfsanalyse «als
  Bestandteil der Studie» – in HERMES 2022 sind es eigene Ergebnisse. Die
  Übertragungsregeln R1–R5 sollten das fachlich nachschärfen (Kandidat für die kontrollierte
  Verbesserung, nicht still geändert).
- **Kosten gesamt:** rund **USD 2.95** (Läufe 1–4, Korpus synthetisch und echt; mit bewusst
  hoch angesetzten Preisen).

**Befunde aus den echten Läufen, behoben und mit Tests festgehalten
(`test_echtlauf_befunde.py`):**

1. «45 Personentage» statt «45» → keine Monatsverteilung, Kap. 5 leer (V0.43.2).
2. Dadurch Angebot eines Untersuchungsauftrags → das Modell erfand ein Ziel (V0.43.2).
3. Themenflut: 33 Themen, acht Fassungen desselben aus derselben Quelle, dieselbe Frage
   viermal → 11 Themen in Lauf 2 (V0.43.2).
4. Stille Ersetzung statt Widerspruch → offener Widerspruch ohne Korrektursignal (V0.43.3).
5. Zehn parallel startende Worker migrierten gleichzeitig → Start abgebrochen, dev einige
   Minuten nicht erreichbar → Migration unter Dateisperre (V0.43.1).

**[O] Noch nicht auf dev nachgewiesen:** Sichtprüfung der Oberfläche (Quellen, Anzeige «Für
den PIA erkannt») durch Screenshots auf dev – dafür braucht es eine angemeldete Sitzung; die
Sessions liegen in der Organisation «Synthetik-Nachweis (erfunden)»: Lauf 2 Fall A = Session
20, Lauf 3 Fall B = Session 22.

## 5. Offen

- Die 36 PIAs mit Klarnamen-Verdacht: erst nach Bereinigung und Freigabe oder mit der
  Schutzschicht.
- Fachliche Nachschärfung der Übertragungsregeln (Struktur- statt Vorhabensthemen).
- Sichtprüfung der Oberfläche auf dev (Abschnitt 4).
- Direkter Sprachmodellweg: `PSEUDO_UMGEHEN` steht in der geteilten `.env`, die alle Stufen
  laden (nur Variablennamen gelesen). Ob er auf test/int/prod wirkt, hängt vom Wert ab –
  Entscheid des Betreibers, siehe Betriebsanleitung.
- Render-Prüfung in Word (kein Word/LibreOffice auf dem Entwicklungsrechner).
- Fachliche Abnahme: Abschlussprofil, Übertragungsregeln, Terminlage, Prompts.
- Spracherkennung über eine Schutzschicht.

Diese Entwicklungsfreigabe ist keine fachliche Abnahme.
