"""Synthetischen Erfahrungskorpus in den Korpus einer Stufe laden – getrennt vom Bestand.

    python scripts/ingest_synthetischer_korpus.py --trocken
    python scripts/ingest_synthetischer_korpus.py --ausfuehren [--max-tokens 50000]

- Quelle: tools/korpus_synthetisch.py (erfundene Vorhaben, keine realen Daten).
- Getrennt vom Bestand: eigene Korpusversion «synthetisch-<Datum>», Kennzeichen
  «extern freigegeben», Methodenversion samt Herkunft. Bestehende Chunks werden
  weder gelöscht noch verändert; Dubletten (gleicher Text) werden übersprungen.
- Kosten: der Trockenlauf schätzt die Tokens ohne einen Aufruf; der Lauf bricht
  ab, bevor die geschätzte Menge --max-tokens überschreitet, und meldet am Ende
  die vom Dienst gemeldeten Tokens.
- Nutzt den konfigurierten Embedding-Weg der Anwendung (Schutzschicht oder
  ausdrücklich direkt). Ohne Weg bricht das Skript ab, statt etwas anzunehmen.
"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _tokens_geschaetzt(text):
    # Vorsichtig: eher zu viele als zu wenige (≈ 3 Zeichen je Token im Deutschen).
    return len(text) // 3 + 1


def main(argv):
    from tools.korpus_synthetisch import DOKUMENTE, HERKUNFT, METHODENVERSION
    trocken = "--trocken" in argv or "--ausfuehren" not in argv
    max_tokens = int(argv[argv.index("--max-tokens") + 1]) if "--max-tokens" in argv else 50000
    schaetzung = sum(_tokens_geschaetzt(d["text"]) for d in DOKUMENTE)
    print(f"{len(DOKUMENTE)} synthetische Dokumente, geschätzt {schaetzung} Tokens "
          f"(Grenze {max_tokens}).")
    if schaetzung > max_tokens:
        print("Abbruch: die Schätzung überschreitet die Grenze.")
        return 3
    if trocken:
        print("Trockenlauf – nichts geladen, kein Dienst aufgerufen. Laden mit --ausfuehren.")
        return 0

    from app.factory import create_app
    app = create_app()
    rag = app.rag_service
    if rag is None or not rag.available:
        print("Abbruch: kein Embedding-Weg konfiguriert "
              f"({app.datenwege['embeddings'].get('grund', '')}).")
        return 2
    version = f"synthetisch-{date.today():%Y-%m-%d}"
    print(f"Embedding-Weg: {rag.embedder.modus}, Modell {rag.embedder.model}, "
          f"Korpusversion {version}")
    neu = 0
    with app.app_context():
        for d in DOKUMENTE:
            n = rag.ingest_document(d["text"], projekt=d["projekt"], org_id=None,
                                    ergebnistyp="PIA", methodenversion=METHODENVERSION,
                                    methodenversion_herkunft=HERKUNFT,
                                    korpus_version=version, extern_freigegeben=True)
            print(f"  {'+' if n else '='} {d['projekt']}: {n} Chunks")
            neu += n
    print(f"Fertig: {neu} Chunks neu. Vom Dienst gemeldete Tokens: {rag.embedder.tokens}.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
