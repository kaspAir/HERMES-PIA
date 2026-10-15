"""Endpunkte des adaptiven Interviews – am selben Blueprint wie die übrigen.

Jeder Endpunkt lädt die Session über `_load_session`: die prüft Anmeldung und
Mandant. Eine Session-ID allein ist keine Zugriffskontrolle (Auftrag 12).
Lesende Endpunkte ändern nichts; schreibende brauchen Schreibrecht.

Alle Antworten sind JSON und tragen die Revision des Zustands. Der Browser
übernimmt nur Antworten, deren Revision nicht älter ist als die angezeigte –
eine verspätete Antwort überschreibt keinen neueren Stand.
"""
from flask import abort, current_app, jsonify, render_template, request

from app.domains.interview.adaptiv.dienst import BeitragFehler
from app.web.auth import permission_required
from app.web.ui_routes import _load_session, _tarife_for_session, bp


def _dienst():
    return current_app.adaptiv_service


def _json():
    daten = request.get_json(silent=True)
    return daten if isinstance(daten, dict) else {}


def _antwort(ansicht, status=200):
    return jsonify(ansicht), status


def render_adaptiv(session):
    """Die Interviewseite im adaptiven Modus – serverseitig vorgerendert mit
    demselben Lesemodell, das die JSON-Endpunkte liefern."""
    from app.domains.generation.pia import ausgabestand as pia_ausgabestand
    from app.domains.qualitaet.service import pruefe_session
    from app.web.ui_routes import _pseudonymisierung_aus
    ansicht = _dienst().ansicht(session.id)
    projekt = current_app.projekt_service.projekt_for_ergebnis(session.ergebnis_id)
    return render_template(
        "interview_adaptiv.html", session=session, ansicht=ansicht, projekt=projekt,
        stt_available=getattr(current_app.transcriber, "available", False),
        llm_available=bool(_dienst().llm),
        # Dieselben Hinweise wie im bisherigen Interview: der Direktmodus muss
        # sichtbar sein, und die Invarianten laufen als Hinweis mit.
        pseudo_aus=_pseudonymisierung_aus(),
        # Geprüft wird der Stand, wie ihn der Download ausgibt (mit dem
        # Versionseintrag des Download-Schritts) – derselbe wie im Abschluss.
        qualitaet=pruefe_session(pia_ausgabestand(session), tarife=_tarife_for_session(session)))


@bp.get("/interview/<int:session_id>/zustand")
@permission_required("read")
def adaptiv_zustand(session_id):
    _load_session(session_id)
    return _antwort(_dienst().ansicht(session_id))


@bp.post("/interview/<int:session_id>/beitrag")
@permission_required("write")
def adaptiv_beitrag(session_id):
    session = _load_session(session_id)
    daten = _json()
    try:
        ansicht = _dienst().beitrag(
            session_id, daten.get("text", ""), anfrage_id=daten.get("anfrage_id"),
            art="korrektur" if daten.get("korrektur_von") else "beitrag",
            tarife=_tarife_for_session(session), korrektur_von=daten.get("korrektur_von"))
    except BeitragFehler as e:
        return jsonify({"fehler": str(e)}), 400
    return _antwort(ansicht)


@bp.post("/interview/<int:session_id>/weiter")
@permission_required("write")
def adaptiv_weiter(session_id):
    session = _load_session(session_id)
    return _antwort(_dienst().weiter(session_id, tarife=_tarife_for_session(session)))


@bp.post("/interview/<int:session_id>/aussage/<schluessel>")
@permission_required("write")
def adaptiv_aussage(session_id, schluessel):
    session = _load_session(session_id)
    try:
        ansicht = _dienst().aussage_aktion(session_id, schluessel, _json().get("aktion"),
                                           tarife=_tarife_for_session(session))
    except BeitragFehler as e:
        return jsonify({"fehler": str(e)}), 400
    return _antwort(ansicht)


@bp.post("/interview/<int:session_id>/bestaetigen")
@permission_required("write")
def adaptiv_sammelbestaetigung(session_id):
    session = _load_session(session_id)
    schluessel = [s for s in (_json().get("schluessel") or []) if isinstance(s, str)]
    return _antwort(_dienst().sammelbestaetigung(session_id, schluessel,
                                                 tarife=_tarife_for_session(session)))


@bp.post("/interview/<int:session_id>/abschluss")
@permission_required("write")
def adaptiv_abschluss(session_id):
    """Abschlussprüfung anzeigen oder fertigstellen. Kein Modellaufruf."""
    session = _load_session(session_id)
    daten = _json()
    from app.domains.generation import pia as pia_dokument
    from app.web.ui_routes import _pruefe_vor_ausgabe
    # Dieselbe Prüfung wie beim Download – über das Dokument, wie es ausgegeben
    # wird (mit dem Versionseintrag, den der Download-Schritt anlegt).
    stand = pia_dokument.ausgabestand(session)
    buf, answers = pia_dokument.erzeuge(stand, current_app.interview_service,
                                        current_app.generation_service, current_app.projekt_service)
    muss = [{"regel": b.regel, "meldung": b.meldung, "fundstelle": b.fundstelle}
            for b in _pruefe_vor_ausgabe(stand, answers, buf).muss]
    try:
        ansicht = _dienst().abschluss(session_id, daten.get("aktion", "pruefen"),
                                      revision=daten.get("revision"), muss_befunde=muss)
    except BeitragFehler as e:
        return jsonify({"fehler": str(e)}), 409
    return _antwort(ansicht)


