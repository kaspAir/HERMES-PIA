---
name: rechtsgrundlagen-kartierung
description: >-
  Systematische Kartierung der für ein Schweizer Verwaltungs- oder Projektvorhaben
  relevanten Rechtsgrundlagen über alle Staatsebenen (Bund via Fedlex/lexfind,
  Kantone, Gemeinden). Findet bestehende und bevorstehende Erlasse, belegt jede
  Fundstelle mit Quelle und Aktualität, markiert fehlende Grundlagen ehrlich und
  liefert ein nachvollziehbares Audit-Protokoll (Auslöser, Abdeckung, Confidence,
  Gegenargumente). Nutze diesen Skill immer, wenn es um eine Rechtsgrundlagenanalyse,
  das Auffinden der einschlägigen Gesetze/Verordnungen für ein Projekt, ein
  HERMES-Initialisierungsergebnis oder die Frage "auf welcher gesetzlichen Grundlage
  dürfen wir das" geht — auch wenn der Begriff "Rechtsgrundlagenanalyse" nicht
  ausdrücklich fällt. Grundsatz: beraten und belegen, nicht entscheiden.
scope: base
version: "1.0"
owner: kaspAIr
applies_to: rechtsgrundlagenanalyse
---

# Rechtsgrundlagen-Kartierung (Schweiz)

Diese Methode beantwortet **eine** Frage und beantwortet sie gründlich:

> **Welche Rechtsgrundlagen sind für dieses Vorhaben einschlägig — über alle
> Staatsebenen hinweg — und welche davon bestehen bereits, welche sind erst
> bevorstehend, und wo scheint gar keine zu existieren?**

Das Auffinden ist der eigentliche Aufwand: Eine spätere Lückenanalyse ist nur so
gut wie die Vollständigkeit dieser Karte. Darum steht hier Sorgfalt vor Tempo.

Der Wert der Methode liegt nicht darin, möglichst selbstsicher zu klingen, sondern
darin, **nachvollziehbar** zu sein: Der Nutzer soll sehen, *warum* gesucht wurde,
*wo* gesucht wurde, *wie belastbar* der Befund ist und *was übersehen worden sein
könnte*. Eine ehrlich markierte Lücke ist mehr wert als eine erfundene Fundstelle.

## Was diese Methode NICHT tut (bewusste Abgrenzung)

Jedes Ergebnis, das über das Auffinden hinausgeht, ist Interpretation und gehört in
ein anderes Dokument. Diese Trennung hält die Analyse schlank und faktentreu:

- **Datenschutz und Informationssicherheit** → Schutzbedarfsanalyse, nicht hier.
- **Fehlt eine Grundlage? (Gap-Analyse)**, **wäre die Massnahme zulässig? (rechtliche
  Würdigung)** und **welche rechtmässigen Alternativen? (Handlungsoptionen)** sind je
  **eigene, nachgelagerte Schichten.** Diese Karte beantwortet nur die *erste* Frage —
  welche Grundlagen bestehen — und *identifiziert* Lücken, füllt und würdigt sie aber
  nicht. Diese vier Ebenen zu vermischen ist der gefährlichste Fehler: Er verbindet
  Belegtes, Auslegung und Empfehlung zu einem scheinbar homogenen Text, in dem der
  Leser die Grenzen nicht mehr erkennt.
- **Termin- oder Risikobewertung** → Risiko-Matrix / Projektmanagementplan.
- **Kosten und Aufwand** → Projektmanagementplan.

Wenn beim Arbeiten etwas aus diesen Bereichen auffällt, wird es als **Hinweis für
das zuständige Dokument** notiert, nicht ausgearbeitet.

## Ablauf

### 1. Ebenen eingrenzen
Kläre zuerst, welche Staatsebenen überhaupt betroffen sind: Bund, Kanton (welcher),
Gemeinde (welche), international. Das begrenzt den Suchraum erheblich — ein reines
Bundesvorhaben muss die kommunale Ebene nicht durchsuchen. Halte fest, *warum* eine
Ebene ein- oder ausgeschlossen wird.

### 2. Rechtsauslösende Merkmale erheben
Klopfe das Vorhaben auf die Merkmale ab, die einen *gesetzlichen Auftrag* auslösen.
Es geht nicht um Querschnitts-Compliance, sondern um die Frage: *Für welche geplante
Tätigkeit braucht es überhaupt eine gesetzliche Grundlage?* Prüfe u. a.:

- Wird eine **hoheitliche Tätigkeit / ein Verwaltungshandeln** ausgeübt, das eine
  gesetzliche Grundlage voraussetzt (Legalitätsprinzip)?
