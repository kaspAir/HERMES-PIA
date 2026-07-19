"""Beweist: Kostensätze (Projekt übersteuert Org, Einheit Stunde/Tag) fliessen in
die Personalkosten-Berechnung (Kap. 3.3) ein."""
import pytest

from app.config import Config
from app.domains.catalog.service import CatalogService
from app.domains.interview.service import InterviewService
from app.domains.method.service import MethodService
from app.factory import create_app


@pytest.fixture
def app(tmp_path):
    from app.shared.database import SessionLocal
    db_path = str(tmp_path / "tarif.db").replace("\\", "/")

    class _Cfg(Config):
        DATABASE_URL = "sqlite:///" + db_path
        SECRET_KEY = "x"

    SessionLocal.remove()
    application = create_app(_Cfg)
    SessionLocal.remove()
    yield application
    SessionLocal.remove()


def test_default_tarife_ohne_eintrag(app):
    with app.app_context():
        t = app.projekt_service.effective_tarife(org_id=1)
        assert t == {"intern": 1200, "extern": 1800}


def test_org_tagessatz(app):
    ps = app.projekt_service
    with app.app_context():
        ps.set_kostensatz(1000, 1500, einheit="tag", org_id=7)
        assert ps.effective_tarife(org_id=7) == {"intern": 1000, "extern": 1500}


def test_stundensatz_wird_auf_tag_umgerechnet(app):
    ps = app.projekt_service
    with app.app_context():
        ps.set_kostensatz(150, 220, einheit="stunde", stunden_pro_tag=8, org_id=3)
        # 150 CHF/h × 8 h = 1200 CHF/Tag; 220 × 8 = 1760
        assert ps.effective_tarife(org_id=3) == {"intern": 1200, "extern": 1760}


def test_projekt_uebersteuert_org(app):
    ps = app.projekt_service
    with app.app_context():
        projekt = ps.create_projekt(org_id=5, name="P")
        ps.set_kostensatz(1000, 1500, org_id=5)                       # Org-Default
        ps.set_kostensatz(2000, 3000, org_id=5, projekt_id=projekt.id)  # Projekt-Override
        assert ps.effective_tarife(org_id=5, projekt_id=projekt.id) == \
            {"intern": 2000, "extern": 3000}
        # Ohne Projektbezug bleibt der Org-Default
        assert ps.effective_tarife(org_id=5) == {"intern": 1000, "extern": 1500}


def test_set_kostensatz_aktualisiert_statt_dupliziert(app):
    ps = app.projekt_service
    with app.app_context():
        ps.set_kostensatz(1000, 1500, org_id=9)
        ps.set_kostensatz(1100, 1600, org_id=9)
        assert ps.effective_tarife(org_id=9) == {"intern": 1100, "extern": 1600}


def test_kosten_breakdown_nutzt_custom_tarife():
    cfg = Config
    svc = InterviewService(MethodService("app/methods"), CatalogService("app/catalogs"), None)
    answers = {"personalaufwand": {"extracted": [
        {"rolle": "Projektleiter", "aufwand": "10"},
        {"rolle": "Externe Fachexpertise", "aufwand": "5"},
    ]}}
    rows = svc._kosten_breakdown([], answers, tarife={"intern": 2000, "extern": 3000})
    text = {r["phase"]: r["betrag"] for r in rows}
    assert text["Interne Personalkosten (gem. Kap. 3.1)"] == "20000"   # 10 × 2000
    assert text["Externe Fachexpertise"] == "15000"                    # 5 × 3000
