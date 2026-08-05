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

# Eingriffsintensitaet -> tiefste Normstufe, die das Legalitaetsprinzip noch
# erfuellt. Grundlage ist Art. 5 Abs. 1 BV: ALLES staatliche Handeln braucht
# eine gesetzliche Grundlage, und je intensiver in Rechte und Pflichten
# eingegriffen wird, desto hoeher muss die Stufe sein. Das gilt fuer eine
# Abgabe so wie fuer eine Bewilligungspflicht - ganz ohne Grundrechtsbezug.
# Art. 36 Abs. 1 BV ist der SONDERFALL fuer Grundrechtseingriffe; er wird nur
# genannt, wenn tatsaechlich Grundrechte beruehrt sind (siehe `sperren`).
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
    "diesem Sinn. Beispiele für Tätigkeiten aus ganz verschiedenen Bereichen: "
    "eine Gebühr erheben; Personendaten an eine andere Behörde bekanntgeben; ein "
    "Register führen; eine Bewilligung verweigern; eine Leistung beschaffen; "
    "einen Sachverhalt automatisiert auswerten.\n"
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
    '{"kartierungen":[{"nr":0,'
    '"grundlagen":[{"erlass":"","fundstelle":"","normstufe":'
    '"verfassung|gesetz|verordnung|richtlinie","status":"in Kraft|bevorstehend|hängig",'
    '"ermaechtigt":true,"geltung":""}],'
    '"eingriff":{"tiefe":"schwer|leicht|keiner","grundrechte":[""],"begruendung":""},'
    '"luecke":{"art":"keine|rechtsluecke|rechercheluecke|informationsluecke",'
    '"beschreibung":""},'
    '"gesucht_in":[""],"confidence":{"stufe":"hoch|mittel|tief",'
    '"begruendung":""}}]}')


def kartiere(liste, wissen, llm, gefundene=None, tenant_id=None, skills_dir=None):
    """Schicht 1 für ALLE Tätigkeiten: welche Grundlage besteht, welche fehlt?

    Ein Schritt je SCHICHT statt je Tätigkeit: bei fünf Tätigkeiten wären es
    sonst zwanzig Aufrufe. Die Nummer verbindet Ergebnis und Tätigkeit.
    """
    eingang = {
        "taetigkeiten": [dict(t, nr=i) for i, t in enumerate(liste or [])],
        "ebene": wissen.ebene or "nicht angegeben",
        "kanton": wissen.kanton or "nicht angegeben",
        "im_pia_genannte_erlasse": wissen.genannte_rechtsgrundlagen(),
        "bereits_verifizierte_fundstellen": gefundene or {},
    }
    user = (
        "Kartiere die Rechtsgrundlagen für JEDE dieser Tätigkeiten einzeln. "
        "Gib je Tätigkeit einen Eintrag mit ihrer Nummer zurück.\n\n"
        f"{json.dumps(eingang, ensure_ascii=False)}\n\n"
        "Bestimme je Tätigkeit zuerst, wie stark sie in Rechte und Pflichten "
        "eingreift – 'schwer', 'leicht' oder 'keiner' – und begründe das. Trage "
        "unter 'grundrechte' NUR ein, was tatsächlich berührt ist; die meisten "
        "Verwaltungstätigkeiten schränken keine Grundrechte ein, und dann bleibt "
        "die Liste leer. Ein Eingriff in Rechte und Pflichten liegt auch ohne "
        "Grundrechtsbezug vor (etwa bei einer Abgabe oder einer "
        "Bewilligungspflicht).\n"
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
    "nicht die schnellste. Das Legalitätsprinzip (Art. 5 Abs. 1 BV) gilt für "
    "jedes staatliche Handeln; je intensiver in Rechte und Pflichten "
    "eingegriffen wird, desto höher die Stufe. Werden GRUNDRECHTE eingeschränkt, "
    "gilt zusätzlich Art. 36 Abs. 1 BV: schwere Eingriffe verlangen ein "
    "formelles Gesetz.\n"
    "- Du würdigst NICHT, ob die Massnahme zulässig wäre. Auch eine schliessbare "
    "Lücke sagt nichts darüber, ob die Tätigkeit erlaubt sein darf.\n"
    "- Organ und Referendumsart sind Fakten der Stufe, keine Risikobewertung. "
    "Keine Dauer-, Kosten- oder Erfolgsprognosen.\n"
    "Antworte AUSSCHLIESSLICH mit validem JSON nach dem vorgegebenen Schema."
)

