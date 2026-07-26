"""Fachliche Prüfung des PIA aus Auftraggeber-Sicht – Stufe 4.

Der PIA ist die Vereinbarung zwischen Auftraggeber und Projektleiter, geschrieben
wird er vom Projektleiter. Die zweite Seite fehlt strukturell; diese Prüfung
nimmt sie ein.

**Die tragende Invariante dieser Stufe: der Prüfer ist nicht der Erzeuger.**
Deshalb ist das ein EIGENER Aufruf mit eigenem System-Prompt, der den Skill
`pia-pruefung-auftraggeber` lädt statt ihn im Code nachzubauen – und der nichts
in den PIA schreibt. Vorschläge bleiben Vorschläge.

Abgrenzung zur Invarianten-Prüfung (Stufe 1): die prüft FORM (deterministisch,
ohne Sprachmodell), diese prüft FACHLICHKEIT (Urteil). Die Regelbefunde werden
als DATENSTRUKTUR übergeben, damit der Prüfer sie übernimmt statt wiederholt –
sonst erstickt das fachliche Urteil in Formalien.
"""
import json
import logging
import re

from app.domains.llm.errors import PseudoFehler
from app.domains.skills import compose_system, load_skills

log = logging.getLogger("hermes.pruefung")

SKILL = "pia-pruefung-auftraggeber"
BEREICH = "projektinitialisierungsauftrag"     # = applies_to des Skills

EMPFEHLUNGEN = ("freigebbar", "mit vorbehalt", "nicht freigebbar")

# Diese Pruefung erzeugt ein langes, strukturiertes Protokoll und ist damit der
# TEUERSTE Aufruf der Anwendung. Gunicorn erlaubt je Anfrage 120 s
# (deploy/hermes_ctl.sh --timeout 120); wird das ueberschritten, ERSCHIESST er
# den Worker – dann greift keine Fehlerseite mehr, weil der Prozess stirbt.
# Deshalb bewusst darunter bleiben und lieber ein knapperes Protokoll verlangen:
MAX_TOKENS = 2500          # 4000 dauerte regelmaessig laenger als das Worker-Limit
ZEITLIMIT = 95             # Sekunden, mit Luft fuer die Fehlerseite
# Obergrenze der Ausgabe. Das ist eine TECHNISCHE Grenze (Zeit/Token), nicht die
# Proportionalitaet, die die Methode meint - dort folgt die Laenge dem BEFUND.
# Deshalb MUSS eine erreichte Grenze sich selbst melden (weitere_befunde), sonst
# sieht eine gekuerzte Pruefung aus wie eine vollstaendige.
MAX_BEFUNDE = 8
MAX_FRAGEN = 4

# Der System-Prompt haelt NUR das Ausgabeformat und die Grenzen fest. Die Methode
# – Haltung, Leitfragen, Prüfraster – kommt vollstaendig aus dem Skill.
SYSTEM = (
    "Du prüfst einen HERMES-2022-Projektinitialisierungsauftrag aus der Sicht des "
    "AUFTRAGGEBERS. Du berätst und forderst heraus – du entscheidest nicht.\n"
    "HARTE GRENZEN:\n"
    "- Du schreibst den PIA NICHT um. Formulierungen darfst du VORSCHLAGEN.\n"
    "- Du sprichst NIE eine Freigabe aus, nur eine Empfehlung an den Auftraggeber.\n"
    "- Formfehler, die dir als bereits gefunden übergeben werden, meldest du NICHT "
    "erneut – du zählst sie nur.\n"
    "- Du erfindest nichts: keine HERMES-Regeln, keine Rechtsaussagen, keine Zahlen. "
    "Unsicheres benennst du als unsicher.\n"
    "- Du bleibst proportional: ein kleiner, sauberer PIA verdient eine kurze Prüfung.\n"
    "Antworte AUSSCHLIESSLICH mit validem JSON nach dem vorgegebenen Schema."
)

