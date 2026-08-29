"""Die D-Regeln der Ebene «Dok» – geprüft am erzeugten Dokument.

Nur was erst im Dokument sichtbar wird, wird hier geprüft: Platzhalter,
Hilfetexte, Standardtexte, Nicht-HERMES-Begriffe.

**Die zwei Stolpersteine aus Katalog 11.1** – beide haben im Prototyp massenhaft
Fehlalarme erzeugt und sind hier bewusst gelöst:

1. **Zellen in Inhaltssteuerelementen.** Auswahlfelder (Kategorie, Priorität,
   Eintrittswahrscheinlichkeit) liegen in Word-SDT-Elementen. `python-docx`
   überspringt sie in `row.cells` – dadurch verschieben sich ALLE Spaltenindizes.
   `zellen()` liest deshalb direkt am XML und nimmt die verpackten Zellen mit.

2. **Text in mehreren Abschnitten je Zelle.** Word zerlegt Text innerhalb einer
   Zelle. Mit Leerzeichen verbunden entstehen Wortbrüche wie «Liefert ermin»,
   und Kopfzeilen werden nicht mehr erkannt. Deshalb OHNE Trennzeichen verbinden.
"""
import re

from app.domains.qualitaet import katalog as K
from app.domains.qualitaet.modell import DOK, HINWEIS, MUSS, Befund

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def zellstext(tc):
    """Text einer Zelle – OHNE Trennzeichen verbunden (Stolperstein 2).

    Word teilt «Liefertermin» in «Liefert» + «ermin»; ein Leerzeichen dazwischen
    macht daraus «Liefert ermin» und die Kopfzeile ist nicht mehr erkennbar.
    """
    return "".join(t.text or "" for t in tc.iter(f"{_W}t")).strip()


def zellen(tr):
    """Alle Zellen einer Zeile – inklusive der in Inhaltssteuerelementen
    verpackten (Stolperstein 1).

    `row.cells` von python-docx überspringt `<w:sdt>`-Zellen; danach zeigt jeder
    Spaltenindex auf die falsche Spalte.
    """
    out = []
    for kind in tr:
        if kind.tag == f"{_W}tc":
            out.append(kind)
        elif kind.tag == f"{_W}sdt":
            out.extend(kind.iter(f"{_W}tc"))
    return out


def _tabellenueberschriften(dok):
    """{Tabellen-Element: letzte Überschrift davor} – der fehlende Zusammenhang.

    Die Vorlage führt drei gleich gebaute Tabellen untereinander:
    Änderungskontrolle, Prüfung, Freigabe. In der Zeile selbst steht nur
    «0.1 | | tt.mm.jjjj» – welche der drei es ist, sagt allein die Überschrift
    DARÜBER. Ohne diesen Bezug traf die Ausnahme für Prüf- und Freigabezeilen
    nie, und der Platzhalter «tt.mm.jjjj» wurde dort als Muss gemeldet, wo er
    hingehört: beide Tabellen werden erst bei der Prüfung bzw. der Freigabe
    ausgefüllt.
    """
    zuordnung, letzte = {}, ""
    for kind in dok.element.body.iterchildren():
        if kind.tag == f"{_W}p":
            text = "".join(t.text or "" for t in kind.iter(f"{_W}t")).strip()
            if text:
                letzte = text
        elif kind.tag == f"{_W}tbl":
            zuordnung[kind] = letzte
    return zuordnung


def _tabellenzeilen(dok):
    ueber = _tabellenueberschriften(dok)
    for tabelle in dok.tables:
        titel = ueber.get(tabelle._tbl, "")
        for tr in tabelle._tbl.iter(f"{_W}tr"):
            yield tabelle, tr, titel


def _alle_absaetze(dok):
    """Alle Absaetze als ROHE XML-Elemente.

    Bewusst einheitlich: `dok.paragraphs` liefert Paragraph-Objekte, die
    Tabellen-Iteration dagegen lxml-Elemente. Gemischt fuehrt das zu
    AttributeError, sobald eine Regel am XML arbeitet (Formatvorlage lesen).
    """
    for absatz in dok.paragraphs:
        yield absatz._p
    for t in dok.tables:
        for tc in t._tbl.iter(f"{_W}tc"):
            for p in tc.iter(f"{_W}p"):
                yield p


