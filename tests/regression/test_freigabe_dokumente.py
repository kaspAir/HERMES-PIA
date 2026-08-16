"""Beweist: Checkliste und Entscheidliste werden als Word-Dokument richtig gefüllt.

Zwei Dokumente, zwei Füllarten – und der Unterschied ist fachlich:

* Die **Checkliste** ist eine Momentaufnahme: sie bekommt genau die Zeilen,
  die bewertet wurden, die Beispielzeilen der Vorlage verschwinden.
* Die **Liste Projektentscheide Steuerung** ist ein Register über das ganze
  Projekt: die vorgedruckten HERMES-Entscheide bleiben stehen, eingetragen
  wird nur das Datum des Entscheids, der wirklich gefallen ist. Wer die
  künftigen Zeilen löschte, machte aus dem Register eine Quittung.

**Warum diese Tests mit `_row_cells` lesen und nicht mit `table.rows[i].cells`:**
Die Spalte «Bewertung» ist in der Vorlage ein Auswahlfeld – im XML eine
`<w:sdt>`-umhüllte Zelle. Der schlichte Zellenleser überspringt sie, alle
folgenden Spalten erscheinen dann um eins verschoben. Beim Bauen sah das
Ergebnis deshalb kaputt aus, obwohl das Dokument stimmte: nicht der Erzeuger
war falsch, sondern die Prüfung.
"""
from docx import Document

from app.domains.freigabe import dokumente as dk
from app.domains.generation.service import _row_cells, _tc_text


def _zeilen(puffer, ueberschrift):
    """Die Tabelle unter einer Überschrift als Liste von Zelltexten."""
    doc = Document(puffer)
    tbl = dk._tabelle_nach(doc, ueberschrift)
    assert tbl is not None, f"Tabelle unter «{ueberschrift}» nicht gefunden"
    return [[_tc_text(c) for c in _row_cells(r)]
            for r in tbl if r.tag == dk.W_TR]


_BEWERTET = {
    "generell": [
        {"nr": "G-01", "pruefpunkt": "Projektinitialisierungsauftrag",
         "kriterium": "… unterschrieben vor?", "bewertung": "zu bestätigen",
         "erlaeuterung": "Eine freigegebene Fassung wurde hochgeladen."},
        {"nr": "G-02", "pruefpunkt": "", "kriterium": "Ressourcen …?",
         "bewertung": "erfüllt", "erlaeuterung": "Kapitel 3.1 weist 5 Rollen aus."},
    ],
    "organisation": [
        {"nr": "O-01", "pruefpunkt": "Dokumentenablage",
         "kriterium": "Ist die Vorgabe geklärt?", "bewertung": "erfüllt",
         "erlaeuterung": ""}],
    "projekt": [],
}


# ---- Checkliste ----------------------------------------------------------- #

def test_die_vorlagen_liegen_im_repo():
    assert dk.CHECKLISTE_VORLAGE.exists(), dk.CHECKLISTE_VORLAGE
    assert dk.ENTSCHEIDE_VORLAGE.exists(), dk.ENTSCHEIDE_VORLAGE


def test_die_bewertung_landet_in_der_richtigen_spalte():
    """Das Auswahlfeld ist eine SDT-Zelle – genau dort verrutscht es sonst."""
    zeilen = _zeilen(dk.checkliste_docx(_BEWERTET), "Generelle Prüfpunkte")
    kopf = zeilen[0]
    assert kopf == ["Nr.", "Prüfpunkt", "Kriterium", "Bewertung",
                    "Erläuterung", "Verantwortlich", "Datum"]
    g01 = zeilen[1]
    assert g01[0] == "G-01"
    assert g01[3] == "zu bestätigen"           # nicht verschoben
    assert g01[4].startswith("Eine freigegebene Fassung")


def test_nur_die_bewerteten_zeilen_stehen_drin():
    zeilen = _zeilen(dk.checkliste_docx(_BEWERTET), "Generelle Prüfpunkte")
    assert len(zeilen) == 3                    # Kopf + G-01 + G-02
    assert [z[0] for z in zeilen[1:]] == ["G-01", "G-02"]


