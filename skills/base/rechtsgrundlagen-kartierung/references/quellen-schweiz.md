# Quellen Schweiz — Zugriff & Felder

Belege stammen ausschliesslich aus diesen Quellen. Der Zugriff ist werkzeug-agnostisch:
interaktiv (Browser, Cowork) oder programmatisch (API-Client, eingebettet).

## 1. lexfind.ch — Aggregator über alle Ebenen (Hauptquelle für Discovery)

Deckt Bund, alle 26 Kantone und kommunales Recht (Kategorie „Gemeindeerlass") ab und
liefert je Treffer den offiziellen Quell-Link der jeweiligen Sammlung.

**JSON-API (site-eigenes Frontend-API, undokumentiert):**
Basis: `https://www.lexfind.ch/api/frontend/v1/{de|fr|it}/…`

| Endpunkt | Zweck |
|---|---|
| `GET /categories` | Kategorien inkl. `{id:9,name:"Gemeindeerlass"}` |
| `GET /entities/extended?n_days=30` | Bund/Kantons-Entitäten (für `entity_filter`) |
| `GET /global/systematics?active_only=false` | Systematik-Baum |
| `POST /fulltext-search` | erzeugt Suche → liefert `id` |
| `GET /fulltext-search/{id}?session_id=…&page_no=1&results_per_page=20` | paginierte Treffer |

**Such-Parameter (Body von POST /fulltext-search):** `search_text`, `entity_filter[]`
(Ebenen), `category_filter[]` (Typen; Gemeindeerlass = 9), `search_in_title`,
`search_in_keywords`, `search_in_content`, `search_in_systematic_number`, `active_only`.

**Nutzbare Treffer-Felder je Erlass:**
- `systematic_number` — echte SR-/systematische Nummer (z. B. DSG `235.1`, DSV `235.11`)
- `is_active` / `info_badge` (`current`) / `version_active_since` — Aktualität
- `entity` — `{abbreviation, name}` (z. B. `CH`/Bund, `BE`/Bern) → Ebene
- `category` — `{id, name}` (Gesetz, Verordnung, Gemeindeerlass …)
- `dta_urls[].original_url` — **offizieller Quell-Link je Ebene** (fedlex.admin.ch,
  bgs.zg.ch, ar.clex.ch …)
- `title`, `keywords`, `matches[].snippet` — Titel, Stichworte, Text-Ausschnitte

**Filter zur Aktualität:** „Nur in Kraft stehendes Recht" (`active_only=true`) vermeidet
veraltete Fassungen.

**Vorbehalt:** interne API ohne publizierte Nutzungsbedingungen/Rate-Limits. Für einen
Produktivbetrieb Stabilität und Rechtliches klären, idealerweise sanktionierten Zugang
einholen. Kommunale Vollständigkeit (~2000 Gemeinden) ist nicht garantiert → fehlende
Gemeinde als Lücke markieren (in Abdeckungs-Matrix B), nicht erraten.

## 2. Fedlex — Bundesrecht, inkl. bevorstehend

- `eli/cc/…` = **Systematische Rechtssammlung** = in Kraft stehendes Bundesrecht.
- `eli/fga/…` = **Bundesblatt (Federal Gazette)** = erlassene, aber noch nicht in Kraft
  getretene Texte. Genau hier findet man „bevorstehende" Grundlagen, die (noch) nicht in
  `cc` und oft noch nicht in lexfind stehen.
- Fedlex benötigt JavaScript → interaktiv über Browser abfragen, nicht per einfachem HTTP-Get.

## 3. parlament.ch / Curia Vista — hängige Geschäfte

Geschäftsdatenbank des eidgenössischen Parlaments. Zeigt Revisionen und neue Erlasse, die
sich noch in parlamentarischer Beratung befinden (Status vor „erlassen"). Relevant, um eine
absehbare Änderung der Rechtslage als „hängig" auszuweisen.

## Ebenen → Filter (Kurzregel)

- Reines Bundesvorhaben → lexfind `entity` CH + Fedlex `cc`/`fga` + Curia.
- Kantonsbezug → zusätzlich `entity` des Kantons in lexfind.
- Gemeindebezug → zusätzlich `category_filter` 9 (Gemeindeerlass) + ggf. lokale Prüfung,
  wenn lexfind die Gemeinde nicht führt.

## Liechtenstein (noch nicht aktiv)

LR/LGBl ist eine eigene Jurisdiktion mit eigener Sammlung (nicht lexfind). Bewusst
zurückgestellt; bei Bedarf als parallele Quelle ergänzen.
