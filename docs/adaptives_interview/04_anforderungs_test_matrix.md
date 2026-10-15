# Anforderungs-Test-Matrix AT01–AT26

Stand 15.10.2026, Branch `feature/pia-adaptives-interview`. Die Nummern folgen dem
Entwicklungsauftrag v1.0, Abschnitt 14.

**Nachweisarten**

- **T** – automatisierter Test (pytest, Modell-Double bzw. Drehbuch-Modell, deterministisch)
- **B** – im echten Chrome nachgewiesen (`tools/ui_nachweis_adaptiv.py`, 22 Prüfungen,
  Screenshots unter `nachweis/`)
- **D** – erzeugte Word-Datei geprüft (`beispiele/`, Strukturanalyse und Invarianten)
- **F** – fachlich abzunehmen (durch Menschen; kein Test kann das ersetzen)
- **L** – braucht einen Live-Lauf mit echtem Modell bzw. echtem Korpus (nicht durchgeführt)

Modell-Doubles beweisen das Verhalten des Codes bei einer gegebenen Modellantwort – nicht,
dass ein echtes Modell diese Antwort gibt. Diese Lücke steht in jeder Zeile mit **L**.

Testdateien unter `tests/regression/`; Kurzformen: `zustand` = `test_adaptiv_zustand.py`,
`rag` = `test_adaptiv_rag.py`, `routen` = `test_adaptiv_routen.py`, `abschluss` =
`test_adaptiv_abschluss.py`, `bestand` = `test_adaptiv_bestand.py`, `pseudo` =
`test_adaptiv_pseudonymisierung.py`, `verbesserung` = `test_adaptiv_verbesserung.py`,
`vorlage` = `test_vorlagenzuordnung.py`.

| AT | Erwartung (kurz) | Tests | Nachweis | Offen |
|---|---|---|---|---|
| 01 | Ein Beitrag beliefert mehrere Bereiche | zustand: `at01_ein_beitrag_beliefert_mehrere_bereiche` | T, B | L: Zerlegung durch ein echtes Modell |
| 02 | Gleicher Abschnitt, anderer Kontext → andere Aktion | rag: `at02_gleicher_abschnitt_unterschiedlicher_kontext` | T | L, F: Eignung der Fragen |
| 03 | Idee ≠ Entscheid | zustand: `at03_idee_wird_nicht_zum_entscheid` | T | L |
| 04 | Unsicheres bleibt unbestätigt, keine stillen Standardwerte | zustand: `at04_unbestaetigtes_bleibt_unbestaetigt`; abschluss: `at04_abschlussbericht_nennt_annahmen_und_korrekturen`; `test_kostensatz.py`, `test_postprocess.py` (kein Tarif, kein «heute») | T, D | – |
| 05 | Korrektur ersetzt nachvollziehbar, Widersprüche bleiben sichtbar | zustand: `at05_korrektur_ersetzt_nachvollziehbar`, `at05_widerspruch_bleibt_sichtbar_und_hat_vorrang` | T, B | L |
| 06 | Gesamtbudget ≠ Initialisierungsbudget | zustand: `at06_gesamtbudget_ist_kein_initialisierungsbudget` | T | L |
| 07 | «Weiss ich nicht» → offener Punkt, keine Schleife, Wiederaufnahme | zustand: `at07_…` (3 Tests) | T | – |
| 08 | RAG-Thema führt nachweisbar zu einer Lückenfrage | rag: `at08_rag_thema_fuehrt_zu_einer_kontextgerechten_frage` | T, B, **D** (echte Embeddings, synthetischer Korpus) | Nutzen mit echten Aufträgen offen (Freigabe/Schutzschicht) |
| 09 | Versionsgrenze HERMES 5.1 → 2022 | rag: `at09_alte_methodenpflicht_wird_nicht_uebernommen` | T | F: Übertragungsregeln R1–R5 |
| 10 | Fundstellen rückverfolgbar, Chunks eines Projekts = ein Beleg | rag: `at10_…` (2 Tests); verbesserung: `at26_kein_ungesteuertes_korpuswachstum` (Hash-Dublette) | T | L |
| 11 | RAG-Ausfall stoppt nichts, Zustand erkennbar | rag: `at11_…` (3 Tests); `test_datenweg.py`: Ausfall der Schutzschicht führt nie zum Anbieter, Ausfall im Direktmodus ist ein Fehler | T, B («nicht abgefragt») | – |
| 12 | Mandantentrennung, keine fremden Namen/Beträge, keine inkompatiblen Embeddings | rag: `at12_…` (3 Tests); `test_datenweg.py`: Direktmodus durchsucht nur freigegebene Korpusteile; `test_korpus_und_echtlauf.py`: Bestandsaufnahme (nur lesend, Kompatibilität) | T | L: Bestand auf den Stufen nicht geprüft (kein Serverzugang) |
| 13 | Live-Aktualisierung ohne Reload, Neu/Geändert erkennbar | routen: `at13_…` (2 Tests) | T, B | Antwortzeiten nur je Beitrag protokolliert (`dauer_s`), nicht unter Last gemessen |
| 14 | Live-Korrektur ohne Neustart | routen: `at14_…` (2 Tests) | T, B | – |
| 15 | Keine Scheinsicherheit, Herkunft unterscheidbar | rag: `at15_herkunft_ist_unterscheidbar_und_ohne_prozente` | T, B | – |
| 16 | Bedienbarkeit Desktop/schmal, Tastatur, Fokus | routen: `at16_…` | T, B (schmal 390 px, kein Querscrollen) | F: Bildschirmleser-Test |
| 17 | Echte Vollständigkeit, n/a ohne Schleife, keine Pflicht-Zielkategorien | zustand: `at17_…` (2 Tests); abschluss: `at17_muss_befunde_der_ausgabepruefung_blockieren_den_abschluss`; vorlage: `keine_pflicht_je_zielkategorie_mehr`; `test_invarianten.py`: `fehlende_zielart_ist_nur_ein_hinweis` | T | F: Abschlussprofil 1.1.0 |
| 18 | Vorlagenabdeckung (Deckblatt, 0.1–0.5, 1–8, 8 Terminzeilen, Enddatum, Risikospalten, 3 Protokolle) | abschluss: `at18_die_vorlage_ist_vollstaendig_abgebildet`; vorlage: 17 Tests | T, D | – |
| 19 | Zahlen und Monate, Risikozahl, Kostengrundlage | abschluss: `at19_kapitel5_ueber_neun_monate_mit_fortsetzung`, `at19_risiken_…`, `invariante_d001_…`, `invariante_d007_…`; vorlage: `risikozahl_…`, `unbekannt_ist_null_nicht_null` | T, D (F-02: 12 Monate) | – |
| 20 | Vorschläge erst nach Übernahme; keine Prüf-/Abnahme-/Freigabeeinträge durch Export | zustand: `at20_…`; abschluss: `at20_…` (5 Tests) | T, D | – |
| 21 | Fehler und Parallelität ohne Verlust/Rückschritt | zustand: `at21_…` (5 Tests); abschluss: `at21_…` (2 Tests) | T | Parallele Tabs nur über Revisionsprüfung getestet, nicht mit zwei Browsern |
| 22 | DOCX-Qualität, Vorschau = Export, idempotent, lange Inhalte | abschluss: `at22_…` (5 Tests) | T, D | **Kein Render-Test in Word/LibreOffice** (auf diesem Rechner nicht vorhanden) |
| 23 | Bestandsschutz, Migration und Rückfall | bestand: 9 Tests; routen: `at23_bestehende_session_behaelt_ihren_ablauf` | T | Migration nur auf Test-Datenbanken; **keine produktive Migration ausgeführt** |
| 24 | Sicherheit, Berechtigungen, Mandanten, Datenwege | routen: `at24_…` (3 Tests); pseudo: 4 Tests; `test_datenweg.py` (13 Tests: Direkt nur ausdrücklich, Schutzschicht gewinnt, keine Schlüssel in `/health`, Banner); `test_stufenkonfiguration.py`: Embeddings direkt nur auf dev | T, B (Entscheidungsseite) | Schutzschicht bewusst noch nicht angebunden (späteres Standardwerkzeug) |
| 25 | Ende-zu-Ende: vollständig vs. Entwurf | abschluss: `at25_…` (4 Tests) | T, B (F-02 bis «Fertiggestellt»), D | L, F: realer Dialog mit echtem Modell |
| 26 | Kontrollierte Verbesserung | verbesserung: 7 Tests; `tools/evaluation_interview.py` | T | L: Bewertung mit echtem Modell offen |
| – | Echter Nachweis dev | `test_korpus_und_echtlauf.py`; Befunde der echten Läufe: `test_echtlauf_befunde.py` (7 Tests) | T, **D** (3 Läufe, USD 2.11) | Sichtprüfung der Oberfläche auf dev |

