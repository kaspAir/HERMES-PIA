#!/usr/bin/env python3
"""
tools/mnemosyne/pseudonymize.py

Mnemosyne-Prototyp Schritt 1: Pseudonymisiert PIAs lokal (offline).
Kein Cloud-API-Aufruf – nur spaCy (NER) + Regex.

Verwendung:
    python tools/mnemosyne/pseudonymize.py \
        --input  C:/Pfad/zu/echten/pias \
        --output C:/Pfad/zu/output

Ausgabe:
    <output>/                     Pseudonymisierte .txt-Dateien
    <output>/mapping.json         Originalname → Pseudonym (PRIVAT, nie ins Repo!)

Voraussetzungen:
    pip install -r tools/mnemosyne/requirements.txt
    python -m spacy download de_core_news_lg
"""
import argparse
import json
import re
import sys
from pathlib import Path

SUPPORTED_EXTENSIONS = {'.docx', '.pdf'}

# Pseudonym-Präfixe pro spaCy-Entitätstyp
_PREFIXES = {
    'PER':  'Person',
    'ORG':  'Org',
    'LOC':  'Ort',
    'MISC': 'Entitaet',
}

# Regex für strukturierte sensible Daten (Phase 2 der Bereinigung)
_REGEX_PATTERNS = [
    (re.compile(r'\b[\w.+\-]+@[\w\-]+\.[a-zA-Z]{2,}\b'),                          'EMAIL'),
    (re.compile(r'\b(?:\+41|0041|0)[ .\-]?\d{2}[ .\-]?\d{3}[ .\-]?\d{2}[ .\-]?\d{2}\b'), 'TELEFON'),
    (re.compile(r'\bCH\d{2}[ \-]?\d{4}[ \-]?\d{4}[ \-]?\d{4}[ \-]?\d{4}[ \-]?\d\b'), 'IBAN'),
]


def _load_mapping(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding='utf-8'))
    return {'entities': {}, 'counters': {}}


def _save_mapping(path: Path, mapping: dict):
    path.write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding='utf-8')


def _get_pseudonym(original: str, entity_type: str, mapping: dict) -> str:
    """Liefert ein stabiles Pseudonym für eine Entität (konsistent über alle Dokumente)."""
    key = f"{entity_type}:{original.strip()}"
    if key not in mapping['entities']:
        prefix = _PREFIXES.get(entity_type, 'Entitaet')
        counter = mapping['counters'].get(prefix, 0) + 1
        mapping['counters'][prefix] = counter
        mapping['entities'][key] = f"[{prefix}_{counter:03d}]"
    return mapping['entities'][key]


def pseudonymize_text(text: str, nlp, mapping: dict) -> str:
    """
    Zweistufige Bereinigung:
      1. spaCy NER  – PER, ORG, LOC, MISC
      2. Regex      – E-Mails, Telefon, IBAN
    """
    # Phase 1: NER
    doc = nlp(text)
    # Von hinten nach vorne ersetzen, damit Char-Offsets gültig bleiben
    spans = sorted(doc.ents, key=lambda e: e.start_char, reverse=True)
    chars = list(text)
    for ent in spans:
        if ent.label_ in _PREFIXES:
            pseudo = _get_pseudonym(ent.text, ent.label_, mapping)
            chars[ent.start_char:ent.end_char] = list(pseudo)
    text = ''.join(chars)

    # Phase 2: Regex-Patterns
    for pattern, label in _REGEX_PATTERNS:
        def _replace(m, _label=label):
            original = m.group(0)
            return _get_pseudonym(original, f'REGEX_{_label}', mapping)
        text = pattern.sub(_replace, text)

    return text


def _extract_text_docx(path: Path) -> str:
    from docx import Document
    doc = Document(str(path))
    lines = []
    for para in doc.paragraphs:
        t = para.text.strip()
        if t:
            lines.append(t)
    return '\n'.join(lines)


def _extract_text_pdf(path: Path) -> str:
    import pdfplumber
    pages = []
    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                pages.append(t)
    return '\n\n'.join(pages)


def process_file(source: Path, output_dir: Path, nlp, mapping: dict) -> Path:
    ext = source.suffix.lower()
    if ext == '.docx':
        text = _extract_text_docx(source)
    elif ext == '.pdf':
        text = _extract_text_pdf(source)
    else:
        raise ValueError(f"Nicht unterstütztes Format: {ext}")

    pseudonymized = pseudonymize_text(text, nlp, mapping)
    out_path = output_dir / (source.stem + '_pseudo.txt')
    out_path.write_text(pseudonymized, encoding='utf-8')
    return out_path


def main():
    parser = argparse.ArgumentParser(
        description='Mnemosyne: Offline-Pseudonymisierung von PIAs (.docx / .pdf)'
    )
    parser.add_argument('--input',  required=True, help='Ordner mit Original-PIAs')
    parser.add_argument('--output', required=True, help='Ausgabe-Ordner (wird erstellt)')
    parser.add_argument('--model',  default='de_core_news_lg', help='spaCy-Modell')
    args = parser.parse_args()

    input_dir  = Path(args.input)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    mapping_path = output_dir / 'mapping.json'

    print(f"[Mnemosyne] Lade spaCy-Modell '{args.model}' …")
    try:
        import spacy
        nlp = spacy.load(args.model)
    except OSError:
        print(f"\n  Modell '{args.model}' nicht gefunden. Bitte ausführen:")
        print(f"  python -m spacy download {args.model}")
        sys.exit(1)

    mapping = _load_mapping(mapping_path)
    files   = sorted(f for f in input_dir.iterdir()
                     if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS)

    if not files:
        print(f"[Mnemosyne] Keine .docx/.pdf-Dateien gefunden in {input_dir}")
        sys.exit(0)

    print(f"[Mnemosyne] {len(files)} Dateien gefunden – starte Pseudonymisierung …\n")

    ok_count = err_count = 0
    for i, f in enumerate(files, 1):
        print(f"  [{i:3d}/{len(files)}] {f.name} … ", end='', flush=True)
        try:
            out = process_file(f, output_dir, nlp, mapping)
            print(f"OK  → {out.name}")
            ok_count += 1
        except Exception as exc:
            print(f"FEHLER: {exc}")
            err_count += 1

    _save_mapping(mapping_path, mapping)

    n_entities = len(mapping['entities'])
    print(f"\n[Mnemosyne] Fertig: {ok_count} OK, {err_count} Fehler")
    print(f"  Pseudonymisierte Entitäten: {n_entities}")
    print(f"  Mapping-Datei:  {mapping_path}")
    print()
    print("  *** SICHERHEITSHINWEIS ***")
    print("  mapping.json enthält die Originalbezeichnungen – nie ins Repo!")
    print("  Die Datei ist in .gitignore ausgeschlossen.")


if __name__ == '__main__':
    main()
