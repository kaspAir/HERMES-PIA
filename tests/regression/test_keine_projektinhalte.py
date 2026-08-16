"""Beweist: HERMES PIA kennt METHODEN, keine Projektinhalte.

Der Grundsatz, um den es geht: **die Anwendung muss für jedes Projekt gleich
gut funktionieren, unabhängig von seinem Gegenstand.** Ein Schulhausbau, eine
Fachanwendung, eine Betriebsablösung und ein Registerprojekt durchlaufen
dieselbe Methode. Sobald eine Regel oder eine Modellanweisung ein bestimmtes
Sachgebiet nennt, kippt das:

  * Als Beispiel in einem Prompt **lenkt** ein Sachgebiet jedes Vorhaben in
    diese Richtung. Gemessen stand in der Rechtsgrundlagen-Anweisung «z.B. im
    Justiz-/Strafregisterumfeld StReG/StReV, StGB, StPO» – ein Schulhausbau
    hätte damit einen Anstoss Richtung Strafrecht bekommen.
  * Als Bedingung in einer Regel **wirkt sie nur beim getesteten Fall** und
    schweigt bei allen anderen. Eine Sperre, die den Einzelfall erkennt statt
    die Struktur, ist wertlos: sie meldet genau das, was ohnehin schon
    aufgefallen ist.

**Was erlaubt ist**, und warum es kein Widerspruch ist: die Methode selbst
(HERMES-Begriffe), das Vokabular des schweizerischen Rechtssystems
(Normstufen, Kantone, Sammlungen) und Querschnittsrecht, das für JEDES
Verwaltungsvorhaben gilt (Datenschutz, Beschaffung, Archivierung). Das ist
allgemeines Wissen über den Kontext, kein Wissen über ein bestimmtes Projekt.

**Kommentare und Doku dürfen den Auslöser nennen** – dort steht der Beleg,
warum eine Regel existiert. Geprüft wird nur der ausführbare Code.
"""
import ast
import re
from pathlib import Path

import pytest

from app.config import BASE_DIR

# Begriffe, die den GEGENSTAND eines Projekts bezeichnen. Sie stammen aus den
# bisher gemessenen Testfaellen und aus benachbarten Sachgebieten - gerade die
# nicht getesteten sind wichtig, damit der Waechter nicht selbst zum Einzelfall
# wird.
PROJEKTINHALTE = (
    # aus den gemessenen Faellen
    "gesichtserkenn", "biometr", "demonstration", "videoüberwach",
    "strafregister", "dna-profil", "streg", "strev",
    # benachbarte Sachgebiete, die genauso wenig hineingehoeren
    "schulhaus", "spital", "krankenkasse", "steuererklärung", "baubewilligung",
    "einbürgerung", "asylverfahren", "führerausweis", "grundbuch",
    "betreibung", "sozialhilfe", "arbeitslosen",
)

# Diese Dateien sind Katalogdaten oder Attrappen, keine Regeln.
AUSNAHMEN = {"kantone.py"}


def _codezeilen(pfad):
    """Der ausführbare Code ohne Kommentare und ohne Docstrings."""
    quelle = pfad.read_text(encoding="utf-8")
    try:
        baum = ast.parse(quelle)
    except SyntaxError:
        return ""
    # Docstrings entfernen: sie tragen die Begründung, nicht die Regel.
    docstrings = set()
    for knoten in ast.walk(baum):
        if isinstance(knoten, (ast.Module, ast.ClassDef, ast.FunctionDef,
                               ast.AsyncFunctionDef)):
            d = ast.get_docstring(knoten, clean=False)
            if d:
                docstrings.add(d)
    ohne_kommentar = "\n".join(
        z for z in quelle.splitlines() if not z.lstrip().startswith("#"))
    for d in docstrings:
        ohne_kommentar = ohne_kommentar.replace(d, "")
    return ohne_kommentar


ANWENDUNGSDATEIEN = [p for p in Path(BASE_DIR, "app").rglob("*.py")
                     if p.name not in AUSNAHMEN]


def test_es_gibt_ueberhaupt_dateien_zu_pruefen():
    assert len(ANWENDUNGSDATEIEN) > 20


@pytest.mark.parametrize("pfad", ANWENDUNGSDATEIEN,
                         ids=lambda p: str(p.relative_to(Path(BASE_DIR, "app"))))
def test_kein_projektinhalt_im_ausfuehrbaren_code(pfad):
    """Keine Regel und keine Modellanweisung nennt ein Sachgebiet."""
    code = _codezeilen(pfad).lower()
    gefunden = [w for w in PROJEKTINHALTE if w in code]
    assert not gefunden, (
        f"{pfad.name} nennt Projektinhalte im Code: {gefunden}. "
        "Regeln und Prompts beschreiben die METHODE – der Inhalt kommt aus dem "
        "PIA. Als Beispiel in einem Prompt lenkt ein Sachgebiet jedes andere "
        "Projekt in diese Richtung; als Bedingung in einer Regel wirkt es nur "
        "beim getesteten Fall.")


def test_die_sperren_der_rechtsgrundlagen_pruefen_struktur():
    """Stichprobe am schärfsten Fall: die Sperren dürfen ausschliesslich
    strukturelle Angaben vergleichen – Eingriffstiefe gegen Normstufe,
    Schranke gegen Ermächtigung, Lückenart."""
    from app.domains.ergebnisse.rechtsgrundlagen import kette

    quelle = _codezeilen(Path(kette.__file__))
    sperren_code = quelle[quelle.index("def sperren"):]
    # Was der Vergleich benutzt, sind Felder – keine Sachbegriffe.
    for feld in ("eingriff", "normstufe", "ermaechtigt", "kerngehalt_verletzt",
                 "luecke"):
        assert feld in sperren_code
    # Und die Regel gilt fuer jedes Sachgebiet gleich: derselbe Befund bei
    # voellig verschiedenen Taetigkeiten.
    def fall(taetigkeit):
        return [{
            "taetigkeit": {"taetigkeit": taetigkeit},
            "kartierung": {"eingriff": {"tiefe": "schwer"},
                           "grundlagen": [{"erlass": "Weisung", "normstufe": "richtlinie",
                                           "ermaechtigt": True}],
                           "luecke": {"art": "keine"}},
            "wuerdigung": {"ergebnis": "zulässig"},
        }]

    for taetigkeit in ("Eine Baubewilligung verweigern",
                       "Sozialhilfedaten an die Gemeinde bekanntgeben",
                       "Ein Fahrzeug amtlich stilllegen",
                       "Eine Prüfungsleistung automatisiert bewerten"):
        muss = [m for m in kette.sperren(fall(taetigkeit)) if m["gewicht"] == "Muss"]
        assert muss, f"Die Regel muss auch hier greifen: {taetigkeit}"


def test_methodenbegriffe_bleiben_erlaubt():
    """Gegenprobe: der Wächter darf die Methode nicht mitverbieten. HERMES-
    Begriffe und das Vokabular des Rechtssystems gehören ausdrücklich hinein."""
    erlaubt = ("hermes", "projektinitialisierungsauftrag", "datenschutz",
               "beschaffung", "verordnung", "gesetz", "kanton")
    for wort in erlaubt:
        assert not any(wort in w or w in wort for w in PROJEKTINHALTE), wort
