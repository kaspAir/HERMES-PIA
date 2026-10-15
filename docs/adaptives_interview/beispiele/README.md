# Synthetische Beispielinterviews

Erfundene Organisationen und Personen («Musterkanton», «Beispielstadt»). Erzeugt mit
`tools/fall_durchspielen.py` über dieselben Dienste wie die Oberfläche, mit einem
**Drehbuch-Modell** (`tools/synthetische_faelle.py`) und einem synthetischen Korpus im Stil
früherer HERMES-5.1-Aufträge. Sie zeigen, was der Code aus gegebenen Modellantworten macht –
nicht, wie gut ein echtes Modell das Gespräch führt.

| Datei | Fall | Stand |
|---|---|---|
| `F-01_Abloesung_Entwurf.docx` + `F-01_zustand.json` | Ablösung einer Fachanwendung (Musterkanton): Supportende als **Annahme**, Korrektur des Enddatums, RAG-Thema «Datenbestände und Schnittstellen» übernommen, HERMES-5.1-Methodenaussage **nicht übernommen** | Entwurf: 6 Blocker, Anhang «Offene Punkte», Terminvorschlag noch nicht übernommen und deshalb nicht im Dokument |
| `F-02_Registerdienste_fertiggestellt.docx` + `F-02_zustand.json` | Zusammenlegung von Registerdiensten (Beispielstadt): **zwölf Monate** Initialisierung, Kostensatz hinterlegt, Sachmittel begründet nicht anwendbar, Vorschläge für Terminplan und Monatsverteilung übernommen | Fertiggestellt: keine Blocker, keine Muss-Befunde, Kap. 5 mit Fortsetzungstabelle (Monat 10–12), Deckblatt «fertiggestellt», Prüfung und Freigabe leer |

Die JSON-Dateien enthalten Gespräch, Aussagen (mit Herkunft, Art, Bestätigung), Themen,
Kriterien, Reife und die Folge der Modellaufrufe.

Neu erzeugen:

```
python -X utf8 tools/fall_durchspielen.py F-01 F-01.docx --json F-01.json
python -X utf8 tools/fall_durchspielen.py F-02 F-02.docx --json F-02.json --fertigstellen
```
