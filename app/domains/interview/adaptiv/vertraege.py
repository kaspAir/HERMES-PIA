"""Versionierte Verträge für Modellausgaben – und ihre Prüfung.

Das Modell liefert ÄNDERUNGSVORSCHLÄGE. Ob einer übernommen wird, entscheiden
Schema-, Bezugs-, Vokabular- und Konsistenzprüfungen hier im Code (Auftrag
Abschnitt 7). Kein Modelltext gelangt ungeprüft in den Zustand.

Was verworfen wird, wird mit Grund zurückgegeben – nie still geschluckt. So
bleibt nachvollziehbar, warum eine Angabe NICHT im Zustand steht.
"""
import json
import re
from dataclasses import dataclass, field

from app.domains.interview.adaptiv.models import BEZUG, ENTSCHEID
from app.domains.method import vorlagenzuordnung as vz

VERTRAG_AUSSAGEN = "aussagen-1.0"
VERTRAG_FRAGE = "frage-1.0"
VERTRAG_THEMEN = "rag-themen-1.0"
VERTRAG_FORMULIERUNG = "ausgangslage-1.0"

# Was das Modell bei einem Benutzerbeitrag vorschlagen darf.
OPERATIONEN = ("neu", "korrektur", "bestaetigen", "verwerfen", "widerspruch",
               "zurueckstellen", "unbekannt", "entscheid", "konflikt_loesen",
               "rag_bewerten")

# Arten, die das Modell einer NEUEN Aussage geben darf. «belegt» setzt nur ein
# hinterlegter Beleg, «systemvorschlag» nur das System selbst – nie die
# Auswertung eines Benutzerbeitrags.
ARTEN_AUS_BEITRAG = ("benutzerangabe", "annahme", "schaetzung", "unbekannt")

# Pseudo-Abschnitt für Eckdaten, die mehrere Kapitel speisen (Start, Ende,
# Dauer der Initialisierung; Personen des Deckblatts).
ECKDATEN = "eckdaten"
ECKDATEN_FELDER = ("start_initialisierung", "ende_initialisierung",
                   "dauer_initialisierung", "auftraggeber", "projektleiter",
                   "verwaltungseinheit")
DATUMSFELDER = ("start_initialisierung", "ende_initialisierung")

# Spalten, die der Code berechnet – das Modell darf sie nicht setzen.
BERECHNET = {"nr", "risikozahl"}

MAX_INHALT = 1000
MAX_FELD = 600
MAX_THEMA = 80

_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# Personentage mit Einheit: «45», «45 PT», «45 Personentage», «4,5 Tage».
_PT = re.compile(r"\s*(\d+(?:[.,]\d+)?)\s*(?:PT|Personentage?|Personen-Tage?|Arbeitstage?|Tage?)?\.?\s*",
                 re.IGNORECASE)
_SCHLUESSEL = re.compile(r"^A-\d{4}$")


@dataclass
class Pruefergebnis:
    gueltig: list = field(default_factory=list)
    verworfen: list = field(default_factory=list)      # [(op, grund)]
    bezug_unklar: str = ""
    vertrag: str = VERTRAG_AUSSAGEN

    @property
    def leer(self):
        return not self.gueltig and not self.bezug_unklar


# ---- Abschnittskatalog -------------------------------------------------------- #

def abschnittskatalog(methode):
    """{abschnitt_id: {"typ", "titel", "spalten", "auswahl"}} für Prompt und Prüfung.

    Abgeleitet aus der massgeblichen Methode der Session (kanonisch oder aus
    einer Organisationsvorlage) und den Auswahlfeldern der Vorlagenzuordnung.
    """
    katalog = {ECKDATEN: {"typ": "eckdaten", "titel": "Eckdaten der Initialisierung",
                          "spalten": list(ECKDATEN_FELDER), "auswahl": {}}}
    for s in (methode or {}).get("sections", []):
        typ = s.get("type")
        if typ not in ("free_text", "table"):
            continue
        spalten = [c["id"] for c in s.get("columns", []) if c.get("id") not in BERECHNET]
        auswahl = {c["id"]: c["vocabulary"] for c in s.get("columns", [])
                   if c.get("type") == "select" and c.get("vocabulary")}
        katalog[s["id"]] = {"typ": typ, "titel": s.get("title", s["id"]),
                            "spalten": spalten, "auswahl": auswahl}
    return katalog