_SCHEMA = (
    '{"gegenstand":{"umfang":"","nicht_geprueft":""},'
    '"befunde":[{"kapitel":"","kriterium":"","feststellung":"",'
    '"gewicht":"Muss|Vorbehalt|Hinweis","vorschlag":""}],'
    '"gut":[""],'
    '"querbezuege":[{"feststellung":"","gewicht":"Muss|Vorbehalt|Hinweis"}],'
    '"evidenz":[{"feststellung":"","gewicht":"Muss|Vorbehalt|Hinweis"}],'
    '"herausforderung":[{"frage":"","begruendung":""}],'
    '"empfehlung":"freigebbar|mit vorbehalt|nicht freigebbar",'
    '"begruendung":"",'
    '"auflagen":[{"offen":"","wer":"","bis_wann":""}],'
    '"confidence":{"stufe":"hoch|mittel|tief","begrenzung":""},'
    '"weitere_befunde":0,"weitere_fragen":0}'
)


def _json_aus(roh):
    """(protokoll, grund) – bei Misserfolg sagt `grund`, WARUM.

    Die drei Faelle sind praktisch verschieden und brauchen verschiedene
    Abhilfen: leere Antwort, gar kein JSON, oder ABGESCHNITTENES JSON (dann war
    das Token-Budget zu klein). Frueher fuehrten alle drei zur selben
    nichtssagenden Meldung.
    """
    if not roh or not roh.strip():
        return None, "Das Modell hat nichts geliefert."
    # Abgeschnitten? Die Klammerbilanz der GANZEN Antwort verraet es zuverlaessig.
    # (Eine gierige Regex fände sonst ein Teilstueck mit schliessender Klammer und
    # meldete «kein gültiges JSON» – richtig, aber nicht handlungsleitend.)
    if roh.count("{") > roh.count("}"):
        return None, ("Die Antwort wurde abgeschnitten (Token-Budget zu klein für "
                      "dieses Protokoll).")
    m = re.search(r"\{.*\}", roh, re.DOTALL)
    if not m:
        return None, f"Die Antwort war kein JSON: {roh[:120]!r}"
    try:
        return json.loads(m.group()), ""
    except (ValueError, TypeError) as e:
        return None, (f"Die Antwort war kein gültiges JSON ({e}). "
                      f"Beginn: {m.group()[:120]!r}")


def _befunde_kompakt(ergebnis):
    """Die Invarianten-Befunde als DATENSTRUKTUR (nicht als Anzeigetext).

    Briefing 5.1: der Prüfer soll sie übernehmen, nicht wiederholen. Übergeben
    werden Regel-ID, Gewicht und Fundstelle – bewusst OHNE die Meldungstexte,
    damit das Modell nicht in Versuchung gerät, sie umzuformulieren.
    """
    if ergebnis is None:
        return {"anzahl": 0, "regeln": []}
    return {
        "anzahl": len(ergebnis.muss) + len(ergebnis.vorbehalte) + len(ergebnis.hinweise),
        "muss": len(ergebnis.muss),
        "vorbehalt": len(ergebnis.vorbehalte),
        "hinweis": len(ergebnis.hinweise),
        "regeln": sorted({b.regel for b in ergebnis.befunde if not b.nicht_pruefbar}),
        "nicht_pruefbar": sorted({b.regel for b in ergebnis.offene_regeln}),
    }


def _pia_kompakt(answers):
    """Der PIA-Inhalt in kompakter Form – nur was fachlich beurteilt wird."""
    out = {}
    for sid, eintrag in (answers or {}).items():
        if sid.startswith("_") or not isinstance(eintrag, dict):
            continue
        ex = eintrag.get("extracted")
        if isinstance(ex, dict):
            text = (ex.get("text") or "").strip()
            if text:
                out[sid] = text[:2500]
        elif isinstance(ex, list) and ex:
            out[sid] = [{k: str(v)[:200] for k, v in r.items() if str(v).strip()}
                        for r in ex if isinstance(r, dict)][:25]
    return out


