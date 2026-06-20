"""
Dokumenterzeugung: füllt die HERMES-.dotx mit Interview-Inhalten.

Strategie: .dotx Content-Type auf .docx patchen, dann mit python-docx öffnen.
Formatierung (Schriften, Farben, Kopf-/Fusszeilen, Bilder) bleibt 1:1 erhalten –
nur Textinhalt wird ersetzt.

Platzhalter im Template:
  •  (U+2022)                     → leeres Wertefeld (wird ersetzt)
  HHilfstextfarbigkursiv105ptF    → Hilfetext-Paragraph (wird gelöscht)
  HTabBeispiel85ptF               → Beispiel-Tabellenzeile (wird gelöscht)
"""
import copy
import zipfile
from io import BytesIO
from pathlib import Path

from docx import Document
from lxml import etree

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
XML_SPACE = '{http://www.w3.org/XML/1998/namespace}space'

PLACEHOLDER = '•'  # •

# Deckblatt: Paragraphen-Labels → Metadata-Keys
COVER_FIELDS = {
    'Projektname / Projektnummer': 'projektname',
    'Bearbeitungsdatum':            'datum',
    'Version':                      'version',
    'Dokument Status':              'status',
    'Klassifizierung':              'klassifizierung',
    'Autor/-in':                    'autor',
    'Projektleiter/in':             'projektleiter',
    'Auftraggeber/in':              'auftraggeber',
    'Verwaltungseinheit':           'verwaltungseinheit',
    'Geschäftsbereich':             'geschaeftsbereich',
}

STYLE_H1 = 'Hberschrift1105pt'
STYLE_H2 = 'Hberschrift2105pt'
STYLE_NORMAL = 'Normal'
STYLE_HELP = 'HHilfstextfarbigkursiv105ptF'
STYLE_EXAMPLE = 'HTabBeispiel85ptF'
STYLE_DATA = 'HTabText85pt'


