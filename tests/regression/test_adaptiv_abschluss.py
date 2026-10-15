"""Abschlussprüfung und vorlagentreuer Export des adaptiven Interviews.

Zugeordnete Akzeptanzfälle (Nummern wie im Entwicklungsauftrag v1.0):
  AT04  Annahmen bleiben als solche sichtbar – auch im Abschlussbericht
  AT17  echte Vollständigkeit: was die Ausgabeprüfung anhält, ist nicht «bereit»
  AT18  Vorlagenabdeckung: Deckblatt, 0.1–0.5, 1–8, acht Terminzeilen,
        Enddatum, Risikospalten, drei Protokolle
  AT19  Zahlen und Monate: Kap. 5 über neun Monate, Summen, Risikozahl
  AT20  Vorschlag und Freigabe: Systemvorschläge erst nach Übernahme im
        Dokument; Export erzeugt keine Prüf-, Abnahme- oder Freigabeeinträge
  AT21  Revision: Fertigstellen nur für den geprüften Stand; spätere
        Änderung setzt zurück
  AT22  DOCX-Qualität: idempotent, ohne Modellaufruf, Vorschau = Export,
        lange Inhalte, keine Beispiele
  AT25  Ende-zu-Ende: ein vollständiger Fall wird herunterladbar, ein Entwurf
        trägt seine offenen Punkte im Dokument

Die Fälle stammen aus tools/synthetische_faelle.py (erfundene Organisationen
und Personen). Sie belegen das Verhalten des Codes, nicht die Qualität eines
echten Sprachmodells.
"""
import io
import json
import re
import zipfile

import pytest
from docx import Document

from app.domains.generation import pia as pia_dokument
from app.domains.qualitaet.dokument import pruefe_dokument
from tests.regression.adaptiv_hilfen import app  # noqa: F401
from tools.fall_durchspielen import spiele_in


def _erzeuge(app, sid):
    s = app.interview_service.get_session(sid)
    buf, answers = pia_dokument.erzeuge(s, app.interview_service, app.generation_service,
                                        app.projekt_service)
    return buf.getvalue(), answers


def _tabellen(roh):
    return [[[c.text for c in r.cells] for r in t.rows] for t in Document(io.BytesIO(roh)).tables]


def _tabelle_mit(roh, kopf):
    return next(t for t in _tabellen(roh) if t and t[0] and t[0][0].startswith(kopf))


def _text(roh):
    d = Document(io.BytesIO(roh))
    teile = [p.text for p in d.paragraphs]
    for t in d.tables:
        for r in t.rows:
            teile.extend(c.text for c in r.cells)
    return "\n".join(teile)


def _anmelden(app, org_id, email="pl@beispiel.example"):
    app.auth_service.create_user(email, "pw", org_id=org_id, can_read=True, can_write=True)
    c = app.test_client()
    c.post("/login", data={"email": email, "password": "pw"})
    return c


def _post(c, url, daten):
    return c.post(url, data=json.dumps(daten), content_type="application/json")


@pytest.fixture
def vollstaendig(app):
    org, sid, ansicht, d = spiele_in(app, "F-02", org_name="Beispielstadt – Registerdienste")
    return {"org": org, "sid": sid, "ansicht": ansicht, "d": d}


@pytest.fixture
def entwurf(app):
    org, sid, ansicht, d = spiele_in(app, "F-01")
    return {"org": org, "sid": sid, "ansicht": ansicht, "d": d}


# ---- AT18 – Abschlussprüfung --------------------------------------------------- #

def test_at25_vollstaendiger_fall_ist_bereit_zur_pruefung(vollstaendig):
    reife = vollstaendig["ansicht"]["erkannt"]["reife"]
    assert reife["zustand"] == "bereit_zur_pruefung" and reife["blocker"] == 0


