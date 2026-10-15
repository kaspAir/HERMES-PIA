"""Echter Nachweis auf dev: Interview mit echtem Sprachmodell, echten Embeddings
und synthetischen Inhalten – mit harter Kostengrenze.

    python tools/dev_echtlauf.py --ziel <ordner> --ausfuehren \\
        --preise in=<USD/Mio>,out=<USD/Mio>,emb=<USD/Mio> [--budget-usd 10]

Läuft AUF DER STUFE (gleiche Konfiguration wie die Anwendung, Schlüssel nur
serverseitig). Ohne --ausfuehren: nur Prüfung der Voraussetzungen, kein Aufruf.

Zwei Fälle, beide synthetisch (erfundene Organisation, erfundene Personen):

  A  vollständig  – offener Einstieg, Fragen des Modells, Antworten aus einem
                    festen Antwortbuch je Kapitel, RAG-Themen aus dem
                    synthetischen Korpus, Vorschläge übernehmen, Abschluss.
  B  Korrektur/Widerspruch – eine ausdrückliche Korrektur und eine
                    widersprüchliche Angabe ohne Korrekturhinweis; danach die
                    Auflösung.

Was echt ist: jede Frage formuliert das Modell, jede Aussage leitet das Modell
aus dem Text ab, jede RAG-Suche ruft den Embedding-Dienst. Was simuliert ist:
der Projektleiter (Antwortbuch). Das Ergebnis ist ein Entwicklungsnachweis,
keine fachliche Abnahme.

Kosten: Die Tokens meldet der Anbieter. Die Preise je Million Tokens gibt der
Betreiber an (--preise), weil sie sich ändern und hier nicht geraten werden.
Vor JEDEM weiteren Schritt wird geprüft, ob der bisherige Verbrauch plus eine
vorsichtige Reserve das Budget überschreiten würde – dann endet der Lauf
geordnet, und das wird ausgewiesen.

Ausgabe im Zielordner: je Fall die Word-Datei, ein JSON-Protokoll (Gespräch,
Aussagen, Themen mit Quellen, Kriterien, Verbrauch) und ein Gesamtbericht.
Die Sessions bleiben in der Datenbank der Stufe und sind in der Oberfläche
ansehbar (Organisation «Synthetik-Nachweis»).
"""
import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ORG = "Synthetik-Nachweis (erfunden)"

# ---- Antwortbuch des simulierten Projektleiters --------------------------------- #

FALL_A = {
    "id": "A", "titel": "Ablösung der Registeranwendung (Beispielamt, erfunden)",
    "kopf": {"projektname": "Synthetik A – Ablösung Registeranwendung",
             "auftraggeber": "Robin Beispiel", "projektleiter": "Kim Muster"},
    "einstieg": ("Das Beispielamt betreibt seit vierzehn Jahren eine Registeranwendung. Der "
                 "Hersteller hat angekündigt, die Wartung Ende 2028 einzustellen – das ist noch "
                 "nicht schriftlich bestätigt. Daten werden doppelt erfasst, weil die Schnittstelle "
                 "zum Gebäuderegister fehlt. Die Initialisierung soll am 1. Februar 2027 beginnen "
                 "und am 30. Juni 2027 abgeschlossen sein."),
    "antworten": {
        "ausgangslage": "Betroffen sind rund 40 Mitarbeitende in zwei Abteilungen; die Bürgerinnen "
                        "und Bürger merken die Doppelerfassung an langen Bearbeitungszeiten.",
        "eckdaten": "Start ist der 1. Februar 2027, Ende der 30. Juni 2027.",
        "ziele": "Ziel der Initialisierung ist eine Studie mit mindestens zwei Lösungsvarianten "
                 "und einer Empfehlung, Priorität Muss, gemessen daran, dass der Auftraggeber "
                 "die Studie abnimmt. Zweites Ziel: der Datenbestand ist auf Qualität und Umfang "
                 "untersucht, Priorität Hoch, Messgrösse ist ein Bericht zur Datenqualität.",
        "rahmenbedingungen": "Vorgabe der Stammorganisation: die Lösung muss im kantonalen "
                             "Rechenzentrum betrieben werden können.",
        "personalaufwand": "Ich rechne für mich als Projektleiter mit 45 Personentagen, der "
                           "Auftraggeber mit 8 Tagen, dazu eine Fachperson aus der Abteilung mit "
                           "20 Tagen.",
        "sachmittel": "Besondere Sachmittel brauchen wir nicht, Arbeitsplätze sind vorhanden.",
        "kosten": "Die Kostensätze sind hinterlegt; andere Kosten fallen nicht an.",
        "termine": "Ja, übernimm den vorgeschlagenen Terminplan so.",
        "projektorganisation": "Ja, die gleichmässige Verteilung passt.",
        "kommunikation": "Die Mitarbeitenden informiere ich monatlich in der Teamsitzung, den "
                         "Auftraggeber alle zwei Wochen in einer kurzen Besprechung.",
        "risiken": "Risiko: die Fachleute sind im Frühling durch die Jahresabschlüsse stark "
                   "belastet. Wahrscheinlichkeit mittel, Auswirkung hoch. Massnahme: Workshops "
                   "früh fix planen. Verantwortlich ist die Projektleitung, Termin Ende Februar 2027.",
    },
}

