"""Die vierschichtige Rechtsgrundlagen-Kette – tätigkeitsweise.

**Warum es diese Datei gibt.** Die bisherige Analyse stellte eine Frage, die
logisch richtig beantwortet wurde und trotzdem in die Irre führte. Gemessen an
einem Vorhaben zur biometrischen Massenüberwachung (BKI Test 6) lautete sie
sinngemäss: «Braucht es eine Rechtsgrundlage dafür, eine Analyse zu schreiben?»
– denn übergeben wurden nur die *Ziele der Phase Initialisierung*. Antwort:
nein, keine Lücke. Das Dokument entwarnte ein Vorhaben, das Grundrechte
berührt.

Zwei Konsequenzen tragen dieses Modul:

1. **Die Einheit der Prüfung ist die TÄTIGKEIT, nicht das Ziel.** Ziele sind
   Absichten, Eingriffe sind Handlungen. Gefragt wird, was wem angetan wird –
   und das steht in der Ausgangslage und in den Rahmenbedingungen, nicht nur in
   der Zielliste.
2. **Alle vier Schichten laufen.** Die Kartierung allein kann die Frage gar
   nicht beantworten: ob eine Grundlage genügt, entscheidet die Würdigung; ob
   eine fehlende Grundlage zu schaffen wäre, die Gap-Analyse. Bisher lief nur
   die Kartierung, und ihre Ausgabe wurde in Kapitel gepresst, die die anderen
   Schichten voraussetzen.

Der Ablauf spiegelt die Fachprüfung: ein Schritt je Aufruf, fortsetzbar, am
Schluss eine Konsolidierung. Was das Modell entscheidet, ist fachliches Urteil;
was nachprüfbar ist, entscheidet der Code – insbesondere die Sperren unten.
"""
import json
import logging

from app.domains.llm.errors import PseudoFehler
from app.domains.skills import compose_system, load_skills

log = logging.getLogger("hermes.rechtsgrundlagen")

BEREICH = "rechtsgrundlagenanalyse"

SKILL_KARTIERUNG = "rechtsgrundlagen-kartierung"
SKILL_GAP = "rechtsgrundlagen-gap-analyse"
SKILL_WUERDIGUNG = "rechtsgrundlagen-wuerdigung"
SKILL_OPTIONEN = "rechtsgrundlagen-handlungsoptionen"

# Grosszuegig: `max_tokens` ist eine Obergrenze, keine Reservation.
SCHRITT_TOKENS = 16000
SCHRITT_ZEITLIMIT = 240

# ---- Normstufen: Fakten aus dem Gap-Analyse-Skill ------------------------- #
# Reihenfolge = Rangfolge. Sie erlaubt dem CODE zu entscheiden, ob eine
# gefundene Grundlage die erforderliche Stufe ueberhaupt erreicht - das ist
# Vergleichen, kein Urteilen.
NORMSTUFEN = ("richtlinie", "verordnung", "gesetz", "verfassung")

NORMSTUFE_VERFAHREN = {
    "verfassung": ("Verfassungsgeber (Volk)", "obligatorisches Referendum"),
    "gesetz": ("Legislative / Parlament", "fakultatives Referendum"),
    "verordnung": ("Exekutive (Regierung oder Verwaltung)", "kein Referendum"),
    "richtlinie": ("Verwaltung", "kein Referendum"),
}

# Eingriffstiefe -> tiefste Stufe, die das Legalitaetsprinzip noch erfuellt.
# Art. 36 Abs. 1 BV: schwere Grundrechtseingriffe verlangen ein formelles Gesetz.
EINGRIFF_MINDESTSTUFE = {
    "schwer": "gesetz",
    "leicht": "verordnung",
    "keiner": "",
}

# Normen, die Grundrechte GARANTIEREN und Eingriffe BEGRENZEN. Sie sind nie die
# Ermaechtigung fuer einen Eingriff. Gemessen: BV und EMRK standen als
# «Bestehende Rechtsgrundlage» Nr. 01 und 02 ueber einem Ueberwachungsvorhaben -
# das liest sich wie eine Erlaubnis.
SCHRANKENNORMEN = (
    "bundesverfassung", "kantonsverfassung", "staatsverfassung", "verfassung",
    "europäische menschenrechtskonvention", "menschenrechtskonvention", "emrk",
    "uno-pakt", "grundrechtskatalog",
)


