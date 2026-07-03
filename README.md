# HERMES PIA

**Vom Gespräch zum strukturierten Ergebnis.**

HERMES PIA führt Benutzer durch ein methodisch geführtes Interview und erzeugt
daraus methodenkonforme Dokumente. Die erste Ausprägung unterstützt den
**Projektinitialisierungsauftrag (PIA) nach HERMES 2022**.

HERMES PIA fragt nicht nur Kapitel für Kapitel ab, sondern **denkt mit**: Es
gleicht die Eingaben mit typischen Inhalten vergleichbarer Projekte ab und
fragt aktiv nach, wenn etwas Übliches zu fehlen scheint
(z. B. „In vergleichbaren Projekten ist das Risiko *Anwenderakzeptanz* fast
immer aufgeführt – bewusst weggelassen?“).

Teil einer Suite mit **Pseudonymisierung** (Pseudonymisierung / Datenschutzschicht)
und **Entscheidungsunterstützung** (Entscheidungsunterstützung).

---

## Architekturprinzip: Konfiguration vor Programmierung

Die Fachlichkeit steckt in **YAML-Konfiguration**, nicht im Code:

- `methods/hermes_pia/method.yaml` — das Methodenmodell (Abschnitte,
  Tabellenspalten, kontrollierte Vokabulare), 1:1 aus der offiziellen Vorlage.
- `methods/hermes_pia/template/…dotx` — die originale HERMES-Vorlage als
  Quelle der Wahrheit für die Dokumenterzeugung.
- `catalogs/fachanwendung_einfuehrung.yaml` — Referenzkatalog mit *abgeleitetem*
  Erfahrungswissen (typische Ziele/Risiken/Lieferergebnisse), das die
  Nachfragen treibt.

Eine weitere Methode oder ein weiterer Projekttyp = eine weitere YAML-Datei,
kein Codeumbau. Kundeneigene Vorlagen (späteres Ziel) nutzen denselben
template-getriebenen Mechanismus.

## Struktur

```text
app/
  domains/
    method/        Methodenmodell laden/bereitstellen
    catalog/       Referenzkatalog (abgeleitetes Wissen)
    interview/     Interview-Loop + gap_check (Nachfrage-Verhalten)
    generation/    .dotx -> .docx füllen (template-getrieben)
    llm/           Anthropic Messages API (eigener Key via .env)
  web/             Flask/Jinja Routen
  shared/          DB, Logging, Errors, Mixins, Config-Loader
methods/           Methodenmodelle + Vorlagen
catalogs/          Referenzkataloge je Projekttyp
migrations/        Alembic
tests/regression/  Tests (inkl. Nachweis des Nachfrage-Verhaltens)
```

## Lokaler Start

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env             # ANTHROPIC_API_KEY eintragen
alembic upgrade head             # erste Migration siehe WEEKEND_PLAN.md
python run.py
```

- UI: <http://localhost:5000/>
- Health: <http://localhost:5000/health>
- Demo Nachfrage-Verhalten: <http://localhost:5000/demo/followups>

## Tests

```bash
pytest tests/regression
```

`tests/regression/test_gap_check.py` beweist das Showpiece: Fehlt ein für den
Projekttyp typisches Risiko, erzeugt HERMES PIA die passende Nachfrage.

## Datenschutz-Hinweis

Echte PIAs enthalten Personendaten. Bevor reale Dokumente an ein Cloud-Modell
gehen, gehören sie durch die Pseudonymisierung (später: Pseudonymisierung). Für die
interne Vorstellung mit synthetischen / handbereinigten Daten arbeiten.

Siehe **docs/ARCHITECTURE.md** für die Zielarchitektur und **WEEKEND_PLAN.md** für den konkreten Bauplan.
