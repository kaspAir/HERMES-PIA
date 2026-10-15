"""Beweist: die Vorlagenzuordnung stimmt mit der Referenzvorlage überein.

Gelesen wird die Word-Datei selbst – Tabellenköpfe, Auswahlwerte der
Inhaltssteuerelemente, Fussnoten, Basis- und Beispielzeilen. Eine
ausgetauschte Vorlage macht diesen Test rot, statt dass die Zuordnung still
veraltet (Akzeptanzfall AT18).
"""
import hashlib
import zipfile
from pathlib import Path

import pytest
from lxml import etree

from app.domains.method import vorlagenzuordnung as vz

WURZEL = Path(__file__).resolve().parents[2] / "methods" / "hermes_pia"
REFERENZ = WURZEL / "template" / "referenz" / "PIA_HERMESPIA.docx"
ERZEUGUNG = WURZEL / "template" / "projektinitialisierungsauftrag.dotx"
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _text(el):
    return "".join(t.text or "" for t in el.iter(W + "t"))


def _zellen(tr):
    aus = []
    for kind in tr:
        if kind.tag == W + "tc":
            aus.append(kind)
        elif kind.tag == W + "sdt":
            aus.extend(kind.iter(W + "tc"))
    return aus


def _tabellen_mit_ueberschrift(pfad):
    """[(Überschrift davor, [[Zelltexte je Zeile]], tbl-Element)]."""
    body = etree.fromstring(zipfile.ZipFile(pfad).read("word/document.xml")).find(W + "body")
    aus, ueber = [], ""
    for el in body:
        if el.tag == W + "p":
            ps = el.find(f"{W}pPr/{W}pStyle")
            t = _text(el).strip()
            stil = ps.get(W + "val") if ps is not None else ""
            if t and ("berschrift" in stil or t in ("Änderungskontrolle", "Prüfung", "Freigabe")):
                ueber = t
        elif el.tag == W + "tbl":
            zeilen = [[_text(tc).strip() for tc in _zellen(tr)] for tr in el.findall(W + "tr")]
            aus.append((ueber, zeilen, el))
    return aus


def _auswahl_listen(pfad):
    doc = etree.fromstring(zipfile.ZipFile(pfad).read("word/document.xml"))
    listen = []
    for dd in doc.iter(W + "dropDownList", W + "comboBox"):
        werte = [li.get(W + "displayText") for li in dd.findall(W + "listItem")]
        werte = [w for w in werte if w not in ("Auswählen", "Wählen Sie ein Element aus.")]
        if werte not in listen:
            listen.append(werte)
    return listen


# ---- Die Datei selbst ------------------------------------------------------ #

def test_die_referenzdatei_ist_unveraendert():
    soll = vz.lade()["vorlage"]["sha256"]
    assert hashlib.sha256(REFERENZ.read_bytes()).hexdigest() == soll


def test_erzeugungsvorlage_ist_strukturgleich():
    """Erzeugt wird auf der .dotx. Sie muss dieselben Tabellen mit denselben
    Köpfen und Basiszeilen tragen wie die Referenz – sonst beschreibt die
    Zuordnung eine Vorlage, die gar nicht verwendet wird."""
    ref = [(u, z) for u, z, _ in _tabellen_mit_ueberschrift(REFERENZ)]
    erz = [(u, z) for u, z, _ in _tabellen_mit_ueberschrift(ERZEUGUNG)]
    assert ref == erz


# ---- Auswahlwerte ---------------------------------------------------------- #

@pytest.mark.parametrize("vokabular", [
    "dokument_status", "klassifizierung", "zielkategorie", "prioritaet",
    "eintrittswahrscheinlichkeit", "auswirkungsgrad"])
def test_auswahlwerte_entsprechen_den_steuerelementen(vokabular):
    assert vz.werte(vokabular) in _auswahl_listen(REFERENZ)


def test_die_risikoskalen_tragen_zahlenwerte():
    assert vz.zahlenwert("eintrittswahrscheinlichkeit", "Niedrig = 1") == 1
    assert vz.zahlenwert("auswirkungsgrad", "Hoch = 3") == 3


# ---- Tabellen -------------------------------------------------------------- #

def _tabelle(titel):
    for ueber, zeilen, el in _tabellen_mit_ueberschrift(REFERENZ):
        if ueber == titel:
            return zeilen, el
    raise AssertionError(f"Keine Tabelle unter «{titel}» in der Referenzvorlage")


@pytest.mark.parametrize("kap", [k for k in vz.lade()["kapitel"] if k.get("tabelle")],
                         ids=lambda k: k["id"])
def test_tabellenkoepfe_stimmen(kap):
    zeilen, _ = _tabelle(kap["titel"])
    assert zeilen[0] == kap["tabelle"]["kopf"]
    assert len(kap["tabelle"]["kopf"]) == len(kap["tabelle"]["spalten"])


