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


# ---- Rechtsprechung nur, wo sie etwas bringt ----------------------------- #
#
# Ein Urteil neben einer klaren Rechtslage schmückt nur und lenkt vom
# Wesentlichen ab. Beigezogen wird sie deshalb NUR dort, wo eine echte
# Rechtsfrage offen ist – und der Grund wird mitgeführt, damit im Nachweis
# steht, warum bei den übrigen nicht gesucht wurde.

@pytest.mark.parametrize("eintrag,erwartet", [
    ({"wuerdigung": {"ergebnis": "zulässig", "sicherheit": "eindeutig"}}, False),
    ({"wuerdigung": {"ergebnis": "bedingt zulässig", "sicherheit": "eindeutig"}}, True),
    ({"wuerdigung": {"ergebnis": "nicht zulässig", "sicherheit": "eindeutig"}}, True),
    ({"wuerdigung": {"ergebnis": "zulässig",
                     "sicherheit": "vertretbare Auffassung"}}, True),
    ({"wuerdigung": {"ergebnis": "zulässig", "sicherheit": "offen"}}, True),
    ({"wuerdigung": {"ergebnis": "zulässig", "kerngehalt_verletzt": True}}, True),
    ({"wuerdigung": {"ergebnis": "zulässig", "sicherheit": "eindeutig"},
      "gap": {"bestaetigt": True}}, True),
    ({"kartierung": {"grundrechtseingriff_denkbar": False},
      "wuerdigung": {"ergebnis": "zulässig", "sicherheit": "eindeutig"}}, False),
])
def test_rechtsprechung_nur_bei_offener_rechtsfrage(eintrag, erwartet):
    noetig, grund = bger.rechtsprechung_noetig(eintrag)
    assert noetig is erwartet
    assert grund, "der Grund wird immer mitgeführt"


def test_die_gross_und_kleinschreibung_darf_die_regel_nicht_aushebeln():
    """Gemessen: «vertretbare Auffassung» wurde gegen eine kleingeschriebene
    Liste verglichen und griff nie – die Sperre war stumm."""
    for schreibweise in ("vertretbare Auffassung", "Vertretbare Auffassung",
                         "VERTRETBARE AUFFASSUNG"):
        noetig, _ = bger.rechtsprechung_noetig(
            {"wuerdigung": {"ergebnis": "zulässig", "sicherheit": schreibweise}})
        assert noetig is True, schreibweise


def test_nicht_belegte_entscheide_werden_getilgt():
    """Die stärkste Sperre gegen erfundene Rechtsprechung: was das Modell
    nennt, muss in der Trefferliste vorkommen."""
    text = ("Vgl. BGE 151 I 137 und BGE 99 IX 999 sowie 6B_1243/2023 und "
            "9C_999/2099.")
    sauber = bger.nur_belegte(text, ["BGE 151 I 137", "6B_1243/2023"])
    assert "BGE 151 I 137" in sauber
    assert "6B_1243/2023" in sauber
    assert "BGE 99 IX 999" not in sauber
    assert "9C_999/2099" not in sauber
    assert sauber.count("[Entscheid ohne Beleg – entfernt]") == 2


def test_ohne_trefferliste_bleibt_kein_entscheid_stehen():
    """Wurde nicht gesucht, darf auch nichts zitiert sein."""
    sauber = bger.nur_belegte("Vgl. BGE 151 I 137.", [])
    assert "BGE 151 I 137" not in sauber


def test_text_ohne_entscheide_bleibt_unveraendert():
    text = "Die Tätigkeit stützt sich auf Art. 36 BV und ist verhältnismässig."
    assert bger.nur_belegte(text, []) == text


