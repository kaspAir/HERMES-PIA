"""Vollständigkeit nach dem offengelegten Abschlussprüfprofil.

Ersetzt «Text vorhanden = vollständig». Je Kriterium ein expliziter Zustand:

    erfuellt | offen | unbekannt | zurueckgestellt | nicht_anwendbar | konflikt

Alles hier ist deterministisch – Zahlen, Felder, Zeilen, Summen. Ob eine
Messgrösse INHALTLICH taugt, ist eine begründete Bewertung (Fachprüfung) und
wird hier nicht vorgetäuscht. Eine positive Modell-Selbsteinschätzung kann
keine dieser Prüfungen überstimmen (Auftrag Abschnitt 9).
"""
import re
from functools import lru_cache
from pathlib import Path

import yaml

from app.domains.interview.adaptiv.projektion import ins_dokument

_PROFIL = Path(__file__).resolve().parents[4] / "methods" / "hermes_pia" / "abschlussprofil.yaml"

ERLEDIGT = ("erfuellt", "nicht_anwendbar")
BLOCKIEREND = ("offen", "konflikt", "unbekannt", "zurueckgestellt")
REIHENFOLGE_GEWICHT = {"wesentlich": 0, "erforderlich": 1, "vertiefung": 2}


@lru_cache(maxsize=2)
def profil(pfad=None):
    with open(pfad or _PROFIL, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _gefuellt(wert):
    return bool(str(wert if wert is not None else "").strip())


def _zielt_auf(aussage, abschnitt):
    return any(z.get("abschnitt") == abschnitt for z in aussage.get("ziele") or [])


def _norm(t):
    return re.sub(r"\s+", " ", str(t or "")).strip().lower()


def _untersuchungsauftrag(aussagen, thema):
    """Wurde ein unbekannter Punkt ausdrücklich zum Untersuchungsauftrag gemacht?"""
    t = _norm(thema)
    return bool(t) and any(
        a["status"] == "aktiv" and a["bestaetigt"] and _norm(a.get("thema")) == t
        and _zielt_auf(a, "ziele") for a in aussagen)


def _markierung(aussagen, abschnitt):
    """Ausdrückliche Markierungen eines Abschnitts: unbekannt, zurückgestellt,
    begründet nicht anwendbar."""
    nicht_anwendbar, unbekannt, zurueck = [], [], []
    for a in aussagen:
        if a["status"] != "aktiv" or not _zielt_auf(a, abschnitt):
            continue
        if any(z.get("abschnitt") == abschnitt and z.get("nicht_anwendbar")
               for z in a["ziele"]) and a["bestaetigt"]:
            nicht_anwendbar.append(a)
        elif a["art"] == "unbekannt" and not _untersuchungsauftrag(aussagen, a.get("thema")):
            (zurueck if a.get("zurueckgestellt") else unbekannt).append(a)
    return nicht_anwendbar, unbekannt, zurueck


def _zeilen(answers, abschnitt):
    eintrag = answers.get(abschnitt) or {}
    zeilen = eintrag.get("extracted")
    return [z for z in zeilen if isinstance(z, dict)] if isinstance(zeilen, list) else []


def _eigene_zeilen(answers, abschnitt):
    """Zeilen mit Projektinhalt – ohne die blossen Vorlagenzeilen."""
    return [z for z in _zeilen(answers, abschnitt) if z.get("_herkunft") != "vorlage"
            or any(_gefuellt(v) for k, v in z.items()
                   if not k.startswith("_") and k not in ("nr", "rolle", "ergebnis", "phase"))]


def _zahl(wert):
    m = re.search(r"\d+(?:[.,]\d+)?", str(wert or ""))
    return float(m.group().replace(",", ".")) if m else None


def _pruefe(k, aussagen, answers, kontext):
    """(zustand, details) eines Kriteriums ohne Markierungen."""
    p = k["pruefung"]
    art = p["art"]
    ab = k["abschnitt"]
    if art in ("aussagen", "aussagen_oder_na"):
        # Eine Begründung «nicht anwendbar» ist kein Inhalt des Kapitels – sie
        # zählt hier nicht, sonst hiesse das Kriterium «erfüllt» statt
        # «begründet nicht anwendbar» (zwei verschiedene Zustände, Auftrag 9).
        n = sum(1 for a in aussagen if ins_dokument(a, ab) and any(
            z.get("abschnitt") == ab and not z.get("nicht_anwendbar") for z in a["ziele"]))
        if ab == "rahmenbedingungen":
            # Die HERMES-Vorgabe der Vorlage zählt nicht als Projektangabe.
            n = len([z for z in _eigene_zeilen(answers, ab) if z.get("_herkunft") != "vorlage"])
        return ("erfuellt" if n >= p.get("mindestens", 1) else "offen"), []
    if art == "eckdatum":
        eck = answers.get("_eckdaten") or {}
        felder = [p["feld"]] + ([p["oder_feld"]] if p.get("oder_feld") else [])
        for f in felder:
            e = eck.get(f)
            if e and (not p.get("vollstaendig") or not e.get("unvollstaendig")):
                return "erfuellt", []
        offen = [f"«{eck[f]['wert']}» ist unvollständig" for f in felder
                 if f in eck and eck[f].get("unvollstaendig")]
        return "offen", offen
    if art == "zeilen":
        n = sum(1 for z in _eigene_zeilen(answers, ab) if _gefuellt(z.get(p["spalte"])))
        return ("erfuellt" if n >= p.get("mindestens", 1) else "offen"), []
    if art == "zeilenfelder":
        zeilen = _zeilen(answers, ab)
        if p.get("zeilen"):
            zeilen = [z for z in zeilen if z.get("rolle") in p["zeilen"]]
        elif ab not in ("termine",):
            zeilen = _eigene_zeilen(answers, ab)
        if not zeilen:
            return "offen", []
        details = []
        for z in zeilen:
            fehlend = [s for s in p["spalten"] if not _gefuellt(z.get(s))]
            if fehlend:
                bez = z.get("beschreibung") or z.get("ergebnis") or z.get("rolle") or z.get("nr") or "?"
                details.append(f"{str(bez)[:60]}: {', '.join(fehlend)} fehlt")
        return ("offen" if details else "erfuellt"), details
    if art == "kosten_berechenbar":
        personal = [z for z in _zeilen(answers, "personalaufwand") if _zahl(z.get("aufwand"))]
        if not personal:
            return "offen", ["Personalaufwand in PT fehlt noch"]
        kosten = _zeilen(answers, "kosten")
        if any(z.get("_offen") == "kostensatz" for z in kosten):
            return "offen", ["kein Kostensatz hinterlegt"]
        total = next((z for z in kosten if "total" in _norm(z.get("phase"))), None)
        return ("erfuellt" if total and _gefuellt(total.get("betrag")) else "offen"), []
    if art == "pt_konsistent":
        soll = {}
        for z in _zeilen(answers, "personalaufwand"):
            pt = _zahl(z.get("aufwand"))
            if pt:
                soll[_norm(z.get("rolle"))] = soll.get(_norm(z.get("rolle")), 0) + pt
        if not soll:
            return "offen", ["Personalaufwand in PT fehlt noch"]
        ist = {}
        for z in _zeilen(answers, "projektorganisation"):
            rolle = _norm(str(z.get("rolle_person", "")).split("/")[0])
            if rolle == "total":
                continue
            summe = sum(_zahl(v) or 0 for k, v in z.items() if k.startswith("monat_"))
            ist[rolle] = ist.get(rolle, 0) + summe
        if not ist:
            return "offen", ["Monatsverteilung fehlt"]
        abweichung = [f"{r}: 3.1 = {soll[r]:g} PT, Kap. 5 = {ist.get(r, 0):g} PT"
                      for r in soll if abs(soll[r] - ist.get(r, 0)) > 0.5]
        return ("konflikt" if abweichung else "erfuellt"), abweichung
    return "offen", [f"unbekannte Prüfart «{art}»"]


def bewerte(aussagen, answers, konflikte=None, kontext=None):
    """Alle Kriterien des Profils mit Zustand und Details, nach Gewicht sortiert."""
    konflikte = konflikte or []
    kontext = kontext or {}
    offen_konflikt = {}
    for kf in konflikte:
        if kf["status"] != "offen":
            continue
        for sch in kf["aussagen"]:
            offen_konflikt.setdefault(sch, []).append(kf)

    ergebnisse = []
    for k in profil()["kriterien"]:
        ab = k["abschnitt"]
        na, unbekannt, zurueck = _markierung(aussagen, ab)
        betroffen = [a["schluessel"] for a in aussagen
                     if a["status"] == "aktiv" and _zielt_auf(a, ab)]
        konfl = sorted({kf["id"] for sch in betroffen for kf in offen_konflikt.get(sch, [])})
        zustand, details = _pruefe(k, aussagen, answers, kontext)
        if zustand != "erfuellt":
            if na:
                zustand, details = "nicht_anwendbar", [na[-1]["inhalt"][:160]]
            elif unbekannt:
                zustand = "unbekannt"
            elif zurueck:
                zustand = "zurueckgestellt"
        if konfl and zustand != "nicht_anwendbar":
            zustand = "konflikt"
        ergebnisse.append({
            "id": k["id"], "abschnitt": ab, "gewicht": k["gewicht"],
            "herkunft": k["herkunft"], "beschreibung": k["beschreibung"],
            "aktion": k.get("aktion", "erkunden"),
            "vorlagenfrage": k.get("vorlagenfrage", ""),
            "zustand": zustand, "details": details, "konflikte": konfl,
            "aussagen": betroffen,
        })
    ergebnisse.sort(key=lambda e: REIHENFOLGE_GEWICHT.get(e["gewicht"], 9))
    return ergebnisse


def reife(ergebnisse):
    """'bereit_zur_pruefung' oder 'entwurf_offen' – mit den Blockern.

    Bereit heisst: kein wesentliches oder erforderliches Kriterium offen,
    unbekannt, zurückgestellt oder im Widerspruch. Vertiefungen blockieren nicht.
    Das ist ein Bearbeitungszustand – keine Prüfung, Abnahme oder Freigabe.
    """
    blocker = [e for e in ergebnisse if e["gewicht"] in ("wesentlich", "erforderlich")
               and e["zustand"] in BLOCKIEREND]
    return ("bereit_zur_pruefung" if not blocker else "entwurf_offen"), blocker