def pruefe_fachlich(answers, llm, invarianten=None, nachweis=None, tenant_id=None,
                    skills_dir=None, erfahrungswerte=None):
    """Führt die fachliche Prüfung durch. Rückgabe: (protokoll, skill_versionen).

    Ohne LLM oder ohne Skill gibt es KEIN Protokoll – geraten wird nicht.
    """
    if llm is None:
        return None, [], "Kein Sprachmodell konfiguriert."
    bundle = load_skills(BEREICH, tenant_id=tenant_id, skills_dir=skills_dir,
                         only={SKILL})
    if not bundle:
        log.warning("Skill %s nicht gefunden – fachliche Prüfung nicht möglich.", SKILL)
        return None, [], (f"Der Skill «{SKILL}» wurde nicht gefunden. Erwartet unter "
                          f"skills/base/{SKILL}/SKILL.md")

    eingang = {
        "pia": _pia_kompakt(answers),
        "invarianten_befunde": _befunde_kompakt(invarianten),
        "provenienz": nachweis or "(nicht geführt)",
        "erfahrungswerte": erfahrungswerte or "(keine)",
    }
    user = (
        "Prüfe den folgenden PIA aus Auftraggeber-Sicht nach der Methode.\n\n"
        f"{json.dumps(eingang, ensure_ascii=False)[:14000]}\n\n"
        "Die unter 'invarianten_befunde' genannten Regeln sind BEREITS gemeldet – "
        "übernimm sie als bekannt und melde sie NICHT erneut.\n"
        "Fasse dich knapp: je Feststellung ein bis zwei Sätze.\n"
        f"Gib höchstens {MAX_BEFUNDE} Befunde und {MAX_FRAGEN} Fragen aus – die "
        "WICHTIGSTEN zuerst. Hast du mehr gefunden, trage die Anzahl der nicht "
        "ausgegebenen in 'weitere_befunde' bzw. 'weitere_fragen' ein. Eine "
        "gekürzte Prüfung darf NIE wie eine vollständige aussehen.\n"
        f"Gib NUR JSON nach diesem Schema:\n{_SCHEMA}"
    )
    system = compose_system(SYSTEM, bundle)
    try:
        roh = llm.complete(system, [{"role": "user", "content": user}],
                           max_tokens=MAX_TOKENS, timeout=ZEITLIMIT)
    except PseudoFehler:
        raise                      # MUSS durchschlagen (ANBINDUNG.md 6.2)
    except Exception as e:         # noqa: BLE001 – lieber kein Protokoll als ein erfundenes
        log.exception("Fachliche Prüfung fehlgeschlagen")
        return None, bundle.versions, f"{e.__class__.__name__}: {e}"

    protokoll, grund = _json_aus(roh)
    if not protokoll:
        log.warning("Fachprüfung ohne auswertbares Protokoll: %s | Antwort: %.400r",
                    grund, roh)
        return None, bundle.versions, grund
    return _bereinige(protokoll), bundle.versions, ""


def _bereinige(p):
    """Haelt die harten Grenzen auch dann ein, wenn das Modell sie verletzt.

    Deterministisches Sicherheitsnetz: eine ausgesprochene FREIGABE wird zur
    Empfehlung zurueckgestuft. Der Prompt sagt es, aber Verlassen ist besser
    als Vertrauen – hier haengt eine Governance-Zusage dran.
    """
    empfehlung = str(p.get("empfehlung", "")).strip().lower()
    if empfehlung not in EMPFEHLUNGEN:
        # Alles Unbekannte (auch «freigegeben») wird zur vorsichtigsten Form.
        p["empfehlung"] = "mit vorbehalt"
        p.setdefault("_hinweis", "Die Empfehlung war nicht eindeutig und wurde auf "
                                 "«mit Vorbehalt» zurückgestuft.")
    else:
        p["empfehlung"] = empfehlung
    for feld in ("weitere_befunde", "weitere_fragen"):
        try:
            p[feld] = max(0, int(p.get(feld) or 0))
        except (TypeError, ValueError):
            p[feld] = 0
    for liste in ("befunde", "querbezuege", "evidenz"):
        for eintrag in p.get(liste) or []:
            if isinstance(eintrag, dict):
                g = str(eintrag.get("gewicht", "")).strip().capitalize()
                eintrag["gewicht"] = g if g in ("Muss", "Vorbehalt", "Hinweis") else "Hinweis"
    return p


# ---- Kapitelweiser Lauf --------------------------------------------------- #
#
# Ein einziger grosser Aufruf riss das gunicorn-Worker-Zeitlimit (120 s) und
# zwang zu einer kuenstlichen Obergrenze der Ausgabe. Kapitelweise ist jeder
# Schritt kurz, das Zeitlimit kein Thema mehr - und die Laenge des Protokolls
# folgt wieder dem BEFUND statt einem Token-Deckel.

