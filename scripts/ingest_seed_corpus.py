"""Seed-Ingestion: pseudonymisierte PIA-Volltexte in den geteilten Basiskorpus laden.

Aufruf (PSEUDO_BASIS_URL muss gesetzt und der Dienst erreichbar sein):
    python scripts/ingest_seed_corpus.py "<verzeichnis>" [--ersetzen] [--trotzdem]

Liest alle *.txt im Verzeichnis, bettet sie ein und legt sie als GETEILTEN
Basiskorpus (org_id = NULL, für alle Mandanten sichtbar) ab. Idempotent:
bereits vorhandene Projekte werden übersprungen. `--ersetzen` leert den geteilten
Korpus vorher – nötig, wenn ein neuer Pseudonymisierungslauf den alten ablöst.

**Klarnamen-Sperre.** Der Korpus speichert den Chunk-TEXT im Klartext; nur die
Einbettung läuft durch die Pseudonymisierungsschicht. Ein im Text verbliebener
Personenname landet also in der Datenbank und kann über die RAG-Suche in ein
neues Projektdokument gelangen. Deshalb prüft dieses Skript vorher auf typische
Restmuster und bricht ab. `--trotzdem` übergeht die Sperre bewusst.
"""
import re
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


# Abkürzungen, die wie "Initial + Nachname" aussehen, aber keine sind.
_KEINE_NAMEN = {
    "Mio", "Mrd", "St", "Nr", "Nrn", "Abs", "Art", "Ziff", "ca", "z", "vgl", "Vgl",
    "bzw", "Bzw", "inkl", "exkl", "Fr", "CHF", "Chf", "Kap", "Pos", "Tel", "Bsp",
    "evtl", "Evtl", "resp", "max", "min", "Std", "Anh", "Bst", "Lit", "Tab", "Abb",
    "ggf", "Ggf", "usw", "Usw", "div", "Div", "bez", "Bez", "reg", "sog", "Sog",
    "Pkt", "Ref", "Akt", "Anf", "Anz", "Arch", "Def", "Dig", "Erw", "Ext", "Hd",
    "Hrg", "Bern", "Dlg", "Jan", "Feb", "Mrz", "Apr", "Jun", "Jul", "Aug", "Sep",
    "Okt", "Nov", "Dez",
}
# "Chr. Dürr", "N. Ehrenreich" – abgekürzter Vorname plus Nachname. Genau die
# Form, die ohne Anrede-Anker durch die Erkennung fällt.
_REST_NAME = re.compile(r"\b([A-ZÄÖÜ][a-zäöü]{0,3})\. ([A-ZÄÖÜ][a-zäöüß]{3,})\b")


def _klarnamen_verdacht(text):
    """Restverdächtige Namensstellen eines Dokuments.

    Gegen Fehlalarme aus Aufzählungen ('B. Betrieb', 'A. Anhang'): Wörter, die im
    selben Dokument auch kleingeschrieben vorkommen, sind Gattungswörter und keine
    Nachnamen. Ein Nachname taucht praktisch nie in Kleinschreibung auf.
    """
    text = text or ""
    klein = {w.lower() for w in re.findall(r"\b[a-zäöüß]{4,}\b", text)}
    treffer = set()
    for m in _REST_NAME.finditer(text):
        initial, nachname = m.group(1), m.group(2)
        if initial in _KEINE_NAMEN or nachname.lower() in klein:
            continue
        # Häufigster Fehlalarm: das 'B.' aus 'z. B.' und das 'a.' aus 'u. a.' –
        # danach folgt ein ganz gewöhnliches Substantiv, kein Nachname.
        davor = text[max(0, m.start() - 4):m.start()].strip().lower()
        if davor.endswith(("z.", "u.", "d.", "i.", "s.")):
            continue
        treffer.add(m.group(0))
    return treffer


def main(directory, ersetzen=False, trotzdem=False):
    app = create_app()
    rag = app.rag_service
    if not rag.available:
        print("FEHLER: PSEUDO_BASIS_URL ist nicht gesetzt – ohne die "
              "Pseudonymisierungsschicht wird nichts eingebettet.")
        return 1

    files = sorted(Path(directory).glob("*.txt"))
    if not files:
        print(f"Keine *.txt in {directory} gefunden.")
        return 1

    # ---- Klarnamen-Sperre VOR jedem Schreibzugriff ----------------------- #
    verdacht = {}
    for f in files:
        treffer = _klarnamen_verdacht(_read(f))
        if treffer:
            verdacht[f.name] = sorted(treffer)
    if verdacht:
        gesamt = sum(len(v) for v in verdacht.values())
        print(f"\nKLARNAMEN-VERDACHT: {gesamt} Stelle(n) in {len(verdacht)} Datei(en).")
        for name, treffer in list(verdacht.items())[:10]:
            print(f"  {name}: {', '.join(treffer[:6])}"
                  + (" …" if len(treffer) > 6 else ""))
        if len(verdacht) > 10:
            print(f"  … und {len(verdacht) - 10} weitere Dateien.")
        if not trotzdem:
            print("\nAbbruch. Der Chunk-Text wird im Klartext gespeichert und kann "
                  "über die RAG-Suche in ein neues Dokument gelangen.\n"
                  "Erst erneut pseudonymisieren – oder bewusst mit --trotzdem "
                  "übergehen.")
            return 2
        print("\n--trotzdem gesetzt: Ingestion läuft trotz Verdacht weiter.\n")

    if ersetzen:
        from app.domains.corpus.models import CorpusChunk
        from app.shared.database import SessionLocal
        db = SessionLocal()
        weg = db.query(CorpusChunk).filter(CorpusChunk.org_id.is_(None)).delete()
        db.commit()
        print(f"Geteilter Basiskorpus geleert: {weg} Chunks entfernt.")

    docs = chunks = skipped = 0
    with app.app_context():
        for f in files:
            text = _read(f).strip()
            if len(text) < 100:               # leere / fehlgeschlagene Pseudonymisierung
                skipped += 1
                continue
            projekt = f.stem.replace("_pseudo", "")
            # Strukturierte Initialisierungs-Dauer (Wochen) je Seed erfassen, damit sie
            # neuen Projekten als Vergleichswert dient (beratender Dauer-Vorschlag).
            from app.domains.interview.service import _parse_dauer_wochen
            dauer = _parse_dauer_wochen(text)
            n = rag.ingest_document(text, projekt=projekt, org_id=None, ergebnistyp="PIA",
                                    init_dauer_wochen=round(dauer) if dauer else None)
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
    argumente = [a for a in sys.argv[1:] if not a.startswith("--")]
    schalter = {a for a in sys.argv[1:] if a.startswith("--")}
    if not argumente:
        print('Aufruf: python scripts/ingest_seed_corpus.py "<verzeichnis>" '
              '[--ersetzen] [--trotzdem]')
        sys.exit(2)
    sys.exit(main(argumente[0],
                  ersetzen="--ersetzen" in schalter,
                  trotzdem="--trotzdem" in schalter))