FALL_B = {
    "id": "B", "titel": "Korrektur und Widerspruch (Beispielstadt, erfunden)",
    "kopf": {"projektname": "Synthetik B – Korrektur und Widerspruch",
             "auftraggeber": "Alex Beispiel", "projektleiter": "Sam Muster"},
    "schritte": [
        "Die Beispielstadt will ihre drei Schalterdienste zusammenlegen. Die Initialisierung "
        "beginnt am 1. März 2027 und dauert bis Ende August 2027. Der Auftraggeber rechnet mit "
        "10 Personentagen.",
        "Korrektur: die Initialisierung beginnt erst am 1. April 2027, nicht im März.",
        "Der Auftraggeber kann für die ganze Initialisierung höchstens 4 Tage einsetzen.",
        "Es gilt: der Auftraggeber setzt 4 Personentage ein, die 10 Tage waren eine erste Schätzung.",
    ],
}


def _antwort(fall, frage, benutzt):
    """Antwort des simulierten Projektleiters auf die gestellte Frage."""
    aktion = (frage or {}).get("aktion")
    abschnitt = (frage or {}).get("abschnitt") or ""
    if aktion == "abschluss":
        return None
    if aktion == "rueckspiegeln":
        return "Ja, das stimmt so."
    if aktion == "vorschlag":
        return "Ja, mach bitte einen Vorschlag."
    if aktion == "widerspruch":
        return "Es gilt die zuletzt genannte Angabe."
    text = fall["antworten"].get(abschnitt)
    if text and abschnitt not in benutzt:
        benutzt.add(abschnitt)
        return text
    return "Dazu weiss ich im Moment nichts Genaueres – bitte als offenen Punkt führen."


# ---- Kosten -------------------------------------------------------------------- #

class Kasse:
    def __init__(self, preise, budget, embedder):
        self.preise, self.budget, self.embedder = preise, budget, embedder

    def stand(self):
        from app.domains.llm.client import VERBRAUCH
        emb = getattr(self.embedder, "tokens", 0) if self.embedder else 0
        usd = (VERBRAUCH["input_tokens"] * self.preise["in"]
               + VERBRAUCH["output_tokens"] * self.preise["out"]
               + emb * self.preise["emb"]) / 1_000_000
        return {"llm_aufrufe": VERBRAUCH["aufrufe"], "input_tokens": VERBRAUCH["input_tokens"],
                "output_tokens": VERBRAUCH["output_tokens"], "embedding_tokens": emb,
                "usd_geschaetzt": round(usd, 4)}

    def reicht_fuer_schritt(self):
        """Reserve für den nächsten Schritt: 20'000 Eingabe- + 4'000 Ausgabetokens."""
        reserve = (20_000 * self.preise["in"] + 4_000 * self.preise["out"]) / 1_000_000
        return self.stand()["usd_geschaetzt"] + reserve <= self.budget


def _bis_zur_frage(d, sid, tarife, kasse, protokoll):
    ansicht = d.ansicht(sid)
    while ansicht["ausstehend"]:
        if not kasse.reicht_fuer_schritt():
            protokoll["abbruch"] = "Budgetgrenze erreicht"
            return ansicht
        ansicht = d.weiter(sid, tarife=tarife)
    return ansicht


