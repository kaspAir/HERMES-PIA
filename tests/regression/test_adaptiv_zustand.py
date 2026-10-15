"""Gemeinsamer Zustand, Verträge und Projektion des adaptiven Interviews.

Zugeordnete Akzeptanzfälle (Auftrag Abschnitt 14): AT01, AT03, AT04, AT05,
AT06, AT07, AT17, AT20, AT21. Das Modell ist ein Double – geprüft wird das
Verhalten des Codes, nicht die Interviewqualität eines echten Modells.
"""
import json

from app.domains.interview.adaptiv.vertraege import abschnittskatalog, pruefe_aussagen_antwort
from tests.regression.adaptiv_hilfen import (  # noqa: F401 – Fixture
    ModellDouble, app, bis_zur_frage, dienst, neu, neue_session, ops,
)


def _answers(app, sid):
    return json.loads(app.interview_service.get_session(sid).answers_json or "{}")


def _zeilen(answers, abschnitt):
    return (answers.get(abschnitt) or {}).get("extracted") or []


# ---- AT01 – themenübergreifende Antwort -------------------------------------- #

def test_at01_ein_beitrag_beliefert_mehrere_bereiche(app):
    """Anlass, Frist, Ressourcen und ein Risiko in EINEM Beitrag erreichen
    die passenden Kapitel – ohne dass danach nach ihnen gefragt wird."""
    sid = neue_session(app)
    modell = ModellDouble(aussagen=[ops(
        neu("Die Fachanwendung für Baubewilligungen erfasst Gesuche doppelt",
            ("ausgangslage", {})),
        neu("Die Initialisierung soll am 2. November 2026 beginnen",
            ("eckdaten", {"start_initialisierung": "2026-11-02"})),
        neu("Als Projektleitung rechne ich mit 20 Personentagen",
            ("personalaufwand", {"rolle": "PL", "aufwand": "20"}), art="schaetzung"),
        neu("Fachpersonen der Bewilligungsabteilung sind knapp verfügbar",
            ("risiken", {"beschreibung": "Fachpersonen sind knapp verfügbar",
                         "ew": "Hoch", "ag": "Mittel"})),
    )])
    d = dienst(app, modell)
    d.starte(sid)
    d.beitrag(sid, "Bei uns werden Gesuche doppelt erfasst. Start ist der 2. November 2026. "
                   "Ich rechne mit 20 PT. Die Fachleute sind knapp.", anfrage_id="a1")
    a = _answers(app, sid)
    assert "doppelt" in a["ausgangslage"]["extracted"]["text"]
    pl = next(z for z in _zeilen(a, "personalaufwand") if z["rolle"] == "PL")
    assert pl["aufwand"] == "20"
    risiko = _zeilen(a, "risiken")[0]
    assert risiko["ew"] == "Hoch = 3" and risiko["risikozahl"] == "6"
    assert app.interview_service.get_session(sid).start_datum == "2026-11-02"

    # Keine redundante Standardfrage: der Planer wählt weder den Anlass noch
    # das Risiko noch den Start erneut.
    ansicht = bis_zur_frage(d, sid)
    assert ansicht["frage"]["ziel"] not in ("start", "K-AL-1", "K-RI-1", "K-ECK-START")


# ---- AT03 – Idee und Entscheid ----------------------------------------------- #

def test_at03_idee_wird_nicht_zum_entscheid(app):
    sid = neue_session(app)
    modell = ModellDouble(aussagen=[
        ops(neu("Wir brauchen eine neue Fachanwendung", ("ausgangslage", {}), entscheid="unklar")),
        ops({"op": "entscheid", "aussage": "A-0001", "wert": "entscheid"}),
    ])
    d = dienst(app, modell)
    d.starte(sid)
    d.beitrag(sid, "Wir brauchen eine neue Fachanwendung.", anfrage_id="b1")
    ansicht = bis_zur_frage(d, sid)
    assert ansicht["frage"]["aktion"] == "rueckspiegeln"
    assert ansicht["frage"].get("unterart") == "entscheid"

    d.beitrag(sid, "Ja, das ist vom Amtsleiter so entschieden.", anfrage_id="b2")
    ansicht = bis_zur_frage(d, sid)
    # Ein bestätigter Entscheid wird nicht endlos neu hinterfragt.
    assert not (ansicht["frage"]["aktion"] == "rueckspiegeln"
                and ansicht["frage"]["ziel"] == "A-0001")


# ---- AT04 – Unsicherheit ------------------------------------------------------- #

