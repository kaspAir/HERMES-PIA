# -*- coding: utf-8 -*-
"""Laeufer fuer die Grundwahrheits-Faelle — mit Protokoll als Nachweis.

Die Regressionstests pruefen den Code. Diese Faelle pruefen das ERGEBNIS: was
muss herauskommen, unabhaengig davon, was gerade herauskommt.

Zwei Arten, aus einem Grund getrennt:

* **offline** — kein Netz. Laeuft in der Testsuite bei jedem Lauf mit.
* **online**  — fragt die amtlichen Sammlungen. Prueft die Verbindung zur
  Welt: antwortet Fedlex noch, hat ein Kanton seine Plattform umgestellt,
  steht der Artikel noch dort. Solche Fehler verrotten still — das Dokument
  sagt weiterhin ehrlich «nicht pruefbar», und niemand fragt, warum immer.

Rueckgabewert 0 = alle Sollwerte erreicht, 1 = mindestens eine Abweichung.
"""
import argparse
import io
import os
import sys
from datetime import datetime

WURZEL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WURZEL)

import yaml   # noqa: E402

FAELLE = os.path.join(WURZEL, "grundwahrheit", "faelle")


class Abweichung(Exception):
    """Ein Sollwert wurde nicht erreicht — mit dem Grund im Text."""


# ---- Die Pruefarten -------------------------------------------------------- #

def _pruefe_invarianten(fall):
    """Schlaegt die Invariantenpruefung an, wenn sie soll?"""
    from app.domains.qualitaet.pruefung import pruefe

    ergebnis = pruefe(fall.get("eingabe") or {})
    gemeldet = {b.regel for b in ergebnis.befunde if not b.nicht_pruefbar}
    erwartet = fall.get("erwartet") or {}
    fehlt = [r for r in (erwartet.get("muss_melden") or []) if r not in gemeldet]
    zuviel = [r for r in (erwartet.get("darf_nicht_melden") or []) if r in gemeldet]
    if fehlt:
        raise Abweichung(f"nicht gemeldet: {', '.join(fehlt)}")
    if zuviel:
        raise Abweichung(f"faelschlich gemeldet: {', '.join(zuviel)}")
    return f"{len(gemeldet)} Befund(e), Sollwerte erreicht"


def _pruefe_fundstelle(fall):
    """Existiert der Artikel, und heisst er, wie wir behaupten?"""
    from app.domains.rechtsquellen.artikel import ArtikelPruefer

    pruefer = ArtikelPruefer(aktiv=True)
    zustand, kopf = pruefer.pruefe(fall["quelle"], str(fall["artikel"]))
    erwartet = fall.get("erwartet") or {}

    if zustand != erwartet.get("zustand"):
        raise Abweichung(f"Zustand «{zustand}» statt «{erwartet.get('zustand')}»")
    soll_kopf = (erwartet.get("ueberschrift") or "").strip()
    if soll_kopf and soll_kopf.lower() not in (kopf or "").lower():
        raise Abweichung(f"Ueberschrift «{kopf[:70]}» enthaelt «{soll_kopf}» nicht")
    soll_sprache = (erwartet.get("sprachfassung") or "").strip()
    if soll_sprache:
        ist = ArtikelPruefer.sprachfassung(fall["quelle"])
        if ist != soll_sprache:
            raise Abweichung(f"Sprachfassung «{ist}» statt «{soll_sprache}»")
    return (kopf[:60] or zustand)


PRUEFARTEN = {"invarianten": _pruefe_invarianten, "fundstellen": _pruefe_fundstelle}


# ---- Laufen ---------------------------------------------------------------- #

def lade_dateien(nur_art=None):
    for name in sorted(os.listdir(FAELLE)):
        if not name.endswith((".yaml", ".yml")):
            continue
        pfad = os.path.join(FAELLE, name)
        daten = yaml.safe_load(io.open(pfad, encoding="utf-8")) or {}
        if nur_art and daten.get("art") != nur_art:
            continue
        yield os.path.splitext(name)[0], daten


def laufe(nur_art=None):
    """(Zeilen fuers Protokoll, Anzahl Abweichungen)."""
    zeilen, abweichungen, geprueft = [], 0, 0
    for schluessel, daten in lade_dateien(nur_art):
        pruefart = PRUEFARTEN.get(schluessel)
        zeilen.append(("kopf", f"{daten.get('titel', schluessel)} "
                               f"({daten.get('art', '?')})"))
        if pruefart is None:
            zeilen.append(("warnung", f"keine Pruefart fuer «{schluessel}»"))
            continue
        for fall in daten.get("faelle") or []:
            geprueft += 1
            try:
                auskunft = pruefart(fall)
                zeilen.append(("ok", f"{fall['name']} — {auskunft}"))
            except Abweichung as e:
                abweichungen += 1
                zeilen.append(("abweichung", f"{fall['name']} — {e}"))
            except Exception as e:              # noqa: BLE001
                abweichungen += 1
                zeilen.append(("fehler",
                               f"{fall['name']} — {e.__class__.__name__}: {e}"))
    return zeilen, abweichungen, geprueft


ZEICHEN = {"ok": "  ok  ", "abweichung": " ABW  ", "fehler": " FEHL ",
           "warnung": " warn "}


def main():
    p = argparse.ArgumentParser(description="Grundwahrheits-Faelle pruefen")
    p.add_argument("--offline", action="store_true",
                   help="nur Faelle ohne Netz")
    p.add_argument("--protokoll", help="Protokoll zusaetzlich in diese Datei")
    args = p.parse_args()

    zeilen, abweichungen, geprueft = laufe("offline" if args.offline else None)

    aus = [f"# Grundwahrheit — Lauf vom {datetime.now():%d.%m.%Y %H:%M}", ""]
    for art, text in zeilen:
        aus.append("" if art == "kopf" else "")
        aus.append(f"## {text}" if art == "kopf" else f"{ZEICHEN[art]} {text}")
    aus.append("")
    aus.append(f"{geprueft} Faelle geprueft, {abweichungen} Abweichung(en).")
    bericht = "\n".join(z for z in aus if z is not None)
    print(bericht)
    if args.protokoll:
        io.open(args.protokoll, "w", encoding="utf-8").write(bericht + "\n")
    return 1 if abweichungen else 0


if __name__ == "__main__":
    sys.exit(main())
