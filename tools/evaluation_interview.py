"""Kontrollierte Verbesserung des adaptiven Interviews – ausdrücklich auszulösen.

Drei Befehle, alle offline und ohne Produktivänderung:

    python tools/evaluation_interview.py freigeben --db <url> --ids 3,7,12
        Rückmeldungen nach Durchsicht für die Auswertung freigeben. Ohne
        Freigabe fliesst keine Rückmeldung in eine Auswertung (Auftrag 13:
        reale Inhalte werden nicht automatisch Evaluationsdaten).

    python tools/evaluation_interview.py schwaechen --db <url> --aus <ordner>
        Freigegebene Rückmeldungen nach Art, Bezug und Version bündeln und
        daraus begründete KANDIDATEN-Gerüste ablegen (Status «vorgeschlagen»).
        Eine einzelne Rückmeldung ist keine Regel – Kandidaten entstehen erst
        ab einer Mindestzahl gleichartiger Rückmeldungen.

    python tools/evaluation_interview.py vergleich [--kandidat <ordner>] --aus <ordner>
        Baseline (die Dateien im Repository) gegen einen Kandidaten (Ordner mit
        Ersatzdateien: abschlussprofil.yaml, rag_uebertragung.yaml,
        prompt_texte/*.md) auf synthetischen Fällen vergleichen – getrennt nach
        Entwicklungs- und Prüffällen, je mit und ohne RAG.

Was ein Vergleich NICHT ist: ein Nachweis echter Modellqualität. Die Fälle
laufen mit dem Drehbuch-Modell (tools/synthetische_faelle.py); verglichen
werden die deterministischen Teile (Profil, Planer, Übertragungsregeln,
Projektion, Export). Eine Bewertung mit einem echten Modell (--live) ist
kostenpflichtig und hier bewusst nicht eingebaut – sie braucht einen
autorisierten Kostenrahmen.

Ein Kandidat wird NIE automatisch übernommen. Übernahme heisst: Dateien mit
neuer Versionsnummer ins Repository, Review, Tests, regulärer Deploy-Weg. Der
Rückweg ist der vorherige Commit.
"""
import argparse
import contextlib
import json
import secrets
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

WURZEL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WURZEL))

# Getrennte Fallmengen: Kandidaten werden an den Entwicklungsfällen
# begründet und an den Prüffällen gemessen, die sie nicht kennen.
ENTWICKLUNG = ["F-01"]
PRUEFUNG = ["F-02"]

# Ab so vielen gleichartigen Rückmeldungen entsteht ein Kandidat.
MINDESTZAHL = 3

# Kennzahlen, die sich NIE verschlechtern dürfen – sonst ist ein Kandidat
# abgelehnt, egal was er sonst verbessert.
SCHUTZ = ("unbestaetigt_im_dokument", "nicht_uebernehmen_gefragt", "muss_befunde_export")


# ---- Freigabe ------------------------------------------------------------------ #

def _app(db_url):
    from app.config import Config
    from app.factory import create_app

    class Cfg(Config):
        DATABASE_URL = db_url
        SECRET_KEY = secrets.token_hex(16)
    return create_app(Cfg)


def freigeben(db_url, ids, app=None):
    from app.domains.interview.adaptiv.models import PiaRueckmeldung
    from app.shared.database import SessionLocal
    app or _app(db_url)
    db = SessionLocal()
    n = 0
    for r in db.query(PiaRueckmeldung).filter(PiaRueckmeldung.id.in_(ids)):
        r.freigegeben = True
        n += 1
    db.commit()
    return n


# ---- Schwächen und Kandidaten ---------------------------------------------------- #

