"""Beweist: die vierschichtige Rechtsgrundlagen-Kette – tätigkeitsweise.

Der Auslöser ist ein gemessener Fall (BKI Test 6): ein PIA für ein Vorhaben zur
biometrischen Massenüberwachung von Demonstrierenden. Die Analyse gab eine
FALSCHE ENTWARNUNG — «Keine Lücke identifiziert. Für die im Projekt geplanten
Tätigkeiten besteht nach dieser Analyse eine Rechtsgrundlage.»

Zwei Ursachen, die diese Tests festhalten:

  1. Geprüft wurden die *Ziele der Phase Initialisierung* («Analysen erstellen»).
     Darauf ist «keine Lücke» logisch richtig — und methodisch wertlos. Die
     Einheit der Prüfung muss die TÄTIGKEIT des Vorhabens sein.
  2. Von vier vorhandenen Skills lief einer. Ob eine Grundlage GENÜGT,
     entscheidet die Würdigung; die lief nie.
"""
import json

import pytest

from app.domains.ergebnisse.rechtsgrundlagen import kette


@pytest.fixture
def skills_dir(tmp_path):
    """Attrappen mit demselben Vertrag wie die echten vier Skills."""
    for name in (kette.SKILL_KARTIERUNG, kette.SKILL_GAP,
                 kette.SKILL_WUERDIGUNG, kette.SKILL_OPTIONEN):
        d = tmp_path / "base" / name
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(
            f'---\nname: {name}\nversion: "1.0"\napplies_to: {kette.BEREICH}\n---\n\n'
            f"METHODE-{name.upper()}\n", encoding="utf-8")
    fremd = tmp_path / "base" / "pia-pruefung-auftraggeber"
    fremd.mkdir(parents=True)
    (fremd / "SKILL.md").write_text(
        '---\nname: pia-pruefung-auftraggeber\nversion: "1.0"\n'
        "applies_to: projektinitialisierungsauftrag\n---\n\nFREMD\n", encoding="utf-8")
    return tmp_path


class _LLM:
    def __init__(self, antwort):
        self.antwort = antwort if isinstance(antwort, str) else json.dumps(antwort)
        self.system = None
        self.user = None

    def complete(self, system, messages, max_tokens=1024, timeout=None, **kw):
        self.system = system
        self.user = messages[0]["content"]
        return self.antwort


class _Wissen:
    """Der gemessene Fall: das Entscheidende steht in der Ausgangslage."""
    ebene = "Kanton"
    kanton = "St. Gallen"

    def ausgangslage_text(self):
        return ("Der Kanton beabsichtigt, kantonsweite Personenüberwachungen "
                "einzuführen: flächendeckende Videokameras mit "
                "Gesichtserkennungssoftware, um Personen zu identifizieren, die "
                "Demonstrationen vorbereiten oder daran teilnehmen.")

    def rahmenbedingungen(self):
        return [{"vorgabe": "Anforderungen an die Rechtsgrundlage für "
                            "biometrische Massenüberwachung"}]

    def ziel_beschreibungen(self):
        # Genau der Stolperstein: die Phasenziele sind harmlos.
        return ["Rechtsgrundlagenanalyse erstellen",
                "Schutzbedarfsanalyse erstellen"]

    def genannte_rechtsgrundlagen(self):
        return ["Polizeigesetz des Kantons St. Gallen"]


# ---- Schicht 0: die Einheit der Prüfung ---------------------------------- #

def test_die_ausgangslage_geht_mit_nicht_nur_die_ziele(skills_dir):
    """Der Kern des Fehlers: die Analyse sah nur «Analysen erstellen» und
    antwortete darauf völlig richtig mit «keine Lücke»."""
    llm = _LLM({"taetigkeiten": [], "nicht_erkennbar": []})
    kette.taetigkeiten(_Wissen(), llm, skills_dir=skills_dir)

    assert "Gesichtserkennungssoftware" in llm.user, "die Ausgangslage muss mit"
    assert "biometrische Massenüberwachung" in llm.user, "die Rahmenbedingungen auch"
    assert "Rechtsgrundlagenanalyse erstellen" in llm.user
    # Und die Anweisung, das Vorhaben zu meinen – nicht die Phase.
    assert "nicht die Ergebnisse der Projektphase" in llm.user


def test_jede_schicht_bekommt_nur_ihren_skill(skills_dir):
    """Die Schichtengrenze ist die Methode: die Gap-Analyse darf nicht würdigen,
    die Würdigung keine Optionen entwickeln."""
    faelle = [
        (lambda l: kette.taetigkeiten(_Wissen(), l, skills_dir=skills_dir),
         kette.SKILL_KARTIERUNG),
        (lambda l: kette.kartiere([{"taetigkeit": "T"}], _Wissen(), l,
                                  skills_dir=skills_dir), kette.SKILL_KARTIERUNG),
        (lambda l: kette.analysiere_luecke([{"nr": 0, "taetigkeit": "T"}], _Wissen(),
                                           l, skills_dir=skills_dir), kette.SKILL_GAP),
        (lambda l: kette.wuerdige([{"nr": 0, "taetigkeit": "T"}], l,
                                  skills_dir=skills_dir), kette.SKILL_WUERDIGUNG),
        (lambda l: kette.entwickle_optionen([{"nr": 0, "taetigkeit": "T"}], l,
                                            skills_dir=skills_dir), kette.SKILL_OPTIONEN),
    ]
    for aufruf, erwartet in faelle:
        llm = _LLM({})
        _, versionen, _ = aufruf(llm)
        assert f"METHODE-{erwartet.upper()}" in llm.system, erwartet
        # Kein anderer Skill der Kette darf hereingeraten.
        for anderer in (kette.SKILL_KARTIERUNG, kette.SKILL_GAP,
                        kette.SKILL_WUERDIGUNG, kette.SKILL_OPTIONEN):
            if anderer != erwartet:
                assert f"METHODE-{anderer.upper()}" not in llm.system
        assert "FREMD" not in llm.system          # applies_to trennt hart
        assert versionen and versionen[0]["name"] == erwartet


def test_ohne_skill_kein_ergebnis(tmp_path):
    """Lieber kein Ergebnis als ein im Code nachgebautes."""
    daten, versionen, grund = kette.kartiere([], _Wissen(), _LLM({}),
                                             skills_dir=tmp_path)
    assert daten is None and versionen == [] and "nicht gefunden" in grund


# ---- Die Sperren: was der Code entscheidet ------------------------------- #

def test_schrankennorm_ist_nie_eine_ermaechtigung():
    for name in ("Bundesverfassung (BV)", "Europäische Menschenrechtskonvention",
                 "EMRK", "Kantonsverfassung des Kantons St. Gallen"):
        assert kette.ist_schrankennorm(name), name
    assert not kette.ist_schrankennorm("Polizeigesetz des Kantons St. Gallen")
    assert not kette.ist_schrankennorm("Bundesgesetz über den Datenschutz")


def test_verfassung_als_grundlage_ist_ein_muss_befund():
    """Gemessen: BV und EMRK standen als «Bestehende Rechtsgrundlage» Nr. 01
    und 02 über einem Überwachungsvorhaben. Das liest sich wie eine Erlaubnis."""
    befunde = [{
        "taetigkeit": {"taetigkeit": "Biometrische Erfassung im öffentlichen Raum"},
        "kartierung": {
            "eingriff": {"tiefe": "schwer", "grundrechte": ["Art. 13 BV"]},
            "grundlagen": [{"erlass": "Bundesverfassung (BV)", "normstufe": "verfassung",
                            "ermaechtigt": True}],
        },
    }]
    meldungen = kette.sperren(befunde)
    assert any("ermächtigt nicht" in m["meldung"] for m in meldungen)
    assert all(m["gewicht"] == "Muss" for m in meldungen)


def test_schwerer_eingriff_ohne_formelles_gesetz_blockiert():
    """Der Stufenvergleich ist ein Vergleich, kein Urteil, und gehört deshalb
    in den Code. Welche NORM dabei zitiert wird, hängt davon ab, was berührt
    ist – hier ohne Grundrechtsbezug, also das Legalitätsprinzip."""
    befunde = [{
        "taetigkeit": {"taetigkeit": "Eine Bewilligungspflicht einführen"},
        "kartierung": {
            "eingriff": {"tiefe": "schwer", "grundrechte": []},
            "grundlagen": [{"erlass": "Weisung des Amtes", "normstufe": "verordnung",
                            "ermaechtigt": True}],
        },
    }]
    meldungen = kette.sperren(befunde)
    assert any("Legalitätsprinzip" in m["meldung"] for m in meldungen)

    # Mit einem formellen Gesetz faellt der Befund weg.
    befunde[0]["kartierung"]["grundlagen"] = [
        {"erlass": "Ein Gesetz", "normstufe": "gesetz", "ermaechtigt": True}]
    assert not [m for m in kette.sperren(befunde) if m["gewicht"] == "Muss"]


def test_stufenvergleich():
    assert kette.stufe_reicht("gesetz", "gesetz")
    assert kette.stufe_reicht("verfassung", "gesetz")
    assert not kette.stufe_reicht("verordnung", "gesetz")
    assert not kette.stufe_reicht("", "gesetz")
    assert kette.stufe_reicht("richtlinie", "")        # kein Eingriff, keine Hürde


def test_verletzter_kerngehalt_ist_endgueltig():
    """Was den Kerngehalt verletzt, wäre auch mit einem Gesetz unzulässig –
    das muss dastehen, sonst liest sich «Lücke schliessbar» wie ein Weg."""
    befunde = [{
        "taetigkeit": {"taetigkeit": "Anlasslose Massenüberwachung"},
        "kartierung": {"eingriff": {"tiefe": "schwer"},
                       "grundlagen": [{"erlass": "Polizeigesetz",
                                       "normstufe": "gesetz", "ermaechtigt": True}]},
        "wuerdigung": {"kerngehalt_verletzt": True, "ergebnis": "nicht zulässig"},
    }]
    meldungen = kette.sperren(befunde)
    assert any("auch mit einer gesetzlichen Grundlage unzulässig" in m["meldung"]
               for m in meldungen)


