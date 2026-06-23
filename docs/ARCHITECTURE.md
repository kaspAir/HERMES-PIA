# HERMES PIA – Zielarchitektur V0.1

**HERMES PIA** – *Vom Gespräch zum strukturierten Ergebnis.*

Eine Plattform für methodisch geführte Interviews und die automatisierte
Erstellung methodenkonformer Dokumente. Die erste Ausprägung unterstützt den
**Projektinitialisierungsauftrag (PIA) nach HERMES 2022**.

| | |
|---|---|
| Version | 0.1 |
| Status | in Arbeit |
| Teil der Suite | Pseudonymisierung · **HERMES PIA** · Entscheidungsunterstützung |
| Stack | Flask · SQLAlchemy · Jinja · Alembic · Docker |

---

## 1 Architekturvision

HERMES PIA ist kein Dokumenteneditor. Es ist ein **methodisch geführter
Dialograum**, der Fachwissen über eine Methode (z. B. HERMES) nutzt, um aus
einem Gespräch ein vollständiges, methodenkonformes Dokument entstehen zu
lassen.

Der Produktkern ist nicht das Dokument, sondern das **geführte Interview mit
mitdenkender Lückenerkennung**: HERMES PIA fragt nicht nur Abschnitt für
Abschnitt ab, sondern gleicht die Eingaben mit dem ab, was in vergleichbaren
Vorhaben üblich ist, und fragt aktiv nach, wenn etwas Typisches zu fehlen
scheint.

### 1.1 Leitmotiv

> HERMES PIA verwandelt das, was ein Mensch *sagt*, in das, was eine Methode
> *verlangt* – und macht sichtbar, was noch fehlt.

### 1.2 Produktkern

Geführte Wissenserhebung auf Basis eines **Methodenmodells** (Struktur des
Zieldokuments) und eines **Referenzkatalogs** (abgeleitetes Erfahrungswissen je
Projekttyp). Aus dem Zusammenspiel entstehen drei Wirkungen: vollständige
Erfassung, aktive Nachfrage bei Lücken und ein originalgetreu gefülltes
Dokument.

---

## 2 Produktkontext: die Suite

HERMES PIA steht zwischen zwei Schwesterprodukten und ist bewusst so geschnitten,
dass die spätere Integration kein Umbau ist:

- **Pseudonymisierung** – Pseudonymisierung / Datenschutzschicht. Liefert später den
  *anonymisierten* Korpus, aus dem die Referenzkataloge automatisch befüllt
  werden, und kapselt jeden Versand fachlicher Inhalte an ein Cloud-Modell.
- **HERMES PIA** – diese Plattform.
- **Entscheidungsunterstützung** – Entscheidungsunterstützung. HERMES PIA und Entscheidungsunterstützung teilen
  Architekturprinzipien und Stack, sodass eine Suite mit einheitlichem
  Verhalten entsteht.

Wichtige Naht: HERMES PIA definiert das Konzept *Referenzkatalog* heute mit
kuratiertem Wissen. Sobald Pseudonymisierung existiert, wird genau dieser Katalog aus
dem anonymisierten Korpus gespeist – gleiche Struktur, andere Quelle. Demo-
Wissen jetzt, Korpus-Wissen später.

---

## 3 Architekturprinzipien