# Je Gruppe: Anzeigename + die Abschnitts-IDs, die dazugehoeren. Die
# Pruefkriterien stehen NICHT hier, sondern im Skill (Pruefraster) - eine Quelle.
GRUPPEN = [
    ("Ausgangslage", ["ausgangslage"]),
    ("Ziele", ["ziele"]),
    ("Rahmenbedingungen", ["rahmenbedingungen"]),
    ("Ressourcen", ["personalaufwand", "sachmittel", "kosten"]),
    ("Ergebnisse und Termine", ["termine"]),
    ("Projektorganisation", ["projektorganisation"]),
    ("Kommunikation", ["kommunikation"]),
    ("Risiken", ["risiken"]),
]

# Je Kapitel reicht ein Bruchteil des frueheren Budgets - deshalb ist es schnell.
KAPITEL_TOKENS = 1200
KAPITEL_ZEITLIMIT = 60
SYNTHESE_TOKENS = 1500

_KAPITEL_SCHEMA = ('{"befunde":[{"kapitel":"","kriterium":"","feststellung":"",'
                   '"gewicht":"Muss|Vorbehalt|Hinweis","vorschlag":""}],"gut":[""],'
                   '"weitere_befunde":0}')

_SYNTHESE_SCHEMA = (
    '{"gegenstand":{"umfang":"","nicht_geprueft":""},'
    '"querbezuege":[{"feststellung":"","gewicht":"Muss|Vorbehalt|Hinweis"}],'
    '"evidenz":[{"feststellung":"","gewicht":"Muss|Vorbehalt|Hinweis"}],'
    '"herausforderung":[{"frage":"","begruendung":""}],'
    '"empfehlung":"freigebbar|mit vorbehalt|nicht freigebbar","begruendung":"",'
    '"auflagen":[{"offen":"","wer":"","bis_wann":""}],'
    '"confidence":{"stufe":"hoch|mittel|tief","begrenzung":""}}')


def schritte():
    """Alle Schritte des Laufs: die Kapitel, dann die Synthese."""
    return [name for name, _ in GRUPPEN] + ["Gesamtwürdigung"]


def _auszug(answers, sids):
    return {sid: v for sid, v in _pia_kompakt(answers).items() if sid in sids}


def pruefe_kapitel(answers, llm, index, invarianten=None, tenant_id=None,
                   skills_dir=None):
    """Prüft EIN Kapitel. Rückgabe: (teilbefund, versionen, grund)."""
    if llm is None:
        return None, [], "Kein Sprachmodell konfiguriert."
    if not 0 <= index < len(GRUPPEN):
        return None, [], f"Unbekannter Schritt {index}."
    bundle = load_skills(BEREICH, tenant_id=tenant_id, skills_dir=skills_dir,
                         only={SKILL})
    if not bundle:
        return None, [], (f"Der Skill «{SKILL}» wurde nicht gefunden. Erwartet unter "
                          f"skills/base/{SKILL}/SKILL.md")

    name, sids = GRUPPEN[index]
    inhalt = _auszug(answers, sids)
    if not inhalt:
        # Nicht bearbeitet -> kein Befund. Geprüft wird gegen den Bearbeitungsstand.
        return {"kapitel": name, "befunde": [], "gut": [], "uebersprungen": True}, \
            bundle.versions, ""

    user = (
        f"Prüfe AUSSCHLIESSLICH das Kapitel «{name}» dieses PIA nach dem Prüfraster "
        f"der Methode. Andere Kapitel beurteilst du hier NICHT – sie werden separat "
        f"geprüft.\n\n"
        f"{json.dumps(inhalt, ensure_ascii=False)[:6000]}\n\n"
        f"Bereits gemeldete Regelbefunde (nicht wiederholen): "
        f"{json.dumps(_befunde_kompakt(invarianten), ensure_ascii=False)}\n"
        "Fasse dich knapp: je Feststellung ein bis zwei Sätze. Nur was du am "
        "vorliegenden Inhalt belegen kannst.\n"
        f"Gib NUR JSON nach diesem Schema:\n{_KAPITEL_SCHEMA}"
    )
    try:
        roh = llm.complete(compose_system(SYSTEM, bundle),
                           [{"role": "user", "content": user}],
                           max_tokens=KAPITEL_TOKENS, timeout=KAPITEL_ZEITLIMIT)
    except PseudoFehler:
        raise
    except Exception as e:      # noqa: BLE001
        log.exception("Kapitelprüfung «%s» fehlgeschlagen", name)
        return None, bundle.versions, f"{e.__class__.__name__}: {e}"

    teil, grund = _json_aus(roh)
    if teil is None:
        log.warning("Kapitel «%s» ohne Protokoll: %s | %.300r", name, grund, roh)
        return None, bundle.versions, grund
    teil["kapitel"] = name
    for b in teil.get("befunde") or []:
        if isinstance(b, dict):
            b.setdefault("kapitel", name)
    return teil, bundle.versions, ""