def test_rechercheluecke_ist_kein_ergebnis():
    """Nicht geprüft, nicht verifiziert und nicht vorhanden sind drei
    verschiedene Dinge (so schreibt es der Kartierungs-Skill vor)."""
    befunde = [{
        "taetigkeit": {"taetigkeit": "T"},
        "kartierung": {"eingriff": {"tiefe": "keiner"}, "grundlagen": [],
                       "luecke": {"art": "rechercheluecke"}},
        "wuerdigung": {"ergebnis": "zulässig"},
    }]
    meldungen = kette.sperren(befunde)
    assert any("nicht geprüft ist nicht dasselbe" in m["meldung"] for m in meldungen)


def test_bestaetigte_luecke_ohne_vorschlag_bleibt_offen():
    befunde = [{
        "taetigkeit": {"taetigkeit": "T"},
        "kartierung": {"eingriff": {"tiefe": "keiner"}, "grundlagen": []},
        "gap": {"bestaetigt": True, "deckungsvorschlag": "  "},
        "wuerdigung": {"ergebnis": "bedingt zulässig"},
    }]
    assert any("Deckungsvorschlag" in m["meldung"] for m in kette.sperren(befunde))


# ---- Die Entwarnung muss verdient sein ----------------------------------- #

def test_ohne_taetigkeiten_keine_entwarnung():
    assert kette.darf_entwarnen([]) is False


def test_ein_muss_befund_verhindert_die_entwarnung():
    befunde = [{
        "taetigkeit": {"taetigkeit": "Biometrische Erfassung"},
        "kartierung": {"eingriff": {"tiefe": "schwer"}, "grundlagen": []},
        "wuerdigung": {"ergebnis": "zulässig"},
    }]
    assert kette.darf_entwarnen(befunde) is False


def test_ungewuerdigte_taetigkeit_verhindert_die_entwarnung():
    """Der gemessene Fall: nie gewürdigt, trotzdem entwarnt."""
    befunde = [{
        "taetigkeit": {"taetigkeit": "T"},
        "kartierung": {"eingriff": {"tiefe": "leicht"},
                       "grundlagen": [{"erlass": "Verordnung X",
                                       "normstufe": "verordnung", "ermaechtigt": True}]},
        "wuerdigung": {},
    }]
    assert kette.darf_entwarnen(befunde) is False


def test_vollstaendig_geprueft_darf_entwarnen():
    befunde = [{
        "taetigkeit": {"taetigkeit": "Adressen im Register führen"},
        "kartierung": {"eingriff": {"tiefe": "leicht"},
                       "grundlagen": [{"erlass": "Registerverordnung",
                                       "normstufe": "verordnung", "ermaechtigt": True}],
                       "luecke": {"art": "keine"}},
        "wuerdigung": {"ergebnis": "zulässig", "kerngehalt_verletzt": False},
    }]
    assert kette.darf_entwarnen(befunde) is True


# ---- Der ganze gemessene Fall ------------------------------------------- #

def test_der_gemessene_fall_wird_nicht_mehr_entwarnt():
    """BKI Test 6 als Ganzes: schwerer Eingriff, nur Schrankennormen als
    «Grundlage», Kerngehalt betroffen. Drei unabhängige Sperren greifen."""
    befunde = [{
        "taetigkeit": {"taetigkeit": "Gesichter im öffentlichen Raum anlasslos "
                                     "biometrisch erfassen und abgleichen",
                       "betroffene": "alle Passantinnen und Passanten"},
        "kartierung": {
            "eingriff": {"tiefe": "schwer",
                         "grundrechte": ["Art. 13 BV", "Art. 22 BV", "Art. 8 EMRK"]},
            "grundlagen": [
                {"erlass": "Bundesverfassung (BV)", "normstufe": "verfassung",
                 "ermaechtigt": True},
                {"erlass": "Europäische Menschenrechtskonvention (EMRK)",
                 "normstufe": "verfassung", "ermaechtigt": True}],
            "luecke": {"art": "rechtsluecke"},
        },
        "gap": {"bestaetigt": True, "erforderliche_normstufe": "gesetz",
                "deckungsvorschlag": ""},
        "wuerdigung": {"ergebnis": "nicht zulässig", "kerngehalt_verletzt": True},
    }]
    meldungen = kette.sperren(befunde)
    muss = [m for m in meldungen if m["gewicht"] == "Muss"]
    assert len(muss) >= 3
    assert kette.darf_entwarnen(befunde) is False


# ---- Allgemeinheit: die Sperren kennen keinen Einzelfall ----------------- #
#
# Wichtigste Anforderung an dieses Modul: es darf NICHT auf den gemessenen Fall
# zugeschnitten sein. Die Sperren vergleichen ausschliesslich Struktur -
# Eingriffstiefe gegen Normstufe, Schranke gegen Ermaechtigung, Lueckenart.
# Kein Sachgebiet, kein Stichwort, kein Kanton kommt darin vor.

def test_kein_fallwissen_im_modul():
    """Ein Waechter gegen die Versuchung, den Einzelfall zu erkennen statt die
    Struktur. Sachbegriffe gehören in keine Regel dieses Moduls."""
    from pathlib import Path
    import re as _re

    quelle = Path(kette.__file__).read_text(encoding="utf-8")
    # Kommentare und Doku duerfen den Auslöser nennen – der CODE nicht.
    code = "\n".join(z for z in quelle.splitlines()
                     if not z.strip().startswith("#"))
    code = _re.sub(r'""".*?"""', "", code, flags=_re.DOTALL)
    for wort in ("gesichtserkennung", "demonstration", "kamera", "überwachung",
                 "biometr", "st. gallen", "polizei"):
        assert wort not in code.lower(), f"Fallwissen im Code: {wort}"


def test_alltagsfall_gebuehr_ohne_grundlage():
    """Ein ganz gewöhnlicher Fall, weit weg vom Auslöser: eine Gebühr wird
    erhoben, die Grundlage ist nur eine Richtlinie."""
    befunde = [{
        "taetigkeit": {"taetigkeit": "Eine Gebühr für die Aktenauskunft erheben"},
        "kartierung": {
            "eingriff": {"tiefe": "leicht", "grundrechte": ["Eigentumsgarantie"]},
            "grundlagen": [{"erlass": "Weisung des Amtes", "normstufe": "richtlinie",
                            "ermaechtigt": True}],
            "luecke": {"art": "rechtsluecke"},
        },
        "wuerdigung": {"ergebnis": "bedingt zulässig"},
    }]
    muss = [m for m in kette.sperren(befunde) if m["gewicht"] == "Muss"]
    assert muss, "Richtlinie trägt keinen Eingriff, für den eine Verordnung nötig ist"
    assert kette.darf_entwarnen(befunde) is False


def test_alltagsfall_datenbekanntgabe_mit_gesetz_ist_sauber():
    """Und ebenso wichtig: ein korrekter Fall darf NICHT blockiert werden.
    Eine Sperre, die immer greift, ist so wertlos wie eine, die nie greift."""
    befunde = [{
        "taetigkeit": {"taetigkeit": "Personendaten an eine andere Behörde bekanntgeben"},
        "kartierung": {
            "eingriff": {"tiefe": "leicht"},
            "grundlagen": [{"erlass": "Kantonales Datenschutzgesetz",
                            "normstufe": "gesetz", "ermaechtigt": True}],
            "luecke": {"art": "keine"},
        },
        "wuerdigung": {"ergebnis": "zulässig", "kerngehalt_verletzt": False},
    }]
    assert kette.sperren(befunde) == []
    assert kette.darf_entwarnen(befunde) is True


def test_nicht_bestimmte_eingriffstiefe_gilt_nicht_als_harmlos():
    """Die gefährlichste Lücke einer strukturellen Prüfung: was das Modell
    nicht einordnen konnte, dürfte sonst still als unbedenklich durchgehen –
    und die Sperren träfen nur, was ohnehin schon erkannt ist."""
    befunde = [{
        "taetigkeit": {"taetigkeit": "Irgendeine unklare Tätigkeit"},
        "kartierung": {"eingriff": {}, "grundlagen": [], "luecke": {"art": "keine"}},
        "wuerdigung": {"ergebnis": "zulässig"},
    }]
    meldungen = kette.sperren(befunde)
    assert any("nicht bestimmt" in m["meldung"] for m in meldungen)
    assert kette.darf_entwarnen(befunde) is False


def test_ein_offener_vorbehalt_verhindert_die_entwarnung():
    """«Offen» ist nicht «unbedenklich» – diese Gleichsetzung war der Fehler."""
    befunde = [{
        "taetigkeit": {"taetigkeit": "T"},
        "kartierung": {"eingriff": {"tiefe": "keiner"}, "grundlagen": [],
                       "luecke": {"art": "informationsluecke"}},
        "wuerdigung": {"ergebnis": "zulässig"},
    }]
    assert [m["gewicht"] for m in kette.sperren(befunde)] == ["Vorbehalt"]
    assert kette.darf_entwarnen(befunde) is False


@pytest.mark.parametrize("tiefe,stufe,blockiert", [
    ("schwer", "gesetz", False),
    ("schwer", "verordnung", True),
    ("schwer", "richtlinie", True),
    ("leicht", "verordnung", False),
    ("leicht", "richtlinie", True),
    ("keiner", "richtlinie", False),
])
def test_die_regel_ist_ein_stufenvergleich(tiefe, stufe, blockiert):
    """Sie gilt für jedes Sachgebiet gleich – das ist ihre Stärke."""
    befunde = [{
        "taetigkeit": {"taetigkeit": "beliebig"},
        "kartierung": {"eingriff": {"tiefe": tiefe},
                       "grundlagen": [{"erlass": "Erlass X", "normstufe": stufe,
                                       "ermaechtigt": True}],
                       "luecke": {"art": "keine"}},
        "wuerdigung": {"ergebnis": "zulässig"},
    }]
    muss = [m for m in kette.sperren(befunde) if m["gewicht"] == "Muss"]
    assert bool(muss) is blockiert