- **Beschaffung** von Leistungen/Software?
- **Subventionen / Finanzhilfen**?
- Führen eines **Registers / einer amtlichen Datensammlung**?
- **Gebühren / Abgaben**?
- Bezug zu einem **Fachbereich** mit eigener Spezialgesetzgebung (Gesundheit,
  Bildung, Bau/Raumplanung, Soziales, Steuern, Verkehr, Umwelt, Migration …)?
- Umsetzung eines **internationalen Standards / Staatsvertrags**?
- Einsatz eines **KI-Systems** oder anderer neu regulierter Technologie?

Diese Liste ist ein Ausgangspunkt, keine Schranke — ergänze, was das konkrete
Vorhaben nahelegt, und begründe jede Ergänzung.

### 3. Discovery über alle Ebenen
Suche zu jedem ausgelösten Merkmal die einschlägigen Erlasse in den Quellen (unten).
Notiere pro Quelle, ob und was gesucht wurde — diese Abdeckung ist später die
Grundlage des negativen Befunds und der Confidence.

Für Vollständigkeit *innerhalb* der Disziplin, ohne in Bewertung zu kippen:
- Zu jedem Gesetz die **Ausführungserlasse** mitprüfen (z. B. die Verordnung zur RPG,
  nicht nur die RPG selbst).
- **Querschnitts-Grundlagen** nicht vergessen: Öffentlichkeitsprinzip, Archivierung,
  Verwaltungsverfahren, elektronische Signatur/Identität.
- Das **Verhältnis zu bereits bestehenden Systemen/Plattformen** erfassen, soweit es
  eine Grundlage berührt (z. B. eine schon betriebene Fachplattform).
- Je Erlass den **Geltungsbereich/die Anwendbarkeit als Fakt** festhalten (gilt direkt
  für wen; nur Referenzcharakter für wen) — das ist Sachverhalt, keine Würdigung.

### 4. Status zuordnen
Ordne jede gefundene Grundlage einem Status zu:

- **In Kraft** — bestehende Grundlage (Fedlex `cc` / lexfind).
- **Bevorstehend** — erlassen, aber noch nicht in Kraft (Fedlex Bundesblatt `fga`);
  mit Inkrafttretens-Datum.
- **Hängig** — Revision in parlamentarischer Beratung (Curia Vista).
- **Keine gefunden** — hier ist **strikt zu unterscheiden**, welche Art von Lücke
  vorliegt (das ist der häufigste Methodenfehler):
  - **Rechtslücke** — trotz *hinreichender* Discovery wurde für eine Tätigkeit keine
    Grundlage gefunden → die einzige Lücke, die an die **Gap-Analyse** geht.
  - **Recherchelücke** — eine erforderliche Quelle/Ebene wurde *nicht geprüft* (jedes
    ✗ in der Abdeckungs-Matrix) → **keine** Rechtslücke; wird durch weitere Recherche
    geschlossen, nicht an die Gap-Analyse übergeben.
  - **Informationslücke** — eine Projektangabe fehlt (z. B. die betroffene Gemeinde)
    → **Rückfrage an die Projektleitung.**
  Nicht geprüft, nicht verifiziert und nicht vorhanden sind drei verschiedene Dinge.

### 5. Selbstkritik
Bevor du abschliesst, dreh die Perspektive um (siehe Ausgabe-Teil E). Das ist kein
Schmuck, sondern der Kern des beratenden Auftrags.

## Quellen (Schweiz)

Für die Details siehe `references/quellen-schweiz.md` (Endpunkte, Filter, Felder).
Kurzüberblick:

| Ebene | Quelle | Deckt |
|---|---|---|
| Bund + alle 26 Kantone + Gemeindeerlasse | **lexfind.ch** (JSON-API `/api/frontend/v1/`) | geltendes Recht aller Ebenen, mit offiziellem Quell-Link je Kanton |
| Bund | **Fedlex** (`cc` = in Kraft, `fga` = Bundesblatt/bevorstehend) | Bundesrecht inkl. noch nicht in Kraft getretener Erlasse |
| Bund (hängig) | **parlament.ch / Curia Vista** | Geschäfte in parlamentarischer Beratung |

Der Zugriff ist bewusst **werkzeug-agnostisch** beschrieben: Ob die Abfrage
interaktiv über einen Browser (Cowork) oder programmatisch über einen API-Client
(eingebettet in eine Applikation) läuft, ändert die Methode nicht — nur die
Fundstellen-Belege müssen aus einer dieser Quellen stammen.

## Ausgabe-Protokoll

Gib das Ergebnis als nachvollziehbares Protokoll aus — in genau diesen Abschnitten:

