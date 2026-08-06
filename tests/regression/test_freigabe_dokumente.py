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
