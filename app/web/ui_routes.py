import base64
import io
import json
import logging
from datetime import date, datetime

from flask import (
    Blueprint, abort, current_app, g, jsonify, redirect, render_template, request,
    send_file, url_for,
)

from app.domains.auth.models import ROLE_MEMBER, ROLE_ORG_ADMIN, ROLE_SUPER_ADMIN
from app.domains.generation import pia as pia_dokument
from app.domains.llm.entscheid import entscheide
from app.domains.llm.kontext import loese_kontext, projekt_schluessel, setze_kontext
from app.domains.llm.errors import (
    PseudoAnbieterFehler,
    PseudoAntwortUnlesbar,
    PseudoUnerwarteteAntwort,
    PseudoKeinSchluessel,
    PseudoKontextFehlt,
    PseudoNichtErreichbar,
    PseudonymisierungBlockiert,
    RueckersetzungUnvollstaendig,
)
from app.domains.qualitaet.service import (
    fachpruefung_schritt, letzte_fachpruefung, pruefe_session,
    starte_fachpruefung, widerspruch,
)
from app.domains.stt.kontext import kontext_fuer_diktat
from app.domains.method.template_structure import (
    ZIEL_GENERISCH,
    ZIEL_UNVERAENDERT,
    build_derived_method,
    propose_mapping,
)
from app.web.auth import (
    current_user, login_required, login_user, logout_user, permission_required,
    roles_required,
)

from app.domains.projekt.naechster_schritt import begruessung, naechster_schritt

bp = Blueprint("ui", __name__)
log = logging.getLogger("hermes.web")


def _pseudonymisierung_aus():
    """Laeuft die Anwendung ohne Pseudonymisierung (Direktmodus)?

    Bewusst aus der KONFIGURATION beantwortet und nicht aus der Client-Instanz:
    die Frage ist eine Eigenschaft des Deployments, nicht eines Objekts. Vorher
    stand dieselbe getattr-Abfrage an drei Stellen - und driftete auseinander,
    sobald eine davon einen anderen Client sah.
    """
    return (bool(current_app.config.get("PSEUDO_UMGEHEN"))
            and bool(current_app.config.get("ANTHROPIC_API_KEY"))
            and not (current_app.config.get("PSEUDO_BASIS_URL") or "").strip())


@bp.get("/health")
def health():
    """Betriebszustand – auch, ob die Pseudonymisierungsschicht steht.

    Ohne sie formuliert HERMES PIA nichts; das muss von aussen prüfbar sein,
    ohne sich durch ein Interview zu klicken. Nennt bewusst KEINE Geheimnisse.
    """
    llm = current_app.interview_service.llm
    direkt = _pseudonymisierung_aus()
    return jsonify({
        "status": "ok",
        "service": "hermes-pia",
        "pseudonymisierung": {
            # 'aus' = Direktmodus: die Aufrufe gehen OHNE Pseudonymisierung raus.
            "modus": "direkt (AUS)" if direkt else ("aktiv" if llm else "kein LLM"),
            "konfiguriert": bool(llm) and not direkt,
            "basis_url": current_app.config.get("PSEUDO_BASIS_URL", "") or None,
            "anwendung": current_app.config.get("PSEUDO_ANWENDUNG", ""),
            # Ohne Dienst laeuft die Anwendung rein deterministisch: keine
            # Formulierung, keine Extraktion, keine Komplexitaetseinschaetzung.
            "textformulierung_aktiv": bool(llm),
        },
    })


# ---- Mandantentrennung: Session laden + Zugriff prüfen ---------------- #

def _load_session(session_id):
    """Lädt eine PIA und stellt sicher, dass sie zur Organisation des
    angemeldeten Benutzers gehört (Super-Admin darf alle)."""
    session = current_app.interview_service.get_session(session_id)
    if not session:
        abort(404)
    user = current_user()
    if user is None:
        abort(401)
    if not user.is_super_admin and session.org_id != user.org_id:
        abort(403)
    return session


def _load_projekt(projekt_id):
    """Lädt ein Projekt und prüft die Mandanten-Zugehörigkeit (Super-Admin: alle)."""
    projekt = current_app.projekt_service.get_projekt(projekt_id)
    if not projekt:
        abort(404)
    user = current_user()
    if user is None:
        abort(401)
    if not user.is_super_admin and projekt.org_id != user.org_id:
        abort(403)
    return projekt


# ---- Authentifizierung ----------------------------------------------- #

@bp.get("/login")
def login():
    if current_user():
        return redirect(url_for("ui.index"))
    return render_template("login.html")


@bp.post("/login")
def login_post():
    email = request.form.get("email", "").strip()
    password = request.form.get("password", "")
    user = current_app.auth_service.authenticate(email, password)
    if not user:
        return render_template("login.html", error="E-Mail oder Passwort falsch.",
                               email=email), 401
    login_user(user)
    return redirect(url_for("ui.index"))


@bp.post("/logout")
def logout():
    logout_user()
    return redirect(url_for("ui.login"))


@bp.get("/passwort")
@login_required
def password_change():
    return render_template("passwort.html")


@bp.post("/passwort")
@login_required
def password_change_post():
    user = current_user()
    old = request.form.get("old_password", "")
    new = request.form.get("new_password", "")
    confirm = request.form.get("confirm_password", "")
    if len(new) < 8:
        return render_template("passwort.html",
                               error="Das neue Passwort muss mindestens 8 Zeichen haben."), 400
    if new != confirm:
        return render_template("passwort.html",
                               error="Die beiden Passwörter stimmen nicht überein."), 400
    if not current_app.auth_service.change_password(user.id, old, new):
        return render_template("passwort.html",
                               error="Das aktuelle Passwort ist nicht korrekt."), 400
    return render_template("passwort.html", success="Ihr Passwort wurde geändert.")


# ---- Startseite ------------------------------------------------------- #

def _zustand_je_projekt(projekte, method):
    """Was je Projekt offen ist – Rohstoff für den Vorschlag «nächster Schritt».

    Bewusst hier und nicht im Rechenmodul: das Zusammensuchen kennt Datenbank
    und Dienste, das Urteil darüber nicht. Ein Fehler beim Erheben eines
    Projekts darf die Startseite nicht leeren – dann fehlt eben dieser eine
    Vorschlag.
    """
    from app.domains.ergebnisse.models import ErgebnisEntwurf
    from app.domains.qualitaet.models import PiaPruefung
    from app.shared.database import SessionLocal

    # Welche Abschnitte das Gespraech fuehrt, weiss der Interview-Dienst - nicht
    # diese Route. Eine zweite Liste hier hatte den Typ `free_text` nicht
    # gekannt und deshalb falsch gezaehlt.
    abschnitte = current_app.interview_service.befragbare_abschnitte(method or {})
    db = SessionLocal()
    svc = current_app.projekt_service
    raus = []
    for p in projekte:
        z = {"projekt_id": p.id, "name": p.name, "abschnitte_total": len(abschnitte)}
        try:
            sitzung = None
            for modul in svc.structure(p)["module"]:
                for erg in modul["ergebnisse"]:
                    sitzung = (current_app.interview_service
                               .session_for_ergebnis(erg.id)) or sitzung
            if sitzung is not None:
                z["session_id"] = sitzung.id
                antworten = json.loads(sitzung.answers_json or "{}")
                z["offene_abschnitte"] = sum(
                    1 for s in abschnitte if s["id"] not in antworten)
                pruefung = db.query(PiaPruefung).filter(
                    PiaPruefung.session_id == sitzung.id,
                    PiaPruefung.status == "fertig",
                ).order_by(PiaPruefung.id.desc()).first()
                if pruefung is not None:
                    z["pruefung_vorhanden"] = True
                    z["muss_befunde"] = _muss_befunde(pruefung)
            else:
                z["offene_abschnitte"] = len(abschnitte)
            entwurf = db.query(ErgebnisEntwurf).filter(
                ErgebnisEntwurf.projekt_id == p.id).first()
            z["rga_vorhanden"] = entwurf is not None and bool(entwurf.answers_json)
            z["rga_laeuft"] = entwurf is not None and entwurf.lauf_status == "laufend"
        except Exception:                       # noqa: BLE001
            log.warning("Zustand von Projekt %s nicht ermittelbar.", p.id,
                        exc_info=True)
            continue
        raus.append(z)
    return raus


def _muss_befunde(pruefung):
    """Zwingende Befunde eines fertigen Prüfprotokolls – gezählt, nicht erzählt."""
    try:
        protokoll = json.loads(pruefung.protokoll_json or "{}")
    except ValueError:
        return 0
    return sum(1 for b in protokoll.get("befunde") or []
               if isinstance(b, dict)
               and str(b.get("gewicht", "")).capitalize() == "Muss")


@bp.get("/")
@login_required
def index():
    user = current_user()
    if user.is_super_admin:
        return redirect(url_for("ui.admin_orgs"))
    method = current_app.method_service.get("hermes_pia")
    projekte = current_app.projekt_service.projekte_for_org(user.org_id)
    vorschlag, weitere, ruhige = naechster_schritt(
        _zustand_je_projekt(projekte, method))
    return render_template("index.html", method=method, projekte=projekte,
                           vorschlag=vorschlag, weitere=weitere, ruhige=ruhige,
                           testlauf=current_app.testlauf_service is not None,
                           begruessung=begruessung(datetime.now().hour))


# ---- Testlauf: ein Vorhaben ohne Rueckfragen durchspielen -------------- #
#
# Nur vorhanden, wo ausdruecklich eingeschaltet (Config TESTLAUF). Auf einer
# Kundenstufe waere ein Knopf, der einen vollstaendigen PIA samt Freigabe
# erzeugt, ohne dass jemand gefragt wurde, ein Weg zu Nachweisen, die keine
# sind.

def _testlauf_dienst():
    dienst = getattr(current_app, "testlauf_service", None)
    if dienst is None:
        abort(404)
    return dienst


@bp.post("/testlauf")
@permission_required("write")
def testlauf_start():
    from app.domains.testlauf.service import TestlaufFehler

    dienst = _testlauf_dienst()
    user = current_user()
    try:
        lauf = dienst.starte(
            org_id=user.org_id,
            ausgangslage=request.form.get("ausgangslage", "").strip(),
            projektname=request.form.get("projektname", "").strip() or "Testlauf",
            projektleiter=(request.form.get("projektleiter", "").strip()
                           or getattr(user, "name", None) or user.email),
            auftraggeber=request.form.get("auftraggeber", "").strip() or None,
            verwaltungseinheit=request.form.get("verwaltungseinheit", "").strip() or None,
            ebene=",".join(request.form.getlist("ebene")) or None,
            kanton=request.form.get("kanton", "").strip() or None,
        )
    except TestlaufFehler as e:
        method = current_app.method_service.get("hermes_pia")
        projekte = current_app.projekt_service.projekte_for_org(user.org_id)
        return render_template("index.html", method=method, projekte=projekte,
                               testlauf=True, error=str(e),
                               begruessung=begruessung(datetime.now().hour)), 400
    return redirect(url_for("ui.testlauf_seite", lauf_id=lauf.id))


