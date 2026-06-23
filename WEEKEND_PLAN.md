# Wochenend-Bauplan — HERMES PIA bis Montag

Ziel: Eine überzeugende **interne** Vorstellung am Montag. Ein durchgehender
vertikaler Schnitt – lieber ein Fall, der von vorne bis hinten läuft, als zehn
halbfertige Felder.

**Projekttyp der Demo:** Einführung einer Fachanwendung (inkl. Org-Anpassung).

---

## Was schon fertig ist (in diesem Paket)

- Repo-Gerüst im Entscheidungsunterstützung-Stil (Flask App Factory, Services, Shared-Infra).
- **PIA-Methodenmodell** vollständig aus der echten Vorlage abgeleitet
  (`methods/hermes_pia/method.yaml`) – inkl. Tabellenspalten und der
  kontrollierten Vokabulare (Zielkategorie, Priorität, EW/Auswirkungsgrad).
- **Referenzkatalog** für den Demo-Projekttyp (`catalogs/…yaml`).
- **Nachfrage-Verhalten** als deterministische Lückenprüfung
  (`app/domains/interview/gap_check.py`) – bereits verifiziert, mit Tests.
- Originale **HERMES-Vorlage** eingebettet (`methods/hermes_pia/template/`).
- Anthropic-Client als Stub (`app/domains/llm/client.py`).

## Reihenfolge fürs Wochenende (mit Claude / Claude Code)

### 1. Erste Migration erzeugen (15 Min)
```bash
alembic revision --autogenerate -m "interview session"
alembic upgrade head
```

### 2. Interview-Loop konkretisieren (Kernarbeit, halber Tag)
In `app/domains/interview/service.py`:
- „nächste Frage“-Logik je Abschnitt aus `method.yaml` (Feld `interview`).
- Freie Antwort → strukturierte Felder extrahieren (LLM via `llm/client.py`).
- Vollständigkeitsprüfung je Abschnitt (Feld `completeness`).
- Nach dem Abschnitt *Risiken*: `followups_for_risks(...)` aufrufen und die
  Nachfragen in den Dialog einspeisen — **das ist der Wow-Moment**.

> Tipp: Das LLM formuliert/extrahiert. Die *Erkennung* der Lücke bleibt
> deterministisch im Katalog — so ist die Demo verlässlich.

### 3. Minimale UI (halber Tag)
- Eine Interview-Seite: aktuelle Frage, Antwortfeld, Fortschritt „was fehlt
  noch“, eingestreute Nachfragen.
- Übersicht der erfassten Abschnitte.
- (Design bewusst schlicht; Politur später.)

### 4. Dokumenterzeugung (halber Tag)
In `app/domains/generation/service.py` (Ansatz steht im Docstring):
- `.dotx` entpacken (ZIP/XML).
- Farbig-kursive Beispiel-/Hilfetexte und Platzhalter durch echte Inhalte
  ersetzen; Tabellenzeilen je nach Anzahl Einträge duplizieren.
- Als `.docx` zusammenpacken und validieren.
- **Originalgetreu** = gegen genau diese Vorlage füllen (nicht im Code nachbauen).

### 5. Demo-Drehbuch (1 Std.)
- Synthetisches Fachanwendungs-Projekt vorbereiten (KEINE echten Daten).
- Bewusst ein typisches Risiko weglassen → HERMES PIA fragt nach → aufnehmen →
  fertiges PIA als `.docx` erzeugen. Das ist die Story für Montag.

## Bewusst NICHT im Wochenend-Scope

- Anonymisierung der 100 echten PIAs → das ist Pseudonymisierung (eigener Track).
- Echte Ähnlichkeitssuche / Embeddings / RAG über den Korpus → spätere Ausbaustufe.
  Für Montag genügt die Typ-Zuordnung + kuratierter Katalog.
- Kundeneigene Vorlagen-Uploads → später (gleicher template-getriebener Mechanismus).
- Authentisierung, Mandantenfähigkeit.

## GitHub (zu Hause, alles public)

```bash
cd hermes-pia
git init
git add .
git commit -m "HERMES PIA scaffold: HERMES PIA method model, reference catalog, gap-check"
git branch -M main
# Repo vorher auf GitHub anlegen (public), dann:
git remote add origin https://github.com/kaspAir/HERMES-PIA.git
git push -u origin main
```