def test_die_beispielzeilen_der_vorlage_verschwinden():
    """Die Vorlage bringt sechs Musterzeilen mit – sie dürfen nicht bleiben."""
    zeilen = _zeilen(dk.checkliste_docx(_BEWERTET), "Generelle Prüfpunkte")
    assert not any("Auswählen" in z[3] for z in zeilen[1:])


def test_ein_leeres_kapitel_behaelt_keine_platzhalter():
    """Kapitel 1.3 ist leer – «…» und «tt.mm.jjjj» gehören nicht ins Dokument."""
    zeilen = _zeilen(dk.checkliste_docx(_BEWERTET), "Projektspezifische Prüfpunkte")
    flach = " ".join(w for z in zeilen for w in z)
    assert "tt.mm.jjjj" not in flach
    assert "…" not in flach


def test_verantwortlich_und_datum_kommen_aus_der_freigabe():
    puffer = dk.checkliste_docx(_BEWERTET, kopf={"verantwortlich": "A. Brèche",
                                                 "datum": "06.08.2026"})
    g01 = _zeilen(puffer, "Generelle Prüfpunkte")[1]
    assert g01[5] == "A. Brèche" and g01[6] == "06.08.2026"


def test_eine_eigene_angabe_schlaegt_die_der_freigabe():
    eigen = {"generell": [dict(_BEWERTET["generell"][0],
                               verantwortlich="Herr Beispiel", datum="01.09.2026")],
             "organisation": [], "projekt": []}
    g01 = _zeilen(dk.checkliste_docx(eigen, kopf={"verantwortlich": "A. Brèche",
                                                  "datum": "06.08.2026"}),
                  "Generelle Prüfpunkte")[1]
    assert g01[5] == "Herr Beispiel" and g01[6] == "01.09.2026"


def test_ohne_zeilen_bleibt_das_dokument_heil():
    puffer = dk.checkliste_docx({"generell": [], "organisation": [], "projekt": []})
    assert _zeilen(puffer, "Generelle Prüfpunkte")


# ---- Liste Projektentscheide Steuerung ------------------------------------ #

class _Entscheid:
    def __init__(self, nr="01", datum="2026-09-01", traeger="Auftraggeber"):
        self.nr = nr
        self.entscheidungsdatum = datum
        self.entscheidungstraeger = traeger


def test_das_datum_landet_bei_der_richtigen_zeile():
    zeilen = _zeilen(dk.entscheide_docx([_Entscheid()]), "Projektentscheide Steuerung")
    nach_nr = {z[0]: z for z in zeilen[1:] if z and z[0]}
    assert nach_nr["01"][4] == "01.09.2026"
    assert nach_nr["02"][4] == ""              # noch nicht entschieden


def test_die_kuenftigen_entscheide_bleiben_stehen():
    """Das Register läuft über das ganze Projekt – nicht nur über heute."""
    zeilen = _zeilen(dk.entscheide_docx([_Entscheid()]), "Projektentscheide Steuerung")
    nummern = [z[0] for z in zeilen[1:] if z and z[0]]
    assert "02" in nummern          # Durchführungsfreigabe
    assert "16" in nummern          # Projektabschluss


def test_kein_datums_platzhalter_bleibt_uebrig():
    zeilen = _zeilen(dk.entscheide_docx([_Entscheid()]), "Projektentscheide Steuerung")
    assert not any("tt.mm.jjjj" in w for z in zeilen for w in z)


def test_das_datum_erscheint_in_schweizer_schreibweise():
    assert dk._als_datum("2026-09-01") == "01.09.2026"
    assert dk._als_datum("") == ""
    assert dk._als_datum("01.09.2026") == "01.09.2026"      # schon so – unverändert