@bp.get("/testlauf/<int:lauf_id>")
@permission_required("read")
def testlauf_seite(lauf_id):
    dienst = _testlauf_dienst()
    lauf = dienst.hole(lauf_id)
    if lauf is None or lauf.org_id != current_user().org_id:
        abort(404)
    from app.domains.testlauf import service as testlauf_modul
    return render_template("testlauf.html", lauf=lauf,
                           zustand=dienst.zustand(lauf),
                           schritte=[n for _, n in testlauf_modul.SCHRITTE])


@bp.post("/testlauf/<int:lauf_id>/schritt")
@permission_required("write")
def testlauf_schritt(lauf_id):
    """EINE Arbeitseinheit. Antwortet IMMER JSON - auch beim Absturz, damit der
    Browser den Grund anzeigen kann statt einer HTML-Fehlerseite."""
    dienst = _testlauf_dienst()
    lauf = dienst.hole(lauf_id)
    if lauf is None or lauf.org_id != current_user().org_id:
        abort(404)
    try:
        return jsonify(dienst.schritt(lauf_id))
    except Exception as e:      # noqa: BLE001 – der Grund muss zum Browser
        current_app.logger.exception("Testlauf-Schritt abgestürzt")
        return jsonify({"fehler": f"{e.__class__.__name__}: {e}"}), 500


@bp.post("/interview/start")
@permission_required("write")
def interview_start():
    def _get(name, fallback=""):
        return request.form.get(name, "").strip() or fallback

    user = current_user()
    project_name = _get("project_name")
    projektleiter = _get("projektleiter")
    if not project_name or not projektleiter:
        method = current_app.method_service.get("hermes_pia")
        projekte = current_app.projekt_service.projekte_for_org(user.org_id)
        return render_template("index.html", method=method, projekte=projekte,
                               error="Projektname und Projektleiter/in sind erforderlich.",
                               form=request.form), 400

    session = current_app.interview_service.start_session(
        method_id="hermes_pia",
        project_name=project_name,
        org_id=user.org_id,
        projektnummer=_get("projektnummer") or None,
        auftraggeber=_get("auftraggeber") or None,
        verwaltungseinheit=_get("verwaltungseinheit") or None,
        geschaeftsbereich=_get("geschaeftsbereich") or None,
        innenauftragsnummer=_get("innenauftragsnummer") or None,
        start_datum=_get("start_datum") or None,
        created_by=projektleiter,
    )
    _wrap_in_projektstruktur(session, projektleiter)
    return redirect(url_for("ui.interview_workspace", session_id=session.id))


def _wrap_in_projektstruktur(session, projektleiter):
    """Legt für eine neue PIA Projekt + Ergebnis-Knoten an und verknüpft sie.

    Defensiv: schlägt die Strukturanlage fehl, bleibt die PIA trotzdem nutzbar
    (sie wird beim nächsten Start vom Backfill nachgezogen)."""
    from app.domains.projekt.reference import ERG_PIA
    try:
        projekt = current_app.projekt_service.create_projekt(
            org_id=session.org_id, name=session.project_name or "Projekt",
            projektnummer=session.projektnummer, auftraggeber=session.auftraggeber,
            verwaltungseinheit=session.verwaltungseinheit,
            geschaeftsbereich=session.geschaeftsbereich,
            innenauftragsnummer=session.innenauftragsnummer,
            start_datum=session.start_datum, created_by=projektleiter,
        )
        ergebnis = current_app.projekt_service.add_ergebnis(
            projekt.id, ERG_PIA, created_by=projektleiter,
        )
        current_app.interview_service.link_ergebnis(session.id, ergebnis.id)
    except Exception:  # noqa: BLE001 – Strukturanlage darf die PIA-Erstellung nie blockieren
        current_app.logger.exception("Projektstruktur für PIA %s konnte nicht angelegt werden",
                                     getattr(session, "id", "?"))


@bp.get("/interview/<int:session_id>")
@permission_required("read")
def interview_workspace(session_id):
    svc = current_app.interview_service
    session = _load_session(session_id)
    state = svc.current_state(session)
    sections = svc.section_summary(session)
    preview = svc.preview_data(session)
    method = current_app.method_service.get(session.method_id)
    projekt = current_app.projekt_service.projekt_for_ergebnis(session.ergebnis_id)
    return render_template(
        "interview.html",
        session=session, state=state, sections=sections, preview=preview, method=method,
        projekt=projekt,
        stt_available=getattr(current_app.transcriber, "available", False),
        # Ohne Pseudonymisierungsdienst wird NICHT formuliert. Das muss sichtbar
        # sein: sonst diktiert der Projektleiter ein ganzes Interview und merkt
        # erst am fertigen Dokument, dass sein Rohtext darin steht.
        # Laufende Invarianten-Pruefung: waehrend der Erstellung ein HINWEIS,
        # verbindlich erst vor der Ausgabe (Briefing Abschnitt 4.1).
        qualitaet=pruefe_session(session, tarife=_tarife_for_session(session)),
        llm_available=bool(svc.llm),
        # Direktmodus muss im Interview SICHTBAR sein – sonst arbeitet jemand
        # wochenlang ohne Pseudonymisierung, ohne es zu merken.
        pseudo_aus=_pseudonymisierung_aus(),
    )


def _tarife_for_session(session):
    """Massgebliche Kostensätze (CHF/PT) für eine Session: Projekt übersteuert Org."""
    ps = current_app.projekt_service
    projekt = ps.projekt_for_ergebnis(session.ergebnis_id) if session.ergebnis_id else None
    return ps.effective_tarife(org_id=session.org_id,
                               projekt_id=projekt.id if projekt else None)


@bp.post("/interview/<int:session_id>/answer")
@permission_required("write")
def interview_answer(session_id):
    session = _load_session(session_id)
    raw_text = request.form.get("raw_text", "").strip()
    try:
        current_app.interview_service.submit_answer(
            session_id, raw_text, tarife=_tarife_for_session(session))
    except ValueError as e:
        return str(e), 400
    return redirect(url_for("ui.interview_workspace", session_id=session_id))


@bp.post("/interview/<int:session_id>/reprocess")
@permission_required("write")
def interview_reprocess(session_id):
    session = _load_session(session_id)
    current_app.interview_service.reprocess(session_id, tarife=_tarife_for_session(session))
    return redirect(url_for("ui.interview_workspace", session_id=session_id))


@bp.post("/interview/<int:session_id>/followup")
@permission_required("write")
def interview_followup(session_id):
    session = _load_session(session_id)
    risk_id = request.form.get("risk_id", "")
    accepted = request.form.get("accepted", "0") == "1"
    raw_text = request.form.get("raw_text", "").strip() or None
    try:
        current_app.interview_service.answer_followup(
            session_id, risk_id, accepted, raw_text, tarife=_tarife_for_session(session))
    except ValueError as e:
        return str(e), 400
    return redirect(url_for("ui.interview_workspace", session_id=session_id))


@bp.post("/interview/<int:session_id>/transcribe")
@permission_required("write")
def interview_transcribe(session_id):
    """Transkribiert ein Mikrofon-Audiosegment (Diktat) und gibt den Text zurück.

    Bevorzugter Transportweg ist Base64 in JSON (Text-Body): der Hosting-Proxy
    leitet Formular-/JSON-POSTs zuverlässig weiter, während rohe Binär-Bodies
    dort scheiterten. Der Roh-Body-Pfad bleibt als Fallback erhalten.

    Datenschutz: Das Audio wird an den konfigurierten externen STT-Dienst gesendet.
    Für Behördendaten einen CH/EU- oder self-hosted-Endpoint (STT_API_URL) verwenden.
    """
    session = _load_session(session_id)
    # Projektspezifisches Vokabular (Projektname + bereits Diktiertes) als Hinweis
    # mitgeben – so passt die Erkennung sich je Mandant/Projekt selbst an.
    return _transcribe_request(kontext_fuer_diktat(session))


def _transcribe_request(kontext=""):
    """Gemeinsame Diktat-Logik: Audio (Base64-JSON bevorzugt, Roh-Body als
    Fallback) an den STT-Dienst geben und den Text zurückgeben."""
    tr = current_app.transcriber
    if not getattr(tr, "available", False):
        return jsonify({"text": "", "error": "Transkription ist nicht konfiguriert."}), 200
    if (request.content_type or "").startswith("application/json"):
        payload = request.get_json(silent=True) or {}
        try:
            audio = base64.b64decode(payload.get("audio") or "")
        except Exception:  # noqa: BLE001 – kaputtes Base64 wie "keine Daten" behandeln
            audio = b""
        mimetype = payload.get("mime") or "audio/webm"
    else:
        # Roher Request-Body statt multipart/form-data: der Multipart-Parser blockierte
        # hinter dem Proxy beim Lesen (Worker-Timeout). get_data() liest exakt
        # Content-Length Bytes und kehrt zurück, sobald der Body da ist.
        audio = request.get_data(cache=False)
        mimetype = request.content_type or "audio/webm"
    if not audio:
        return jsonify({"text": "", "error": "Keine Audiodaten."}), 400
    try:
        text = tr.transcribe(audio, filename="segment.webm", mimetype=mimetype,
                             kontext=kontext)
    except Exception as exc:  # noqa: BLE001 – Fehler an den Client melden, nicht crashen
        return jsonify({"text": "", "error": f"Transkription fehlgeschlagen: {exc}"}), 502
    return jsonify({"text": text})


@bp.post("/transcribe")
@permission_required("write")
def transcribe():
    """Session-unabhängiges Diktat (z.B. Bemerkungsfelder im Zuordnungs-Editor)."""
    return _transcribe_request()


@bp.post("/interview/<int:session_id>/delete")
@permission_required("delete")
def interview_delete(session_id):
    _load_session(session_id)
    current_app.interview_service.delete_session(session_id)
    return redirect(url_for("ui.index"))


# ---- Projekte: Container für die Ergebnisse --------------------------- #

