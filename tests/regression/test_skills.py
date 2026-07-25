"""Beweist: Skill-Loader (Basis + Mandant) mit harter applies_to- und
Mandanten-Isolation, Override, Nachweis – und Injektion in den richtigen Schritt.
"""
import pytest

from app.domains.skills import compose_system, load_skills


def _skill(dir_, name, applies_to="rechtsgrundlagenanalyse", version="1.0",
           body="Methode.", scope_hint=""):
    d = dir_ / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\nversion: \"{version}\"\napplies_to: {applies_to}\n---\n\n{body}\n",
        encoding="utf-8")
    return d


@pytest.fixture
def skills_dir(tmp_path):
    base = tmp_path / "base"
    _skill(base, "rg-kartierung", body="BASIS-KARTIERUNG")
    _skill(base, "rg-luecke", body="BASIS-LUECKE")
    # Ein Skill fuer einen ANDEREN Schritt darf nie in die Kartierung geraten.
    _skill(base, "fremd", applies_to="schutzbedarfsanalyse", body="FREMD-SCHRITT")
    # Mandant 7: ueberschreibt kartierung + bringt einen eigenen Skill.
    m7 = tmp_path / "mandant-7"
    _skill(m7, "rg-kartierung", version="7.1", body="MANDANT7-KARTIERUNG")
    _skill(m7, "rg-mandant", body="MANDANT7-EIGEN")
    # Mandant 8: darf NIE bei Mandant 7 auftauchen.
    _skill(tmp_path / "mandant-8", "rg-geheim", body="MANDANT8-GEHEIM")
    return tmp_path


def test_basis_skills_nach_applies_to_gefiltert(skills_dir):
    b = load_skills("rechtsgrundlagenanalyse", tenant_id=None, skills_dir=skills_dir)
    assert "BASIS-KARTIERUNG" in b.text and "BASIS-LUECKE" in b.text
    assert "FREMD-SCHRITT" not in b.text          # anderer Schritt -> nie geladen


def test_fremder_schritt_bekommt_diese_skills_nicht(skills_dir):
    b = load_skills("schutzbedarfsanalyse", tenant_id=None, skills_dir=skills_dir)
    assert "FREMD-SCHRITT" in b.text
    assert "BASIS-KARTIERUNG" not in b.text       # Kartierung gehoert nicht hierher


def test_mandant_ueberschreibt_basis_und_ergaenzt(skills_dir):
    b = load_skills("rechtsgrundlagenanalyse", tenant_id=7, skills_dir=skills_dir)
    assert "MANDANT7-KARTIERUNG" in b.text        # Delta gewinnt
    assert "BASIS-KARTIERUNG" not in b.text       # ... und verdraengt die Basis
    assert "BASIS-LUECKE" in b.text               # nicht ueberschriebene Basis bleibt
    assert "MANDANT7-EIGEN" in b.text             # additiv


def test_mandanten_isolation_strikt(skills_dir):
    """Der wichtigste Test: ein Mandant sieht NIE die Skills eines anderen."""
    b = load_skills("rechtsgrundlagenanalyse", tenant_id=7, skills_dir=skills_dir)
    assert "MANDANT8-GEHEIM" not in b.text
    b8 = load_skills("rechtsgrundlagenanalyse", tenant_id=8, skills_dir=skills_dir)
    assert "MANDANT7-EIGEN" not in b8.text and "MANDANT7-KARTIERUNG" not in b8.text


def test_tenant_id_kann_nicht_aus_base_ausbrechen(skills_dir):
    """Ein praeparierter Mandant-Wert darf keinen fremden Pfad laden."""
    b = load_skills("rechtsgrundlagenanalyse", tenant_id="../base",
                    skills_dir=skills_dir)
    # Nur die Basis greift; kein Traversal, kein Absturz.
    assert "BASIS-KARTIERUNG" in b.text


def test_evals_werden_nie_geladen(tmp_path):
    base = tmp_path / "base"
    d = _skill(base, "rg-kartierung", body="METHODE")
    (d / "evals").mkdir()
    (d / "evals" / "ground-truth.md").write_text("GEHEIME-GROUND-TRUTH", encoding="utf-8")
    b = load_skills("rechtsgrundlagenanalyse", skills_dir=tmp_path)
    assert "METHODE" in b.text
    assert "GROUND-TRUTH" not in b.text


def test_references_werden_mitgeladen(tmp_path):
    base = tmp_path / "base"
    d = _skill(base, "rg-kartierung", body="METHODE")
    (d / "references").mkdir()
    (d / "references" / "quellen.md").write_text("QUELLEN-SCHWEIZ", encoding="utf-8")
    b = load_skills("rechtsgrundlagenanalyse", skills_dir=tmp_path)
    assert "QUELLEN-SCHWEIZ" in b.text


