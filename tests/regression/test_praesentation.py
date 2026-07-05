"""PIA-Upload + Präsentationsgenerierung: Parser, Builder, Vorlagen-Vorrang, Routen."""
import base64
import io

import docx
import pytest
from pptx import Presentation

from app.config import Config
from app.domains.praesentation.parser import parse_pia
from app.domains.praesentation.service import PraesentationService
from app.factory import create_app


# ---- Hilfen: Beispiel-PIA (.docx) und Vorlage (.pptx) im Speicher ------ #

LANGES_RISIKO = ("Schlüsselpersonen aus dem IT-Betrieb sind wegen operativer Belastung "
                 "nicht ausreichend für die Erarbeitung der Studie, der Schutzbedarfsanalyse "
                 "und des Projektmanagementplans verfügbar, wodurch die fristgerechte "
                 "Fertigstellung der Initialisierungsergebnisse gefährdet wird.")


def _beispiel_pia_bytes():
    d = docx.Document()
    # Kopftabelle (vor der ersten Überschrift) -> Metadaten
    meta = d.add_table(rows=2, cols=2)
    meta.cell(0, 0).text = "Projektleiter/in"
    meta.cell(0, 1).text = "Petra Muster"
    meta.cell(1, 0).text = "Auftraggeber/in"
    meta.cell(1, 1).text = "Hans Beispiel"

    d.add_heading("Ausgangslage", level=1)
    d.add_paragraph("Das System X wird abgelöst. Die Betriebssicherheit muss steigen. "
                    "Alle Einheiten sind betroffen.")

    d.add_heading("Ziele der Phase Initialisierung", level=2)
    t = d.add_table(rows=2, cols=5)
    for i, h in enumerate(("Nr.", "Kategorie", "Beschreibung", "Messgrösse", "Priorität")):
        t.cell(0, i).text = h
    t.cell(1, 0).text = "01"
    t.cell(1, 2).text = "Die Studie liegt als Entscheidungsgrundlage vor."
    t.cell(1, 3).text = "Studie abgenommen"

    d.add_heading("Personalaufwand", level=2)
    t = d.add_table(rows=3, cols=3)
    for i, h in enumerate(("Rolle", "Name", "Aufwand in PT")):
        t.cell(0, i).text = h
    t.cell(1, 0).text = "Projektleiterin"; t.cell(1, 1).text = "Petra Muster"
    t.cell(1, 2).text = "25"
    t.cell(2, 0).text = "Externe Fachexpertise (extern)"; t.cell(2, 2).text = "20"

    d.add_heading("Kosten (in CHF inkl. MwSt.)", level=2)
    t = d.add_table(rows=5, cols=2)
    t.cell(0, 0).text = "Phase"; t.cell(0, 1).text = "Betrag"
    t.cell(1, 0).text = "Interne Personalkosten"; t.cell(1, 1).text = "50400"
    t.cell(2, 0).text = "Externe Fachexpertise (extern)"; t.cell(2, 1).text = "36000"
    t.cell(3, 0).text = "Summe externe Kosten"; t.cell(3, 1).text = "36000"
    t.cell(4, 0).text = "Total Initialisierung"; t.cell(4, 1).text = "86400"

    d.add_heading("Ergebnisse und Termine", level=2)
    t = d.add_table(rows=4, cols=5)
    for i, h in enumerate(("Nr.", "Lieferergebnisse (abnahmerelevant)", "Liefertermin",
                           "Abnahme durch (Rolle)", "Prüfmethode")):
        t.cell(0, i).text = h
    t.cell(1, 1).text = "Rechtsgrundlagenanalyse"; t.cell(1, 2).text = "05.10.2026"
    t.cell(1, 3).text = "Projektleiter"
    t.cell(2, 1).text = "Studie"; t.cell(2, 2).text = "26.10.2026"; t.cell(2, 3).text = "Projektleiter"
    t.cell(3, 1).text = "Meilenstein Durchführungsfreigabe"; t.cell(3, 2).text = "14.12.2026"
    t.cell(3, 3).text = "Auftraggeber"

    d.add_heading("Risiken", level=1)
    t = d.add_table(rows=3, cols=8)
    for i, h in enumerate(("Nr.", "Risikobeschreibung", "Eintrittswahrscheinlichkeit",
                           "Auswirkungsgrad", "Risikozahl", "Massnahmen",
                           "Verantwortung", "Termin")):
        t.cell(0, i).text = h
    t.cell(1, 1).text = LANGES_RISIKO
    t.cell(1, 2).text = "Hoch"; t.cell(1, 3).text = "Mittel"
    t.cell(2, 1).text = "Externe Expertise fehlt."
    t.cell(2, 4).text = "9"                     # EW/AG leer -> Fallback über Risikozahl

    d.add_heading("Dokument-Protokoll", level=1)  # Ende-Marker
    d.add_paragraph("Wird ignoriert.")

    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def _leere_pptx_bytes(width=None):
    prs = Presentation()
    if width:
        prs.slide_width = width
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


