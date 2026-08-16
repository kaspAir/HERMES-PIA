"""Versionierung von Dokumenten – ein Baustein für ALLE Ergebnisse.

Jedes erzeugte Dokument braucht dasselbe: eine Versionsnummer, ein
Änderungsprotokoll und die Angabe, was sich seit der letzten Ausgabe geändert
hat. Beim Projektinitialisierungsauftrag war das im Interview-Dienst
eingebaut; die Rechtsgrundlagenanalyse hätte es kopieren müssen, die
Schutzbedarfs- und die Beschaffungsanalyse danach ebenso. Beim dritten Mal
wäre es dreimal verschieden.

Dieser Baustein kennt deshalb **kein** Dokument. Er kennt nur einen Vertrag:
Ein *Träger* ist irgendein Objekt mit vier Feldern –

  ``doc_version``          aktuelle Nummer, z. B. ``"0.3"``
  ``changelog_json``       Liste der Einträge als JSON-Text
  ``last_snapshot_json``   Inhalt zum Zeitpunkt der letzten Ausgabe
  ``answers_json``         aktueller Inhalt

– und alles Weitere ist Sache des Aufrufers. Wer speichert, entscheidet der
Aufrufer; dieser Baustein setzt nur die Felder. Das hält ihn frei von
Datenbank- und Sitzungswissen und macht ihn prüfbar ohne beides.

Die Zählweise ist die des PIA und bleibt es: ``minor`` erhöht die zweite
Stelle und setzt die dritte zurück, ``patch`` erhöht die dritte. Aus ``0.1``
wird mit ``minor`` ``0.2``, mit ``patch`` ``0.1.1``.
"""
import json
from datetime import date


def naechste_version(aktuell, art="minor"):
    """Die nächste Nummer. ``art``: ``minor`` (+0.1) oder ``patch`` (+0.0.1)."""
    teile = []
    for stueck in str(aktuell or "0.0").split("."):
        try:
            teile.append(int(stueck))
        except ValueError:
            teile.append(0)
    while len(teile) < 3:
        teile.append(0)
    if art == "minor":
        teile[1] += 1
        teile[2] = 0
    else:
        teile[2] += 1
    return (f"{teile[0]}.{teile[1]}" if teile[2] == 0
            else f"{teile[0]}.{teile[1]}.{teile[2]}")


def _inhalt(eintrag):
    """Der vergleichbare Inhalt eines Abschnitts – Text wie Tabelle.

    Der PIA verglich nur ``extracted.text`` und übersah damit jede Änderung in
    einer Tabelle: eine geänderte Kostenzeile galt als «nichts geändert».
    Hier zählt der ganze Abschnitt.
    """
    if not isinstance(eintrag, dict):
        return json.dumps(eintrag, ensure_ascii=False, sort_keys=True)
    return json.dumps(eintrag.get("extracted"), ensure_ascii=False, sort_keys=True)


def geaenderte_abschnitte(traeger, abschnitte=None):
    """Welche Abschnitte haben sich seit der letzten Ausgabe geändert?

    ``abschnitte``: optionale Liste ``[{id, number, title}]`` für die
    Beschriftung. Fehlt sie, wird die Kennung des Abschnitts verwendet – so
    funktioniert der Baustein auch für Ergebnisse ohne Methodenmodell.
    """
    schnappschuss = json.loads(getattr(traeger, "last_snapshot_json", None) or "{}")
    aktuell = json.loads(getattr(traeger, "answers_json", None) or "{}")
    beschriftung = {a["id"]: a for a in (abschnitte or []) if a.get("id")}

    raus = []
    for sid, eintrag in aktuell.items():
        if str(sid).startswith("_"):        # Nachweisfelder sind kein Inhalt
            continue
        if sid in schnappschuss and _inhalt(schnappschuss[sid]) == _inhalt(eintrag):
            continue
        vorlage = beschriftung.get(sid, {})
        raus.append({"id": sid,
                     "number": vorlage.get("number", ""),
                     "title": vorlage.get("title", sid)})
    if abschnitte:      # in der Reihenfolge des Dokuments, nicht des Zufalls
        rang = {a["id"]: i for i, a in enumerate(abschnitte)}
        raus.sort(key=lambda x: rang.get(x["id"], 10_000))
    return raus


def stand(traeger, abschnitte=None):
    """Aktuelle Version, Änderungsprotokoll und die offenen Änderungen."""
    return {
        "current_version": getattr(traeger, "doc_version", None) or "0.0",
        "changelog": json.loads(getattr(traeger, "changelog_json", None) or "[]"),
        "changed_sections": geaenderte_abschnitte(traeger, abschnitte),
    }


def eintragen(traeger, art="minor", name="", bemerkungen="", heute=None):
    """Setzt die neue Version am Träger und ergänzt das Protokoll.

    Der Aufrufer speichert – dieser Baustein berührt keine Datenbank. Der
    Schnappschuss wird auf den aktuellen Stand gesetzt: ab jetzt gilt alles
    Weitere wieder als Änderung.

    Rückgabe: (neue Version, Änderungsprotokoll).
    """
    neu = naechste_version(getattr(traeger, "doc_version", None), art)
    protokoll = json.loads(getattr(traeger, "changelog_json", None) or "[]")
    protokoll.append({
        "version": neu,
        "name": name or "",
        "datum": (heute or date.today()).strftime("%d.%m.%Y"),
        "bemerkungen": bemerkungen or "",
    })
    traeger.doc_version = neu
    traeger.changelog_json = json.dumps(protokoll, ensure_ascii=False)
    traeger.last_snapshot_json = getattr(traeger, "answers_json", None) or "{}"
    return neu, protokoll
