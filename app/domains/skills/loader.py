"""Lädt Skills und fügt sie zu einem System-Prompt-Block zusammen.

Layout unter SKILLS_DIR (kanonische Quelle: das Git-Repo der Skills, per
scripts/sync_skills.py hierher gespiegelt):

    base/<skill-name>/SKILL.md            (+ references/…)
    mandant-<tenant_id>/<skill-name>/SKILL.md   (+ references/…)

Regeln (alle hier hart durchgesetzt):
  * **applies_to** aus dem Frontmatter MUSS zum `task` passen – sonst wird der
    Skill NICHT geladen. So kann ein Rechtsgrundlagen-Skill niemals in einen
    fremden Schritt (Extraktion, Schutzbedarf, Studie …) geraten und dessen
    Ausgabe verfälschen.
  * **Mandanten-Isolation:** gelesen werden ausschliesslich `base/` und der
    Ordner `mandant-<aktueller tenant_id>/`. Nie ein anderer Mandant. Analog zum
    org_id-Muster des RAG-Korpus (NULL = geteilt, sonst mandantenspezifisch).
  * **Override:** ein Mandanten-Skill gleichen Namens schlägt die Basis (Delta
    gewinnt); ansonsten additiv (neue Skills ergänzen).
  * **evals/ wird NIE geladen** – reines Entwicklungs-/Qualitäts-Artefakt.

Fehlt SKILLS_DIR ganz (nicht ausgerollt, Tests), liefert load_skills ein leeres
Bündel – die Aufrufer verhalten sich dann exakt wie vor der Skill-Einführung.
"""
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

log = logging.getLogger("hermes.skills")