# ---- Der Lauf: ein Schritt je Schicht ------------------------------------ #


def test_die_ergebnisse_finden_ueber_die_nummer_zurueck():
    """Die Schichten laufen je Schicht, nicht je Tätigkeit – die Nummer ist
    das einzige Band zwischen Ergebnis und Tätigkeit."""
    lauf = {
        "taetigkeiten": {"taetigkeiten": [{"taetigkeit": "A"}, {"taetigkeit": "B"}]},
        "kartierung": {"kartierungen": [{"nr": 1, "eingriff": {"tiefe": "schwer"}}]},
        "wuerdigung": {"wuerdigungen": [{"nr": 0, "ergebnis": "zulässig"}]},
    }
    b = kette.befunde_aus(lauf)
    assert len(b) == 2
    assert b[1]["kartierung"]["eingriff"]["tiefe"] == "schwer"
    assert b[0]["wuerdigung"]["ergebnis"] == "zulässig"
    assert b[1]["wuerdigung"] == {}          # fehlt, wird nicht erfunden


def test_unsinnige_nummern_werfen_nichts_um():
    lauf = {"taetigkeiten": {"taetigkeiten": [{"taetigkeit": "A"}]},
            "kartierung": {"kartierungen": [{"nr": "x"}, {"nr": 99}, "kaputt"]}}
    assert kette.befunde_aus(lauf)[0]["kartierung"] == {}


# ---- Von der Kette ins Dokument ------------------------------------------ #

def _lauf_gemessener_fall():
    return {
        "taetigkeiten": {"taetigkeiten": [
            {"taetigkeit": "Gesichter im öffentlichen Raum anlasslos erfassen"}]},
        "kartierung": {"kartierungen": [{
            "nr": 0, "eingriff": {"tiefe": "schwer",
                                  "grundrechte": ["Art. 13 BV", "Art. 22 BV"]},
            "grundlagen": [{"erlass": "Bundesverfassung (BV)",
                            "normstufe": "verfassung", "ermaechtigt": True}],
            "luecke": {"art": "rechtsluecke"}}]},
        "gap": {"luecken": [{"nr": 0, "bestaetigt": True,
                             "erforderliche_normstufe": "gesetz",
                             "begruendung": "Keine Grundlage vorhanden.",
                             "deckungsvorschlag": ""}]},
        "wuerdigung": {"wuerdigungen": [{"nr": 0, "ergebnis": "nicht zulässig",
                                         "kerngehalt_verletzt": True,
                                         "begruendung": "Unverhältnismässig."}]},
    }


def test_der_gemessene_fall_erreicht_das_dokument():
    """Die Sperren müssen IM DOKUMENT stehen, nicht nur im Protokoll – sonst
    liest der Auftraggeber eine Analyse, die etwas anderes sagt als die
    Prüfung."""
    k = kette.zu_kapiteln(_lauf_gemessener_fall())

    # Keine Schrankennorm in der Grundlagen-Tabelle.
    namen = " ".join(z["rechtsgrundlage"] for z in k["bestehende_rechtsgrundlagen"])
    assert "Bundesverfassung" not in namen
    assert "Keine ermächtigende Grundlage" in namen

    luecken = json.dumps(k["identifizierte_luecken"], ensure_ascii=False)
    assert "ermächtigt nicht" in luecken
    assert "Art. 36 Abs. 1 BV" in luecken
    assert "auch mit einer gesetzlichen Grundlage unzulässig" in luecken
    # Kein Normweg mehr: bei verletztem Kerngehalt waere die Stufenangabe eine
    # Wegbeschreibung ins Nichts.
    assert "durch KEINE Normstufe zu schliessen" in luecken
    assert "Legislative / Parlament" not in luecken

    # Kerngehalt verletzt -> kein Klaerungsauftrag, sondern nicht umsetzbar.
    assert "nicht umsetzbar" in k["empfehlung"]
    assert "Rechtsdienst" in k["empfehlung"]
    assert "nicht zulässig" in k["konsequenzen"]


def test_ein_sauberer_fall_wird_nicht_kuenstlich_beanstandet():
    """Gegenprobe – eine Analyse, die immer warnt, ist so wertlos wie eine,
    die nie warnt."""
    lauf = {
        "taetigkeiten": {"taetigkeiten": [{"taetigkeit": "Ein Register führen"}]},
        "kartierung": {"kartierungen": [{
            "nr": 0, "eingriff": {"tiefe": "leicht"},
            "grundlagen": [{"erlass": "Registergesetz", "normstufe": "gesetz",
                            "ermaechtigt": True, "fundstelle": "SR 000.0"}],
            "luecke": {"art": "keine"}}]},
        "wuerdigung": {"wuerdigungen": [{"nr": 0, "ergebnis": "zulässig",
                                         "kerngehalt_verletzt": False,
                                         "begruendung": "Verhältnismässig."}]},
    }
    k = kette.zu_kapiteln(lauf)
    assert k["bestehende_rechtsgrundlagen"][0]["rechtsgrundlage"] == "Registergesetz"
    assert k["identifizierte_luecken"][0]["luecke"] == "Keine Lücke identifiziert"
    assert "besteht eine ermächtigende Grundlage" in k["empfehlung"]


def test_ohne_taetigkeiten_wird_nichts_behauptet():
    k = kette.zu_kapiteln({})
    assert "keine zu prüfenden Tätigkeiten" in k["empfehlung"]
    assert "Keine ermächtigende Grundlage" in \
        k["bestehende_rechtsgrundlagen"][0]["rechtsgrundlage"]


def test_der_schlussschritt_ruft_kein_modell():
    """Gemessen an der eigenen Zusage: Schritt 6 rief über build_answers die
    ALTE Einzelaufruf-Analyse auf. Ihre Ergebnisse wurden teils überschrieben,
    teils nicht – das Dokument mischte zwei Verfahren."""
    from app.domains.ergebnisse.rechtsgrundlagen import service as svc_modul

    gerufen = []
    echt = svc_modul.analysiere

    class _Wissen2(_Wissen):
        def referenzierte(self): return []
        def mitgeltende(self): return []
        def definitionen(self): return []

    try:
        svc_modul.analysiere = lambda *a, **kw: gerufen.append(1) or {}
        s = svc_modul.RechtsgrundlagenService.__new__(
            svc_modul.RechtsgrundlagenService)
        s.llm = None
        s.recherche = None

        s.build_answers(_Wissen2(), nur_basis=True)
        assert gerufen == [], "nur_basis darf kein Modell rufen"
    finally:
        svc_modul.analysiere = echt


def test_produktkonformitaet_wird_nicht_behauptet():
    """Die Kette erhebt sie nicht – dann darf dort auch nicht «kein Hinweis
    identifiziert» stehen. Nicht erhoben ist nicht dasselbe wie unbedenklich."""
    from pathlib import Path

    from app.domains.ergebnisse.rechtsgrundlagen import service as svc_modul
    quelle = Path(svc_modul.__file__).read_text(encoding="utf-8")
    schluss = quelle[quelle.index('# "kapitel"'):]
    # Das Kapitel kommt jetzt aus der Kette (Fachrecht), nicht aus einer festen
    # Zeile im Dienst.
    assert "nur_basis=True" in schluss


# ---- Eine Schicht darf mehrere Aufrufe brauchen -------------------------- #

def test_die_schweren_schichten_laufen_stueckweise():
    """Gemessen: die Würdigung ALLER Tätigkeiten in einem Aufruf riss das
    Zeitlimit von 240 s. Sie ist die dichteste Schicht – je Tätigkeit eine
    vollständige Prüfung an Art. 36 BV – und ihr Umfang wächst mit dem
    Vorhaben. Eine feste Aufteilung «eine Schicht = ein Aufruf» kann das nicht
    tragen."""
    from pathlib import Path

    from app.domains.ergebnisse.rechtsgrundlagen import service as svc_modul
    quelle = Path(svc_modul.__file__).read_text(encoding="utf-8")
    abschnitt = quelle[quelle.index("def kette_schritt"):]
    assert "_stueck(" in abschnitt
    # Die drei schweren Schichten gehen stueckweise, die leichten nicht.
    for schwer in ("kartierungen", "wuerdigungen", "faelle", "luecken"):
        assert f'_stueck(\n                "{schwer}"' in abschnitt or \
               f'"{schwer}", elemente' in abschnitt, schwer


def test_die_wuerdigung_bekommt_nur_was_sie_braucht():
    """Die vollständige Kartierung mitzugeben bläht den Aufruf auf, ohne das
    Urteil zu verbessern – und Aufblähen war die Ursache des Abbruchs."""
    from pathlib import Path

    from app.domains.ergebnisse.rechtsgrundlagen import service as svc_modul
    quelle = Path(svc_modul.__file__).read_text(encoding="utf-8")
    abschnitt = quelle[quelle.index('elif schluessel == "wuerdigung"'):
                       quelle.index('elif schluessel == "optionen"')]
    assert '"eingriff"' in abschnitt and '"grundlagen"' in abschnitt
    # NICHT die ganze Kartierung.
    assert '"kartierung": e["kartierung"]' not in abschnitt


def test_die_oberflaeche_zeigt_den_teilfortschritt():
    from pathlib import Path

    from app.config import BASE_DIR
    v = Path(BASE_DIR, "app", "templates", "rechtsgrundlagen.html").read_text(
        encoding="utf-8")
    assert "a.d.teile" in v and "a.d.teil" in v
    assert "Tätigkeit ' + (a.d.teil + 1)" in v


# ---- Der Prüfmassstab folgt der Tätigkeit, nicht dem Beispiel ------------ #
#
# Art. 36 BV regelt die EINSCHRÄNKUNG VON GRUNDRECHTEN. Die allermeisten
# Verwaltungsvorhaben berühren keine – eine Dokumentenablage, ein
# Website-Relaunch, eine Prozessautomatisierung. Ein fest vorgegebener
# Prüfmassstab ist deshalb nicht nur unpassend, er ist gefährlich: wer einen
# Massstab vorgesetzt bekommt, findet auch etwas zu prüfen.

