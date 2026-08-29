"""Der gemeinsame Kopf jedes HERMES-Dokuments.

Jedes Ergebnis – Projektinitialisierungsauftrag, Rechtsgrundlagenanalyse,
Checkliste, Liste Projektentscheide Steuerung – beginnt gleich: Titel mit
Projektname und -nummer, die Metadatentabelle (Bearbeitungsdatum, Version,
Status, Klassifizierung, Autor/-in, Projektleiter/in, Auftraggeber/in,
Verwaltungseinheit, Geschäftsbereich, Innenauftragsnr., Projektnummer), und
danach die Kapitel 0.2 bis 0.5, die für alle Dokumente eines Projekts
dieselben sind.

Das ist der Grund für dieses Modul: **es passiert bei jedem Dokument.** Wer
es je Dokument neu schreibt, schreibt es je Dokument neu falsch. Der Kopf
gehört einmal gebaut und überall benutzt.

**Was hier NICHT entschieden wird.** Das Modul füllt, was ihm gereicht wird.
Es holt keine Daten, es rät keine Namen, und wo ein Wert fehlt, bleibt das
Feld der Vorlage stehen, statt mit einer Erfindung überschrieben zu werden.

**Hilfstexte verschwinden.** Die Vorlage bringt magentafarbene Platzhalter und
kursive Hinweise mit («Diese Tabelle bei Bedarf anpassen vor Verwendung»).
Sie gehören in die Vorlage, nicht in ein fertiges Dokument – jemand druckt es
sonst mit Regieanweisungen aus.
"""
from app.domains.generation.service import (
    STYLE_EXAMPLE, STYLE_HELP, GenerationService,
)

# Kapitel, die jedes Dokument eines Projekts gleich führt. Die Reihenfolge
# entspricht der HERMES-Vorlage.
GEMEINSAME_KAPITEL = (
    "referenzierte_dokumente",     # 0.2
    "mitgeltende_unterlagen",      # 0.3
    "definitionen",                # 0.4
    "vorgaben_methoden",           # 0.5
)

# Die Kopfarbeit hängt nicht an einer Methode – sie ist für jedes Dokument
# dieselbe. Deshalb genügt hier ein Erzeuger ohne Methodenverzeichnis.
_ERZEUGER = GenerationService(None)