_FRONTMATTER = re.compile(r"^\s*---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)
# Ein Mandant wird über eine Ordnerkonvention adressiert. Nur genau diese Form
# zulassen – so kann ein Mandant-Wert nie aus base/ ausbrechen (Pfad-Traversal).
_TENANT_DIR = re.compile(r"^mandant-[A-Za-z0-9_-]+$")


@dataclass
class Skill:
    name: str
    version: str
    scope: str            # 'base' | 'mandant'
    applies_to: str
    body: str
    references: str = ""
    quelle: str = ""      # Herkunftspfad (Nachvollziehbarkeit)

    def als_block(self):
        """Der in den System-Prompt injizierte Text dieses einen Skills."""
        teile = [f"## Skill: {self.name} (v{self.version}, {self.scope})", self.body.strip()]
        if self.references.strip():
            teile.append("### Referenzen\n" + self.references.strip())
        return "\n\n".join(teile)


@dataclass
class SkillBundle:
    text: str = ""
    versions: list = field(default_factory=list)   # [{name, version, scope}]

    def __bool__(self):
        return bool(self.text.strip())


def _parse_skill_md(inhalt, scope, quelle):
    """Zerlegt eine SKILL.md in Frontmatter + Körper. None, wenn unbrauchbar."""
    m = _FRONTMATTER.match(inhalt or "")
    if not m:
        log.warning("Skill ohne Frontmatter übersprungen: %s", quelle)
        return None
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as e:
        log.warning("Skill mit defektem Frontmatter übersprungen (%s): %s", quelle, e)
        return None
    if not isinstance(meta, dict):
        return None
    name = str(meta.get("name") or "").strip()
    applies_to = str(meta.get("applies_to") or "").strip()
    if not name or not applies_to:
        log.warning("Skill ohne name/applies_to übersprungen: %s", quelle)
        return None
    return Skill(
        name=name,
        version=str(meta.get("version") or "0").strip(),
        scope=scope,
        applies_to=applies_to,
        body=m.group(2),
        quelle=str(quelle),
    )


def _lies_references(skill_dir):
    """Alle references/*.md (sortiert) zu einem Text. evals/ wird NIE angefasst."""
    ref_dir = skill_dir / "references"
    if not ref_dir.is_dir():
        return ""
    stuecke = []
    for p in sorted(ref_dir.glob("*.md")):
        try:
            stuecke.append(p.read_text(encoding="utf-8"))
        except OSError as e:
            log.warning("Referenz nicht lesbar (%s): %s", p, e)
    return "\n\n".join(stuecke)


def _lies_skill_ordner(basis, scope, task):
    """Liest alle passenden Skills eines Ordners (base/ oder mandant-<id>/).

    Gibt {name -> Skill} zurück, GEFILTERT auf applies_to == task."""
    out = {}
    if not basis.is_dir():
        return out
    for skill_dir in sorted(p for p in basis.iterdir() if p.is_dir()):
        md = skill_dir / "SKILL.md"
        if not md.is_file():
            continue
        try:
            skill = _parse_skill_md(md.read_text(encoding="utf-8"), scope, md)
        except OSError as e:
            log.warning("SKILL.md nicht lesbar (%s): %s", md, e)
            continue
        if skill is None:
            continue
        if skill.applies_to != task:
            continue                      # harte Zuordnung Skill ↔ Schritt
        skill.references = _lies_references(skill_dir)
        out[skill.name] = skill
    return out


def load_skills(task, tenant_id=None, skills_dir=None, only=None):
    """Lädt die für `task` einschlägigen Basis- + Mandanten-Skills.

    `task`:      das Ergebnis/der Bereich, z.B. 'rechtsgrundlagenanalyse'. Nur
                 Skills mit passendem `applies_to` werden geladen (harte
                 Zuordnung – ein Skill kann nie in einen fremden Bereich geraten).
    `tenant_id`: Mandant (org_id). None/leer -> nur Basis-Skills.
    `skills_dir`: Wurzel mit base/ + mandant-<id>/. Fehlt sie, ist das Bündel leer.
    `only`:      Optionales Set/Liste von Skill-NAMEN. Damit bildet der einzelne
                 Verarbeitungsschritt sein Mapping ab (z.B. der Kartierungs-Schritt
                 nur 'rechtsgrundlagen-kartierung'), obwohl mehrere Skills demselben
                 Bereich angehören. None = alle des Bereichs.

    Rückgabe: SkillBundle (text = injizierbarer Block, versions = Nachweis).
    """
    if skills_dir is None:
        try:
            from flask import current_app
            skills_dir = current_app.config.get("SKILLS_DIR")
        except Exception:                 # noqa: BLE001 – ausserhalb App-Kontext
            skills_dir = None
    if not skills_dir:
        return SkillBundle()
    wurzel = Path(skills_dir)
    if not wurzel.is_dir():
        return SkillBundle()

    skills = _lies_skill_ordner(wurzel / "base", "base", task)

    # Mandanten-Layer NUR des aktuellen Mandanten – nie ein fremder.
    if tenant_id not in (None, ""):
        ordner = f"mandant-{tenant_id}"
        if _TENANT_DIR.match(ordner):
            for name, skill in _lies_skill_ordner(wurzel / ordner, "mandant", task).items():
                skills[name] = skill      # Mandanten-Delta gewinnt (Override)

    if only is not None:
        erlaubt = set(only)
        skills = {n: s for n, s in skills.items() if n in erlaubt}

    if not skills:
        return SkillBundle()
    geordnet = [skills[n] for n in sorted(skills)]
    text = "\n\n".join(s.als_block() for s in geordnet)
    versions = [{"name": s.name, "version": s.version, "scope": s.scope} for s in geordnet]
    return SkillBundle(text=text, versions=versions)


def compose_system(basis_system, bundle):
    """Fügt den Skill-Block an einen bestehenden System-Prompt an.

    Der ursprüngliche System-Prompt bleibt VORNE und behält das letzte Wort über
    das Ausgabeformat (JSON-Vertrag) und die harten Methodengrenzen – der Skill
    liefert die Methode (Sorgfalt, Quellenbelege, Ehrlichkeit über Lücken), nicht
    ein neues Ausgabeformat.
    """
    if not bundle:
        return basis_system
    return (
        f"{basis_system}\n\n"
        "--- METHODENLEITFADEN (Skill) ---\n"
        "Wende die folgende Methode konsequent an. Sie bestimmt das VORGEHEN "
        "(Gründlichkeit, Quellenbelege, ehrlicher Umgang mit Lücken). Das oben "
        "verlangte Ausgabeformat und die Methodengrenzen bleiben verbindlich.\n\n"
        f"{bundle.text}"
    )