def test_at04_unbestaetigtes_bleibt_unbestaetigt(app):
    sid = neue_session(app)
    modell = ModellDouble(aussagen=[ops(
        neu("Der Hersteller stellt den Support angeblich Ende 2027 ein",
            ("ausgangslage", {}), art="annahme"),
        neu("Die Initialisierung soll Ende November abgeschlossen sein",
            ("eckdaten", {"ende_initialisierung": "Ende November"})),
    )])
    d = dienst(app, modell)
    d.starte(sid)
    ansicht = d.beitrag(sid, "Habe gehört, der Support endet Ende 2027. Fertig sein "
                             "sollten wir Ende November.", anfrage_id="c1")
    a = _answers(app, sid)
    assert "(unbestätigt)" in a["ausgangslage"]["extracted"]["text"]
    eintrag = next(e for g in ansicht["erkannt"]["gruppen"] for e in g["eintraege"]
                   if "Support" in e["inhalt"])
    assert eintrag["status_text"] == "von Dir genannt – unbestätigt"
    # «Ende November» ohne Jahr bleibt unvollständig – kein stilles Jahr.
    assert a["_eckdaten"]["ende_initialisierung"]["unvollstaendig"] is True
    assert "_enddatum" not in a
    # Ohne Startdatum keine Termine, ohne Kostensatz kein Betrag.
    assert all(z["termin"] == "" for z in _zeilen(a, "termine"))


# ---- AT05 – Korrektur und Konflikt ---------------------------------------------- #

def test_at05_korrektur_ersetzt_nachvollziehbar(app):
    sid = neue_session(app)
    modell = ModellDouble(aussagen=[
        ops(neu("Der Termin Ende März gilt für die Einführung", ("rahmenbedingungen",
            {"vorgaben": "Termin", "beschreibung": "Einführung bis Ende März"}),
            bezug="gesamtvorhaben")),
        ops({"op": "korrektur", "aussage": "A-0001",
             "inhalt": "Der Termin Ende März gilt für die Initialisierung",
             "bezug": "initialisierung",
             "ziele": [{"abschnitt": "eckdaten", "felder": {"ende_initialisierung": "Ende März"}}]}),
    ])
    d = dienst(app, modell)
    d.starte(sid)
    d.beitrag(sid, "Ende März muss die Einführung stehen.", anfrage_id="d1")
    rev1 = app.interview_service.get_session(sid).revision
    d.beitrag(sid, "Der Termin gilt für die Initialisierung, nicht für die Einführung.",
              anfrage_id="d2")
    z = d.zustand.lade(sid)
    alt, neu_ = z.aussage("A-0001"), z.aussage("A-0002")
    assert alt["status"] == "ersetzt" and alt["ersetzt_durch"] == "A-0002"
    assert neu_["status"] == "aktiv" and neu_["bezug"] == "initialisierung"
    assert z.revision > rev1
    # Der Originalbeitrag ist unverändert erhalten.
    assert z.nachrichten[1]["text"] == "Ende März muss die Einführung stehen."
    a = _answers(app, sid)
    assert "ende_initialisierung" in a["_eckdaten"]


def test_at05_widerspruch_bleibt_sichtbar_und_hat_vorrang(app):
    sid = neue_session(app)
    modell = ModellDouble(aussagen=[
        ops(neu("Die Initialisierung dauert drei Monate", ("eckdaten", {"dauer_initialisierung": "3 Monate"})),
            neu("Die Initialisierung dauert sechs Monate", ("eckdaten", {"dauer_initialisierung": "6 Monate"}))),
        ops({"op": "widerspruch", "aussagen": ["A-0001", "A-0002"],
             "beschreibung": "Drei oder sechs Monate Dauer?"}),
    ])
    d = dienst(app, modell)
    d.starte(sid)
    d.beitrag(sid, "Drei Monate. Oder eher sechs.", anfrage_id="e1")
    d.beitrag(sid, "Da habe ich mich widersprochen.", anfrage_id="e2")
    ansicht = bis_zur_frage(d, sid)
    assert ansicht["frage"]["aktion"] == "widerspruch"
    assert ansicht["erkannt"]["konflikte"][0]["status_text"] == "Widerspruch – offen"


# ---- AT06 – Phasengrenze ------------------------------------------------------- #