def ist_schrankennorm(name):
    """Garantiert die Norm Grundrechte, statt einen Eingriff zu erlauben?"""
    n = f" {(name or '').lower()} "
    return any(k in n for k in SCHRANKENNORMEN)


def stufe_reicht(gefunden, erforderlich):
    """Erreicht die gefundene Normstufe die erforderliche? (Vergleich, kein Urteil)"""
    if not erforderlich:
        return True
    try:
        return NORMSTUFEN.index((gefunden or "").lower()) >= \
            NORMSTUFEN.index(erforderlich.lower())
    except ValueError:
        return False


def _json_aus(roh):
    """(Daten, Grund) – Meldungen ohne Implementierungsbegriffe."""
    import re
    if not roh or not str(roh).strip():
        return None, "Die Analyse hat kein Ergebnis geliefert."
    if str(roh).count("{") > str(roh).count("}"):
        return None, ("Das Ergebnis ist unvollständig geblieben – die Analyse "
                      "wurde mitten im Schreiben abgebrochen.")
    m = re.search(r"\{.*\}", str(roh), re.DOTALL)
    if not m:
        return None, "Das Ergebnis war nicht auswertbar."
    try:
        return json.loads(m.group()), ""
    except (ValueError, TypeError) as e:
        log.warning("Ergebnis nicht lesbar (%s): %.200r", e, m.group())
        return None, "Das Ergebnis war nicht vollständig auswertbar."


def _rufe(llm, skill, system, user, tenant_id=None, skills_dir=None):
    """Ein Schritt = ein Modellaufruf mit GENAU EINEM Skill.

    `only={skill}` ist nicht Bequemlichkeit, sondern die Schichtengrenze: die
    Gap-Analyse darf nicht würdigen, die Würdigung keine Optionen entwickeln.
    Vermischt man die Skills, verschwimmt genau die Trennung, die die Methode
    ausmacht.
    """
    if llm is None:
        return None, [], "Kein Sprachmodell konfiguriert."
    bundle = load_skills(BEREICH, tenant_id=tenant_id, skills_dir=skills_dir,
                         only={skill})
    if not bundle:
        return None, [], (f"Der Skill «{skill}» wurde nicht gefunden. Erwartet "
                          f"unter skills/base/{skill}/SKILL.md")
    try:
        roh = llm.complete(compose_system(system, bundle),
                           [{"role": "user", "content": user}],
                           max_tokens=SCHRITT_TOKENS, timeout=SCHRITT_ZEITLIMIT)
    except PseudoFehler:
        raise
    except Exception as e:      # noqa: BLE001
        log.exception("Schritt «%s» fehlgeschlagen", skill)
        return None, bundle.versions, f"{e.__class__.__name__}: {e}"
    daten, grund = _json_aus(roh)
    if daten is None:
        log.warning("Schritt «%s» ohne Ergebnis: %s | %.300r", skill, grund, roh)
        return None, bundle.versions, grund
    return daten, bundle.versions, ""


# ======================================================================== #
#  Schicht 0 · Die Tätigkeiten des VORHABENS herausschälen
# ======================================================================== #

_SYSTEM_TAETIGKEITEN = (
    "Du bereitest eine schweizerische Rechtsgrundlagenanalyse vor. Deine einzige "
    "Aufgabe: aus der Projektbeschreibung die geplanten TÄTIGKEITEN herausschälen, "
    "für die es eine gesetzliche Grundlage brauchen könnte.\n"
    "GRUNDSÄTZE:\n"
    "- Eine Tätigkeit ist eine HANDLUNG gegenüber Menschen oder Daten, kein Ziel "
    "und kein Projektergebnis. «Ein Konzept erstellen» ist keine Tätigkeit in "
    "diesem Sinn; «Gesichter im öffentlichen Raum biometrisch erfassen» ist eine.\n"
    "- Gemeint ist das VORHABEN, nicht die Projektphase. Dass in der "
    "Initialisierung nur Analysen entstehen, ändert nichts daran, was das "
    "Vorhaben tun soll.\n"
    "- Du beschreibst, du beurteilst nicht. Keine Rechtsfolgen, keine Erlasse.\n"
    "- Du erfindest nichts. Was nicht im Text steht, steht nicht in der Liste.\n"
    "Antworte AUSSCHLIESSLICH mit validem JSON nach dem vorgegebenen Schema."
)

