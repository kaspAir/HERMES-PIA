"""Anbindung der Invarianten-Prüfung an eine PIA-Session.

Sammelt aus der Session zusammen, was die Regeln brauchen (Tarife, Phasendauer,
Änderungskontrolle) und ruft die Prüfung. Bewusst NUR lesend: die Prüfung ist
vom Erzeugen getrennt (Briefing, Leitplanken).
"""
import json

from app.domains.qualitaet.pruefung import pruefe


def _phasendauer_monate(answers):
    """Geplante Phasendauer in Monaten – aus dem, was das Interview kennt."""
    try:
        from app.domains.interview.service import _phase_dauer_wochen
        wochen = _phase_dauer_wochen(answers or {})
        if wochen:
            return max(1, int(round(wochen / 4.345)))
    except Exception:      # noqa: BLE001 – ohne Dauer laufen die Regeln ohne sie
        pass
    return None


def pruefe_session(session, answers=None, tarife=None, dokument=None,
                   standardtext=None, zusatzrollen=None):
    """Invarianten-Prüfung für eine Interview-Session.

    `dokument` optional: dann laufen zusätzlich die Regeln der Ebene «Dok».
    """
    if answers is None:
        answers = json.loads(getattr(session, "answers_json", None) or "{}")
    return pruefe(
        answers,
        session=session,
        tarife=tarife,
        dokument=dokument,
        standardtext=standardtext,
        zusatzrollen=zusatzrollen,
        phasendauer_monate=_phasendauer_monate(answers),
    )


# ---- Stufe 4: fachliche Prüfung aus Auftraggeber-Sicht ------------------- #

def fuehre_fachpruefung(session, llm, answers=None, tarife=None, nachweis=None,
                        tenant_id=None):
    """Fachliche Prüfung als EIGENER Aufruf – getrennt von der Erzeugung.

    Die Invarianten-Befunde gehen als Datenstruktur mit, damit der Prüfer sie
    übernimmt statt wiederholt. Speichert das Protokoll NEBEN dem PIA (eigene
    Tabelle) – der Prüfer schreibt nichts hinein.
    """
    import json as _json

    from app.domains.qualitaet.auftraggeber import pruefe_fachlich
    from app.domains.qualitaet.models import PiaPruefung
    from app.shared.database import SessionLocal

    if answers is None:
        answers = _json.loads(getattr(session, "answers_json", None) or "{}")
    invarianten = pruefe_session(session, answers=answers, tarife=tarife)
    protokoll, versionen, grund = pruefe_fachlich(
        answers, llm, invarianten=invarianten, nachweis=nachweis, tenant_id=tenant_id)
    if protokoll is None:
        return None, invarianten, grund

    db = SessionLocal()
    zeile = PiaPruefung(
        session_id=session.id,
        pia_version=getattr(session, "doc_version", None),
        protokoll_json=_json.dumps(protokoll, ensure_ascii=False),
        empfehlung=protokoll.get("empfehlung"),
        skill_versionen_json=_json.dumps(versionen, ensure_ascii=False),
    )
    db.add(zeile)
    db.commit()
    db.refresh(zeile)
    return zeile, invarianten, ""


def letzte_fachpruefung(session_id):
    from app.domains.qualitaet.models import PiaPruefung
    from app.shared.database import SessionLocal
    db = SessionLocal()
    return (db.query(PiaPruefung)
            .filter(PiaPruefung.session_id == session_id)
            .order_by(PiaPruefung.id.desc()).first())


def widerspruch(pruefung_id, befund_index, begruendung, urheber=""):
    """Begründete Ablehnung eines Befunds – wird festgehalten, nicht wegdiskutiert.

    Briefing 5.1: «Der Nutzer kann einen Befund begründet ablehnen; die Ablehnung
    wird im Nachweis festgehalten.» Der Befund BLEIBT im Protokoll stehen.
    """
    import json as _json

    from app.domains.qualitaet.models import PiaPruefung
    from app.shared.database import SessionLocal

    db = SessionLocal()
    zeile = db.get(PiaPruefung, pruefung_id)
    if zeile is None:
        return None
    bestand = _json.loads(zeile.widersprueche_json or "[]")
    bestand.append({"befund": befund_index, "begruendung": begruendung,
                    "urheber": urheber})
    zeile.widersprueche_json = _json.dumps(bestand, ensure_ascii=False)
    db.commit()
    return zeile
