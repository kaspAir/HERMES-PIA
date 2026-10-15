# Adaptives Interview – Ist-Analyse und Umsetzungsplan

Auftrag: `HERMES-PIA_Entwicklerprompt_v1.0.md` (15.10.2026).
Arbeitsbranch: `feature/pia-adaptives-interview`, abgezweigt von `develop` @ `9a11936`.

## 1. Entwicklungsstand

| Referenz | Commit | Befund |
|---|---|---|
| `develop` | `9a1193686d68…` | identisch mit der im Auftrag genannten Referenz; Ausgangspunkt |
| `main` | `35b893c9c9bd…` | deutlich älter; Produktion meldet noch `service: methodos` |

Keine ungesicherten Änderungen. Kein CLAUDE.md im Repository; Arbeitskonventionen
stehen in Commit-Historie und `deploy/BETRIEB.md` (Promotion develop → test →
integration → main, keine Stufe überspringen).

## 2. Vorlagenabgleich

`PIA_HERMESPIA.docx`, SHA-256 `2b02548e…700e9d` – **stimmt** mit dem Auftrag überein.

Die im Repository verwendete Vorlage `methods/hermes_pia/template/projektinitialisierungsauftrag.dotx`
(SHA-256 `3a325f52…`) ist **strukturell identisch**: gleiche Kapitel, Tabellen, Zeilen,
Inhaltssteuerelemente, Auswahlwerte, Fussnoten und Abschnitte. Abweichend sind nur
die zwischengespeicherten Werte der Dateinamen-Felder in den Fusszeilen. Die Abweichungen
zur Referenz liegen damit **nicht in der Vorlage, sondern in Konfiguration und Code**:

| Bereich | Vorlage (verbindlich) | `method.yaml` / Code heute |
|---|---|---|
| Dokument Status | in Arbeit, geprüft, fertiggestellt, abgenommen | in Arbeit, in Pruefung, freigegeben |
| Klassifizierung | Nicht klassifiziert, INTERN, VERTRAULICH, GEHEIM | Nicht klassifiziert, Intern, Vertraulich, Geheim |
| Eintrittswahrscheinlichkeit | Niedrig = 1, Mittel = 2, Hoch = 3 | Tief, Mittel, Hoch |
| Auswirkungsgrad | Tief = 1, Mittel = 2, Hoch = 3 | Tief, Mittel, Hoch |
| Risikozahl | Fussnote: EW × AG | `_risk_num("Niedrig = 1")` ergibt 0 – die echten Vorlagenwerte rechnen nicht |
| Ziele | keine Pflicht je Kategorie | Vollständigkeit verlangt «mind. ein System- und ein Vorgehensziel» – **unbelegt** |
| Kap. 5 | Monat 1–9 + Bestätigung + **Total-Zeile** | Monatsspalten bis 9, Phasendauer still auf 9 gekappt |
| Kommunikation | Kapitel der Vorlage | `required: false`, im Interview faktisch übersprungen |
| Kap. 7 Zeile 2 | **ausgeblendetes** Beispiel (Hilfstext-Stil, `vanish`) | wird über den Stil entfernt – zu prüfen |

## 3. RAG-Integrationsbefund

**Code:** `RagService` (Ingest, Chunking, Cosinus-Suche, Mandantenfilter `org_id IS NULL OR = Mandant`),
`VoyageEmbedder` (nur über die Pseudonymisierungsschicht), `_with_corpus_context`
(Vorschlags-Grounding), `vergleichbare_dauer_wochen` (Dauer-Median je Projekt).

**Betrieb – der entscheidende Befund:** Die Health-Endpunkte melden für **dev, test und int**
`basis_url: null` (Direktmodus). `factory.py` baut den Embedder nur mit `PSEUDO_BASIS_URL`;
ohne sie ist `rag_service.available = False`. **Die bestehende RAG-Integration ist auf keiner
laufenden Stufe aktiv.** Da auch der Ingest diesen Weg braucht, ist anzunehmen, dass die
Server-Korpora leer sind – nachgewiesen ist es nicht: ein SSH-Zugang besteht aus dieser
Umgebung nicht. Der lokale Korpus (`methodos.db`) enthält 0 Chunks.

Quelldaten liegen lokal vor (`C:\Projekte\Daten\Pseudonymisiert_2`: 209 Texte). Sie werden
hier nur als Metadaten gezählt, nicht gelesen und nicht ins Repository übernommen.

**Weitere Lücken im RAG-Code:**

- Die Suche vergleicht alle Vektoren gleicher Länge – Modellgleichheit wird nicht geprüft.
- Treffer tragen keine Chunk-ID, keinen Dokument-Hash, keine Methodenversion, keine Korpusversion.
- Der RAG reichert nur fertige Vorschlagstexte an; er wählt keine Interviewthemen.
- Mehrere Chunks desselben Projekts zählen beim Grounding als getrennte Treffer.

