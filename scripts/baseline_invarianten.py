"""Baseline-Lauf der Invarianten-Prüfung (Katalog Abschnitt 13).

    python scripts/baseline_invarianten.py
    python scripts/baseline_invarianten.py --db sqlite:///pfad/zur.db --csv baseline.csv

Läuft über die in HERMES PIA erzeugten PIAs (Interview-Sessions) und misst je
Regel: wie oft sie auslöst und in wie vielen Dokumenten. Das ist die
Ausgangsmessung, gegen die spätere Verbesserungen gemessen werden.

Bewusst NUR auf den eigenen PIAs: dort liegen die strukturierten Daten vor, also
laufen beide Prüfebenen. Der Altbestand ist überwiegend HERMES 5.1 – eine
Baseline darauf würde vor allem die Methodengeneration messen, nicht die
Regelgüte.

Aussagekraft (Katalog 13): Regeln, die NIE oder IMMER auslösen, sind Kandidaten
zur Überarbeitung – die einen tragen nichts bei, die anderen sind zu scharf.
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.domains.qualitaet import MUSS, VORBEHALT, HINWEIS   # noqa: E402
from app.domains.qualitaet.service import pruefe_session      # noqa: E402


def _sessions(datenbank_url):
    from app.shared.database import SessionLocal, init_engine
    from app.domains.interview.models import InterviewSession
    init_engine(datenbank_url)
    db = SessionLocal()
    return db.query(InterviewSession).order_by(InterviewSession.id).all()


def lauf(datenbank_url, csv_pfad=None):
    sessions = _sessions(datenbank_url)
    bearbeitet = [s for s in sessions
                  if len(json.loads(s.answers_json or "{}")) > 0]
    if not bearbeitet:
        print("Keine bearbeiteten PIAs in der Datenbank – nichts zu messen.")
        return 1

    treffer = Counter()          # Regel -> Anzahl Befunde insgesamt
    dokumente = Counter()        # Regel -> in wie vielen PIAs
    je_gewicht = Counter()
    alle_regeln = set()
    zeilen = []

    for s in bearbeitet:
        ergebnis = pruefe_session(s)
        alle_regeln |= set(ergebnis.geprueft)
        gesehen = set()
        for b in ergebnis.befunde:
            if b.nicht_pruefbar:
                continue
            treffer[b.regel] += 1
            je_gewicht[b.gewicht] += 1
            if b.regel not in gesehen:
                dokumente[b.regel] += 1
                gesehen.add(b.regel)
        z = ergebnis.zusammenfassung()
        zeilen.append((s.id, s.project_name or "", z["muss"], z["vorbehalt"],
                       z["hinweis"], "ja" if z["ausgabe_moeglich"] else "NEIN"))

    n = len(bearbeitet)
    print(f"Baseline über {n} bearbeitete PIA(s)\n")
    print(f"{'PIA':>4}  {'Projekt':<34} {'Muss':>5} {'Vorb':>5} {'Hinw':>5}  ausgabefähig")
    print("-" * 78)
    for sid, name, muss, vorb, hinw, ok in zeilen:
        print(f"{sid:>4}  {name[:34]:<34} {muss:>5} {vorb:>5} {hinw:>5}  {ok}")

    print(f"\nBefunde gesamt: {je_gewicht[MUSS]} Muss · {je_gewicht[VORBEHALT]} "
          f"Vorbehalt · {je_gewicht[HINWEIS]} Hinweis\n")
    print(f"{'Regel':<8} {'Befunde':>8} {'Dok':>5} {'Anteil':>7}   Beurteilung")
    print("-" * 78)
    for regel in sorted(alle_regeln):
        anz, dok = treffer[regel], dokumente[regel]
        anteil = dok / n
        if dok == 0:
            urteil = "nie ausgelöst – trägt sie etwas bei?"
        elif dok == n:
            urteil = "IMMER ausgelöst – zu scharf oder echter Systemfehler?"
        else:
            urteil = ""
        print(f"{regel:<8} {anz:>8} {dok:>5} {anteil:>6.0%}   {urteil}")

    print("\nRegeln, die nie oder immer auslösen, sind Kandidaten zur Überarbeitung "
          "(Katalog 13).")

    if csv_pfad:
        import csv
        with open(csv_pfad, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["regel", "befunde", "dokumente", "anteil"])
            for regel in sorted(alle_regeln):
                w.writerow([regel, treffer[regel], dokumente[regel],
                            f"{dokumente[regel] / n:.2f}"])
        print(f"\nCSV geschrieben: {csv_pfad}")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", default=None, help="DATABASE_URL (Vorgabe: aus der Konfiguration)")
    p.add_argument("--csv", default=None, help="Auswertung je Regel zusätzlich als CSV")
    args = p.parse_args()
    from app.config import get_config
    sys.exit(lauf(args.db or get_config().DATABASE_URL, args.csv))