def test_ohne_entscheide_bleibt_das_register_leer_aber_heil():
    zeilen = _zeilen(dk.entscheide_docx([]), "Projektentscheide Steuerung")
    assert len(zeilen) > 10
    assert not any("tt.mm.jjjj" in w for z in zeilen for w in z)


# ---- Die Risikonummer steht nicht in den Daten ---------------------------- #

def test_der_vorschlag_nennt_die_risikonummer():
    """Gemessen: die Vorschläge hiessen «Risiko ?».

    Die Nummer entsteht erst beim Erzeugen des Dokuments aus der Position in
    der Tabelle – in den gespeicherten Zeilen steht sie nicht. Wer sie aus der
    Zeile lesen will, bekommt nichts.
    """
    from app.domains.freigabe.pruefpunkte import projektspezifische_vorschlaege

    wissen = {"risiken": {"extracted": [
        {"beschreibung": "Erstes Risiko", "risikozahl": "4",
         "massnahmen": "Erste Massnahme."},
        {"beschreibung": "Zweites Risiko", "risikozahl": "9",
         "massnahmen": "Zweite Massnahme."},
    ]}}
    vorschlaege = projektspezifische_vorschlaege(wissen)
    assert "?" not in " ".join(v["pruefpunkt"] for v in vorschlaege)
    # Nach Risikozahl sortiert (9 vor 4), aber mit der Nummer der TABELLE.
    assert vorschlaege[0]["pruefpunkt"] == "Risiko 02"
    assert vorschlaege[1]["pruefpunkt"] == "Risiko 01"


def test_eine_vorhandene_nummer_wird_bevorzugt():
    from app.domains.freigabe.pruefpunkte import projektspezifische_vorschlaege

    wissen = {"risiken": {"extracted": [
        {"nr": "07", "beschreibung": "Ein Risiko", "massnahmen": "Eine Massnahme."}]}}
    assert projektspezifische_vorschlaege(wissen)[0]["pruefpunkt"] == "Risiko 07"


# ---- Der gemeinsame Dokumentenkopf ---------------------------------------- #
#
# «Diese haben ja (Dokumente) alle denselben Kopf. Dieser muss natürlich immer
# ausgefüllt werden.» Genau deshalb liegt er in einem eigenen Modul: was bei
# jedem Dokument passiert, wird sonst bei jedem Dokument neu falsch gemacht.

_ANGABEN = {
    "projektname": "BKI Test 8 / 001-25", "projektnummer": "001-25",
    "datum": "06.08.2026", "version": "0.1", "status": "in Arbeit",
    "klassifizierung": "Nicht klassifiziert", "autor": "Amélie Brèche",
    "projektleiter": "Amélie Brèche", "auftraggeber": "Max Mustermann",
    "verwaltungseinheit": "Testamt", "geschaeftsbereich": "Generalsekretariat",
    "innenauftragsnummer": "IA-42",
}

_ABSCHNITTE = [
    {"id": "referenzierte_dokumente", "title": "Referenzierte Dokumente",
     "type": "table", "columns": [{"id": "nr", "label": "Nr."},
                                  {"id": "name", "label": "Name"},
                                  {"id": "link", "label": "Nummer / Link"}]},
    {"id": "vorgaben_methoden", "title": "Vorgaben, Methoden und Werkzeuge",
     "type": "table", "columns": [{"id": "titel", "label": "Titel"},
                                  {"id": "vorgabe", "label": "Vorgabe / Methode / Werkzeug"},
                                  {"id": "version", "label": "Version"}]},
]

_WISSEN = {
    "referenzierte_dokumente": {"extracted": [{"name": "ZertES"}, {"name": "BöB"}]},
    "vorgaben_methoden": {"extracted": [
        {"titel": "Projektmanagementmethode", "vorgabe": "HERMES 2022",
         "version": "2022"}]},
}


def _text(puffer):
    from app.domains.generation.service import _p_text

    doc = Document(puffer)
    W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"
    return "\n".join(_p_text(p) for p in doc.element.body.iter(W))


