"""Beweist: Fundstellen werden RECHERCHIERT, nicht behauptet.

Zwei Quellen, eine Regel. Die Analyse zitiert auf Artikel-, Absatz- und
Litera-Ebene und stützt sich auf Rechtsprechung – geprüft wurde bisher nur der
ERLASS. Gemessen stand im Dokument «StPO Art. 351 ff., insb. Art. 354» für die
Vollstreckung von Bussen; Art. 354 StPO regelt die **Einsprache gegen den
Strafbefehl**. Eine falsche Artikelangabe ist gefährlicher als gar keine: sie
sieht präziser aus, als sie belegt ist.

Die Tests laufen OHNE NETZ – die Antworten der amtlichen Quellen sind
aufgezeichnet. Was live geprüft wurde, steht in den Kommentaren.
"""
import json

import pytest

from app.domains.rechtsquellen import bger
from app.domains.rechtsquellen.artikel import (
    BELEGT, EXISTIERT_NICHT, NICHT_PRUEFBAR, ArtikelPruefer, artikelnummern,
)

# Aufgezeichnet von fedlex.data.admin.ch (Bundesverfassung, HTML-Fassung).
_BUND_HTML = (
    '<p id="art_5"><b>Art. 5</b> Grundsätze rechtsstaatlichen Handelns</p>'
    "<p>1 &nbsp;Grundlage und Schranke staatlichen Handelns ist das Recht.</p>"
    '<p id="art_36"><b>Art. 36</b> Einschränkungen von Grundrechten</p>'
    "<p>1 &nbsp;Einschränkungen von Grundrechten bedürfen einer gesetzlichen "
    "Grundlage.</p>"
)

# Aufgezeichnet von gesetzessammlung.sg.ch (JSON-API + amtliche PDF-Fassung).
_KANTON_JSON = json.dumps({"text_of_law": {
    "title": "Polizeigesetz", "abbreviation": "PG",
    "pdf_link": "https://www.gesetzessammlung.sg.ch/api/de/versions/3670/pdf",
}}).encode()
_KANTON_TEXT = ("Art. 3 Zuständigkeit 1 Die Kantonspolizei … "
                "Art. 4 Polizeiliche Anordnungen a) im allgemeinen 1 Die "
                "Regierung erlässt polizeiliche Anordnungen, wenn …")


def _oeffner(html=_BUND_HTML):
    """Ein Ersatz für den Netzzugriff – gibt Aufgezeichnetes zurück."""
    def oeffne(url, timeout=30):
        if "sparqlendpoint" in url:
            raise AssertionError("SPARQL läuft über einen eigenen Weg")
        if "/api/" in url and "texts_of_law" in url:
            return _KANTON_JSON
        if "pdf" in url:
            return b"%PDF-1.4"          # der PDF-Leser wird ersetzt, s. u.
        return html.encode("utf-8")
    return oeffne


# ---- Zitate erkennen ----------------------------------------------------- #

@pytest.mark.parametrize("zitat,erwartet", [
    ("Art. 36 BV", ["36"]),
    ("Art. 5 Abs. 1 BV", ["5"]),
    ("Art. 5 lit. c Ziff. 5 nDSG", ["5"]),
    ("Art. 351 ff., insb. Art. 354 StPO", ["351", "354"]),
    ("Artikel 13a des Gesetzes", ["13a"]),
    ("Art. 36 Abs. 1, 3, 4 BV", ["36"]),
    ("SR 235.1 – Bundesgesetz über den Datenschutz", []),
])
def test_artikelnummern_werden_erkannt(zitat, erwartet):
    assert artikelnummern(zitat) == erwartet


def test_dubletten_verschwinden():
    assert artikelnummern("Art. 36 BV und Art. 36 Abs. 4 BV") == ["36"]


# ---- Drei Zustände, streng getrennt -------------------------------------- #

def test_ohne_netz_ist_der_pruefer_inaktiv():
    """Er erfindet nie einen Beleg – und «nicht geprüft» ist nicht «nicht
    vorhanden». Diese Unterscheidung ist der Kern des Moduls."""
    p = ArtikelPruefer()          # aktiv=False
    assert p.pruefe("https://www.fedlex.admin.ch/eli/cc/1999/404/de", "36") == \
        (NICHT_PRUEFBAR, "")


def test_bundesartikel_wird_belegt(monkeypatch):
    """Live gegen Fedlex geprüft: Art. 36 BV → «Einschränkungen von
    Grundrechten»."""
    p = ArtikelPruefer(aktiv=True, oeffner=_oeffner())
    monkeypatch.setattr(p, "_fedlex_datei", lambda eli: "https://beispiel/html")
    zustand, kopf = p.pruefe("https://www.fedlex.admin.ch/eli/cc/1999/404/de", "36")
    assert zustand == BELEGT
    assert kopf == "Einschränkungen von Grundrechten"


def test_die_ueberschrift_verliert_die_artikelnummer(monkeypatch):
    """Wird zuerst am Punkt getrennt, bleibt von «Art. 36 Einschränkungen …»
    das Wort «Art» übrig – gemessen genau so passiert."""
    p = ArtikelPruefer(aktiv=True, oeffner=_oeffner())
    monkeypatch.setattr(p, "_fedlex_datei", lambda eli: "https://beispiel/html")
    _, kopf = p.pruefe("https://www.fedlex.admin.ch/eli/cc/1999/404/de", "5")
    assert kopf == "Grundsätze rechtsstaatlichen Handelns"
    assert not kopf.startswith("Art")


