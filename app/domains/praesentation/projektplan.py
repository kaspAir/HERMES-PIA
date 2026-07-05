"""Exportiert den Terminplan des freigabebereiten PIA als Projektplan.

Zwei Formate:
* MS-Project-XML: das offizielle Austauschformat, das Microsoft Project direkt
  öffnet (Datei > Öffnen). Aufgaben manuell geplant (Termine bleiben, wie im
  PIA festgehalten), Meilensteine mit Dauer 0.
* Excel (.xlsx): tabellarischer Plan mit Start/Ende/Dauer und Abnahme-Rolle.

Die Zeitlogik entspricht dem Gantt der Präsentation: Ergebnisse laufen
kaskadierend vom Vorgänger-Termin bis zu ihrem Termin, Meilensteine haben
Dauer 0 an ihrem Termin.
"""
import io
import re
from datetime import datetime, timedelta
from xml.sax.saxutils import escape

import xlsxwriter


def _parse_datum(text):
    m = re.search(r"\d{2}\.\d{2}\.\d{4}", str(text or ""))
    if not m:
        return None
    try:
        return datetime.strptime(m.group(), "%d.%m.%Y")
    except ValueError:
        return None


def plan_eintraege(termine):
    """Termine des PIA -> [(name, start, ende, meilenstein, abnahme)] (Kaskade)."""
    datiert = []
    for t in termine or []:
        datum = _parse_datum(t.get("termin"))
        if datum:
            datiert.append((t["ergebnis"], datum,
                            "meilenstein" in t["ergebnis"].lower(),
                            t.get("abnahme", "")))
    datiert.sort(key=lambda e: e[1])
    out = []
    vorher = datiert[0][1] if datiert else None
    for name, datum, meilenstein, abnahme in datiert:
        if meilenstein:
            out.append((name, datum, datum, True, abnahme))
        else:
            start = vorher if vorher < datum else datum - timedelta(days=1)
            out.append((name, start, datum, False, abnahme))
        vorher = datum
    return out


# ---------------------------------------------------------------------- #
# MS Project XML                                                           #
# ---------------------------------------------------------------------- #

# Reihenfolge gemaess mspdi-Schema (Project prueft die xsd:sequence STRIKT):
# UID, ID, Name, ... OutlineLevel, ... Start, Finish, Duration, DurationFormat,
# ... Milestone, ... ConstraintType, ConstraintDate, ... und die 2010er-Felder
# (Active, Manual, ManualStart/Finish/Duration) am ENDE (im Schema angehaengt).
_TASK_ELEMENT_ORDER = (
    "UID", "ID", "Name", "OutlineLevel", "Start", "Finish", "Duration",
    "DurationFormat", "Milestone", "ConstraintType", "ConstraintDate",
    "Active", "Manual", "ManualStart", "ManualFinish", "ManualDuration",
)


def build_msproject_xml(eintraege, projektname):
    """Minimales, von Microsoft Project direkt lesbares Projekt-XML
    (Element-Reihenfolge strikt nach mspdi-Schema)."""
    if not eintraege:
        return b""
    start = min(e[1] for e in eintraege)
    tasks = []
    for uid, (name, s, e, meilenstein, _abnahme) in enumerate(eintraege, 1):
        dauer_stunden = 0 if meilenstein else max((e - s).days, 1) * 8
        werte = {
            "UID": uid,
            "ID": uid,
            "Name": escape(name),
            "OutlineLevel": 1,
            "Start": f"{s:%Y-%m-%d}T08:00:00",
            "Finish": f"{e:%Y-%m-%d}T17:00:00",
            "Duration": f"PT{dauer_stunden}H0M0S",
            "DurationFormat": 7,                      # Tage
            "Milestone": 1 if meilenstein else 0,
            "ConstraintType": 4,                      # Muss anfangen am (Datum bleibt fix)
            "ConstraintDate": f"{s:%Y-%m-%d}T08:00:00",
            "Active": 1,
            "Manual": 1,
            "ManualStart": f"{s:%Y-%m-%d}T08:00:00",
            "ManualFinish": f"{e:%Y-%m-%d}T17:00:00",
            "ManualDuration": f"PT{dauer_stunden}H0M0S",
        }
        felder = "\n".join(f"      <{k}>{werte[k]}</{k}>" for k in _TASK_ELEMENT_ORDER)
        tasks.append("    <Task>\n" + felder + "\n    </Task>")
    xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Project xmlns="http://schemas.microsoft.com/project">\n'
        f"  <Name>{escape(projektname)}</Name>\n"
        f"  <Title>{escape(projektname)} – Phase Initialisierung</Title>\n"
        f"  <StartDate>{start:%Y-%m-%d}T08:00:00</StartDate>\n"
        "  <Tasks>\n"
        + "\n".join(tasks) + "\n"
        "  </Tasks>\n"
        "</Project>\n"
    )
    return xml.encode("utf-8")


# ---------------------------------------------------------------------- #
# Excel                                                                    #
# ---------------------------------------------------------------------- #

_MONATE_KURZ = ("Jan", "Feb", "Mär", "Apr", "Mai", "Jun",
                "Jul", "Aug", "Sep", "Okt", "Nov", "Dez")