def test_at21_fertigstellen_nur_fuer_den_geprueften_stand(app, vollstaendig):
    c = _anmelden(app, vollstaendig["org"])
    sid = vollstaendig["sid"]
    r = _post(c, f"/interview/{sid}/abschluss", {"aktion": "pruefen"})
    assert r.status_code == 200
    bericht = r.get_json()["abschluss"]
    assert bericht["bereit"] and not bericht["blocker"]
    assert "keine Prüfung" in bericht["hinweis"]
    revision = r.get_json()["revision"]

    alt = _post(c, f"/interview/{sid}/abschluss", {"aktion": "fertigstellen", "revision": revision - 1})
    assert alt.status_code == 409
    assert app.interview_service.get_session(sid).pia_status != "fertiggestellt"

    ok = _post(c, f"/interview/{sid}/abschluss", {"aktion": "fertigstellen", "revision": revision})
    assert ok.status_code == 200 and ok.get_json()["pia_status"] == "fertiggestellt"


def test_at25_entwurf_mit_blockern_laesst_sich_nicht_fertigstellen(app, entwurf):
    c = _anmelden(app, entwurf["org"])
    sid = entwurf["sid"]
    bericht = _post(c, f"/interview/{sid}/abschluss", {"aktion": "pruefen"}).get_json()["abschluss"]
    assert not bericht["bereit"] and bericht["blocker"]
    r = _post(c, f"/interview/{sid}/abschluss", {"aktion": "fertigstellen"})
    assert r.status_code == 409
    assert app.interview_service.get_session(sid).pia_status != "fertiggestellt"


def test_at21_aenderung_nach_fertigstellung_setzt_den_status_zurueck(app, vollstaendig):
    d, sid = vollstaendig["d"], vollstaendig["sid"]
    d.abschluss(sid, "fertigstellen")
    assert app.interview_service.get_session(sid).pia_status == "fertiggestellt"
    z = d.zustand.lade(sid, False)
    risiko = next(a for a in z.aussagen if a["status"] == "aktiv"
                  and any(x["abschnitt"] == "risiken" for x in a["ziele"]))
    d.aussage_aktion(sid, risiko["schluessel"], "verwerfen")
    assert app.interview_service.get_session(sid).pia_status == "laufend"


def test_at04_abschlussbericht_nennt_annahmen_und_korrekturen(entwurf):
    d, sid = entwurf["d"], entwurf["sid"]
    bericht = d.abschluss(sid, "pruefen")["abschluss"]
    # F-01: «Support endet Ende 2027» ist eine Annahme, das Enddatum wurde korrigiert.
    assert any("Support" in a for a in bericht["annahmen"])
    assert bericht["korrekturen"] >= 1


# ---- AT19 – Vorlagentreue ------------------------------------------------------ #

def _steuerelement(roh, alias):
    """Text des Inhaltssteuerelements mit diesem Titel (Deckblatt-Felder)."""
    from lxml import etree
    w = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    with zipfile.ZipFile(io.BytesIO(roh)) as z:
        baum = etree.fromstring(z.read("word/document.xml"))
    for sdt in baum.iter(w + "sdt"):
        a = sdt.find(f"{w}sdtPr/{w}alias")
        if a is not None and a.get(w + "val") == alias:
            return "".join(t.text or "" for t in sdt.find(w + "sdtContent").iter(w + "t"))
    return None


def test_at20_deckblattstatus_folgt_nur_tatsaechlichen_vorgaengen(app, vollstaendig):
    sid = vollstaendig["sid"]
    roh, _ = _erzeuge(app, sid)
    assert _steuerelement(roh, "Dokument Status") == "in Arbeit"
    vollstaendig["d"].abschluss(sid, "fertigstellen")
    roh, _ = _erzeuge(app, sid)
    assert _steuerelement(roh, "Dokument Status") == "fertiggestellt"


def test_at20_protokolle_enthalten_nur_tatsaechliche_vorgaenge(app, vollstaendig):
    roh, _ = _erzeuge(app, vollstaendig["sid"])
    tabellen = [t for t in _tabellen(roh) if t[0][:2] == ["Version", "Name"]]
    aenderung, pruefung, freigabe = tabellen
    # Änderungskontrolle: genau der Versionseintrag der Projektleitung.
    assert [z[1] for z in aenderung[1:]] == ["Kim Muster"]
    # Prüfung und Freigabe haben nicht stattgefunden – kein Name, kein Datum.
    for t in (pruefung, freigabe):
        assert not any(z[1].strip() for z in t[1:])
        assert not any(re.match(r"\d\d\.\d\d\.\d{4}", z[2]) for z in t[1:])