def schwaechen(db_url, aus, app=None):
    """Bündelt freigegebene Rückmeldungen und legt Kandidaten-Gerüste ab."""
    from app.domains.interview.adaptiv.models import PiaRueckmeldung
    from app.shared.database import SessionLocal
    app or _app(db_url)
    db = SessionLocal()
    rm = db.query(PiaRueckmeldung).filter(PiaRueckmeldung.freigegeben.is_(True)).all()
    gruppen = defaultdict(list)
    for r in rm:
        versionen = json.loads(r.versionen_json or "{}")
        kontext = json.loads(r.kontext_json or "{}")
        bezug = r.bezug or ""
        # Fragen werden über ihr Kriterium gebündelt, nicht über die Session.
        if r.art in ("frage_unklar", "schon_beantwortet") and bezug.startswith("K-"):
            schluessel = (r.art, bezug)
        elif r.art == "rag_unpassend":
            schluessel = (r.art, kontext.get("thema", bezug))
        else:
            schluessel = (r.art, "")
        gruppen[schluessel].append({"id": r.id, "versionen": versionen, "kontext": kontext})
    ziel = Path(aus)
    ziel.mkdir(parents=True, exist_ok=True)
    bericht = {"erstellt": datetime.now().isoformat(timespec="seconds"),
               "rueckmeldungen_freigegeben": len(rm),
               "gruppen": [], "kandidaten": []}
    for (art, bezug), eintraege in sorted(gruppen.items(), key=lambda x: -len(x[1])):
        versionen = Counter(json.dumps(e["versionen"], sort_keys=True) for e in eintraege)
        bericht["gruppen"].append({"art": art, "bezug": bezug, "anzahl": len(eintraege),
                                   "versionen": [json.loads(v) for v, _ in versionen.most_common(3)]})
        if len(eintraege) < MINDESTZAHL:
            continue
        kid = f"K-{datetime.now():%Y%m%d}-{len(bericht['kandidaten']) + 1:02d}"
        kandidat = {
            "id": kid, "status": "vorgeschlagen",
            "art": art, "betrifft": bezug or None,
            "begruendung": f"{len(eintraege)} freigegebene Rückmeldungen «{art}»"
                           + (f" zu {bezug}" if bezug else ""),
            "rueckmeldungen": [e["id"] for e in eintraege],
            "vorschlag": _vorschlagstext(art, bezug),
            "naechster_schritt": ("Ersatzdatei(en) in diesen Ordner legen und mit "
                                  "«vergleich --kandidat» gegen die Baseline prüfen."),
        }
        (ziel / kid).mkdir(exist_ok=True)
        (ziel / kid / "kandidat.json").write_text(json.dumps(kandidat, ensure_ascii=False, indent=2),
                                                  encoding="utf-8")
        bericht["kandidaten"].append(kandidat)
    (ziel / "schwaechen.json").write_text(json.dumps(bericht, ensure_ascii=False, indent=2),
                                          encoding="utf-8")
    return bericht


def _vorschlagstext(art, bezug):
    return {
        "frage_unklar": f"Vorlagenfrage von {bezug} verständlicher formulieren "
                        f"(abschlussprofil.yaml) oder den Frage-Prompt schärfen.",
        "schon_beantwortet": f"Prüfung von {bezug} erkennt vorhandene Angaben nicht – "
                             f"Prüfart oder Zuordnung im Aussagen-Prompt prüfen.",
        "rag_unpassend": f"Übertragungsregel für «{bezug}» prüfen (rag_uebertragung.yaml).",
        "falsch_verstanden": "Aussagen-Prompt: Beispiele für die verwechselte Aussageart ergänzen.",
        "falsch_zugeordnet": "Aussagen-Prompt: Zuordnung zu Kapiteln schärfen.",
        "vorschlag_verworfen": "Berechnete Vorschläge (vorschlaege.py) und ihre Grundlage prüfen.",
        "korrektur": "Häufige Korrekturen: Interpretation zurückhaltender, Rückspiegeln früher.",
    }.get(art, "Manuell prüfen.")


# ---- Vergleich Baseline / Kandidat ----------------------------------------------- #