def test_die_acht_terminzeilen_der_vorlage():
    zeilen, _ = _tabelle("Ergebnisse und Termine")
    # EXAKT verglichen. Eine frühere Fassung verglich nur die Anfänge – und
    # verdeckte damit, dass Zeile 5 falsch abgeschrieben war («mit Checkliste»
    # statt «Checkliste»). Ein Test, der Abweichungen toleriert, prüft sie nicht.
    vorlage = [z[1] for z in zeilen[1:]]
    assert vorlage == vz.basiszeilen("termine")
    assert len(vorlage) == 8


def test_personalaufwand_fuehrt_ag_und_pl():
    zeilen, _ = _tabelle("Personalaufwand")
    assert [z[0] for z in zeilen[1:]] == vz.basiszeilen("personalaufwand")


def test_kap5_hat_neun_monate_und_eine_summenzeile():
    zeilen, _ = _tabelle("Projektorganisation und Personal")
    assert zeilen[0][1:10] == [f"Monat {i}" for i in range(1, 10)]
    assert zeilen[-1][0] == vz.kapitel("projektorganisation")["summenzeile"]["label"]


def test_das_ausgeblendete_risikobeispiel_ist_erfasst():
    """Normalerweise unsichtbar – und gerade deshalb leicht übersehen."""
    _, el = _tabelle("Risiken")
    versteckt = [tr for tr in el.findall(W + "tr")
                 if any(r.find(f"{W}rPr/{W}vanish") is not None and _text(r).strip()
                        for r in tr.iter(W + "r"))]
    assert len(versteckt) == 1
    assert "Jurist" in _text(versteckt[0])
    assert any(b.get("ausgeblendet") for b in vz.beispiele("risiken"))


def test_die_beispiele_der_vorlage_werden_erkannt():
    assert vz.ist_beispiel("projektorganisation", {"rolle_person": "AG / Hans Meier"})
    assert vz.ist_beispiel("vorgaben_methoden", {"titel": "Dokumentation",
                                                 "vorgabe": "MS Office Palette gem. Vorlage"})
    assert not vz.ist_beispiel("vorgaben_methoden", {"titel": "Dokumentation",
                                                     "vorgabe": "SharePoint der Dienststelle"})


# ---- Fussnoten ------------------------------------------------------------- #

def test_fussnoten():
    fn = etree.fromstring(zipfile.ZipFile(REFERENZ).read("word/footnotes.xml"))
    texte = {f.get(W + "id"): _text(f).strip() for f in fn.findall(W + "footnote")}
    for nr, text in vz.lade()["fussnoten"].items():
        assert texte[str(nr)] == text


# ---- Rechenregeln ---------------------------------------------------------- #

def test_risikozahl_aus_den_vorlagenwerten():
    assert vz.risikozahl("Hoch = 3", "Mittel = 2") == 6


def test_unbekannt_ist_null_nicht_null():
    """Unbekannt ist None – nicht 0 und nicht automatisch «Tief»."""
    assert vz.risikozahl("Hoch = 3", None) is None
    assert vz.risikozahl("Auswählen", "Tief = 1") is None
    assert vz.risikozahl("Wählen Sie ein Element aus.", "Tief = 1") is None


def test_eindeutige_altwerte_werden_abgebildet():
    assert vz.auswahlwert("eintrittswahrscheinlichkeit", "Tief") == "Niedrig = 1"
    assert vz.auswahlwert("klassifizierung", "Intern") == "INTERN"


def test_mehrdeutige_altwerte_werden_nicht_geraten():
    """«in Pruefung» ist nicht «geprüft», «freigegeben» nicht «abgenommen»."""
    assert vz.auswahlwert("dokument_status", "in Pruefung") is None
    assert vz.auswahlwert("dokument_status", "freigegeben") is None


# ---- method.yaml folgt der Zuordnung -------------------------------------- #

def test_method_yaml_fuehrt_die_auswahlwerte_der_vorlage():
    """Zwei Orte, ein Stand: weicht method.yaml ab, extrahiert das Interview
    Werte, die das Dokument nicht kennt."""
    import yaml
    methode = yaml.safe_load((WURZEL / "method.yaml").read_text(encoding="utf-8"))
    for name, werte in methode["vocabularies"].items():
        assert werte == vz.werte(name), name


def test_keine_pflicht_je_zielkategorie_mehr():
    """Die Vorlage verlangt nicht je Kategorie ein Ziel (Auftrag 4.2)."""
    import yaml
    methode = yaml.safe_load((WURZEL / "method.yaml").read_text(encoding="utf-8"))
    ziele = next(s for s in methode["sections"] if s["id"] == "ziele")
    kriterien = " ".join(ziele["interview"]["completeness"]).lower()
    assert "systemziel" not in kriterien and "vorgehensziel" not in kriterien