| Prinzip | Bedeutung |
|---|---|
| Konfiguration vor Programmierung | Methoden, Dokumentstrukturen und Fachwissen liegen als YAML vor, nicht im Code. Eine neue Methode = eine neue Konfiguration. |
| Template-getriebene Generierung | Die Vorlage (`.dotx`) ist die Quelle der Wahrheit. Dokumente werden *gefüllt*, nicht im Code nachgebaut. Derselbe Mechanismus trägt später kundeneigene Vorlagen. |
| Deterministischer Erkennungskern | Die Lückenerkennung (Gap-Check) ist regel-/katalogbasiert und reproduzierbar. Das LLM formuliert und extrahiert, entscheidet aber nicht über das Vorhandensein einer Lücke. |
| KI berät, der Mensch verantwortet | HERMES PIA schlägt vor, fragt nach und formuliert. Inhalt und Freigabe bleiben beim Projektleiter. |
| Datenschutz by Design | Fachliche Inhalte mit Personenbezug gehören vor jedem Cloud-Versand durch die Pseudonymisierung (Pseudonymisierung). Kataloge enthalten nur *abgeleitetes*, aggregiertes Wissen. |
| Methodenneutralität | HERMES/PIA ist die erste Ausprägung, nicht das Fundament. Das Kernmodell kennt „Methode", „Abschnitt", „Tabelle", „Vokabular" – nicht HERMES-Spezifika. |
| Modularität | Fachdomänen (method, catalog, interview, generation, llm) sind klar getrennt. |
| Auditierbarkeit (leichtgewichtig) | Kernobjekte tragen `created_at`, `updated_at`, `version`, `created_by`, `status` – ohne Workflow-Engine. |
| Explizite Architekturentscheide | Wesentliche Entscheide werden als ADR dokumentiert (siehe §12). |

---

## 4 Capability Map

```text
Core Capabilities
├── Methodenmodellierung (Struktur des Zieldokuments)
├── Geführtes Interview
├── Lückenerkennung / Nachfrage (Gap-Check)
├── Referenzwissen je Projekttyp
├── Dokumenterzeugung (template-getrieben)
└── KI-gestützte Formulierung & Extraktion

Enabling Capabilities
├── Konfiguration / Customizing (YAML)
├── Persistenz & Migration
├── Datenschutz-Naht (Pseudonymisierung, später)
├── Audit / Logging
└── Betrieb (Docker)
```

---

## 5 Fachliche Domänen

### 5.1 Method (Methodenmodell)
Beschreibt das Zieldokument: Abschnitte, deren Typ (Fließtext, Tabelle,
Standardtext), Tabellenspalten, kontrollierte Vokabulare und – je Abschnitt –
Interview-Hinweise (Fragen, Vollständigkeitskriterien). Quelle:
`methods/<id>/method.yaml`. Erste Instanz: HERMES 2022 PIA mit 14 Abschnitten.

### 5.2 Catalog (Referenzkatalog)
Abgeleitetes Erfahrungswissen je Projekttyp: typische Ziele, Lieferergebnisse,
Rahmenbedingungen und – zentral – typische Risiken mit `salience` und
vorformulierter Nachfrage. Quelle: `catalogs/<projekttyp>.yaml`. Erste Instanz:
*Einführung einer Fachanwendung*.

### 5.3 Interview (Dialog & Lückenerkennung)
Führt durch die Abschnitte, erfasst Antworten und betreibt den **Gap-Check**:
den deterministischen Abgleich erfasster Inhalte gegen die salienten
Katalogeinträge. Der Produktkern.

### 5.4 Generation (Dokumenterzeugung)
Füllt die originale Vorlage mit den erfassten Inhalten und liefert eine `.docx`.
Template-getrieben.

### 5.5 LLM (Sprachmodell-Anbindung)
Dünne Anbindung an die Anthropic Messages API für Frageformulierung und
Antwortextraktion. Server-seitig, eigener Schlüssel via `.env`.

---

## 6 Applikationsarchitektur

```text
app/
├── factory.py            App Factory: Services aus Konfiguration aufbauen
├── config.py             Pfade zu methods/ und catalogs/, LLM-Konfig
├── domains/
│   ├── method/           Methodenmodell laden/bereitstellen
│   ├── catalog/          Referenzkatalog bereitstellen
│   ├── interview/        Interview-Loop + gap_check.py (Kern)
│   ├── generation/       .dotx -> .docx füllen
│   └── llm/              Anthropic-Client
├── web/                  Flask/Jinja Routen (Health, UI, Demo)
├── shared/               database, logging, errors, model_mixins, config_loader
├── templates/            Jinja
└── static/css/

methods/<id>/method.yaml + template/*.dotx
catalogs/<projekttyp>.yaml
migrations/                Alembic
tests/regression/          inkl. Nachweis des Nachfrage-Verhaltens
```

Die Services (`MethodService`, `CatalogService`, `InterviewService`) werden in
der App Factory aus der Konfiguration instanziiert und am App-Objekt gehalten.
So bleibt die Fachlichkeit datengetrieben.