@bp.get("/projekt/<int:projekt_id>")
@permission_required("read")
def projekt_detail(projekt_id):
    """Projektansicht: Phase Initialisierung → Module → Ergebnisse + Meilensteine."""
    projekt = _load_projekt(projekt_id)
    svc = current_app.projekt_service
    structure = svc.structure(projekt)
    # PIA-Ergebnisse mit ihrer Session bzw. Freigabe-Dokumenten verknüpfen.
    sessions, freigabe_docs = {}, {}
    for modul in structure["module"]:
        for erg in modul["ergebnisse"]:
            s = current_app.interview_service.session_for_ergebnis(erg.id)
            if s:
                sessions[erg.id] = s
            dok = svc.latest_dokument(erg.id, art="freigabe")
            if dok:
                freigabe_docs[erg.id] = dok
    vorlage = svc.resolve_vorlage(projekt)
    methoden_vorlage = svc.projekt_methoden_vorlage(projekt.id)
    org_methoden_vorlage = svc.org_methoden_vorlage(projekt.org_id)
    aktive_methoden_vorlage = methoden_vorlage or org_methoden_vorlage
    methoden_report = _methoden_vorlage_report(aktive_methoden_vorlage)
    # Download-Dateinamen (yyyymmdd_Projektname.*) stehen in der URL, weil der
    # Hosting-Proxy den Content-Disposition-Header verschluckt.
    stamp = f"{date.today():%Y%m%d}_{_safe_filename(projekt.name or 'Projekt')}"
    downloads = {
        "praesentation": f"{stamp}.pptx",
        "plan_msproject": f"{stamp}_Projektplan.xml",
        "plan_excel": f"{stamp}_Projektplan.xlsx",
    }
    # Wann welcher Entscheid gefallen ist - damit ein erreichter Meilenstein
    # nicht nur einen gruenen Rand traegt, sondern es auch dasteht.
    entscheiddaten = {}
    for e in current_app.freigabe_service.entscheide(projekt.id):
        if e.nr == "01":
            entscheiddaten["projektinitialisierungsfreigabe"] = e.entscheidungsdatum
    return render_template("projekt_detail.html", projekt=projekt,
                           entscheiddaten=entscheiddaten,
                           structure=structure, sessions=sessions,
                           freigabe_docs=freigabe_docs, vorlage=vorlage,
                           methoden_vorlage=methoden_vorlage,
                           org_methoden_vorlage=org_methoden_vorlage,
                           aktive_methoden_vorlage=aktive_methoden_vorlage,
                           methoden_report=methoden_report,
                           methoden_editor=_methoden_editor(methoden_vorlage),
                           methoden_mapping_url=url_for(
                               "ui.methoden_mapping", projekt_id=projekt.id),
                           kostensatz=svc.projekt_kostensatz(projekt.id),
                           org_kostensatz=svc.org_kostensatz(projekt.org_id),
                           downloads=downloads)


@bp.post("/projekt/<int:projekt_id>/kostensatz")
@permission_required("write")
def projekt_kostensatz(projekt_id):
    """Speichert den projektspezifischen Kostensatz (übersteuert die PMO-Vorgabe)."""
    projekt = _load_projekt(projekt_id)
    current_app.projekt_service.set_kostensatz(
        satz_intern=request.form.get("satz_intern"),
        satz_extern=request.form.get("satz_extern"),
        einheit=request.form.get("einheit", "tag"),
        stunden_pro_tag=request.form.get("stunden_pro_tag") or 8,
        org_id=projekt.org_id, projekt_id=projekt.id,
    )
    return redirect(url_for("ui.projekt_detail", projekt_id=projekt.id))


# ---- Rechtsgrundlagenanalyse (abgeleitetes Ergebnis, eigenes Modul) ----- #

KANTONE = [
    ("AG", "Aargau"), ("AI", "Appenzell Innerrhoden"), ("AR", "Appenzell Ausserrhoden"),
    ("BE", "Bern"), ("BL", "Basel-Landschaft"), ("BS", "Basel-Stadt"), ("FR", "Freiburg"),
    ("GE", "Genf"), ("GL", "Glarus"), ("GR", "Graubünden"), ("JU", "Jura"), ("LU", "Luzern"),
    ("NE", "Neuenburg"), ("NW", "Nidwalden"), ("OW", "Obwalden"), ("SG", "St. Gallen"),
    ("SH", "Schaffhausen"), ("SO", "Solothurn"), ("SZ", "Schwyz"), ("TG", "Thurgau"),
    ("TI", "Tessin"), ("UR", "Uri"), ("VD", "Waadt"), ("VS", "Wallis"), ("ZG", "Zug"),
    ("ZH", "Zürich"),
]


@bp.get("/projekt/<int:projekt_id>/rechtsgrundlagen")
@permission_required("read")
def rechtsgrundlagen(projekt_id):
    projekt = _load_projekt(projekt_id)
    svc = current_app.rechtsgrundlagen_service
    entwurf = svc.get_entwurf(projekt.id)
    wissen, session = svc.projektwissen(projekt,
                                        ebene=entwurf.ebene if entwurf else None,
                                        kanton=entwurf.kanton if entwurf else None)
    version = (entwurf.doc_version if entwurf and entwurf.doc_version else "0.1")
    download_name = (f"{_safe_filename(projekt.name or 'Projekt')}"
                     f"_Rechtsgrundlagenanalyse_V{version}.docx")
    from app.domains.ergebnisse.rechtsgrundlagen.kette import schrittnamen
    return render_template(
        "rechtsgrundlagen.html", projekt=projekt, entwurf=entwurf,
        genannte=wissen.genannte_rechtsgrundlagen(), hat_pia=session is not None,
        kantone=KANTONE, download_name=download_name,
        grounding=svc.grounding_status(projekt),
        kette_laeuft=bool(entwurf and entwurf.lauf_status == "laufend"),
        schrittnamen=schrittnamen())


@bp.post("/projekt/<int:projekt_id>/rechtsgrundlagen/erzeugen")
@permission_required("write")
def rechtsgrundlagen_erzeugen(projekt_id):
    projekt = _load_projekt(projekt_id)
    ebenen = request.form.getlist("ebene")
    current_app.rechtsgrundlagen_service.erzeuge_entwurf(
        projekt, ebene=",".join(ebenen) or None, kanton=request.form.get("kanton") or None)
    return redirect(url_for("ui.rechtsgrundlagen", projekt_id=projekt.id))


@bp.post("/projekt/<int:projekt_id>/rechtsgrundlagen/kette")
@permission_required("write")
def rechtsgrundlagen_kette(projekt_id):
    """Startet die vierschichtige Analyse. Sie laeuft danach schrittweise."""
    projekt = _load_projekt(projekt_id)
    ebenen = request.form.getlist("ebene")
    current_app.rechtsgrundlagen_service.starte_kette(
        projekt, ebene=",".join(ebenen) or None,
        kanton=request.form.get("kanton") or None)
    return redirect(url_for("ui.rechtsgrundlagen", projekt_id=projekt.id))


@bp.post("/projekt/<int:projekt_id>/rechtsgrundlagen/kette/schritt")
@permission_required("write")
def rechtsgrundlagen_kette_schritt(projekt_id):
    """EIN Schritt der Kette. Antwortet IMMER JSON – auch beim Absturz, damit
    der Browser den Grund anzeigen kann statt einer HTML-Fehlerseite, an der
    er scheitert."""
    projekt = _load_projekt(projekt_id)
    try:
        zustand, grund = current_app.rechtsgrundlagen_service.kette_schritt(projekt)
    except Exception as e:      # noqa: BLE001 – der Grund muss zum Browser
        current_app.logger.exception("Kettenschritt abgestürzt")
        return jsonify({"fehler": f"{e.__class__.__name__}: {e}"}), 500
    if zustand is None:
        return jsonify({"fehler": grund or "Der Schritt ist fehlgeschlagen."}), 502
    return jsonify(zustand)


# ---- Projektinitialisierungsfreigabe ---------------------------------- #
#
# Die Reihenfolge (Checkliste -> Freigabe -> Meilenstein -> Entscheid) steht im
# Dienst, nicht hier. Diese Routen zeigen an, nehmen entgegen und melden
# zurueck, warum ein Schritt nicht geht - entscheiden tun sie nichts.

def _freigabe_seite(projekt, fehler=None, hinweis=None, auto_download=None):
    svc = current_app.freigabe_service
    checkliste = svc.checkliste(projekt.id)
    alle = svc.zeilen(checkliste)
    from app.domains.freigabe.pruefpunkte import (
        ERFUELLT, NICHT_ERFUELLT, TEILWEISE, ZU_BESTAETIGEN, offene_punkte)
    return render_template(
        "freigabe.html", projekt=projekt, checkliste=checkliste, alle=alle,
        freigegeben=(checkliste is not None and checkliste.status == "freigegeben"),
        offen=offene_punkte(svc.alle_zeilen(alle)),
        bewertungen=(ERFUELLT, TEILWEISE, NICHT_ERFUELLT, ZU_BESTAETIGEN),
        meilenstein=svc.meilenstein(projekt.id),
        entscheide=svc.entscheide(projekt.id),
        heute=date.today().isoformat(),
        dateinamen=_freigabe_dateinamen(projekt),
        versionsstand=svc.versionsstand(projekt.id),
        fassungen=svc.fassungen(projekt.id),
        auto_download=auto_download,
        fehler=fehler, hinweis=hinweis)


@bp.get("/projekt/<int:projekt_id>/freigabe")
@permission_required("read")
def freigabe(projekt_id):
    return _freigabe_seite(_load_projekt(projekt_id))


@bp.post("/projekt/<int:projekt_id>/freigabe/erzeugen")
@permission_required("write")
def freigabe_erzeugen(projekt_id):
    from app.domains.freigabe.service import FreigabeFehler

    projekt = _load_projekt(projekt_id)
    try:
        current_app.freigabe_service.erzeuge(projekt)
    except FreigabeFehler as e:
        return _freigabe_seite(projekt, fehler=str(e))
    return redirect(url_for("ui.freigabe", projekt_id=projekt.id))


@bp.post("/projekt/<int:projekt_id>/freigabe/speichern")
@permission_required("write")
def freigabe_speichern(projekt_id):
    """Bewertungen und Erlaeuterungen aus dem Formular uebernehmen."""
    from app.domains.freigabe.service import FreigabeFehler

    projekt = _load_projekt(projekt_id)
    svc = current_app.freigabe_service
    zeilen = svc.zeilen(svc.checkliste(projekt.id))
    for kapitel, liste in zeilen.items():
        for i, zeile in enumerate(liste):
            bewertung = request.form.get(f"bewertung-{kapitel}-{i}")
            if bewertung is not None:
                zeile["bewertung"] = bewertung.strip()
            erlaeuterung = request.form.get(f"erlaeuterung-{kapitel}-{i}")
            if erlaeuterung is not None:
                zeile["erlaeuterung"] = erlaeuterung.strip()
    try:
        svc.speichere_zeilen(projekt.id, zeilen)
    except FreigabeFehler as e:
        return _freigabe_seite(projekt, fehler=str(e))
    return redirect(url_for("ui.freigabe", projekt_id=projekt.id))


@bp.post("/projekt/<int:projekt_id>/freigabe/geben")
@permission_required("write")
def freigabe_geben(projekt_id):
    from app.domains.freigabe.service import FreigabeFehler

    projekt = _load_projekt(projekt_id)
    user = current_user()
    try:
        current_app.freigabe_service.gib_frei(
            projekt.id, getattr(user, "name", None) or getattr(user, "email", ""))
    except FreigabeFehler as e:
        return _freigabe_seite(projekt, fehler=str(e))
    return _freigabe_seite(
        projekt, hinweis="Die Checkliste ist freigegeben. Der Auftraggeber kann "
                         "den Meilenstein jetzt setzen.")


