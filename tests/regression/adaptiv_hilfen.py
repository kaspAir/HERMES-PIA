"""Gemeinsame Hilfen der Tests zum adaptiven Interview.

Das Modell-Double bedient die VERTRÄGE, nicht eine Wunschvorstellung: es
liefert die JSON-Formen, die der Code prüft. Damit beweisen die Tests das
Verhalten des Codes – nicht die Qualität eines echten Modells (das ist
ausdrücklich eine eigene, noch offene Abnahme).
"""
import json

import pytest

from app.config import Config
from app.factory import create_app


class ModellDouble:
    """Antwortet je Prompt-Art aus einer Warteschlange; zählt alle Aufrufe."""

    def __init__(self, aussagen=None, fragen=None, texte=None, themen=None):
        self.aussagen = list(aussagen or [])
        self.fragen = list(fragen or [])
        self.texte = list(texte or [])
        self.themen = list(themen or [])
        self.aufrufe = []

    def complete(self, system, messages, max_tokens=1024, **kw):
        inhalt = messages[-1]["content"] if messages else ""
        if "ÄNDERUNGEN am Stand" in system:
            art, schlange = "aussagen", self.aussagen
        elif "WAS als Nächstes zu klären ist" in system:
            art, schlange = "frage", self.fragen
        elif "Kapitel «Ausgangslage»" in system:
            art, schlange = "ausgangslage", self.texte
        elif "THEMENKANDIDATEN" in system:
            art, schlange = "themen", self.themen
        else:
            art, schlange = "anderes", []
        self.aufrufe.append({"art": art, "inhalt": inhalt, "max_tokens": max_tokens})
        if not schlange:
            if art == "frage":
                return json.dumps({"frage": "Was ist Dir dazu noch wichtig?"})
            return "{}"
        antwort = schlange.pop(0)
        if isinstance(antwort, Exception):
            raise antwort
        return antwort if isinstance(antwort, str) else json.dumps(antwort, ensure_ascii=False)


def ops(*operationen, bezug_unklar=None):
    return {"operationen": list(operationen), "bezug_unklar": bezug_unklar}


def neu(inhalt, *ziele, art="benutzerangabe", quelle="wortlaut", bezug=None,
        entscheid=None, thema=""):
    o = {"op": "neu", "inhalt": inhalt, "art": art, "quelle": quelle,
         "thema": thema, "ziele": [{"abschnitt": a, "felder": f} for a, f in ziele]}
    if bezug:
        o["bezug"] = bezug
    if entscheid:
        o["entscheid"] = entscheid
    return o


@pytest.fixture
def app(tmp_path):
    from app.shared.database import SessionLocal

    class _Cfg(Config):
        DATABASE_URL = "sqlite:///" + str(tmp_path / "adaptiv.db").replace("\\", "/")
        SECRET_KEY = "test-secret"
        SUPERADMIN_EMAIL = "betreiber@test.ch"
        SUPERADMIN_PASSWORD = "pw-super"

    SessionLocal.remove()
    anwendung = create_app(_Cfg)
    SessionLocal.remove()
    yield anwendung
    SessionLocal.remove()


def neue_session(app, org_id=1, **kopf):
    s = app.interview_service.start_session(
        method_id="hermes_pia", project_name=kopf.get("projektname", "Ablösung Fachanwendung"),
        org_id=org_id, auftraggeber=kopf.get("auftraggeber", "Maria Beispiel"),
        created_by=kopf.get("projektleiter", "Sam Muster"),
        start_datum=kopf.get("start_datum"))
    return s.id


def dienst(app, modell=None, themen=None):
    from app.domains.interview.adaptiv.dienst import AdaptivesInterview
    return AdaptivesInterview(app.interview_service, llm=modell, themen=themen)


def bis_zur_frage(d, sid, hoechstens=6):
    """Ruft weiter() wie der Browser: so lange, bis nichts mehr aussteht."""
    ansicht = d.ansicht(sid)
    for _ in range(hoechstens):
        if not ansicht["ausstehend"]:
            return ansicht
        ansicht = d.weiter(sid)
    raise AssertionError(f"Nach {hoechstens} Schritten steht noch {ansicht['ausstehend']} aus")