def _zeiteinheiten(start, ende):
    """Spalten des Excel-Gantt: Kalenderwochen; bei sehr langen Plänen Monate.
    Rückgabe: (einheit, [(von, bis, label, monatslabel)])."""
    montag = start - timedelta(days=start.weekday())
    wochen = []
    d = montag
    while d <= ende:
        wochen.append((d, d + timedelta(days=6),
                       f"{d.isocalendar()[1]:02d}",
                       f"{_MONATE_KURZ[d.month - 1]} {d.strftime('%y')}"))
        d += timedelta(days=7)
    if len(wochen) <= 40:
        return "KW", wochen
    monate = []
    d = datetime(start.year, start.month, 1)
    while d <= ende:
        naechster = datetime(d.year + (1 if d.month == 12 else 0), d.month % 12 + 1, 1)
        monate.append((d, naechster - timedelta(days=1),
                       _MONATE_KURZ[d.month - 1],
                       d.strftime("%Y")))
        d = naechster
    return "Monat", monate


def build_excel(eintraege, projektname):
    """Projektplan als .xlsx (XlsxWriter, komplett im Speicher) –
    Tabelle plus Gantt-Raster (schmale Zeiteinheiten-Spalten rechts)."""
    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {"in_memory": True})
    ws = wb.add_worksheet("Projektplan")

    titel_fmt = wb.add_format({"bold": True, "font_size": 14})
    kopf_fmt = wb.add_format({"bold": True, "bg_color": "#F2F2F2", "border": 1})
    kopf_klein_fmt = wb.add_format({"bold": True, "bg_color": "#F2F2F2", "border": 1,
                                    "align": "center", "font_size": 8})
    monat_fmt = wb.add_format({"bold": True, "bg_color": "#F2F2F2", "border": 1,
                               "align": "center", "font_size": 9})
    zelle_fmt = wb.add_format({"border": 1})
    ms_fmt = wb.add_format({"border": 1, "bold": True})
    datum_fmt = wb.add_format({"border": 1, "num_format": "dd.mm.yyyy"})
    datum_ms_fmt = wb.add_format({"border": 1, "bold": True, "num_format": "dd.mm.yyyy"})
    balken_fmt = wb.add_format({"bg_color": "#2E75B6", "border": 1,
                                "border_color": "#D9D9D9"})
    raute_fmt = wb.add_format({"bold": True, "align": "center", "border": 1,
                               "border_color": "#D9D9D9", "font_color": "#1F3864"})
    raster_fmt = wb.add_format({"border": 1, "border_color": "#D9D9D9"})

    ws.write(0, 0, f"{projektname} – Projektplan Phase Initialisierung", titel_fmt)
    koepfe = ("Nr.", "Ergebnis / Meilenstein", "Typ", "Start", "Ende",
              "Dauer (Kalendertage)", "Abnahme durch")
    kopfzeile = 2
    for c, kopf in enumerate(koepfe):
        ws.write(kopfzeile, c, kopf, kopf_fmt)

    # ---- Gantt-Raster: eine schmale Spalte je Zeiteinheit ------------- #
    gantt_von = len(koepfe)
    start_min = min(e[1] for e in eintraege)
    ende_max = max(e[2] for e in eintraege)
    einheit, spalten = _zeiteinheiten(start_min, ende_max)
    # Obere Kopfzeile: Monats- bzw. Jahresblöcke über den Einheiten (verbunden).
    block_start = 0
    for i in range(len(spalten) + 1):
        wechsel = (i == len(spalten)
                   or (i > 0 and spalten[i][3] != spalten[block_start][3]))
        if wechsel:
            c1, c2 = gantt_von + block_start, gantt_von + i - 1
            label = spalten[block_start][3]
            if c1 == c2:
                ws.write(kopfzeile - 1, c1, label, monat_fmt)
            else:
                ws.merge_range(kopfzeile - 1, c1, kopfzeile - 1, c2, label, monat_fmt)
            block_start = i
    for i, (_von, _bis, label, _mlabel) in enumerate(spalten):
        ws.write(kopfzeile, gantt_von + i, label, kopf_klein_fmt)

    for r, (name, s, e, meilenstein, abnahme) in enumerate(eintraege, kopfzeile + 1):
        txt = ms_fmt if meilenstein else zelle_fmt
        dat = datum_ms_fmt if meilenstein else datum_fmt
        ws.write(r, 0, r - kopfzeile, txt)
        ws.write(r, 1, name, txt)
        ws.write(r, 2, "Meilenstein" if meilenstein else "Ergebnis", txt)
        ws.write_datetime(r, 3, s, dat)
        ws.write_datetime(r, 4, e, dat)
        ws.write(r, 5, 0 if meilenstein else max((e - s).days, 1), txt)
        ws.write(r, 6, abnahme, txt)
        for i, (von, bis, _label, _mlabel) in enumerate(spalten):
            if meilenstein:
                if von <= s <= bis:
                    ws.write(r, gantt_von + i, "◆", raute_fmt)
                else:
                    ws.write_blank(r, gantt_von + i, None, raster_fmt)
            elif s <= bis and e >= von:
                ws.write_blank(r, gantt_von + i, None, balken_fmt)
            else:
                ws.write_blank(r, gantt_von + i, None, raster_fmt)

    ws.set_column(0, 0, 5)
    ws.set_column(1, 1, 70)
    ws.set_column(2, 2, 12)
    ws.set_column(3, 5, 14)
    ws.set_column(6, 6, 22)
    ws.set_column(gantt_von, gantt_von + len(spalten) - 1, 3.2)
    ws.freeze_panes(kopfzeile + 1, gantt_von)
    wb.close()
    buf.seek(0)
    return buf.getvalue()