_SCHEMA_TAETIGKEITEN = (
    '{"taetigkeiten":[{"taetigkeit":"","betroffene":"","daten":"",'
    '"hoheitlich":true,"merkmale":[""],"fundstelle_im_pia":""}],'
    '"nicht_erkennbar":[""]}')


def taetigkeiten(wissen, llm, tenant_id=None, skills_dir=None):
    """Schicht 0: was tut das Vorhaben – wem gegenüber, mit welchen Daten?

    Die Kartierung verlangt das in Schritt 2 («Rechtsauslösende Merkmale
    erheben»), deshalb läuft sie mit ihrem Skill. Übergeben werden Ausgangslage
    UND Rahmenbedingungen UND Ziele: das Entscheidende stand im gemessenen Fall
    in der Ausgangslage, die Analyse sah aber nur die Ziele.
    """
    eingang = {
        "ausgangslage": wissen.ausgangslage_text(),
        "rahmenbedingungen": wissen.rahmenbedingungen(),
        "ziele": wissen.ziel_beschreibungen(),
        "ebene": wissen.ebene or "nicht angegeben",
        "kanton": wissen.kanton or "nicht angegeben",
    }
    user = (
        "Schäle aus dieser Projektbeschreibung die geplanten Tätigkeiten des "
        "VORHABENS heraus – nicht die Ergebnisse der Projektphase.\n\n"
        f"{json.dumps(eingang, ensure_ascii=False)}\n\n"
        "Nenne je Tätigkeit die Betroffenen, die bearbeiteten Daten, ob sie "
        "hoheitlich ausgeübt wird, die rechtsauslösenden Merkmale (z. B. "
        "hoheitliches Handeln, Datenbearbeitung, Register, Beschaffung, "
        "Gebühren, KI-Einsatz) und die Stelle im PIA, aus der sie stammt.\n"
        "Was du nicht erkennen kannst, gehört in 'nicht_erkennbar' – nicht in "
        "die Liste der Tätigkeiten.\n"
        f"Gib NUR eine Antwort nach diesem Aufbau:\n{_SCHEMA_TAETIGKEITEN}"
    )
    return _rufe(llm, SKILL_KARTIERUNG, _SYSTEM_TAETIGKEITEN, user,
                 tenant_id, skills_dir)


# ======================================================================== #
#  Schicht 1 · Kartierung je Tätigkeit
# ======================================================================== #

_SYSTEM_KARTIERUNG = (
    "Du kartierst die Rechtsgrundlagen für EINE geplante Tätigkeit eines "
    "schweizerischen Verwaltungsvorhabens.\n"
    "HARTE GRENZEN:\n"
    "- Du würdigst NICHT, ob die Tätigkeit zulässig ist – das ist eine andere "
    "Schicht. Du stellst fest, welche Grundlage besteht und welche nicht.\n"
    "- Eine Norm, die Grundrechte GARANTIERT (Bundesverfassung, EMRK, "
    "Kantonsverfassung), ist NIE eine Ermächtigungsgrundlage. Sie begrenzt den "
    "Eingriff. Führe sie nie als bestehende Grundlage auf.\n"
    "- Du erfindest keine Fundstelle. Kennst du die SR-Nummer nicht sicher, "
    "lässt du sie leer – ein leeres Feld ist besser als eine erfundene Nummer.\n"
    "- Unterscheide streng: RECHTSLÜCKE (trotz hinreichender Suche keine "
    "Grundlage), RECHERCHELÜCKE (eine Quelle wurde nicht geprüft), "
    "INFORMATIONSLÜCKE (eine Projektangabe fehlt). Nicht geprüft, nicht "
    "verifiziert und nicht vorhanden sind drei verschiedene Dinge.\n"
    "Antworte AUSSCHLIESSLICH mit validem JSON nach dem vorgegebenen Schema."
)

