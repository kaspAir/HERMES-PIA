"""Woher das Projektwissen kommt – Interview ODER hochgeladener PIA.

Bisher gab es genau einen Weg: die Interview-Sitzung in HERMES PIA. Wer einen
anderswo geschriebenen, freigabebereiten PIA hochlädt, konnte daraus eine
Präsentation erzeugen – aber keine Rechtsgrundlagenanalyse. Das ist eine
willkürliche Grenze: die Analyse braucht den INHALT, nicht die Herkunft des
Inhalts.

Dieses Modul macht daraus **eine Quelle mit zwei Zuflüssen**. Es liefert immer
dieselbe Form – die Abschnittsstruktur ``{abschnitt: {"extracted": …}}``, die
`Projektwissen` erwartet. Was danach kommt, muss nicht wissen, ob der PIA
diktiert oder hochgeladen wurde.

Der Vorrang ist bewusst so herum: **die Interview-Sitzung schlägt das
Dokument.** Wer in HERMES PIA arbeitet, hat den aktuelleren Stand; ein
hochgeladenes Dokument ist ein Abzug von irgendwann. Gibt es beides, gewinnt
das Lebendige – und wo nur das Dokument da ist, sagt die Herkunft es an.
"""
import json
import logging

log = logging.getLogger("hermes.ergebnisse")

# Abschnitte, die der Dokument-Parser als TEXT liefert; alles andere sind
# Tabellen (Listen von Zeilen). Die Unterscheidung ist der ganze Unterschied
# zwischen {"text": …} und einer Zeilenliste.
_TEXTABSCHNITTE = ("ausgangslage",)


def _als_abschnitt(wert):
    """Ein Parser-Wert in der Form, die `Projektwissen` erwartet."""
    if isinstance(wert, list):
        return {"extracted": wert}
    return {"extracted": {"text": str(wert or "")}}


def aus_dokument(parsed):
    """Aus dem geparsten PIA-Dokument die Abschnittsstruktur.

    ``parsed`` ist die Rückgabe von ``praesentation.parser.parse_pia``. Leere
    Abschnitte werden weggelassen – ein leerer Abschnitt ist keine Aussage,
    und nachgelagerte Schritte sollen «nicht vorhanden» von «leer» trennen
    können.
    """
    raus = {}
    for schluessel in ("ausgangslage", "ziele", "rahmenbedingungen", "termine",
                       "personalaufwand", "sachmittel", "kosten", "risiken",
                       "projektorganisation", "kommunikation",
                       "referenzierte_dokumente", "mitgeltende_unterlagen"):
        wert = (parsed or {}).get(schluessel)
        if not wert:
            continue
        raus[schluessel] = _als_abschnitt(wert)
    return raus


def aus_session(session):
    """Aus der Interview-Sitzung die Abschnittsstruktur."""
    roh = getattr(session, "answers_json", None)
    if not roh:
        return {}
    try:
        return json.loads(roh)
    except ValueError:
        log.warning("answers_json der Sitzung ist nicht lesbar.")
        return {}


def projektwissen_quelle(session=None, dokument_bytes=None, parser=None):
    """(Abschnitte, Herkunft) – die Sitzung schlägt das Dokument.

    ``herkunft`` ist ``"interview"``, ``"dokument"`` oder ``""``. Sie wird
    mitgeführt, damit das erzeugte Ergebnis sagen kann, worauf es beruht –
    ein Abzug von irgendwann ist etwas anderes als der laufende Stand.
    """
    abschnitte = aus_session(session) if session is not None else {}
    if abschnitte:
        return abschnitte, "interview"
    if dokument_bytes and parser is not None:
        try:
            return aus_dokument(parser(dokument_bytes)), "dokument"
        except Exception as e:      # noqa: BLE001 – ein kaputtes Dokument darf
            log.warning("Hochgeladener PIA nicht lesbar: %s", e)   # nichts umwerfen
            return {}, ""
    return {}, ""