class GenerationService:
    def __init__(self, method_service):
        self.methods = method_service

    def template_path(self, method_id):
        data = self.methods.get(method_id)
        return Path(data['_dir']) / data['method']['template']

    def generate(self, method_id, session_answers, metadata, changelog=None):
        """
        Füllt die .dotx-Vorlage und gibt das fertige Dokument als BytesIO zurück.

        Args:
            session_answers: {section_id: {'extracted': ..., 'raw_text': ...}}
            metadata: {'projektname': ..., 'projektleiter': ..., ...}
            changelog: list of {version, name, datum, bemerkungen} for Änderungskontrolle
        """
        template = self.template_path(method_id)
        method = self.methods.get(method_id)

        doc = self._open_template(template)

        self._fill_cover(doc, metadata)
        self._fill_headers(doc, metadata)
        self._fill_body(doc, method, session_answers)
        if changelog:
            self._fill_aenderungskontrolle(doc, changelog)
        self._delete_style(doc, STYLE_HELP)
        self._delete_style(doc, STYLE_EXAMPLE)

        buf = BytesIO()
        doc.save(buf)
        buf.seek(0)
        return buf

    # ------------------------------------------------------------------ #
    # Template öffnen (Content-Type-Patch: .dotx → .docx)                 #
    # ------------------------------------------------------------------ #

    def _open_template(self, path):
        raw = Path(path).read_bytes()
        buf_in = BytesIO(raw)
        buf_out = BytesIO()
        with zipfile.ZipFile(buf_in, 'r') as zin, \
             zipfile.ZipFile(buf_out, 'w', zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)
                if item.filename == '[Content_Types].xml':
                    data = data.replace(
                        b'wordprocessingml.template.main+xml',
                        b'wordprocessingml.document.main+xml'
                    )
                zout.writestr(item, data)
        buf_out.seek(0)
        return Document(buf_out)

    # ------------------------------------------------------------------ #
    # Deckblatt                                                            #
    # ------------------------------------------------------------------ #

    def _fill_cover(self, doc, metadata):
        # Direkt über lxml iterieren: doc.paragraphs übersieht Paragraphen
        # in Tabellen und Content-Controls (trifft Projektname nicht, aber
        # ist robuster für spätere Template-Änderungen).
        W_R   = f'{{{W}}}r'
        W_T   = f'{{{W}}}t'
        W_SDT = f'{{{W}}}sdt'
        W_SDT_PR      = f'{{{W}}}sdtPr'
        W_SDT_CONTENT = f'{{{W}}}sdtContent'
        W_SHOWING_PLH = f'{{{W}}}showingPlcHdr'

        # Jedes Feld nur einmal befüllen – "Version" kommt im Template auf
        # dem Deckblatt UND in der Änderungshistorie-Tabelle vor.
        filled: set = set()

        for p_el in doc.element.body.iter(f'{{{W}}}p'):
            # Nur direkte w:r-Kinder (nicht solche in fldSimple / w:sdt)
            direct_runs = [c for c in p_el if c.tag == W_R]
            if not direct_runs:
                continue
            label = ''.join(t.text or '' for t in direct_runs[0].iter(W_T)).strip()
            key = COVER_FIELDS.get(label)
            if not key or key in filled:
                continue
            value = metadata.get(key, '')
            if not value:
                continue

            # Prüfe ob ein w:sdt-Kindelement den Wert enthält (z.B. Version-Feld)
            sdt_children = [c for c in p_el if c.tag == W_SDT]
            if sdt_children:
                # SDT-Struktur: Wert in <w:sdtContent> schreiben, Platzhalter-Flag entfernen
                sdt = sdt_children[0]
                sdt_content = sdt.find(W_SDT_CONTENT)
                if sdt_content is not None:
                    for t in sdt_content.iter(W_T):
                        t.text = value
                        break
                sdt_pr = sdt.find(W_SDT_PR)
                if sdt_pr is not None:
                    showing = sdt_pr.find(W_SHOWING_PLH)
                    if showing is not None:
                        sdt_pr.remove(showing)
            elif len(direct_runs) >= 3:
                # Standard-Struktur: runs[0]=Label, runs[1]=Tab, runs[2]=Wert
                for t in direct_runs[2].iter(W_T):
                    t.text = value
                    break
            elif len(direct_runs) == 1:
                # Einzelner Label-Run (z.B. "Projektname / Projektnummer" in Magenta):
                # Label-Text durch Wert ersetzen und Farb-Formatierung entfernen.
                label_run = direct_runs[0]
                rPr = label_run.find(f'{{{W}}}rPr')
                if rPr is not None:
                    color_el = rPr.find(f'{{{W}}}color')
                    if color_el is not None:
                        rPr.remove(color_el)
                for t in label_run.iter(W_T):
                    t.text = value
                    if value and (value[0] == ' ' or value[-1] == ' '):
                        t.set(XML_SPACE, 'preserve')
                    break
            # len(direct_runs)==2: Label+Tab mit fldSimple-Wert (Bearbeitungsdatum) → unberührt lassen

            filled.add(key)

    # ------------------------------------------------------------------ #
    # Kopfzeilen befüllen                                                  #
    # ------------------------------------------------------------------ #

    def _fill_headers(self, doc, metadata):
        """Ersetzt 'Projektname / Projektnummer' in allen Kopfzeilen."""
        projektname = metadata.get('projektname', '')
        if not projektname:
            return
        W_T = f'{{{W}}}t'
        placeholder = 'Projektname / Projektnummer'
        for section in doc.sections:
            for t_el in section.header._element.iter(W_T):
                if (t_el.text or '').strip() == placeholder:
                    t_el.text = projektname
                    if projektname[0] == ' ' or projektname[-1] == ' ':
                        t_el.set(XML_SPACE, 'preserve')

    # ------------------------------------------------------------------ #
    # Abschnitte (Fliesstext + Tabellen)                                  #
    # ------------------------------------------------------------------ #

    def _fill_body(self, doc, method, session_answers):
        sections = {s['id']: s for s in method.get('sections', [])}
        body = doc.element.body
        children = list(body)
        current_sid = None

        for i, el in enumerate(children):
            tag = _tag(el)
            if tag == 'p':
                style = _p_style(el)
                if style in (STYLE_H1, STYLE_H2):
                    heading = _p_text(el).strip()
                    current_sid = self._match_section(heading, sections)
            elif tag == 'tbl':
                if current_sid and current_sid in session_answers:
                    sect = sections[current_sid]
                    if sect.get('type') == 'table':
                        extracted = session_answers[current_sid].get('extracted') or []
                        self._fill_table(el, sect, extracted)
                    current_sid = None
            elif tag == 'sdt':
                current_sid = None

        # Freitext-Abschnitte: Normal-Paragraph mit • unter dem Heading
        for i, el in enumerate(children):
            if _tag(el) != 'p':
                continue
            if _p_style(el) not in (STYLE_H1, STYLE_H2):
                continue
            heading = _p_text(el).strip()
            sid = self._match_section(heading, sections)
            if not sid or sid not in session_answers:
                continue
            sect = sections[sid]
            if sect.get('type') != 'free_text':
                continue
            text = (session_answers[sid].get('extracted') or {}).get('text') \
                   or session_answers[sid].get('raw_text', '')
            # Nächsten Normal-Paragraph suchen
            for j in range(i + 1, min(i + 6, len(children))):
                if _tag(children[j]) == 'p' and _p_style(children[j]) == STYLE_NORMAL:
                    _set_p_text(children[j], text)
                    break
                if _tag(children[j]) in (STYLE_H1, STYLE_H2, 'tbl'):
                    break

    def _match_section(self, heading, sections):
        # Umlaut-tolerant vergleichen: Vorlage schreibt "Abkürzungen",
        # die method.yaml transkribiert als "Abkuerzungen" (ASCII).
        h = _normalize(heading)
        for sid, sect in sections.items():
            title = _normalize(sect.get('title', ''))
            if title and (h == title or h.endswith(title) or title in h):
                return sid
        return None

    # ------------------------------------------------------------------ #
    # Tabellen befüllen                                                    #
    # ------------------------------------------------------------------ #

    def _fill_table(self, tbl_el, section, data_rows):
        if not data_rows:
            return

        has_nr = any(c.get('id') == 'nr' for c in section.get('columns', []))
        columns = [c['id'] for c in section.get('columns', []) if c.get('id') != 'nr']
        col_defs = {c['id']: c for c in section.get('columns', [])}

        W_TR = f'{{{W}}}tr'
        W_TC = f'{{{W}}}tc'
        W_SDT = f'{{{W}}}sdt'
        W_SDT_CONTENT = f'{{{W}}}sdtContent'
        W_SDT_PR = f'{{{W}}}sdtPr'
        W_SHOWING_PLH = f'{{{W}}}showingPlcHdr'

        # Alle Vorlage-Datenzeilen (HTabText85pt) sammeln. Manche Tabellen
        # liefern mehrere mit – z.B. Ergebnisse (8 Beispielzeilen) oder
        # Personalaufwand (AG + PL). Die erste dient als Klonvorlage, ALLE
        # werden am Ende entfernt – sonst bleiben Geisterzeilen stehen.
        template_rows = [
            row for row in tbl_el
            if row.tag == W_TR and _row_style(row) == STYLE_DATA
        ]
        if not template_rows:
            return

        template_row = template_rows[0]
        insert_pos = list(tbl_el).index(template_row)

        for idx, data in enumerate(data_rows):
            new_row = copy.deepcopy(template_row)
            data = dict(data) if isinstance(data, dict) else {}

            # Computed fields vorberechnen (z.B. risikozahl = ew * ag)
            for col in section.get('columns', []):
                cid = col.get('id', '')
                expr = col.get('computed', '')
                if expr and not data.get(cid):
                    parts = [p.strip() for p in expr.split('*')]
                    try:
                        result = 1
                        for p in parts:
                            result *= int(data.get(p) or 0)
                        data[cid] = str(result) if result else ''
                    except (ValueError, TypeError):
                        pass

            # Alle Zellen in Reihenfolge sammeln – inkl. SDT-umhüllter Zellen
            # (Dropdown-/Combobox-Spalten liegen als <w:sdt><w:sdtContent><w:tc> vor)
            all_cells = []
            for child in new_row:
                if child.tag == W_TC:
                    all_cells.append(child)
                elif child.tag == W_SDT:
                    sdt_pr = child.find(W_SDT_PR)
                    sdt_content = child.find(W_SDT_CONTENT)
                    if sdt_content is not None:
                        tc = sdt_content.find(W_TC)
                        if tc is not None:
                            if sdt_pr is not None:
                                showing = sdt_pr.find(W_SHOWING_PLH)
                                if showing is not None:
                                    sdt_pr.remove(showing)
                            all_cells.append(tc)

            # Erste Spalte: Nummer (nur wenn Nr-Spalte im Schema vorhanden)
            start_idx = 0
            if has_nr and all_cells:
                _set_tc_text(all_cells[0], f'{idx + 1:02d}')
                start_idx = 1

            # Datenspalten in Reihenfolge
            for col_offset, col_id in enumerate(columns):
                cell_idx = col_offset + start_idx
                if cell_idx < len(all_cells):
                    val = data.get(col_id, '')
                    _set_tc_text(all_cells[cell_idx], str(val) if val else '')

            tbl_el.insert(insert_pos + idx, new_row)

        # Alle originalen Vorlage-Datenzeilen entfernen (nicht nur die erste)
        for row in template_rows:
            tbl_el.remove(row)

    # ------------------------------------------------------------------ #
    # Änderungskontrolle (Kapitel 8)                                       #
    # ------------------------------------------------------------------ #

    def _fill_aenderungskontrolle(self, doc, changelog):
        """
        Schreibt den Changelog in die Tabelle unter 'Änderungskontrolle'.
        Erwartet: changelog = [{version, name, datum, bemerkungen}, ...]
        """
        if not changelog:
            return

        W_TR = f'{{{W}}}tr'
        W_TC = f'{{{W}}}tc'
        W_SDT = f'{{{W}}}sdt'
        W_SDT_CONTENT = f'{{{W}}}sdtContent'

        body = doc.element.body
        children = list(body)

        # Kapitel 8-Überschrift und direkt folgende Tabelle finden
        target_tbl = None
        in_akk = False
        for el in children:
            if _tag(el) == 'p':
                txt = _p_text(el).strip()
                if 'nderungskontrolle' in txt or 'nderungsprotokoll' in txt:
                    in_akk = True
                    continue
                if in_akk and _p_style(el) in (STYLE_H1, STYLE_H2):
                    in_akk = False
            elif _tag(el) == 'tbl' and in_akk:
                target_tbl = el
                break

        if target_tbl is None:
            return

        # Template-Datenzeilen suchen (HTabText85pt). Erste = Klonvorlage,
        # alle werden am Ende entfernt (die Vorlage liefert eine Leerzeile mit).
        template_rows = [
            row for row in target_tbl
            if row.tag == W_TR and _row_style(row) == STYLE_DATA
        ]
        if not template_rows:
            return

        template_row = template_rows[0]
        insert_pos = list(target_tbl).index(template_row)
        col_keys = ['version', 'name', 'datum', 'bemerkungen']

        for idx, entry in enumerate(changelog):
            new_row = copy.deepcopy(template_row)
            all_cells = []
            for child in new_row:
                if child.tag == W_TC:
                    all_cells.append(child)
                elif child.tag == W_SDT:
                    sdt_content = child.find(W_SDT_CONTENT)
                    if sdt_content is not None:
                        tc = sdt_content.find(W_TC)
                        if tc is not None:
                            all_cells.append(tc)
            for j, key in enumerate(col_keys):
                if j < len(all_cells):
                    _set_tc_text(all_cells[j], entry.get(key, ''))
            target_tbl.insert(insert_pos + idx, new_row)

        # Alle originalen Vorlage-Datenzeilen entfernen
        for row in template_rows:
            target_tbl.remove(row)

    # ------------------------------------------------------------------ #
    # Hilfe-/Beispieltexte löschen                                        #
    # ------------------------------------------------------------------ #

    def _delete_style(self, doc, style_id):
        body = doc.element.body
        W_TR = f'{{{W}}}tr'
        W_TC = f'{{{W}}}tc'

        # Loose paragraphs
        for el in list(body):
            if _tag(el) == 'p' and _p_style(el) == style_id:
                body.remove(el)

        # Tabellenzeilen
        for tbl in body.iter(f'{{{W}}}tbl'):
            for row in list(tbl):
                if row.tag == W_TR and _row_style(row) == style_id:
                    tbl.remove(row)


