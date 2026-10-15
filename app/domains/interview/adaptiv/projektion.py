"""Projektion: aus den Aussagen des Zustands werden die Dokumentdaten.

`answers_json` ist die Sicht, die Generierung, Invariantenprüfung,
Projektwissen, Freigabe, Rechtsgrundlagen- und Schutzbedarfsanalyse lesen.
Sie wird hier VOLLSTÄNDIG aus dem Zustand neu berechnet – deterministisch,
ohne Modellaufruf. Derselbe Zustand ergibt dieselben Dokumentdaten.

Was NICHT ins Dokument gelangt:
- unbestätigte Interpretationen und Systemvorschläge (AT20: neue
  Systembehauptungen werden nicht still zu Projektfakten),
- verworfene und ersetzte Aussagen,
- als «unbekannt» oder zurückgestellt markierte Punkte (sie sind offene
  Punkte, keine Inhalte),
- Angaben zum späteren Gesamtvorhaben in Kapiteln, die nur die
  Initialisierung betreffen (AT06: ein Gesamtbudget ist kein
  Initialisierungsbudget).

Unsicheres bleibt als solches erkennbar (AT04): eine Annahme trägt im
Dokument den Vermerk «(unbestätigt)».
"""
import hashlib
import json
import re

from app.domains.interview.adaptiv.vertraege import ECKDATEN
from app.domains.method import vorlagenzuordnung as vz

# Kapitel, die ausschliesslich die Phase Initialisierung beschreiben. Angaben
# zum Gesamtvorhaben gehören nicht hinein – sie sind Kontext (Ausgangslage)
# oder Vorgabe für die Durchführung (Rahmenbedingungen).
NUR_INITIALISIERUNG = {"ziele", "personalaufwand", "sachmittel", "kosten",
                       "termine", "projektorganisation", "kommunikation", "risiken"}

UNSICHER_VERMERK = "(unbestätigt)"

# Rollen-Synonyme für die Basiszeilen AG/PL der Vorlage.
_ROLLEN = {
    "AG": ("ag", "auftraggeber", "auftraggeberin", "auftraggeber/in"),
    "PL": ("pl", "projektleiter", "projektleiterin", "projektleiter/in", "projektleitung"),
}


def _norm(text):
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def ins_dokument(aussage, abschnitt):
    """Gehört diese Aussage in diesen Abschnitt des Dokuments?"""
    if aussage["status"] != "aktiv":
        return False
    # Übernommener Altbestand stand schon im bisherigen Dokument. Er bleibt
    # dort, bis er bestätigt, berichtigt oder verworfen wird – sonst verlöre
    # die Umstellung Inhalte. Die Bestätigung wird NICHT unterstellt: die
    # Abschlussprüfung blockiert, solange Altbestand unbestätigt ist.
    if not aussage["bestaetigt"] and aussage["herkunft"] != "altbestand":
        return False
    if aussage["art"] == "unbekannt" or aussage.get("zurueckgestellt"):
        return False
    if abschnitt in NUR_INITIALISIERUNG and aussage.get("bezug") in ("gesamtvorhaben", "unklar"):
        return False
    return True


def _mit_vermerk(text, aussage):
    t = str(text or "").strip()
    if aussage["art"] == "annahme" and t and UNSICHER_VERMERK not in t:
        return f"{t} {UNSICHER_VERMERK}"
    return t


def basis_hash(aussagen):
    """Kennung des Aussagenstands, aus dem ein Text formuliert wurde."""
    teile = [f"{a['schluessel']}|{a['inhalt']}|{a['art']}|{a['bezug']}" for a in aussagen]
    return hashlib.sha256("\n".join(teile).encode("utf-8")).hexdigest()[:16]


# ---- Tabellenzeilen ----------------------------------------------------------- #

def _rollenschluessel(rolle):
    r = _norm(rolle)
    for kurz, synonyme in _ROLLEN.items():
        if r in synonyme:
            return kurz
    return None


def _passt_auf_basiszeile(wert, basis):
    """Gehört ein Ergebnisname zu einer Basiszeile der Vorlage?"""
    w, b = _norm(wert), _norm(basis)
    if not w:
        return False
    kern = b.split("(")[0].strip()
    return w == b or w == kern or (len(w) >= 6 and kern.startswith(w)) or (len(kern) >= 6 and w.startswith(kern))


def _zeilen_aus_aussagen(abschnitt, aussagen):
    zeilen = []
    for a in aussagen:
        if not ins_dokument(a, abschnitt):
            continue
        for z in a["ziele"]:
            if z.get("abschnitt") != abschnitt:
                continue
            felder = {k: v for k, v in (z.get("felder") or {}).items()
                      if not k.endswith("_unvollstaendig")}
            if not any(str(v).strip() for v in felder.values()):
                continue
            zeile = {k: _mit_vermerk(v, a) if isinstance(v, str) else v for k, v in felder.items()}
            zeile["_aussagen"] = [a["schluessel"]]
            zeile["_herkunft"] = a["herkunft"]
            zeilen.append(zeile)
    return zeilen