_SCHEMA_GAP = (
    '{"luecken":[{"nr":0,"bestaetigt":true,"begruendung":"",'
    '"erforderliche_normstufe":"verfassung|gesetz|verordnung|richtlinie",'
    '"stufenbegruendung":"","organ":"","referendum":"",'
    '"deckungsvorschlag":"","confidence":{"stufe":"hoch|mittel|tief",'
    '"begruendung":""}}]}')


def analysiere_luecke(faelle, wissen, llm, tenant_id=None, skills_dir=None):
    """Schicht 2: sind die Lücken echt, und welche Normstufe müssten sie tragen?

    `faelle`: [{nr, taetigkeit, kartierung}] – nur die gemeldeten Rechtslücken.
    """
    eingang = {"faelle": faelle,
               "ebene": wissen.ebene or "nicht angegeben",
               "kanton": wissen.kanton or "nicht angegeben"}
    user = (
        "Prüfe diese gemeldeten Rechtslücken – je Fall ein Eintrag mit seiner "
        "Nummer.\n\n"
        f"{json.dumps(eingang, ensure_ascii=False)}\n\n"
        "Bestätige je Fall zuerst, ob wirklich keine Grundlage besteht. "
        "Bestimme dann die erforderliche Normstufe und begründe sie. Nenne "
        "Organ und Referendumsart als Fakten der Stufe.\n"
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
    "- BESTIMME ZUERST DEN PRÜFMASSSTAB. Er hängt davon ab, was die Tätigkeit "
    "tatsächlich berührt, und ist NICHT für jedes Vorhaben derselbe:\n"
    "  · Immer: das Legalitätsprinzip (Art. 5 Abs. 1 BV) – besteht eine "
    "gesetzliche Grundlage der erforderlichen Stufe, und deckt sie diese "
    "Tätigkeit?\n"
    "  · Nur wenn GRUNDRECHTE eingeschränkt werden: Art. 36 BV (öffentliches "
    "Interesse, Verhältnismässigkeit, Kerngehalt) und die EMRK, wo einschlägig. "
    "Der Kerngehalt ist unantastbar – was ihn verletzt, wäre auch mit einem "
    "Gesetz unzulässig; sag das dann ausdrücklich.\n"
    "  · Wo einschlägig: die Anforderungen des massgeblichen Spezialrechts, der "
    "Zuständigkeitsordnung und des Verfahrensrechts.\n"
    "- Berührt die Tätigkeit keine Grundrechte, prüfst du KEINE "
    "Grundrechtsschranke. Erfinde keinen Eingriff, um etwas zu prüfen zu haben – "
    "die meisten Verwaltungsvorhaben schränken keine Grundrechte ein, und für "
    "sie ist das Legalitätsprinzip der ganze Massstab.\n"
    "- Eine Grundlage zu HABEN heisst nicht, zulässig zu sein: sie muss die "
    "Tätigkeit auch decken.\n"
    "- Du erfindest keine Gerichtsentscheide und keine Fundstellen.\n"
    "- Deine Einschätzung ist BERATEND und ersetzt den Rechtsdienst nicht. "
    "Sag das im Feld 'vorbehalt'.\n"
    "Antworte AUSSCHLIESSLICH mit validem JSON nach dem vorgegebenen Schema."
)