def _protokoll_fall(app, d, sid, ansicht):
    z = d.zustand.lade(sid)
    rag = app.rag_service
    themen = []
    for t in z.themen:
        quellen = []
        for q in t["quellen"]:
            c = rag.chunk(q.get("chunk_id"), org_id=None) if q.get("chunk_id") else None
            quellen.append({"chunk_id": q.get("chunk_id"), "abschnitt": q.get("abschnitt"),
                            "auszug": q.get("auszug"), "korpus_version": q.get("korpus_version"),
                            "projekt": (c or {}).get("projekt")})
        themen.append({"thema": t["thema"], "uebertragbarkeit": t["uebertragbarkeit"],
                       "regel": t["regel_id"], "status": t["status"], "quellen": quellen})
    return {
        "gespraech": [{"rolle": m["rolle"], "art": m["art"], "aktion": m["aktion"],
                       "text": m["text"], "status": m["status"]} for m in z.nachrichten],
        "aussagen": [{k: a[k] for k in ("schluessel", "inhalt", "art", "herkunft", "bestaetigt",
                                       "status", "bezug", "ziele")} for a in z.aussagen],
        "konflikte": z.konflikte, "themen": themen,
        "kriterien": [{k: e[k] for k in ("id", "zustand", "details")} for e in ansicht["kriterien"]],
        "reife": ansicht["erkannt"]["reife"], "pia_status": ansicht["pia_status"],
        "rag_stand": json.loads(app.interview_service.get_session(sid).rag_stand_json or "{}"),
    }


def _docx(app, sid, ziel, name, projektleiter):
    from app.domains.generation import pia as pia_dokument
    app.interview_service.record_version_bump(sid, "minor", projektleiter,
                                              "Entwurf aus dem Interview (Nachweis dev)")
    s = app.interview_service.get_session(sid)
    buf, _ = pia_dokument.erzeuge(s, app.interview_service, app.generation_service,
                                  app.projekt_service)
    pfad = Path(ziel) / name
    pfad.write_bytes(buf.getvalue())
    return pfad.name


def lauf_a(app, d, org, ziel, kasse, max_runden=16):
    k = FALL_A["kopf"]
    s = app.interview_service.start_session(method_id="hermes_pia", project_name=k["projektname"],
                                            org_id=org, auftraggeber=k["auftraggeber"],
                                            created_by=k["projektleiter"])
    tarife = app.projekt_service.effective_tarife(org_id=org)
    protokoll = {"fall": "A", "titel": FALL_A["titel"], "session_id": s.id}
    d.starte(s.id)
    text, benutzt = FALL_A["einstieg"], set()
    for runde in range(max_runden):
        if not kasse.reicht_fuer_schritt():
            protokoll["abbruch"] = "Budgetgrenze erreicht"
            break
        d.beitrag(s.id, text, anfrage_id=f"A-{runde}", tarife=tarife)
        ansicht = _bis_zur_frage(d, s.id, tarife, kasse, protokoll)
        if protokoll.get("abbruch"):
            break
        text = _antwort(FALL_A, ansicht["frage"], benutzt)
        if text is None:
            break
    # Wie in der Oberfläche: «Alle Vorschläge übernehmen».
    ansicht = d.ansicht(s.id)
    offen = [e["schluessel"] for e in ansicht["erkannt"]["offen"]
             if e["herkunft"] == "system" and not e["bestaetigt"]]
    if offen and kasse.reicht_fuer_schritt():
        d.sammelbestaetigung(s.id, offen, tarife=tarife)
        ansicht = _bis_zur_frage(d, s.id, tarife, kasse, protokoll)
    bericht = d.abschluss(s.id, "pruefen")["abschluss"]
    if bericht["bereit"]:
        ansicht = d.abschluss(s.id, "fertigstellen")
    protokoll.update(_protokoll_fall(app, d, s.id, d.ansicht(s.id)))
    protokoll["abschlussbericht"] = bericht
    protokoll["docx"] = _docx(app, s.id, ziel, "Synthetik-A_vollstaendig.docx", k["projektleiter"])
    return protokoll


