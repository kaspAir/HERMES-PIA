"""Basis- und Mandanten-Skills als Laufzeit-Steuerung der LLM-Aufrufe.

Eigenes Modul: der PIA-Kern und die Ergebnis-Module rufen den Loader nur auf,
tragen die Skill-Logik aber nicht in sich. So bleibt die Wartung getrennt und ein
neuer Mandant ist reine Konfiguration (Ordner + Registry), kein Code-Deploy.
"""
from app.domains.skills.loader import SkillBundle, compose_system, load_skills

__all__ = ["SkillBundle", "compose_system", "load_skills"]