**Gesamter Testbestand:** 1149 bestanden, 14 übersprungen (Ausgangslage 972 / 1 Testfehler / 14). Die 14 übersprungenen sind die fachlichen Ende-zu-Ende-Fälle `tests/e2e/test_fachlich_e2e.py` (pia-fachlich-0001 bis 0014): sie brauchen Audioaufnahmen, die bewusst nicht im Repository liegen. Sie prüfen den bisherigen Ablauf mit Spracherkennung und sind für diese Änderung **nicht** gelaufen.
Kein Test wurde entfernt. Geänderte Erwartungen mit Quellenbezug:

- `test_hermes_correctness.py`: Rollenbezeichnungen neutral («/in»), weil der Auftrag
  Geschlechtsableitung aus Namen untersagt (Abschnitt 10).
- `test_invarianten.py`, `test_fachpruefung.py`: D-030 ist ein Hinweis (die Vorlage sieht
  Zielkategorien vor, verlangt aber nicht, dass beide vertreten sind; AT17); die Tests, die D-030 nur als Beispiel für «einen Muss-Befund»
  nutzten, verwenden jetzt D-071.
- `test_pseudonymisierung.py`: «der Embedding-Weg kennt keinen eigenen Schlüssel» ist durch
  den Entscheid vom 15.10.2026 abgelöst; geprüft wird jetzt die Doppelbedingung (Schalter +
  Schlüssel). Das Banner nennt jeden direkten Weg statt «abgeschaltet».
- `test_stufenkonfiguration.py`: der dev-Block trägt zusätzlich `EMBEDDING_DIREKT=1`.
- `test_pseudonymisierung.py`: prüft ausdrücklich den bisherigen Ablauf
  (`INTERVIEW_ADAPTIV=False`), weil dessen Schreibwege adaptive Sessions jetzt abweisen; den
  adaptiven Weg prüft `test_adaptiv_pseudonymisierung.py`.
