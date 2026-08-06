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
              vorrang=None):
    """Die Kopfangaben aus Projekt, Interview-Sitzung – und dem PIA.

    ``vorrang`` sind die Angaben aus der Fassung des
    Projektinitialisierungsauftrags, auf der das Dokument beruht. Sie
    **gewinnen**, denn sie folgen derselben Rangfolge wie der Inhalt: wer im
    freigegebenen Word die Projektleitung ändert, hat sie geändert, und ein
    abgeleitetes Dokument, das weiter den alten Namen trägt, widerspricht
    seiner eigenen Grundlage.

    Fehlende Werte bleiben leer – dann lässt der Erzeuger das Feld der
    Vorlage unangetastet, statt es mit einer Erfindung zu füllen.
    """
    vorrang = vorrang or {}

    def von(quelle, *namen):
        for name in namen:
            wert = getattr(quelle, name, None) if quelle is not None else None
            if wert:
                return str(wert)
        return ""

    projektname = von(projekt, "name") or von(session, "project_name")
    projektnummer = von(projekt, "projektnummer") or von(session, "projektnummer")
    projektleiter = vorrang.get("projektleiter") or von(session, "created_by")
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
        "klassifizierung": klassifizierung,
        "autor": autor or projektleiter,
        "projektleiter": projektleiter,
        "auftraggeber": (vorrang.get("auftraggeber")
                         or von(projekt, "auftraggeber")
                         or von(session, "auftraggeber")),
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
    if abschnitte and wissen:
        uebernimm_gemeinsame_kapitel(doc, abschnitte, wissen)
    # Zuletzt: was jetzt noch magenta oder kursiv ist, ist Regieanweisung.
    _ERZEUGER._delete_style(doc, STYLE_HELP)
    _ERZEUGER._delete_style(doc, STYLE_EXAMPLE)
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