def test_ohne_ueberschrift_steht_der_wortlaut_da(monkeypatch):
    """Nicht jeder Artikel hat eine Sachüberschrift – Art. 106 StGB beginnt
    direkt mit dem Normtext. Dann ist der Anfang des Textes die ehrliche
    Auskunft; als «Überschrift» ausgegeben wäre er irreführend."""
    ohne_ueberschrift = (
        '<p id="art_106"><b>Art. 106</b></p>'
        "<p>1 &nbsp;Bestimmt es das Gesetz nicht anders, so ist der Höchstbetrag "
        "der Busse 10 000 Franken.</p>")
    p = ArtikelPruefer(aktiv=True,
                       oeffner=lambda url, timeout=30: ohne_ueberschrift.encode())
    monkeypatch.setattr(p, "_fedlex_datei", lambda eli: "https://beispiel/html")
    zustand, text = p.pruefe("https://www.fedlex.admin.ch/eli/cc/54/757/de", "106")
    assert zustand == BELEGT
    assert text.startswith("[Wortlaut] ")
    assert "Höchstbetrag der Busse" in text
    assert not text.startswith("Art")


# ---- Kantonale Fundstellen: gemessen, nicht angenommen -------------------- #
#
# Eine Messung über alle 26 Kantone (Suche → Adresse → JSON → PDF → Text) ergab:
# die Artikelprüfung trug für **keinen einzigen** Kanton. Der Grund war kein
# Ausfall der Quellen, sondern eine Adressform, die es nicht gibt: der Code
# erwartete `/data/<Sprache>/texts_of_law/<Slug>`, lexfind liefert aber
# `/data/<Nummer>/<Sprache>`. Kantonale Artikel fielen deshalb immer auf «nicht
# prüfbar» — ehrlich in der Ausgabe, aber die Funktion lief nie.
#
# Die bestehenden Tests konnten das nicht finden: sie arbeiteten mit einer von
# Hand gebauten Beispieladresse in der erwarteten Form. Ein Test, der seine
# Eingabe selbst erfindet, prüft die Annahme mit, statt sie zu widerlegen.

def test_die_gemessene_adressform_wird_umgebaut():
    """`/data/<Nummer>/<Sprache>` – so liefert lexfind es wirklich."""
    from app.domains.rechtsquellen.artikel import ArtikelPruefer as A

    assert A._kantons_api("https://bgs.so.ch/data/114.2/de") \
        == "https://bgs.so.ch/api/de/texts_of_law/114.2"
    assert A._kantons_api("https://www.belex.sites.be.ch/data/152.043/de") \
        == "https://www.belex.sites.be.ch/api/de/texts_of_law/152.043"
    assert A._kantons_api("https://gesetzessammlungen.ag.ch/data/150.700/de") \
        == "https://gesetzessammlungen.ag.ch/api/de/texts_of_law/150.700"


def test_die_aeltere_adressform_bleibt_gueltig():
    from app.domains.rechtsquellen.artikel import ArtikelPruefer as A

    assert A._kantons_api("https://ai.clex.ch/app/de/texts_of_law/172.700") \
        == "https://ai.clex.ch/api/de/texts_of_law/172.700"


def test_fremde_adressen_werden_nicht_umgebaut():
    """Bund und eigene Kantonsplattformen sind kein Lexwork."""
    from app.domains.rechtsquellen.artikel import ArtikelPruefer as A

    assert A._kantons_api("https://www.fedlex.admin.ch/eli/cc/1999/404/de") is None
    assert A._kantons_api(
        "https://www.zh.ch/de/politik-staat/gesetze-beschluesse/"
        "gesetzessammlung/zhlex-ls/erlass-170_4-2008") is None
    assert A._kantons_api("") is None
    assert A._kantons_api(None) is None


def test_direkte_pdf_fassungen_werden_erkannt():
    """Genf und Schwyz liefern die amtliche Fassung als PDF, ohne Lexwork."""
    from app.domains.rechtsquellen.artikel import ArtikelPruefer as A

    assert A._ist_pdf_adresse("https://www.sz.ch/public/upload/assets/5406/140_411.pdf?fp=2")
    assert A._ist_pdf_adresse("https://silgeneve.ch/legis/program/books/RSG/pdf/rsg_a2_08")
    assert not A._ist_pdf_adresse("https://bgs.so.ch/data/114.2/de")
    assert not A._ist_pdf_adresse("")