def _ist_freigabezeile(zeilentext):
    """Kap. 8: die Zeilen für Prüfung und Freigabe dürfen «tt.mm.jjjj» tragen –
    sie werden erst bei Prüfung bzw. Freigabe ausgefüllt. Im Baseline-Lauf war
    das die häufigste Fehlmeldung (Katalog Abschnitt 11)."""
    t = (zeilentext or "").lower()
    return any(w in t for w in ("prüfung", "pruefung", "freigabe", "geprüft", "genehmigt"))


def pruefe_dokument(dok, standardtext=None, phasenuebergreifend=False):
    """Alle Dok-Regeln über ein python-docx-Document. Liste von Befunden.

    ``phasenuebergreifend``: das Dokument betrifft nicht nur die
    Initialisierung (z.B. die Liste Projektentscheide Steuerung, die das
    ganze Projekt fuehrt). Dann entfallen die Begriffsregeln, die allein
    fuer die Initialisierung gelten.
    """
    befunde = []
    befunde += list(_d003_platzhalter(dok))
    befunde += list(_d011_leere_platzhalterzeile(dok))
    befunde += list(_d004_hilfetexte(dok))
    befunde += list(_d005_nicht_hermes_begriffe(dok, phasenuebergreifend))
    befunde += list(_d081_freigabe_nicht_vorausgefuellt(dok))
    if standardtext:
        befunde += list(_d020_standardtext_unveraendert(dok, standardtext))
    return befunde


# ---- D-003 --------------------------------------------------------------- #

def _d003_platzhalter(dok):
    gemeldet = set()
    for _tabelle, tr, ueberschrift in _tabellenzeilen(dok):
        # Die Ueberschrift gehoert zum Zeilenkontext: sie sagt, ob dies die
        # Aenderungskontrolle ist (Datum PFLICHT) oder die Pruef-/Freigabe-
        # tabelle (Datum kommt spaeter).
        zeile = " ".join(zellstext(tc) for tc in zellen(tr)) + " " + ueberschrift
        for tc in zellen(tr):
            text = zellstext(tc)
            klein = text.lower()
            for p in K.PLATZHALTER:
                if p in klein and p not in gemeldet:
                    gemeldet.add(p)
                    yield Befund("D-003", MUSS, DOK,
                                 f"Im Dokument stehen noch Platzhalter der Vorlage: "
                                 f"«{text[:60]}».", "Tabelle")
            # Datums-Platzhalter NUR ausserhalb der Prüf-/Freigabezeilen.
            if K.DATUM_PLATZHALTER in klein and not _ist_freigabezeile(zeile):
                if "datum" not in gemeldet:
                    gemeldet.add("datum")
                    yield Befund("D-003", MUSS, DOK,
                                 f"Im Dokument steht noch ein Datums-Platzhalter: "
                                 f"«{K.DATUM_PLATZHALTER}».", "Tabelle")
    for p in dok.paragraphs:
        klein = (p.text or "").lower()
        for muster in K.PLATZHALTER:
            if muster in klein and muster not in gemeldet:
                gemeldet.add(muster)
                yield Befund("D-003", MUSS, DOK,
                             f"Im Dokument stehen noch Platzhalter der Vorlage: "
                             f"«{p.text[:60]}».", "Fliesstext")


# ---- D-011 --------------------------------------------------------------- #

def _d011_leere_platzhalterzeile(dok):
    """«…» zählt NUR als alleiniger Zellinhalt – im Fliesstext ist es eine
    Auslassung (Katalog Abschnitt 11)."""
    for i, tabelle in enumerate(dok.tables, 1):
        for tr in tabelle._tbl.iter(f"{_W}tr"):
            texte = [zellstext(tc) for tc in zellen(tr)]
            inhalt = [t for t in texte if t]
            if inhalt and all(t.strip() in (K.LEERZEILE, "...") for t in inhalt):
                yield Befund("D-011", MUSS, DOK,
                             f"Die Tabelle {i} ist leer geblieben – die Platzhalterzeile "
                             f"der Vorlage steht noch.", f"Tabelle {i}")
                break


# ---- D-004 --------------------------------------------------------------- #