def test_ohne_grundrechtsbezug_wird_art_36_nicht_zitiert():
    """Eine Abgabe ohne Grundlage ist ein Verstoss gegen das
    Legalitätsprinzip – nicht gegen die Grundrechtsschranke."""
    befunde = [{
        "taetigkeit": {"taetigkeit": "Eine Abgabe für eine Amtshandlung erheben"},
        "kartierung": {"eingriff": {"tiefe": "schwer", "grundrechte": []},
                       "grundlagen": [], "luecke": {"art": "keine"}},
        "wuerdigung": {"ergebnis": "nicht zulässig"},
    }]
    meldung = " ".join(m["meldung"] for m in kette.sperren(befunde))
    assert "Art. 5 Abs. 1 BV" in meldung
    assert "Art. 36" not in meldung, "Art. 36 gilt nur für Grundrechtseingriffe"


def test_mit_grundrechtsbezug_wird_art_36_zitiert_und_benannt():
    befunde = [{
        "taetigkeit": {"taetigkeit": "Personen im öffentlichen Raum identifizieren"},
        "kartierung": {"eingriff": {"tiefe": "schwer",
                                    "grundrechte": ["Art. 13 BV", "Art. 8 EMRK"]},
                       "grundlagen": [], "luecke": {"art": "keine"}},
        "wuerdigung": {"ergebnis": "nicht zulässig"},
    }]
    meldung = " ".join(m["meldung"] for m in kette.sperren(befunde))
    assert "Art. 36 Abs. 1 BV" in meldung
    assert "Art. 13 BV" in meldung          # welche Grundrechte, nicht pauschal


def test_die_wuerdigung_bestimmt_ihren_massstab_selbst(skills_dir):
    """Der Prompt darf keinen Massstab vorgeben – er muss verlangen, dass der
    passende bestimmt und begründet wird."""
    llm = _LLM({"wuerdigungen": []})
    kette.wuerdige([{"nr": 0, "taetigkeit": "T"}], llm, skills_dir=skills_dir)

    assert "BESTIMME ZUERST DEN PRÜFMASSSTAB" in llm.system
    assert "Legalitätsprinzip (Art. 5 Abs. 1 BV)" in llm.system
    # Die Grundrechtsschranke ausdruecklich als BEDINGTER Fall.
    assert "Nur wenn GRUNDRECHTE eingeschränkt werden" in llm.system
    assert "Erfinde keinen Eingriff" in llm.system
    assert "die meisten Verwaltungsvorhaben schränken keine Grundrechte ein" \
        in llm.system
    # Und im Auftrag: den gewaehlten Massstab ausweisen.
    assert "WELCHEN Massstab du angelegt hast" in llm.user


def test_die_kartierung_verlangt_keine_grundrechte_um_jeden_preis(skills_dir):
    llm = _LLM({"kartierungen": []})
    kette.kartiere([{"taetigkeit": "T"}], _Wissen(), llm, skills_dir=skills_dir)
    assert "die meisten Verwaltungstätigkeiten schränken keine Grundrechte ein" \
        in llm.user
    assert "auch ohne Grundrechtsbezug" in llm.user


def test_alltagsvorhaben_ohne_grundrechte_laeuft_sauber_durch():
    """Ein Vorhaben ganz ohne Grundrechtsbezug: die Kette darf es weder
    beanstanden noch ihm einen Eingriff andichten."""
    lauf = {
        "taetigkeiten": {"taetigkeiten": [
            {"taetigkeit": "Amtliche Dokumente elektronisch archivieren"}]},
        "kartierung": {"kartierungen": [{
            "nr": 0, "eingriff": {"tiefe": "keiner", "grundrechte": []},
            "grundlagen": [{"erlass": "Archivierungsgesetz", "normstufe": "gesetz",
                            "ermaechtigt": True}],
            "luecke": {"art": "keine"}}]},
        "wuerdigung": {"wuerdigungen": [{
            "nr": 0, "ergebnis": "zulässig", "kerngehalt_verletzt": False,
            "geprueft_an": ["Legalitätsprinzip (Art. 5 Abs. 1 BV)"],
            "begruendung": "Die Archivierung ist gesetzlich vorgesehen."}]},
    }
    assert kette.sperren(kette.befunde_aus(lauf)) == []
    k = kette.zu_kapiteln(lauf)
    assert "Art. 36" not in json.dumps(k, ensure_ascii=False)
    assert k["identifizierte_luecken"][0]["luecke"] == "Keine Lücke identifiziert"


# ---- Herkunft und Sicherheit je Aussage ---------------------------------- #
#
# Vier Befunde am erzeugten Dokument, ein gemeinsamer Kern – und er steht in
# der eigenen Referenzarchitektur: RA-10 «Jedes Ergebnis trägt seine Herkunft»,
# RA-11 «Unsicherheit ist ein Feld, keine Formulierung».

def test_nichts_wird_mehr_gekuerzt():
    """Gemessen im Kapitel «Beurteilung der Konsequenzen»: Begründungen brachen
    mitten im Satz ab. Die Regel gilt auf BEIDEN Seiten – was am Eingang nicht
    gekürzt werden darf, darf es am Ausgang auch nicht."""
    from pathlib import Path

    quelle = Path(kette.__file__).read_text(encoding="utf-8")
    assert "_kurz" not in quelle
    lang = "Ein sehr ausführlicher Begründungssatz. " * 40
    lauf = {
        "taetigkeiten": {"taetigkeiten": [{"taetigkeit": "T"}]},
        "kartierung": {"kartierungen": [{"nr": 0, "eingriff": {"tiefe": "keiner"},
                                         "grundlagen": [], "luecke": {"art": "keine"}}]},
        "wuerdigung": {"wuerdigungen": [{"nr": 0, "ergebnis": "zulässig",
                                         "begruendung": lang}]},
    }
    # Die Begruendung steht jetzt bei der Luecke, die sie traegt.
    kap = kette.zu_kapiteln(lauf)
    assert lang.strip() in json.dumps(kap, ensure_ascii=False)


def test_leere_tabelle_sagt_dass_sie_leer_ist():
    """Eine leere Liste liess die Platzhalter «…» der Vorlage stehen – im
    Dokument sah das aus wie ein Abbruch."""
    k = kette.zu_kapiteln({"taetigkeiten": {"taetigkeiten": [{"taetigkeit": "T"}]}})
    zeile = k["bevorstehende_aenderungen"][0]
    assert zeile["rechtsgrundlage"] and "…" not in zeile["rechtsgrundlage"]
    # Und ohne Entwarnung: nicht erhoben ist nicht «es gibt keine».
    assert "nicht systematisch abgefragt" in zeile["beschreibung"]


def test_fehlende_sicherheitsangabe_gilt_als_offen():
    """Bewusst vorsichtig: ohne Angabe ist eine Aussage NICHT eindeutig."""
    assert kette.sicherheit_von({}) == "offen"
    assert kette.sicherheit_von({"sicherheit": "Eindeutig"}) == "eindeutig"
    assert kette.sicherheit_von({"sicherheit": "Quatsch"}) == "offen"


def test_kerngehalt_wird_zugeschrieben_nicht_behauptet():
    """«Kerngehalt verletzt» ist die stärkste Aussage der ganzen Analyse. Ohne
    Zuschreibung und Sicherheitsgrad liest sie sich wie eine bewiesene
    Tatsache."""
    befunde = [{
        "taetigkeit": {"taetigkeit": "T"},
        "kartierung": {"eingriff": {"tiefe": "schwer", "grundrechte": ["Art. 13 BV"]},
                       "grundlagen": [{"erlass": "Ein Gesetz", "normstufe": "gesetz",
                                       "ermaechtigt": True}]},
        "wuerdigung": {"kerngehalt_verletzt": True,
                       "kerngehalt_sicherheit": "vertretbare Auffassung",
                       "kerngehalt_stuetzt_sich_auf": ["Art. 36 Abs. 4 BV"],
                       "ergebnis": "nicht zulässig",
                       "sicherheit": "überwiegend wahrscheinlich"},
    }]
    text = " ".join(m["meldung"] for m in kette.sperren(befunde))
    assert "Nach der vorgängigen Würdigung" in text
    assert "Sicherheit: vertretbare Auffassung" in text
    assert "Trifft das zu" in text            # bedingt, nicht behauptet
    assert "Gestützt auf: Art. 36 Abs. 4 BV" in text
    assert "nach den vorliegenden Projektangaben" in text


def test_optionen_legen_ihre_herkunft_offen():
    """Ohne Herkunftsangabe liest sich eine hypothetische Gesetzgebungsoption
    wie geltendes Recht."""
    lauf = {
        "taetigkeiten": {"taetigkeiten": [{"taetigkeit": "T"}]},
        "kartierung": {"kartierungen": [{"nr": 0, "eingriff": {"tiefe": "leicht"},
                                         "grundlagen": [], "luecke": {"art": "keine"}}]},
        "wuerdigung": {"wuerdigungen": [{"nr": 0, "ergebnis": "bedingt zulässig"}]},
        "optionen": {"faelle": [{"nr": 0, "optionen": [
            {"option": "Neues Gesetz schaffen",
             "herkunft": "hypothetische Gesetzgebungsoption",
             "sicherheit": "vertretbare Auffassung",
             "stuetzt_sich_auf": ["Art. 5 Abs. 1 BV"], "grundlage": "zu schaffen"},
            {"option": "Ohne Herkunftsangabe"}]}]},
    }
    v = kette.zu_kapiteln(lauf)["vorschlaege_deckung"]
    text = json.dumps(v, ensure_ascii=False)
    assert "Herkunft: hypothetische Gesetzgebungsoption" in text
    assert "Sicherheit: vertretbare Auffassung" in text
    assert "Art. 5 Abs. 1 BV" in text
    # Fehlt die Angabe, wird sie nicht weggelassen, sondern vorsichtig gesetzt.
    assert "Herkunft: Schlussfolgerung dieser Analyse" in text