def test_at22_keine_beispiele_und_keine_dokumentbefunde(app, vollstaendig):
    roh, _ = _erzeuge(app, vollstaendig["sid"])
    text = _text(roh)
    assert "Jurist" not in text                     # ausgeblendete Beispielzeile der Vorlage
    assert "Nutzwertanalyse" not in text            # Beispielziel der Vorlage
    with zipfile.ZipFile(io.BytesIO(roh)) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    assert "HTabBeispiel85ptF" not in xml
    assert pruefe_dokument(Document(io.BytesIO(roh))) == []


def test_at19_kapitel5_ueber_neun_monate_mit_fortsetzung(app, vollstaendig):
    roh, answers = _erzeuge(app, vollstaendig["sid"])
    teile = [t for t in _tabellen(roh) if t[0][0] == "Rolle / Person"]
    assert len(teile) == 2
    erste, fortsetzung = teile
    assert erste[0][1] == "Monat 1" and fortsetzung[0][1] == "Monat 10"
    pl = next(z for z in fortsetzung if z[0].startswith("PL"))
    assert pl[1:4] == ["5", "5", "5"] and not any(pl[4:10])
    # Summe über beide Tabellen = Personentage aus Kap. 3.1
    pl1 = next(z for z in erste if z[0].startswith("PL"))
    assert sum(int(x) for x in pl1[1:10] + pl[1:4]) == 60
    assert "Fortsetzung: Monate 10 bis 12" in _text(roh)
    total = next(z for z in erste if z[0] == "Total")
    assert total[1] == "6"


def test_at19_risiken_mit_vorlagennummer_und_risikozahl(app, vollstaendig):
    roh, _ = _erzeuge(app, vollstaendig["sid"])
    risiken = next(t for t in _tabellen(roh) if "Risikobeschreibung" in t[0])
    # python-docx übergeht Zellen in Inhaltssteuerelementen (EW, AG) – daher
    # über den Inhalt statt über die Spaltennummer.
    assert risiken[1][0] == "PR01" and "6" in risiken[1]


def test_at18_die_vorlage_ist_vollstaendig_abgebildet(app, vollstaendig):
    roh, _ = _erzeuge(app, vollstaendig["sid"])
    d = Document(io.BytesIO(roh))
    titel = [p.text.strip() for p in d.paragraphs if p.style.name.lower().startswith(("heading", "h"))]
    text = _text(roh)
    for kapitel in ("Ziel und Zweck des Dokuments", "Referenzierte Dokumente", "Mitgeltende Unterlagen",
                    "Definitionen und Abkürzungen", "Vorgaben, Methoden und Werkzeuge", "Ausgangslage",
                    "Ziele der Phase Initialisierung", "Rahmenbedingungen", "Personalaufwand",
                    "Sachmittel", "Kosten (in CHF inkl. MwSt.)", "Ergebnisse und Termine",
                    "Projektorganisation und Personal", "Kommunikation", "Risiken",
                    "Dokument-Protokoll"):
        assert kapitel in text, kapitel
    termine = next(t for t in _tabellen(roh) if t[0][0] == "Nr." and "Liefertermin" in t[0][2])
    assert len(termine) - 1 == 8
    assert "Geplantes Enddatum der Phase Initialisierung: 31.01.2028" in text
    risiken = next(t for t in _tabellen(roh) if "Risikobeschreibung" in t[0])
    for spalte in ("Risikozahl", "Massnahmen", "Verantwortung", "Termin"):
        assert spalte in risiken[0]
    assert len([t for t in _tabellen(roh) if t[0][:2] == ["Version", "Name"]]) == 3
    assert _steuerelement(roh, "Dokument Status") is not None
    assert titel                                   # Überschriften tragen Formatvorlagen


# ---- AT20 – Vorschläge erst nach Übernahme ------------------------------------- #