_SCHEMA_WUERDIGUNG = (
    '{"wuerdigungen":[{"nr":0,"rechtsgueter":[""],"geprueft_an":[""],'
    '"pruefung":[{"kriterium":"","ergebnis":"erfüllt|fraglich|nicht erfüllt",'
    '"begruendung":""}],'
    '"ergebnis":"zulässig|bedingt zulässig|nicht zulässig",'
    '"kerngehalt_verletzt":false,"begruendung":"","vorbehalt":"",'
    '"confidence":{"stufe":"hoch|mittel|tief","begruendung":""}}]}')


def wuerdige(faelle, llm, tenant_id=None, skills_dir=None):
    """Schicht 3: Verhältnismässigkeit und Kerngehalt – der Schritt, der im
    gemessenen Fall vollständig fehlte.

    `faelle`: [{nr, taetigkeit, kartierung, gap}] – JEDE Tätigkeit wird
    gewürdigt, auch die mit bestehender Grundlage. Eine Grundlage zu HABEN
    heisst nicht, zulässig zu sein.
    """
    eingang = {"faelle": faelle}
    user = (
        "Würdige für JEDE dieser Tätigkeiten, ob sie rechtlich zulässig wäre – "
        "je Tätigkeit ein Eintrag mit ihrer Nummer.\n\n"
        f"{json.dumps(eingang, ensure_ascii=False)}\n\n"
        "Halte je Fall unter 'geprueft_an' fest, WELCHEN Massstab du angelegt "
        "hast und warum gerade diesen. Prüfe dann daran. Ist eine "
        "Grundrechtsschranke einschlägig und der Kerngehalt betroffen, halte "
        "das ausdrücklich fest: dann wäre die Tätigkeit auch mit einer "
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
    '{"faelle":[{"nr":0,"eigentliches_ziel":"",'
    '"optionen":[{"option":"","grundlage":"","voraussetzungen":"","grenzen":""}],'
    '"nicht_gangbar":[{"weg":"","warum":""}],'
    '"vorbehalt":"","confidence":{"stufe":"hoch|mittel|tief",'
    '"begruendung":""}}]}')