def test_der_kopf_wird_ausgefuellt():
    inhalt = _text(dk.checkliste_docx(_BEWERTET, angaben=_ANGABEN))
    for wert in ("BKI Test 8 / 001-25", "06.08.2026", "Amélie Brèche",
                 "Max Mustermann", "Testamt", "Generalsekretariat", "IA-42"):
        assert wert in inhalt, wert


def test_die_magenta_platzhalter_verschwinden():
    """Rückmeldung: «Auch sollten in allen Ergebnissen die magenta Einträge
    raus sein.» Regieanweisungen gehören in die Vorlage, nicht ins Dokument."""
    inhalt = _text(dk.checkliste_docx(_BEWERTET, angaben=_ANGABEN))
    assert "Projektname / Projektnummer" not in inhalt
    assert "bei Bedarf anpassen" not in inhalt


def test_die_gemeinsamen_kapitel_kommen_aus_dem_pia():
    """Diese Daten sind bereits erhoben – sie ein zweites Mal zu erfragen
    wäre eine Zumutung, sie wegzulassen eine Lücke."""
    puffer = dk.checkliste_docx(_BEWERTET, angaben=_ANGABEN,
                                abschnitte=_ABSCHNITTE, wissen=_WISSEN)
    referenzen = _zeilen(puffer, "Referenzierte Dokumente")
    assert [z[1] for z in referenzen[1:]] == ["ZertES", "BöB"]
    vorgaben = _zeilen(puffer, "Vorgaben, Methoden und Werkzeuge")
    assert vorgaben[1][:3] == ["Projektmanagementmethode", "HERMES 2022", "2022"]


def test_ohne_projektwissen_bleibt_die_vorlage_stehen():
    """Nichts erfinden: fehlt die Angabe, wird sie nicht ersetzt."""
    puffer = dk.checkliste_docx(_BEWERTET, angaben=_ANGABEN)
    assert _zeilen(puffer, "Definitionen und Abkürzungen")


def test_der_entscheidungstraeger_traegt_den_namen():
    """«Der Name des Auftraggebers ist ja auch bekannt.»"""
    zeilen = _zeilen(dk.entscheide_docx([_Entscheid()], angaben=_ANGABEN),
                     "Projektentscheide Steuerung")
    eins = [z for z in zeilen if z and z[0] == "01"][0]
    assert eins[3] == "Auftraggeber (Max Mustermann)"


def test_ohne_namen_bleibt_die_rolle_allein_stehen():
    zeilen = _zeilen(dk.entscheide_docx([_Entscheid()]), "Projektentscheide Steuerung")
    eins = [z for z in zeilen if z and z[0] == "01"][0]
    assert eins[3] == "Auftraggeber"


# ---- Der Rückweg ---------------------------------------------------------- #

def test_die_bearbeitete_checkliste_wird_zurueckgelesen():
    puffer = dk.checkliste_docx(_BEWERTET, kopf={"verantwortlich": "PL",
                                                 "datum": "06.08.2026"})
    gelesen = dk.checkliste_aus_docx(puffer.read())
    assert gelesen["generell"]["G-01"]["bewertung"] == "zu bestätigen"
    assert gelesen["generell"]["G-02"]["bewertung"] == "erfüllt"
    assert gelesen["generell"]["G-01"]["verantwortlich"] == "PL"


def test_die_uebernahme_ersetzt_nur_die_menschlichen_spalten():
    bestand = {"generell": [{"nr": "G-01", "kriterium": "Die Frage?",
                             "bewertung": "", "erlaeuterung": ""}],
               "organisation": [], "projekt": []}
    gelesen = {"generell": {"G-01": {"bewertung": "erfüllt",
                                     "erlaeuterung": "belegt durch X",
                                     "verantwortlich": "PL", "datum": "06.08.2026"}}}
    neu, geaendert = dk.uebernimm(bestand, gelesen)
    zeile = neu["generell"][0]
    assert zeile["bewertung"] == "erfüllt" and zeile["erlaeuterung"] == "belegt durch X"
    assert zeile["kriterium"] == "Die Frage?"       # die Frage bleibt die Frage
    assert geaendert == 4