_SCHEMA_KARTIERUNG = (
    '{"grundlagen":[{"erlass":"","fundstelle":"","normstufe":'
    '"verfassung|gesetz|verordnung|richtlinie","status":"in Kraft|bevorstehend|hängig",'
    '"ermaechtigt":true,"geltung":""}],'
    '"eingriff":{"tiefe":"schwer|leicht|keiner","grundrechte":[""],"begruendung":""},'
    '"luecke":{"art":"keine|rechtsluecke|rechercheluecke|informationsluecke",'
    '"beschreibung":""},'
    '"gesucht_in":[""],"confidence":{"stufe":"hoch|mittel|tief","begruendung":""}}')


def kartiere(taetigkeit, wissen, llm, gefundene=None, tenant_id=None, skills_dir=None):
    """Schicht 1 für EINE Tätigkeit: welche Grundlage besteht, welche fehlt?"""
    eingang = {
        "taetigkeit": taetigkeit,
        "ebene": wissen.ebene or "nicht angegeben",
        "kanton": wissen.kanton or "nicht angegeben",
        "im_pia_genannte_erlasse": wissen.genannte_rechtsgrundlagen(),
        "bereits_verifizierte_fundstellen": gefundene or {},
    }
    user = (
        "Kartiere die Rechtsgrundlagen für DIESE eine Tätigkeit.\n\n"
        f"{json.dumps(eingang, ensure_ascii=False)}\n\n"
        "Bestimme zuerst die Eingriffstiefe: Welche Grundrechte berührt die "
        "Tätigkeit, und ist der Eingriff schwer oder leicht? Begründe das.\n"
        "Führe dann die Erlasse auf, die diese Tätigkeit ERMÄCHTIGEN, je mit "
        "Normstufe und Status. Setze 'ermaechtigt' nur auf true, wenn der "
        "Erlass die Tätigkeit tatsächlich erlaubt – nicht, wenn er sie nur "
        "berührt oder begrenzt.\n"
        "Halte fest, wo du gesucht hast; daraus folgt, ob eine fehlende "
        "Grundlage eine Rechtslücke oder bloss eine Recherchelücke ist.\n"
        f"Gib NUR eine Antwort nach diesem Aufbau:\n{_SCHEMA_KARTIERUNG}"
    )
    return _rufe(llm, SKILL_KARTIERUNG, _SYSTEM_KARTIERUNG, user,
                 tenant_id, skills_dir)


# ======================================================================== #
#  Schicht 2 · Gap-Analyse (nur bei bestätigter Rechtslücke)
# ======================================================================== #

_SYSTEM_GAP = (
    "Du prüfst eine gemeldete Rechtslücke eines schweizerischen Vorhabens und "
    "schlägst vor, WIE sie zu schliessen wäre.\n"
    "HARTE GRENZEN:\n"
    "- Du bestätigst die Lücke zuerst: besteht wirklich keine Grundlage, oder "
    "wurde nur nicht gründlich genug gesucht? Eine unbestätigte Lücke ist keine.\n"
    "- Du nennst die TIEFSTE Normstufe, die das Legalitätsprinzip noch erfüllt – "
    "nicht die schnellste. Bei schwerem Grundrechtseingriff verlangt Art. 36 "
    "Abs. 1 BV eine Grundlage im formellen Gesetz.\n"
    "- Du würdigst NICHT, ob die Massnahme zulässig wäre. Auch eine schliessbare "
    "Lücke sagt nichts darüber, ob die Tätigkeit erlaubt sein darf.\n"
    "- Organ und Referendumsart sind Fakten der Stufe, keine Risikobewertung. "
    "Keine Dauer-, Kosten- oder Erfolgsprognosen.\n"
    "Antworte AUSSCHLIESSLICH mit validem JSON nach dem vorgegebenen Schema."
)