---

## 7 Datenmodell

Im MVP bewusst schlank. Persistiert wird die **InterviewSession** (Methode,
Projekttyp, Projektname, Antworten je Abschnitt als JSON), erweitert um den
Governance-Mixin (`created_at`, `updated_at`, `version`, `created_by`,
`status`). Methodenmodelle und Kataloge sind **Konfiguration**, keine
Datenbankobjekte – sie werden aus YAML geladen und gecacht.

---

## 8 Der Interview-Loop (Kernablauf)

```text
1. Session starten        -> Methode + Projekttyp wählen
2. Je Abschnitt:
   a. Frage stellen       (aus method.yaml: interview.questions)
   b. Antwort aufnehmen   (frei) -> LLM extrahiert Felder
   c. Vollständigkeit?    (method.yaml: interview.completeness)
3. Nach gap_check-Abschnitten (z. B. Risiken):
   a. Erfasstes vs. salientes Katalogwissen vergleichen   [deterministisch]
   b. Fehlt etwas Typisches -> Nachfrage einspeisen
      "In vergleichbaren Projekten ist X üblich – bewusst weggelassen?"
   c. Antwort: aufnehmen ODER bewusst-ausgeschlossen markieren
4. Dokument erzeugen      -> Vorlage füllen -> .docx
```

Trennung der Verantwortung: Der **Gap-Check** (`interview/gap_check.py`) ist
rein deterministisch und damit in einer Live-Demo verlässlich. Das **LLM**
übernimmt nur Sprache (Frage formulieren, freie Antwort in Felder überführen),
nie die Entscheidung, ob eine Lücke vorliegt.

---

## 9 Dokumenterzeugung

**Heute (originalgetreu):** Die offizielle HERMES-`.dotx` wird entpackt
(ZIP/XML), die farbig-kursiven Beispiel-/Hilfetexte und Platzhalter werden durch
die erfassten Inhalte ersetzt, Tabellenzeilen nach Bedarf dupliziert, danach als
`.docx` zusammengepackt und validiert.

**Später (kundeneigene Vorlagen):** Derselbe template-getriebene Mechanismus.
Die Herausforderung verschiebt sich auf das **Mapping** (welcher Abschnitt
gehört an welche Stelle einer unbekannten Vorlage). Lösung über benannte
Bindungspunkte (Word-Inhaltssteuerelemente) oder eine konfigurierte
Feldzuordnung – nicht über automatisches Raten.

---

## 10 Wissens- und Katalogmodell (Datenschutz-Ausblick)

Der Referenzkatalog enthält **abgeleitetes** Wissen: „bei Projekttyp X tauchen
typischerweise diese Risiken auf". Sobald eine Aussage aggregiert ist, ist der
Personenbezug per Konstruktion verschwunden.

Reihenfolge der Reifung:

1. **Heute:** kuratierter Katalog (HERMES-Standard + Fachwissen).
2. **Mit Pseudonymisierung:** Katalog wird aus dem *anonymisierten* Korpus der ~100 PIAs
   automatisch befüllt (Muster, nicht Rohtext).
3. **Später (optional):** Ähnlichkeitssuche / RAG über den anonymisierten Korpus
   für projektnahe Vorschläge statt nur typbasierter.

Ein eigenes kleines Modell (SLM) ist – falls überhaupt – ein *lokaler* Baustein
(Extraktion/Klassifikation, Privacy), nicht der Wissensspeicher. „Wissen für das
LLM" ist klassisch Retrieval (RAG), nicht Training.

---

## 11 Konfigurationsmodell

**`method.yaml`** (Auszug der Felder): `method` (id, name, framework,
template), `vocabularies` (kontrollierte Listen), `metadata_fields`,
`sections[]` mit `type`, `columns[]`, `interview` (questions, completeness) und
`gap_check`.

**`catalog/<projekttyp>.yaml`**: `project_type`, `ziele[]`,
`lieferergebnisse[]`, `risiken[]` (mit `salience`, `nachfrage`, `schlagworte`),
`rahmenbedingungen[]`.

Schwelle: Einträge mit `salience >= 0.8` lösen eine Nachfrage aus, wenn sie im
erfassten Dokument keine Entsprechung haben.