def metadaten(projekt=None, session=None, version="", status="in Arbeit",
              datum="", autor="", klassifizierung="Nicht klassifiziert",
              vorrang=None, erkenne_geschlecht=None):
    """Die Kopfangaben aus Projekt, Interview-Sitzung – und dem PIA.

    ``vorrang`` sind die HINTERLEGTEN Kopfdaten des Projekts. Sie gewinnen,
    denn sie sind die einzigen, die ein Mensch bestätigt hat – eine
    Namensschreibweise oder eine Anrede ist nichts, was eine Freigabe
    beschliesst. Weicht ein hochgeladenes Dokument ab, führt das zum
    Abgleich mit Rückfrage, nicht zum stillen Überschreiben.

    (Eine frühere Fassung liess die Angaben aus dem Dokument gewinnen. Das
    war richtig, solange es keine gepflegte Ablage gab: irgendeine Quelle
    musste führen, und die geprüfte Fassung war die bessere. Mit einem
    bestätigten Datensatz ist der bestätigte Wert der bessere.)

    Fehlende Werte bleiben leer – dann lässt der Erzeuger das Feld der
    Vorlage unangetastet, statt es mit einer Erfindung zu füllen.
    """
    vorrang = vorrang or {}
    # Ist die Anrede hinterlegt, wird sie NICHT neu geschätzt: ein gepflegter
    # Wert schlägt eine Vermutung, und jede Schätzung kostet einen
    # Modellaufruf mit dem Namen als Eingabe.
    _hinterlegt = {
        "projektleiter": vorrang.get("projektleiter_anrede"),
        "auftraggeber": vorrang.get("auftraggeber_anrede"),
    }

    # Die Vorlage führt Doppelformen: «Projektleiter/in», «Autor/-in»,
    # «Auftraggeber/in». Ist die Person bekannt, gehört die passende Form
    # dorthin – wer namentlich dasteht, soll auch richtig angesprochen werden.
    # Bleibt das Geschlecht unklar, bleibt die Doppelform der Vorlage stehen;
    # geraten wird nicht.
    _bekannt = {}

    def geschlecht(name, rolle=None):
        gepflegt = _hinterlegt.get(rolle)
        if gepflegt in ("w", "m", "u"):
            return gepflegt
        if not name or erkenne_geschlecht is None:
            return "u"
        # Je Name nur EINE Abfrage – sie kostet einen Modellaufruf.
        if name not in _bekannt:
            _bekannt[name] = erkenne_geschlecht(name) or "u"
        return _bekannt[name]

    def von(quelle, *namen):
        for name in namen:
            wert = getattr(quelle, name, None) if quelle is not None else None
            if wert:
                return str(wert)
        return ""

    projektname = von(projekt, "name") or von(session, "project_name")
    projektnummer = von(projekt, "projektnummer") or von(session, "projektnummer")
    projektleiter = vorrang.get("projektleiter") or von(session, "created_by")
    auftraggeber = (vorrang.get("auftraggeber") or von(projekt, "auftraggeber")
                    or von(session, "auftraggeber"))
    verfasser = autor or projektleiter
    return {
        # Der Titel führt beides – so heisst das Feld in der Vorlage. Steht er
        # schon zusammengesetzt im PIA, wird er nicht neu gebaut.
        "projektname": (vorrang.get("projektname")
                        or (f"{projektname} / {projektnummer}"
                            if projektname and projektnummer else projektname)),
        "projektnummer": projektnummer,
        "datum": datum,
        "version": version,
        "status": status,
        "klassifizierung": vorrang.get("klassifizierung") or klassifizierung,
        "autor": verfasser,
        "projektleiter": projektleiter,
        "auftraggeber": auftraggeber,
        # Die Anrede folgt der Person, nicht der Rolle.
        "projektleiter_geschlecht": geschlecht(projektleiter, "projektleiter"),
        "auftraggeber_geschlecht": geschlecht(auftraggeber, "auftraggeber"),
        # Der Autor ist die erfassende Person – in aller Regel die Projektleitung.
        "autor_geschlecht": geschlecht(
            verfasser, "projektleiter" if verfasser == projektleiter else None),
        # Die Vorlage prüft ausserdem diese beiden Kurzformen.
        "projektleiter_weiblich": geschlecht(projektleiter, "projektleiter") == "w",
        "auftraggeber_weiblich": geschlecht(auftraggeber, "auftraggeber") == "w",
        "verwaltungseinheit": (vorrang.get("verwaltungseinheit")
                               or von(projekt, "verwaltungseinheit")
                               or von(session, "verwaltungseinheit")),
        "geschaeftsbereich": (vorrang.get("geschaeftsbereich")
                              or von(projekt, "geschaeftsbereich")
                              or von(session, "geschaeftsbereich")),
        "innenauftragsnummer": (von(projekt, "innenauftragsnummer")
                                or von(session, "innenauftragsnummer")),
    }


def fuelle(doc, angaben, abschnitte=None, wissen=None):
    """Kopf, gemeinsame Kapitel und Hilfstexte – in dieser Reihenfolge.

    ``abschnitte``: die Abschnittsbeschreibungen aus ``method.yaml`` (für die
    Spalten der Kapitel 0.2–0.5). ``wissen``: die Abschnittsdaten des Projekts.
    Fehlt eines von beiden, bleiben die Kapitel wie in der Vorlage.
    """
    _ERZEUGER._fill_cover(doc, angaben or {})
    _ERZEUGER._fill_headers(doc, angaben or {})
    fuelle_aenderungskontrolle(doc, angaben or {})
    if abschnitte and wissen:
        uebernimm_gemeinsame_kapitel(doc, abschnitte, wissen)
    # Zuletzt: was jetzt noch magenta oder kursiv ist, ist Regieanweisung.
    _ERZEUGER._delete_style(doc, STYLE_HELP)
    _ERZEUGER._delete_style(doc, STYLE_EXAMPLE)
    return doc