def test_die_amtssprache_entscheidet_ueber_die_adresse():
    """Genf führt seine Erlasse NUR auf Französisch – «nur de» fand nichts."""
    from app.domains.rechtsquellen.lexfind import adresse_aus

    assert adresse_aus([{"language": "fr", "original_url": "F"},
                        {"language": "de", "original_url": "D"}]) == "D"
    assert adresse_aus([{"language": "fr", "original_url": "F"}]) == "F"
    assert adresse_aus([{"language": "it", "original_url": "I"}]) == "I"
    # Unbekannte Sprache ist besser als keine Adresse.
    assert adresse_aus([{"language": "xx", "original_url": "X"}]) == "X"
    assert adresse_aus([]) == ""
    assert adresse_aus(None) == ""


def test_die_amtssprachen_der_kantone_sind_hinterlegt():
    """Angabe des Nutzers, mit der Sprachenkarte abgeglichen.

    Sie steht im Code und nicht in einem Messskript, weil sie das Verhalten
    bestimmt: Wer einen Genfer Erlass mit einem deutschen Begriff sucht,
    findet ihn nicht.
    """
    from app.domains.rechtsquellen.kantone import KANTON_SAMMLUNG, sprachen

    assert sprachen("GE") == ("fr",)
    assert sprachen("VD") == ("fr",)
    assert sprachen("TI") == ("it",)
    assert sprachen("FR")[0] == "fr"          # zweisprachig, Hauptsprache FR
    assert sprachen("BE") == ("de", "fr")     # zweisprachig, Hauptsprache DE
    assert sprachen("GR") == ("de", "it", "rm")
    assert sprachen("ZH") == ("de",)
    # Jeder Kanton bekommt eine Auskunft, auch die ohne Sondereintrag.
    assert all(sprachen(k) for k in KANTON_SAMMLUNG)


def test_die_adresswahl_folgt_der_amtssprache():
    from app.domains.rechtsquellen.kantone import sprachen
    from app.domains.rechtsquellen.lexfind import adresse_aus

    beide = [{"language": "de", "original_url": "D"},
             {"language": "fr", "original_url": "F"}]
    # Freiburg fuehrt Franzoesisch zuerst, Bern Deutsch.
    assert adresse_aus(beide, sprachen("FR")) == "F"
    assert adresse_aus(beide, sprachen("BE")) == "D"
    # Ohne Angabe bleibt es bei der allgemeinen Reihenfolge.
    assert adresse_aus(beide) == "D"


def test_der_befund_nennt_die_gepruefte_sprachfassung():
    """Bundesrecht ist dreisprachig, alle Fassungen sind gleich verbindlich —
    und ihre Auslegung kann auseinandergehen. Ein Beleg ohne Angabe der
    geprüften Fassung sagt, DASS der Artikel existiert, aber nicht, an welchem
    Wortlaut er gemessen wurde."""
    from app.domains.rechtsquellen.artikel import ArtikelPruefer as A

    assert A.sprachfassung("https://www.fedlex.admin.ch/eli/cc/1999/404/de") == "de"
    assert A.sprachfassung("https://www.fedlex.admin.ch/eli/cc/1999/404/fr") == "fr"
    assert A.sprachfassung("https://bgs.so.ch/data/114.2/de") == "de"
    assert A.sprachfassung("https://x.ch/data/1/it") == "it"
    # Wo die Adresse nichts hergibt, wird nichts behauptet.
    assert A.sprachfassung("https://silgeneve.ch/legis/books/RSG/rsg_a2_08") == ""
    assert A.sprachfassung("") == ""


def test_die_sprachfassung_steht_im_befund():
    from app.domains.rechtsquellen.artikel import ArtikelPruefer

    p = ArtikelPruefer(aktiv=False)          # ohne Netz: Zustand nicht prüfbar
    befunde = p.pruefe_fundstelle("https://www.fedlex.admin.ch/eli/cc/1999/404/de",
                                  "Art. 4")
    assert befunde and befunde[0]["sprachfassung"] == "de"


def test_das_bundesrecht_ist_dreisprachig():
    from app.domains.rechtsquellen.kantone import BUND_SPRACHEN

    assert BUND_SPRACHEN == ("de", "fr", "it")   # Englisch ist nicht verbindlich
