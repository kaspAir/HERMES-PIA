"""Der Projektinitialisierungsauftrag aus dem Stand einer Interview-Sitzung.

EINE Stelle fuer beide Wege: den Download in der Oberflaeche und den
Testlauf. Zwei Stellen hiessen, dass der Testlauf ein anderes Dokument
pruefte als das, welches die Projektleitung bekommt - und dann belegt ein
gruener Testlauf nichts ueber das ausgelieferte Dokument.
"""
import json
from datetime import date


def erzeuge(session, interview_service, generation_service, projekt_service):
    """(Puffer, Antworten) - das fertige .docx und der Stand, aus dem es entstand.

    Prueft NICHT. Die verbindliche Pruefung vor der Ausgabe bleibt beim
    Aufrufer: der Download blockiert bei Muss-Befunden, der Testlauf
    protokolliert sie und laeuft weiter. Beide sollen dasselbe Dokument
    beurteilen, aber nicht dieselbe Folge daraus ziehen.
    """
    svc, gen = interview_service, generation_service
    answers = json.loads(session.answers_json or "{}")
    changelog = json.loads(session.changelog_json or "[]")

    name_part = session.project_name or "Projekt"
    name_display = (f"{name_part} / {session.projektnummer}"
                    if session.projektnummer else name_part)

    # Aus Namen wird kein Geschlecht abgeleitet (Auftrag Abschnitt 10); die
    # Vorlage führt neutrale Bezeichnungen.
    pl_g = ag_g = "u"

    metadata = {
        "projektname":        name_display,
        "projektleiter":      session.created_by or "",
        "auftraggeber":       session.auftraggeber or "",
        "projektleiter_weiblich": pl_g == "w",
        "auftraggeber_weiblich":  ag_g == "w",
        # Volle Geschlechtsangabe (w/m/u) für die geschlechtergerechten Deckblatt-Labels;
        # Autor = erfassende Person = Projektleiter/in.
        "projektleiter_geschlecht": pl_g,
        "auftraggeber_geschlecht":  ag_g,
        "autor_geschlecht":         pl_g,
        "autor":              session.created_by or "",
        "verwaltungseinheit": session.verwaltungseinheit or "",
        "geschaeftsbereich":  session.geschaeftsbereich or "",
        "innenauftragsnummer": session.innenauftragsnummer or "",
        "projektnummer":      session.projektnummer or "",
        "datum":              date.today().strftime("%d.%m.%Y"),
        "version":            session.doc_version or "0.0",
        "status":             "in Arbeit",
        "klassifizierung":    "Nicht klassifiziert",
    }

    # Komplexitätseinschätzung (aus der Ausgangslage-Vertiefung) in den Ausgangslage-
    # Text einfliessen lassen – begründet die abgeleiteten Dauern in Kap. 4.1.
    ausgangslage = answers.get("ausgangslage")
    if isinstance(ausgangslage, dict) and ausgangslage.get("komplexitaet"):
        extracted = ausgangslage.setdefault("extracted", {})
        if isinstance(extracted, dict):
            extracted["text"] = svc.composed_ausgangslage(answers)

    offene = None
    if getattr(session, "modus", None) == "adaptiv":
        # Adaptive Sitzung: alles aus dem gespeicherten Zustand, KEIN
        # Modellaufruf beim Herunterladen. Derselbe Stand ergibt dasselbe
        # Dokument (Auftrag: Export idempotent, Vorschau = Export).
        nachweis = (answers.get("_nachweis") or {}).get("eintraege") or []
        metadata["status"] = dokumentstatus(session)
        metadata["nachweis_einleitung"] = NACHWEIS_ADAPTIV
        offene = _offene_punkte(session, answers)
    else:
        nachweis = svc.build_nachweis(session, answers)

    # Hat das Projekt eine eigene Word-Vorlage? Dann im Format DIESER Vorlage
    # erzeugen (gleiche abgeleitete Struktur wie das Interview), sonst kanonisch.
    methoden_vorlage = None
    projekt = (projekt_service.projekt_for_ergebnis(session.ergebnis_id)
               if session.ergebnis_id else None)
    if projekt is not None:
        methoden_vorlage = projekt_service.resolve_methoden_vorlage(projekt)
    if methoden_vorlage is not None:
        method = svc._effective_method(session)
        buf = gen.generate_into_template(
            methoden_vorlage.data, method, answers, metadata,
            changelog=changelog, nachweis=nachweis, offene_punkte=offene)
    else:
        buf = gen.generate(session.method_id, answers, metadata,
                           changelog=changelog, nachweis=nachweis, offene_punkte=offene)
    return buf, answers


NACHWEIS_ADAPTIV = (
    "Diese Übersicht weist je Kapitel aus, woher die Angaben stammen: aus dem Interview mit der "
    "Projektleitung, aus Vorschlägen von HERMES PIA, die die Projektleitung übernommen hat, oder "
    "aus der Vorbelegung der Vorlage. Sie ist aus dem gespeicherten Interviewstand berechnet. Der "
    "Anhang dient der Nachvollziehbarkeit und kann für die finale Fassung entfernt werden."
)


def dokumentstatus(session):
    """Deckblatt-Status: nur, was tatsächlich geschehen ist.

    «fertiggestellt» erst nach bestandener Abschlussprüfung und ausdrücklicher
    Fertigstellung durch die Projektleitung. «geprüft» und «abgenommen» setzt
    HERMES PIA NIE – das sind Handlungen von Menschen, kein Programmzustand.
    """
    return "fertiggestellt" if getattr(session, "pia_status", None) == "fertiggestellt" else "in Arbeit"


def _offene_punkte(session, answers):
    from app.domains.interview.adaptiv.vollstaendigkeit import bewerte, offene_punkte
    from app.domains.interview.adaptiv.zustand import ZustandService
    z = ZustandService().lade(session.id, mit_nachrichten=False)
    if z is None:
        return None
    return offene_punkte(z.aussagen, bewerte(z.aussagen, answers, z.konflikte), z.konflikte)


def ausgabestand(session):
    """Der Stand, wie ihn der Download ausgibt – als losgelöste Kopie.

    Der Download führt über den Versionsschritt, der einen Eintrag in die
    Änderungskontrolle schreibt. Eine Prüfung VOR diesem Schritt (die
    Abschlussprüfung) muss das Dokument so beurteilen, wie es ausgegeben wird,
    sonst meldet sie «Änderungskontrolle nicht geführt» über einen Auftrag,
    der beim Herunterladen korrekt wäre. Der Eintrag ist vorläufig und wird
    NICHT gespeichert: die Kopie ist kein Datenbankobjekt.
    """
    from types import SimpleNamespace

    from app.domains.interview.service import _bump_version
    werte = {c.name: getattr(session, c.name) for c in session.__table__.columns}
    protokoll = json.loads(werte.get("changelog_json") or "[]")
    if not protokoll:
        neu = _bump_version(werte.get("doc_version") or "0.0", "minor")
        protokoll.append({"version": neu, "name": werte.get("created_by") or "",
                          "datum": date.today().strftime("%d.%m.%Y"),
                          "bemerkungen": "(wird beim Herunterladen eingetragen)"})
        werte["doc_version"] = neu
        werte["changelog_json"] = json.dumps(protokoll, ensure_ascii=False)
    return SimpleNamespace(**werte)
