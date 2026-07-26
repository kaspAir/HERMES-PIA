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
    # (Diese Zeile richtet sich an das Modell, nicht an den Nutzer - dort ist
    # der Fachbegriff korrekt und noetig.)
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
    # Die Meldungen gehen dem NUTZER auf den Bildschirm - deshalb ohne
    # Implementierungsbegriffe («JSON», «Token»). Was ich zur Fehlersuche
    # brauche, steht im Protokoll, nicht in der Meldung.
    if not roh or not roh.strip():
        return None, "Die Prüfung hat kein Ergebnis geliefert."
    # Abgeschnitten? Die Klammerbilanz der GANZEN Antwort verraet es zuverlaessig.
    # (Eine gierige Regex fände sonst ein Teilstueck mit schliessender Klammer und
    # meldete «kein gültiges JSON» – richtig, aber nicht handlungsleitend.)
    if roh.count("{") > roh.count("}"):
        return None, ("Das Ergebnis ist unvollständig geblieben – die Prüfung "
                      "wurde mitten im Schreiben abgebrochen.")
    m = re.search(r"\{.*\}", roh, re.DOTALL)
    if not m:
        return None, "Das Ergebnis war nicht auswertbar."
    try:
        return json.loads(m.group()), ""
    except (ValueError, TypeError) as e:
        log.warning("Ergebnis nicht lesbar (%s): %.200r", e, m.group())
        return None, "Das Ergebnis war nicht vollständig auswertbar."


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
    """Der PIA-Inhalt für die Prüfung – VOLLSTAENDIG. Es wird NICHTS gekürzt.

    Frueher wurden Texte auf 2500 Zeichen und Tabellen auf 25 Zeilen beschnitten.
    Das machte die Pruefung inhaltlich FALSCH: das Modell beurteilt dann einen
    Ausschnitt, haelt ihn fuer das Ganze und meldet als «fehlend», was nur nicht
    uebergeben wurde. Kapitelweise geprueft passt der volle Inhalt ohnehin in
    einen Aufruf.

    Auch ein «gekuerzt, aber markiert» gibt es hier nicht: sobald gekuerzt wird,
    urteilt der Pruefer ueber etwas anderes als das, was vorliegt. Waere ein
    Kapitel wirklich zu gross, muss der Aufruf mit einem klaren Fehler scheitern
    - nicht mit einem stillen Ausschnitt.
    """
    out = {}
    for sid, eintrag in (answers or {}).items():
        if sid.startswith("_") or not isinstance(eintrag, dict):
            continue
        ex = eintrag.get("extracted")
        if isinstance(ex, dict):
            text = (ex.get("text") or "").strip()
            if text:
                out[sid] = text
        elif isinstance(ex, list) and ex:
            out[sid] = [{k: str(v) for k, v in r.items() if str(v).strip()}
                        for r in ex if isinstance(r, dict)]
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
        f"{json.dumps(eingang, ensure_ascii=False)}\n\n"
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

# --- Grenzen: grosszuegig und EINE Regel ---------------------------------
# Drei Anlaeufe an dieser Stelle waren drei zu viel. Deshalb jetzt schlicht:
# `max_tokens` ist eine OBERGRENZE, keine Reservation - abgerechnet wird die
# tatsaechlich erzeugte Ausgabe. Ein grosszuegiger Wert kostet also nichts und
# nimmt der Ausgabelaenge jede kuenstliche Schranke.
SCHRITT_TOKENS = 16000
# Das Lese-Zeitlimit bleibt unter dem Worker-Limit (deploy/hermes_ctl.sh
# --timeout 300), damit sich die Anwendung bei einem langsamen Aufruf SELBST
# mit einem klaren Grund meldet, statt in eine nackte 500 zu laufen.
#
# Zur Geschichte: die «geheimnisvolle 30-s-Grenze» war keine Eigenschaft des
# Hostings, sondern gunicorns STANDARD-Timeout - eine Kommentarzeile mitten in
# einem mit \ fortgesetzten Befehl hatte das --timeout im Startskript
# auskommentiert. Ein Test verbietet solche Kommentare jetzt.
KAPITEL_ZEITLIMIT = 100