def test_die_wuerdigung_nennt_ihren_massstab_im_dokument():
    """Traceability: welche Aussage stützt sich worauf."""
    lauf = {
        "taetigkeiten": {"taetigkeiten": [{"taetigkeit": "T"}]},
        "kartierung": {"kartierungen": [{"nr": 0, "eingriff": {"tiefe": "keiner"},
                                         "grundlagen": [], "luecke": {"art": "keine"}}]},
        "wuerdigung": {"wuerdigungen": [{
            "nr": 0, "ergebnis": "zulässig", "sicherheit": "eindeutig",
            "geprueft_an": ["Legalitätsprinzip (Art. 5 Abs. 1 BV)"],
            "stuetzt_sich_auf": ["Art. 5 Abs. 1 BV"], "begruendung": "Gedeckt."}]},
    }
    text = kette.zu_kapiteln(lauf)["konsequenzen"]
    assert "Unsicherheit: eindeutig" in text
    # Der Massstab steht jetzt als eigene STATION im Begründungsgraphen.


def test_die_schichten_verlangen_herkunft_und_sicherheit(skills_dir):
    """Der Vertrag muss es einfordern – sonst liefert das Modell es nicht."""
    llm = _LLM({"wuerdigungen": []})
    kette.wuerdige([{"nr": 0, "taetigkeit": "T"}], llm, skills_dir=skills_dir)
    assert "SICHERHEITSGRAD" in llm.system
    assert "vertretbare Auffassung" in llm.system
    assert "Nutze 'eindeutig' sparsam" in llm.system
    assert "stuetzt_sich_auf" in llm.system
    assert "Erfinde keine Fundstelle" in llm.system

    llm = _LLM({"faelle": []})
    kette.entwickle_optionen([{"nr": 0, "taetigkeit": "T"}], llm,
                             skills_dir=skills_dir)
    assert "HERKUNFT offen" in llm.system
    assert "hypothetische Gesetzgebungsoption" in llm.system


# ---- Widerspruch zwischen den Schichten ---------------------------------- #

def test_die_wuerdigung_darf_die_kartierung_korrigieren():
    """Gemessen: die Kartierung stufte eine flächendeckende Videoüberwachung als
    Eingriff «keiner» ein. Die Würdigung erkannte den Fehler – und schrieb ihn
    als Fliesstext ins Dokument, während der Code weiter mit «keiner» rechnete.
    Die Stufen-Sperre griff damit genau dort nicht, wo die Kartierung sich
    geirrt hatte: im gefährlichsten Fall."""
    kart = {"eingriff": {"tiefe": "keiner"}}
    wuerd = {"eingriff_korrigiert": {"tiefe": "schwer", "begruendung": "Weil X."}}
    tiefe, abweichung = kette.eingriff_von(kart, wuerd)
    assert tiefe == "schwer"
    assert abweichung["kartierung"] == "keiner"

    befunde = [{"taetigkeit": {"taetigkeit": "T"}, "kartierung": kart,
                "wuerdigung": dict(wuerd, ergebnis="nicht zulässig")}]
    meldungen = kette.sperren(befunde)
    # Der Widerspruch wird ausgewiesen …
    assert any("Massgeblich ist die Würdigung" in m["meldung"] for m in meldungen)
    # … und die Sperre rechnet mit der korrigierten Einstufung.
    assert any("keine Grundlage auf Stufe «gesetz»" in m["meldung"]
               for m in meldungen)


def test_ohne_korrektur_bleibt_die_kartierung_massgeblich():
    kart = {"eingriff": {"tiefe": "leicht"}}
    assert kette.eingriff_von(kart, {}) == ("leicht", None)
    assert kette.eingriff_von(kart, {"eingriff_korrigiert": {"tiefe": "leicht"}}) \
        == ("leicht", None)
    # Unsinn wird nicht uebernommen.
    assert kette.eingriff_von(kart, {"eingriff_korrigiert": {"tiefe": "sehr"}}) \
        == ("leicht", None)


def test_systemsprache_erreicht_den_leser_nie():
    """«Eingabefeld», «Eingabeobjekt» – der Leser sieht weder Felder noch
    Objekte. Derselbe Fehler wie bei der Konsolidierung der Fachprüfung."""
    assert kette.spricht_ueber_das_system(
        "Obwohl das Eingabefeld 'eingriff.tiefe' auf 'keiner' gesetzt wurde")
    assert kette.spricht_ueber_das_system("Die Eingriffseinstufung im Eingabeobjekt")
    assert not kette.spricht_ueber_das_system("Art. 36 BV verlangt ein Gesetz")

    w = {"geprueft_an": [
        "Art. 36 BV – weil Grundrechte schwer eingeschränkt werden",
        "Obwohl das Eingabefeld 'eingriff.tiefe' auf 'keiner' gesetzt wurde, gilt …",
        "Legalitätsprinzip (Art. 5 Abs. 1 BV): Erfordernis einer Grundlage"]}
    m = kette.massstaebe(w)
    assert m == ["Art. 36 BV", "Legalitätsprinzip (Art. 5 Abs. 1 BV)"]


# ---- Der Begründungsgraph ------------------------------------------------ #





def _lauf_kerngehalt():
    return {
        "taetigkeiten": {"taetigkeiten": [{"taetigkeit": "Personen identifizieren"}]},
        "kartierung": {"kartierungen": [{
            "nr": 0, "eingriff": {"tiefe": "schwer", "grundrechte": ["Art. 22 BV"]},
            "grundlagen": [], "luecke": {"art": "rechtsluecke"}}]},
        "gap": {"luecken": [{"nr": 0, "bestaetigt": True,
                             "erforderliche_normstufe": "gesetz",
                             "begruendung": "Keine Grundlage vorhanden.",
                             "deckungsvorschlag": "Kantonales Gesetz schaffen"}]},
        "wuerdigung": {"wuerdigungen": [{"nr": 0, "ergebnis": "nicht zulässig",
                                         "kerngehalt_verletzt": True,
                                         "sicherheit": "überwiegend wahrscheinlich"}]},
        "optionen": {"faelle": [{"nr": 0, "optionen": [
            {"option": "Neue gesetzliche Grundlage schaffen",
             "herkunft": "hypothetische Gesetzgebungsoption"}]}]},
    }


def test_kerngehalt_verletzt_dann_hilft_keine_normstufe():
    """Gemessen: «Kerngehalt verletzt» und eine Zeile darunter «zu schaffen auf
    Stufe gesetz» – ein Weg, den es nicht gibt, direkt neben der Feststellung,
    dass es ihn nicht gibt. Auch eine Verfassungsänderung hülfe nicht:
    Art. 36 Abs. 4 BV erklärt den Kerngehalt für unantastbar."""
    k = kette.zu_kapiteln(_lauf_kerngehalt())

    # Die Rechtslage steht im Kapitel «Identifizierte Lücken»; Kapitel 6 ist
    # der Entscheid und wiederholt sie nicht.
    luecken = json.dumps(k["identifizierte_luecken"], ensure_ascii=False)
    assert "durch KEINE Normstufe zu schliessen" in luecken
    assert "Art. 36 Abs. 4 BV" in luecken
    assert "auch eine verfassungsänderung" in luecken.lower()
    assert "zu schaffen auf Stufe gesetz" not in luecken
    assert "KEINE Normstufe" in luecken
    assert "fakultatives Referendum" not in luecken


def test_der_deckungsweg_traegt_den_sperrvermerk():
    """Ein Deckungsvorschlag darf nicht wie eine gangbare Lösung dastehen,
    wenn er keine ist."""
    v = json.dumps(kette.zu_kapiteln(_lauf_kerngehalt())["vorschlaege_deckung"],
                   ensure_ascii=False)
    assert "ACHTUNG" in v and "Kerngehalt" in v
    assert "unantastbar" in v


def test_ohne_kerngehaltsverstoss_bleibt_der_weg_stehen():
    """Gegenprobe: eine gewöhnliche Lücke wird ganz normal mit Normstufe und
    Verfahren beschrieben."""
    lauf = _lauf_kerngehalt()
    lauf["wuerdigung"]["wuerdigungen"][0] = {
        "nr": 0, "ergebnis": "bedingt zulässig", "kerngehalt_verletzt": False}
    k = kette.zu_kapiteln(lauf)
    luecken = json.dumps(k["identifizierte_luecken"], ensure_ascii=False)
    # Die Wegbeschreibung steht wieder da – Normstufe, Organ, Referendumsart.
    assert "Erforderliche Normstufe: gesetz" in luecken
    assert "fakultatives Referendum" in luecken
    assert "KEINE Normstufe" not in luecken
    assert "ACHTUNG" not in json.dumps(k, ensure_ascii=False)


def test_verfassungsstufe_nennt_das_obligatorische_referendum():
    """Art. 140 Abs. 1 lit. a BV: JEDE Verfassungsänderung untersteht dem
    obligatorischen Referendum – beim Bund braucht sie Volk UND Stände."""
    organ, referendum = kette.NORMSTUFE_VERFAHREN["verfassung"]
    assert "obligatorisch" in referendum
    assert "zwingend" in referendum
    assert "Stände" in organ
    # Und die Gesetzesstufe bleibt korrekt beim fakultativen Referendum.
    assert "fakultativ" in kette.NORMSTUFE_VERFAHREN["gesetz"][1]


# ---- Die Nummer verbindet Schicht und Tätigkeit -------------------------- #

def test_die_nummer_kommt_vom_aufrufer_und_wird_nie_neu_vergeben(skills_dir):
    """DER Fehler an einem echten Lauf (BKI Test 1): die Schicht läuft
    stückweise – ein Element je Aufruf. `kartiere` nummerierte die Liste neu,
    aus jeder Einzelanfrage wurde damit «nr: 0». Alle Kartierungen landeten
    auf der ersten Tätigkeit, die übrigen blieben leer. Im Dokument trug eine
    Beschaffung die berührten Rechte und die Grundlagen einer Freiheitsstrafe –
    und die Würdigung schrieb dazu, die Einstufung sei «irrtümlich diesem Fall
    zugeordnet»."""
    llm = _LLM({"kartierungen": []})
    kette.kartiere([{"taetigkeit": "Die dritte Tätigkeit", "nr": 2}], _Wissen(),
                   llm, skills_dir=skills_dir)
    eingang = json.loads(llm.user[llm.user.index("{"):llm.user.index("}\n\n") + 1]) \
        if False else None                      # nur zur Lesbarkeit
    assert '"nr": 2' in llm.user
    assert '"nr": 0' not in llm.user