def test_at06_gesamtbudget_ist_kein_initialisierungsbudget(app):
    sid = neue_session(app)
    modell = ModellDouble(aussagen=[ops(
        neu("Für das Gesamtvorhaben sind 2,4 Mio. CHF vorgesehen",
            ("kosten", {"phase": "Gesamtvorhaben", "betrag": "2400000"}),
            ("ausgangslage", {}), bezug="gesamtvorhaben"),
    )])
    d = dienst(app, modell)
    d.starte(sid)
    d.beitrag(sid, "Insgesamt haben wir 2,4 Millionen budgetiert.", anfrage_id="f1")
    a = _answers(app, sid)
    kosten = " ".join(f"{z.get('phase')} {z.get('betrag')}" for z in _zeilen(a, "kosten"))
    assert "2400000" not in kosten
    assert "2,4 Mio" in a["ausgangslage"]["extracted"]["text"]


# ---- AT07 – Unwissen und Pause --------------------------------------------------- #

def test_at07_weiss_ich_nicht_erzeugt_offenen_punkt_statt_schleife(app):
    sid = neue_session(app)
    modell = ModellDouble(aussagen=[
        ops(neu("Gesuche werden doppelt erfasst", ("ausgangslage", {}))),
        ops({"op": "unbekannt", "thema": "Risiken der Initialisierung",
             "inhalt": "Risiken kann ich noch nicht abschätzen",
             "ziele": [{"abschnitt": "risiken", "felder": {}}]}),
    ])
    d = dienst(app, modell)
    d.starte(sid)
    d.beitrag(sid, "Gesuche werden doppelt erfasst.", anfrage_id="g1")
    d.beitrag(sid, "Risiken? Weiss ich noch nicht.", anfrage_id="g2")
    ansicht = bis_zur_frage(d, sid)
    risiko = next(k for k in ansicht["kriterien"] if k["id"] == "K-RI-1")
    assert risiko["zustand"] == "unbekannt"
    # Nicht dieselbe Frage nochmals: Vorschlag/Untersuchungsauftrag anbieten,
    # oder ein anderer Punkt – nie die Erkundungsfrage zu den Risiken.
    if ansicht["frage"]["ziel"] == "K-RI-1":
        assert ansicht["frage"]["aktion"] == "vorschlag"
    offen = ansicht["erkannt"]["offen"]
    assert any(e["status_text"].startswith("Offene Frage") for e in offen)


def test_at07_wiederaufnahme_verliert_nichts(app):
    sid = neue_session(app)
    modell = ModellDouble(aussagen=[ops(neu("Gesuche werden doppelt erfasst", ("ausgangslage", {})))])
    d = dienst(app, modell)
    d.starte(sid)
    d.beitrag(sid, "Gesuche werden doppelt erfasst.", anfrage_id="h1")
    bis_zur_frage(d, sid)
    vorher = d.ansicht(sid)
    # Neuer Dienst, gleiche Datenbank: wie nach einem Neustart oder Tag später.
    wieder = dienst(app, ModellDouble()).ansicht(sid)
    assert wieder["revision"] == vorher["revision"]
    assert wieder["frage"]["frage"] == vorher["frage"]["frage"]
    assert [m["text"] for m in wieder["nachrichten"]] == [m["text"] for m in vorher["nachrichten"]]


def test_at07_unbeantwortete_frage_wird_nicht_endlos_wiederholt(app):
    from app.domains.interview.adaptiv.planer import naechste_aktion
    from app.domains.interview.adaptiv.vollstaendigkeit import bewerte
    sid = neue_session(app)
    d = dienst(app, ModellDouble(aussagen=[ops(neu("Anlass ist bekannt", ("ausgangslage", {})))]))
    d.starte(sid)
    d.beitrag(sid, "Anlass ist bekannt.", anfrage_id="i1")
    z = d.zustand.lade(sid)
    a = _answers(app, sid)
    erste = naechste_aktion(z.aussagen, z.konflikte, z.themen, bewerte(z.aussagen, a), z.nachrichten)
    # Zwei Systemfragen zum selben Ziel, beide ohne Fortschritt:
    for _ in range(2):
        d.zustand.nachricht(sid, "system", "Frage", art="frage", aktion=erste["aktion"],
                            bezug={"ziel": erste["ziel"]})
    z = d.zustand.lade(sid)
    danach = naechste_aktion(z.aussagen, z.konflikte, z.themen, bewerte(z.aussagen, a), z.nachrichten)
    assert danach["ziel"] != erste["ziel"]
    assert erste["ziel"] in danach["zurueckgestellt"]


# ---- AT17 – echte Vollständigkeit -------------------------------------------------- #

