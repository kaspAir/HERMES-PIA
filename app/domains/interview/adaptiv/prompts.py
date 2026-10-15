"""Versionierte Prompts: je Datei unter `prompt_texte/` ein Prompt mit Kopf.

Der Kopf trägt `version` und `vertrag`. Beide werden an jedem verarbeiteten
Beitrag gespeichert (`PiaNachricht.versionen_json`), damit sich jede Ausgabe
einer Prompt- und Vertragsversion zuordnen lässt (Auftrag Abschnitt 7/13).
"""
from functools import lru_cache
from pathlib import Path

import yaml

_ORDNER = Path(__file__).resolve().parent / "prompt_texte"


@lru_cache(maxsize=16)
def lade(name):
    """(kopf: dict, text: str) eines Prompts."""
    roh = (_ORDNER / f"{name}.md").read_text(encoding="utf-8")
    if not roh.startswith("---"):
        raise ValueError(f"Prompt «{name}» ohne Kopf")
    _, kopf, text = roh.split("---", 2)
    return yaml.safe_load(kopf), text.strip()


def version(name):
    return lade(name)[0]["version"]


def fuelle(name, **werte):
    """Prompttext mit eingesetzten Platzhaltern {name} – ohne str.format,
    damit die JSON-Beispiele mit ihren geschweiften Klammern stehen bleiben."""
    text = lade(name)[1]
    for k, v in werte.items():
        text = text.replace("{" + k + "}", str(v))
    return text