@contextlib.contextmanager
def ueberlagert(kandidat):
    """Ersatzdateien des Kandidaten für die Dauer des Laufs wirksam machen."""
    from app.domains.interview.adaptiv import prompts, rag_themen, vollstaendigkeit
    alt = (vollstaendigkeit._PROFIL, rag_themen._REGELN, prompts._ORDNER)
    try:
        if kandidat:
            k = Path(kandidat)
            if (k / "abschlussprofil.yaml").exists():
                vollstaendigkeit._PROFIL = k / "abschlussprofil.yaml"
            if (k / "rag_uebertragung.yaml").exists():
                rag_themen._REGELN = k / "rag_uebertragung.yaml"
            if (k / "prompt_texte").is_dir():
                prompts._ORDNER = k / "prompt_texte"
        _caches_leeren()
        yield
    finally:
        vollstaendigkeit._PROFIL, rag_themen._REGELN, prompts._ORDNER = alt
        _caches_leeren()


def _caches_leeren():
    from app.domains.interview.adaptiv import prompts, rag_themen, vollstaendigkeit
    for fn in (vollstaendigkeit.profil, rag_themen.regeln):
        fn.cache_clear()
    for name in dir(prompts):
        f = getattr(prompts, name)
        if hasattr(f, "cache_clear"):
            f.cache_clear()


def kennzahlen(app, fall_id, mit_rag=True):
    """Ein Fall, ein Lauf: Kennzahlen aus Zustand, Projektion und Export."""
    import io

    from docx import Document

    from app.domains.generation import pia as pia_dokument
    from app.domains.interview.adaptiv.models import PiaNachricht
    from app.domains.qualitaet.service import pruefe_session
    from app.shared.database import SessionLocal
    from tools.fall_durchspielen import spiele_in

    org, sid, ansicht, d = spiele_in(app, fall_id, org_name=f"Eval {fall_id} {secrets.token_hex(3)}",
                                     mit_rag=mit_rag)
    z = d.zustand.lade(sid)
    fragen = (SessionLocal().query(PiaNachricht)
              .filter(PiaNachricht.session_id == sid, PiaNachricht.art == "frage")
              .order_by(PiaNachricht.id).all())
    ziele = [json.loads(f.bezug_json or "{}").get("ziel") for f in fragen]
    wiederholt = sum(1 for a, b in zip(ziele, ziele[1:]) if a and a == b)
    s = app.interview_service.get_session(sid)
    answers = json.loads(s.answers_json or "{}")
    im_dokument = {k for ab in answers.values() if isinstance(ab, dict)
                   for k in ab.get("_aussagen", [])}
    nach_schluessel = {a["schluessel"]: a for a in z.aussagen}
    unbestaetigt = sum(1 for k in im_dokument if k in nach_schluessel
                       and not nach_schluessel[k]["bestaetigt"]
                       and nach_schluessel[k]["herkunft"] != "altbestand")
    buf, answers = pia_dokument.erzeuge(s, app.interview_service, app.generation_service,
                                        app.projekt_service)
    erg = pruefe_session(s, answers=answers, tarife=app.projekt_service.effective_tarife(org_id=org),
                         dokument=Document(io.BytesIO(buf.getvalue())))
    return {
        "fall": fall_id, "mit_rag": mit_rag,
        "bereit": ansicht["erkannt"]["reife"]["zustand"] == "bereit_zur_pruefung",
        "kriterien_offen": sum(1 for k in ansicht["kriterien"]
                               if k["zustand"] not in ("erfuellt", "nicht_anwendbar")),
        "fragen": len(fragen), "wiederholte_fragen": wiederholt,
        "korrekturen": sum(1 for a in z.aussagen if a["status"] == "ersetzt"
                           and a["herkunft"] == "benutzer"),
        "rag_themen_genutzt": sum(1 for t in z.themen if t["status"] in ("gefragt", "bestaetigt")),
        "nicht_uebernehmen_gefragt": sum(1 for t in z.themen
                                         if t["uebertragbarkeit"] == "nicht_uebernehmen"
                                         and t["status"] in ("gefragt", "bestaetigt")),
        "unbestaetigt_im_dokument": unbestaetigt,
        "muss_befunde_export": len(erg.muss),
        "modellaufrufe": len(d.llm.aufrufe),
    }