def entwickle_optionen(faelle, llm, tenant_id=None, skills_dir=None):
    """Schicht 4: was wäre stattdessen rechtmässig möglich?

    `faelle`: [{nr, taetigkeit, wuerdigung, gap}] – nur die nicht oder bedingt
    zulässigen Tätigkeiten.
    """
    eingang = {"faelle": faelle}
    user = (
        "Entwickle für jeden Fall rechtmässige Handlungsoptionen – je Fall ein "
        "Eintrag mit seiner Nummer.\n\n"
        f"{json.dumps(eingang, ensure_ascii=False)}\n\n"
        "Bestimme zuerst das eigentliche Regelungsziel hinter der jeweiligen "
        "Tätigkeit. Entwickle daran ausgerichtete Optionen und benenne die "
        "nicht gangbaren Wege.\n"
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

        eingriff = str((kart.get("eingriff") or {}).get("tiefe", "")).strip().lower()
        # Eine NICHT BESTIMMTE Eingriffstiefe ist nicht «keiner». Ohne diese
        # Unterscheidung wuerde jede Taetigkeit, deren Eingriff das Modell nicht
        # einordnen konnte, still als harmlos durchgehen - und die Sperre unten
        # traefe nur die Faelle, die ohnehin schon erkannt sind.
        if eingriff not in EINGRIFF_MINDESTSTUFE:
            raus.append({
                "gewicht": "Vorbehalt", "taetigkeit": name,
                "meldung": ("Die Eingriffstiefe dieser Tätigkeit wurde nicht "
                            "bestimmt. Solange offen ist, ob und wie stark "
                            "Grundrechte berührt sind, lässt sich die "
                            "erforderliche Normstufe nicht beurteilen."),
            })
        noetig = EINGRIFF_MINDESTSTUFE.get(eingriff, "")
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

        # 2. Eingriff ohne Grundlage auf der noetigen Stufe.
        #    Die zitierte Norm haengt davon ab, WAS beruehrt ist: das
        #    Legalitaetsprinzip gilt immer, die Grundrechtsschranke nur, wenn
        #    tatsaechlich Grundrechte genannt sind. Art. 36 BV pauschal zu
        #    zitieren waere fuer die meisten Vorhaben schlicht falsch.
        if noetig:
            tragend = [g for g in grundlagen
                       if not ist_schrankennorm(g.get("erlass"))
                       and stufe_reicht(g.get("normstufe"), noetig)]
            if not tragend:
                grundrechte = [r for r in (kart.get("eingriff") or {}).get(
                    "grundrechte") or [] if str(r).strip()]
                if grundrechte and eingriff == "schwer":
                    warum = ("Werden Grundrechte schwer eingeschränkt, verlangt "
                             "Art. 36 Abs. 1 BV eine Grundlage im formellen "
                             f"Gesetz (berührt: {', '.join(map(str, grundrechte))}).")
                else:
                    warum = ("Staatliches Handeln braucht eine gesetzliche "
                             "Grundlage (Legalitätsprinzip, Art. 5 Abs. 1 BV); "
                             "je intensiver der Eingriff in Rechte und Pflichten, "
                             "desto höher die erforderliche Normstufe.")
                raus.append({
                    "gewicht": "Muss", "taetigkeit": name,
                    "meldung": (f"Für diese Tätigkeit ({eingriff}er Eingriff) ist "
                                f"keine Grundlage auf Stufe «{noetig}» "
                                f"nachgewiesen. {warum}"),
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
    # Auch ein Vorbehalt verhindert die Entwarnung: er heisst «offen», und
    # offen ist nicht dasselbe wie unbedenklich. Genau diese Gleichsetzung war
    # der Fehler, den das Dokument dem Leser als Ergebnis verkaufte.
    if sperren(befunde):
        return False
    return all((e.get("wuerdigung") or {}).get("ergebnis") for e in befunde)


# ======================================================================== #
#  Der Ablauf: ein Schritt je Schicht
# ======================================================================== #

SCHRITTE = [
    ("taetigkeiten", "Tätigkeiten bestimmen"),
    ("kartierung", "Rechtsgrundlagen kartieren"),
    ("gap", "Lücken prüfen"),
    ("wuerdigung", "Zulässigkeit würdigen"),
    ("optionen", "Handlungsoptionen"),
    ("kapitel", "Dokument zusammenstellen"),
]


def schrittnamen():
    return [name for _, name in SCHRITTE]


def _mit_nr(liste):
    return [dict(e, nr=i) for i, e in enumerate(liste or []) if isinstance(e, dict)]


def _nach_nr(eintraege, schluessel):
    """{nr -> Eintrag} aus der Antwort einer Schicht."""
    raus = {}
    for e in (eintraege or {}).get(schluessel) or []:
        if not isinstance(e, dict):
            continue
        try:
            raus[int(e.get("nr"))] = e
        except (TypeError, ValueError):
            continue
    return raus


def befunde_aus(lauf):
    """Die Ergebnisse aller Schichten je Tätigkeit zusammengeführt.

    Das ist die Form, die `sperren` und `darf_entwarnen` erwarten – und die
    einzige Stelle, an der die Nummern wieder zu Tätigkeiten werden.
    """
    taet = _mit_nr((lauf.get("taetigkeiten") or {}).get("taetigkeiten"))
    kart = _nach_nr(lauf.get("kartierung"), "kartierungen")
    gap = _nach_nr(lauf.get("gap"), "luecken")
    wuerd = _nach_nr(lauf.get("wuerdigung"), "wuerdigungen")
    opt = _nach_nr(lauf.get("optionen"), "faelle")
    return [{"taetigkeit": t, "kartierung": kart.get(i, {}), "gap": gap.get(i, {}),
             "wuerdigung": wuerd.get(i, {}), "optionen": opt.get(i, {})}
            for i, t in enumerate(taet)]


# ======================================================================== #
#  Von der Kette ins Dokument
# ======================================================================== #

def _kurz(text, grenze=400):
    t = str(text or "").strip()
    return t if len(t) <= grenze else t[:grenze].rstrip() + " …"


def zu_kapiteln(lauf):
    """Bildet die Ergebnisse der Kette auf die Dokumentkapitel ab.

    Zwei Regeln tragen diese Funktion, und beide folgen aus dem gemessenen
    Fehlverhalten:

    * **Nichts wird behauptet, was nicht geprüft wurde.** Jede Zeile nennt die
      Tätigkeit, auf die sie sich bezieht – dadurch ist sichtbar, was NICHT
      abgedeckt ist.
    * **Die Sperren stehen im Dokument, nicht nur im Protokoll.** Ein
      Muss-Befund gehört in die Lückenliste und in die Beurteilung; sonst liest
      der Auftraggeber eine Analyse, die etwas anderes sagt als die Prüfung.
    """
    befunde = befunde_aus(lauf)
    meldungen = sperren(befunde)
    muss = [m for m in meldungen if m["gewicht"] == "Muss"]
    offen = [m for m in meldungen if m["gewicht"] == "Vorbehalt"]

    # ---- Bestehende Rechtsgrundlagen ------------------------------------ #
    bestehende, gesehen = [], set()
    for e in befunde:
        for g in (e["kartierung"].get("grundlagen") or []):
            if not isinstance(g, dict) or not g.get("erlass"):
                continue
            # Eine Schrankennorm erscheint hier nie – sie ermächtigt nicht.
            if ist_schrankennorm(g["erlass"]) or not g.get("ermaechtigt"):
                continue
            schluessel = g["erlass"].strip().lower()
            if schluessel in gesehen:
                continue
            gesehen.add(schluessel)
            teile = [t for t in (g.get("fundstelle"), g.get("geltung")) if t]
            bestehende.append({
                "rechtsgrundlage": g["erlass"],
                "beschreibung": " – ".join(teile) or
                                f"Deckt ab: {_kurz(e['taetigkeit'].get('taetigkeit'), 200)}",
            })
    if not bestehende:
        bestehende = [{
            "rechtsgrundlage": "Keine ermächtigende Grundlage nachgewiesen",
            "beschreibung": "Für keine der geprüften Tätigkeiten liess sich eine "
                            "Grundlage benennen, die sie ermächtigt.",
        }]

    # ---- Bevorstehende Änderungen --------------------------------------- #
    bevorstehend = []
    for e in befunde:
        for g in (e["kartierung"].get("grundlagen") or []):
            if isinstance(g, dict) and str(g.get("status", "")).lower() in (
                    "bevorstehend", "hängig", "haengig"):
                bevorstehend.append({
                    "rechtsgrundlage": g.get("erlass", ""),
                    "beschreibung": f"Status: {g.get('status')}. "
                                    f"{_kurz(g.get('geltung'), 200)}".strip(),
                    "auswirkung": "neutral",
                })

    # ---- Identifizierte Lücken ------------------------------------------ #
    luecken = []
    for m in muss:
        luecken.append({"luecke": _kurz(m["taetigkeit"], 120),
                        "beschreibung": m["meldung"]})
    for e in befunde:
        art = str((e["kartierung"].get("luecke") or {}).get("art", "")).lower()
        if art == "rechtsluecke" and e["gap"].get("bestaetigt"):
            stufe = e["gap"].get("erforderliche_normstufe", "")
            organ, referendum = NORMSTUFE_VERFAHREN.get(str(stufe).lower(), ("", ""))
            luecken.append({
                "luecke": _kurz(e["taetigkeit"].get("taetigkeit"), 120),
                "beschreibung": (f"{_kurz(e['gap'].get('begruendung'), 260)} "
                                 f"Erforderliche Normstufe: {stufe}"
                                 f"{f' ({organ}, {referendum})' if organ else ''}."),
            })
    for m in offen:
        luecken.append({"luecke": f"Offen: {_kurz(m['taetigkeit'], 110)}",
                        "beschreibung": m["meldung"]})
    if not luecken:
        luecken = [{"luecke": "Keine Lücke identifiziert",
                    "beschreibung": "Jede geprüfte Tätigkeit ist durch eine "
                                    "ermächtigende Grundlage der erforderlichen "
                                    "Normstufe gedeckt und wurde gewürdigt."}]

    # ---- Vorschläge zur Deckung ----------------------------------------- #
    vorschlaege = []
    for e in befunde:
        name = _kurz(e["taetigkeit"].get("taetigkeit"), 120)
        if e["gap"].get("deckungsvorschlag"):
            vorschlaege.append({"luecke": name,
                                "vorschlag": _kurz(e["gap"]["deckungsvorschlag"])})
        for o in (e["optionen"].get("optionen") or []):
            if isinstance(o, dict) and o.get("option"):
                vorschlaege.append({
                    "luecke": name,
                    "vorschlag": (f"Option: {_kurz(o['option'], 240)} "
                                  f"[Grundlage: {o.get('grundlage', '–')}; "
                                  f"Grenzen: {o.get('grenzen', '–')}]"),
                })
    if not vorschlaege:
        vorschlaege = [{
            "luecke": "Entfällt" if not luecken or luecken[0]["luecke"].startswith(
                "Keine Lücke") else "Offen",
            "vorschlag": "Es besteht keine zu deckende Lücke."
            if not muss and not offen else
            "Zu den offenen Punkten liegt noch kein Vorschlag vor.",
        }]

    # ---- Beurteilung der Konsequenzen ----------------------------------- #
    zeilen = []
    for e in befunde:
        w = e["wuerdigung"]
        if not w.get("ergebnis"):
            continue
        zeilen.append(
            f"{_kurz(e['taetigkeit'].get('taetigkeit'), 160)}: {w['ergebnis']}. "
            f"{_kurz(w.get('begruendung'), 320)}")
    if muss:
        zeilen.append("Zwingend zu klären, bevor dieses Vorhaben weitergeführt "
                      "werden kann: " + " ".join(m["meldung"] for m in muss))
    konsequenzen = "\n".join(zeilen) or (
        "Die Konsequenzen wurden nicht beurteilt. Dieses Dokument ist insoweit "
        "unvollständig und ohne die Beurteilung nicht freigabefähig.")

    # ---- Empfehlung ------------------------------------------------------ #
    if not befunde:
        empfehlung = ("Es liegt keine Empfehlung vor: aus dem Projektauftrag "
                      "liessen sich keine zu prüfenden Tätigkeiten ableiten.")
    elif muss:
        empfehlung = (
            "Das Vorhaben ist in der vorliegenden Form nicht weiterzuführen, "
            "solange die zwingenden Punkte offen sind. Diese Analyse ist "
            "beratend; die Beurteilung ist mit dem Rechtsdienst abzustimmen.")
    elif darf_entwarnen(befunde):
        empfehlung = (
            "Für jede geprüfte Tätigkeit besteht eine ermächtigende Grundlage der "
            "erforderlichen Normstufe, und jede wurde gewürdigt. Diese Analyse "
            "ist beratend; die Beurteilung ist mit dem Rechtsdienst abzustimmen.")
    else:
        empfehlung = (
            "Die Analyse ist nicht abgeschlossen: einzelne Punkte sind offen. "
            "Bis zu ihrer Klärung kann diese Analyse keine Freigabe tragen.")

    return {
        "bestehende_rechtsgrundlagen": bestehende,
        "bevorstehende_aenderungen": bevorstehend,
        "identifizierte_luecken": luecken,
        "vorschlaege_deckung": vorschlaege,
        "konsequenzen": konsequenzen,
        "empfehlung": empfehlung,
        "_sperren": meldungen,
    }
