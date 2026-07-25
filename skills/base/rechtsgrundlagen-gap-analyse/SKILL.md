---
name: rechtsgrundlagen-gap-analyse
description: >-
  Zweite Schicht nach der Rechtsgrundlagen-Kartierung: prüft für jede identifizierte
  *Rechtslücke* eines Schweizer Verwaltungs-/Projektvorhabens, ob wirklich keine
  hinreichende Grundlage der richtigen Normstufe besteht, und schlägt vor, WIE die
  Lücke zu schliessen wäre — minimal nötige Normstufe (Legalitätsprinzip), zuständiges
  Organ und Verfahrensweg, alles als Fakten. Nutze diesen Skill, wenn eine
  Rechtsgrundlagen-Kartierung eine Rechtslücke ergeben hat, wenn gefragt wird, ob ein
  neues Gesetz/eine neue Verordnung nötig ist, auf welcher Normstufe eine Grundlage
  geschaffen werden müsste, oder wie eine fehlende gesetzliche Grundlage gedeckt wird.
  Grundsatz: beraten und belegen, nicht entscheiden — und die rechtliche Würdigung
  (ob die Massnahme zulässig wäre) NICHT vorwegnehmen.
scope: base
version: "1.0"
owner: kaspAIr
applies_to: rechtsgrundlagenanalyse
---

# Rechtsgrundlagen-Gap-Analyse (Schweiz)

Diese Methode setzt **nach** der Kartierung an und bearbeitet nur deren **Rechtslücken**
(nicht Recherche- oder Informationslücken). Sie beantwortet zwei Fragen:

> **Besteht wirklich keine hinreichende Grundlage — auf der *nötigen* Normstufe?
> Und wenn nein: auf welcher Stufe, durch welches Organ, über welchen Verfahrensweg
> müsste eine geschaffen werden?**

Der Wert liegt darin, eine Lücke nicht vorschnell zu behaupten und den Deckungsweg als
**Fakten** auszuweisen — nicht als Bewertung.

## Eingang

- Die **Rechtslücken** aus der Kartierung (je: betroffene Tätigkeit, warum ungedeckt).
- Der Projektkontext (welche hoheitliche Tätigkeit, welche Eingriffstiefe).
- Ignoriere Recherche-/Informationslücken der Kartierung — die gehören zurück in
  Recherche bzw. an die Projektleitung, nicht hierher.

## Was diese Methode NICHT tut (die 4-Schichten-Grenze)

Vier Schichten, strikt getrennt — sie zu vermischen ist der gefährlichste Fehler:

```
Kartierung          → Welche Grundlagen bestehen?        (vorige Schicht)
Gap-Analyse         → Fehlt eine Grundlage & wie decken? ← DIESE Schicht
Rechtliche Würdigung→ Wäre die Massnahme zulässig?       (eigene Schicht)
Handlungsoptionen   → Welche rechtmässigen Alternativen? (eigene Schicht)
```

- **Keine Zulässigkeits-/Verfassungswürdigung.** Ob die Massnahme inhaltlich zulässig
  wäre (Verhältnismässigkeit, Grundrechte, Kerngehalt), ist Schicht 3 — hier tabu.