**Folge für die Abnahme:** Die neue RAG-Nutzung wird vollständig integriert und mit einem
deterministischen Embedding-Double getestet. Ein produktiver Nachweis ist erst möglich, wenn
eine Stufe Embeddings erzeugen kann. Das wird nicht als erfolgreiche Integration ausgegeben.

## 4. Gesprächssteuerung heute

- **Abschnittsweise:** `current_state` liefert «nächster unbeantworteter Abschnitt». Eine
  Antwort landet ausschliesslich im aktuellen Kapitel (`answers[section_id]`).
- **Zustandsänderung beim Seitenaufruf:** `current_state` ruft `_ensure_complexity_followups`
  und `_ensure_project_type` – beide rufen das Modell und schreiben. Ein Reload kann neue
  Nachfragen erzeugen.
- **Vollständigkeit:** «Text vorhanden = vollständig» (`_is_complete`).
- **Stille Vorbelegungen:**
  - Kostensatz-Rückfall 1200/1800 CHF ohne hinterlegten Tarif.
  - Termine ab «heute», wenn kein Startdatum genannt wurde.
  - Personentage-Schätzung ohne sichtbare Grundlage im Interview.
  - Pauschales Leeren der Link-Spalte in 0.2/0.3, auch für vom Benutzer genannte Referenzen.
  - Pauschales Entfernen von Zeitrahmen aus den Rahmenbedingungen.
- **Geschlecht:** `detect_gender` leitet aus Namen per Modell Anreden ab (11 Stellen). Das
  verbietet der Auftrag ausdrücklich. Die Funktion entstand auf frühere Bitte des
  Auftraggebers; die neue Vorgabe ersetzt sie.

## 5. Test-Baseline

`pytest tests`: **972 bestanden, 1 fehlgeschlagen, 14 übersprungen.** Der eine Fehler
(`test_ohne_schalter_gibt_es_den_testlauf_nicht`) ist ein Testfehler: das Versionsabzeichen
zeigt den Betreff des letzten Commits, und der enthält das Wort «Testlauf». Der Test prüft das
Wort statt des Formulars. Wird im ersten Schritt korrigiert, nicht entfernt.

## 6. Architekturentscheide

1. **`answers_json` bleibt die Dokumentprojektion.** Generierung, Invariantenprüfung,
   `Projektwissen`, `pia_quelle`, Freigabe, Rechtsgrundlagen- und Schutzbedarfsanalyse lesen
   sie. Der neue Zustand speist sie, statt sie zu ersetzen – eine Wahrheit, mehrere Sichten.
2. **Neuer Zustand neben der Session, additiv:** Gesprächsbeiträge, Aussagen (mit stabiler
   ID, Herkunft, Aussageart, Bestätigung, Beleglage), Widersprüche, RAG-Themenkandidaten.
   Eine Revisionsnummer je Session schützt vor verspäteten Ergebnissen.
3. **Das Modell schlägt Operationen vor, der Code entscheidet.** Jede LLM-Ausgabe hat einen
   versionierten Vertrag; Schema-, Bezugs-, Vokabular- und Revisionsprüfung entscheiden über
   die Übernahme.
4. **Ein Aufruf = eine Modellanfrage.** Bewährtes Muster der Rechtsgrundlagen-Kette und des
   Testlaufs: der Beitrag wird gesichert und verarbeitet; Formulierung, RAG-Themen und nächste
   Frage folgen als einzeln abrufbare Schritte. Die Erkenntnisanzeige aktualisiert sich nach
   dem ersten Schritt.
5. **Die nächste Frage wird gespeichert.** Ein Reload zeigt dieselbe Frage; lesende Ansichten
   ändern nichts.
6. **Neue Sessions laufen adaptiv**, bestehende behalten ihren Ablauf. Eine Umstellung
   übernimmt deren Angaben als «aus früherer Erfassung» – ohne Herkunft zu erfinden.

## 7. Umsetzungsplan

| Schritt | Inhalt | Akzeptanzfälle |
|---|---|---|
| 1 | Versionierte Vorlagenzuordnung; Vokabulare und Rechenregeln nach Vorlage; stille Vorbelegungen entfernen | AT18, AT19 (Teil) |
| 2 | Gemeinsamer Zustand: Modelle, additive Migration, Verträge, Revision, Projektion | AT01, AT03–AT07, AT21 |
| 3 | Vollständigkeitsprofil und Gesprächsplaner | AT02, AT07, AT17 |
| 4 | RAG als Themenquelle: Schema additiv, Modellkompatibilität, Übertragungsregeln, Nachweis | AT08–AT12, AT15 |
| 5 | Endpunkte und Oberfläche mit «Für den PIA erkannt», Korrekturen | AT13, AT14, AT16, AT24 |
| 6 | Abschlussprüfung und vorlagentreuer Export, Kap. 5 über neun Monate | AT18–AT20, AT22, AT25 |
| 7 | Bestandsschutz, Feedback, auslösbare Evaluation | AT23, AT26 |
| 8 | Dokumentation, Anforderungs-Test-Matrix, synthetische Interviews mit DOCX, Screenshots | alle |