### A · Auslöser
Zeige, welche Merkmale die Suche ausgelöst haben — **auch die nicht zutreffenden**,
damit die Projektleitung eine Fehleinschätzung sofort erkennt:
```
☑ Beschaffung   ☑ Subvention   ☑ Fachbereich: Bau
☐ Register      ☐ KI-System    ☐ Internationaler Standard
```

### B · Gesucht in
Eine Abdeckungs-Matrix je Ebene. Sie macht den negativen Befund ehrlich: Ein ✗ sagt
klar, wo *nicht* verlässlich gesucht werden konnte.
```
Fedlex (Bund)          ✓
Bundesblatt (fga)      ✓
Curia Vista            ✓
lexfind Kanton BE      ✓
Gemeinde X (Reglement) ✗   nicht maschinell auffindbar → lokal prüfen
```

### C · Befunde
Je gefundene Grundlage: Titel (Abkürzung) · Ebene/Entität · Kategorie ·
SR-/systematische Nummer · Quell-Link · Status (in Kraft seit / bevorstehend ab /
hängig) · **Geltungsbereich/Anwendbarkeit** (gilt direkt für wen / nur Referenz) ·
kurze Relevanz-Begründung (welcher Auslöser).

Lücken **getrennt nach Art** ausweisen (siehe Ablauf 4) — niemals vermischt:
- **Rechtslücken** → betroffene Tätigkeit · warum ungedeckt · Übergabe an Gap-Analyse.
- **Recherchelücken** → welche Quelle/Ebene offen ist (Spiegel der ✗ aus Teil B).
- **Informationslücken** → welche Projektangabe fehlt (Rückfrage an die PL).

### D · Confidence
Eine abgeleitete Einschätzung — **nicht aus dem Bauch, sondern als Ablesung von B**
und der Belegqualität. Je Dimension ein bis fünf Sterne mit Ein-Satz-Begründung.
Das ist ein beratendes Signal, kein Pass/Fail-Urteil.
```
Discovery   ★★★★☆   Bund vollständig; Gemeinde X nicht maschinell verifizierbar
```
Ein ✗ in der Abdeckung deckelt die zugehörige Confidence — Vollständigkeit, die
nicht belegt ist, darf nicht als hoch ausgewiesen werden.

### E · Gegenargumente & alternative Lesarten
Die wertvollste Selbstprüfung. Stell dir aktiv die unbequemen Fragen und gib sie als
**zu prüfende Hypothesen** aus, niemals als behauptete Fundstellen:
- Welche Rechtsgrundlage könnte ich übersehen haben (anderer Fachbereich, andere
  Ebene, anderes Stichwort)?
- Wäre eine andere Auslegung des Vorhabens möglich, die andere Erlasse einschlägig
  macht?
- Abschluss: **offene Fragen an die Projektleitung.**

## Unverrückbare Grundsätze

Diese wenigen Punkte sind der Grund, warum man dem Ergebnis trauen kann — sie stehen
über Vollständigkeitsdruck:

- **Kein Beleg aus dem Gedächtnis.** Eine SR-Nummer, ein Link, ein Inkrafttretens-
  Datum wird nur ausgegeben, wenn es aus einer echten Quellabfrage stammt. Andernfalls:
  Feld leer und als „zu verifizieren" markieren. Erfundene Fundstellen sind der
  schlimmste mögliche Fehler dieser Methode, weil sie falsche Sicherheit erzeugen.
- **Ein negativer Befund ist eine Vermutung, keine Gewissheit.** „Keine Grundlage
  gefunden" heisst „in den abgesuchten Quellen nicht gefunden" — begrenzt durch die
  Abdeckung in B. Und **eine nicht geprüfte Quelle ist nie eine Rechtslücke**, sondern
  eine Recherchelücke (Ablauf 4).
- **Belegt heisst nicht verifiziert-korrekt.** Ein Treffer kann eine falsche Status-
  oder Datumsangabe enthalten; auditierbare Falschinformation bleibt Falschinformation.
  Ein Status („in Kraft seit", „totalrevidiert") muss dem *tatsächlichen Erlasstext*
  entnehmbar sein — stammt er nur aus einem Index/einer Sekundärquelle, kennzeichnen.
  Diese Methode reduziert Halluzination, ersetzt aber nicht die inhaltliche Validierung
  der Treffer.
- **Fakten festhalten, nicht bewerten.** Termin-, Risiko-, Kosten- und
  Normstufen-Interpretationen sind Handoffs an andere Dokumente.
- **Beraten, nicht entscheiden.** Die Methode legt Befunde und Zweifel offen; die
  Entscheidung trifft der Mensch.
