"""Seed-Ingestion: pseudonymisierte PIA-Volltexte in den geteilten Basiskorpus laden.

Aufruf (Voyage-Key muss in der Umgebung/.env gesetzt sein):
    python scripts/ingest_seed_corpus.py "<verzeichnis-mit-pseudonymisierten-txt>"

Liest alle *.txt im Verzeichnis, bettet sie ein und legt sie als GETEILTEN
Basiskorpus (org_id = NULL, für alle Mandanten sichtbar) ab. Idempotent:
bereits vorhandene Projekte werden übersprungen.
"""
import sys
from pathlib import Path

# Projekt-Root auf den Import-Pfad legen, damit 'app' gefunden wird, egal aus
# welchem Verzeichnis das Skript gestartet wird.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.factory import create_app  # noqa: E402


def _read(path):
    for enc in ("utf-8", "cp1252", "latin-1"):
        try:
            return path.read_text(encoding=enc)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def main(directory):
    app = create_app()
    rag = app.rag_service
    if not rag.available:
        print("FEHLER: VOYAGE_API_KEY ist nicht gesetzt – Ingestion abgebrochen.")
        return 1

    files = sorted(Path(directory).glob("*.txt"))
    if not files:
        print(f"Keine *.txt in {directory} gefunden.")
        return 1

    docs = chunks = skipped = 0
    with app.app_context():
        for f in files:
            text = _read(f).strip()
            if len(text) < 100:               # leere / fehlgeschlagene Pseudonymisierung
                skipped += 1
                continue
            projekt = f.stem.replace("_pseudo", "")
            n = rag.ingest_document(text, projekt=projekt, org_id=None, ergebnistyp="PIA")
            if n:
                docs += 1
                chunks += n
                print(f"  + {projekt}: {n} Chunks")
            else:
                skipped += 1
        gesamt = rag.count(org_id=None)
    print(f"\nFertig: {docs} Dokumente, {chunks} Chunks neu, {skipped} übersprungen.")
    print(f"Geteilter Basiskorpus gesamt: {gesamt} Chunks.")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Aufruf: python scripts/ingest_seed_corpus.py "<verzeichnis>"')
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