def test_at20_unbestaetigter_terminvorschlag_steht_nicht_im_dokument(app, entwurf):
    roh, answers = _erzeuge(app, entwurf["sid"])
    termine = next(t for t in _tabellen(roh) if t[0][0] == "Nr." and "Liefertermin" in t[0][2])
    assert not any(re.match(r"\d\d\.\d\d\.\d{4}", z[2]) for z in termine[1:])
    # … aber als offener Punkt im Anhang des Entwurfs.
    offene = next(t for t in _tabellen(roh) if t[0] == ["Punkt", "Art", "Zustand"])
    assert any("Vorschlag Terminplan" in z[0] and z[2] == "nicht bestätigt" for z in offene[1:])


def test_at20_vorschlag_folgt_einer_korrigierten_grundlage(entwurf):
    """F-01 korrigiert das Enddatum; der Terminvorschlag rechnet mit dem neuen."""
    z = entwurf["d"].zustand.lade(entwurf["sid"], False)
    aktiv = [a for a in z.aussagen if a["thema"] == "Terminplan" and a["status"] == "aktiv"]
    assert len(aktiv) == 1 and "31.03.2027" in aktiv[0]["inhalt"]
    assert any(a["thema"] == "Terminplan" and a["status"] == "ersetzt" for a in z.aussagen)


def test_at20_verworfener_vorschlag_kommt_nicht_wieder(app, entwurf):
    d, sid = entwurf["d"], entwurf["sid"]
    z = d.zustand.lade(sid, False)
    termin = next(a for a in z.aussagen if a["thema"] == "Terminplan" and a["status"] == "aktiv")
    d.aussage_aktion(sid, termin["schluessel"], "verwerfen")
    while d.ansicht(sid)["ausstehend"]:
        d.weiter(sid)
    z = d.zustand.lade(sid, False)
    assert not [a for a in z.aussagen if a["thema"] == "Terminplan" and a["status"] == "aktiv"]


# ---- AT22 – Export idempotent, ohne Modell, Vorschau = Export --------------------- #

def test_at22_export_ist_idempotent_und_ohne_modellaufruf(app, vollstaendig):
    d, sid = vollstaendig["d"], vollstaendig["sid"]
    vorher = len(d.llm.aufrufe)
    app.interview_service.llm = _Verboten()
    erster, _ = _erzeuge(app, sid)
    zweiter, _ = _erzeuge(app, sid)
    assert len(d.llm.aufrufe) == vorher
    with zipfile.ZipFile(io.BytesIO(erster)) as a, zipfile.ZipFile(io.BytesIO(zweiter)) as b:
        assert a.read("word/document.xml") == b.read("word/document.xml")


class _Verboten:
    available = True

    def complete(self, *a, **kw):
        raise AssertionError("Beim Herunterladen darf kein Modell aufgerufen werden")


def test_at22_nachweis_ist_aus_dem_zustand_berechnet(app, vollstaendig):
    roh, _ = _erzeuge(app, vollstaendig["sid"])
    nachweis = next(t for t in _tabellen(roh) if t[0] == ["Abschnitt", "Herkunft", "Begründung"])
    zeilen = {z[0]: z for z in nachweis[1:]}
    assert "HERMES PIA (Vorschlag" in zeilen["Ergebnisse und Termine"][1]
    assert zeilen["Ausgangslage"][1] == "Projektleitung (Interview)"
    assert all("kombiniert" not in z[1] for z in nachweis[1:])


def test_at22_vorschau_zeigt_dieselben_daten_wie_der_export(app, vollstaendig):
    sid = vollstaendig["sid"]
    c = _anmelden(app, vollstaendig["org"])
    vorschau = c.get(f"/interview/{sid}/vorschau").get_json()
    roh, _ = _erzeuge(app, sid)
    abschnitte = {a["id"]: a for a in vorschau["abschnitte"]}
    termine = next(t for t in _tabellen(roh) if t[0][0] == "Nr." and "Liefertermin" in t[0][2])
    assert [z[2] for z in termine[1:]] == [r["termin"] for r in abschnitte["termine"]["rows"]]
    risiken = next(t for t in _tabellen(roh) if "Risikobeschreibung" in t[0])
    assert risiken[1][1] == abschnitte["risiken"]["rows"][0]["beschreibung"]