_SCHEMA_GAP = (
    '{"bestaetigt":true,"begruendung":"",'
    '"erforderliche_normstufe":"verfassung|gesetz|verordnung|richtlinie",'
    '"stufenbegruendung":"","organ":"","referendum":"",'
    '"deckungsvorschlag":"","confidence":{"stufe":"hoch|mittel|tief","begruendung":""}}')


def analysiere_luecke(taetigkeit, kartierung, wissen, llm, tenant_id=None,
                      skills_dir=None):
    """Schicht 2: ist die Lücke echt, und welche Normstufe müsste sie tragen?"""
    eingang = {"taetigkeit": taetigkeit, "kartierung": kartierung,
               "ebene": wissen.ebene or "nicht angegeben",
               "kanton": wissen.kanton or "nicht angegeben"}
    user = (
        "Prüfe diese gemeldete Rechtslücke.\n\n"
        f"{json.dumps(eingang, ensure_ascii=False)}\n\n"
        "Bestätige zuerst, ob wirklich keine Grundlage besteht. Bestimme dann "
        "die erforderliche Normstufe und begründe sie. Nenne Organ und "
        "Referendumsart als Fakten der Stufe.\n"
        f"Gib NUR eine Antwort nach diesem Aufbau:\n{_SCHEMA_GAP}"
    )
    return _rufe(llm, SKILL_GAP, _SYSTEM_GAP, user, tenant_id, skills_dir)


# ======================================================================== #
#  Schicht 3 · Würdigung – wäre die Tätigkeit überhaupt zulässig?
# ======================================================================== #

_SYSTEM_WUERDIGUNG = (
    "Du würdigst, ob eine geplante hoheitliche Tätigkeit rechtlich ZULÄSSIG "
    "wäre – gestützt auf eine bestehende oder eine erst zu schaffende Grundlage.\n"
    "HARTE GRENZEN:\n"
    "- Eine Grundlage zu HABEN heisst nicht, zulässig zu sein. Prüfe den "
    "Eingriff an Art. 36 BV (gesetzliche Grundlage, öffentliches Interesse, "
    "Verhältnismässigkeit, Kerngehalt) und an der EMRK, wo einschlägig.\n"
    "- Der Kerngehalt ist unantastbar: was ihn verletzt, wäre auch mit einem "
    "Gesetz unzulässig. Sag das ausdrücklich, wenn es zutrifft.\n"
    "- Du erfindest keine Gerichtsentscheide und keine Fundstellen.\n"
    "- Deine Einschätzung ist BERATEND und ersetzt den Rechtsdienst nicht. "
    "Sag das im Feld 'vorbehalt'.\n"
    "Antworte AUSSCHLIESSLICH mit validem JSON nach dem vorgegebenen Schema."
)

_SCHEMA_WUERDIGUNG = (
    '{"rechtsgueter":[""],"geprueft_an":[""],'
    '"pruefung":[{"kriterium":"","ergebnis":"erfüllt|fraglich|nicht erfüllt",'
    '"begruendung":""}],'
    '"ergebnis":"zulässig|bedingt zulässig|nicht zulässig",'
    '"kerngehalt_verletzt":false,"begruendung":"","vorbehalt":"",'
    '"confidence":{"stufe":"hoch|mittel|tief","begruendung":""}}')


def wuerdige(taetigkeit, kartierung, gap, llm, tenant_id=None, skills_dir=None):
    """Schicht 3: Verhältnismässigkeit und Kerngehalt – der Schritt, der im
    gemessenen Fall vollständig fehlte."""
    eingang = {"taetigkeit": taetigkeit, "kartierung": kartierung,
               "gap_analyse": gap or "(keine Lücke gemeldet)"}
    user = (
        "Würdige, ob diese Tätigkeit rechtlich zulässig wäre.\n\n"
        f"{json.dumps(eingang, ensure_ascii=False)}\n\n"
        "Prüfe den Eingriff an den Voraussetzungen von Art. 36 BV und – wo "
        "einschlägig – an der EMRK. Halte ausdrücklich fest, wenn der "
        "Kerngehalt betroffen ist: dann wäre die Tätigkeit auch mit einer "
        "gesetzlichen Grundlage unzulässig.\n"
        f"Gib NUR eine Antwort nach diesem Aufbau:\n{_SCHEMA_WUERDIGUNG}"
    )
    return _rufe(llm, SKILL_WUERDIGUNG, _SYSTEM_WUERDIGUNG, user,
                 tenant_id, skills_dir)


