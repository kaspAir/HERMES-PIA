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
    """Art. 36 Abs. 1 BV – das ist ein Vergleich, kein Urteil, und gehört
    deshalb in den Code."""
    befunde = [{
        "taetigkeit": {"taetigkeit": "Biometrische Erfassung"},
        "kartierung": {
            "eingriff": {"tiefe": "schwer"},
            "grundlagen": [{"erlass": "Polizeiverordnung", "normstufe": "verordnung",
                            "ermaechtigt": True}],
        },
    }]
    meldungen = kette.sperren(befunde)
    assert any("Art. 36 Abs. 1 BV" in m["meldung"] for m in meldungen)

    # Mit einem formellen Gesetz faellt der Befund weg.
    befunde[0]["kartierung"]["grundlagen"] = [
        {"erlass": "Polizeigesetz", "normstufe": "gesetz", "ermaechtigt": True}]
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
