"""Word-Ausgabe der beiden Freigabe-Dokumente.

Zwei Dokumente, zwei verschiedene Arten zu füllen – und der Unterschied ist
fachlich, nicht technisch:

**Die Checkliste** ist eine Momentaufnahme. Ihre Tabellen bekommen genau die
Zeilen, die bewertet wurden; die Beispielzeilen der Vorlage verschwinden. Wie
beim Projektinitialisierungsauftrag.

**Die Liste Projektentscheide Steuerung** ist ein Register, das über das ganze
Projekt läuft. Die Vorlage druckt die HERMES-Entscheide vor – heute die
Projektinitialisierungsfreigabe, später weiteres Vorgehen und
Durchführungsfreigabe. Diese Zeilen bleiben stehen; eingetragen wird nur das
Datum des Entscheids, der wirklich gefallen ist. Wer die künftigen Zeilen
löschte, machte aus dem Register eine Quittung.

Was in beiden gilt: **Platzhalter der Vorlage verschwinden.** «tt.mm.jjjj» in
einer Zeile, über die noch nicht entschieden wurde, ist keine Information,
sondern ein unausgefülltes Formularfeld im fertigen Dokument.
"""
import re
from io import BytesIO
from pathlib import Path

from app.domains.generation.service import (
    STYLE_DATA, STYLE_H1, STYLE_H2, W, _p_style, _p_text, _row_cells,
    _set_tc_text, _tag, _tc_text,
)

VORLAGEN = Path(__file__).resolve().parents[3] / "methods" / "freigabe" / "template"
CHECKLISTE_VORLAGE = VORLAGEN / "checkliste_projektinitialisierungsfreigabe.docx"
ENTSCHEIDE_VORLAGE = VORLAGEN / "liste_projektentscheide_steuerung.docx"

# Platzhalter, die die Vorlage mitbringt und die im fertigen Dokument nichts
# verloren haben. Der erste ist ein Datum, der zweite eine Auslassung.
_PLATZHALTER = re.compile(r"^(tt\.mm\.jjjj|…|\.\.\.|#)$")

W_TR = f"{{{W}}}tr"


def _tabelle_nach(doc, ueberschrift):
    """Die erste Tabelle unter einer Überschrift – oder None.

    Gesucht wird über den Text der Überschrift, nicht über eine Position:
    Vorlagen verschieben Kapitel, sie benennen sie selten um.
    """
    gesucht = ueberschrift.strip().lower()
    treffer = False
    for el in doc.element.body:
        if _tag(el) == "p":
            if _p_style(el) in (STYLE_H1, STYLE_H2):
                treffer = _p_text(el).strip().lower() == gesucht
        elif _tag(el) == "tbl" and treffer:
            return el
    return None


def _datenzeilen(tbl_el):
    """Zeilen im Datenstil – die Vorlage markiert sie so."""
    return [r for r in tbl_el if r.tag == W_TR and _p_style_of_row(r) == STYLE_DATA]


def _p_style_of_row(row_el):
    for zelle in _row_cells(row_el):
        p = zelle.find(f"{{{W}}}p")
        if p is not None:
            return _p_style(p)
    return ""


def _spaltenzuordnung(tbl_el, spalten):
    """Kopftext → Spaltenschlüssel. Ohne Kopfzeile keine Zuordnung."""
    zeilen = [r for r in tbl_el if r.tag == W_TR]
    if not zeilen:
        return {}
    kopf = [_tc_text(c).strip().lower() for c in _row_cells(zeilen[0])]
    zuordnung = {}
    for pos, text in enumerate(kopf):
        for schluessel, beschriftung in spalten.items():
            if schluessel in zuordnung.values():
                continue
            b = beschriftung.strip().lower()
            if text and (text == b or b in text or text in b):
                zuordnung[pos] = schluessel
                break
    return zuordnung


def _schreibe_zeilen(tbl_el, zeilen, spalten):
    """Ersetzt die Vorlage-Datenzeilen durch die übergebenen Werte."""
    import copy

    vorlage_zeilen = _datenzeilen(tbl_el)
    if not vorlage_zeilen:
        return False
    muster = vorlage_zeilen[0]
    zuordnung = _spaltenzuordnung(tbl_el, spalten)
    if not zuordnung:
        return False
    einfuege_pos = list(tbl_el).index(muster)

    for i, daten in enumerate(zeilen):
        neu = copy.deepcopy(muster)
        zellen = _row_cells(neu)
        for pos, schluessel in zuordnung.items():
            if pos < len(zellen):
                _set_tc_text(zellen[pos], str(daten.get(schluessel, "") or ""))
        tbl_el.insert(einfuege_pos + i, neu)
    for zeile in vorlage_zeilen:
        tbl_el.remove(zeile)
    return True


def _tilge_platzhalter(tbl_el):
    """Leert Zellen, die nur einen Vorlage-Platzhalter enthalten."""
    for zeile in tbl_el:
        if zeile.tag != W_TR:
            continue
        for zelle in _row_cells(zeile):
            if _PLATZHALTER.match(_tc_text(zelle).strip()):
                _set_tc_text(zelle, "")


