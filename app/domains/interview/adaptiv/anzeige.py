"""Lesemodell für «Für den PIA erkannt» – eine Darstellung gespeicherter
Aussagen und Schlussfolgerungen, keine Anzeige interner Modellgedanken.

Reine Funktion: aus Zustand, Dokumentdaten und Prüfergebnis wird die
Anzeige berechnet. Sie ändert NICHTS – ein Reload oder ein zweiter Tab
erzeugt keine neue Frage und keine versteckte Zustandsänderung (Auftrag
Abschnitt 12).

Status wird immer auch als TEXT ausgewiesen, nie nur über Farbe (AT16).
Keine Konfidenzprozente (AT15).
"""
from app.domains.interview.adaptiv.vertraege import ECKDATEN

# Thematische Gliederung der Anzeige – nach PIA-Bereichen, nicht nach
# Kapitelnummern, weil eine Aussage mehrere Kapitel beliefern kann.
BEREICHE = (
    ("ausgangslage", "Ausgangslage", ("ausgangslage",)),
    ("ziele", "Ziele der Initialisierung", ("ziele",)),
    ("rahmen", "Rahmen, Termine und Vorgaben",
     (ECKDATEN, "rahmenbedingungen", "termine", "referenzierte_dokumente",
      "mitgeltende_unterlagen", "vorgaben_methoden", "definitionen")),
    ("ressourcen", "Personal, Sachmittel und Kosten",
     ("personalaufwand", "sachmittel", "kosten", "projektorganisation")),
    ("kommunikation", "Kommunikation", ("kommunikation",)),
    ("risiken", "Risiken", ("risiken",)),
)

KAPITEL = {
    ECKDATEN: "Eckdaten", "ausgangslage": "1", "referenzierte_dokumente": "0.2",
    "mitgeltende_unterlagen": "0.3", "definitionen": "0.4", "vorgaben_methoden": "0.5",
    "ziele": "2.1", "rahmenbedingungen": "2.2", "personalaufwand": "3.1",
    "sachmittel": "3.2", "kosten": "3.3", "termine": "4.1",
    "projektorganisation": "5", "kommunikation": "6", "risiken": "7",
}

GEWICHT_TEXT = {"wesentlich": "wesentlich für die Beauftragung",
                "erforderlich": "erforderlich", "vertiefung": "Vertiefung"}

ZUSTAND_TEXT = {"erfuellt": "erfüllt", "offen": "offen", "unbekannt": "noch nicht bekannt",
                "zurueckgestellt": "zurückgestellt", "nicht_anwendbar": "begründet nicht anwendbar",
                "konflikt": "Widerspruch"}


def status_text(a):
    """Verständlicher Herkunfts-/Statushinweis einer Aussage."""
    if a["status"] == "ersetzt":
        return "ersetzt"
    if a["status"] == "verworfen":
        return "verworfen"
    if a["art"] == "unbekannt":
        return "zurückgestellt" if a.get("zurueckgestellt") else "Offene Frage – noch nicht bekannt"
    if a["herkunft"] == "altbestand":
        return ("aus früherer Erfassung – von Dir bestätigt" if a["bestaetigt"]
                else "aus früherer Erfassung – Herkunft nicht erfasst, noch zu bestätigen")
    if a["herkunft"] in ("system", "rag"):
        if a["art"] == "interpretation":
            return "Interpretation – von Dir bestätigt" if a["bestaetigt"] \
                else "Interpretation – noch zu bestätigen"
        quelle = "aus Vergleichsprojekten" if a["herkunft"] == "rag" else "von HERMES PIA"
        return f"Vorschlag {quelle} – übernommen" if a["bestaetigt"] \
            else f"Vorschlag {quelle} – noch nicht übernommen"
    if a["art"] == "annahme":
        return "von Dir genannt – unbestätigt"
    if a["art"] == "schaetzung":
        return "von Dir geschätzt"
    if a["art"] == "belegt":
        return "von Dir genannt – mit Beleg"
    return "von Dir genannt"


def _ziele_text(a):
    aus = []
    for z in a.get("ziele") or []:
        ab = z.get("abschnitt")
        kap = KAPITEL.get(ab, ab)
        aus.append({"abschnitt": ab, "kapitel": kap,
                    "nicht_anwendbar": bool(z.get("nicht_anwendbar"))})
    return aus


def _bereich(a):
    abschnitte = [z.get("abschnitt") for z in a.get("ziele") or []]
    for key, _titel, gruppe in BEREICHE:
        if any(ab in gruppe for ab in abschnitte):
            return key
    return "sonstiges"