# Spalte, über die eine eigene Zeile einer Vorbelegungszeile der Vorlage
# zugeordnet wird. Tabellen ohne Eintrag werden NICHT verschmolzen: zwei
# Systemziele sind zwei Ziele, auch wenn ihre Kategorie gleich ist.
VERSCHMELZUNGSSPALTE = {
    "definitionen": "abkuerzung",
    "vorgaben_methoden": "titel",
    "rahmenbedingungen": "vorgaben",
}


# «Begründet nicht anwendbar» steht im Dokument als eigene Zeile mit der
# Begründung der Projektleitung – sonst bliebe die Platzhalterzeile der Vorlage
# stehen, und das Dokument sähe unbearbeitet aus (Dokumentprüfung D-011).
NA_SPALTE = {"sachmittel": ("bezeichnung", "beschreibung"),
             "kommunikation": ("empfaenger", "inhalt"),
             "rahmenbedingungen": ("vorgaben", "beschreibung"),
             "referenzierte_dokumente": ("name", None),
             "mitgeltende_unterlagen": ("name", None)}
MIT_VORBELEGUNG = {"rahmenbedingungen"}     # die HERMES-Vorgabe bleibt stehen


def _na_zeile(abschnitt, aussagen):
    na = [a for a in aussagen if ins_dokument(a, abschnitt) and any(
        z.get("abschnitt") == abschnitt and z.get("nicht_anwendbar") for z in a["ziele"])]
    if not na:
        return None
    a = na[-1]
    titel, text = NA_SPALTE[abschnitt]
    zeile = {titel: "Keine" if text else f"Keine – {a['inhalt']}",
             "_aussagen": [a["schluessel"]], "_herkunft": a["herkunft"], "_nicht_anwendbar": True}
    if text:
        zeile[text] = a["inhalt"]
    return zeile


def _verschmelze(basis, eigene, schluesselspalte, passt):
    """Eigene Zeilen in Basiszeilen der Vorlage einsortieren; Rest anhängen.

    Ziel einer Verschmelzung sind NUR die Zeilen der Vorlage, nie bereits
    angehängte eigene Zeilen – sonst fielen zwei gleichartige Angaben des
    Benutzers zu einer zusammen.
    """
    vorlage = list(basis)
    for e in eigene:
        ziel = next((b for b in vorlage if passt(e.get(schluesselspalte), b.get(schluesselspalte))), None)
        if ziel is None:
            basis.append(e)
            continue
        for k, v in e.items():
            if k == schluesselspalte or k.startswith("_"):
                continue
            if str(v).strip():
                ziel[k] = v
        ziel["_aussagen"] = ziel.get("_aussagen", []) + e.get("_aussagen", [])
        ziel["_herkunft"] = e.get("_herkunft", ziel.get("_herkunft"))
    return basis


def _zahl(wert):
    m = re.search(r"\d+(?:[.,]\d+)?", str(wert or ""))
    return float(m.group().replace(",", ".")) if m else None


def _summenzeile(zeilen):
    """«Total» je Monat (Vorlage Kap. 5) – über ALLE Monate, auch über neun."""
    monate = sorted({k for z in zeilen for k in z if re.fullmatch(r"monat_\d+", k)},
                    key=lambda k: int(k.split("_")[1]))
    total = {"rolle_person": vz.kapitel("projektorganisation")["summenzeile"]["label"],
             "_herkunft": "berechnet"}
    for m in monate:
        werte = [_zahl(z.get(m)) for z in zeilen]
        werte = [w for w in werte if w is not None]
        if werte:
            total[m] = f"{sum(werte):g}"
    return total


def _nummeriere(zeilen, format_):
    for i, z in enumerate(zeilen, 1):
        z["nr"] = format_.format(nr=i)
    return zeilen


# ---- Eckdaten ------------------------------------------------------------------ #

def eckdaten(aussagen):
    """{feld: {"wert", "aussage", "unvollstaendig"}} – jeweils die NEUESTE Angabe."""
    aus = {}
    for a in aussagen:
        if not ins_dokument(a, ECKDATEN):
            continue
        for z in a["ziele"]:
            if z.get("abschnitt") != ECKDATEN:
                continue
            for k, v in (z.get("felder") or {}).items():
                if k.endswith("_unvollstaendig"):
                    continue
                aus[k] = {"wert": v, "aussage": a["schluessel"], "art": a["art"],
                          "unvollstaendig": bool(z["felder"].get(f"{k}_unvollstaendig"))}
    return aus


