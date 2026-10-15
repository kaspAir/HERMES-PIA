"""Bestand des RAG-Korpus einer Stufe ausgeben – ausschliesslich lesend.

    python scripts/korpus_bestand.py <datenbank.db | sqlite:///…> [--modell voyage-3]

Beispiele auf dem Server (eine Stufe je Aufruf):

    python scripts/korpus_bestand.py ~/methodos-dev/data/methodos-dev.db --modell voyage-3

Öffnet die Datenbank schreibgeschützt, startet die Anwendung NICHT (keine
Migration) und ruft keinen externen Dienst auf. Ausgabe als JSON.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.domains.corpus.bestand import bestand, pfad_aus_url  # noqa: E402


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    modell = os.environ.get("VOYAGE_MODEL", "voyage-3")
    if "--modell" in argv:
        modell = argv[argv.index("--modell") + 1]
        args = [a for a in args if a != modell]
    if not args:
        print(__doc__)
        return 2
    ziel = args[0]
    pfad = pfad_aus_url(ziel) or os.path.expanduser(ziel)
    print(json.dumps(bestand(pfad, modell=modell), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