---

## 12 Architecture Decision Records (initial)

| ADR | Entscheid | Begründung |
|---|---|---|
| ADR-001 | Geteilter Stack mit Entscheidungsunterstützung (Flask App Factory, SQLAlchemy, Jinja, Alembic, Docker) | Einheitliche Suite, Wiederverwendung, geringere kognitive Last. |
| ADR-002 | Methoden & Dokumentstrukturen als YAML-Konfiguration | Erweiterbarkeit ohne Codeumbau; Methodenneutralität. |
| ADR-003 | Template-getriebene Dokumenterzeugung (Vorlage = Quelle der Wahrheit) | Originaltreue heute, kundeneigene Vorlagen später – ein Mechanismus. |
| ADR-004 | Deterministischer Gap-Check, LLM nur für Sprache | Verlässliches, demonstrierbares Verhalten; klare Verantwortungstrennung. |
| ADR-005 | Anthropic Messages API server-seitig, Inhalte erst nach Pseudonymisierung | KI als Berater; Datenschutz by Design. |

Künftige ADRs sollten u. a. festhalten: Persistenzformat der Antworten,
Mapping-Verfahren für kundeneigene Vorlagen, RAG-Architektur.

---

## 13 Sicherheit & Datenschutz

- Echte PIAs enthalten Personendaten; vor jedem Cloud-Versand steht die
  Pseudonymisierung (Pseudonymisierung). Bis dahin: Demos mit synthetischen oder
  handbereinigten Daten.
- API-Schlüssel ausschließlich via `.env` / Umgebungsvariablen, nie im Repo.
- Kataloge enthalten nur aggregiertes Wissen, keine Rohzitate.

---

## 14 Qualität & Tests

Regressionstests unter `tests/regression/`. Besonders:
`test_gap_check.py` belegt das Kernverhalten (fehlt ein typisches Risiko, wird
nachgefragt; ein erfasstes Risiko wird nicht erneut gefragt) und
`test_method_model.py` sichert, dass das Methodenmodell mit den erwarteten
Abschnitten und Vokabularen lädt. Der deterministische Kern ist damit gegen
Regressionen abgesichert.

---

## 15 Roadmap

| Version | Inhalt |
|---|---|
| V0.1 | Gerüst, PIA-Methodenmodell, Referenzkatalog, deterministischer Gap-Check |
| V0.2 | Interview-Loop vollständig (nächste Frage, Extraktion, Vollständigkeit) |
| V0.3 | Dokumenterzeugung originalgetreu (`.dotx` -> `.docx`) |
| V0.4 | UI-Ausbau (Interview-Workspace, Fortschritt, Nachfragen inline) |
| V0.5 | Weitere Projekttypen / weitere Kataloge |
| V0.6 | Pseudonymisierung-Naht: Katalog aus anonymisiertem Korpus befüllen |
| V0.7 | Kundeneigene Vorlagen (Upload + Mapping) |
| V0.8 | RAG über anonymisierten Korpus (projektnahe Vorschläge) |
| V1.x | Weitere Methoden/Dokumenttypen, Mandantenfähigkeit, Governance-Reife |

---

## 16 Abgrenzung / Nicht-Ziele

- Kein Ersatz für die methodische Verantwortung des Projektleiters.
- Keine automatische Freigabe von Dokumenten.
- Kein Wissensspeicher aus Rohdokumenten ohne vorherige Pseudonymisierung.
- (MVP) keine Mandantenfähigkeit, keine Authentisierung, keine Ähnlichkeitssuche.

---

## 17 Kurzform für das Team

> HERMES PIA führt ein methodisches Gespräch und erzeugt daraus ein
> methodenkonformes Dokument. Die Methode und das Erfahrungswissen sind
> Konfiguration, nicht Code. HERMES PIA denkt mit, indem es typische Inhalte
> kennt und bei Lücken nachfragt – verlässlich, weil die Erkennung
> deterministisch ist. Die KI formuliert und extrahiert; entschieden und
> verantwortet wird vom Menschen. Personenbezogene Inhalte gehen erst nach
> Pseudonymisierung in die Cloud.
