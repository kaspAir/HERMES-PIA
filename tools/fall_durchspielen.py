"""Einen synthetischen Fall durchspielen und den PIA als Word-Datei erzeugen.

    python tools/fall_durchspielen.py <fall-id> <ziel.docx> [--json zustand.json]

Nutzt dieselben Dienste wie die Oberfläche (Beitrag -> ausstehende Schritte
bis zur nächsten Frage), ein Drehbuch-Modell und einen synthetischen Korpus.
Ergebnis: die Word-Datei aus derselben Projektion wie der Download – und
optional der Zustand als JSON (Aussagen, Kriterien, Themen).

Kein Nachweis echter Modellqualität; siehe tools/synthetische_faelle.py.
"""
import copy
import json
import secrets
import sys
import tempfile
from pathlib import Path

WURZEL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WURZEL))


def spiele_in(app, fall_id, org_name="Musterkanton – Amt für Baubewilligungen",
              nur_schritte=None, version="Entwurf aus dem Interview", mit_rag=True):
    """Spielt den Fall in einer BESTEHENDEN Anwendung durch (auch für Tests).

    Rückgabe: (org_id, session_id, letzte Ansicht, Dienst). Der Dienst trägt
    das Drehbuch-Modell; `dienst.llm.aufrufe` zählt jeden Modellaufruf.
    """
    from app.domains.corpus.service import RagService
    from app.domains.interview.adaptiv.dienst import AdaptivesInterview
    from app.domains.interview.adaptiv.rag_themen import ThemenQuelle
    from tools.synthetische_faelle import FAELLE, KORPUS, DrehbuchModell, WortEmbedder

    # Kopie: ein Lauf darf das Drehbuch nicht für den nächsten verändern.
    fall = copy.deepcopy(next(f for f in FAELLE if f["id"] == fall_id))
    rag = RagService(WortEmbedder())
    for k in KORPUS:
        rag.ingest_document(k["text"], projekt=k["projekt"], korpus_version="synthetisch-1")
    d = AdaptivesInterview(app.interview_service, llm=DrehbuchModell(fall),
                           themen=ThemenQuelle(rag) if mit_rag else None)
    org = app.auth_service.create_org(org_name).id
    if fall.get("tarife"):
        app.projekt_service.set_kostensatz(fall["tarife"]["intern"], fall["tarife"]["extern"],
                                           einheit="tag", org_id=org)
    k = fall["kopf"]
    s = app.interview_service.start_session(method_id="hermes_pia", project_name=k["projektname"],
                                            org_id=org, auftraggeber=k["auftraggeber"],
                                            created_by=k["projektleiter"])
    tarife = app.projekt_service.effective_tarife(org_id=org)
    ansicht = d.starte(s.id)
    schritte = fall["schritte"][:nur_schritte] if nur_schritte else fall["schritte"]
    for i, schritt in enumerate(schritte):
        ansicht = d.beitrag(s.id, schritt["text"], anfrage_id=f"{fall_id}-{i}", tarife=tarife)
        while ansicht["ausstehend"]:
            ansicht = d.weiter(s.id, tarife=tarife)
        for nachfolge in schritt.get("danach", []):
            if nachfolge == "vorschlaege_uebernehmen":
                offen = [e["schluessel"] for e in ansicht["erkannt"]["offen"]
                         if e["herkunft"] == "system" and not e["bestaetigt"]]
                ansicht = d.sammelbestaetigung(s.id, offen, tarife=tarife)
                while ansicht["ausstehend"]:
                    ansicht = d.weiter(s.id, tarife=tarife)
    if version:
        # Wie in der Oberfläche: Download über die Versionsseite. Der Eintrag
        # in der Änderungskontrolle ist ein tatsächlicher Vorgang.
        app.interview_service.record_version_bump(s.id, "minor", k["projektleiter"], version)
    return org, s.id, ansicht, d


def spiele(fall_id, ziel_docx, zustand_json=None, nur_schritte=None,
           version="Entwurf aus dem Interview"):
    from app.config import Config
    from app.domains.generation import pia as pia_dokument
    from app.factory import create_app

    tmp = Path(tempfile.mkdtemp(prefix="hp_fall_"))

    class Cfg(Config):
        DATABASE_URL = "sqlite:///" + str(tmp / "fall.db").replace("\\", "/")
        SECRET_KEY = secrets.token_hex(16)

    app = create_app(Cfg)
    _, sid, ansicht, d = spiele_in(app, fall_id, nur_schritte=nur_schritte, version=version)
    session = app.interview_service.get_session(sid)
    buf, answers = pia_dokument.erzeuge(session, app.interview_service, app.generation_service,
                                        app.projekt_service)
    Path(ziel_docx).write_bytes(buf.getvalue())
    if zustand_json:
        z = d.zustand.lade(sid)
        Path(zustand_json).write_text(json.dumps({
            "aussagen": z.aussagen, "themen": z.themen, "konflikte": z.konflikte,
            "kriterien": ansicht["kriterien"], "frage": ansicht["frage"],
            "reife": ansicht["erkannt"]["reife"], "modellaufrufe": d.llm.aufrufe,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    return app, sid, ansicht


if __name__ == "__main__":
    args = sys.argv[1:]
    zj = args[args.index("--json") + 1] if "--json" in args else None
    spiele(args[0], args[1], zj)
    print("geschrieben:", args[1])