def lauf_b(app, d, org, ziel, kasse):
    k = FALL_B["kopf"]
    s = app.interview_service.start_session(method_id="hermes_pia", project_name=k["projektname"],
                                            org_id=org, auftraggeber=k["auftraggeber"],
                                            created_by=k["projektleiter"])
    tarife = app.projekt_service.effective_tarife(org_id=org)
    protokoll = {"fall": "B", "titel": FALL_B["titel"], "session_id": s.id, "zwischenstaende": []}
    d.starte(s.id)
    for i, text in enumerate(FALL_B["schritte"]):
        if not kasse.reicht_fuer_schritt():
            protokoll["abbruch"] = "Budgetgrenze erreicht"
            break
        d.beitrag(s.id, text, anfrage_id=f"B-{i}", tarife=tarife)
        ansicht = _bis_zur_frage(d, s.id, tarife, kasse, protokoll)
        z = d.zustand.lade(s.id, False)
        protokoll["zwischenstaende"].append({
            "beitrag": text, "frage": (ansicht["frage"] or {}).get("frage"),
            "aktion": (ansicht["frage"] or {}).get("aktion"),
            "offene_konflikte": [kf["beschreibung"] for kf in z.konflikte if kf["status"] == "offen"],
            "ersetzt": [a["inhalt"] for a in z.aussagen if a["status"] == "ersetzt"],
            "eckdaten": json.loads(app.interview_service.get_session(s.id).answers_json or "{}"
                                   ).get("_eckdaten"),
        })
        if protokoll.get("abbruch"):
            break
    protokoll.update(_protokoll_fall(app, d, s.id, d.ansicht(s.id)))
    protokoll["docx"] = _docx(app, s.id, ziel, "Synthetik-B_korrektur_widerspruch.docx",
                              k["projektleiter"])
    return protokoll


def voraussetzungen(app):
    w = app.datenwege
    probleme = []
    if w["llm"]["modus"] == "aus":
        probleme.append(f"Kein Weg zum Sprachmodell ({w['llm'].get('grund')})")
    if w["embeddings"]["modus"] == "aus":
        probleme.append(f"Kein Embedding-Weg ({w['embeddings'].get('grund')})")
    rag = app.rag_service
    if rag is not None and rag.available:
        with app.app_context():
            from app.domains.corpus.models import CorpusChunk
            from app.shared.database import SessionLocal
            q = SessionLocal().query(CorpusChunk)
            if rag.nur_extern_freigegeben:
                q = q.filter(CorpusChunk.extern_freigegeben.is_(True))
            n = q.count()
        if not n:
            probleme.append("Kein durchsuchbarer Korpus (im Direktmodus: keine extern "
                            "freigegebenen Chunks – zuerst scripts/ingest_synthetischer_korpus.py)")
    return {"datenwege": {k: w[k]["modus"] for k in ("llm", "embeddings")},
            "probleme": probleme}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--ziel", required=True)
    p.add_argument("--ausfuehren", action="store_true")
    p.add_argument("--preise", help="in=<USD/Mio>,out=<USD/Mio>,emb=<USD/Mio>")
    p.add_argument("--budget-usd", type=float, default=10.0)
    a = p.parse_args(argv)

    from app.factory import create_app
    app = create_app()
    v = voraussetzungen(app)
    print(json.dumps(v, ensure_ascii=False, indent=2))
    if v["probleme"] or not a.ausfuehren:
        print("Kein Lauf." if v["probleme"] else "Voraussetzungen erfüllt. Starten mit --ausfuehren.")
        return 2 if v["probleme"] else 0
    if not a.preise:
        print("Abbruch: --preise fehlt (USD je Million Tokens; nicht geraten).")
        return 2
    preise = {k: float(x) for k, x in (t.split("=") for t in a.preise.split(","))}
    ziel = Path(a.ziel)
    ziel.mkdir(parents=True, exist_ok=True)
    kasse = Kasse(preise, a.budget_usd, app.rag_service.embedder)
    with app.app_context():
        org = app.auth_service.create_org(ORG).id
        app.projekt_service.set_kostensatz(1000, 1500, einheit="tag", org_id=org)
        d = app.adaptiv_service
        gesamt = {"gestartet": datetime.now().isoformat(timespec="seconds"),
                  "budget_usd": a.budget_usd, "preise_usd_pro_mio": preise,
                  "datenwege": v["datenwege"], "faelle": []}
        for fall in (lauf_a, lauf_b):
            if not kasse.reicht_fuer_schritt():
                gesamt["faelle"].append({"abbruch": "Budgetgrenze vor Fallbeginn"})
                break
            prot = fall(app, d, org, ziel, kasse)
            (ziel / f"Synthetik-{prot['fall']}_protokoll.json").write_text(
                json.dumps(prot, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            gesamt["faelle"].append({k: prot.get(k) for k in
                                     ("fall", "session_id", "reife", "pia_status", "docx", "abbruch")})
        gesamt["verbrauch"] = kasse.stand()
        gesamt["beendet"] = datetime.now().isoformat(timespec="seconds")
    (ziel / "bericht.json").write_text(json.dumps(gesamt, ensure_ascii=False, indent=2),
                                       encoding="utf-8")
    print(json.dumps(gesamt, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