def test_at22_langer_inhalt_bleibt_vollstaendig(app, vollstaendig):
    from tests.regression.adaptiv_hilfen import ops, neu
    d, sid = vollstaendig["d"], vollstaendig["sid"]
    langer = "Die Registerdienste arbeiten mit unterschiedlichen Formularen " * 60
    d.llm.fall["schritte"].append({"aussagen": ops(neu(langer.strip(), ("ausgangslage", {})))})
    d.beitrag(sid, "Noch etwas zur Ausgangslage …", anfrage_id="lang-1")
    while d.ansicht(sid)["ausstehend"]:
        d.weiter(sid)
    roh, _ = _erzeuge(app, sid)
    assert langer.strip()[-80:] in _text(roh)


# ---- AT25 – Ende zu Ende ------------------------------------------------------- #

def test_at25_vollstaendiger_fall_ist_herunterladbar(app, vollstaendig):
    c = _anmelden(app, vollstaendig["org"])
    r = c.get(f"/interview/{vollstaendig['sid']}/download/Registerdienste_PIA_v0.1.docx")
    assert r.status_code == 200
    doc = Document(io.BytesIO(r.data))
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "Offene Punkte" not in text               # nichts mehr offen
    assert "Nachweis – Herkunft der Angaben" in text


def test_at25_entwurf_traegt_seine_luecken_und_wird_vor_der_ausgabe_angehalten(app, entwurf):
    c = _anmelden(app, entwurf["org"])
    url = f"/interview/{entwurf['sid']}/download/Abloesung_PIA_v0.1.docx"
    assert c.get(url).status_code == 409             # Muss-Befunde: Prüfung hält an
    r = c.get(url + "?trotzdem=1")
    assert r.status_code == 200
    text = "\n".join(p.text for p in Document(io.BytesIO(r.data)).paragraphs)
    assert "Offene Punkte" in text


def test_at17_muss_befunde_der_ausgabepruefung_blockieren_den_abschluss(app, entwurf):
    """Profil und Ausgabeprüfung dürfen nicht auseinanderfallen: was der
    Download anhalten würde, steht schon in der Abschlussprüfung."""
    c = _anmelden(app, entwurf["org"])
    bericht = _post(c, f"/interview/{entwurf['sid']}/abschluss",
                    {"aktion": "pruefen"}).get_json()["abschluss"]
    assert any(b["id"].startswith("D-") for b in bericht["blocker"])


# ---- Invarianten, die der vollständige Fall sichtbar gemacht hat --------------- #

def test_invariante_d001_zaehlt_auch_monate_ab_zehn():
    from app.domains.qualitaet.pruefung import pruefe
    a = {"personalaufwand": {"extracted": [{"rolle": "PL", "aufwand": "12"}]},
         "projektorganisation": {"extracted": [
             {"rolle_person": "PL / Kim Muster",
              **{f"monat_{i}": "1" for i in range(1, 13)}}]}}
    assert not [b for b in pruefe(a).befunde if b.regel == "D-001"]


def test_invariante_d007_erkennt_die_gebuendelte_zeile_mit_ihrer_grundlage():
    from app.domains.qualitaet.pruefung import pruefe
    a = {"personalaufwand": {"extracted": [{"rolle": "PL", "aufwand": "60"},
                                           {"rolle": "AG", "aufwand": "12"}]},
         "kosten": {"extracted": [
             {"phase": "Interne Personalkosten (gem. Kap. 3.1) (72 PT × 1000 CHF)", "betrag": "72000"}]}}
    assert not [b for b in pruefe(a).befunde if b.regel == "D-007" and b.gewicht == "Muss"]
    # Gegenprobe: falsche Personentage sind keine Grundlage.
    a["kosten"]["extracted"][0]["phase"] = "Interne Personalkosten (gem. Kap. 3.1) (90 PT × 1000 CHF)"
    assert [b for b in pruefe(a).befunde if b.regel == "D-007" and b.gewicht == "Muss"]


def test_invariante_d053_kennt_die_abkuerzungen_der_vorlage():
    from app.domains.qualitaet.pruefung import pruefe
    a = {"termine": {"extracted": [{"ergebnis": "Studie", "termin": "01.03.2027", "abnahme": "AG",
                                    "pruefmethode": "Review"}]}}
    assert not [b for b in pruefe(a).befunde if b.regel == "D-053"]
