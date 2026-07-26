"""Anbindung der Invarianten-Prüfung an eine PIA-Session.

Sammelt aus der Session zusammen, was die Regeln brauchen (Tarife, Phasendauer,
Änderungskontrolle) und ruft die Prüfung. Bewusst NUR lesend: die Prüfung ist
vom Erzeugen getrennt (Briefing, Leitplanken).
"""
import json
import logging

from app.domains.qualitaet.pruefung import pruefe

log = logging.getLogger("hermes.qualitaet")


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


# ---- Kapitelweiser Lauf der Fachpruefung --------------------------------- #

def starte_fachpruefung(session):
    """Legt einen neuen Lauf an (Schritt 0). Ein alter Lauf bleibt erhalten."""
    import json as _json

    from app.domains.qualitaet.models import PiaPruefung
    from app.shared.database import SessionLocal

    db = SessionLocal()
    zeile = PiaPruefung(session_id=session.id,
                        pia_version=getattr(session, "doc_version", None),
                        status="laufend", schritt=0,
                        teilbefunde_json=_json.dumps([]))
    db.add(zeile)
    db.commit()
    db.refresh(zeile)
    return zeile


def fachpruefung_schritt(pruefung_id, session, llm, answers=None, tarife=None,
                         nachweis_fn=None, tenant_id=None):
    """Führt GENAU EINEN Schritt aus. Rückgabe: (zustand, grund).

    So bleibt jeder HTTP-Aufruf kurz – das Worker-Zeitlimit ist damit kein Thema
    mehr, und die Ausgabelänge muss nicht gedeckelt werden.

    `nachweis_fn` ist bewusst eine FUNKTION und wird nur im Syntheseschritt
    gerufen: der Nachweis kostet selbst einen LLM-Aufruf (4096 Token). Vor jedem
    Kapitel berechnet, sprengte er zusammen mit dem Kapitelaufruf das
    Worker-Zeitlimit – und war achtmal umsonst.
    """
    import json as _json

    from app.domains.qualitaet.auftraggeber import (
        GRUPPEN, baue_protokoll, pruefe_kapitel, schritte, synthese,
    )
    from app.domains.qualitaet.models import PiaPruefung
    from app.shared.database import SessionLocal

    import time as _time
    t0 = _time.monotonic()

    def _takt(was):
        # Bewusst WARNING: bei einem Haenger muss im Protokoll stehen, WELCHER
        # Abschnitt die Zeit verbraucht - sonst raet man wieder.
        log.warning("Fachpruefung-Schritt: %s nach %.1fs", was, _time.monotonic() - t0)

    db = SessionLocal()
    zeile = db.get(PiaPruefung, pruefung_id)
    if zeile is None:
        return None, "Der Prüflauf wurde nicht gefunden."
    if zeile.status == "fertig":
        return _zustand(zeile), ""
    _takt("Lauf geladen")

    if answers is None:
        answers = _json.loads(getattr(session, "answers_json", None) or "{}")
    invarianten = pruefe_session(session, answers=answers, tarife=tarife)
    _takt("Invarianten geprueft")
    teile = _json.loads(zeile.teilbefunde_json or "[]")
    index = zeile.schritt or 0

    if index < len(GRUPPEN):
        teil, versionen, grund = pruefe_kapitel(
            answers, llm, index, invarianten=invarianten, tenant_id=tenant_id)
        _takt(f"Kapitel {index} geprueft")
        if teil is None:
            return None, grund
        teile.append(teil)
        zeile.teilbefunde_json = _json.dumps(teile, ensure_ascii=False)
        zeile.skill_versionen_json = _json.dumps(versionen, ensure_ascii=False)
        zeile.schritt = index + 1
        db.commit()
        return _zustand(zeile), ""

    # Letzter Schritt: Gesamtwürdigung.
    nachweis = None
    if nachweis_fn is not None:
        try:
            nachweis = nachweis_fn()
        except Exception:      # noqa: BLE001 – ohne Nachweis laeuft die Synthese weiter
            log.warning("Nachweis nicht verfuegbar – Synthese ohne Evidenzgrundlage.")
    gesamt, versionen, grund = synthese(
        teile, answers, llm, invarianten=invarianten, nachweis=nachweis,
        tenant_id=tenant_id)
    if gesamt is None:
        return None, grund
    protokoll = baue_protokoll(teile, gesamt)
    zeile.protokoll_json = _json.dumps(protokoll, ensure_ascii=False)
    zeile.empfehlung = protokoll.get("empfehlung")
    zeile.skill_versionen_json = _json.dumps(versionen, ensure_ascii=False)
    zeile.schritt = len(schritte())
    zeile.status = "fertig"
    db.commit()
    return _zustand(zeile), ""


def _zustand(zeile):
    from app.domains.qualitaet.auftraggeber import schritte
    namen = schritte()
    index = min(zeile.schritt or 0, len(namen) - 1)
    return {
        "pruefung_id": zeile.id,
        "schritt": zeile.schritt or 0,
        "gesamt": len(namen),
        "naechstes": namen[index] if zeile.status != "fertig" else "",
        "fertig": zeile.status == "fertig",
    }