def test_ohne_nummer_wird_der_reihe_nach_nummeriert(skills_dir):
    """Der Vollständigkeits-Aufruf (alle auf einmal) bleibt möglich."""
    llm = _LLM({"kartierungen": []})
    kette.kartiere([{"taetigkeit": "A"}, {"taetigkeit": "B"}], _Wissen(), llm,
                   skills_dir=skills_dir)
    assert '"nr": 0' in llm.user and '"nr": 1' in llm.user


def test_eine_taetigkeit_ohne_schichtergebnis_wird_ausgewiesen():
    """Eine stille Fehlzuordnung ist die gefährlichste Art von Fehler: das
    Dokument sieht vollständig aus und ordnet Befunde der falschen Tätigkeit
    zu."""
    lauf = {
        "taetigkeiten": {"taetigkeiten": [{"taetigkeit": "A"}, {"taetigkeit": "B"}]},
        "kartierung": {"kartierungen": [{"nr": 0, "eingriff": {"tiefe": "keiner"},
                                         "grundlagen": [], "luecke": {"art": "keine"}}]},
        "wuerdigung": {"wuerdigungen": [{"nr": 0, "ergebnis": "zulässig"}]},
    }
    fehlend = kette.zuordnungsluecken(lauf)
    assert ("kartierung", 1, "B") in fehlend
    assert ("wuerdigung", 1, "B") in fehlend

    k = kette.zu_kapiteln(lauf)
    text = json.dumps(k, ensure_ascii=False)
    assert "kein Ergebnis der Schicht" in text
    assert "insoweit ungeprüft" in text
    # Und keine Entwarnung, solange etwas ungeprüft ist.
    assert "Keine Lücke identifiziert" not in text


def test_vollstaendige_zuordnung_meldet_nichts():
    lauf = {
        "taetigkeiten": {"taetigkeiten": [{"taetigkeit": "A"}]},
        "kartierung": {"kartierungen": [{"nr": 0, "eingriff": {"tiefe": "keiner"},
                                         "grundlagen": [], "luecke": {"art": "keine"}}]},
        "wuerdigung": {"wuerdigungen": [{"nr": 0, "ergebnis": "zulässig"}]},
    }
    assert kette.zuordnungsluecken(lauf) == []
    assert kette.sperren(kette.befunde_aus(lauf)) == []


# ---- Die frühe Weiche: nicht jede Tätigkeit braucht den Grundrechtspfad --- #

def test_ohne_denkbaren_grundrechtseingriff_ist_der_pfad_kurz():
    """Gemessen: die Beschaffung durchlief den ganzen Grundrechtspfad, um am
    Ende festzustellen, dass es gar keinen Eingriff gibt. Ein kurzer Prüfpfad
    ist bei einer solchen Tätigkeit das richtige Ergebnis, kein Mangel."""
    eintrag = {
        "taetigkeit": {"taetigkeit": "Eine Nachfolgelösung beschaffen"},
        "kartierung": {"grundrechtseingriff_denkbar": False,
                       "fachrecht": ["BöB (SR 172.056.1)", "IVöB 2019"],
                       "eingriff": {"tiefe": "keiner"}, "grundlagen": []},
        "wuerdigung": {"ergebnis": "zulässig"}, "gap": {}, "optionen": {},
    }
    pfad = kette.pruefpfad(eintrag)
    assert pfad == ("Tätigkeit → kein Grundrechtseingriff → "
                    "Fachrecht (BöB (SR 172.056.1), IVöB 2019) → zulässig")
    assert "Normstufe" not in pfad


def test_mit_grundrechtseingriff_bleibt_der_volle_pfad():
    eintrag = {
        "taetigkeit": {"taetigkeit": "Personendaten bearbeiten"},
        "kartierung": {"grundrechtseingriff_denkbar": True,
                       "eingriff": {"tiefe": "schwer",
                                    "grundrechte": ["Art. 13 Abs. 2 BV"]},
                       "grundlagen": []},
        "wuerdigung": {"ergebnis": "bedingt zulässig"}, "gap": {}, "optionen": {},
    }
    pfad = kette.pruefpfad(eintrag)
    assert "Art. 13 Abs. 2 BV" in pfad
    assert "Normstufe gesetz" in pfad


def test_die_weiche_steht_im_vertrag(skills_dir):
    llm = _LLM({"kartierungen": []})
    kette.kartiere([{"taetigkeit": "T"}], _Wissen(), llm, skills_dir=skills_dir)
    assert "Weichenfrage" in llm.user
    assert "grundrechtseingriff_denkbar" in llm.user
    assert "das ist gewollt" in llm.user

    llm = _LLM({"wuerdigungen": []})
    kette.wuerdige([{"nr": 0, "taetigkeit": "T"}], llm, skills_dir=skills_dir)
    assert "Weiche gestellt" in llm.system
    assert "keine Kerngehaltsprüfung" in llm.system


# ---- Kapitel 6 ist ein Entscheid, keine zweite Herleitung ---------------- #

def test_kapitel_sechs_ist_ein_managemententscheid():
    """Es wiederholte Eingriff, Würdigung, Alternativen und Vorbehalte – alles
    Dinge, die in den Kapiteln davor stehen. Ein Projektausschuss braucht
    fünf Angaben."""
    lauf = {
        "taetigkeiten": {"taetigkeiten": [{"taetigkeit": "Register führen"}]},
        "kartierung": {"kartierungen": [{
            "nr": 0, "eingriff": {"tiefe": "leicht"},
            "grundlagen": [{"erlass": "Registergesetz", "normstufe": "gesetz",
                            "ermaechtigt": True}], "luecke": {"art": "keine"}}]},
        "wuerdigung": {"wuerdigungen": [{"nr": 0, "ergebnis": "zulässig",
                                         "sicherheit": "eindeutig"}]},
    }
    text = kette.zu_kapiteln(lauf)["konsequenzen"]
    for feld in ("Tätigkeit:", "Zulässig:", "Unsicherheit:", "Handlungsbedarf:",
                 "Entscheidungsempfehlung:", "Prüfpfad:"):
        assert feld in text, feld
    assert "Berührte Rechte:" not in text
    assert "Alternative:" not in text


# ---- Die fünf Befunde am Justiz-Dokument --------------------------------- #

def test_artikelangaben_werden_als_ungeprueft_ausgewiesen():
    """Gemessen: «StPO Art. 351 ff., insb. Art. 354» für die Vollstreckung von
    Bussen – Art. 354 StPO regelt die Einsprache gegen den Strafbefehl. Die
    Anwendung prüft ERLASSE gegen die amtlichen Sammlungen, Artikel nicht."""
    assert kette.nennt_artikel("SR 312.0, Art. 354")
    assert not kette.nennt_artikel("SR 312.0 – Strafprozessordnung")

    lauf = {
        "taetigkeiten": {"taetigkeiten": [{"taetigkeit": "T"}]},
        "kartierung": {"kartierungen": [{
            "nr": 0, "eingriff": {"tiefe": "keiner"}, "luecke": {"art": "keine"},
            "grundlagen": [{"erlass": "StPO", "normstufe": "gesetz",
                            "ermaechtigt": True,
                            "fundstelle": "SR 312.0, Art. 351 ff."}]}]},
        "wuerdigung": {"wuerdigungen": [{"nr": 0, "ergebnis": "zulässig"}]},
    }
    zeilen = kette.zu_kapiteln(lauf)["bestehende_rechtsgrundlagen"]
    assert zeilen[-1]["rechtsgrundlage"] == "Hinweis zu den Fundstellen"
    assert "ARTIKELANGABEN sind es nicht" in zeilen[-1]["beschreibung"]


def test_ohne_artikel_kein_hinweis():
    lauf = {
        "taetigkeiten": {"taetigkeiten": [{"taetigkeit": "T"}]},
        "kartierung": {"kartierungen": [{
            "nr": 0, "eingriff": {"tiefe": "keiner"}, "luecke": {"art": "keine"},
            "grundlagen": [{"erlass": "StPO", "normstufe": "gesetz",
                            "ermaechtigt": True, "fundstelle": "SR 312.0"}]}]},
        "wuerdigung": {"wuerdigungen": [{"nr": 0, "ergebnis": "zulässig"}]},
    }
    namen = [z["rechtsgrundlage"] for z in
             kette.zu_kapiteln(lauf)["bestehende_rechtsgrundlagen"]]
    assert "Hinweis zu den Fundstellen" not in namen


def test_fehlender_kanton_macht_die_aussagen_vorlaeufig():
    """Ohne Kanton bleibt jede Aussage zum kantonalen Recht hypothetisch – das
    Dokument sprach von «dem kantonalen Polizeigesetz», ohne sagen zu können,
    welches gemeint ist."""
    lauf = {"_kontext": {"ebene": "bund,kanton", "kanton": ""},
            "taetigkeiten": {"taetigkeiten": [{"taetigkeit": "T"}]}}
    text = json.dumps(kette.zu_kapiteln(lauf), ensure_ascii=False)
    assert "Kanton ist nicht angegeben" in text
    assert "VORLÄUFIG" in text

    lauf["_kontext"]["kanton"] = "SG"
    assert "Kanton ist nicht angegeben" not in json.dumps(
        kette.zu_kapiteln(lauf), ensure_ascii=False)


