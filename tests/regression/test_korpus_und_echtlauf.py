"""Bestandsaufnahme des Korpus, synthetischer Korpus und Werkzeug für den
echten Nachweis auf dev – geprüft ohne externe Aufrufe.

- Die Bestandsaufnahme liest nur (schreibgeschützt, keine Migration).
- Der synthetische Korpus wird getrennt vom Bestand geladen (eigene
  Korpusversion, «extern freigegeben»), Bestand bleibt unverändert.
- Der echte Lauf prüft seine Voraussetzungen, bricht an der Budgetgrenze
  geordnet ab und schreibt Word-Datei und Protokoll.
"""
import hashlib
import json

import pytest

from app.domains.corpus.bestand import bestand
from app.domains.corpus.service import RagService
from tests.regression.adaptiv_hilfen import ModellDouble, app  # noqa: F401
from tools import dev_echtlauf
from tools.korpus_synthetisch import DOKUMENTE
from tools.synthetische_faelle import WortEmbedder


def _db_pfad(app):
    return app.config["DATABASE_URL"][len("sqlite:///"):]


def test_bestandsaufnahme_liest_nur(app):
    with app.app_context():
        rag = RagService(WortEmbedder())
        rag.ingest_document("1 Ausgangslage\nMigration der Datenbestände. " * 4, projekt="Bestand-1")
        rag.ingest_document(DOKUMENTE[0]["text"], projekt=DOKUMENTE[0]["projekt"],
                            korpus_version="synthetisch-test", extern_freigegeben=True)
    pfad = _db_pfad(app)
    vorher = hashlib.sha256(open(pfad, "rb").read()).hexdigest()
    b = bestand(pfad, modell="synthetisch-wort-v1")
    assert hashlib.sha256(open(pfad, "rb").read()).hexdigest() == vorher
    g = b["bereiche"]["geteilt"]
    assert g["dokumente"] == 2 and g["chunks"] >= 2
    assert g["extern_freigegeben"] >= 1
    assert "synthetisch-test" in g["korpus_versionen"]
    assert g["kompatibilitaet"]["einheitliche_vektorlaenge"] is True


def test_bestandsaufnahme_meldet_fehlendes_konkret(tmp_path):
    assert bestand(tmp_path / "gibt-es-nicht.db")["grund"] == "Datenbankdatei nicht gefunden"


def test_bestand_nur_fuer_den_betreiber(app):
    org = app.auth_service.create_org("Musteramt").id
    app.auth_service.create_user("pl@m.example", "pw", org_id=org, can_read=True, can_write=True)
    c = app.test_client()
    c.post("/login", data={"email": "pl@m.example", "password": "pw"})
    assert c.get("/admin/korpus/bestand").status_code in (302, 403)
    b = app.test_client()
    b.post("/login", data={"email": "betreiber@test.ch", "password": "pw-super"})
    r = b.get("/admin/korpus/bestand")
    assert r.status_code == 200
    assert "bereiche" in r.get_json() or "grund" in r.get_json()
    assert "/" not in r.get_json()["datenbank"]             # kein Serverpfad


def test_synthetischer_korpus_ist_frei_von_realen_bezuegen():
    texte = " ".join(d["text"] + d["projekt"] for d in DOKUMENTE)
    for verboten in ("Zürich", "Zuerich", "Bern ", "Riccarda", "[Person_", "[Org_"):
        assert verboten not in texte
    assert all(d["projekt"].startswith("Synthetik-") for d in DOKUMENTE)


# ---- echter Lauf: Mechanik ohne externe Aufrufe ---------------------------------- #

def test_echtlauf_prueft_voraussetzungen(app):
    v = dev_echtlauf.voraussetzungen(app)
    assert v["probleme"]                                     # Testumgebung: keine Wege


def test_echtlauf_endet_geordnet_an_der_budgetgrenze(app, tmp_path, monkeypatch):
    from app.domains.llm import client
    monkeypatch.setitem(client.VERBRAUCH, "input_tokens", 10_000_000)
    kasse = dev_echtlauf.Kasse({"in": 3, "out": 15, "emb": 0.1}, 10.0, None)
    assert kasse.stand()["usd_geschaetzt"] == 30.0 and not kasse.reicht_fuer_schritt()
    d = app.adaptiv_service
    d.llm = ModellDouble()
    with app.app_context():
        org = app.auth_service.create_org("Synthetik").id
        prot = dev_echtlauf.lauf_a(app, d, org, tmp_path, kasse)
    assert prot["abbruch"] == "Budgetgrenze erreicht"
    assert (tmp_path / prot["docx"]).exists()                # Stand bleibt nachvollziehbar


def test_echtlauf_schreibt_protokoll_und_docx(app, tmp_path):
    kasse = dev_echtlauf.Kasse({"in": 3, "out": 15, "emb": 0.1}, 10.0, None)
    d = app.adaptiv_service
    d.llm = ModellDouble()
    with app.app_context():
        org = app.auth_service.create_org("Synthetik").id
        prot = dev_echtlauf.lauf_b(app, d, org, tmp_path, kasse)
    assert len(prot["zwischenstaende"]) == len(dev_echtlauf.FALL_B["schritte"])
    assert (tmp_path / prot["docx"]).exists()
    json.dumps(prot, default=str)                            # serialisierbar


@pytest.mark.parametrize("frage,erwartet", [
    ({"aktion": "abschluss"}, None),
    ({"aktion": "rueckspiegeln"}, "Ja, das stimmt so."),
    ({"aktion": "erkunden", "abschnitt": "sachmittel"}, dev_echtlauf.FALL_A["antworten"]["sachmittel"]),
])
def test_antwortbuch(frage, erwartet):
    assert dev_echtlauf._antwort(dev_echtlauf.FALL_A, frage, set()) == erwartet
