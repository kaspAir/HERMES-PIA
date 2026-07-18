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

> ⚠️ **Das GitHub-Repo ist ÖFFENTLICH.** Sprachaufnahmen (Stimme!) gehören NIE
> ins Repo. `tests/e2e/fixtures/*.{m4a,wav,mp3,webm,ogg,flac}` sind daher
> gitignoriert. Committet wird höchstens ein **Transkript** (Text), und auch das
> nur bei unbedenklichem Inhalt.

1. Sprich einen realistischen **Ausgangslage**-Abschnitt für ein Beispielprojekt
   (~30–90 Sekunden), wie im Interview.
2. Ablage der Aufnahme (Dateiname `<fall-id>_<beschreibung>.<endung>`, z.B.
   `pia-fachlich-0003_ausgangslage.m4a`; Endungen `.webm .wav .mp3 .m4a .ogg .flac`):
   - **Lokal:** in `tests/e2e/fixtures/` (gitignoriert – wird nicht gepusht).
   - **Build-Agent (Promotion):** an einem geschützten Ort ablegen und den Ordner
     über die Umgebungsvariable **`E2E_FIXTURES_DIR`** angeben (z.B. per
     Jenkins-Secret-File-Credential, das die Datei vor dem Testlauf dorthin
     schreibt). Der Test sucht zuerst dort, dann im Repo-Ordner.

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

Aufnahmen enthalten die **Stimme** (biometrisch) und ggf. sensible Inhalte. Das
Repo ist öffentlich → Audio bleibt **draussen** (gitignoriert, nur auf dem
geschützten Build-Agent via `E2E_FIXTURES_DIR`). Nur unbedenkliche
Beispielprojekte aufnehmen; keine echten, schützenswerten Personendaten.
Transkripte gehen an den externen STT/LLM-Dienst – Datenresidenz beachten.