@bp.post("/projekt/<int:projekt_id>/freigabe/meilenstein")
@permission_required("write")
def freigabe_meilenstein(projekt_id):
    from app.domains.freigabe.service import FreigabeFehler

    projekt = _load_projekt(projekt_id)
    user = current_user()
    try:
        current_app.freigabe_service.erreiche_meilenstein(
            projekt.id, getattr(user, "name", None) or getattr(user, "email", ""),
            entscheidungsdatum=(request.form.get("datum") or "").strip() or None)
    except FreigabeFehler as e:
        return _freigabe_seite(projekt, fehler=str(e))
    # Die Liste wird sofort bezogen - der Entscheid ist gefallen, das
    # Dokument ist der Beleg dafuer. Wer ihn erst suchen muss, legt ihn nicht ab.
    return _freigabe_seite(
        projekt,
        hinweis="Der Meilenstein ist erreicht, der Entscheid ist in der Liste "
                "Projektentscheide Steuerung nachgetragen. Die Phase "
                "Initialisierung laeuft. Die Liste wird jetzt heruntergeladen.",
        auto_download=url_for(
            "ui.freigabe_entscheide_docx", projekt_id=projekt.id,
            filename=_freigabe_dateinamen(projekt)["entscheide"]))


DOCX_MIME = ("application/vnd.openxmlformats-officedocument"
             ".wordprocessingml.document")


def _freigabe_dateinamen(projekt):
    """Dateinamen mit Datum und Projektname - wie bei den uebrigen Downloads.

    Der Name steht IN DER URL: der Hosting-Proxy verschluckt den
    Content-Disposition-Header, der Browser benennt die Datei sonst nach dem
    letzten URL-Segment.
    """
    stamp = f"{date.today():%Y%m%d}_{_safe_filename(projekt.name or 'Projekt')}"
    return {
        "checkliste": f"{stamp}_Checkliste_Projektinitialisierungsfreigabe.docx",
        "entscheide": f"{stamp}_Liste_Projektentscheide_Steuerung.docx",
    }


@bp.get("/projekt/<int:projekt_id>/freigabe/checkliste/<path:filename>")
@permission_required("read")
def freigabe_checkliste_docx(projekt_id, filename):
    """Die ausgefuellte Checkliste nach der HERMES-Vorlage."""
    from app.domains.freigabe import dokumente

    projekt = _load_projekt(projekt_id)
    svc = current_app.freigabe_service
    checkliste = svc.checkliste(projekt.id)
    if checkliste is None:
        abort(404)
    # Der HERMES-Versionssprung: 0.x solange in Arbeit, 1.0 mit der Freigabe.
    freigegeben = checkliste.status == "freigegeben"
    stand = "freigegeben" if freigegeben else "in Arbeit"
    freigabedatum = (checkliste.freigegeben_am.strftime("%d.%m.%Y")
                     if checkliste.freigegeben_am else "")
    angaben, abschnitte, wissen = svc.dokument_kontext(
        projekt, methode=current_app.method_service.get("hermes_pia"),
        version="1.0" if freigegeben else "0.1", status=stand,
        datum=freigabedatum or f"{date.today():%d.%m.%Y}")
    # Verantwortlich ist, wer fuer die Checkliste einsteht: die Projektleitung.
    # Ihr Name steht im Projektinitialisierungsauftrag - er wird nicht erfragt
    # und nicht geraten.
    kopf = {
        "verantwortlich": angaben.get("projektleiter", ""),
        "datum": freigabedatum,
    }
    puffer = dokumente.checkliste_docx(svc.zeilen(checkliste), kopf=kopf,
                                       angaben=angaben, abschnitte=abschnitte,
                                       wissen=wissen)
    return send_file(puffer, mimetype=DOCX_MIME, as_attachment=True,
                     download_name=filename)


@bp.get("/projekt/<int:projekt_id>/freigabe/entscheide/<path:filename>")
@permission_required("read")
def freigabe_entscheide_docx(projekt_id, filename):
    """Das Register der Projektentscheide Steuerung."""
    from app.domains.freigabe import dokumente

    projekt = _load_projekt(projekt_id)
    svc = current_app.freigabe_service
    angaben, abschnitte, wissen = svc.dokument_kontext(
        projekt, methode=current_app.method_service.get("hermes_pia"),
        version="0.1", status="in Arbeit", datum=f"{date.today():%d.%m.%Y}")
    puffer = dokumente.entscheide_docx(svc.entscheide(projekt.id), angaben=angaben,
                                       abschnitte=abschnitte, wissen=wissen)
    return send_file(puffer, mimetype=DOCX_MIME, as_attachment=True,
                     download_name=filename)


@bp.post("/projekt/<int:projekt_id>/freigabe/checkliste/upload")
@permission_required("write")
def freigabe_checkliste_upload(projekt_id):
    """Die in Word bearbeitete Checkliste zurueckuebernehmen (Base64-JSON).

    Ein Ergebnis, das man nur herunterladen kann, ist eine Sackgasse:
    gearbeitet wird in Word, und was dort entsteht, muss zurueckfliessen.
    Uebernommen werden nur die vier Spalten, die ein Mensch ausfuellt.
    """
    from app.domains.freigabe import dokumente
    from app.domains.freigabe.service import FreigabeFehler

    _load_projekt(projekt_id)
    svc = current_app.freigabe_service
    checkliste = svc.checkliste(projekt_id)
    if checkliste is None:
        return jsonify({"error": "Fuer dieses Projekt gibt es noch keine "
                                 "Checkliste."}), 404
    filename, daten = _json_upload(".docx")
    if filename is None:
        return jsonify({"error": daten}), 400

    # Die ART entscheidet, was mit der Datei geschieht. Ein Arbeitsstand
    # fliesst in die Bewertungen zurueck; eine Freigabeversion und die
    # freigegebene Fassung werden ABGELEGT - sie sind Nachweise und werden
    # nicht in Einzelteile zerlegt.
    art = (request.args.get("art") or "arbeitsstand").strip()
    if art != "arbeitsstand":
        try:
            svc.lege_fassung_ab(
                projekt_id, art, filename, daten,
                durch=(getattr(current_user(), "name", None)
                       or getattr(current_user(), "email", "")),
                doc_version=checkliste.doc_version or "")
        except FreigabeFehler as e:
            return jsonify({"error": str(e)}), 400
        return jsonify({"ok": True, "abgelegt": art})

    try:
        gelesen = dokumente.checkliste_aus_docx(daten)
    except Exception as e:                      # noqa: BLE001
        log.warning("Hochgeladene Checkliste nicht lesbar: %s", e)
        return jsonify({"error": "Die Datei liess sich nicht als Checkliste "
                                 "lesen. Stammt sie aus dem Herunterladen "
                                 "dieser Seite?"}), 400
    bestand, geaendert = dokumente.uebernimm(svc.zeilen(checkliste), gelesen)
    try:
        svc.speichere_zeilen(projekt_id, bestand)
    except FreigabeFehler as e:
        return jsonify({"error": str(e)}), 409
    return jsonify({"ok": True, "geaendert": geaendert})


# ---- Kopfdaten -------------------------------------------------------- #
#
# Die zwoelf Angaben, die jedes Dokument des Projekts im Kopf traegt. Sie
# liegen einmal, bestaetigt und aenderbar; weicht ein hochgeladener Auftrag
# ab, wird gefragt statt still ueberschrieben.

def _kopfdaten_bereitstellen(projekt):
    """(Eintrag, Angaben aus dem hochgeladenen Auftrag) - legt an, falls noetig."""
    svc = current_app.kopfdaten_service
    _, _, _, sitzung, aus_dokument = current_app.freigabe_service.projektwissen(projekt)
    return svc.stelle_bereit(projekt, session=sitzung,
                             aus_dokument=aus_dokument), aus_dokument


def _kopfdaten_seite(projekt, hinweis=None):
    from app.domains.dokumentenkopf.models import ANREDEN, FELDER
    from app.domains.dokumentenkopf.service import BESCHRIFTUNG

    svc = current_app.kopfdaten_service
    eintrag, aus_dokument = _kopfdaten_bereitstellen(projekt)
    return render_template(
        "kopfdaten.html", projekt=projekt, kopfdaten=eintrag,
        felder=FELDER, beschriftung=BESCHRIFTUNG, anreden=ANREDEN,
        abweichungen=svc.abweichungen(projekt.id, aus_dokument),
        hinweis=hinweis)


@bp.get("/projekt/<int:projekt_id>/kopfdaten")
@permission_required("read")
def kopfdaten(projekt_id):
    return _kopfdaten_seite(_load_projekt(projekt_id))


@bp.post("/projekt/<int:projekt_id>/kopfdaten")
@permission_required("write")
def kopfdaten_speichern(projekt_id):
    from app.domains.dokumentenkopf.models import FELDER

    projekt = _load_projekt(projekt_id)
    user = current_user()
    # Erst sicherstellen, DANN speichern: wer das Formular ohne vorherigen
    # Besuch abschickt, haette sonst ins Leere gespeichert.
    _kopfdaten_bereitstellen(projekt)
    felder = {f: request.form.get(f, "") for f in FELDER}
    for f in ("projektleiter_anrede", "auftraggeber_anrede"):
        felder[f] = request.form.get(f, "")
    current_app.kopfdaten_service.speichere(
        projekt.id, felder,
        durch=getattr(user, "name", None) or getattr(user, "email", ""))
    return _kopfdaten_seite(projekt, hinweis="Die Kopfdaten sind gesichert. Sie "
                                             "gelten ab sofort fuer jedes Dokument "
                                             "dieses Projekts.")


@bp.post("/projekt/<int:projekt_id>/kopfdaten/uebernehmen")
@permission_required("write")
def kopfdaten_uebernehmen(projekt_id):
    """Ausgewaehlte Werte aus dem hochgeladenen Auftrag uebernehmen."""
    projekt = _load_projekt(projekt_id)
    user = current_user()
    _, aus_dokument = _kopfdaten_bereitstellen(projekt)
    gewaehlt = request.form.getlist("feld")
    if not gewaehlt:
        return _kopfdaten_seite(projekt, hinweis="Es war nichts ausgewaehlt - "
                                                 "es wurde nichts geaendert.")
    current_app.kopfdaten_service.uebernimm(
        projekt.id, aus_dokument, gewaehlt,
        durch=getattr(user, "name", None) or getattr(user, "email", ""))
    return _kopfdaten_seite(
        projekt, hinweis=f"{len(gewaehlt)} Angabe(n) aus dem hochgeladenen "
                         "Auftrag uebernommen.")


@bp.post("/projekt/<int:projekt_id>/freigabe/version")
@permission_required("write")
def freigabe_neue_version(projekt_id):
    """Die naechste Fassung der Checkliste anlegen."""
    from app.domains.freigabe.service import FreigabeFehler

    projekt = _load_projekt(projekt_id)
    user = current_user()
    try:
        neu, _ = current_app.freigabe_service.neue_version(
            projekt.id, art=(request.form.get("art") or "minor"),
            name=(getattr(user, "name", None) or getattr(user, "email", "")),
            bemerkungen=(request.form.get("bemerkungen") or "").strip())
    except FreigabeFehler as e:
        return _freigabe_seite(projekt, fehler=str(e))
    return _freigabe_seite(
        projekt, hinweis=f"Version {neu} angelegt. Die Checkliste ist wieder ein "
                         "Entwurf; der freigegebene Stand bleibt als Fassung "
                         "erhalten.")