# ------------------------------------------------------------------ #
# XML-Hilfsfunktionen                                                  #
# ------------------------------------------------------------------ #

def _normalize(s):
    """Kleinschreibung + Umlaut-Transkription für robusten Titelvergleich."""
    s = (s or '').lower().strip()
    for a, b in (('ä', 'ae'), ('ö', 'oe'), ('ü', 'ue'), ('ß', 'ss')):
        s = s.replace(a, b)
    return s


def _tag(el):
    return el.tag.split('}')[-1] if '}' in el.tag else el.tag


def _p_style(p_el):
    pPr = p_el.find(f'{{{W}}}pPr')
    if pPr is None:
        return 'Normal'
    ps = pPr.find(f'{{{W}}}pStyle')
    return ps.get(f'{{{W}}}val', 'Normal') if ps is not None else 'Normal'


def _p_text(p_el):
    return ''.join(t.text or '' for t in p_el.iter(f'{{{W}}}t'))


def _set_p_text(p_el, text):
    """Ersetzt den Textinhalt eines Paragraphen, erhält Stil."""
    for r in list(p_el):
        if r.tag == f'{{{W}}}r':
            p_el.remove(r)
    r = etree.SubElement(p_el, f'{{{W}}}r')
    t = etree.SubElement(r, f'{{{W}}}t')
    t.text = text
    if text and (text[0] == ' ' or text[-1] == ' '):
        t.set(XML_SPACE, 'preserve')


def _row_style(row_el):
    W_TC = f'{{{W}}}tc'
    first_tc = next((c for c in row_el if c.tag == W_TC), None)
    if first_tc is None:
        return 'Normal'
    first_p = first_tc.find(f'{{{W}}}p')
    return _p_style(first_p) if first_p is not None else 'Normal'


def _set_tc_text(tc_el, text):
    p = tc_el.find(f'{{{W}}}p')
    if p is None:
        return
    _set_p_text(p, text)