def fuelle_aenderungskontrolle(doc, angaben):
    """Die erste Zeile der Änderungskontrolle – Fassung, Name, Datum.

    Beim Projektinitialisierungsauftrag schreibt der Erzeuger diese Tabelle aus
    dem Änderungsprotokoll. Die abgeleiteten Ergebnisse haben kein solches
    Protokoll und liessen die Zeile deshalb stehen, wie die Vorlage sie bringt:
    «0.1 | | tt.mm.jjjj». Gemessen an drei echten Dokumenten – Rechtsgrundlagen-
    analyse, Checkliste, Liste Projektentscheide – stand dort in allen dreien
    der Platzhalter. Eine Änderungskontrolle ohne Datum kontrolliert nichts.

    Die Tabellen für Prüfung und Freigabe bleiben unangetastet: sie werden
    erst bei Prüfung bzw. Freigabe ausgefüllt, und ihr «tt.mm.jjjj» ist dort
    kein Mangel, sondern der richtige Zustand.
    """
    from app.domains.freigabe.dokumente import (
        W_TR, _row_cells, _set_tc_text, _tc_text)
    from app.domains.generation.service import W, _p_text, _tag

    # NICHT ueber `_tabelle_nach`: das verlangt eine Ueberschriften-
    # Formatvorlage. In den abgeleiteten Ergebnissen steht «Aenderungskontrolle»
    # als NORMALER Absatz - der Aufruf lief still ins Leere, und der Platzhalter
    # blieb stehen. Hier zaehlt der Text, nicht die Formatvorlage.
    tabelle, treffer = None, False
    for el in doc.element.body:
        if _tag(el) == "p":
            text = (_p_text(el) or "").strip().lower()
            if text:
                treffer = "nderungskontrolle" in text or "nderungsprotokoll" in text
        elif _tag(el) == "tbl" and treffer:
            tabelle = el
            break
    if tabelle is None:
        return doc
    from datetime import date

    # Das Datum faellt NIE aus: eine Aenderungskontrolle ohne Datum kontrolliert
    # nichts, und der Platzhalter der Vorlage bliebe stehen.
    werte = [str(angaben.get("version") or "0.1"),
             str(angaben.get("autor") or angaben.get("projektleiter") or ""),
             str(angaben.get("datum") or f"{date.today():%d.%m.%Y}")]
    for zeile in tabelle:
        if zeile.tag != W_TR:
            continue
        zellen = _row_cells(zeile)
        if len(zellen) < 3:
            continue
        # Die Kopfzeile nicht überschreiben.
        if _tc_text(zellen[0]).strip().lower().startswith("version"):
            continue
        for zelle, wert in zip(zellen, werte):
            # Auch ein LEERER Wert wird geschrieben: sonst bliebe der
            # Platzhalter der Vorlage stehen und behauptete etwas.
            _set_tc_text(zelle, wert)
        break
    return doc


def uebernimm_gemeinsame_kapitel(doc, abschnitte, wissen):
    """Kapitel 0.2 bis 0.5 aus dem Projektwissen – dieselben Daten wie im PIA.

    Diese Angaben sind bereits erhoben; sie ein zweites Mal zu erfragen wäre
    eine Zumutung, sie wegzulassen eine Lücke.
    """
    from app.domains.freigabe.dokumente import _tabelle_nach

    nach_id = {a.get("id"): a for a in abschnitte or []}
    for kapitel in GEMEINSAME_KAPITEL:
        abschnitt = nach_id.get(kapitel)
        if abschnitt is None:
            continue
        zeilen = ((wissen or {}).get(kapitel) or {}).get("extracted")
        if not isinstance(zeilen, list) or not zeilen:
            continue
        tbl = _tabelle_nach(doc, abschnitt.get("title", ""))
        if tbl is None:
            continue
        _ERZEUGER._fill_table(tbl, abschnitt, zeilen)