@bp.get("/projekt/<int:projekt_id>/freigabe/fassung/<int:fassung_id>/<path:filename>")
@permission_required("read")
def freigabe_fassung_download(projekt_id, fassung_id, filename):
    from app.domains.freigabe.models import Dokumentfassung
    from app.shared.database import SessionLocal

    _load_projekt(projekt_id)
    fassung = SessionLocal().get(Dokumentfassung, fassung_id)
    if fassung is None or fassung.projekt_id != int(projekt_id):
        abort(404)
    return send_file(io.BytesIO(fassung.data), mimetype=DOCX_MIME,
                     as_attachment=True, download_name=filename)


@bp.get("/projekt/<int:projekt_id>/rechtsgrundlagen/version")
@permission_required("write")
def rechtsgrundlagen_version(projekt_id):
    """Versionsstand der Rechtsgrundlagenanalyse – dieselbe Seite wie beim PIA."""
    projekt = _load_projekt(projekt_id)
    svc = current_app.rechtsgrundlagen_service
    return render_template(
        "version_bump.html", session=None,
        info=svc.version_stand(projekt),
        titel=projekt.name, dokumentname="Rechtsgrundlagenanalyse",
        zurueck_url=url_for("ui.rechtsgrundlagen", projekt_id=projekt.id))


@bp.post("/projekt/<int:projekt_id>/rechtsgrundlagen/version")
@permission_required("write")
def rechtsgrundlagen_version_post(projekt_id):
    projekt = _load_projekt(projekt_id)
    svc = current_app.rechtsgrundlagen_service
    neu, _ = svc.version_eintragen(
        projekt, art=request.form.get("bump_type", "minor"),
        # current_user() liefert ein User-OBJEKT, kein Wörterbuch. Die Zeile
        # hier rief .get() darauf - erfunden, obwohl dieselbe Datei die
        # richtige Schreibweise zweimal enthält.
        name=getattr(current_user(), "email", "") or "",
        bemerkungen=request.form.get("bemerkungen", "").strip())
    name = (f"{_safe_filename(projekt.name or 'Projekt')}"
            f"_Rechtsgrundlagenanalyse_V{neu}.docx")
    return redirect(url_for("ui.rechtsgrundlagen_download",
                            projekt_id=projekt.id, filename=name))