_HILFE_STIL = ("hilfe", "hinweis", "beispiel", "muster", "erklärung", "erklaerung")


def _d004_hilfetexte(dok):
    """Unterscheidet LEERE Vorlagenzeile von INHALTSTRAGENDER.

    Wichtig fuer die Handlungsanweisung: eine leere Beispielzeile gehoert
    geloescht – eine mit Inhalt bedeutet, dass das Kapitel nicht befuellt wurde,
    und dann ist zu BEFUELLEN. Die frueher einheitliche Meldung verleitete dazu,
    sinnvolle Angaben zu loeschen (Katalog v0.4, D-004).
    """
    for p in _alle_absaetze(dok):
        stil = ""
        pr = p.find(f"{_W}pPr")
        if pr is not None:
            ps = pr.find(f"{_W}pStyle")
            if ps is not None:
                stil = (ps.get(f"{_W}val") or "").lower()
        if not (stil and any(h in stil for h in _HILFE_STIL)):
            continue
        text = "".join(t.text or "" for t in p.iter(f"{_W}t")).strip()
        if text:
            yield Befund("D-004", MUSS, DOK,
                         f"Das Kapitel wurde nicht befüllt; die Vorlagenzeile steht "
                         f"noch: «{text[:60]}».", f"Formatvorlage {stil}")
        else:
            yield Befund("D-004", MUSS, DOK,
                         "Eine leere Hilfe-/Beispielzeile der Vorlage ist noch "
                         "enthalten und gehört entfernt.", f"Formatvorlage {stil}")
        return


# ---- D-005 --------------------------------------------------------------- #

def _d005_nicht_hermes_begriffe(dok, phasenuebergreifend=False):
    gemeldet = set()
    if phasenuebergreifend:
        gemeldet.update(K.NUR_INITIALISIERUNG)
    for p in _alle_absaetze(dok):
        text = "".join(t.text or "" for t in p.iter(f"{_W}t")).lower()
        for begriff, ersatz in K.NICHT_HERMES.items():
            if begriff in text and begriff not in gemeldet:
                gemeldet.add(begriff)
                yield Befund("D-005", MUSS, DOK,
                             f"Der Begriff «{begriff}» entspricht nicht HERMES 2022 – "
                             f"richtig wäre «{ersatz}».", "Fliesstext")


# ---- D-020 --------------------------------------------------------------- #

def _d020_standardtext_unveraendert(dok, standardtext):
    def norm(t):
        return re.sub(r"\s+", " ", (t or "")).strip().lower()

    soll = norm(standardtext)
    if not soll:
        return
    for p in dok.paragraphs:
        ist = norm(p.text)
        if ist and (soll[:40] in ist or ist[:40] in soll):
            if ist != soll:
                yield Befund("D-020", MUSS, DOK,
                             "Der Standardtext in Kap. 0.1 wurde verändert.", "Kap. 0.1")
            return


# ---- D-081 --------------------------------------------------------------- #

def _d081_freigabe_nicht_vorausgefuellt(dok):
    """Prüfung/Freigabe dürfen noch nicht eingetragen sein."""
    for tabelle in dok.tables:
        kopf = " ".join(zellstext(tc) for tc in zellen(next(iter(
            tabelle._tbl.iter(f"{_W}tr")), []))).lower()
        if not _ist_freigabezeile(kopf) and "name" not in kopf:
            continue
        for tr in list(tabelle._tbl.iter(f"{_W}tr"))[1:]:
            texte = [zellstext(tc) for tc in zellen(tr)]
            zeile = " ".join(texte).lower()
            if not _ist_freigabezeile(zeile):
                continue
            # Ein Name UND ein echtes Datum => bereits eingetragen.
            hat_name = any(t and not re.match(r"^[\d.\-/]+$", t) and
                           K.DATUM_PLATZHALTER not in t.lower() and
                           not _ist_freigabezeile(t) for t in texte)
            hat_datum = any(re.search(r"\d{1,2}\.\d{1,2}\.\d{2,4}", t) for t in texte)
            if hat_name and hat_datum:
                yield Befund("D-081", MUSS, DOK,
                             "Eine Prüfung oder Freigabe ist eingetragen, obwohl sie "
                             "noch aussteht.", "Kap. 8")
                return
