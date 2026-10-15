# Adaptives Interview – Architekturentscheide und Grenzen

Ergänzt `01_ist_analyse.md` (Abschnitt 6). Hier steht, was in der Umsetzung entschieden
wurde, warum, und wo die Grenzen liegen.

## Aufbau in einem Satz

Der Benutzer spricht frei; das Modell **schlägt Operationen vor**, versionierte Verträge
prüfen sie, der **gemeinsame Zustand** (Aussagen mit Herkunft, Art, Bestätigung, Bezug)
speichert sie mit Revision, eine **deterministische Projektion** erzeugt daraus
`answers_json` – die Sicht, aus der Anzeige, Vorschau, Prüfung und Word-Export lesen.

```
Beitrag ──► Vertrag ──► Zustand (Revision) ──► Projektion ──► answers_json ──► Anzeige / Vorschau / DOCX
   │                       ▲      ▲                                   │
   │       RAG-Themen ─────┘      └── Systemvorschläge (berechnet)    └── Ausgabeprüfung (Invarianten)
   └── nächste Aktion (Planer, gespeichert)
```

Module unter `app/domains/interview/adaptiv/`: `vertraege`, `zustand`, `projektion`,
`vollstaendigkeit`, `planer`, `vorschlaege`, `rag_themen`, `anzeige`, `dienst`, `prompts`
(+ `prompt_texte/`). Konfiguration als Daten: `methods/hermes_pia/vorlagenzuordnung.yaml`,
`abschlussprofil.yaml`, `rag_uebertragung.yaml`.

## Entscheide aus der Umsetzung

1. **Systemvorschläge sind berechnet, nicht formuliert** (`vorschlaege.py`). Terminplan
   und Monatsverteilung entstehen ohne Modell aus bekannten Grössen (Start, Ende,
   Personentage) und nennen ihre Grundlage. Sie bleiben unbestätigt, bis die Projektleitung
   sie übernimmt. Ändert sich die Grundlage, wird der offene Vorschlag ersetzt; ein
   verworfener kommt nicht wieder. Die relative Lage der Termine ist ein **Produktentscheid**
   von HERMES PIA, keine HERMES-Vorgabe – so steht es im Vorschlag.

2. **Der Download ruft kein Modell auf.** Für adaptive Sessions wird der Herkunftsnachweis
   aus dem Zustand berechnet; derselbe Stand ergibt dieselbe Datei (`word/document.xml`
   bytegleich). Der bisherige Ablauf behält seine modellformulierte Begründung.

3. **«Bereit» heisst: herunterladbar.** Die Abschlussprüfung vereint das Abschlussprofil
   mit der verbindlichen Ausgabeprüfung (Invarianten, Daten- und Dokumentebene). Geprüft
   wird der Stand, wie er ausgegeben wird – einschliesslich des Versionseintrags, den der
   Download-Schritt anlegt (`pia.ausgabestand`, nicht gespeichert). Das Profil wurde
   angeglichen (1.1.0), wo die Ausgabeprüfung mehr verlangte (Sachmittel, Risiko-
   Verantwortung und -Termin).

4. **Status nur aus tatsächlichen Vorgängen.** Deckblatt: «in Arbeit» oder – nach
   bestandener Abschlussprüfung und ausdrücklicher Fertigstellung – «fertiggestellt».
   «geprüft» und «abgenommen» setzt HERMES PIA nie. Prüfung und Freigabe im
   Dokument-Protokoll bleiben leer, bis sie stattgefunden haben. Jede Änderung nach der
   Fertigstellung setzt den Status zurück.

5. **Kap. 5 über neun Monate:** Fortsetzungstabellen mit umbeschrifteten Monatsspalten
   («Monat 10» …), Summenzeile je Tabelle. Die Invarianten D-001/D-060 zählen alle Monate.

6. **Entwürfe tragen ihre Lücken im Dokument** (Anhang «Offene Punkte»), nicht nur in der
   Oberfläche.

