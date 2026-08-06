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

**Der Vorrang folgt der Verbindlichkeit, nicht der Aktualität.** Das
freigegebene Dokument schlägt das freigabebereite, und beide schlagen die
Interview-Sitzung. Der Grund ist fachlich: Was hochgeladen wird, ist die
Fassung, die durch Prüfung und Freigabe gegangen ist – und sie kann
ausserhalb von HERMES PIA überarbeitet worden sein. Das ist der Normalfall,
nicht die Ausnahme. Die Interview-Sitzung ist der Arbeitsstand; ein
abgeleitetes Ergebnis muss auf dem beruhen, was gilt, nicht auf dem, woran
gerade gearbeitet wird.

(Eine frühere Fassung dieses Moduls hatte den Vorrang umgekehrt – mit dem
Argument, das Interview sei aktueller. Aktueller ist nicht dasselbe wie
massgeblich.)
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


# Die Dokumentarten in absteigender VERBINDLICHKEIT. Die Reihenfolge ist die
# fachliche Rangfolge, nicht die zeitliche: freigegeben schlaegt
# freigabebereit, und beide schlagen den Arbeitsstand im Interview.
DOKUMENTARTEN = ("freigegeben", "freigabe")

HERKUNFT_TEXT = {
    "freigegeben": "freigegebenes Dokument",
    "freigabe": "freigabebereites Dokument",
    "interview": "Arbeitsstand im Interview",
}


# Kopfangaben, die JEDES Dokument eines Projekts traegt. Sie stehen im PIA in
# der Metadatentabelle des Deckblatts - nicht in einem Abschnitt, weshalb
# `aus_dokument` sie bewusst weglaesst. Fuer den gemeinsamen Dokumentenkopf
# werden sie trotzdem gebraucht, und zwar aus DERSELBEN Fassung wie der
# Inhalt: wer im freigegebenen Word die Projektleitung aendert, hat sie
# geaendert - jedes abgeleitete Dokument muss den neuen Namen tragen.
KOPFANGABEN = ("projektname", "projektleiter", "auftraggeber",
               "verwaltungseinheit", "geschaeftsbereich", "version")


def kopfangaben_aus_dokument(parsed):
    """Die Kopfangaben aus dem geparsten PIA - leere Werte fallen weg."""
    raus = {}
    for schluessel in KOPFANGABEN:
        wert = (parsed or {}).get(schluessel)
        if wert:
            raus[schluessel] = str(wert).strip()
    return raus


def quelle(session=None, dokumente=None, parser=None):
    """(Abschnitte, Kopfangaben, Herkunft) - das VERBINDLICHSTE gewinnt.

    Wie `projektwissen_quelle`, liefert aber zusaetzlich die Kopfangaben aus
    demselben Dokument. Inhalt und Namen duerfen nicht auseinanderlaufen.
    """
    dokumente = dokumente or {}
    for art in DOKUMENTARTEN:
        rohdaten = dokumente.get(art)
        if not rohdaten or parser is None:
            continue
        try:
            geparst = parser(rohdaten)
            abschnitte = aus_dokument(geparst)
        except Exception as e:      # noqa: BLE001
            log.warning("Hochgeladener PIA (%s) nicht lesbar: %s", art, e)
            continue
        if abschnitte:
            return abschnitte, kopfangaben_aus_dokument(geparst), art
    abschnitte = aus_session(session) if session is not None else {}
    return (abschnitte, {}, "interview") if abschnitte else ({}, {}, "")


def projektwissen_quelle(session=None, dokumente=None, parser=None):
    """(Abschnitte, Herkunft) – das VERBINDLICHSTE Vorhandene gewinnt.

    ``dokumente``: {art: bytes}, etwa {"freigegeben": …, "freigabe": …}.
    ``herkunft`` ist eine der Dokumentarten, ``"interview"`` oder ``""`` – sie
    wird mitgeführt, damit das erzeugte Ergebnis sagen kann, worauf es beruht.
    """
    dokumente = dokumente or {}
    for art in DOKUMENTARTEN:
        rohdaten = dokumente.get(art)
        if not rohdaten or parser is None:
            continue
        try:
            abschnitte = aus_dokument(parser(rohdaten))
        except Exception as e:      # noqa: BLE001 – ein kaputtes Dokument darf
            log.warning("Hochgeladener PIA (%s) nicht lesbar: %s", art, e)
            continue                # nichts umwerfen, aber auch nichts erfinden
        if abschnitte:
            return abschnitte, art
    abschnitte = aus_session(session) if session is not None else {}
    return (abschnitte, "interview") if abschnitte else ({}, "")