# ---- Parser ------------------------------------------------------------ #

def test_parser_liest_abschnitte_und_tabellen():
    pia = parse_pia(_beispiel_pia_bytes())
    assert pia["projektleiter"] == "Petra Muster"
    assert pia["auftraggeber"] == "Hans Beispiel"
    assert "Betriebssicherheit" in pia["ausgangslage"]
    assert pia["ziele"][0]["beschreibung"].startswith("Die Studie")
    assert {p["rolle"]: p["aufwand"] for p in pia["personalaufwand"]} == {
        "Projektleiterin": 25, "Externe Fachexpertise (extern)": 20}
    assert pia["personalaufwand"][0]["name"] == "Petra Muster"
    assert any(k["position"] == "Total Initialisierung" and k["betrag"] == 86400
               for k in pia["kosten"])
    assert pia["termine"][0]["ergebnis"] == "Rechtsgrundlagenanalyse"
    # "Abnahme durch (Rolle)" darf NICHT auf "(abnahmerelevant)" matchen:
    assert pia["termine"][0]["abnahme"] == "Projektleiter"
    assert pia["termine"][2]["abnahme"] == "Auftraggeber"
    # Risiko 1: EW/AG aus Text; Risiko 2: Fallback aus Risikozahl 9 -> (3,3)
    assert (pia["risiken"][0]["ew"], pia["risiken"][0]["ag"]) == (3, 2)
    assert (pia["risiken"][1]["ew"], pia["risiken"][1]["ag"]) == (3, 3)


# ---- Builder ------------------------------------------------------------ #

def test_builder_erzeugt_praesentation_ohne_vorlage():
    svc = PraesentationService(llm=None)
    buf = svc.generate_from_docx(_beispiel_pia_bytes(), template_bytes=None,
                                 fallback_name="Fallback", datum="05.07.2026")
    prs = Presentation(buf)
    # Titel, Ausgangslage, Ziele, Termine, Personal, Kosten, Matrix, Risiken, Antrag
    assert len(prs.slides) >= 8
    titel_texte = " ".join(s.text for s in prs.slides[0].shapes if s.has_text_frame
                           for s in [s])
    # Projektname kommt aus dem Dokument-Fallback (erste Absätze fehlen -> fallback_name)
    assert "Projektinitialisierungsauftrag" in _slide_text(prs.slides[0])


def _slide_text(slide):
    return " ".join(sh.text_frame.text for sh in slide.shapes if sh.has_text_frame)


def test_builder_baut_auf_vorlage_auf():
    breite = 12192000  # 16:9-Breite in EMU
    vorlage = _leere_pptx_bytes(width=breite)
    svc = PraesentationService(llm=None)
    buf = svc.generate_from_docx(_beispiel_pia_bytes(), template_bytes=vorlage,
                                 fallback_name="X", datum="")
    prs = Presentation(buf)
    assert prs.slide_width == breite            # Foliengrösse der Vorlage übernommen
    assert len(prs.slides) >= 8


def _vorlage_mit_beispielfolien():
    """Vorlage wie eine Firmenvorlage: 3 Beispiel-Folien auf unterschiedlichen
    Layouts (erste = Titeldesign, letzte = Schlussdesign)."""
    prs = Presentation()
    s1 = prs.slides.add_slide(prs.slide_layouts[0])
    s1.shapes.add_textbox(0, 0, 100, 100).text_frame.text = "BEISPIEL-MARKER-1"
    prs.slides.add_slide(prs.slide_layouts[1])
    s3 = prs.slides.add_slide(prs.slide_layouts[2])
    s3.shapes.add_textbox(0, 0, 100, 100).text_frame.text = "BEISPIEL-MARKER-3"
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue(), prs.slide_layouts[0].name, prs.slide_layouts[2].name


def test_beispielfolien_raus_titel_und_schluss_aus_vorlage():
    vorlage, titel_layout, schluss_layout = _vorlage_mit_beispielfolien()
    svc = PraesentationService(llm=None)
    buf = svc.generate_from_docx(_beispiel_pia_bytes(), template_bytes=vorlage,
                                 fallback_name="X", datum="06.07.2026")
    prs = Presentation(buf)
    alle_texte = " ".join(_slide_text(s) for s in prs.slides)
    assert "BEISPIEL-MARKER" not in alle_texte            # Beispiel-Folien entfernt
    assert prs.slides[0].slide_layout.name == titel_layout   # Titeldesign der Vorlage
    assert prs.slides[-1].slide_layout.name == schluss_layout  # Schlussdesign (z.B. blau)
    assert "Besten Dank" in _slide_text(prs.slides[-1])


