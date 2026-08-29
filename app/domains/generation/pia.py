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

    pl_g = ag_g = "u"
    if getattr(svc, "llm", None):
        from app.domains.interview.extraction import detect_gender
        pl_g = detect_gender(svc.llm, session.created_by or "")
        ag_g = detect_gender(svc.llm, session.auftraggeber or "")

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
            changelog=changelog, nachweis=nachweis)
    else:
        buf = gen.generate(session.method_id, answers, metadata,
                           changelog=changelog, nachweis=nachweis)
    return buf, answers