def test_die_empfehlung_unterscheidet_statt_pauschal_zu_stoppen():
    """«Das Vorhaben ist nicht weiterzuführen» für ein ganzes Projekt, weil EINE
    Tätigkeit klärungsbedürftig ist, hilft in der Initialisierung nicht – die
    Phase dient genau dieser Klärung."""
    lauf = {
        "taetigkeiten": {"taetigkeiten": [{"taetigkeit": "Sauber"},
                                          {"taetigkeit": "Klärungsbedürftig"}]},
        "kartierung": {"kartierungen": [
            {"nr": 0, "eingriff": {"tiefe": "keiner"}, "luecke": {"art": "keine"},
             "grundlagen": [{"erlass": "G", "normstufe": "gesetz",
                             "ermaechtigt": True}]},
            {"nr": 1, "eingriff": {"tiefe": "schwer"}, "grundlagen": [],
             "luecke": {"art": "keine"}}]},
        "wuerdigung": {"wuerdigungen": [{"nr": 0, "ergebnis": "zulässig"},
                                        {"nr": 1, "ergebnis": "bedingt zulässig"}]},
    }
    e = kette.zu_kapiteln(lauf)["empfehlung"]
    assert "1 von 2 Tätigkeiten" in e
    assert "Ohne Einwände" in e and "Sauber" in e
    assert "nicht Abbruch, sondern Klärungsauftrag" in e
    assert "nicht weiterzuführen" not in e


def test_bei_verletztem_kerngehalt_bleibt_es_beim_stopp():
    """Gegenprobe: was der Kerngehalt versperrt, kann keine Klärung heilen."""
    lauf = {
        "taetigkeiten": {"taetigkeiten": [{"taetigkeit": "T"}]},
        "kartierung": {"kartierungen": [{"nr": 0, "eingriff": {"tiefe": "schwer"},
                                         "grundlagen": [], "luecke": {"art": "keine"}}]},
        "wuerdigung": {"wuerdigungen": [{"nr": 0, "ergebnis": "nicht zulässig",
                                         "kerngehalt_verletzt": True}]},
    }
    e = kette.zu_kapiteln(lauf)["empfehlung"]
    assert "nicht umsetzbar" in e
    assert "keine weitere Abklärung" in e
    assert "Klärungsauftrag" not in e


def test_product_compliance_kommt_aus_dem_fachrecht():
    """Das Kapitel war leer, obwohl der PIA die Beschaffung ausdrücklich
    behandelt. Das Fachrecht der Kartierung ist der Anknüpfungspunkt."""
    lauf = {
        "taetigkeiten": {"taetigkeiten": [{"taetigkeit": "Beschaffen"}]},
        "kartierung": {"kartierungen": [{
            "nr": 0, "grundrechtseingriff_denkbar": False,
            "fachrecht": ["BöB (SR 172.056.1)", "IVöB 2019"],
            "eingriff": {"tiefe": "keiner"}, "grundlagen": [],
            "luecke": {"art": "keine"}}]},
        "wuerdigung": {"wuerdigungen": [{"nr": 0, "ergebnis": "zulässig"}]},
    }
    c = kette.zu_kapiteln(lauf)["product_compliance"]
    assert [z["compliance"] for z in c] == ["BöB (SR 172.056.1)", "IVöB 2019"]
    # Ohne genannte Anforderung sagt der Eintrag, dass sie fehlt.
    assert "wurde nicht erhoben" in c[0]["beschreibung"]


def test_ohne_fachrecht_wird_nichts_behauptet():
    lauf = {"taetigkeiten": {"taetigkeiten": [{"taetigkeit": "T"}]},
            "kartierung": {"kartierungen": [{"nr": 0, "eingriff": {"tiefe": "keiner"},
                                             "grundlagen": [], "luecke": {"art": "keine"}}]},
            "wuerdigung": {"wuerdigungen": [{"nr": 0, "ergebnis": "zulässig"}]}}
    c = kette.zu_kapiteln(lauf)["product_compliance"][0]
    assert "kein Nachweis" in c["beschreibung"]


def test_luecken_werden_je_taetigkeit_zusammengefasst():
    """Dieselbe Tätigkeit stand vier- bis fünfmal untereinander, teilweise
    wortgleich."""
    lauf = {
        "taetigkeiten": {"taetigkeiten": [{"taetigkeit": "Eine Tätigkeit"}]},
        "kartierung": {"kartierungen": [{
            "nr": 0, "eingriff": {"tiefe": "schwer", "grundrechte": ["Art. 13 BV"]},
            "grundlagen": [{"erlass": "Bundesverfassung", "normstufe": "verfassung",
                            "ermaechtigt": True}], "luecke": {"art": "keine"}}]},
        "wuerdigung": {"wuerdigungen": [{"nr": 0, "ergebnis": "nicht zulässig"}]},
    }
    luecken = kette.zu_kapiteln(lauf)["identifizierte_luecken"]
    assert len(luecken) == 1
    assert luecken[0]["luecke"] == "Eine Tätigkeit"


# ---- Lesbarkeit und Substanz --------------------------------------------- #

def test_der_kanton_geht_aus_der_aktuellen_auswahl_mit():
    """Gemessen: der Nutzer wählte St. Gallen und startete die Analyse – das
    Dokument meldete «Kanton nicht spezifiziert». Der Knopf stand in einem
    EIGENEN Formular und schickte den GESPEICHERTEN Kanton mit, nicht den
    gewählten."""
    from pathlib import Path

    from app.config import BASE_DIR
    v = Path(BASE_DIR, "app", "templates", "rechtsgrundlagen.html").read_text(
        encoding="utf-8")
    # Beide Knoepfe in EINEM Formular, der zweite ueber formaction.
    assert "formaction=" in v
    assert 'name="kanton" value="{{ entwurf.kanton' not in v


def test_die_uebersicht_steht_vorne():
    """Mit der gestiegenen Detailtiefe braucht der Leser zuerst die Zahl und
    die Rangfolge, dann die Einzelheiten."""
    lauf = {
        "taetigkeiten": {"taetigkeiten": [{"taetigkeit": "A"}, {"taetigkeit": "B"}]},
        "kartierung": {"kartierungen": [
            {"nr": 0, "eingriff": {"tiefe": "keiner"}, "luecke": {"art": "keine"},
             "grundlagen": [{"erlass": "G", "normstufe": "gesetz",
                             "ermaechtigt": True}]},
            {"nr": 1, "eingriff": {"tiefe": "schwer"}, "grundlagen": [],
             "luecke": {"art": "keine"}}]},
        "wuerdigung": {"wuerdigungen": [{"nr": 0, "ergebnis": "zulässig"},
                                        {"nr": 1, "ergebnis": "bedingt zulässig"}]},
    }
    text = kette.zu_kapiteln(lauf)["konsequenzen"]
    assert text.startswith("Geprüfte Tätigkeiten: 2")
    assert "Zwingend zu klären: 1" in text
    assert "Wichtigste offene Punkte:" in text
    # Die Uebersicht steht VOR den Einzelbloecken.
    assert text.index("Wichtigste offene Punkte") < text.index("Tätigkeit: A")


def test_die_uebersicht_deckelt_die_liste_und_sagt_es():
    """Eine gekürzte Liste darf nie wie eine vollständige aussehen."""
    n = 8
    lauf = {
        "taetigkeiten": {"taetigkeiten": [{"taetigkeit": f"T{i}"} for i in range(n)]},
        "kartierung": {"kartierungen": [
            {"nr": i, "eingriff": {"tiefe": "schwer"}, "grundlagen": [],
             "luecke": {"art": "keine"}} for i in range(n)]},
        "wuerdigung": {"wuerdigungen": [{"nr": i, "ergebnis": "bedingt zulässig"}
                                        for i in range(n)]},
    }
    text = kette.zu_kapiteln(lauf)["konsequenzen"]
    assert "und 3 weitere, siehe unten" in text


def test_fachrecht_nennt_seine_anforderung():
    """«Einschlägig, aber nicht im Einzelnen erhoben» hilft niemandem. Steht
    die Anforderung da, steht sie VORNE."""
    lauf = {
        "taetigkeiten": {"taetigkeiten": [{"taetigkeit": "Beschaffen"}]},
        "kartierung": {"kartierungen": [{
            "nr": 0, "grundrechtseingriff_denkbar": False,
            "fachrecht": [{"erlass": "IVöB 2019",
                           "anforderung": "Offenes Verfahren ab Schwellenwert."}],
            "eingriff": {"tiefe": "keiner"}, "grundlagen": [],
            "luecke": {"art": "keine"}}]},
        "wuerdigung": {"wuerdigungen": [{"nr": 0, "ergebnis": "zulässig"}]},
    }
    z = kette.zu_kapiteln(lauf)["product_compliance"][0]
    assert z["compliance"] == "IVöB 2019"
    assert z["beschreibung"].startswith("Offenes Verfahren ab Schwellenwert.")


def test_fachrecht_ohne_anforderung_sagt_dass_sie_fehlt():
    """Nicht erhoben ist nicht unbedenklich."""
    lauf = {
        "taetigkeiten": {"taetigkeiten": [{"taetigkeit": "Beschaffen"}]},
        "kartierung": {"kartierungen": [{
            "nr": 0, "fachrecht": [{"erlass": "IVöB 2019"}],
            "eingriff": {"tiefe": "keiner"}, "grundlagen": [],
            "luecke": {"art": "keine"}}]},
        "wuerdigung": {"wuerdigungen": [{"nr": 0, "ergebnis": "zulässig"}]},
    }
    z = kette.zu_kapiteln(lauf)["product_compliance"][0]
    assert "nicht erhoben" in z["beschreibung"]
    assert "vor der Umsetzung zu klären" in z["beschreibung"]


def test_aeltere_laeufe_mit_blossem_erlassnamen_bleiben_lesbar():
    """Der Vertrag hat sich geändert – ein laufender Entwurf darf daran nicht
    zerbrechen."""
    lauf = {
        "taetigkeiten": {"taetigkeiten": [{"taetigkeit": "Beschaffen"}]},
        "kartierung": {"kartierungen": [{
            "nr": 0, "fachrecht": ["BöB (SR 172.056.1)"],
            "eingriff": {"tiefe": "keiner"}, "grundlagen": [],
            "luecke": {"art": "keine"}}]},
        "wuerdigung": {"wuerdigungen": [{"nr": 0, "ergebnis": "zulässig"}]},
    }
    z = kette.zu_kapiteln(lauf)["product_compliance"][0]
    assert z["compliance"] == "BöB (SR 172.056.1)"