@bp.post("/interview/<int:session_id>/nachricht/<int:nachricht_id>/verarbeiten")
@permission_required("write")
def adaptiv_erneut_verarbeiten(session_id, nachricht_id):
    """Gespeicherten Beitrag erneut auswerten – als FORMULAR-Aufruf.

    Blockiert die Pseudonymisierung erneut, zeigt die Anwendung ihre
    Entscheidungsseite (Fundstellen, Ersetzen/Fehlalarm) und wiederholt nach
    dem Entscheid genau diesen Aufruf. Danach geht es im Interview weiter;
    die ausstehenden Schritte arbeitet die Seite beim Laden ab.
    """
    from flask import redirect, url_for
    session = _load_session(session_id)
    try:
        _dienst().verarbeite_erneut(session_id, nachricht_id, tarife=_tarife_for_session(session))
    except BeitragFehler as e:
        return jsonify({"fehler": str(e)}), 409
    return redirect(url_for("ui.interview_workspace", session_id=session_id))


@bp.post("/interview/<int:session_id>/umstellen")
@permission_required("write")
def adaptiv_umstellen(session_id):
    """Bestehende Session auf das adaptive Interview umstellen (mit Sicherung)."""
    from flask import redirect, url_for
    session = _load_session(session_id)
    _dienst().umstellen(session_id, tarife=_tarife_for_session(session))
    return redirect(url_for("ui.interview_workspace", session_id=session_id))


@bp.post("/interview/<int:session_id>/zurueck-zum-bisherigen-ablauf")
@permission_required("write")
def adaptiv_rueckfall(session_id):
    """Rückfallweg: Stand vor der Umstellung wiederherstellen."""
    from flask import redirect, url_for
    _load_session(session_id)
    try:
        _dienst().zurueck_zum_bisherigen_ablauf(session_id)
    except BeitragFehler as e:
        return jsonify({"fehler": str(e)}), 409
    return redirect(url_for("ui.interview_workspace", session_id=session_id))


@bp.post("/interview/<int:session_id>/thema/<int:thema_id>")
@permission_required("write")
def adaptiv_thema(session_id, thema_id):
    _load_session(session_id)
    return _antwort(_dienst().thema_bewerten(session_id, thema_id, bool(_json().get("passt"))))


@bp.post("/interview/<int:session_id>/rueckmeldung")
@permission_required("write")
def adaptiv_rueckmeldung(session_id):
    _load_session(session_id)
    art = _json().get("art")
    if art not in ("frage_unklar", "schon_beantwortet", "falsch_verstanden",
                   "falsch_zugeordnet", "rag_unpassend"):
        return jsonify({"fehler": "Unbekannte Rückmeldung"}), 400
    return _antwort(_dienst().rueckmeldung(session_id, art, bezug=_json().get("bezug")))


@bp.get("/interview/<int:session_id>/quelle/<int:thema_id>")
@permission_required("read")
def adaptiv_quelle(session_id, thema_id):
    """Die tatsächlich verwendeten Passagen eines RAG-Themas.

    Nur die gespeicherten Auszüge dieser Session – und je Passage nochmals die
    Mandantenprüfung über den Korpus, falls der Volltext nachgeladen wird.
    """
    session = _load_session(session_id)
    z = _dienst().zustand.lade(session_id, mit_nachrichten=False)
    thema = next((t for t in z.themen if t["id"] == thema_id), None)
    if thema is None:
        abort(404)
    org = session.org_id          # Mandant der SESSION – auch für den Betreiber
    rag = current_app.rag_service
    quellen = []
    for q in thema["quellen"]:
        eintrag = {k: q.get(k) for k in ("chunk_id", "abschnitt", "auszug", "methodenversion",
                                          "methodenversion_herkunft", "korpus_version")}
        # Projektname des Vergleichsprojekts wird nicht angezeigt: er könnte
        # Rückschlüsse auf eine andere Organisation erlauben.
        if rag is not None and getattr(rag, "chunk", None) and q.get("chunk_id"):
            if rag.chunk(q["chunk_id"], org_id=org) is None:
                continue
        quellen.append(eintrag)
    return jsonify({"thema": thema["thema"], "regel": thema["regel_id"],
                    "regel_version": thema["regel_version"],
                    "uebertragbarkeit": thema["uebertragbarkeit"],
                    "begruendung": thema["begruendung"], "n_projekte": thema["n_projekte"],
                    "quellen": quellen})


@bp.get("/interview/<int:session_id>/vorschau")
@permission_required("read")
def adaptiv_vorschau(session_id):
    """Dokumentvorschau aus derselben Projektion wie der Export."""
    session = _load_session(session_id)
    return jsonify({"revision": session.revision or 0,
                    "abschnitte": current_app.interview_service.preview_data(session)})
