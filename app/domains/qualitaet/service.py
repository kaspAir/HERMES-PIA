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