# ---- Hilfen ------------------------------------------------------------------ #

def lies_json(roh):
    """Das erste JSON-Objekt aus einer Modellantwort – oder None."""
    if isinstance(roh, dict):
        return roh
    text = (roh or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text)
    try:
        wert = json.loads(text)
        return wert if isinstance(wert, dict) else None
    except (ValueError, TypeError):
        pass
    start, ende = text.find("{"), text.rfind("}")
    if start >= 0 and ende > start:
        try:
            wert = json.loads(text[start:ende + 1])
            return wert if isinstance(wert, dict) else None
        except (ValueError, TypeError):
            return None
    return None


def _text(wert, grenze):
    t = re.sub(r"\s+", " ", str(wert if wert is not None else "")).strip()
    return t[:grenze]


def _pruefe_ziele(ziele, katalog, hinweise):
    """Ziele normalisieren: nur bekannte Abschnitte, nur bekannte Spalten,
    Auswahlwerte nach Vorlage. Unbekanntes wird verworfen und vermerkt."""
    aus = []
    for z in ziele if isinstance(ziele, list) else []:
        if not isinstance(z, dict):
            continue
        abschnitt = str(z.get("abschnitt") or "").strip()
        info = katalog.get(abschnitt)
        if info is None:
            hinweise.append(f"unbekannter Abschnitt «{abschnitt}»")
            continue
        felder = {}
        for k, v in (z.get("felder") or {}).items() if isinstance(z.get("felder"), dict) else []:
            # Neun Monatsspalten der Vorlage sind keine Höchstdauer: weitere
            # Monate gehen in eine Fortsetzungstabelle (vorlagenzuordnung.yaml).
            weiterer_monat = (abschnitt == "projektorganisation" and re.fullmatch(r"monat_\d{1,2}", k))
            if k not in info["spalten"] and not weiterer_monat:
                if k not in BERECHNET:
                    hinweise.append(f"{abschnitt}: unbekannte Spalte «{k}»")
                continue
            if k in info["auswahl"]:
                wert = vz.auswahlwert(info["auswahl"][k], v)
                if wert is None:
                    if str(v or "").strip():
                        hinweise.append(f"{abschnitt}.{k}: «{v}» ist kein Auswahlwert der Vorlage")
                    continue
                felder[k] = wert
                continue
            t = _text(v, MAX_FELD)
            if not t:
                continue
            if abschnitt == ECKDATEN and k in DATUMSFELDER and not _ISO.match(t):
                # Ein Datum ohne Jahr oder Tag bleibt Text – unvollständig,
                # nicht ergänzt (Auftrag AT04: keine stillen Standardwerte).
                felder[k] = t
                felder[f"{k}_unvollstaendig"] = True
                continue
            if (abschnitt == "personalaufwand" and k == "aufwand") or weiterer_monat \
                    or (abschnitt == "projektorganisation" and k.startswith("monat_")):
                # Die Spalte heisst «Aufwand in PT» – die Einheit steht im Kopf,
                # nicht in der Zelle. Ein echtes Modell liefert «45 Personentage»
                # (dev, 15.10.2026); nur eine eindeutige Zahl mit PT-Einheit wird
                # zur Zahl, alles andere bleibt, wie es gesagt wurde.
                m = _PT.fullmatch(t)
                if m:
                    t = m.group(1).replace(",", ".")
            felder[k] = t
        eintrag = {"abschnitt": abschnitt, "felder": felder}
        # «Begründet nicht anwendbar» ist ein eigener Zustand – nicht leer und
        # nicht unbekannt (Auftrag Abschnitt 9). Die Begründung ist der Inhalt
        # der Aussage.
        if z.get("nicht_anwendbar") is True:
            eintrag["nicht_anwendbar"] = True
        aus.append(eintrag)
    return aus


