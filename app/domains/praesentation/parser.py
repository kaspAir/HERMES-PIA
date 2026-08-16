"""Liest einen (ggf. extern nachbearbeiteten) PIA im .docx-Format strukturiert ein.

Grundlage für die Präsentation ist bewusst die HOCHGELADENE Datei, nicht die
Interview-Daten: der freigabebereite PIA kann in Word weiterbearbeitet worden
sein, und genau dieser Stand wird dem Auftraggeber präsentiert.

Robustheit:
* Abschnitte werden über die bekannten PIA-Überschriften erkannt (umlaut- und
  stiltolerant), Tabellen dem jeweils aktuellen Abschnitt zugeordnet.
* Zelltexte werden per XPath (.//w:t) gelesen — so ist auch der Inhalt von
  SDT-Dropdown-Zellen (z.B. EW/AG bei Risiken) sichtbar, den python-docx'
  cell.text verschluckt.
"""
import io
import re

import docx
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

_W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _norm(text):
    t = (text or "").strip().lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("é", "e"), ("è", "e"), ("–", "-")):
        t = t.replace(a, b)
    return re.sub(r"\s+", " ", t)


# Überschrift (normalisiert, Präfix-Match) -> Abschnittsschlüssel; None = ignorieren.
_SECTION_PREFIXES = [
    ("ausgangslage", "ausgangslage"),
    ("ziele", "ziele"),
    ("rahmenbedingungen", "rahmenbedingungen"),
    ("personalaufwand", "personalaufwand"),
    ("sachmittel", "sachmittel"),
    ("kosten", "kosten"),
    ("ergebnisse und termine", "termine"),
    ("termine", "termine"),
    ("projektorganisation", "projektorganisation"),
    ("kommunikation", "kommunikation"),
    ("risiken", "risiken"),
    ("einleitung", None),
    ("ziel und zweck", None),
    # Frueher ignoriert. Die Rechtsgrundlagenanalyse speist ihre ersten
    # Kapitel daraus - wer nur den PIA hochlaedt, haette sie sonst leer.
    ("referenzierte dokumente", "referenzierte_dokumente"),
    ("mitgeltende unterlagen", "mitgeltende_unterlagen"),
    # Frueher ignoriert. Jedes HERMES-Dokument des Projekts fuehrt diese
    # Kapitel gleich; wer nur den PIA hochlaedt, haette sie sonst leer.
    ("definitionen", "definitionen"),
    ("vorgaben", "vorgaben_methoden"),
    ("ressourcenbedarf", None),          # Zwischentitel; die Untertitel folgen
    ("dokument-protokoll", "_ende"),
    ("aenderungskontrolle", "_ende"),
    ("nachweis", "_ende"),
]


def _heading_key(paragraph):
    """Abschnittsschlüssel, wenn der Absatz eine bekannte PIA-Überschrift ist."""
    text = _norm(paragraph.text)
    if not text or len(text) > 60:
        return False, None
    style = (paragraph.style.name or "").lower() if paragraph.style else ""
    is_heading_style = "heading" in style or "berschrift" in style or "titel" in style
    for prefix, key in _SECTION_PREFIXES:
        if text == prefix or (is_heading_style and text.startswith(prefix)):
            return True, key
    return False, None


def _cell_text(cell):
    """Zelltext inkl. SDT-Inhalten (Dropdowns), die cell.text nicht liefert."""
    texts = [t.text or "" for t in cell._tc.iter(f"{_W_NS}t")]
    return re.sub(r"\s+", " ", "".join(texts)).strip()


def _table_rows(table):
    """Tabelle -> Liste von Zeilen (Liste der Zelltexte, Duplikate durch
    verbundene Zellen entfernt)."""
    rows = []
    for row in table.rows:
        seen, cells = set(), []
        for cell in row.cells:
            if id(cell._tc) in seen:      # verbundene Zellen nur einmal
                continue
            seen.add(id(cell._tc))
            cells.append(_cell_text(cell))
        rows.append(cells)
    return rows


def _iter_blocks(document):
    for child in document.element.body.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, document)
        elif child.tag == qn("w:tbl"):
            yield Table(child, document)


def _header_index(header_cells, *needles):
    """Index der ersten Spalte, deren Kopf eine der Suchwörter enthält."""
    for i, h in enumerate(header_cells):
        hn = _norm(h)
        if any(n in hn for n in needles):
            return i
    return None


def _num(value):
    m = re.search(r"\d[\d'’.\s]*", str(value or ""))
    if not m:
        return None
    digits = re.sub(r"[^\d]", "", m.group())
    return int(digits) if digits else None


