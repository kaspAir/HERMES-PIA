"""Kontrollierte Verbesserung: Rückmeldungen, Kandidaten, Baseline-Vergleich.

Zugeordneter Akzeptanzfall: AT26 – Feedback führt zu einem versionierten
Kandidaten und einem Baseline-Vergleich, nicht zu ungefragter
Produktivänderung oder unkontrolliertem Korpuswachstum.
"""
import hashlib
import json
from pathlib import Path

from app.domains.corpus.models import CorpusChunk
from app.domains.interview.adaptiv.models import PiaRueckmeldung
from app.shared.database import SessionLocal
from tests.regression.adaptiv_hilfen import ModellDouble, app, dienst, neue_session  # noqa: F401
from tools import evaluation_interview as ev

WURZEL = Path(__file__).resolve().parents[2]
NORMDATEIEN = [WURZEL / "methods/hermes_pia/abschlussprofil.yaml",
               WURZEL / "methods/hermes_pia/rag_uebertragung.yaml"]


def _hashes():
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in NORMDATEIEN}


def test_at26_rueckmeldung_traegt_die_wirksamen_versionen(app):
    d = dienst(app, ModellDouble())
    sid = neue_session(app)
    d.starte(sid)
    d.rueckmeldung(sid, "frage_unklar")
    r = SessionLocal().query(PiaRueckmeldung).filter(PiaRueckmeldung.session_id == sid).one()
    versionen = json.loads(r.versionen_json)
    assert versionen["abschlussprofil"] and versionen["prompt_frage"]
    assert r.freigegeben is False              # nie automatisch Evaluationsdaten


def test_at26_nur_freigegebene_rueckmeldungen_bilden_kandidaten(app, tmp_path):
    d = dienst(app, ModellDouble())
    sid = neue_session(app)
    d.starte(sid)
    for _ in range(4):
        d.rueckmeldung(sid, "frage_unklar", bezug="K-PO-1")
    ids = [r.id for r in SessionLocal().query(PiaRueckmeldung).all()]
    vorher = _hashes()

    leer = ev.schwaechen(None, tmp_path / "ohne", app=app)
    assert leer["rueckmeldungen_freigegeben"] == 0 and not leer["kandidaten"]

    ev.freigeben(None, ids[:3], app=app)
    bericht = ev.schwaechen(None, tmp_path / "mit", app=app)
    assert bericht["rueckmeldungen_freigegeben"] == 3
    (kandidat,) = bericht["kandidaten"]
    assert kandidat["status"] == "vorgeschlagen" and kandidat["betrifft"] == "K-PO-1"
    assert (tmp_path / "mit" / kandidat["id"] / "kandidat.json").exists()
    assert _hashes() == vorher                 # keine Produktivänderung


def test_at26_einzelne_rueckmeldung_ist_keine_regel(app, tmp_path):
    d = dienst(app, ModellDouble())
    sid = neue_session(app)
    d.starte(sid)
    d.rueckmeldung(sid, "frage_unklar", bezug="K-KM-1")
    ev.freigeben(None, [r.id for r in SessionLocal().query(PiaRueckmeldung).all()], app=app)
    assert not ev.schwaechen(None, tmp_path, app=app)["kandidaten"]


def test_at26_kandidat_wird_nur_fuer_den_lauf_wirksam(tmp_path):
    from app.domains.interview.adaptiv import vollstaendigkeit
    original = vollstaendigkeit.profil()["profil"]["version"]
    k = tmp_path / "K-test"
    k.mkdir()
    text = NORMDATEIEN[0].read_text(encoding="utf-8")
    (k / "abschlussprofil.yaml").write_text(
        text.replace(f'version: "{original}"', 'version: "kandidat-1"', 1)
        if f'version: "{original}"' in text else text.replace(original, "kandidat-1", 1),
        encoding="utf-8")
    with ev.ueberlagert(k):
        assert vollstaendigkeit.profil()["profil"]["version"] == "kandidat-1"
    assert vollstaendigkeit.profil()["profil"]["version"] == original


def test_at26_schutzkennzahlen_lehnen_ab():
    basis = [{"fall": "F-02", "mit_rag": True, "bereit": True, "unbestaetigt_im_dokument": 0,
              "nicht_uebernehmen_gefragt": 0, "muss_befunde_export": 0,
              "wiederholte_fragen": 1, "kriterien_offen": 0, "fragen": 6}]
    weniger_fragen_aber_unbestaetigtes = [dict(basis[0], fragen=3, unbestaetigt_im_dokument=1)]
    urteil, gruende = ev.urteil(basis, weniger_fragen_aber_unbestaetigtes)
    assert urteil == "abgelehnt" and "unbestaetigt_im_dokument" in gruende[0]
    nur_weniger = [dict(basis[0], fragen=4, wiederholte_fragen=0)]
    assert ev.urteil(basis, nur_weniger)[0] == "besser"


def test_at26_kennzahlen_eines_falls(app):
    k = ev.kennzahlen(app, "F-02")
    assert k["bereit"] and k["muss_befunde_export"] == 0 and k["unbestaetigt_im_dokument"] == 0
    assert k["nicht_uebernehmen_gefragt"] == 0


def test_at26_kein_ungesteuertes_korpuswachstum(app):
    from app.domains.corpus.service import RagService
    from tools.fall_durchspielen import spiele_in
    from tools.synthetische_faelle import KORPUS, WortEmbedder
    spiele_in(app, "F-02")
    db = SessionLocal()
    vorher = db.query(CorpusChunk).count()
    spiele_in(app, "F-01", org_name="Zweites Amt")        # Interview + Export
    assert db.query(CorpusChunk).count() == vorher       # nichts zurückgespeist
    # Derselbe Text unter anderem Projektnamen ist eine Dublette.
    rag = RagService(WortEmbedder())
    assert rag.ingest_document(KORPUS[0]["text"], projekt="Umbenannt") == 0