# ---- Vertrag: Aussagen aus einem Benutzerbeitrag ------------------------------- #

def pruefe_aussagen_antwort(roh, katalog, aussagen, konflikte=None, themen=None):
    """Prüft die Modellantwort auf einen Benutzerbeitrag.

    `aussagen`:  {schluessel: {"status": …}} des AKTUELLEN Zustands
    `konflikte`: {id: status}, `themen`: {id: status}
    Rückgabe: Pruefergebnis mit gültigen, normalisierten Operationen.
    """
    erg = Pruefergebnis()
    daten = lies_json(roh)
    if daten is None:
        erg.verworfen.append(({}, "Antwort ist kein gültiges JSON-Objekt"))
        return erg
    konflikte = konflikte or {}
    themen = themen or {}
    erg.bezug_unklar = _text(daten.get("bezug_unklar"), 300) if daten.get("bezug_unklar") else ""

    ops = daten.get("operationen")
    if not isinstance(ops, list):
        erg.verworfen.append((daten, "Feld «operationen» fehlt oder ist keine Liste"))
        return erg

    def aktiv(s):
        return s in aussagen and aussagen[s].get("status") == "aktiv"

    for op in ops:
        if not isinstance(op, dict):
            erg.verworfen.append((op, "Operation ist kein Objekt"))
            continue
        art_op = op.get("op")
        if art_op not in OPERATIONEN:
            erg.verworfen.append((op, f"unbekannte Operation «{art_op}»"))
            continue
        hinweise = []

        if art_op in ("neu", "korrektur"):
            inhalt = _text(op.get("inhalt"), MAX_INHALT)
            if not inhalt:
                erg.verworfen.append((op, "Inhalt fehlt"))
                continue
            if art_op == "korrektur" and not aktiv(op.get("aussage")):
                erg.verworfen.append((op, f"Korrektur bezieht sich auf keine aktive Aussage ({op.get('aussage')})"))
                continue
            art = op.get("art") or "benutzerangabe"
            gefolgert = op.get("quelle") == "gefolgert"
            if not gefolgert and art not in ARTEN_AUS_BEITRAG:
                hinweise.append(f"Art «{art}» aus einem Beitrag nicht zulässig -> benutzerangabe")
                art = "benutzerangabe"
            # Ohne Angabe None: eine NEUE Aussage gilt dann der Initialisierung,
            # eine KORREKTUR erbt den Bezug der korrigierten. Ein Vorgabewert
            # hier würde «gesamtvorhaben» bei jeder Korrektur still überschreiben.
            bezug = op.get("bezug") if op.get("bezug") in BEZUG else None
            entscheid = op.get("entscheid") if op.get("entscheid") in ENTSCHEID else None
            neu = {
                "op": art_op,
                "inhalt": inhalt,
                "thema": _text(op.get("thema"), MAX_THEMA),
                # Gefolgertes ist eine Interpretation des Systems, keine Angabe
                # des Benutzers – auch wenn es dieselben Worte trägt.
                "art": "interpretation" if gefolgert else art,
                "herkunft": "system" if gefolgert else "benutzer",
                "bestaetigt": not gefolgert,
                "bezug": bezug,
                "entscheid": entscheid,
                "beleg": _text(op.get("beleg"), 300) or None,
                "ziele": _pruefe_ziele(op.get("ziele"), katalog, hinweise),
            }
            if art_op == "korrektur":
                neu["aussage"] = op["aussage"]
            neu["hinweise"] = hinweise
            erg.gueltig.append(neu)

        elif art_op in ("bestaetigen", "verwerfen"):
            if not aktiv(op.get("aussage")):
                erg.verworfen.append((op, f"keine aktive Aussage «{op.get('aussage')}»"))
                continue
            erg.gueltig.append({"op": art_op, "aussage": op["aussage"]})

        elif art_op == "entscheid":
            if not aktiv(op.get("aussage")) or op.get("wert") not in ("idee", "entscheid"):
                erg.verworfen.append((op, "Entscheid braucht aktive Aussage und Wert idee|entscheid"))
                continue
            erg.gueltig.append({"op": "entscheid", "aussage": op["aussage"], "wert": op["wert"]})

        elif art_op == "widerspruch":
            ids = [a for a in (op.get("aussagen") or []) if aktiv(a)]
            beschreibung = _text(op.get("beschreibung"), 400)
            if len(set(ids)) < 2 or not beschreibung:
                erg.verworfen.append((op, "Widerspruch braucht zwei aktive Aussagen und eine Beschreibung"))
                continue
            erg.gueltig.append({"op": "widerspruch", "aussagen": sorted(set(ids)),
                                "beschreibung": beschreibung})

        elif art_op == "konflikt_loesen":
            kid = op.get("konflikt")
            if konflikte.get(kid) != "offen" and konflikte.get(str(kid)) != "offen":
                erg.verworfen.append((op, f"kein offener Konflikt «{kid}»"))
                continue
            gilt = op.get("gilt")
            if gilt is not None and not aktiv(gilt):
                erg.verworfen.append((op, f"«{gilt}» ist keine aktive Aussage"))
                continue
            erg.gueltig.append({"op": "konflikt_loesen", "konflikt": int(kid), "gilt": gilt,
                                "loesung": _text(op.get("loesung"), 300)})

        elif art_op in ("zurueckstellen", "unbekannt"):
            thema = _text(op.get("thema"), MAX_THEMA)
            if not thema:
                erg.verworfen.append((op, "Thema fehlt"))
                continue
            erg.gueltig.append({"op": art_op, "thema": thema,
                                "inhalt": _text(op.get("inhalt"), MAX_INHALT) or thema,
                                "ziele": _pruefe_ziele(op.get("ziele"), katalog, hinweise),
                                "hinweise": hinweise})

        elif art_op == "rag_bewerten":
            tid = op.get("thema_id")
            if str(tid) not in {str(k) for k in themen}:
                erg.verworfen.append((op, f"unbekanntes RAG-Thema «{tid}»"))
                continue
            erg.gueltig.append({"op": "rag_bewerten", "thema_id": int(tid),
                                "passt": bool(op.get("passt"))})
    return erg