def test_at17_text_vorhanden_ist_nicht_vollstaendig(app):
    sid = neue_session(app)
    modell = ModellDouble(aussagen=[ops(
        neu("Die Studie soll Varianten aufzeigen", ("ziele", {"beschreibung": "Varianten aufzeigen"})),
        neu("Kommunikation braucht es in der Initialisierung keine eigene, der AG ist ohnehin "
            "wöchentlich dabei", ("ausgangslage", {})),
    )])
    d = dienst(app, modell)
    d.starte(sid)
    d.beitrag(sid, "Die Studie soll Varianten aufzeigen.", anfrage_id="j1")
    k = {e["id"]: e for e in d.ansicht(sid)["kriterien"]}
    assert k["K-ZI-1"]["zustand"] == "erfuellt"
    assert k["K-ZI-2"]["zustand"] == "offen"          # Ziel ohne Messgrösse/Priorität
    assert "messgroesse" in k["K-ZI-2"]["details"][0]


def test_at17_begruendet_nicht_anwendbar_erzeugt_keine_schleife(app):
    sid = neue_session(app)
    begr = {"op": "neu", "inhalt": "Keine eigene Kommunikation nötig, der AG ist wöchentlich dabei",
            "art": "benutzerangabe", "quelle": "wortlaut",
            "ziele": [{"abschnitt": "kommunikation", "felder": {}, "nicht_anwendbar": True}]}
    d = dienst(app, ModellDouble(aussagen=[ops(begr)]))
    d.starte(sid)
    d.beitrag(sid, "Kommunikation braucht es keine.", anfrage_id="k1")
    k = {e["id"]: e for e in d.ansicht(sid)["kriterien"]}
    assert k["K-KM-1"]["zustand"] == "nicht_anwendbar"


# ---- AT20 – Vorschlag wird nicht still zum Fakt -------------------------------------- #

def test_at20_systemvorschlag_erst_nach_bestaetigung_im_dokument(app):
    sid = neue_session(app)
    d = dienst(app, ModellDouble())
    d.starte(sid)
    erg = d.zustand.wende_an(sid, [{"op": "systemvorschlag",
                                    "inhalt": "Risiko: Schlüsselpersonen nicht verfügbar",
                                    "ziele": [{"abschnitt": "risiken",
                                               "felder": {"beschreibung": "Schlüsselpersonen nicht verfügbar"}}]}],
                             nachher=d._projektions_hook(d._methode(d._session(sid)), {}))
    assert not _zeilen(_answers(app, sid), "risiken")
    d.sammelbestaetigung(sid, erg.neu)
    assert _zeilen(_answers(app, sid), "risiken")


# ---- AT21 – Fehler und Parallelität ---------------------------------------------------- #

def test_at21_doppelklick_wird_einmal_verarbeitet(app):
    sid = neue_session(app)
    modell = ModellDouble(aussagen=[ops(neu("Anlass X", ("ausgangslage", {}))),
                                    ops(neu("Anlass Y", ("ausgangslage", {})))])
    d = dienst(app, modell)
    d.starte(sid)
    d.beitrag(sid, "Anlass X", anfrage_id="gleich")
    d.beitrag(sid, "Anlass X", anfrage_id="gleich")
    z = d.zustand.lade(sid)
    assert len([m for m in z.nachrichten if m["rolle"] == "benutzer"]) == 1
    assert len(z.aktive) == 1
    assert sum(1 for c in modell.aufrufe if c["art"] == "aussagen") == 1


def test_at21_ungueltige_modellantwort_aendert_nichts(app):
    sid = neue_session(app)
    d = dienst(app, ModellDouble(aussagen=["das ist kein JSON"]))
    d.starte(sid)
    vorher = app.interview_service.get_session(sid).revision
    d.beitrag(sid, "Etwas", anfrage_id="m1")
    s = app.interview_service.get_session(sid)
    assert s.revision == vorher
    z = d.zustand.lade(sid)
    assert z.nachrichten[-1]["text"] == "Etwas"          # Beitrag gesichert
    assert not z.aktive


def test_at21_modellausfall_sichert_den_beitrag(app):
    sid = neue_session(app)
    d = dienst(app, ModellDouble(aussagen=[TimeoutError("zu langsam")]))
    d.starte(sid)
    ansicht = d.beitrag(sid, "Wichtiger Beitrag", anfrage_id="n1")
    assert "gespeichert" in ansicht["fehler"]
    z = d.zustand.lade(sid)
    eingang = [m for m in z.nachrichten if m["rolle"] == "benutzer"][0]
    assert eingang["text"] == "Wichtiger Beitrag" and eingang["status"] == "fehler"