def parse_pia(docx_bytes):
    """PIA-.docx -> strukturierte Inhalte für die Präsentation."""
    document = docx.Document(io.BytesIO(docx_bytes))

    meta = {}
    sections_text = {}
    sections_table = {}
    current = None
    ended = False

    for block in _iter_blocks(document):
        if ended:
            break
        if isinstance(block, Paragraph):
            is_heading, key = _heading_key(block)
            if is_heading:
                if key == "_ende":
                    ended = True
                else:
                    current = key
                continue
            text = block.text.strip()
            if text and current:
                sections_text.setdefault(current, []).append(text)
            elif text and current is None and "\t" in text:
                # Titelseite der offiziellen Vorlage: Metadaten als
                # Tab-getrennte Absätze («Verwaltungseinheit⇥Demoamt»).
                label, _, wert = text.partition("\t")
                if label.strip() and wert.strip():
                    meta[_norm(label)] = wert.strip()
        else:  # Tabelle
            rows = _table_rows(block)
            if current is None:
                # Kopftabelle (Label | Wert) vor der ersten Überschrift.
                for cells in rows:
                    if len(cells) >= 2 and cells[0]:
                        meta[_norm(cells[0])] = cells[1]
            elif current not in sections_table:
                sections_table[current] = rows

    result = {
        "projektname": _meta_value(meta, "projektname") or _title_fallback(document),
        "projektleiter": _meta_value(meta, "projektleiter"),
        "auftraggeber": _meta_value(meta, "auftraggeber"),
        "verwaltungseinheit": _meta_value(meta, "verwaltungseinheit"),
        "geschaeftsbereich": _meta_value(meta, "geschaeftsbereich"),
        "version": _meta_value(meta, "version"),
        "ausgangslage": "\n".join(sections_text.get("ausgangslage", [])),
        "ziele": _parse_ziele(sections_table.get("ziele")),
        "termine": _parse_termine(sections_table.get("termine")),
        "personalaufwand": _parse_personal(sections_table.get("personalaufwand")),
        "kosten": _parse_kosten(sections_table.get("kosten")),
        "risiken": _parse_risiken(sections_table.get("risiken")),
        "enddatum": "\n".join(sections_text.get("termine", [])),
        # Ab hier für die ABGELEITETEN Ergebnisse, nicht für die Präsentation.
        # Die Rahmenbedingungen trugen im gemessenen Fall das Entscheidende –
        # sie wurden gelesen, aber nicht zurückgegeben.
        "rahmenbedingungen": (sections_table.get("rahmenbedingungen")
                              or sections_text.get("rahmenbedingungen") or []),
        "referenzierte_dokumente": _parse_spalten(
            sections_table.get("referenzierte_dokumente"),
            (("nr", "nr"), ("name", "name"), ("link", "nummer", "link"))),
        "definitionen": _parse_spalten(
            sections_table.get("definitionen"),
            (("abkuerzung", "abkuerzung", "abk"), ("bedeutung", "bedeutung"))),
        "vorgaben_methoden": _parse_spalten(
            sections_table.get("vorgaben_methoden"),
            (("titel", "titel"), ("vorgabe", "vorgabe", "methode", "werkzeug"),
             ("version", "version"))),
        "mitgeltende_unterlagen": _parse_spalten(
            sections_table.get("mitgeltende_unterlagen"),
            (("name", "name"), ("link", "nummer", "link"))),
        "projektorganisation": sections_table.get("projektorganisation") or [],
        "kommunikation": sections_table.get("kommunikation") or [],
        "sachmittel": sections_table.get("sachmittel") or [],
    }
    return result


def _meta_value(meta, needle):
    for k, v in meta.items():
        if needle in k and v:
            return v.strip()
    return None


def _title_fallback(document):
    """Projektname aus den ersten Absätzen (Zeile nach dem Dokumenttitel).
    Überschriften zählen nicht – findet sich nichts, greift der Aufrufer auf den
    Projektnamen aus der Datenbank zurück."""
    for p in document.paragraphs[:6]:
        text = p.text.strip()
        if not text or _norm(text) == "projektinitialisierungsauftrag":
            continue
        if _heading_key(p)[0]:
            return ""
        return text
    return ""


def _parse_ziele(rows):
    if not rows or len(rows) < 2:
        return []
    out = []
    for cells in rows[1:]:
        if not cells:
            continue
        # Verbundene/SDT-Zellen verschieben Spalten -> längste Zelle = Beschreibung.
        candidates = cells[1:] if len(cells) > 1 else cells
        beschreibung = max(candidates, key=len, default="").strip()
        if beschreibung:
            out.append({"beschreibung": beschreibung})
    return out


def _parse_termine(rows):
    if not rows or len(rows) < 2:
        return []
    header = rows[0]
    i_erg = _header_index(header, "ergebnis", "lieferergebnis")
    i_termin = _header_index(header, "termin")
    # "abnahme durch" zuerst: die Ergebnis-Spalte heisst "(abnahmerelevant)" und
    # wuerde bei blossem "abnahme" faelschlich matchen.
    i_abnahme = _header_index(header, "abnahme durch", "rolle")
    if i_abnahme is None:
        i_abnahme = _header_index(header, "abnahme")
    if i_abnahme == i_erg:
        i_abnahme = None
    out = []
    for cells in rows[1:]:
        def _get(i):
            return cells[i].strip() if i is not None and i < len(cells) else ""
        ergebnis = _get(i_erg)
        if ergebnis:
            out.append({"ergebnis": ergebnis, "termin": _get(i_termin),
                        "abnahme": _get(i_abnahme)})
    return out