# ======================================================================== #
#  Schicht 4 · Handlungsoptionen (nur wenn nicht oder bedingt zulässig)
# ======================================================================== #

_SYSTEM_OPTIONEN = (
    "Du entwickelst rechtmässige Handlungsoptionen, weil die geplante Tätigkeit "
    "nicht oder nur bedingt zulässig wäre.\n"
    "HARTE GRENZEN:\n"
    "- Richte dich am eigentlichen REGELUNGSZIEL aus, nicht am wörtlichen "
    "Vorhaben. Die Frage ist, was erreicht werden soll – nicht, wie es "
    "ursprünglich gemacht werden sollte.\n"
    "- Jede Option nennt die Grundlage, auf die sie sich stützt (bestehend oder "
    "zu schaffen), und ihre Grenzen.\n"
    "- Benenne auch die NICHT gangbaren Wege – das schützt vor dem zweiten "
    "Anlauf in dieselbe Sackgasse.\n"
    "- Deine Vorschläge sind BERATEND: jede gewählte Option ist erneut zu "
    "würdigen und mit dem Rechtsdienst abzustimmen.\n"
    "Antworte AUSSCHLIESSLICH mit validem JSON nach dem vorgegebenen Schema."
)

_SCHEMA_OPTIONEN = (
    '{"eigentliches_ziel":"",'
    '"optionen":[{"option":"","grundlage":"","voraussetzungen":"","grenzen":""}],'
    '"nicht_gangbar":[{"weg":"","warum":""}],'
    '"vorbehalt":"","confidence":{"stufe":"hoch|mittel|tief","begruendung":""}}')


def entwickle_optionen(taetigkeit, wuerdigung, gap, llm, tenant_id=None,
                       skills_dir=None):
    """Schicht 4: was wäre stattdessen rechtmässig möglich?"""
    eingang = {"taetigkeit": taetigkeit, "wuerdigung": wuerdigung,
               "gap_analyse": gap or "(keine)"}
    user = (
        "Entwickle rechtmässige Handlungsoptionen.\n\n"
        f"{json.dumps(eingang, ensure_ascii=False)}\n\n"
        "Bestimme zuerst das eigentliche Regelungsziel hinter der Tätigkeit. "
        "Entwickle daran ausgerichtete Optionen und benenne die nicht gangbaren "
        "Wege.\n"
        f"Gib NUR eine Antwort nach diesem Aufbau:\n{_SCHEMA_OPTIONEN}"
    )
    return _rufe(llm, SKILL_OPTIONEN, _SYSTEM_OPTIONEN, user, tenant_id, skills_dir)


# ======================================================================== #
#  Die Sperren – was der CODE entscheidet, nicht das Modell
# ======================================================================== #