def test_fehlender_artikel_wird_als_solcher_gemeldet(monkeypatch):
    p = ArtikelPruefer(aktiv=True, oeffner=_oeffner())
    monkeypatch.setattr(p, "_fedlex_datei", lambda eli: "https://beispiel/html")
    zustand, kopf = p.pruefe("https://www.fedlex.admin.ch/eli/cc/1999/404/de", "9999")
    assert zustand == EXISTIERT_NICHT and kopf == ""


def test_unerreichbare_quelle_ist_nicht_pruefbar():
    """Nicht erreichbar ist ein Zustand, kein Ergebnis."""
    def kaputt(url, timeout=30):
        raise OSError("kein Netz")

    p = ArtikelPruefer(aktiv=True, oeffner=kaputt)
    assert p.pruefe("https://www.gesetzessammlung.sg.ch/app/de/texts_of_law/451.1",
                    "4") == (NICHT_PRUEFBAR, "")


# ---- Kantonales Recht ---------------------------------------------------- #

def test_kantons_api_wird_aus_dem_sammlungslink_abgeleitet():
    """Die kantonalen Sammlungen sind JavaScript-Seiten; die Lexwork-Plattform
    bietet daneben ein JSON-API. Der Weg dorthin ist ableitbar."""
    p = ArtikelPruefer()
    assert p._kantons_api(
        "https://www.gesetzessammlung.sg.ch/app/de/texts_of_law/451.1") == \
        "https://www.gesetzessammlung.sg.ch/api/de/texts_of_law/451.1"
    assert p._kantons_api("https://www.fedlex.admin.ch/eli/cc/1999/404/de") is None


def test_kantonsartikel_wird_belegt(monkeypatch):
    """Live gegen die St. Galler Sammlung geprüft: Art. 4 PG → «Polizeiliche
    Anordnungen a) im allgemeinen»."""
    p = ArtikelPruefer(aktiv=True, oeffner=_oeffner())
    monkeypatch.setattr(p, "_kantons_text", lambda url: _KANTON_TEXT)
    zustand, kopf = p.pruefe(
        "https://www.gesetzessammlung.sg.ch/app/de/texts_of_law/451.1", "4")
    assert zustand == BELEGT
    assert kopf.startswith("Polizeiliche Anordnungen")


def test_ein_zitat_wird_vollstaendig_geprueft(monkeypatch):
    p = ArtikelPruefer(aktiv=True, oeffner=_oeffner())
    monkeypatch.setattr(p, "_fedlex_datei", lambda eli: "https://beispiel/html")
    befunde = p.pruefe_fundstelle(
        "https://www.fedlex.admin.ch/eli/cc/1999/404/de", "Art. 5 und Art. 36 BV")
    assert [b["artikel"] for b in befunde] == ["5", "36"]
    assert all(b["zustand"] == BELEGT for b in befunde)


# ---- Bundesgerichtsentscheide: nie erfinden ------------------------------ #

_BGER_SEITE = (
    '<a href="index.php?lang=de&type=show_document&highlight_docid='
    'aza%3A%2F%2F05-02-2024-6B_1243-2023">…</a>'
    '<a href="index.php?highlight_docid=atf%3A%2F%2F151-I-137%3Ade">…</a>'
    '<a href="index.php?highlight_docid=unsinn-ohne-kennung">…</a>'
)


def test_ohne_netz_gibt_es_keine_entscheide():
    """Es gibt keinen Ersatzweg. Ein erfundener Entscheid ist der teuerste
    Fehler, den dieses Produkt machen kann."""
    assert bger.BgerClient().suche("Gesichtserkennung") == []


def test_entscheide_stammen_aus_der_amtlichen_suche():
    """Live geprüft: die Suche nach «Gesichtserkennung» liefert unter anderem
    6B_1243/2023 und BGE 151 I 137."""
    c = bger.BgerClient(aktiv=True, oeffner=lambda url, timeout=30: _BGER_SEITE)
    treffer = c.suche("Gesichtserkennung")
    assert [t["kennung"] for t in treffer] == ["6B_1243/2023", "BGE 151 I 137"]
    assert treffer[0]["datum"] == "05.02.2024"
    assert all(t["fundstelle_geprueft"] for t in treffer)
    assert all("search.bger.ch" in t["url"] for t in treffer)


def test_treffer_ohne_amtliche_kennung_werden_verworfen():
    """Lieber nichts als ein Verweis, den niemand nachschlagen kann."""
    c = bger.BgerClient(aktiv=True,
                        oeffner=lambda url, timeout=30:
                        '<a href="?highlight_docid=kaputt">x</a>')
    assert c.suche("egal") == []


def test_ein_ausfall_der_suche_erfindet_nichts():
    def kaputt(url, timeout=30):
        raise OSError("kein Netz")

    assert bger.BgerClient(aktiv=True, oeffner=kaputt).suche("egal") == []


def test_mehrere_begriffe_ohne_dubletten():
    c = bger.BgerClient(aktiv=True, oeffner=lambda url, timeout=30: _BGER_SEITE)
    alle = c.suche_mehrere(["Gesichtserkennung", "Videoüberwachung"])
    assert [t["kennung"] for t in alle] == ["6B_1243/2023", "BGE 151 I 137"]
    assert alle[0]["suchbegriff"] == "Gesichtserkennung"


def test_kennungen_werden_streng_entziffert():
    """Was sich nicht entziffern lässt, wird verworfen – ein Treffer ohne
    nachschlagbare Kennung ist als Beleg wertlos."""
    assert bger._entziffere("aza://17-10-2024-1C_63-2023") == ("1C_63/2023",
                                                               "17.10.2024")
    assert bger._entziffere("atf://151-I-137:de") == ("BGE 151 I 137", "")
    assert bger._entziffere("irgendwas") == (None, None)