def _oeffne(pfad):
    from docx import Document

    if not Path(pfad).exists():
        raise FileNotFoundError(f"Vorlage fehlt: {pfad}")
    return Document(str(pfad))


def _speichere(doc):
    puffer = BytesIO()
    doc.save(puffer)
    puffer.seek(0)
    return puffer


# ---- Checkliste Projektinitialisierungsfreigabe --------------------------- #

_CHECK_SPALTEN = {
    "nr": "Nr.",
    "pruefpunkt": "Prüfpunkt",
    "kriterium": "Kriterium",
    "bewertung": "Bewertung",
    "erlaeuterung": "Erläuterung",
    "verantwortlich": "Verantwortlich",
    "datum": "Datum",
}

_CHECK_KAPITEL = (
    ("generell", "Generelle Prüfpunkte"),
    ("organisation", "Organisationsspezifische Prüfpunkte"),
    ("projekt", "Projektspezifische Prüfpunkte"),
)


def checkliste_docx(zeilen, kopf=None):
    """Die ausgefüllte Checkliste als Word-Dokument.

    ``zeilen``: {"generell": [...], "organisation": [...], "projekt": [...]}
    ``kopf``: optionale Angaben für Verantwortlich/Datum, wo die Zeile sie
    nicht selbst trägt – etwa die freigebende Person und das Freigabedatum.
    """
    doc = _oeffne(CHECKLISTE_VORLAGE)
    kopf = kopf or {}
    for schluessel, ueberschrift in _CHECK_KAPITEL:
        tbl = _tabelle_nach(doc, ueberschrift)
        if tbl is None:
            continue
        daten = []
        for z in (zeilen or {}).get(schluessel) or []:
            if not isinstance(z, dict):
                continue
            eintrag = dict(z)
            # Verantwortlich und Datum stehen an der Zeile, wenn jemand sie
            # gesetzt hat; sonst tragen sie die Freigabe – wer bewertet hat
            # und wann. Erfunden wird nichts.
            eintrag.setdefault("verantwortlich", "")
            eintrag.setdefault("datum", "")
            if not eintrag["verantwortlich"]:
                eintrag["verantwortlich"] = kopf.get("verantwortlich", "")
            if not eintrag["datum"]:
                eintrag["datum"] = kopf.get("datum", "")
            daten.append(eintrag)
        if daten:
            _schreibe_zeilen(tbl, daten, _CHECK_SPALTEN)
        _tilge_platzhalter(tbl)
    return _speichere(doc)


# ---- Liste Projektentscheide Steuerung ------------------------------------ #

_ENTSCHEID_SPALTEN = {
    "nr": "Nr.",
    "entscheid": "Entscheid",
    "grundlagen": "Zugrundeliegende Dokumente",
    "entscheidungstraeger": "Entscheidungsträger",
    "entscheidungsdatum": "Entscheidungsdatum",
}


def entscheide_docx(entscheide):
    """Das Register mit den gefallenen Entscheiden.

    Die vorgedruckten Zeilen der Vorlage bleiben stehen – sie sind der
    Fahrplan der HERMES-Entscheide über das ganze Projekt. Eingetragen wird
    das Datum bei der Zeile, deren Nummer zu einem erfassten Entscheid passt.
    """
    doc = _oeffne(ENTSCHEIDE_VORLAGE)
    tbl = _tabelle_nach(doc, "Projektentscheide Steuerung")
    if tbl is None:
        return _speichere(doc)

    nach_nr = {}
    for e in entscheide or []:
        nummer = str(getattr(e, "nr", "") or "").strip().lstrip("0") or "0"
        nach_nr[nummer] = e

    zuordnung = _spaltenzuordnung(tbl, _ENTSCHEID_SPALTEN)
    umgekehrt = {schluessel: pos for pos, schluessel in zuordnung.items()}
    nr_pos = umgekehrt.get("nr")
    datum_pos = umgekehrt.get("entscheidungsdatum")
    traeger_pos = umgekehrt.get("entscheidungstraeger")

    for zeile in tbl:
        if zeile.tag != W_TR:
            continue
        zellen = _row_cells(zeile)
        if nr_pos is None or nr_pos >= len(zellen):
            continue
        nummer = _tc_text(zellen[nr_pos]).strip().lstrip("0") or "0"
        eintrag = nach_nr.get(nummer)
        if eintrag is None:
            continue
        if datum_pos is not None and datum_pos < len(zellen):
            _set_tc_text(zellen[datum_pos], _als_datum(eintrag.entscheidungsdatum))
        if traeger_pos is not None and traeger_pos < len(zellen) \
                and not _tc_text(zellen[traeger_pos]).strip():
            _set_tc_text(zellen[traeger_pos], eintrag.entscheidungstraeger or "")

    _tilge_platzhalter(tbl)
    return _speichere(doc)


def _als_datum(iso):
    """ISO-Datum in die Schweizer Schreibweise – oder unverändert zurück."""
    text = str(iso or "").strip()
    teile = text.split("-")
    if len(teile) == 3 and all(t.isdigit() for t in teile):
        return f"{teile[2]}.{teile[1]}.{teile[0]}"
    return text