def _prst_geom(shape):
    el = shape._element.find(
        ".//{http://schemas.openxmlformats.org/drawingml/2006/main}prstGeom")
    return el.get("prst") if el is not None else None


def test_gantt_folie_mit_balken_und_meilenstein_rauten():
    svc = PraesentationService(llm=None)
    buf = svc.generate_from_docx(_beispiel_pia_bytes(), None, "X", "")
    prs = Presentation(buf)
    gantt = next((s for s in prs.slides if "Terminplan" in _slide_text(s)), None)
    assert gantt is not None
    formen = [_prst_geom(sh) for sh in gantt.shapes]
    assert formen.count("diamond") == 1        # 1 Meilenstein -> 1 Raute (Dauer 0)
    assert formen.count("roundRect") == 2      # 2 Ergebnisse -> 2 Balken


def test_risiken_volltext_notizen_und_keine_auslassungspunkte():
    svc = PraesentationService(llm=None)
    buf = svc.generate_from_docx(_beispiel_pia_bytes(), None, "X", "")
    prs = Presentation(buf)
    # Volle Risikobeschreibung in einer Tabelle - keine Kürzung.
    zelltexte = []
    for slide in prs.slides:
        for sh in slide.shapes:
            if getattr(sh, "has_table", False):
                zelltexte += [c.text for r in sh.table.rows for c in r.cells]
    assert any(LANGES_RISIKO == t for t in zelltexte)
    # HERMES-Terminologie: "Ergebnis", nicht "Lieferergebnis".
    assert "Ergebnis" in zelltexte and not any("Lieferergebnis" in t for t in zelltexte)
    # NIRGENDS abgeschnittene Sätze mit '…' - weder auf Folien noch in Notizen.
    for slide in prs.slides:
        for sh in slide.shapes:
            if sh.has_text_frame:
                assert "…" not in sh.text_frame.text
        assert "…" not in " ".join(zelltexte)
        assert slide.has_notes_slide
        notizen = slide.notes_slide.notes_text_frame.text
        assert notizen.strip() and "…" not in notizen and "Lieferergebnis" not in notizen


def test_parser_risiken_mit_verschobenen_spalten():
    """Datenzeilen kuerzer als der Kopf (leere SDT-Zellen) -> Felder inhaltlich finden."""
    from app.domains.praesentation.parser import _parse_risiken
    rows = [
        ["Nr.", "Risikobeschreibung", "Eintrittswahrscheinlichkeit", "Auswirkungsgrad",
         "Risikozahl", "Massnahmen", "Verantwortung", "Termin"],
        ["01", "Externe Fachexpertise ist nicht rechtzeitig verfuegbar und gefaehrdet die Studie.",
         "9", "Fruehzeitig Marktsondierung einleiten und Anbieter anfragen.",
         "Projektleiter", "laufend"],
    ]
    out = _parse_risiken(rows)
    assert len(out) == 1
    assert (out[0]["ew"], out[0]["ag"]) == (3, 3)          # Risikozahl 9 -> hoch/hoch
    assert out[0]["beschreibung"].startswith("Externe Fachexpertise")


# ---- App-Fixture für Service/Routen ------------------------------------- #

@pytest.fixture
def app(tmp_path):
    from app.shared.database import SessionLocal
    db_path = str(tmp_path / "praes.db").replace("\\", "/")

    class _Cfg(Config):
        DATABASE_URL = "sqlite:///" + db_path
        SUPERADMIN_EMAIL = "betreiber@test.ch"
        SUPERADMIN_PASSWORD = "pw-super"
        SECRET_KEY = "test-secret"

    SessionLocal.remove()
    application = create_app(_Cfg)
    SessionLocal.remove()
    yield application
    SessionLocal.remove()


def _client_mit_projekt(app):
    auth = app.auth_service
    org_id = auth.create_org("Org").id      # ID sofort sichern (Detached-Falle)
    auth.create_user("pl@org.ch", "pw", org_id=org_id,
                     can_read=True, can_write=True, can_delete=True)
    c = app.test_client()
    c.post("/login", data={"email": "pl@org.ch", "password": "pw"})
    c.post("/interview/start", data={"project_name": "P Demo", "projektleiter": "PL"})
    pid = app.projekt_service.projekte_for_org(org_id)[0].id
    eid = app.projekt_service.ergebnisse(pid)[0].id
    return c, org_id, pid, eid


# ---- Vorlagen-Vorrang ----------------------------------------------------- #