_DAUER = re.compile(r"(\d{1,2})\s*(monat|woche)", re.I)


def dauer_wochen(text):
    m = _DAUER.search(str(text or ""))
    if not m:
        return None
    n = int(m.group(1))
    return round(n * 4.345) if m.group(2).lower().startswith("monat") else n


def _datum_ch(iso):
    if re.match(r"^\d{4}-\d{2}-\d{2}$", str(iso or "")):
        j, m, t = iso.split("-")
        return f"{t}.{m}.{j}"
    return str(iso or "")


# ---- Projektion ---------------------------------------------------------------- #

def projiziere(aussagen, methode, meta=None, tarife=None, alte_answers=None, revision=None):
    """Die Dokumentdaten (answers) aus den Aussagen – vollständig neu berechnet.

    `aussagen`: alle Aussagen der Session (inkl. ersetzt/verworfen)
    `meta`:     {"auftraggeber", "projektleiter"} aus dem Projektkopf
    `alte_answers`: nur, um eine bereits formulierte Ausgangslage zu behalten,
                 solange ihre Aussagenbasis unverändert ist.
    """
    meta = meta or {}
    alte = alte_answers or {}
    answers = {}
    abschnitte = {s["id"]: s for s in (methode or {}).get("sections", [])}

    # -- Ausgangslage (Freitext) -------------------------------------------- #
    ausg = [a for a in aussagen if ins_dokument(a, "ausgangslage")
            and any(z.get("abschnitt") == "ausgangslage" for z in a["ziele"])]
    if "ausgangslage" in abschnitte and ausg:
        basis = basis_hash(ausg)
        formuliert = (alte.get("ausgangslage") or {}).get("_formulierung") or {}
        if formuliert.get("basis") == basis and formuliert.get("text"):
            text, veraltet = formuliert["text"], False
        else:
            # Deterministische Fassung: die Aussagen in ihrer Reihenfolge. Die
            # sprachliche Glättung folgt als eigener Schritt; bis dahin steht
            # im Dokument, was gesagt wurde – nicht etwas Erfundenes.
            text = " ".join(_mit_vermerk(a["inhalt"], a).rstrip(".") + "." for a in ausg)
            veraltet = True
        answers["ausgangslage"] = {
            "raw_text": "\n".join(a["inhalt"] for a in ausg),
            "extracted": {"text": text},
            "complete": True,
            "_aussagen": [a["schluessel"] for a in ausg],
            "_formulierung": formuliert if not veraltet else {"basis": basis, "text": ""},
            "_formulierung_veraltet": veraltet,
        }

    # -- Tabellen --------------------------------------------------------------- #
    for sid, s in abschnitte.items():
        if s.get("type") != "table":
            continue
        eigene = _zeilen_aus_aussagen(sid, aussagen)
        kap = vz.kapitel(sid) or {}

        if sid == "personalaufwand":
            basis = [{"rolle": r, "name": "", "aufwand": "", "_herkunft": "vorlage"}
                     for r in vz.basiszeilen(sid)]
            for b in basis:
                b["name"] = meta.get("auftraggeber" if b["rolle"] == "AG" else "projektleiter", "") or ""
            zeilen = _verschmelze(basis, eigene, "rolle",
                                  lambda e, b: _rollenschluessel(e) == b if _rollenschluessel(e) else _norm(e) == _norm(b))
        elif sid == "termine":
            basis = [{"ergebnis": r, "termin": "", "abnahme": "", "pruefmethode": "",
                      "_herkunft": "vorlage"} for r in vz.basiszeilen(sid)]
            zeilen = _nummeriere(_verschmelze(basis, eigene, "ergebnis", _passt_auf_basiszeile), "{nr:02d}")
        elif sid == "kosten":
            continue            # nach dem Personalaufwand berechnet, siehe unten
        else:
            vorbelegt = [dict(z, _herkunft="vorlage") for z in vz.vorbelegung(sid)]
            spalte = VERSCHMELZUNGSSPALTE.get(sid)
            zeilen = (_verschmelze(vorbelegt, eigene, spalte, lambda e, b: _norm(e) == _norm(b))
                      if spalte else vorbelegt + eigene)
            if sid == "risiken":
                for z in zeilen:
                    rz = vz.risikozahl(z.get("ew"), z.get("ag"))
                    z["risikozahl"] = str(rz) if rz is not None else ""
                _nummeriere(zeilen, "PR{nr:02d}")
            elif sid in ("ziele", "rahmenbedingungen"):
                _nummeriere(zeilen, "{nr:02d}")
            elif sid == "referenzierte_dokumente":
                _nummeriere(zeilen, "[{nr}]")
            elif sid == "projektorganisation" and zeilen:
                zeilen.append(_summenzeile(zeilen))

        if not eigene and sid in NA_SPALTE:
            na = _na_zeile(sid, aussagen)
            if na is not None:
                zeilen = [z for z in zeilen if z.get("_herkunft") != "vorlage" or sid in MIT_VORBELEGUNG] + [na]
                if sid == "rahmenbedingungen":
                    _nummeriere(zeilen, "{nr:02d}")
                elif sid == "referenzierte_dokumente":
                    _nummeriere(zeilen, "[{nr}]")
        if not zeilen and sid not in ("kosten",):
            continue
        answers[sid] = {
            "raw_text": "",
            "extracted": zeilen,
            "complete": bool(zeilen),
            "_aussagen": sorted({sch for z in zeilen for sch in z.get("_aussagen", [])}),
        }

    # -- Kosten aus dem Personalaufwand (keine erfundenen Tarife) ---------------- #
    if "kosten" in abschnitte:
        from app.domains.interview.service import InterviewService
        sachmittel = _zeilen_aus_aussagen("kosten", aussagen)
        zeilen = InterviewService._kosten_breakdown(sachmittel, answers, tarife or {})
        if not zeilen:
            zeilen = [{"phase": vz.basiszeilen("kosten")[0], "betrag": "", "_herkunft": "vorlage"}]
        answers["kosten"] = {"raw_text": "", "extracted": zeilen, "complete": True,
                             "_aussagen": sorted({sch for z in sachmittel
                                                  for sch in z.get("_aussagen", [])})}

    # -- Eckdaten -------------------------------------------------------------- #
    eck = eckdaten(aussagen)
    answers["_eckdaten"] = eck
    if "dauer_initialisierung" in eck:
        w = dauer_wochen(eck["dauer_initialisierung"]["wert"])
        if w:
            answers["_dauer_wochen"] = w
    if "ende_initialisierung" in eck and not eck["ende_initialisierung"]["unvollstaendig"]:
        answers["_enddatum"] = _datum_ch(eck["ende_initialisierung"]["wert"])

    answers["_nachweis"] = {"eintraege": nachweis(answers, aussagen, methode)}
    answers["_projektion"] = {"revision": revision, "aussagen": len(aussagen)}
    return answers