- **Keine Termin-/Risikobewertung.** Ob ein Verfahren lange dauert oder ein Referendum
  wahrscheinlich ist → Risiko-Matrix / PMP. Hier stehen nur die *Verfahrens-Fakten*
  (z. B. „Referendum: obligatorisch").
- **Keine Handlungsempfehlung/Alternativen** — Schicht 4.

## Ablauf

### 1. Gap wirklich bestätigen
Bevor eine Lücke bestätigt wird, sind zwei Fragen zu klären:

**(a) Planwidrige Lücke oder qualifiziertes Schweigen?**
Fehlt die Grundlage *planwidrig* (der Gesetzgeber hat den Fall übersehen → echte,
schliessbare Lücke) — oder ist das Fehlen eine *bewusste* Nichtregelung
(«qualifiziertes Schweigen»)? Indiz für qualifiziertes Schweigen: ein bestehendes,
kohärentes System abgestufter Regelungen, das die Tätigkeit gerade *nicht* in dieser
Form vorsieht (z. B. bewusst nur situative, befristete Instrumente statt eines
Dauerinstruments). Liegt qualifiziertes Schweigen vor, besteht **keine planwidrige,
schliessbare Lücke**; ob dennoch eine Grundlage geschaffen werden *dürfte*, ist eine
**Würdigungsfrage (Schicht 3) → Handoff** — kein Deckungsvorschlag dieser Schicht.
Die Unterscheidung selbst ist Gap-Klassifikation, kein Zulässigkeitsurteil.

**(b) Normstufen-Check.** Eine Lücke ist nicht „keine Regel", sondern „keine Regel auf
der *nötigen* Stufe":
- Verlangt die Tätigkeit nach dem **Legalitätsprinzip** überhaupt eine Grundlage, und
  auf welcher Mindeststufe? Wichtige/grundrechtsrelevante Eingriffe brauchen ein
  **formelles Gesetz** (Bund: BV Art. 164); Untergeordnetes kann eine Verordnung oder
  eine bestehende **Delegationsnorm** decken.
- Reicht eine bestehende Grundlage/Delegation bereits aus? Dann **keine** Lücke
  (verwerfen, mit Begründung).

**Drei mögliche Ergebnisse:** *bestätigte (planwidrige) Rechtslücke* auf nötiger Stufe →
Deckungsvorschlag (Schritt 2–3) · *verworfen* (bestehende Grundlage reicht) ·
*qualifiziertes Schweigen* → Handoff an die rechtliche Würdigung, kein Deckungsvorschlag.

### 2. Erforderliche Normstufe bestimmen
Benenne die **tiefste Stufe, die das Legalitätsprinzip noch erfüllt** — nicht die
schnellste. Begründe die Zuordnung (warum Gesetz und nicht Verordnung, o. ä.).

### 3. Verfahrensweg als Fakten
Gib zur bestimmten Normstufe die *Fakten* des Zustandekommens an (siehe Tabelle) —
Organ, Referendumsart. **Keine** Dauer-/Risikobewertung.

## Normstufen & Verfahren (Fakten, keine Bewertung)

| Normstufe | Erlassendes Organ | Referendum | Abstimmung |
|---|---|---|---|
| Verfassung | Verfassungsgeber (Volk) | **obligatorisch** | findet sicher statt (Bund: Volk + Stände; kantonal: kant. Volk) |
| Gesetz | Legislative / Parlament (je Stufe) | **fakultativ** | nur falls ergriffen |
| Verordnung | Exekutive — Regierung *oder* Verwaltung | keines | — |
| Richtlinie | Verwaltung | keines | — |

Referendumsart ist ein **Fakt** der Stufe, kein Risikourteil. Die Deutung (planbar vs.
unsicher, Ablehnungsrisiko) gehört in die Risiko-Matrix.

## Ausgabe-Protokoll

### A · Bearbeitete Rechtslücken
Welche Rechtslücken aus der Kartierung übernommen wurden (Recherche-/Informationslücken
ausdrücklich ausgeschlossen).

### B · Gap-Bestätigung
Je Lücke eines von **drei** Ergebnissen, mit Begründung (gestützt auf die Kartierungs-
Abdeckung):
- **bestätigt** — planwidrige Lücke, keine hinreichende Grundlage der nötigen Stufe → Deckungsvorschlag (C).
- **verworfen** — eine bestehende Grundlage/Delegation reicht bereits (mit Beleg).
- **qualifiziertes Schweigen** — bewusste Nichtregelung; keine schliessbare Lücke. Ob
  dennoch eine Grundlage zulässig wäre → Handoff an die rechtliche Würdigung (Schicht 3),
  **kein** Deckungsvorschlag dieser Schicht.

### C · Deckungsvorschlag (nur bei bestätigter Lücke)
Je Lücke: **erforderliche Normstufe** (Legalitäts-begründet) · **zuständiges Organ** ·
**Verfahrensweg** · **Referendumsart** (Fakt). Logik-Invariante: Ein Deckungsvorschlag
existiert **nur**, wenn die Lücke bestätigt ist — keine Lücke, kein neues Gesetz.

### D · Confidence
Je Dimension (Gap-Bestätigung, Normstufen-Zuordnung) ein bis fünf Sterne mit
Ein-Satz-Begründung, abgeleitet aus der Beleglage — beratendes Signal, kein Tor.

### E · Gegenargumente & Handoffs
- Zu prüfende Hypothesen: Könnte eine bestehende Delegation doch reichen? Wurde die
  Normstufe zu hoch/zu tief angesetzt?
- **Handoffs:** Zulässigkeit → rechtliche Würdigung. Dauer/Referendumsrisiko →
  Risiko-Matrix/PMP. Alternativen → Handlungsoptionen.

## Unverrückbare Grundsätze

- **Eine Lücke braucht den Normstufen-Bezug.** „Keine Regel" genügt nicht; entscheidend
  ist „keine Regel auf der nötigen Stufe".
- **Planwidrig ≠ qualifiziertes Schweigen.** Nur eine planwidrige Lücke ruft nach
  Schliessung. Bewusste Nichtregelung wird als solche benannt und weitergereicht, nicht
  „gedeckt" — ob trotzdem eine Grundlage zulässig wäre, ist Würdigung (Schicht 3).
- **Kein Beleg aus dem Gedächtnis; belegt ≠ verifiziert-korrekt.** Wie in der Kartierung.
- **Deckungsvorschlag ⟺ bestätigte Lücke.** Nie ein neues Gesetz ohne bestätigte Lücke.
- **Fakten festhalten, nicht bewerten.** Zulässigkeit, Dauer, Risiko und Alternativen
  sind Handoffs an die dafür zuständigen Schichten.
- **Beraten, nicht entscheiden.**