def test_eine_geleerte_zelle_loescht_nichts():
    """Ein Ausdruck ohne Bewertung wäre sonst eine Löschung."""
    bestand = {"generell": [{"nr": "G-01", "bewertung": "erfüllt"}],
               "organisation": [], "projekt": []}
    neu, geaendert = dk.uebernimm(bestand, {"generell": {"G-01": {"bewertung": ""}}})
    assert neu["generell"][0]["bewertung"] == "erfüllt"
    assert geaendert == 0


def test_eine_im_word_entfernte_zeile_verschwindet_nicht_still():
    bestand = {"generell": [{"nr": "G-01", "bewertung": "erfüllt"},
                            {"nr": "G-02", "bewertung": "erfüllt"}],
               "organisation": [], "projekt": []}
    neu, _ = dk.uebernimm(bestand, {"generell": {"G-01": {"bewertung": "teilweise erfüllt"}}})
    assert len(neu["generell"]) == 2
    assert neu["generell"][1]["nr"] == "G-02"


def test_ein_fremdes_dokument_wirft_nichts_um():
    gelesen = dk.checkliste_aus_docx(dk.entscheide_docx([]).read())
    assert gelesen == {} or not any(gelesen.values())


# ---- Die Anrede folgt der Person ------------------------------------------ #
#
# «Das System erkennt ja, ob es sich bei der Person um einen Mann oder eine
# Frau handelt. Es sollte also Projektleiterin und Autorin bzw. Auftraggeber
# schreiben. Im PIA funktioniert das jedenfalls...» – Es funktionierte dort,
# weil die PIA-Ausgabe das Geschlecht ermittelt und mitgibt. Der gemeinsame
# Kopf tat das nicht; die Vorlage behielt ihre Doppelformen.

def _erkenner(name):
    return "w" if name.startswith("Am") else "m"


def _kopf_mit_anrede(**kwargs):
    from app.domains.dokumentenkopf import kopf as kopfmodul

    grund = {"vorrang": {"projektleiter": "Amélie Brèche",
                         "auftraggeber": "Max Mustermann",
                         "projektname": "BKI Test 8 / 001-25"},
             "erkenne_geschlecht": _erkenner}
    grund.update(kwargs)
    return kopfmodul.metadaten(**grund)


def test_die_doppelformen_werden_aufgeloest():
    inhalt = _text(dk.checkliste_docx(_BEWERTET, angaben=_kopf_mit_anrede()))
    assert "AutorinAmélie Brèche" in inhalt
    assert "ProjektleiterinAmélie Brèche" in inhalt
    assert "AuftraggeberMax Mustermann" in inhalt
    assert "Projektleiter/in" not in inhalt
    assert "Autor/-in" not in inhalt


def test_ohne_erkennung_bleibt_die_doppelform_stehen():
    """Geraten wird nicht: unklar heisst, die Vorlage behält ihre Form."""
    inhalt = _text(dk.checkliste_docx(
        _BEWERTET, angaben=_kopf_mit_anrede(erkenne_geschlecht=None)))
    assert "Projektleiter/in" in inhalt


def test_ein_name_kostet_nur_eine_abfrage():
    """Jede Abfrage ist ein Modellaufruf – Autor und Projektleitung sind
    dieselbe Person, also wird einmal gefragt, nicht zweimal."""
    gefragt = []

    def zaehlend(name):
        gefragt.append(name)
        return "w"

    _kopf_mit_anrede(erkenne_geschlecht=zaehlend)
    assert gefragt.count("Amélie Brèche") == 1


def test_die_kurzformen_stehen_ebenfalls_bereit():
    angaben = _kopf_mit_anrede()
    assert angaben["projektleiter_weiblich"] is True
    assert angaben["auftraggeber_weiblich"] is False
