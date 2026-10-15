"""Zugriff auf die versionierte Vorlagenzuordnung (`vorlagenzuordnung.yaml`).

Eine Stelle für alles, was die Word-Vorlage festlegt: Auswahlwerte samt
Zahlenwert, Basis- und Beispielzeilen, Fussnoten, Rechenregeln. Code, der
eine dieser Fragen beantwortet, fragt hier – damit eine geänderte Vorlage an
EINER Stelle nachgeführt wird und nicht in sieben verstreuten Konstanten.
"""
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

import yaml

_STANDARD = Path(__file__).resolve().parents[3] / "methods" / "hermes_pia" / "vorlagenzuordnung.yaml"


@lru_cache(maxsize=4)
def lade(pfad=None):
    """Die Zuordnung als Dict (zwischengespeichert)."""
    with open(pfad or _STANDARD, encoding="utf-8") as f:
        return yaml.safe_load(f)


def version():
    return str(lade()["zuordnung"]["version"])


def kapitel(kapitel_id):
    for k in lade()["kapitel"]:
        if k["id"] == kapitel_id:
            return k
    return None


# ---- Auswahlwerte ---------------------------------------------------------- #

def _schluessel(text):
    """Vergleichsform: Kleinschreibung, ohne Akzente, ohne Leerraum-Varianten."""
    t = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", t).strip().lower()


def werte(vokabular):
    """Die Beschriftungen eines Vokabulars in Vorlagenreihenfolge."""
    eintrag = lade()["vokabulare"][vokabular]
    return [w["label"] if isinstance(w, dict) else w for w in eintrag["werte"]]


def _eintraege(vokabular):
    eintrag = lade()["vokabulare"][vokabular]
    return [w if isinstance(w, dict) else {"label": w, "wert": None}
            for w in eintrag["werte"]]


def auswahlwert(vokabular, wert):
    """Der Vorlagenwert zu einer Angabe – oder None, wenn er nicht eindeutig ist.

    Erkannt wird: die exakte Beschriftung, dieselbe ohne Zahlenteil («Niedrig»
    für «Niedrig = 1»), der Zahlenwert allein und die abgebildeten Altwerte.
    Ein Platzhalter des Steuerelements («Auswählen») ist kein Wert.
    """
    if wert is None:
        return None
    roh = str(wert).strip()
    if not roh or _schluessel(roh) in ("auswahlen", "wahlen sie ein element aus."):
        return None
    k = _schluessel(roh)
    for e in _eintraege(vokabular):
        label = e["label"]
        if k == _schluessel(label):
            return label
        kurz = _schluessel(label.split("=")[0])
        if k == kurz:
            return label
        if e.get("wert") is not None and k == str(e["wert"]):
            return label
    alt = (lade().get("altwerte") or {}).get(vokabular) or {}
    for alter, neu in alt.items():
        if k == _schluessel(alter):
            return neu
    return None


def zahlenwert(vokabular, wert):
    """Der Zahlenwert einer Auswahl (z.B. «Hoch = 3» -> 3) – oder None."""
    label = auswahlwert(vokabular, wert)
    if label is None:
        return None
    for e in _eintraege(vokabular):
        if e["label"] == label:
            return e.get("wert")
    return None


def risikozahl(ew, ag):
    """EW × AG nach Fussnote 4 der Vorlage – None, sobald ein Faktor unbekannt ist.

    Unbekannt ist nicht 0 und nicht «Tief»: eine Risikozahl aus einem geratenen
    Faktor sähe aus wie eine Bewertung, die niemand vorgenommen hat.
    """
    a = zahlenwert("eintrittswahrscheinlichkeit", ew)
    b = zahlenwert("auswirkungsgrad", ag)
    if a is None or b is None:
        return None
    return a * b


# ---- Zeilen der Vorlage ---------------------------------------------------- #

def basiszeilen(kapitel_id):
    """Die festen ersten Spalten einer Tabelle (z.B. die acht Termin-Ergebnisse)."""
    k = kapitel(kapitel_id) or {}
    return list(((k.get("basiszeilen") or {}).get("zeilen")) or [])


def vorbelegung(kapitel_id):
    k = kapitel(kapitel_id) or {}
    return [dict(z) for z in ((k.get("vorbelegung") or {}).get("zeilen")) or []]


def beispiele(kapitel_id):
    k = kapitel(kapitel_id) or {}
    return [dict(z) for z in k.get("beispiele") or []]


def ist_beispiel(kapitel_id, zeile):
    """Stimmt eine Zeile mit einem Beispiel der Vorlage überein?

    Verglichen werden nur die Felder, die das Beispiel nennt. So erkennt die
    Prüfung auch ein Beispiel, dessen übrige Spalten leer geblieben sind.
    """
    if not isinstance(zeile, dict):
        return False
    for b in beispiele(kapitel_id):
        felder = [k for k in b if k != "ausgeblendet"]
        if felder and all(_schluessel(zeile.get(f)) == _schluessel(b[f]) for f in felder):
            return True
    return False


def tabellenkopf(kapitel_id):
    k = kapitel(kapitel_id) or {}
    return list(((k.get("tabelle") or {}).get("kopf")) or [])


def spalten(kapitel_id):
    k = kapitel(kapitel_id) or {}
    return list(((k.get("tabelle") or {}).get("spalten")) or [])
