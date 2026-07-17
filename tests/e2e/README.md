# Fachliche End-to-End-Fälle (Promotion) – gegen echte Umsysteme

Diese Fälle fliessen eine **echte Diktat-Aufnahme** durch die ganze Kette
(Audio → STT → Interview → LLM-Extraktion → PIA) und prüfen **Invarianten**
(Testkonzept §10), nicht ein exaktes Golden-Dokument – weil echte LLM-Antworten
variieren.

Sie laufen **nur auf Promotion** (nicht bei jedem Build), Testkonzept §9:

```bash
pytest tests/e2e -m promotion -v
```

Ohne Aufnahme oder ohne API-Keys **überspringen** sie sich (kein Fehlschlag).
Das Orakel selbst (tests/e2e/invarianten.py) wird durch nicht-markierte
Selbsttests laufend geprüft.

## Eine Aufnahme als Testdaten hinterlegen

1. Sprich einen realistischen **Ausgangslage**-Abschnitt für ein Beispielprojekt
   (~30–90 Sekunden), wie im Interview.
2. Speichere die Datei unter:

   ```
   tests/e2e/fixtures/<fall-id>_<beschreibung>.<endung>
   ```

   z.B. `tests/e2e/fixtures/pia-fachlich-0003_ausgangslage.webm`
   Unterstützte Endungen: `.webm .wav .mp3 .m4a .ogg .flac`.

3. Damit der Lauf gegen echte Dienste möglich ist, müssen im Ausführungskontext
   gesetzt sein: `STT_API_KEY` (+ ggf. `STT_API_URL`, `STT_MODEL`) und
   `ANTHROPIC_API_KEY`.

Die Aufnahme wird **einmal** transkribiert und das Transkript im Lauf verwendet.
Für einen **deterministischen Jeder-Build-Zwilling** kann dasselbe Transkript
später als eingefrorenes Fixture mit **gemocktem LLM** wiederverwendet werden
(schnelle Suite, §9) – ohne die Aufnahme erneut zu senden.

## Fall-IDs

Die Fälle teilen die IDs mit dem manuellen Katalog
`tests/fachlich/hermes_pia_testfaelle.yaml` und dem Testprotokoll
(`pia-fachlich-000X`) – so bleibt die Traceability Anforderung ↔ Testfall ↔
Ergebnis erhalten (§14).

## Datenschutz

Aufnahmen und Transkripte können sensible Inhalte enthalten. Nur unbedenkliche
Beispielprojekte aufnehmen; keine echten, schützenswerten Personendaten in die
Fixtures legen (die Fixtures liegen im Git-Repo).