7. **Bestehende Sessions** bleiben im bisherigen Ablauf. Eine Umstellung sichert zuerst die
   Dokumentdaten, übernimmt jede Angabe als «aus früherer Erfassung» (unbestätigt, Art
   unbekannt) und lässt sie im Dokument, bis sie bestätigt, berichtigt oder verworfen wird.
   Der Rückfallweg stellt den gesicherten Stand wieder her. Die Schreibwege des bisherigen
   Interviews weisen adaptive Sessions ab.

8. **Pseudonymisierung:** Ein angehaltener Beitrag bleibt gespeichert; es geht nichts an das
   Modell. «Fundstellen prüfen und verarbeiten» führt über die bestehende Entscheidungsseite
   und wiederholt die Auswertung **desselben** Beitrags. Kein «trotzdem senden».

9. **Kontrollierte Verbesserung:** Rückmeldungen tragen die wirksamen Versionen und sind
   erst nach ausdrücklicher Freigabe Auswertungsdaten. Kandidaten entstehen ab drei
   gleichartigen Rückmeldungen und werden nie automatisch übernommen. Ein Vergleich läuft
   offline gegen die Baseline, getrennt nach Entwicklungs- und Prüffällen, mit und ohne RAG;
   Schutzkennzahlen (unbestätigte Angaben im Dokument, «nicht übernehmen»-Themen gefragt,
   Muss-Befunde im Export) dürfen sich nie verschlechtern. Der Korpus erkennt Dubletten über
   den Dokument-Hash; es gibt keinen Weg, eigene Ausgaben in den Korpus zurückzuspeisen.

## Entscheide an bestehenden Normen (bitte fachlich bestätigen)

| Was | Vorher | Jetzt | Grund |
|---|---|---|---|
| Invariante D-030 «beide Zielarten» | Muss | **Hinweis** | Vorlage verlangt keine Zielkategorien; Auftrag AT17: «unbelegte Pflicht-Zielkategorien werden nicht erzwungen» |
| D-053 Rollenkatalog | «AG»/«PL» unbekannt | als Rollen anerkannt | Die Vorlage definiert AG und PL selbst (Kap. 0.4) und führt sie als Basiszeilen |
| D-007 gebündelte Personalkosten | Zeile «Interne Personalkosten (gem. Kap. 3.1)» gemeldet | anerkannt, wenn die genannten PT den internen PT aus 3.1 entsprechen | So schreibt HERMES PIA die Zeile selbst; die Gegenprobe (falsche PT) meldet weiter |
| D-042 Trennung intern/extern | fehlte ohne externe Posten | Zeile «Summe externe Kosten (keine externen Posten erfasst): 0» | Die 0 ist aus Kap. 3.1/3.2 abgeleitet, nicht angenommen |
| D-001/D-060 | nur Monat 1–9 | alle Monate | Kap. 5 über neun Monate |

## Grenzen (ehrlich)

- **RAG ist auf keiner laufenden Stufe aktiv** (`PSEUDO_BASIS_URL` leer → kein Embedder).
  Die Themennutzung ist vollständig integriert und mit einem deterministischen Embedding-
  Double getestet – ein Nachweis mit dem echten Korpus steht aus.
- **Keine Live-Tests mit einem echten Sprachmodell.** Alle Gesprächsläufe nutzen Drehbücher.
  Ob ein echtes Modell aus freien Beiträgen dieselben Operationen ableitet, ist offen.
- **Kein Render-Nachweis in Word.** Auf dem Entwicklungsrechner gibt es weder Word-
  Automatisierung noch LibreOffice; geprüft wurden Struktur, Text und Invarianten der Datei.
- Fortsetzungstabellen in Kap. 5 zeigen leere Spalten bis «Monat 18», wenn die Phase z.B.
  zwölf Monate dauert (die Spaltenbreiten der Vorlage bleiben unverändert).
- Die Rubrik für Gesprächsqualität (Relevanz, Kontextnutzung, Neutralität, Phasenfokus,
  RAG-Übertragung, Aktualität der Anzeige, Dokumentqualität) ist in `03_betriebsanleitung.md`
  definiert; gemessen werden offline nur die deterministisch messbaren Teile.