@bp.get("/projekt/<int:projekt_id>/rechtsgrundlagen/download/<path:filename>")
@permission_required("read")
def rechtsgrundlagen_download(projekt_id, filename):
    projekt = _load_projekt(projekt_id)
    buf = current_app.rechtsgrundlagen_service.generate_docx(projekt)
    return send_file(
        buf, as_attachment=True, download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document")


# ---- Schutzbedarfsanalyse (BACS-Excel, Formeln unberührt) --------------- #

@bp.get("/projekt/<int:projekt_id>/schutzbedarf")
@permission_required("read")
def schutzbedarf(projekt_id):
    projekt = _load_projekt(projekt_id)
    svc = current_app.schutzbedarf_service
    _, session = svc.projektwissen(projekt)
    stamp = _safe_filename(projekt.name or "Projekt")
    return render_template(
        "schutzbedarf.html", projekt=projekt, entwurf=svc.get_entwurf(projekt.id),
        hat_pia=session is not None, download_name=f"{stamp}_Schutzbedarfsanalyse.xlsx")


@bp.post("/projekt/<int:projekt_id>/schutzbedarf/erzeugen")
@permission_required("write")
def schutzbedarf_erzeugen(projekt_id):
    projekt = _load_projekt(projekt_id)
    current_app.schutzbedarf_service.erzeuge_entwurf(projekt)
    return redirect(url_for("ui.schutzbedarf", projekt_id=projekt.id))


@bp.get("/projekt/<int:projekt_id>/schutzbedarf/download/<path:filename>")
@permission_required("read")
def schutzbedarf_download(projekt_id, filename):
    projekt = _load_projekt(projekt_id)
    buf = current_app.schutzbedarf_service.generate_xlsx(projekt)
    return send_file(
        buf, as_attachment=True, download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ---- Dokumente & Präsentation am Ergebnis ------------------------------ #

_UPLOAD_LIMIT = 15 * 1024 * 1024   # 15 MB (decodiert)


def _json_upload(allowed_ext):
    """Liest einen Base64-JSON-Upload {filename, data} und validiert ihn.
    Rückgabe: (filename, bytes) oder (None, Fehlermeldung)."""
    payload = request.get_json(silent=True) or {}
    filename = (payload.get("filename") or "").strip()
    exts = (allowed_ext,) if isinstance(allowed_ext, str) else tuple(allowed_ext)
    if not filename.lower().endswith(exts):
        return None, f"Nur {'/'.join(exts)}-Dateien sind erlaubt."
    try:
        data = base64.b64decode(payload.get("data") or "")
    except Exception:  # noqa: BLE001 – kaputtes Base64 = keine Daten
        data = b""
    if not data:
        return None, "Keine Dateidaten empfangen."
    if len(data) > _UPLOAD_LIMIT:
        return None, "Datei zu gross (max. 15 MB)."
    if not data.startswith(b"PK"):     # docx/pptx sind ZIP-Container
        return None, "Die Datei ist keine gültige Office-Datei."
    return filename, data


def _methoden_vorlage_report(vorlage):
    """Erkennungs-Vorschau einer hochgeladenen Wortvorlage: wie viele Kapitel
    erkennt HERMES PIA, welche werden generisch erfragt, welche kanonischen
    Kapitel fehlen. Gibt None zurück, wenn keine Vorlage vorliegt."""
    if vorlage is None:
        return None
    try:
        method = current_app.method_service.get("hermes_pia")
        _, report = build_derived_method(vorlage.data, method)
    except Exception:  # noqa: BLE001 – Vorschau darf nie eine Seite sprengen
        return None
    titel = {s["id"]: s.get("title", s["id"]) for s in method.get("sections", [])}
    report["missing_titles"] = [titel.get(sid, sid)
                                for sid in report.get("missing_canonical", [])]
    report["erkannt"] = len(report.get("matched", []))
    report["gesamt"] = report["erkannt"] + len(report.get("generic", []))
    return report


def _methoden_editor(vorlage):
    """Baut die Daten für den Kapitel-Zuordnungs-Editor: je Vorlagenkapitel das
    (bestätigte oder vorgeschlagene) Ziel + Bemerkung, die Dropdown-Optionen und
    die im Template fehlenden HERMES-Kapitel."""
    if vorlage is None:
        return None
    try:
        method = current_app.method_service.get("hermes_pia")
        vorschlag, missing_ids = propose_mapping(vorlage.data, method)
    except Exception:  # noqa: BLE001 – Editor darf die Seite nie sprengen
        return None
    sections = method.get("sections", [])
    optionen = [{"id": s["id"], "label": f"{s.get('number', '')} {s['title']}".strip()}
                for s in sections if s.get("type") in ("free_text", "table")]
    titel = {s["id"]: s.get("title", s["id"]) for s in sections}

    saved = {}
    if vorlage.mapping_json:
        try:
            for e in json.loads(vorlage.mapping_json):
                saved[e.get("heading")] = e
        except (ValueError, TypeError):
            saved = {}

    rows = []
    for v in vorschlag:
        s = saved.get(v["heading"], {})
        rows.append({"heading": v["heading"], "level": v["level"],
                     "ziel": s.get("ziel", v["ziel"]),
                     "bemerkung": s.get("bemerkung", "")})
    return {
        "vorlage_id": vorlage.id,
        "rows": rows,
        "optionen": optionen,
        "missing": [titel.get(i, i) for i in missing_ids],
        "bestaetigt": bool(vorlage.mapping_json),
        "ziel_generisch": ZIEL_GENERISCH,
        "ziel_unveraendert": ZIEL_UNVERAENDERT,
    }


def _save_mapping_from_form(vorlage_id):
    headings = request.form.getlist("heading[]")
    ziele = request.form.getlist("ziel[]")
    bemerkungen = request.form.getlist("bemerkung[]")
    mapping = []
    for i, h in enumerate(headings):
        mapping.append({
            "heading": h,
            "ziel": ziele[i] if i < len(ziele) else ZIEL_UNVERAENDERT,
            "bemerkung": (bemerkungen[i] if i < len(bemerkungen) else "").strip(),
        })
    current_app.projekt_service.set_methoden_mapping(vorlage_id, mapping)


def _load_ergebnis(projekt_id, ergebnis_id):
    """Stellt sicher, dass das Ergebnis zum (zugriffsgeprüften) Projekt gehört."""
    _load_projekt(projekt_id)
    projekt = current_app.projekt_service.projekt_for_ergebnis(ergebnis_id)
    if not projekt or projekt.id != int(projekt_id):
        abort(404)
    return projekt


@bp.post("/projekt/<int:projekt_id>/ergebnis/<int:ergebnis_id>/dokument")
@permission_required("write")
def ergebnis_dokument_upload(projekt_id, ergebnis_id):
    """Lädt eine PIA-Fassung (.docx) zum Ergebnis hoch (Base64-JSON).

    Die ART bestimmt die Verbindlichkeit: «freigegeben» schlägt
    «freigabe» (freigabebereit), und beide schlagen den Arbeitsstand im
    Interview. Abgeleitete Ergebnisse beruhen auf dem, was gilt.
    """
    from app.domains.ergebnisse.pia_quelle import DOKUMENTARTEN

    _load_ergebnis(projekt_id, ergebnis_id)
    art = (request.args.get("art") or "freigabe").strip()
    if art not in DOKUMENTARTEN:
        return jsonify({"error": f"Unbekannte Dokumentart «{art}»."}), 400
    filename, data = _json_upload(".docx")
    if filename is None:
        return jsonify({"error": data}), 400
    user = current_user()
    dok = current_app.projekt_service.add_dokument(
        ergebnis_id, filename, data, art=art,
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        uploaded_by=getattr(user, "email", None),
    )
    if dok is None:
        abort(404)
    return jsonify({"ok": True, "dokument_id": dok.id})


@bp.get("/projekt/<int:projekt_id>/dokument/<int:dokument_id>/<path:filename>")
@permission_required("read")
def ergebnis_dokument_download(projekt_id, dokument_id, filename):
    # Der Dateiname steht IN DER URL: der Hosting-Proxy verschluckt den
    # Content-Disposition-Header, der Browser benennt die Datei sonst nach
    # dem letzten URL-Segment (gleiches Muster wie beim PIA-Word-Download).
    _load_projekt(projekt_id)
    dok = current_app.projekt_service.get_dokument(dokument_id)
    if not dok:
        abort(404)
    projekt = current_app.projekt_service.projekt_for_ergebnis(dok.ergebnis_id)
    if not projekt or projekt.id != int(projekt_id):
        abort(404)
    return send_file(
        io.BytesIO(dok.data),
        mimetype=dok.mimetype or "application/octet-stream",
        as_attachment=True,
        download_name=dok.filename,
    )


@bp.post("/projekt/<int:projekt_id>/vorlage")
@permission_required("write")
def praesentations_vorlage_upload(projekt_id):
    """Lädt eine projektspezifische .pptx-Vorlage hoch – sie ÜBERSTEUERT die
    PMO-Vorlage der Organisationseinheit. Die organisationsweite Vorlage wird
    im PMO-Bereich gepflegt."""
    projekt = _load_projekt(projekt_id)
    filename, data = _json_upload(".pptx")
    if filename is None:
        return jsonify({"error": data}), 400
    user = current_user()
    current_app.projekt_service.add_vorlage(
        filename, data,
        org_id=projekt.org_id,
        projekt_id=projekt.id,
        uploaded_by=getattr(user, "email", None),
    )
    return jsonify({"ok": True})


@bp.post("/projekt/<int:projekt_id>/methoden-vorlage")
@permission_required("write")
def methoden_vorlage_upload(projekt_id):
    """Lädt eine projektspezifische Word-Vorlage (.docx/.dotx) hoch – sie
    ÜBERSTEUERT die PMO-Vorlage der Organisationseinheit für dieses Projekt.
    Aus ihrer Kapitelstruktur leitet HERMES PIA das Interview ab."""
    projekt = _load_projekt(projekt_id)
    filename, data = _json_upload((".docx", ".dotx"))
    if filename is None:
        return jsonify({"error": data}), 400
    user = current_user()
    current_app.projekt_service.add_methoden_vorlage(
        filename, data,
        org_id=projekt.org_id,
        projekt_id=projekt.id,
        uploaded_by=getattr(user, "email", None),
    )
    return jsonify({"ok": True})


@bp.post("/projekt/<int:projekt_id>/methoden-vorlage/zuordnung")
@permission_required("write")
def methoden_mapping(projekt_id):
    """Speichert die bestätigte Kapitel-Zuordnung der Projekt-Wortvorlage."""
    projekt = _load_projekt(projekt_id)
    vorlage = current_app.projekt_service.projekt_methoden_vorlage(projekt.id)
    if vorlage is None:
        abort(404)
    _save_mapping_from_form(vorlage.id)
    return redirect(url_for("ui.projekt_detail", projekt_id=projekt.id))


# ---- PMO: organisationsweite Vorgaben ---------------------------------- #

@bp.get("/pmo")
@permission_required("read")
def pmo():
    """PMO-Bereich: organisationsweite Präsentationsvorlage für alle Projekte.
    Aktuell für alle Benutzer der Organisationseinheit zugänglich; eine eigene
    PMO-Rolle kann später darauf aufsetzen."""
    user = current_user()
    svc = current_app.projekt_service
    vorlage = svc.org_vorlage(user.org_id)
    methoden_vorlage = svc.org_methoden_vorlage(user.org_id)
    methoden_report = _methoden_vorlage_report(methoden_vorlage)
    return render_template("pmo.html", vorlage=vorlage,
                           methoden_vorlage=methoden_vorlage,
                           methoden_report=methoden_report,
                           methoden_editor=_methoden_editor(methoden_vorlage),
                           methoden_mapping_url=url_for("ui.pmo_methoden_mapping"),
                           kostensatz=svc.org_kostensatz(user.org_id))


@bp.post("/pmo/kostensatz")
@permission_required("write")
def pmo_kostensatz():
    """Speichert die organisationsweiten Kostensätze (Standard für alle Projekte)."""
    user = current_user()
    current_app.projekt_service.set_kostensatz(
        satz_intern=request.form.get("satz_intern"),
        satz_extern=request.form.get("satz_extern"),
        einheit=request.form.get("einheit", "tag"),
        stunden_pro_tag=request.form.get("stunden_pro_tag") or 8,
        org_id=user.org_id,
    )
    return redirect(url_for("ui.pmo"))


@bp.post("/pmo/branding")
@permission_required("write")
def pmo_branding_farben():
    """Speichert die UI-Farben der Organisationseinheit (Hex #RRGGBB)."""
    user = current_user()
    try:
        current_app.auth_service.set_branding_farben(
            user.org_id,
            kopfleiste=request.form.get("kopfleiste_farbe"),
            akzent=request.form.get("akzent_farbe"),
            primaer=request.form.get("primaer_farbe"),
        )
    except ValueError:
        abort(400)
    return redirect(url_for("ui.pmo"))


@bp.post("/pmo/branding/logo")
@permission_required("write")
def pmo_branding_logo():
    """Lädt das Logo der Organisationseinheit hoch (PNG/JPG, Base64-JSON)."""
    payload = request.get_json(silent=True) or {}
    filename = (payload.get("filename") or "").strip()
    if not filename.lower().endswith((".png", ".jpg", ".jpeg")):
        return jsonify({"error": "Nur PNG- oder JPG-Dateien sind erlaubt."}), 400
    try:
        data = base64.b64decode(payload.get("data") or "")
    except Exception:  # noqa: BLE001 – kaputtes Base64 wie "keine Daten" behandeln
        data = b""
    if not data:
        return jsonify({"error": "Keine Dateidaten empfangen."}), 400
    if len(data) > 2 * 1024 * 1024:
        return jsonify({"error": "Logo zu gross (max. 2 MB)."}), 400
    if data.startswith(b"\x89PNG"):
        mimetype = "image/png"
    elif data.startswith(b"\xff\xd8\xff"):
        mimetype = "image/jpeg"
    else:
        return jsonify({"error": "Die Datei ist kein gültiges PNG-/JPG-Bild."}), 400
    user = current_user()
    current_app.auth_service.set_branding_logo(user.org_id, filename, data, mimetype)
    return jsonify({"ok": True})


@bp.post("/pmo/branding/reset")
@permission_required("write")
def pmo_branding_reset():
    """Setzt Logo und Farben auf das Standard-Erscheinungsbild zurück."""
    current_app.auth_service.reset_branding(current_user().org_id)
    return redirect(url_for("ui.pmo"))


@bp.get("/branding/logo")
@login_required
def branding_logo():
    """Liefert das Logo der eigenen Organisationseinheit (mandantengetrennt)."""
    user = current_user()
    branding = (current_app.auth_service.get_branding(user.org_id)
                if user.org_id else None)
    if not branding or not branding.logo_filename:
        abort(404)
    return send_file(io.BytesIO(branding.logo_data),
                     mimetype=branding.logo_mimetype or "image/png")


@bp.post("/pmo/vorlage")
@permission_required("write")
def pmo_vorlage_upload():
    """Lädt die PMO-Präsentationsvorlage der Organisationseinheit hoch
    (gilt für alle Projekte ohne eigene Projekt-Vorlage)."""
    filename, data = _json_upload(".pptx")
    if filename is None:
        return jsonify({"error": data}), 400
    user = current_user()
    current_app.projekt_service.add_vorlage(
        filename, data,
        org_id=user.org_id,
        projekt_id=None,
        uploaded_by=getattr(user, "email", None),
    )
    return jsonify({"ok": True})


@bp.post("/pmo/methoden-vorlage")
@permission_required("write")
def pmo_methoden_vorlage_upload():
    """Lädt die organisationsweite Word-Vorlage (.docx/.dotx) hoch. Aus ihrer
    Kapitelstruktur leitet HERMES PIA das Interview ab; einzelne Projekte können
    sie mit einer eigenen Vorlage übersteuern."""
    filename, data = _json_upload((".docx", ".dotx"))
    if filename is None:
        return jsonify({"error": data}), 400
    user = current_user()
    current_app.projekt_service.add_methoden_vorlage(
        filename, data,
        org_id=user.org_id,
        projekt_id=None,
        uploaded_by=getattr(user, "email", None),
    )
    return jsonify({"ok": True})


@bp.post("/pmo/methoden-vorlage/zuordnung")
@permission_required("write")
def pmo_methoden_mapping():
    """Speichert die bestätigte Kapitel-Zuordnung der organisationsweiten Wortvorlage."""
    vorlage = current_app.projekt_service.org_methoden_vorlage(current_user().org_id)
    if vorlage is None:
        abort(404)
    _save_mapping_from_form(vorlage.id)
    return redirect(url_for("ui.pmo"))


@bp.get("/projekt/<int:projekt_id>/ergebnis/<int:ergebnis_id>/praesentation/<path:filename>")
@permission_required("read")
def ergebnis_praesentation(projekt_id, ergebnis_id, filename):
    """Generiert die Präsentation für Auftraggeber/Projektausschuss aus dem
    zuletzt hochgeladenen freigabebereiten PIA (auf Basis der Vorlage).
    Dateiname in der URL (Proxy verschluckt Content-Disposition)."""
    projekt = _load_ergebnis(projekt_id, ergebnis_id)
    svc = current_app.projekt_service
    dok = svc.latest_dokument(ergebnis_id, art="freigabe")
    if not dok:
        return ("Bitte zuerst den freigabebereiten PIA (.docx) hochladen – "
                "die Präsentation wird aus dessen Inhalt erstellt."), 400
    vorlage = svc.resolve_vorlage(projekt)
    buf = current_app.praesentation_service.generate_from_docx(
        dok.data,
        template_bytes=vorlage.data if vorlage else None,
        fallback_name=projekt.name,
        datum=date.today().strftime("%d.%m.%Y"),
    )
    return send_file(
        buf,
        mimetype="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        as_attachment=True,
        download_name=filename,
    )


@bp.get("/projekt/<int:projekt_id>/ergebnis/<int:ergebnis_id>/projektplan/<fmt>/<path:filename>")
@permission_required("read")
def ergebnis_projektplan(projekt_id, ergebnis_id, fmt, filename):
    """Projektplan aus dem hochgeladenen PIA – als MS-Project-XML oder Excel.
    Dateiname in der URL (Proxy verschluckt Content-Disposition)."""
    if fmt not in ("msproject", "excel"):
        abort(404)
    projekt = _load_ergebnis(projekt_id, ergebnis_id)
    dok = current_app.projekt_service.latest_dokument(ergebnis_id, art="freigabe")
    if not dok:
        return ("Bitte zuerst den freigabebereiten PIA (.docx) hochladen – "
                "der Projektplan wird aus dessen Terminen erstellt."), 400
    from app.domains.praesentation import projektplan
    from app.domains.praesentation.parser import parse_pia
    eintraege = projektplan.plan_eintraege(parse_pia(dok.data).get("termine"))
    if not eintraege:
        return ("Der hochgeladene PIA enthält keine datierten Termine – "
                "bitte Kapitel «Ergebnisse und Termine» prüfen."), 400
    name = projekt.name or "Projekt"
    if fmt == "excel":
        # Zeiteinheit wählbar (?einheit=tag|woche|monat|quartal|semester|jahr);
        # ohne bzw. bei ungültiger Angabe gilt der Vorschlag von HERMES PIA.
        einheit = request.args.get("einheit") or None
        data = projektplan.build_excel(eintraege, name, einheit=einheit)
        mimetype = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        data = projektplan.build_msproject_xml(eintraege, name)
        mimetype = "application/xml"
    return send_file(io.BytesIO(data), mimetype=mimetype, as_attachment=True,
                     download_name=filename)


@bp.post("/projekt/<int:projekt_id>/delete")
@permission_required("delete")
def projekt_delete(projekt_id):
    """Löscht ein Projekt samt Struktur und enthaltenen PIA-Ergebnissen."""
    _load_projekt(projekt_id)
    svc = current_app.projekt_service
    for erg in svc.ergebnisse(projekt_id):
        s = current_app.interview_service.session_for_ergebnis(erg.id)
        if s:
            current_app.interview_service.delete_session(s.id)
    svc.delete_projekt(projekt_id)
    return redirect(url_for("ui.index"))


@bp.get("/interview/<int:session_id>/edit/<section_id>")
@permission_required("write")
def interview_edit(session_id, section_id):
    """Bearbeiten: Freitext mit vorgeladenem Inhalt; Tabellen werden zurückgesetzt."""
    svc = current_app.interview_service
    session = _load_session(session_id)
    section = svc._section_by_id(svc._effective_method(session), section_id)
    if not section:
        return "Abschnitt nicht gefunden", 404
    if section.get("type") == "free_text":
        return render_template("edit_section.html", session=session, section=section,
                               text=svc.section_text(session, section_id))
    svc.reset_section(session_id, section_id)
    return redirect(url_for("ui.interview_workspace", session_id=session_id))


@bp.post("/interview/<int:session_id>/edit/<section_id>")
@permission_required("write")
def interview_edit_save(session_id, section_id):
    """Speichert den bearbeiteten Freitext und lässt ihn neu formulieren."""
    _load_session(session_id)
    raw_text = request.form.get("raw_text", "").strip()
    current_app.interview_service.update_free_text(session_id, section_id, raw_text)
    return redirect(url_for("ui.interview_workspace", session_id=session_id))


# ---- Versionsverwaltung ---------------------------------------------- #

@bp.get("/interview/<int:session_id>/version")
@permission_required("write")
def interview_version(session_id):
    svc = current_app.interview_service
    session = _load_session(session_id)
    info = svc.version_info(session)
    return render_template(
        "version_bump.html", session=session, info=info,
        titel=session.project_name, dokumentname="PIA",
        zurueck_url=url_for("ui.interview_workspace", session_id=session.id))


def _safe_filename(name_part):
    cleaned = "".join(c if c.isalnum() or c in " -_" else "_" for c in name_part).strip()
    return cleaned.replace(" ", "_")


@bp.post("/interview/<int:session_id>/version")
@permission_required("write")
def interview_version_post(session_id):
    svc = current_app.interview_service
    session = _load_session(session_id)

    bump_type = request.form.get("bump_type", "minor")
    bemerkungen = request.form.get("bemerkungen", "").strip()
    new_version, _ = svc.record_version_bump(
        session_id, bump_type=bump_type,
        projektleiter=session.created_by or "", bemerkungen=bemerkungen,
    )

    safe_name = _safe_filename(session.project_name or "Projekt")
    filename = f"{safe_name}_PIA_v{new_version}.docx"
    return redirect(url_for("ui.interview_download", session_id=session_id, filename=filename))


@bp.get("/interview/<int:session_id>/download/<path:filename>")
@permission_required("read")
def interview_download(session_id, filename):
    """Generiert den PIA aus dem aktuellen Stand und liefert ihn als Download."""
    session = _load_session(session_id)
    # Erzeugt wird an EINER Stelle - derselbe Weg, den der Testlauf geht.
    buf, answers = pia_dokument.erzeuge(
        session, current_app.interview_service, current_app.generation_service,
        current_app.projekt_service)

    # VERBINDLICHE Pruefung vor der Ausgabe (Briefing Abschnitt 4.1):
    # Muss-Befunde verhindern die Ausgabe, Vorbehalte werden als Auflage gefuehrt.
    # Die Dok-Ebene laeuft mit - Platzhalter und Hilfetexte zeigen sich erst hier.
    ergebnis = _pruefe_vor_ausgabe(session, answers, buf)
    if not ergebnis.ausgabe_moeglich and not request.args.get("trotzdem"):
        return render_template("qualitaet_blockiert.html", session=session,
                               ergebnis=ergebnis, filename=filename), 409
    return send_file(
        buf,
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        as_attachment=True,
        download_name=filename,
    )


def _pruefe_vor_ausgabe(session, answers, buf):
    """Daten- UND Dokumentebene pruefen, ohne den Puffer zu verbrauchen."""
    dok = None
    try:
        from docx import Document
        buf.seek(0)
        dok = Document(buf)
    except Exception:      # noqa: BLE001 - Dok-Ebene ist optional
        dok = None
    finally:
        buf.seek(0)
    return pruefe_session(session, answers=answers,
                          tarife=_tarife_for_session(session), dokument=dok)


# ===================================================================== #
# Verwaltung: Betreiber (Super-Admin) – Organisationseinheiten          #
# ===================================================================== #

@bp.get("/admin/organisationen")
@roles_required(ROLE_SUPER_ADMIN)
def admin_orgs():
    auth = current_app.auth_service
    orgs = auth.list_orgs()
    org_users = {o.id: auth.list_users(o.id) for o in orgs}
    return render_template("admin_orgs.html", orgs=orgs, org_users=org_users)


@bp.post("/admin/organisationen/neu")
@roles_required(ROLE_SUPER_ADMIN)
def admin_org_create():
    name = request.form.get("name", "").strip()
    if name:
        current_app.auth_service.create_org(name)
    return redirect(url_for("ui.admin_orgs"))


@bp.post("/admin/organisationen/<int:org_id>/benutzer")
@roles_required(ROLE_SUPER_ADMIN)
def admin_org_user_create(org_id):
    """Legt einen Benutzer ODER Org-Admin an (Rollenwahl + Rechte)."""
    auth = current_app.auth_service
    email = request.form.get("email", "").strip()
    password = request.form.get("password", "")
    name = request.form.get("name", "").strip()
    is_admin = request.form.get("role") == "admin"
    if email and password and not auth.get_user_by_email(email):
        if is_admin:
            auth.create_user(email, password, name=name, role=ROLE_ORG_ADMIN, org_id=org_id,
                             can_read=True, can_write=True, can_delete=True)
        else:
            auth.create_user(email, password, name=name, role=ROLE_MEMBER, org_id=org_id,
                             can_read=request.form.get("can_read") == "on",
                             can_write=request.form.get("can_write") == "on",
                             can_delete=request.form.get("can_delete") == "on")
    return redirect(url_for("ui.admin_orgs"))


@bp.post("/admin/organisationen/benutzer/<int:user_id>/rolle")
@roles_required(ROLE_SUPER_ADMIN)
def admin_org_user_role(user_id):
    role = ROLE_ORG_ADMIN if request.form.get("role") == "admin" else ROLE_MEMBER
    current_app.auth_service.set_role(user_id, role)
    return redirect(url_for("ui.admin_orgs"))


@bp.post("/admin/organisationen/benutzer/<int:user_id>/rechte")
@roles_required(ROLE_SUPER_ADMIN)
def admin_org_user_permissions(user_id):
    current_app.auth_service.set_permissions(
        user_id,
        request.form.get("can_read") == "on",
        request.form.get("can_write") == "on",
        request.form.get("can_delete") == "on",
    )
    return redirect(url_for("ui.admin_orgs"))


@bp.post("/admin/organisationen/benutzer/<int:user_id>/loeschen")
@roles_required(ROLE_SUPER_ADMIN)
def admin_org_user_delete(user_id):
    current_app.auth_service.delete_user(user_id)
    return redirect(url_for("ui.admin_orgs"))


# ===================================================================== #
# Verwaltung: Org-Admin – Benutzer der eigenen Organisationseinheit      #
# ===================================================================== #

@bp.get("/admin/benutzer")
@roles_required(ROLE_ORG_ADMIN)
def admin_users():
    auth = current_app.auth_service
    user = current_user()
    org = auth.get_org(user.org_id)
    users = auth.list_users(user.org_id)
    return render_template("admin_users.html", org=org, users=users)


@bp.post("/admin/benutzer/neu")
@roles_required(ROLE_ORG_ADMIN)
def admin_user_create():
    auth = current_app.auth_service
    user = current_user()
    email = request.form.get("email", "").strip()
    password = request.form.get("password", "")
    name = request.form.get("name", "").strip()
    if email and password and not auth.get_user_by_email(email):
        auth.create_user(
            email, password, name=name, org_id=user.org_id,
            can_read=request.form.get("can_read") == "on",
            can_write=request.form.get("can_write") == "on",
            can_delete=request.form.get("can_delete") == "on",
        )
    return redirect(url_for("ui.admin_users"))


@bp.post("/admin/benutzer/<int:user_id>/rechte")
@roles_required(ROLE_ORG_ADMIN)
def admin_user_permissions(user_id):
    auth = current_app.auth_service
    target = auth.get_user(user_id)
    # Nur Benutzer der eigenen Organisationseinheit verwalten.
    if target and target.org_id == current_user().org_id:
        auth.set_permissions(
            user_id,
            request.form.get("can_read") == "on",
            request.form.get("can_write") == "on",
            request.form.get("can_delete") == "on",
        )
    return redirect(url_for("ui.admin_users"))


@bp.post("/admin/benutzer/<int:user_id>/loeschen")
@roles_required(ROLE_ORG_ADMIN)
def admin_user_delete(user_id):
    auth = current_app.auth_service
    target = auth.get_user(user_id)
    if target and target.org_id == current_user().org_id:
        auth.delete_user(user_id)
    return redirect(url_for("ui.admin_users"))


@bp.post("/admin/benutzer/<int:user_id>/passwort")
@roles_required(ROLE_SUPER_ADMIN, ROLE_ORG_ADMIN)
def admin_reset_password(user_id):
    """Admin setzt das Passwort eines Benutzers zurück.
    Hauptadmin: alle. Org-Admin: nur Benutzer der eigenen Organisation."""
    auth = current_app.auth_service
    actor = current_user()
    target = auth.get_user(user_id)
    new_password = request.form.get("new_password", "")
    if target and new_password:
        allowed = actor.is_super_admin or (
            actor.is_org_admin
            and target.org_id == actor.org_id
            and not target.is_super_admin
        )
        if allowed:
            auth.reset_password(user_id, new_password)
    return redirect(url_for("ui.admin_orgs") if actor.is_super_admin
                    else url_for("ui.admin_users"))


# ---- Pseudonymisierungsschicht: Blockierfall ------------------------------ #
#
# Wird ein Aufruf angehalten (HTTP 409), MUSS der Nutzer das sehen. Wuerde der
# Fehler still geschluckt, saehe er nur ein schlechteres Ergebnis und hielte es
# fuer ein Qualitaetsproblem des Modells (ANBINDUNG.md 6.2).
#
# Der Dienst speichert den blockierten Text bewusst NICHT -- sonst legte er
# ausgerechnet von den heikelsten Texten eine Halde an. Deshalb haelt die
# Anwendung die Formularfelder und sendet sie nach dem Entscheid unveraendert
# erneut (ANBINDUNG.md 5).

@bp.before_app_request
def _pseudo_kontext_setzen():
    """Mandant und Projekt fuer JEDE Anfrage setzen -- nicht je Aufrufstelle.

    Die vier dekorierten Einstiegspunkte im Interview deckten die Ergebnis-Module
    (Rechtsgrundlagen, Schutzbedarf, Praesentation) und den Nachweis NICHT ab;
    dort ging `X-Pseudo-Projekt` leer raus und der Dienst antwortete zu Recht mit
    400. Hier greift es fuer alle Routen, auch fuer kuenftige.
    """
    benutzer = current_user()
    marken = setze_kontext(
        projekt=projekt_schluessel(request.view_args),
        mandant=getattr(benutzer, "org_id", None) if benutzer else None,
    )
    g._pseudo_marken = marken


@bp.teardown_app_request
def _pseudo_kontext_loesen(_fehler=None):
    # Ohne Zuruecksetzen truege die naechste Anfrage auf demselben Thread den
    # Mandanten der vorherigen -- Zuordnungen landeten im falschen Topf.
    marken = g.pop("_pseudo_marken", None)
    if marken:
        loese_kontext(marken)


@bp.app_errorhandler(PseudonymisierungBlockiert)
def _pseudo_blockiert(exc):
    # request.form ist auch hier noch verfuegbar: der Originalaufruf wird daraus
    # spaeter Feld fuer Feld unveraendert wiederhergestellt.
    #
    # Die Methode MUSS mitgefuehrt werden: nicht jeder LLM-Aufruf haengt an einem
    # Formular. Die Praesentation etwa wird per GET erzeugt -- ein stures POST-
    # Replay liefe dort in einen 405.
    felder = [(k, v) for k, v in request.form.items(multi=True)]
    ziel = request.full_path.rstrip("?") if request.method == "GET" else request.path
    return render_template("pseudo_blockiert.html",
                           befunde=exc.befunde, vorgang_id=exc.vorgang_id,
                           ziel=ziel, methode=request.method,
                           formfelder=felder, fehler=""), 409


@bp.app_errorhandler(RueckersetzungUnvollstaendig)
def _pseudo_rueckersetzung(exc):
    """HTTP 502 ist eine Schutzabschaltung, kein Netzwerkfehler.

    Es wird KEIN Text uebernommen und nicht stillschweigend wiederholt."""
    return render_template("pseudo_fehler.html", meldung=str(exc), art="rueckersetzung"), 502


@bp.app_errorhandler(PseudoNichtErreichbar)
def _pseudo_weg(exc):
    return render_template("pseudo_fehler.html", meldung=str(exc), art="nicht_erreichbar"), 503


@bp.app_errorhandler(PseudoKontextFehlt)
@bp.app_errorhandler(PseudoKeinSchluessel)
def _pseudo_konfiguration(exc):
    return render_template("pseudo_fehler.html", meldung=str(exc), art="konfiguration"), 500


@bp.app_errorhandler(PseudoAnbieterFehler)
def _pseudo_anbieter(exc):
    """Der Anbieter hat abgelehnt. OB der Text dabei geschuetzt war, haengt am
    Modus - die Seite darf das nicht pauschal behaupten."""
    current_app.logger.error("Anbieter hat abgelehnt (%s): %s",
                             exc.status, exc.anbieter_meldung or exc)
    return render_template("pseudo_fehler.html", art="anbieter", meldung=str(exc),
                           anbieter_meldung=exc.anbieter_meldung,
                           pseudo_aus=_pseudonymisierung_aus()), 502


@bp.app_errorhandler(PseudoAntwortUnlesbar)
@bp.app_errorhandler(PseudoUnerwarteteAntwort)
def _pseudo_antwort_unlesbar(exc):
    """Lieber ein sichtbarer Fehler als ein Dokument mit dem rohen Diktat darin."""
    current_app.logger.warning("Antwort der Pseudonymisierungsschicht unbrauchbar: %s", exc)
    return render_template("pseudo_fehler.html", meldung=str(exc), art="antwort"), 502


@bp.post("/pseudo/entscheide")
@permission_required("write")
def pseudo_entscheide():
    """Nimmt die Entscheide entgegen und wiederholt danach den Originalaufruf."""
    basis = current_app.config.get("PSEUDO_BASIS_URL", "")
    ziel = request.form.get("ziel", "")
    urheber = getattr(current_user(), "email", "") or ""

    fehler = []
    for befund_id in request.form.getlist("befund_id"):
        entscheid = request.form.get(f"entscheid__{befund_id}", "")
        muster = request.form.get(f"muster__{befund_id}", "")
        if not entscheid:
            fehler.append(f"Befund {befund_id}: keine Entscheidung getroffen.")
            continue
        ok, meldung = entscheide(
            basis, befund_id, entscheid, muster,
            begruendung=request.form.get(f"begruendung__{befund_id}", ""),
            urheber=urheber,
        )
        if not ok:
            fehler.append(f"Befund {befund_id}: {meldung}")

    if fehler:
        # Bleibt ein Befund unentschieden, bleibt der Aufruf blockiert.
        # Es gibt bewusst kein "trotzdem senden".
        return render_template("pseudo_fehler.html", art="entscheid",
                               meldung=" ".join(fehler)), 400

    # Originalaufruf UNVERAENDERT wiederholen. Bewusst als echtes Replay im
    # Browser statt als interner Wiedereinstieg: so gelten Anmeldung, Rechte und
    # Fehlerbehandlung genau wie beim ersten Versuch.
    # `//` mit abfangen: '//example.com' ist protokollrelativ und fuehrte sonst
    # aus der Anwendung heraus.
    if not ziel.startswith("/") or ziel.startswith("//"):
        abort(400)                          # nur anwendungseigene Ziele
    methode = "GET" if request.form.get("methode") == "GET" else "POST"
    felder = [(k[len("orig__"):], v) for k, v in request.form.items(multi=True)
              if k.startswith("orig__")]
    if methode == "GET":
        return redirect(ziel)               # GET-Aufrufe tragen keinen Rumpf
    return render_template("pseudo_wiederholen.html", ziel=ziel, felder=felder)


# ---- Stufe 4: fachliche Pruefung aus Auftraggeber-Sicht ------------------ #
#
# EIGENER Aufruf, getrennt von der Erzeugung (Briefing 5.1). Der Pruefer schreibt
# nichts in den PIA: das Protokoll liegt in einer eigenen Tabelle, Vorschlaege
# werden angezeigt und nicht angewandt, die Empfehlung nie automatisch umgesetzt.

@bp.post("/interview/<int:session_id>/fachpruefung")
@permission_required("write")
def interview_fachpruefung(session_id):
    """Startet einen kapitelweisen Lauf. Die Schritte holt der Browser einzeln ab –
    so bleibt jeder Aufruf weit unter dem Worker-Zeitlimit."""
    session = _load_session(session_id)
    if not current_app.interview_service.llm:
        return render_template("pseudo_fehler.html", art="konfiguration",
                               meldung="Ohne Sprachmodell ist keine fachliche "
                                       "Prüfung möglich."), 500
    zeile = starte_fachpruefung(session)
    return redirect(url_for("ui.interview_fachpruefung_zeigen",
                            session_id=session_id, lauf=zeile.id))


@bp.post("/interview/<int:session_id>/fachpruefung/schritt")
@permission_required("write")
def interview_fachpruefung_schritt(session_id):
    """EIN Schritt (ein Kapitel oder die Gesamtwürdigung). Antwortet als JSON,
    damit der Browser den Fortschritt anzeigen kann."""
    session = _load_session(session_id)
    svc = current_app.interview_service
    answers = json.loads(session.answers_json or "{}")
    # Formular ODER JSON annehmen - multipart wird bewusst nicht verwendet
    # (der Hosting-Proxy laesst es nicht durch, siehe fachpruefung.html).
    rumpf = request.get_json(silent=True) or request.form
    # Dieser Endpunkt antwortet IMMER JSON – auch beim Absturz. Sonst schickt
    # der allgemeine Fehlerbehandler eine HTML-Seite, der Browser scheitert am
    # Parsen und meldet «Verbindung unterbrochen»: der echte Grund geht
    # verloren, und man sucht Stunden an der falschen Stelle.
    try:
        zustand, grund = fachpruefung_schritt(
            int(rumpf.get("pruefung_id", 0) or 0), session, svc.llm,
            answers=answers, tarife=_tarife_for_session(session),
            # OHNE Modellaufruf: als Evidenz zaehlt die deterministisch
            # abgeleitete Herkunft, nicht die ausformulierte Prosa. Damit
            # braucht dieser Schritt keine Modellzeit - der frueher noetige
            # neunte Aufruf war die Ursache des Abbruchs nach 30 s.
            nachweis_fn=lambda: svc.build_nachweis(session, answers,
                                                   mit_llm=False),
            tenant_id=getattr(session, "org_id", None))
    except Exception as e:      # noqa: BLE001 – der Grund muss zum Browser
        current_app.logger.exception("Prüfschritt abgestürzt")
        return jsonify({"fehler": f"{e.__class__.__name__}: {e}"}), 500
    if zustand is None:
        return jsonify({"fehler": grund or "Der Schritt ist fehlgeschlagen."}), 502
    return jsonify(zustand)


@bp.get("/interview/<int:session_id>/fachpruefung")
@permission_required("read")
def interview_fachpruefung_zeigen(session_id):
    session = _load_session(session_id)
    zeile = letzte_fachpruefung(session_id)
    protokoll = json.loads(zeile.protokoll_json) if zeile and zeile.protokoll_json else None
    from app.domains.qualitaet.auftraggeber import schritte as _schritte
    return render_template(
        "fachpruefung.html", session=session, pruefung=zeile, protokoll=protokoll,
        laeuft=bool(zeile and zeile.status != "fertig"),
        schrittnamen=_schritte(),
        versionen=json.loads(zeile.skill_versionen_json or "[]") if zeile else [],
        widersprueche={w["befund"]: w for w in
                       (json.loads(zeile.widersprueche_json or "[]") if zeile else [])},
    )


@bp.post("/interview/<int:session_id>/fachpruefung/widerspruch")
@permission_required("write")
def interview_fachpruefung_widerspruch(session_id):
    """Begruendete Ablehnung eines Befunds - sie wird FESTGEHALTEN, der Befund
    bleibt stehen (Briefing 5.1)."""
    _load_session(session_id)
    pruefung_id = int(request.form.get("pruefung_id", 0) or 0)
    index = int(request.form.get("befund", -1))
    begruendung = (request.form.get("begruendung", "") or "").strip()
    if pruefung_id and index >= 0 and begruendung:
        widerspruch(pruefung_id, index, begruendung,
                    urheber=getattr(current_user(), "email", "") or "")
    return redirect(url_for("ui.interview_fachpruefung_zeigen", session_id=session_id))