HERKUNFT_TEXT = {
    "benutzer": "Projektleitung (Interview)",
    "system": "HERMES PIA (Vorschlag, von der Projektleitung übernommen)",
    "rag": "Erfahrungswissen früherer Projekte (von der Projektleitung übernommen)",
    "altbestand": "Altbestand vor der Umstellung (Herkunft nicht erfasst)",
}


def nachweis(answers, aussagen, methode):
    """Herkunftsnachweis je Kapitel – deterministisch aus dem Zustand.

    Ersetzt für adaptive Sitzungen die modellformulierte Begründung beim
    Download (Auftrag: kein Modellaufruf beim Herunterladen). Was hier steht,
    ist aus den Aussagen ablesbar, nicht formuliert: wer etwas eingebracht
    hat, wie viele Aussagen das Kapitel tragen, welche davon Annahmen sind
    und was nur aus der Vorbelegung der Vorlage stammt.
    """
    nach_schluessel = {a["schluessel"]: a for a in aussagen}
    eintraege = []
    for s in (methode or {}).get("sections", []):
        ans = answers.get(s.get("id"))
        if not isinstance(ans, dict):
            continue
        tragend = [nach_schluessel[k] for k in ans.get("_aussagen", []) if k in nach_schluessel]
        zeilen = ans.get("extracted") if isinstance(ans.get("extracted"), list) else []
        nur_vorlage = bool(zeilen) and all(z.get("_herkunft") == "vorlage" for z in zeilen
                                           if isinstance(z, dict))
        if not tragend and not nur_vorlage:
            continue
        herkunft = []
        for a in tragend:
            t = HERKUNFT_TEXT.get(a["herkunft"], a["herkunft"])
            if t not in herkunft:
                herkunft.append(t)
        if any(isinstance(z, dict) and z.get("_herkunft") == "vorlage" for z in zeilen):
            herkunft.append("Vorbelegung der Vorlage")
        annahmen = sum(1 for a in tragend if a["art"] == "annahme")
        if tragend:
            begruendung = (f"{len(tragend)} von der Projektleitung bestätigte Aussage(n)"
                           + (f", davon {annahmen} Annahme(n), im Dokument als "
                              f"«{UNSICHER_VERMERK}» vermerkt" if annahmen else "") + ".")
        else:
            begruendung = "Nur die Vorbelegung der Vorlage; im Interview nicht ergänzt."
        eintraege.append({"abschnitt": s.get("title", s.get("id")),
                          "herkunft": " + ".join(herkunft), "begruendung": begruendung})
    return eintraege


def projektions_json(answers):
    return json.dumps(answers, ensure_ascii=False, indent=2)