# Nur noch fuer den einteiligen Altweg (pruefe_fachlich).
KAPITEL_TOKENS = SCHRITT_TOKENS
SYNTHESE_TOKENS = SCHRITT_TOKENS

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
    """Alle Schritte des Laufs.

    EINE Regel traegt das Ganze: **je Schritt hoechstens ein Modellaufruf.**
    Der Nachweis ist deshalb ein eigener Schritt und nicht mehr Vorarbeit der
    Gesamtwuerdigung - zusammen sprengten die beiden Aufrufe das Zeitlimit des
    Workers, und dann ist der ganze Schritt verloren statt nur gekuerzt.
    """
    return ([name for name, _ in GRUPPEN]
            + ["Konsolidierung", "Herkunft der Angaben", "Gesamtwürdigung"])


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

    log.warning("Kapitelpruefung: Skill geladen (%s Zeichen)", len(bundle.text))
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
        f"{json.dumps(inhalt, ensure_ascii=False)}\n\n"
        "Der Kapitelinhalt oben ist VOLLSTÄNDIG übergeben. Trägt ein Feld die "
        "Angabe '_gekuerzt', ist genau dieses Feld unvollständig – dann beurteile "
        "seine Vollständigkeit NICHT.\n"
        f"Bereits gemeldete Regelbefunde (nicht wiederholen): "
        f"{json.dumps(_befunde_kompakt(invarianten), ensure_ascii=False)}\n"
        "Fasse dich knapp: je Feststellung ein bis zwei Sätze, kein Vorwort. Nur "
        "was du am vorliegenden Inhalt belegen kannst.\n"
        "Führe für DIESES Kapitel alle Befunde auf, die du belegen kannst. Musst "
        "du dennoch kürzen, nenne die wichtigsten und trage die Zahl der übrigen "
        "in 'weitere_befunde' ein – eine gekürzte Prüfung darf nie wie eine "
        "vollständige aussehen.\n"
        f"Gib NUR JSON nach diesem Schema:\n{_KAPITEL_SCHEMA}"
    )
    try:
        roh = llm.complete(compose_system(SYSTEM, bundle),
                           [{"role": "user", "content": user}],
                           max_tokens=SCHRITT_TOKENS, timeout=KAPITEL_ZEITLIMIT)
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


_KONSOLIDIERUNG_SCHEMA = (
    '{"befunde":[{"kapitel":"","kriterium":"","feststellung":"",'
    '"gewicht":"Muss|Vorbehalt|Hinweis","vorschlag":"","zusammengefasst_aus":[""]}],'
    '"gut":[""],'
    '"aufgeloeste_widersprueche":[{"worum":"","aufloesung":""}],'
    '"geprueft":[""],"nicht_geprueft":[""]}')