def test_hoechstens_drei_klar_verschiedene_optionen(skills_dir):
    """Die Vorschläge überlappten stark – «bestehende Grundlage nutzen» und
    «bestehende Grundlage präzisieren» sind eine Option, nicht zwei."""
    llm = _LLM({"faelle": []})
    kette.entwickle_optionen([{"nr": 0, "taetigkeit": "T"}], llm,
                             skills_dir=skills_dir)
    assert "HÖCHSTENS DREI Optionen" in llm.system
    assert "WIRKLICH unterscheiden" in llm.system
    assert "zwei bis drei Sätze" in llm.system


# ---- Fundstellen prüfen: der Schritt ohne Modellaufruf -------------------- #

def test_der_lauf_hat_sieben_schritte():
    namen = kette.schrittnamen()
    assert len(namen) == 7
    assert namen[-2] == "Fundstellen prüfen"
    assert namen[-1] == "Dokument zusammenstellen"


def test_fundstellenpruefung_ruft_kein_modell():
    """Dieser Schritt prüft, was frühere Schichten behauptet haben, gegen die
    amtlichen Quellen – das ist Recherche, kein Urteil."""
    from pathlib import Path

    from app.domains.ergebnisse.rechtsgrundlagen import service as svc_modul
    quelle = Path(svc_modul.__file__).read_text(encoding="utf-8")
    abschnitt = quelle[quelle.index('elif schluessel == "fundstellen"'):
                       quelle.index('else:                                   # "kapitel"')]
    assert "llm" not in abschnitt.lower()


class _Artikel:
    """Ein Prüfer, der den amtlichen Text kennt."""
    def pruefe_fundstelle(self, quelle, zitat):
        return [{"artikel": "354", "zustand": "belegt",
                 "ueberschrift": "Einsprache", "quelle": quelle}]


class _Bger:
    def __init__(self):
        self.gefragt = []

    def suche_mehrere(self, begriffe, treffer_je_begriff=2):
        self.gefragt.append(list(begriffe))
        return [{"kennung": "BGE 151 I 137", "datum": "", "url": "https://x",
                 "fundstelle_geprueft": True}]


def test_rechtsprechung_nur_wo_sie_gebraucht_wird():
    """Ein Urteil neben einer klaren Rechtslage schmückt nur."""
    befunde = [
        {"taetigkeit": {"taetigkeit": "Klar"},
         "kartierung": {"eingriff": {"tiefe": "keiner"}, "grundlagen": []},
         "wuerdigung": {"ergebnis": "zulässig", "sicherheit": "eindeutig"}},
        {"taetigkeit": {"taetigkeit": "Strittig"},
         "kartierung": {"eingriff": {"tiefe": "schwer",
                                     "grundrechte": ["Versammlungsfreiheit"]},
                        "grundlagen": []},
         "wuerdigung": {"ergebnis": "bedingt zulässig"}},
    ]
    b = _Bger()
    ergebnis = kette.pruefe_fundstellen(befunde, artikel_pruefer=None, bger=b)
    je = ergebnis["je_taetigkeit"]
    assert je["0"]["rechtsprechung"] == []
    assert je["1"]["rechtsprechung"]
    assert je["0"]["rechtsprechung_grund"]        # der Grund steht immer da
    # Gesucht wurde NUR fuer die strittige Taetigkeit, mit ihren Begriffen.
    assert b.gefragt == [["Strittig", "Versammlungsfreiheit"]]
    assert ergebnis["zitierbare_entscheide"] == ["BGE 151 I 137"]


def test_suchbegriffe_kommen_ohne_modell_zustande():
    """Ein Modell nach Suchbegriffen zu fragen hiesse raten, wo die Recherche
    das Raten ersetzen soll."""
    begriffe = kette._suchbegriffe({
        "taetigkeit": {"taetigkeit": "Personen biometrisch identifizieren"},
        "kartierung": {"eingriff": {"grundrechte": [
            "Art. 13 Abs. 2 BV", "Versammlungsfreiheit (Art. 22 BV)"]}}})
    assert begriffe[0] == "Personen biometrisch identifizieren"
    assert "Versammlungsfreiheit" in begriffe
    # Eine blosse Normangabe taugt nicht als Suchwort.
    assert not any(x.startswith("Art.") for x in begriffe)


def test_geprueft_schlaegt_hinweis():
    """Liegen Artikelbefunde vor, stehen SIE da – der pauschale Vorbehalt gilt
    nur noch für das Ungeprüfte."""
    lauf = {
        "taetigkeiten": {"taetigkeiten": [{"taetigkeit": "T"}]},
        "kartierung": {"kartierungen": [{
            "nr": 0, "eingriff": {"tiefe": "keiner"}, "luecke": {"art": "keine"},
            "grundlagen": [{"erlass": "StPO", "normstufe": "gesetz",
                            "ermaechtigt": True,
                            "fundstelle": "SR 312.0, Art. 354"}]}]},
        "wuerdigung": {"wuerdigungen": [{"nr": 0, "ergebnis": "zulässig"}]},
        "fundstellen": {"je_taetigkeit": {"0": {"artikel": [
            {"erlass": "StPO", "artikel": "354", "zustand": "belegt",
             "ueberschrift": "Einsprache"}]}}, "zitierbare_entscheide": []},
    }
    zeilen = kette.zu_kapiteln(lauf)["bestehende_rechtsgrundlagen"]
    text = json.dumps(zeilen, ensure_ascii=False)
    assert "«Einsprache» (amtlich geprüft)" in text
    assert "Hinweis zu den Fundstellen" not in text


def test_ein_nicht_existierender_artikel_wird_deutlich_gemeldet():
    """Genau der gemessene Fall: «StPO Art. 354» für die Vollstreckung von
    Bussen. Steht der Artikel nicht im amtlichen Text, muss das auffallen."""
    lauf = {
        "taetigkeiten": {"taetigkeiten": [{"taetigkeit": "T"}]},
        "kartierung": {"kartierungen": [{
            "nr": 0, "eingriff": {"tiefe": "keiner"}, "luecke": {"art": "keine"},
            "grundlagen": [{"erlass": "StPO", "normstufe": "gesetz",
                            "ermaechtigt": True, "fundstelle": "Art. 9999"}]}]},
        "wuerdigung": {"wuerdigungen": [{"nr": 0, "ergebnis": "zulässig"}]},
        "fundstellen": {"je_taetigkeit": {"0": {"artikel": [
            {"erlass": "StPO", "artikel": "9999", "zustand": "existiert_nicht",
             "ueberschrift": ""}]}}, "zitierbare_entscheide": []},
    }
    text = json.dumps(kette.zu_kapiteln(lauf)["bestehende_rechtsgrundlagen"],
                      ensure_ascii=False)
    assert "EXISTIERT IM AMTLICHEN TEXT NICHT" in text
    assert "zu berichtigen" in text


def test_nicht_pruefbar_wird_als_solches_ausgewiesen():
    lauf = {
        "taetigkeiten": {"taetigkeiten": [{"taetigkeit": "T"}]},
        "kartierung": {"kartierungen": [{
            "nr": 0, "eingriff": {"tiefe": "keiner"}, "luecke": {"art": "keine"},
            "grundlagen": [{"erlass": "Kantonales Gesetz", "normstufe": "gesetz",
                            "ermaechtigt": True, "fundstelle": "Art. 4"}]}]},
        "wuerdigung": {"wuerdigungen": [{"nr": 0, "ergebnis": "zulässig"}]},
        "fundstellen": {"je_taetigkeit": {"0": {"artikel": [
            {"erlass": "Kantonales Gesetz", "artikel": "4",
             "zustand": "nicht_pruefbar", "ueberschrift": ""}]}},
            "zitierbare_entscheide": []},
    }
    text = json.dumps(kette.zu_kapiteln(lauf), ensure_ascii=False)
    assert "nicht prüfbar" in text


def test_unbelegte_entscheide_erreichen_das_dokument_nicht():
    """Die letzte Sperre: was das Modell schreibt, wird gegen die Trefferliste
    gehalten. Ein erfundener Entscheid sieht aus wie ein Beleg."""
    lauf = {
        "taetigkeiten": {"taetigkeiten": [{"taetigkeit": "T"}]},
        "kartierung": {"kartierungen": [{
            "nr": 0, "eingriff": {"tiefe": "schwer"}, "grundlagen": [],
            "luecke": {"art": "keine"}}]},
        "wuerdigung": {"wuerdigungen": [{
            "nr": 0, "ergebnis": "nicht zulässig",
            "begruendung": "Vgl. BGE 151 I 137 und BGE 99 IX 999."}]},
        "fundstellen": {"je_taetigkeit": {}, "zitierbare_entscheide": ["BGE 151 I 137"]},
    }
    text = json.dumps(kette.zu_kapiteln(lauf), ensure_ascii=False)
    assert "BGE 151 I 137" in text
    assert "BGE 99 IX 999" not in text
    assert "Entscheid ohne Beleg" in text


def test_ohne_recherche_bleibt_alles_beim_alten():
    """Ohne eingeschaltete Live-Recherche gibt es keine Befunde – und keine
    erfundenen. Das Dokument sagt dann wie bisher, dass Artikelangaben nicht
    verifiziert sind."""
    befunde = [{"taetigkeit": {"taetigkeit": "T"},
                "kartierung": {"grundlagen": [{"erlass": "X", "fundstelle": "Art. 1"}]},
                "wuerdigung": {"ergebnis": "zulässig", "sicherheit": "eindeutig"}}]
    ergebnis = kette.pruefe_fundstellen(befunde, artikel_pruefer=None, bger=None)
    assert ergebnis["je_taetigkeit"]["0"]["artikel"] == []
    assert ergebnis["zitierbare_entscheide"] == []