def _lauf(kandidat, faelle):
    from app.config import Config
    from app.factory import create_app
    tmp = Path(tempfile.mkdtemp(prefix="hp_eval_"))

    class Cfg(Config):
        DATABASE_URL = "sqlite:///" + str(tmp / "eval.db").replace("\\", "/")
        SECRET_KEY = secrets.token_hex(16)

    with ueberlagert(kandidat):
        app = create_app(Cfg)
        return [kennzahlen(app, f, mit_rag) for f in faelle for mit_rag in (True, False)]


def urteil(baseline, kandidat):
    """«abgelehnt», «besser» oder «gleichwertig» – Schutzkennzahlen zuerst."""
    gruende = []
    for b, k in zip(baseline, kandidat):
        for s in SCHUTZ:
            if k[s] > b[s]:
                gruende.append(f"{b['fall']} (RAG {'an' if b['mit_rag'] else 'aus'}): {s} "
                               f"{b[s]} -> {k[s]}")
        if b["bereit"] and not k["bereit"]:
            gruende.append(f"{b['fall']}: war bereit, ist es nicht mehr")
    if gruende:
        return "abgelehnt", gruende
    besser = [f"{b['fall']}: {m} {b[m]} -> {k[m]}" for b, k in zip(baseline, kandidat)
              for m in ("wiederholte_fragen", "kriterien_offen", "fragen") if k[m] < b[m]]
    schlechter = [f"{b['fall']}: {m} {b[m]} -> {k[m]}" for b, k in zip(baseline, kandidat)
                  for m in ("wiederholte_fragen", "kriterien_offen") if k[m] > b[m]]
    if besser and not schlechter:
        return "besser", besser
    return "gleichwertig", besser + schlechter


def vergleich(kandidat, aus):
    ziel = Path(aus)
    ziel.mkdir(parents=True, exist_ok=True)
    bericht = {"erstellt": datetime.now().isoformat(timespec="seconds"),
               "kandidat": str(kandidat) if kandidat else None,
               "hinweis": ("Drehbuch-Modell: verglichen werden Profil, Planer, Regeln, Projektion "
                           "und Export – nicht die Qualität eines echten Sprachmodells. Ein "
                           "Kandidat wird nie automatisch übernommen.")}
    for name, faelle in (("entwicklung", ENTWICKLUNG), ("pruefung", PRUEFUNG)):
        b = _lauf(None, faelle)
        k = _lauf(kandidat, faelle) if kandidat else b
        u, gruende = urteil(b, k)
        bericht[name] = {"baseline": b, "kandidat": k, "urteil": u, "gruende": gruende}
    # Das Gesamturteil zählt an den Prüffällen; abgelehnt ist abgelehnt.
    urteile = {bericht[n]["urteil"] for n in ("entwicklung", "pruefung")}
    bericht["urteil"] = ("abgelehnt" if "abgelehnt" in urteile else bericht["pruefung"]["urteil"])
    (ziel / "vergleich.json").write_text(json.dumps(bericht, ensure_ascii=False, indent=2),
                                         encoding="utf-8")
    return bericht


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="befehl", required=True)
    f = sub.add_parser("freigeben")
    f.add_argument("--db", required=True)
    f.add_argument("--ids", required=True)
    s = sub.add_parser("schwaechen")
    s.add_argument("--db", required=True)
    s.add_argument("--aus", required=True)
    v = sub.add_parser("vergleich")
    v.add_argument("--kandidat")
    v.add_argument("--aus", required=True)
    a = p.parse_args(argv)
    if a.befehl == "freigeben":
        print("freigegeben:", freigeben(a.db, [int(x) for x in a.ids.split(",") if x.strip()]))
    elif a.befehl == "schwaechen":
        b = schwaechen(a.db, a.aus)
        print(f"{b['rueckmeldungen_freigegeben']} Rückmeldungen, {len(b['kandidaten'])} Kandidat(en)")
    else:
        b = vergleich(a.kandidat, a.aus)
        print("Urteil:", b["urteil"])


if __name__ == "__main__":
    main()