def test_ohne_skills_ordner_leeres_buendel():
    b = load_skills("rechtsgrundlagenanalyse", skills_dir="/gibt/es/nicht")
    assert not b and b.text == "" and b.versions == []


def test_nachweis_traegt_name_version_scope(skills_dir):
    b = load_skills("rechtsgrundlagenanalyse", tenant_id=7, skills_dir=skills_dir)
    eintraege = {v["name"]: v for v in b.versions}
    assert eintraege["rg-kartierung"]["version"] == "7.1"
    assert eintraege["rg-kartierung"]["scope"] == "mandant"
    assert eintraege["rg-luecke"]["scope"] == "base"


def test_compose_system_haengt_an_und_haelt_das_format(skills_dir):
    b = load_skills("rechtsgrundlagenanalyse", skills_dir=skills_dir)
    zusammengesetzt = compose_system("BASIS-SYSTEM mit JSON-Vertrag", b)
    assert zusammengesetzt.startswith("BASIS-SYSTEM mit JSON-Vertrag")
    assert "BASIS-KARTIERUNG" in zusammengesetzt
    # Leeres Buendel laesst den System-Prompt unveraendert.
    assert compose_system("X", load_skills("egal", skills_dir="/nix")) == "X"


# ---- Die echten vier Basis-Skills aus dem Repo ---------------------------- #

def test_ausgelieferte_basis_skills_laden():
    """skills/base der App enthaelt die vier Rechtsgrundlagen-Skills."""
    from app.config import Config
    b = load_skills("rechtsgrundlagenanalyse", skills_dir=Config.SKILLS_DIR)
    namen = {v["name"] for v in b.versions}
    assert "rechtsgrundlagen-kartierung" in namen
    assert len(namen) >= 4


# ---- Injektion nur im richtigen Schritt ----------------------------------- #

def test_analysiere_injiziert_den_skill_in_den_system_prompt(skills_dir, monkeypatch):
    """Der Kartierungs-Skill landet im System-Prompt des Rechtsgrundlagen-Schritts."""
    from app.domains.ergebnisse.rechtsgrundlagen import proposals

    gesehen = {}

    class _LLM:
        def complete(self, system, messages, max_tokens=1024):
            gesehen["system"] = system
            return '{"bestehende":[],"luecken":[]}'

    class _Wissen:
        ebene = "bund"; kanton = None
        def ziel_beschreibungen(self): return ["Ziel A"]
        def genannte_rechtsgrundlagen(self): return []
        def ausgangslage_text(self): return "Ausgangslage."

    bundle = load_skills("rechtsgrundlagenanalyse", skills_dir=skills_dir)
    proposals.analysiere(_Wissen(), _LLM(), skill_bundle=bundle)
    assert "BASIS-KARTIERUNG" in gesehen["system"]
    assert "METHODENLEITFADEN" in gesehen["system"]


def test_analysiere_ohne_skill_unveraendert(monkeypatch):
    """Ohne Bündel bleibt der bisherige System-Prompt exakt erhalten."""
    from app.domains.ergebnisse.rechtsgrundlagen import proposals

    gesehen = {}

    class _LLM:
        def complete(self, system, messages, max_tokens=1024):
            gesehen["system"] = system
            return "{}"

    class _Wissen:
        ebene = None; kanton = None
        def ziel_beschreibungen(self): return []
        def genannte_rechtsgrundlagen(self): return []
        def ausgangslage_text(self): return ""

    proposals.analysiere(_Wissen(), _LLM(), skill_bundle=None)
    assert gesehen["system"] == proposals.SYSTEM
    assert "METHODENLEITFADEN" not in gesehen["system"]


def test_only_bildet_das_schritt_mapping_ab(skills_dir):
    """Mehrere Skills im selben Bereich, aber der Schritt zieht nur seinen einen."""
    b = load_skills("rechtsgrundlagenanalyse", tenant_id=None,
                    skills_dir=skills_dir, only={"rg-kartierung"})
    assert "BASIS-KARTIERUNG" in b.text
    assert "BASIS-LUECKE" not in b.text          # anderer Schritt der Kette
    assert [v["name"] for v in b.versions] == ["rg-kartierung"]


def test_kartierungsschritt_zieht_nur_kartierung_aus_den_echten_skills():
    """Nicht alle vier Skills der Kette landen im Kartierungs-Prompt (sonst 29k)."""
    from app.config import Config
    b = load_skills("rechtsgrundlagenanalyse", skills_dir=Config.SKILLS_DIR,
                    only={"rechtsgrundlagen-kartierung"})
    namen = {v["name"] for v in b.versions}
    assert namen == {"rechtsgrundlagen-kartierung"}
    assert "würdigung" not in b.text.lower() or "Skill: rechtsgrundlagen-wuerdigung" not in b.text