def _parse_spalten(rows, spalten):
    """Rohe Tabellenzeilen als Woerterbuecher – Kopfzeile raus, Spalten benannt.

    Die Vorlagen liefern hier LISTEN von Zelltexten, inklusive Kopfzeile. Wer
    sie unveraendert weiterreicht, bekommt spaeter leere Tabellen: die
    Erzeugung erwartet Woerterbuecher und verwirft alles andere still.

    ``spalten``: ((spalten_id, suchwort, ...), ...) – das Suchwort wird im
    Kopftext gesucht, damit abweichende Beschriftungen nicht zum Verlust
    fuehren. Findet sich keine Spalte, wird nach POSITION zugeordnet.
    """
    if not rows or len(rows) < 2:
        return []
    header = rows[0]
    positionen = {}
    for pos, eintrag in enumerate(spalten):
        spalten_id, suchworte = eintrag[0], eintrag[1:]
        i = _header_index(header, *suchworte) if suchworte else None
        positionen[spalten_id] = pos if i is None else i
    out = []
    for cells in rows[1:]:
        zeile = {}
        for spalten_id, i in positionen.items():
            zeile[spalten_id] = cells[i].strip() if i < len(cells) else ""
        if any(zeile.values()):
            out.append(zeile)
    return out


def _parse_personal(rows):
    if not rows or len(rows) < 2:
        return []
    header = rows[0]
    i_rolle = _header_index(header, "rolle")
    i_name = _header_index(header, "name")
    i_aufwand = _header_index(header, "aufwand")
    out = []
    for cells in rows[1:]:
        def _get(i):
            return cells[i].strip() if i is not None and i < len(cells) else ""
        rolle = _get(i_rolle)
        aufwand = _num(_get(i_aufwand))
        if rolle:
            out.append({"rolle": rolle, "name": _get(i_name), "aufwand": aufwand})
    return out


def _parse_kosten(rows):
    if not rows or len(rows) < 2:
        return []
    out = []
    for cells in rows[1:]:
        if len(cells) < 2 or not cells[0].strip():
            continue
        out.append({"position": cells[0].strip(), "betrag": _num(cells[1])})
    return out


_STUFEN = {"tief": 1, "gering": 1, "niedrig": 1, "mittel": 2, "hoch": 3}

# Risikozahl -> plausible (EW, AG)-Position, falls EW/AG-Zellen leer sind.
_RISIKOZAHL_POS = {9: (3, 3), 6: (2, 3), 4: (2, 2), 3: (1, 3), 2: (1, 2), 1: (1, 1)}


def _parse_risiken(rows):
    if not rows or len(rows) < 2:
        return []
    header = rows[0]
    i_beschr = _header_index(header, "beschreibung", "risiko")
    i_ew = _header_index(header, "eintritt")
    i_ag = _header_index(header, "auswirkung")
    i_zahl = _header_index(header, "risikozahl")
    i_massn = _header_index(header, "massnahme")
    out = []
    for nr, cells in enumerate(rows[1:], 1):
        def _get(i):
            return cells[i].strip() if i is not None and i < len(cells) else ""

        if len(cells) == len(header):
            beschreibung = _get(i_beschr)
            ew = _STUFEN.get(_norm(_get(i_ew)))
            ag = _STUFEN.get(_norm(_get(i_ag)))
            zahl = _num(_get(i_zahl))
            massnahmen = _get(i_massn)
        else:
            # Datenzeile kürzer als der Kopf (leere SDT-Dropdown-Zellen verschieben
            # die Spalten) -> Felder inhaltlich statt über Indizes bestimmen.
            beschreibung = max(cells[1:] if len(cells) > 1 else cells, key=len, default="").strip()
            stufen = [_STUFEN[_norm(c)] for c in cells if _norm(c) in _STUFEN]
            ew = stufen[0] if len(stufen) > 0 else None
            ag = stufen[1] if len(stufen) > 1 else None
            # Risikozahl = einstellige Zahl (1-9); cells[0] ist die Nr.-Spalte ("01").
            zahl = next((int(c) for c in (c.strip() for c in cells[1:])
                         if c.isdigit() and len(c) == 1), None)
            laenger = sorted((c for c in cells if c.strip()), key=len)
            massnahmen = laenger[-2].strip() if len(laenger) >= 2 else ""
        if not beschreibung:
            continue
        if (ew is None or ag is None) and zahl in _RISIKOZAHL_POS:
            ew, ag = _RISIKOZAHL_POS[zahl]
        out.append({"nr": nr, "beschreibung": beschreibung,
                    "ew": ew, "ag": ag, "massnahmen": massnahmen})
    return out
