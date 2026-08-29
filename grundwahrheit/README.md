# Grundwahrheits-Fälle

Die 900 Regressionstests prüfen, ob der **Code** tut, was er soll. Sie sagen
nichts darüber, ob das **Ergebnis** stimmt. Genau dort lagen die Fehler, die in
den letzten Wochen aufgefallen sind — und sie fielen auf, weil ein Mensch ein
Dokument angeschaut hat, nicht weil etwas rot wurde.

Diese Fälle schliessen die Lücke. Jeder Fall hält ein **Sollergebnis** fest,
das von Hand bestimmt wurde: was *muss* herauskommen, unabhängig davon, was
gerade herauskommt.

## Die eine Regel

> **Sollwerte werden nicht aus einem Lauf übernommen.**

Wer den Istwert als Sollwert einträgt, zementiert den Fehler und nennt es
Prüfung. Jeder Sollwert hier ist entweder fachlich bekannt (die Überschrift von
Art. 36 BV *ist* «Einschränkungen von Grundrechten») oder logisch zwingend (ein
Auftrag ohne Ziele *muss* die Zielregel auslösen).

## Zwei Arten, aus einem Grund getrennt

| Art | Netz | Läuft |
|---|---|---|
| **offline** | nein | in der Testsuite, bei jedem Lauf |
| **online** | ja | auf Abruf, gegen die echten Quellen |

Die Trennung ist nicht Bequemlichkeit: Online-Fälle prüfen die **Welt** — ob
Fedlex noch antwortet, ob ein Kanton seine Plattform umgestellt hat, ob ein
Artikel noch dort steht. Das gehört nicht in eine Suite, die bei jedem Commit
läuft, aber es gehört geprüft. Ein Fehler dieser Art verrottet still: das
Dokument sagt weiterhin ehrlich «nicht prüfbar», und niemand fragt, warum
eigentlich immer.

## Laufen lassen

    python tools/grundwahrheit.py            # alles, mit Netz
    python tools/grundwahrheit.py --offline  # nur ohne Netz
    python tools/grundwahrheit.py --protokoll lauf.md

Rückgabewert 0 = alle Sollwerte erreicht, 1 = mindestens eine Abweichung.