# ---- Vertrag: Formulierung einer Frage ---------------------------------------- #

def pruefe_frage(roh):
    """{"frage": …} – genau EINE gut beantwortbare Hauptfrage, oder None.

    Keine Fragenbatterie: mehr als zwei Fragezeichen werden abgelehnt, ebenso
    überlange Texte. Der Aufrufer fällt dann auf die Vorlagenfrage zurück.
    """
    daten = lies_json(roh)
    if not daten:
        return None
    frage = _text(daten.get("frage"), 600)
    if not frage or len(frage) > 500 or frage.count("?") > 2:
        return None
    return {"frage": frage, "vertrag": VERTRAG_FRAGE}


# ---- Vertrag: Formulierung der Ausgangslage ----------------------------------- #

def pruefe_formulierung(roh, aussagen_schluessel):
    """{"text": …, "verwendet": ["A-0001", …]} – nur bekannte Aussagen."""
    daten = lies_json(roh)
    if not daten:
        return None
    text = str(daten.get("text") or "").strip()
    if not text:
        return None
    verwendet = [s for s in (daten.get("verwendet") or []) if s in aussagen_schluessel]
    return {"text": text[:8000], "verwendet": verwendet, "vertrag": VERTRAG_FORMULIERUNG}


def ist_schluessel(wert):
    return bool(_SCHLUESSEL.match(str(wert or "")))