def konsolidiere(teilbefunde, llm, tenant_id=None, skills_dir=None):
    """Räumt die Kapitelbefunde auf, BEVOR das Gesamturteil gebildet wird.

    Kapitelweise Prüfung hat einen Preis: jedes Kapitel urteilt für sich, kennt
    die anderen nicht und kann ihnen widersprechen oder dasselbe ein zweites Mal
    melden. Dieser Schritt löst Widersprüche auf, fasst Doppelbefunde zusammen
    und gleicht den Prüfumfang gegen die TATSÄCHLICH vorliegenden Kapitel ab –
    er ist die Zusammenführung, die zwischen Teil und Ganzem fehlte.

    Er urteilt nicht neu: er darf zusammenfassen und auflösen, aber keinen
    Befund erfinden und keinen Muss-Befund fallen lassen.
    """
    if llm is None:
        return None, [], "Kein Sprachmodell konfiguriert."
    bundle = load_skills(BEREICH, tenant_id=tenant_id, skills_dir=skills_dir,
                         only={SKILL})
    if not bundle:
        return None, [], f"Der Skill «{SKILL}» wurde nicht gefunden."

    vorhanden = [t.get("kapitel") for t in teilbefunde
                 if isinstance(t, dict) and not t.get("uebersprungen")]
    leer = [t.get("kapitel") for t in teilbefunde
            if isinstance(t, dict) and t.get("uebersprungen")]
    roh = {"kapitel_mit_inhalt": vorhanden, "kapitel_ohne_inhalt": leer,
           "befunde": [b for t in teilbefunde if isinstance(t, dict)
                       for b in (t.get("befunde") or [])],
           "gut": [g for t in teilbefunde if isinstance(t, dict)
                   for g in (t.get("gut") or [])]}

    user = (
        "Die Kapitel sind einzeln geprüft worden – jedes ohne Kenntnis der "
        "anderen. Führe die Befunde jetzt zusammen:\n"
        "1. WIDERSPRÜCHE auflösen: sagen zwei Befunde Gegenteiliges, entscheide "
        "begründet und halte die Auflösung fest.\n"
        "2. DOPPELBEFUNDE zusammenfassen: dieselbe Sache aus zwei Kapiteln wird "
        "EIN Befund; nenne in 'zusammengefasst_aus' die betroffenen Kapitel.\n"
        "3. PRÜFUMFANG abgleichen: 'geprueft' sind die Kapitel mit Inhalt, "
        "'nicht_geprueft' die ohne. Behaupte nichts über Kapitel ohne Inhalt.\n\n"
        "HARTE REGELN: Du urteilst nicht neu. Du erfindest keinen Befund. Kein "
        "Muss-Befund darf verschwinden – er darf nur mit einem anderen "
        "verschmelzen. Bleiben zwei Befunde verschieden, bleiben es zwei.\n\n"
        f"{json.dumps(roh, ensure_ascii=False)}\n\n"
        f"Gib NUR eine Antwort nach diesem Aufbau:\n{_KONSOLIDIERUNG_SCHEMA}"
    )
    try:
        antwort = llm.complete(compose_system(SYSTEM, bundle),
                               [{"role": "user", "content": user}],
                               max_tokens=SCHRITT_TOKENS, timeout=KAPITEL_ZEITLIMIT)
    except PseudoFehler:
        raise
    except Exception as e:      # noqa: BLE001
        log.exception("Konsolidierung fehlgeschlagen")
        return None, bundle.versions, f"{e.__class__.__name__}: {e}"

    teil, grund = _json_aus(antwort)
    if teil is None:
        log.warning("Konsolidierung ohne Ergebnis: %s | %.300r", grund, antwort)
        return None, bundle.versions, grund

    # Sicherheitsnetz: kein Muss-Befund darf beim Zusammenfassen verlorengehen.
    vorher = [b for b in roh["befunde"]
              if str(b.get("gewicht", "")).capitalize() == "Muss"]
    nachher = [b for b in (teil.get("befunde") or [])
               if isinstance(b, dict)
               and str(b.get("gewicht", "")).capitalize() == "Muss"]
    if len(nachher) < len(vorher):
        fehlend = {str(b.get("feststellung", ""))[:80] for b in vorher} -                   {str(b.get("feststellung", ""))[:80] for b in nachher}
        zusammengefasst = {z for b in (teil.get("befunde") or [])
                           if isinstance(b, dict)
                           for z in (b.get("zusammengefasst_aus") or [])}
        if fehlend and not zusammengefasst:
            log.warning("Konsolidierung liess Muss-Befunde weg – Originale bleiben.")
            teil["befunde"] = roh["befunde"]
            teil["_hinweis"] = ("Die Zusammenführung hätte Muss-Befunde weggelassen; "
                                "es gelten deshalb die ursprünglichen Befunde.")
    return teil, bundle.versions, ""