def sperren(befunde):
    """Deterministische Befunde über die ganze Kette.

    Sie hängen nicht am Urteil des Modells, sondern am Vergleich von Angaben,
    die es geliefert hat. Was hier steht, kann kein Prompt aushebeln.

    `befunde`: Liste je Tätigkeit mit {taetigkeit, kartierung, gap, wuerdigung}.
    Rückgabe: Liste von {gewicht, meldung, taetigkeit}.
    """
    raus = []
    for eintrag in befunde or []:
        name = (eintrag.get("taetigkeit") or {}).get("taetigkeit", "(ohne Namen)")
        kart = eintrag.get("kartierung") or {}
        wuerd = eintrag.get("wuerdigung") or {}
        gap = eintrag.get("gap") or {}

        eingriff = (kart.get("eingriff") or {}).get("tiefe", "")
        noetig = EINGRIFF_MINDESTSTUFE.get(str(eingriff).lower(), "")
        grundlagen = [g for g in (kart.get("grundlagen") or [])
                      if isinstance(g, dict) and g.get("ermaechtigt")]

        # 1. Eine Schrankennorm als Ermächtigung ist eine Umkehrung.
        for g in grundlagen:
            if ist_schrankennorm(g.get("erlass")):
                raus.append({
                    "gewicht": "Muss", "taetigkeit": name,
                    "meldung": (f"«{g.get('erlass')}» wird als Ermächtigung geführt. "
                                "Diese Norm garantiert Grundrechte und begrenzt "
                                "Eingriffe – sie ermächtigt nicht zu ihnen."),
                })

        # 2. Schwerer Eingriff ohne Grundlage auf der nötigen Stufe.
        if noetig:
            tragend = [g for g in grundlagen
                       if not ist_schrankennorm(g.get("erlass"))
                       and stufe_reicht(g.get("normstufe"), noetig)]
            if not tragend:
                raus.append({
                    "gewicht": "Muss", "taetigkeit": name,
                    "meldung": (f"Für diese Tätigkeit ({eingriff}er Eingriff) ist "
                                f"keine Grundlage auf Stufe «{noetig}» nachgewiesen. "
                                "Art. 36 Abs. 1 BV verlangt für schwere "
                                "Grundrechtseingriffe eine Grundlage im formellen "
                                "Gesetz."),
                })

        # 3. Der Kerngehalt ist unantastbar – auch ein Gesetz hilft dann nicht.
        if wuerd.get("kerngehalt_verletzt"):
            raus.append({
                "gewicht": "Muss", "taetigkeit": name,
                "meldung": ("Die Würdigung sieht den Kerngehalt eines Grundrechts "
                            "verletzt. Eine solche Tätigkeit wäre auch mit einer "
                            "gesetzlichen Grundlage unzulässig; das Vorhaben ist "
                            "in dieser Form nicht umsetzbar."),
            })

        # 4. Als unzulässig gewürdigt.
        if str(wuerd.get("ergebnis", "")).lower().startswith("nicht zulässig"):
            raus.append({
                "gewicht": "Muss", "taetigkeit": name,
                "meldung": "Die Würdigung kommt zum Ergebnis, dass diese Tätigkeit "
                           "nicht zulässig wäre.",
            })

        # 5. Recherchelücke: ehrlich als UNGEPRÜFT ausweisen, nicht als Ergebnis.
        art = str((kart.get("luecke") or {}).get("art", "")).lower()
        if art == "rechercheluecke":
            raus.append({
                "gewicht": "Vorbehalt", "taetigkeit": name,
                "meldung": "Eine erforderliche Quelle wurde nicht geprüft. Das "
                           "Ergebnis ist insoweit offen – nicht geprüft ist nicht "
                           "dasselbe wie nicht vorhanden.",
            })
        if art == "informationsluecke":
            raus.append({
                "gewicht": "Vorbehalt", "taetigkeit": name,
                "meldung": "Eine Projektangabe fehlt; die Analyse kann diese "
                           "Tätigkeit erst nach Rückfrage bei der Projektleitung "
                           "abschliessen.",
            })
        # 6. Bestätigte Lücke ohne Deckungsvorschlag bleibt sichtbar offen.
        if gap.get("bestaetigt") and not str(gap.get("deckungsvorschlag", "")).strip():
            raus.append({
                "gewicht": "Vorbehalt", "taetigkeit": name,
                "meldung": "Die Rechtslücke ist bestätigt, ein Deckungsvorschlag "
                           "fehlt jedoch.",
            })
    return raus


def darf_entwarnen(befunde):
    """Darf das Dokument sagen, es bestehe für alles eine Grundlage?

    Nur, wenn JEDE Tätigkeit gewürdigt wurde und kein Muss-Befund offen ist.
    Genau diese Bedingung fehlte, als die Analyse ein Überwachungsvorhaben
    entwarnte.
    """
    if not befunde:
        return False
    if any(b["gewicht"] == "Muss" for b in sperren(befunde)):
        return False
    return all((e.get("wuerdigung") or {}).get("ergebnis") for e in befunde)