def test_at21_ansicht_aendert_nichts(app):
    """Refresh und lesende Ansichten erzeugen keine neue Frage und keine
    versteckte Zustandsänderung (Auftrag Abschnitt 12)."""
    sid = neue_session(app)
    modell = ModellDouble(aussagen=[ops(neu("Anlass", ("ausgangslage", {})))])
    d = dienst(app, modell)
    d.starte(sid)
    d.beitrag(sid, "Anlass", anfrage_id="o1")
    bis_zur_frage(d, sid)
    eins = d.ansicht(sid)
    aufrufe = len(modell.aufrufe)
    zwei = d.ansicht(sid)
    drei = d.ansicht(sid)
    assert eins["revision"] == zwei["revision"] == drei["revision"]
    assert eins["frage"] == zwei["frage"] == drei["frage"]
    assert len(eins["nachrichten"]) == len(drei["nachrichten"])
    assert len(modell.aufrufe) == aufrufe


def test_at21_veraltete_korrektur_trifft_nicht_die_falsche_aussage(app):
    """Zwei Tabs: Tab 1 korrigiert A-0001, Tab 2 hat noch den alten Stand und
    korrigiert ebenfalls A-0001. Die zweite Korrektur wird verworfen – sie
    überschreibt nicht die neuere."""
    sid = neue_session(app)
    d = dienst(app, ModellDouble(aussagen=[ops(neu("Version A", ("ausgangslage", {})))]))
    d.starte(sid)
    d.beitrag(sid, "Version A", anfrage_id="p1")
    korr = {"op": "korrektur", "aussage": "A-0001", "inhalt": "x", "art": "benutzerangabe",
            "herkunft": "benutzer", "bestaetigt": True, "ziele": [{"abschnitt": "ausgangslage", "felder": {}}]}
    erste = d.zustand.wende_an(sid, [dict(korr, inhalt="Version B")])
    zweite = d.zustand.wende_an(sid, [dict(korr, inhalt="Version C (veraltet)")])
    assert erste.neu and not zweite.neu
    assert zweite.verworfen
    assert d.zustand.lade(sid).aussage("A-0002")["inhalt"] == "Version B"


# ---- Verträge -------------------------------------------------------------------------- #

def test_vertrag_verwirft_erfundenes(app):
    """Unbekannte Abschnitte, Spalten und Auswahlwerte sowie Bezüge auf nicht
    existierende Aussagen werden verworfen – mit Grund, nicht still."""
    katalog = abschnittskatalog(app.method_service.get("hermes_pia"))
    roh = ops(
        neu("x", ("phantasiekapitel", {"a": "b"})),
        neu("y", ("risiken", {"beschreibung": "R", "ew": "sehr hoch", "erfunden": "z"})),
        {"op": "korrektur", "aussage": "A-0099", "inhalt": "z"},
        {"op": "loeschen_alles"},
    )
    erg = pruefe_aussagen_antwort(json.dumps(roh), katalog, {}, {}, {})
    gruende = " ".join(g for _, g in erg.verworfen)
    assert "A-0099" in gruende and "loeschen_alles" in gruende
    risiko = next(o for o in erg.gueltig if o["inhalt"] == "y")
    assert risiko["ziele"][0]["felder"] == {"beschreibung": "R"}   # ew und erfundenes Feld weg
    assert any("kein Auswahlwert" in h for h in risiko["hinweise"])


def test_vertrag_gefolgertes_ist_interpretation(app):
    katalog = abschnittskatalog(app.method_service.get("hermes_pia"))
    erg = pruefe_aussagen_antwort(json.dumps(ops(
        neu("Es handelt sich um eine Ablösung", ("ausgangslage", {}), quelle="gefolgert"))),
        katalog, {}, {}, {})
    o = erg.gueltig[0]
    assert o["art"] == "interpretation" and o["herkunft"] == "system" and o["bestaetigt"] is False


def test_vertrag_belegt_kann_das_modell_nicht_setzen(app):
    """«belegt» setzt nur ein hinterlegter Beleg, nie die Auswertung."""
    katalog = abschnittskatalog(app.method_service.get("hermes_pia"))
    erg = pruefe_aussagen_antwort(json.dumps(ops(neu("x", ("ausgangslage", {}), art="belegt"))),
                                  katalog, {}, {}, {})
    assert erg.gueltig[0]["art"] == "benutzerangabe"