def synthese(teilbefunde, answers, llm, invarianten=None, nachweis=None,
             tenant_id=None, skills_dir=None, konsolidiert=None):
    """Querbezüge, Evidenz, Herausforderung und Empfehlung – braucht das
    Gesamtbild und läuft deshalb NACH den Kapiteln und NACH der Konsolidierung."""
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
        f"Kapitelbefunde:\n{json.dumps(kurz, ensure_ascii=False)}\n\n"
        f"Ziele und Ergebnisse zum Abgleich:\n"
        f"{json.dumps(_auszug(answers, ['ziele', 'termine']), ensure_ascii=False)}\n\n"
        f"Herkunft je Kapitel (Evidenz):\n{json.dumps(nachweis or '(nicht geführt)', ensure_ascii=False)}\n\n"
        "Wiederhole die Kapitelbefunde NICHT – sie stehen bereits im Protokoll.\n"
        f"Gib NUR JSON nach diesem Schema:\n{_SYNTHESE_SCHEMA}"
    )
    try:
        roh = llm.complete(compose_system(SYSTEM, bundle),
                           [{"role": "user", "content": user}],
                           max_tokens=SCHRITT_TOKENS, timeout=KAPITEL_ZEITLIMIT)
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


def _ohne_dubletten_zu_befunden(auflagen, befunde):
    """Auflagen, die nur einen Muss-Befund wiederholen, fallen weg.

    Beobachtet: die Auflagenliste war eine zweite Fassung derselben
    Muss-Befunde. Eine Auflage soll nennen, was ZUSAETZLICH zu tun ist – sonst
    liest man dieselbe Sache zweimal und haelt sie fuer zwei.
    """
    def kern(text):
        return set(re.findall(r"\w{5,}", str(text or "").lower()))

    muss = [kern(b.get("feststellung")) for b in befunde
            if isinstance(b, dict)
            and str(b.get("gewicht", "")).capitalize() == "Muss"]
    behalten = []
    for a in auflagen or []:
        if not isinstance(a, dict):
            continue
        k = kern(a.get("offen"))
        # Deutliche Ueberlappung = dieselbe Sache, anders formuliert.
        if k and any(len(k & m) >= max(2, int(len(k) * 0.6)) for m in muss):
            continue
        behalten.append(a)
    return behalten


def baue_protokoll(teilbefunde, gesamt, konsolidiert=None):
    """Fügt Kapitelbefunde, Konsolidierung und Synthese zum Protokoll A–E zusammen."""
    p = dict(gesamt or {})
    if konsolidiert and konsolidiert.get("befunde"):
        # Die zusammengefuehrte Fassung ist die massgebliche: dort sind
        # Widersprueche aufgeloest und Doppelbefunde verschmolzen.
        p["befunde"] = [b for b in konsolidiert["befunde"] if isinstance(b, dict)]
        p["gut"] = [g for g in (konsolidiert.get("gut") or []) if str(g).strip()]
        p["aufgeloeste_widersprueche"] = konsolidiert.get("aufgeloeste_widersprueche") or []
        if konsolidiert.get("_hinweis"):
            p.setdefault("_hinweis", konsolidiert["_hinweis"])
    else:
        befunde, gut = [], []
        for t in teilbefunde:
            befunde.extend(t.get("befunde") or [])
            gut.extend(t.get("gut") or [])
        p["befunde"] = befunde
        p["gut"] = [g for g in gut if str(g).strip()]
    p["auflagen"] = _ohne_dubletten_zu_befunden(p.get("auflagen"), p["befunde"])
    p.setdefault("gegenstand", {"umfang": "", "nicht_geprueft": ""})
    # Kapitelweise entfaellt die Gesamt-Obergrenze. Reisst ein EINZELNES Kapitel
    # sein Budget, bleibt der Hinweis erhalten - still unvollstaendig soll die
    # Pruefung nie sein.
    p["weitere_befunde"] = sum(int(t.get("weitere_befunde") or 0) for t in teilbefunde)
    p["weitere_fragen"] = 0
    return _bereinige(p)
