"""Bestandsaufnahme des RAG-Korpus – ausschliesslich lesend.

Öffnet die SQLite-Datenbank SCHREIBGESCHÜTZT (`mode=ro`) und ohne die
Anwendung zu starten: keine Migration, keine Änderung, kein Netzaufruf. So
lässt sie sich auf jeder Stufe gefahrlos ausführen – auch vor einem Deploy.

Ergebnis je Bereich (geteilter Korpus / je Organisation): Dokumente, Chunks,
Embedding-Modelle mit Vektorlänge, Korpusstand (Korpusversion, Zeitraum),
Methodenversion, Freigabe zur externen Verarbeitung – und die Kompatibilität
mit dem vorgesehenen Modell.

«Kompatibel» heisst hier: gleicher Modellname und eine einheitliche
Vektorlänge. Ob die Vektorlänge zum Modell passt, zeigt erst eine echte
Anfrage; die Suche überspringt abweichende Vektoren und zählt sie
(`RagService.search_mit_bericht`). Das wird nicht vorweggenommen.
"""
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path


def pfad_aus_url(database_url):
    """'sqlite:///…' -> Dateipfad, sonst None (nur SQLite wird unterstützt)."""
    url = str(database_url or "")
    if not url.startswith("sqlite:///"):
        return None
    return url[len("sqlite:///"):]


def bestand(pfad, modell=None):
    """Bestand des Korpus in der Datenbank `pfad` (schreibgeschützt gelesen)."""
    p = Path(pfad)
    if not p.exists():
        return {"datenbank": str(p), "gefunden": False,
                "grund": "Datenbankdatei nicht gefunden"}
    con = sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True)
    try:
        tabellen = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "corpus_chunks" not in tabellen:
            return {"datenbank": str(p), "gefunden": True, "korpus_tabelle": False,
                    "grund": "Tabelle corpus_chunks fehlt – es gibt keinen Korpus"}
        spalten = {r[1] for r in con.execute("PRAGMA table_info(corpus_chunks)")}

        def sp(name):
            return name if name in spalten else "NULL"
        sql = (f"SELECT org_id, projekt, ergebnistyp, model, embedding_json, "
               f"{sp('dokument_hash')}, {sp('korpus_version')}, {sp('methodenversion')}, "
               f"{sp('extern_freigegeben')}, {sp('created_at')} FROM corpus_chunks")
        bereiche = defaultdict(lambda: {"chunks": 0, "dokumente": set(), "ohne_vektor": 0,
                                        "modelle": Counter(), "laengen": defaultdict(Counter),
                                        "korpus_versionen": Counter(),
                                        "methodenversionen": Counter(),
                                        "extern_freigegeben": 0, "ergebnistypen": Counter(),
                                        "erstellt": []})
        for (org, projekt, typ, mod, emb, dhash, kv, mv, frei, erstellt) in con.execute(sql):
            b = bereiche["geteilt" if org is None else f"org {org}"]
            b["chunks"] += 1
            b["dokumente"].add(dhash or f"projekt:{projekt}")
            b["ergebnistypen"][typ or "?"] += 1
            b["modelle"][mod or "(nicht erfasst)"] += 1
            if emb:
                try:
                    b["laengen"][mod or "(nicht erfasst)"][len(json.loads(emb))] += 1
                except ValueError:
                    b["ohne_vektor"] += 1
            else:
                b["ohne_vektor"] += 1
            b["korpus_versionen"][kv or "(nicht erfasst)"] += 1
            b["methodenversionen"][mv or "(nicht erfasst)"] += 1
            b["extern_freigegeben"] += 1 if frei else 0
            if erstellt:
                b["erstellt"].append(str(erstellt))
    finally:
        con.close()

    aus = {"datenbank": str(p), "gefunden": True, "korpus_tabelle": True,
           "vorgesehenes_modell": modell,
           "neue_spalten_vorhanden": {s: s in spalten for s in
                                      ("dokument_hash", "korpus_version", "methodenversion",
                                       "extern_freigegeben")},
           "bereiche": {}}
    for name, b in sorted(bereiche.items()):
        laengen = {m: dict(c) for m, c in b["laengen"].items()}
        kompatibel = None
        if modell:
            passend = b["modelle"].get(modell, 0)
            einheitlich = len(laengen.get(modell, {})) == 1
            kompatibel = {"chunks_mit_vorgesehenem_modell": passend,
                          "einheitliche_vektorlaenge": einheitlich,
                          "andere_modelle": {m: n for m, n in b["modelle"].items() if m != modell}}
        aus["bereiche"][name] = {
            "dokumente": len(b["dokumente"]), "chunks": b["chunks"],
            "ohne_vektor": b["ohne_vektor"], "ergebnistypen": dict(b["ergebnistypen"]),
            "modelle": dict(b["modelle"]), "vektorlaengen": laengen,
            "korpus_versionen": dict(b["korpus_versionen"]),
            "methodenversionen": dict(b["methodenversionen"]),
            "extern_freigegeben": b["extern_freigegeben"],
            "erstellt_von_bis": [min(b["erstellt"]), max(b["erstellt"])] if b["erstellt"] else None,
            "kompatibilitaet": kompatibel,
        }
    if not aus["bereiche"]:
        aus["grund"] = "Tabelle vorhanden, aber leer – keine Chunks"
    return aus