def test_vorlage_projekt_schlaegt_org(app):
    svc = app.projekt_service
    c, org_id, pid, eid = _client_mit_projekt(app)
    projekt = svc.get_projekt(pid)
    assert svc.resolve_vorlage(projekt) is None
    svc.add_vorlage("org.pptx", b"PKorg", org_id=org_id, projekt_id=None)
    assert svc.resolve_vorlage(projekt).filename == "org.pptx"
    svc.add_vorlage("projekt.pptx", b"PKprj", org_id=org_id, projekt_id=pid)
    assert svc.resolve_vorlage(projekt).filename == "projekt.pptx"


# ---- Routen ----------------------------------------------------------------- #

def _b64(data):
    return base64.b64encode(data).decode()


def test_upload_download_und_status(app):
    c, org_id, pid, eid = _client_mit_projekt(app)
    pia = _beispiel_pia_bytes()
    r = c.post(f"/projekt/{pid}/ergebnis/{eid}/dokument",
               json={"filename": "PIA_v0.9.docx", "data": _b64(pia)})
    assert r.status_code == 200
    dok = app.projekt_service.latest_dokument(eid, art="freigabe")
    assert dok.filename == "PIA_v0.9.docx" and dok.size == len(pia)
    # Status des Ergebnisses wechselt auf "zur Freigabe"
    erg = app.projekt_service.ergebnisse(pid)[0]
    assert erg.status == "zur Freigabe"
    # Download liefert die Originaldatei
    r = c.get(f"/projekt/{pid}/dokument/{dok.id}")
    assert r.status_code == 200 and r.data == pia


def test_upload_validierung(app):
    c, org_id, pid, eid = _client_mit_projekt(app)
    url = f"/projekt/{pid}/ergebnis/{eid}/dokument"
    assert c.post(url, json={"filename": "x.txt", "data": _b64(b"PKx")}).status_code == 400
    assert c.post(url, json={"filename": "x.docx", "data": ""}).status_code == 400
    assert c.post(url, json={"filename": "x.docx", "data": _b64(b"kein zip")}).status_code == 400


def test_praesentation_route(app):
    c, org_id, pid, eid = _client_mit_projekt(app)
    # Ohne hochgeladenen PIA: klarer Hinweis statt Absturz
    assert c.get(f"/projekt/{pid}/ergebnis/{eid}/praesentation").status_code == 400
    c.post(f"/projekt/{pid}/ergebnis/{eid}/dokument",
           json={"filename": "PIA.docx", "data": _b64(_beispiel_pia_bytes())})
    # Mit Projekt-Vorlage
    c.post(f"/projekt/{pid}/vorlage",
           json={"filename": "v.pptx", "data": _b64(_leere_pptx_bytes()), "scope": "projekt"})
    r = c.get(f"/projekt/{pid}/ergebnis/{eid}/praesentation")
    assert r.status_code == 200
    assert "presentationml" in r.mimetype
    # Dateiname: yyyymmdd_Projektname.pptx
    import re as _re
    cd = r.headers.get("Content-Disposition", "")
    assert _re.search(r"\d{8}_P_Demo\.pptx", cd), cd
    prs = Presentation(io.BytesIO(r.data))
    assert len(prs.slides) >= 8


def test_dokumente_fremder_org_gesperrt(app):
    c, org_id, pid, eid = _client_mit_projekt(app)
    pia = _beispiel_pia_bytes()
    c.post(f"/projekt/{pid}/ergebnis/{eid}/dokument",
           json={"filename": "PIA.docx", "data": _b64(pia)})
    dok_id = app.projekt_service.latest_dokument(eid).id

    auth = app.auth_service
    other_id = auth.create_org("Andere").id
    auth.create_user("fremd@x.ch", "pw", org_id=other_id,
                     can_read=True, can_write=True, can_delete=False)
    cb = app.test_client()
    cb.post("/login", data={"email": "fremd@x.ch", "password": "pw"})
    assert cb.get(f"/projekt/{pid}/dokument/{dok_id}").status_code == 403
    assert cb.post(f"/projekt/{pid}/ergebnis/{eid}/dokument",
                   json={"filename": "x.docx", "data": _b64(pia)}).status_code == 403


def test_delete_projekt_raeumt_dokumente_und_vorlagen(app):
    c, org_id, pid, eid = _client_mit_projekt(app)
    c.post(f"/projekt/{pid}/ergebnis/{eid}/dokument",
           json={"filename": "PIA.docx", "data": _b64(_beispiel_pia_bytes())})
    c.post(f"/projekt/{pid}/vorlage",
           json={"filename": "v.pptx", "data": _b64(_leere_pptx_bytes()), "scope": "projekt"})
    dok_id = app.projekt_service.latest_dokument(eid).id
    c.post(f"/projekt/{pid}/delete")
    assert app.projekt_service.get_projekt(pid) is None
    assert app.projekt_service.get_dokument(dok_id) is None