def synthese(teilbefunde, answers, llm, invarianten=None, nachweis=None,
             tenant_id=None, skills_dir=None):
    """Querbezüge, Evidenz, Herausforderung und Empfehlung – braucht das
    Gesamtbild und läuft deshalb NACH den Kapiteln."""
    if llm is None:
        return None, [], "Kein Sprachmodell konfiguriert."
    bundle = load_skills(BEREICH, tenant_id=tenant_id, skills_dir=skills_dir,
                         only={SKILL})
    if not bundle:
        return None, [], f"Der Skill «{SKILL}» wurde nicht gefunden."

    # Nur das Nötige: die Kapitelbefunde in Kurzform, nicht der ganze PIA.
    kurz = [{"kapitel": t.get("kapitel"),
             "befunde": [f"{b.get('gewicht')}: {b.get('feststellung')}"
                         for b in (t.get("befunde") or [])]}
            for t in teilbefunde]
    user = (
        "Die Kapitel sind einzeln geprüft. Bilde jetzt das Gesamturteil: "
        "Querbezüge zwischen den Kapiteln, Evidenz (Soll gegen Ist), drei bis "
        "fünf Herausforderungen an die Projektleitung und die Empfehlung.\n\n"
        f"Kapitelbefunde:\n{json.dumps(kurz, ensure_ascii=False)[:6000]}\n\n"
        f"Ziele und Ergebnisse zum Abgleich:\n"
        f"{json.dumps(_auszug(answers, ['ziele', 'termine']), ensure_ascii=False)[:3000]}\n\n"
        f"Herkunft je Kapitel (Evidenz):\n{json.dumps(nachweis or '(nicht geführt)', ensure_ascii=False)[:2000]}\n\n"
        "Wiederhole die Kapitelbefunde NICHT – sie stehen bereits im Protokoll.\n"
        f"Gib NUR JSON nach diesem Schema:\n{_SYNTHESE_SCHEMA}"
    )
    try:
        roh = llm.complete(compose_system(SYSTEM, bundle),
                           [{"role": "user", "content": user}],
                           max_tokens=SYNTHESE_TOKENS, timeout=KAPITEL_ZEITLIMIT)
    except PseudoFehler:
        raise
    except Exception as e:      # noqa: BLE001
        log.exception("Synthese fehlgeschlagen")
        return None, bundle.versions, f"{e.__class__.__name__}: {e}"

    teil, grund = _json_aus(roh)
    if teil is None:
        log.warning("Synthese ohne Protokoll: %s | %.300r", grund, roh)
        return None, bundle.versions, grund
    return teil, bundle.versions, ""


def baue_protokoll(teilbefunde, gesamt):
    """Fügt Kapitelbefunde und Synthese zum Protokoll A–E zusammen."""
    befunde, gut = [], []
    for t in teilbefunde:
        befunde.extend(t.get("befunde") or [])
        gut.extend(t.get("gut") or [])
    p = dict(gesamt or {})
    p["befunde"] = befunde
    p["gut"] = [g for g in gut if str(g).strip()]
    p.setdefault("gegenstand", {"umfang": "", "nicht_geprueft": ""})
    # Kapitelweise entfaellt die Gesamt-Obergrenze. Reisst ein EINZELNES Kapitel
    # sein Budget, bleibt der Hinweis erhalten - still unvollstaendig soll die
    # Pruefung nie sein.
    p["weitere_befunde"] = sum(int(t.get("weitere_befunde") or 0) for t in teilbefunde)
    p["weitere_fragen"] = 0
    return _bereinige(p)
