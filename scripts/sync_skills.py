"""Spiegelt die kanonische Skill-Quelle (Git-Repo) in die App: skills/base/.

Grundsatz «eine Quelle, zwei Orte»: dieselbe SKILL.md gilt in Cowork UND in der
App. Cowork liest sie aus ~/.claude/skills, die App aus ihrem eigenen skills/base
– dieses Skript hält Letzteres mit dem Repo deckungsgleich.

    python scripts/sync_skills.py "C:/Projekte/Skills"
    python scripts/sync_skills.py "$HOME/Skills" --dest skills/base

Kopiert je Skill NUR SKILL.md + references/. Der evals/-Ordner wird bewusst NICHT
mitgenommen (Entwicklungs-/Qualitäts-Artefakt, gehört nicht ins Deployment).
Mandanten-Ordner (mandant-<id>/) pflegt der Betrieb separat und werden hier NICHT
angefasst – das Skript räumt nur base/ auf und neu ein.
"""
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def sync(quelle, dest):
    quelle, dest = Path(quelle), Path(dest)
    if not quelle.is_dir():
        print(f"FEHLER: Quelle {quelle} existiert nicht.")
        return 1
    skills = [p for p in sorted(quelle.iterdir())
              if p.is_dir() and (p / "SKILL.md").is_file()]
    if not skills:
        print(f"Keine Skills (Ordner mit SKILL.md) in {quelle}.")
        return 1

    dest.mkdir(parents=True, exist_ok=True)
    kopiert = 0
    for skill in skills:
        ziel = dest / skill.name
        if ziel.exists():
            shutil.rmtree(ziel)
        ziel.mkdir(parents=True)
        shutil.copy2(skill / "SKILL.md", ziel / "SKILL.md")
        ref = skill / "references"
        if ref.is_dir():
            shutil.copytree(ref, ziel / "references")
        # evals/ bewusst ausgelassen.
        print(f"  + {skill.name}" + ("  (+ references)" if ref.is_dir() else ""))
        kopiert += 1
    print(f"\nFertig: {kopiert} Skill(s) nach {dest} gespiegelt (evals ausgelassen).")
    return 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dest = ROOT / "skills" / "base"
    if "--dest" in sys.argv:
        dest = Path(sys.argv[sys.argv.index("--dest") + 1])
    if not args:
        print('Aufruf: python scripts/sync_skills.py "<skills-repo>" [--dest skills/base]')
        sys.exit(2)
    sys.exit(sync(args[0], dest))
