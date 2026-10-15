"""Der Testlauf führt das adaptive Interview – mit simuliertem Projektleiter.

Befund des Auftraggebers auf dev (15.10.2026): Der Testlauf «führte kein
Interview», er spielte alles aus der Ausgangslage durch – er lief noch auf dem
bisherigen Ablauf. Jetzt führt er, wenn ein Sprachmodell da ist, dasselbe
adaptive Interview wie der normale PIA-Start: HERMES PIA fragt, ein simulierter
Projektleiter antwortet NUR aus der Ausgangslage.
"""
import json

from app.domains.interview.adaptiv.models import PiaNachricht
from app.domains.testlauf import service as tl
from app.shared.database import SessionLocal
from tests.regression.adaptiv_hilfen import ModellDouble, neu, ops
from tests.regression.test_testlauf import angemeldet, app  # noqa: F401


class Modell(ModellDouble):
    """Interview-Antworten aus der Warteschlange; Projektleiter aus der Ausgangslage."""

    def __init__(self):
        super().__init__(aussagen=[ops(neu("Die Registeranwendung ist veraltet",
                                           ("ausgangslage", {})))])
        self.pl_eingaben = []

    def complete(self, system, messages, max_tokens=1024, **kw):
        if "TESTLAUF die Projektleitung" in system:
            self.aufrufe.append({"art": "projektleiter"})
            self.pl_eingaben.append(messages[-1]["content"])
            return tl.PL_UNBEKANNT
        return super().complete(system, messages, max_tokens, **kw)


def _lauf(app, org_id):
    return app.testlauf_service.starte(
        org_id=org_id, ausgangslage="Die Registeranwendung ist veraltet.",
        projektname="Testlauf adaptiv", projektleiter="Kim Muster", auftraggeber="Robin Beispiel")


def test_testlauf_fuehrt_das_adaptive_interview(app, angemeldet, monkeypatch):
    _, org_id = angemeldet
    modell = Modell()
    app.adaptiv_service.llm = modell
    monkeypatch.setattr(tl, "HOECHSTZAHL_ANTWORTEN", 3)
    lauf = _lauf(app, org_id)
    assert app.interview_service.get_session(lauf.session_id).modus == "adaptiv"

    aufrufe_je_schritt = []
    for _ in range(60):
        vorher = len(modell.aufrufe)
        z = app.testlauf_service.schritt(lauf.id)
        aufrufe_je_schritt.append(len(modell.aufrufe) - vorher)
        if z["schritt"] >= 1:                      # Interview-Schritt abgeschlossen
            break
    assert z["schritt"] >= 1, "das Interview endet"
    # Ein Aufruf = höchstens ein Modellaufruf (Zeitlimit-Regel des Testlaufs).
    assert max(aufrufe_je_schritt) <= 1

    nachrichten = SessionLocal().query(PiaNachricht).filter(
        PiaNachricht.session_id == lauf.session_id).order_by(PiaNachricht.id).all()
    beitraege = [m.text for m in nachrichten if m.rolle == "benutzer"]
    fragen = [m for m in nachrichten if m.rolle == "system" and m.art == "frage"]
    assert beitraege[0] == "Die Registeranwendung ist veraltet."
    assert tl.PL_UNBEKANNT in beitraege[1:]          # simulierter Projektleiter antwortet
    assert len(fragen) >= 2                           # HERMES PIA hat gefragt
    # Der Projektleiter kennt nur die Ausgangslage – und bekommt die Frage.
    assert all(e.startswith("AUSGANGSLAGE:\nDie Registeranwendung ist veraltet.")
               for e in modell.pl_eingaben)
    texte = " ".join(e["text"] for e in z["protokoll"])
    assert "Frage:" in texte and "Antwort:" in texte and "Interview" in texte


def test_ohne_sprachmodell_bleibt_der_bisherige_ablauf(app, angemeldet):
    _, org_id = angemeldet
    app.adaptiv_service.llm = None
    lauf = _lauf(app, org_id)
    assert app.interview_service.get_session(lauf.session_id).modus is None
    app.testlauf_service.schritt(lauf.id)
    answers = json.loads(app.interview_service.get_session(lauf.session_id).answers_json or "{}")
    assert "veraltet" in ((answers.get("ausgangslage") or {}).get("extracted") or {}).get("text", "")