def _eintrag(a, revision, nachrichten_nach_id):
    neu = a.get("revision_neu") == revision and revision > 0
    geaendert = (not neu and a.get("revision_geaendert") == revision and revision > 0)
    original = nachrichten_nach_id.get(a.get("nachricht_id"))
    hinweise = []
    if a.get("bezug") == "gesamtvorhaben":
        hinweise.append("betrifft das Gesamtvorhaben, nicht die Initialisierung")
    elif a.get("bezug") == "unklar":
        hinweise.append("Bezug unklar: Initialisierung oder Gesamtvorhaben?")
    if a.get("entscheid") == "idee":
        hinweise.append("Lösungsidee – nicht entschieden")
    elif a.get("entscheid") == "entscheid":
        hinweise.append("Entscheid")
    elif a.get("entscheid") == "unklar":
        hinweise.append("Idee oder Entscheid? – noch offen")
    for z in a.get("ziele") or []:
        for k, v in (z.get("felder") or {}).items():
            if k.endswith("_unvollstaendig") and v:
                hinweise.append("Angabe unvollständig (z.B. Jahr fehlt)")
    if a.get("beleg"):
        hinweise.append(f"Quelle genannt: {a['beleg']}")
    aktionen = []
    if a["status"] == "aktiv":
        if not a["bestaetigt"]:
            aktionen.append("bestaetigen")
        aktionen += ["berichtigen", "verwerfen"]
    return {
        "schluessel": a["schluessel"], "inhalt": a["inhalt"], "thema": a.get("thema", ""),
        "status_text": status_text(a), "art": a["art"], "herkunft": a["herkunft"],
        "bestaetigt": a["bestaetigt"], "ziele": _ziele_text(a), "hinweise": hinweise,
        "neu": neu, "geaendert": geaendert, "aktionen": aktionen,
        "original": (original or {}).get("text", "")[:600] if original else "",
        "ersetzt": a.get("ersetzt"),
    }


def anzeige(zustand, session, answers, kriterien, reife, rag_stand=None):
    """Das vollständige Lesemodell der Erkenntnisanzeige."""
    rev = zustand.revision
    nach_id = {n["id"]: n for n in zustand.nachrichten}

    gruppen = {key: {"key": key, "titel": titel, "eintraege": []} for key, titel, _ in BEREICHE}
    gruppen["sonstiges"] = {"key": "sonstiges", "titel": "Weitere Angaben", "eintraege": []}
    offen = []
    for a in zustand.aktive:
        e = _eintrag(a, rev, nach_id)
        # Offene Fragen, Interpretationen und Vorschläge stehen OBEN und nur
        # dort – nicht zwischen bestätigten Angaben versteckt (Auftrag 8.2) und
        # nicht doppelt. Nach der Bestätigung wandern sie in ihren Bereich.
        if a["art"] == "unbekannt" or not a["bestaetigt"]:
            offen.append(e)
            continue
        gruppen[_bereich(a)]["eintraege"].append(e)

    konflikte = []
    for kf in zustand.offene_konflikte:
        konflikte.append({"id": kf["id"], "beschreibung": kf["beschreibung"],
                          "aussagen": kf["aussagen"], "status_text": "Widerspruch – offen",
                          "neu": kf.get("revision_erkannt") == rev and rev > 0})

    themen = []
    for t in zustand.themen:
        if t["status"] in ("verworfen", "erledigt") or t["uebertragbarkeit"] == "nicht_uebernehmen":
            continue
        themen.append({
            "id": t["id"], "thema": t["thema"], "frage_ansatz": t["frage_ansatz"],
            "status_text": ("Vorschlag aus Vergleichsprojekten – nicht als Projektbedarf bestätigt"
                            if t["status"] in ("kandidat", "gefragt")
                            else "von Dir als relevant bestätigt"),
            "uebertragbarkeit": t["uebertragbarkeit"],
            "begruendung": t["begruendung"], "n_projekte": t["n_projekte"],
            "ziele": [{"abschnitt": z, "kapitel": KAPITEL.get(z, z)} for z in t["pia_ziele"]],
            "quellen_anzahl": len(t["quellen"]), "neu": t.get("revision") == rev and rev > 0,
        })

    blocker = [{"id": e["id"], "beschreibung": e["beschreibung"],
                "zustand_text": ZUSTAND_TEXT.get(e["zustand"], e["zustand"]),
                "gewicht_text": GEWICHT_TEXT.get(e["gewicht"], e["gewicht"]),
                "details": e["details"], "abschnitt": e["abschnitt"],
                "kapitel": KAPITEL.get(e["abschnitt"], e["abschnitt"])}
               for e in kriterien if e["zustand"] not in ("erfuellt", "nicht_anwendbar")]

    neu = sum(1 for g in gruppen.values() for e in g["eintraege"] if e["neu"]) + \
        sum(1 for e in offen if e["neu"] and e["art"] == "unbekannt")
    geaendert = sum(1 for g in gruppen.values() for e in g["eintraege"] if e["geaendert"])
    return {
        "revision": rev,
        "gruppen": [g for g in gruppen.values() if g["eintraege"]],
        "offen": offen, "konflikte": konflikte, "themen": themen,
        "blocker": blocker, "reife": reife,
        "zaehler": {"neu": neu, "geaendert": geaendert,
                    "offen": len(offen) + len(konflikte),
                    "aussagen": len(zustand.aktive)},
        "rag": rag_stand or {"verfuegbar": False, "grund": "nicht abgefragt"},
    }
