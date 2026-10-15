"""Einen Testlauf ohne Browser ausführen – derselbe Dienst wie der Knopf.

    python tools/testlauf_ausfuehren.py --wie-lauf <id>          # Ausgangslage eines früheren Laufs
    python tools/testlauf_ausfuehren.py --org <id> --datei <ausgangslage.txt> --name <Projektname>

Läuft auf der Stufe (gleiche Konfiguration wie die Anwendung). Der Lauf ist
danach in der Oberfläche sichtbar wie jeder andere Testlauf; das Interview
unter «Interview ansehen». Kein Ersatz für eine fachliche Prüfung.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--wie-lauf", type=int)
    p.add_argument("--org", type=int)
    p.add_argument("--datei")
    p.add_argument("--name", default="Testlauf (Kommandozeile)")
    p.add_argument("--projektleiter", default="Kim Muster")
    p.add_argument("--auftraggeber", default="Robin Beispiel")
    a = p.parse_args(argv)

    from app.factory import create_app
    app = create_app()
    dienst = app.testlauf_service
    if dienst is None:
        print("Testlauf ist auf dieser Stufe nicht eingeschaltet (TESTLAUF).")
        return 2
    with app.app_context():
        if a.wie_lauf:
            alt = dienst.hole(a.wie_lauf)
            org, ausgangslage, ebene, kanton = alt.org_id, alt.ausgangslage, alt.ebene, alt.kanton
            name = f"{a.name} – wie Lauf {a.wie_lauf}"
        else:
            org, ausgangslage, ebene, kanton = a.org, Path(a.datei).read_text(encoding="utf-8"), None, None
            name = a.name
        lauf = dienst.starte(org_id=org, ausgangslage=ausgangslage, projektname=name,
                             projektleiter=a.projektleiter, auftraggeber=a.auftraggeber,
                             ebene=ebene, kanton=kanton)
        print(f"Testlauf {lauf.id}, Session {lauf.session_id}, Projekt {lauf.projekt_id}", flush=True)
        gesehen = 0
        while True:
            z = dienst.schritt(lauf.id)
            for e in z["protokoll"][gesehen:]:
                print(f"[{e['schritt']}] {e['text']}", flush=True)
            gesehen = len(z["protokoll"])
            if z["fertig"]:
                print(f"Status: {z['status']}", flush=True)
                return 0 if z["status"] == "fertig" else 1


if __name__ == "__main__":
    sys.exit(main())
