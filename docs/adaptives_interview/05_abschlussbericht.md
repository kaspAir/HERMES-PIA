# Adaptives Interview – Abschlussbericht

Auftrag: `HERMES-PIA_Entwicklerprompt_v1.0.md`, Referenz `PIA_HERMESPIA.docx`
(SHA-256 `2b02548e…700e9d`, unverändert). Branch `feature/pia-adaptives-interview`,
nicht gepusht, nicht gemergt, nicht deployt.

## 1. Umgesetzt

- **Gemeinsamer, versionierter Projektzustand** neben der Session (additiv): Aussagen mit
  Herkunft, Art, Bestätigung, Bezug (Initialisierung/Gesamtvorhaben), Entscheid-Charakter,
  Widersprüche, RAG-Themen, Rückmeldungen; Revision je Session; Idempotenz je Anfrage.
- **Adaptive Gesprächsführung**: Modell schlägt Operationen vor, versionierte Verträge
  prüfen; Planer mit Prioritäten (Widerspruch, Rückspiegeln, Lücken nach Gewicht, Vorschlag,
  Zurückstellen, Abschluss), Wiederholungsschutz, gespeicherte nächste Aktion.
- **Bestehender RAG als Themenquelle**: derselbe `RagService`, Modellkompatibilität,
  Fundstellen mit Chunk-ID/Hash/Methoden- und Korpusversion, Übertragungsregeln R1–R5
  (versioniert), Sperrmuster für fremde Namen/Beträge/Pseudonyme, ein Beleg je Projekt,
  Dublettenerkennung über den Dokument-Hash, Thema in der Lücke statt daneben.
- **Live-Anzeige «Für den PIA erkannt»**: ein Lesemodell, ohne Reload, Neu/Geändert seit dem
  letzten Beitrag, Herkunft als Text, Korrekturen an der Anzeige, Sammelübernahme,
  Revisionsschutz, aria-live, schmale Ansicht mit Kurzstatus.
- **Abschlussprüfung und Export**: Abschlussprofil 1.1.0 plus verbindliche Ausgabeprüfung;
  «Fertigstellen» nur für den geprüften Stand; vorlagentreuer Export mit acht Basis-
  Terminzeilen, Enddatum, Risikozahl nach Vorlage, Kap. 5 über neun Monate, Protokolle nur mit
  tatsächlichen Vorgängen, Herkunftsnachweis ohne Modellaufruf, Anhang «Offene Punkte» für
  Entwürfe; berechnete Vorschläge für Terminplan und Monatsverteilung.
- **Bestandsschutz**: bestehende Sessions unverändert; Umstellung mit Sicherung, Rückfallweg,
  Abweisung der alten Schreibwege für adaptive Sessions; Löschung samt Gesprächsdaten.
- **Pseudonymisierung** im adaptiven Weg: angehaltener Beitrag bleibt gespeichert, Entscheid
  über die bestehende Seite, unveränderte Wiederholung.
- **Kontrollierte Verbesserung**: versionierte Rückmeldungen, Freigabe, Kandidaten,
  Baseline-Vergleich (`tools/evaluation_interview.py`).
- Rückfallschalter `INTERVIEW_ADAPTIV=0`.

## 2. Getestet

- **1123 Tests bestanden, 14 übersprungen** (Ausgangslage 972/1 Testfehler/14). Zuordnung zu
  AT01–AT26: `04_anforderungs_test_matrix.md`.
- **Browser**: 22 von 22 Prüfungen in kopflosem Chrome, Screenshots in `nachweis/`
  (Desktop, schmal, Abschluss, Pseudonymisierung).
- **Word-Dateien**: zwei synthetische Fälle in `beispiele/`; F-02 ohne Dokumentbefund der
  Ausgabeprüfung, F-01 als Entwurf mit offenen Punkten.
- **Baseline-Auswertung** in `auswertung/vergleich.json` (mit/ohne RAG).

## 3. Nicht nachgewiesen – offen

1. **RAG mit echtem Korpus.** Auf dev, test und int ist `PSEUDO_BASIS_URL` leer; damit gibt es
   keinen Embedder und kein RAG. Ob die Server-Datenbanken Chunks enthalten, konnte ich ohne
   SSH-Zugang nicht prüfen. Alle RAG-Nachweise laufen mit einem deterministischen Embedding-
   Double. **Das ist keine produktive Integration.**
2. **Echtes Sprachmodell.** Kein Live-Lauf (kostenpflichtig, nicht autorisiert). Ob ein Modell
   aus freien Beiträgen die erwarteten Operationen ableitet, ist offen.
3. **Render in Word.** Kein Word/LibreOffice auf dem Entwicklungsrechner; geprüft wurden
   Struktur, Text und Invarianten.
4. **Migration auf einer echten Stufe.** Nur auf Test-Datenbanken ausgeführt.

## 4. Fachlich abzunehmen

- Abschlussprofil 1.1.0 (welche Kriterien «bereit» verhindern) und Gewichtung.
- Übertragungsregeln R1–R5 und Korpusdeklaration «HERMES 5.1».
- Lage der vorgeschlagenen Termine im Phasenverlauf (Produktentscheid).
- Änderungen an Invarianten (Tabelle in `02_architektur_und_grenzen.md`), insbesondere
  **D-030 von Muss zu Hinweis** (Vorlage verlangt keine Zielkategorien, AT17).
- Formulierung der Prompts mit einem echten Modell.

## 5. Ausserhalb des Auftrags

Keine neue HERMES-Aufgabe für die PIA-Erstellung; keine automatische Übernahme von
Verbesserungen; keine produktive Migration, kein Push, kein Merge, kein Deploy.

## 6. Entscheide, die ich brauche

1. **Zugang für RAG**: Pseudonymisierungsdienst auf dev in Betrieb nehmen, oder einen
   geschützten Direktzugang für Embeddings auf dev zulassen (analog zum LLM-Direktmodus)?
   Und: Liegen auf den Stufen bereits Chunks, oder soll der Korpus neu geladen werden?
2. **Freigabe zum Push** des Branches und zum Merge nach `develop` (danach dev.hermespia.ch).
3. **D-030** als Hinweis bestätigen – oder die Vorlage bzw. HERMES-Quelle nennen, die beide
   Zielarten verlangt.
