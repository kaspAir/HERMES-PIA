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
import re

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
    # Art. 140 Abs. 1 lit. a BV: JEDE Verfassungsaenderung untersteht dem
    # obligatorischen Referendum - beim Bund braucht sie Volk UND Staende.
    "verfassung": ("Verfassungsgeber (Volk, beim Bund zusätzlich die Stände)",
                   "obligatorisches Referendum – die Abstimmung findet zwingend statt"),
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

# Sprachlich korrekt: aus «keiner» wurde durch blosses Anhaengen «keinerer».
EINGRIFF_TEXT = {
    "schwer": "schwerer Eingriff in Rechte und Pflichten",
    "leicht": "leichter Eingriff in Rechte und Pflichten",
    "keiner": "kein Eingriff in Rechte und Pflichten",
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


# Sicherheitsgrade. Im Recht ist der Unterschied zwischen «eindeutig» und
# «vertretbare Auffassung» der halbe Befund - eine Aussage ohne Grad liest
# sich immer wie die erste Stufe. Reihenfolge = absteigende Sicherheit.
SICHERHEITSGRADE = ("eindeutig", "überwiegend wahrscheinlich",
                    "vertretbare Auffassung", "offen")

# Woher eine vorgeschlagene Option stammt. Ohne diese Angabe liest sich eine
# hypothetische Gesetzgebungsoption wie geltendes Recht.
OPTION_HERKUNFT = ("aus bestehender Norm abgeleitet", "bekannte Praxis",
                   "hypothetische Gesetzgebungsoption",
                   "Schlussfolgerung dieser Analyse")


# Woran man erkennt, dass ein Text ueber die ANALYSE statt ueber das Vorhaben
# spricht. Gemessen stand im Dokument: «Obwohl das Eingabefeld 'eingriff.tiefe'
# auf 'keiner' gesetzt wurde …» - der Leser sieht weder Felder noch Objekte.
_SYSTEMSPRACHE = re.compile(
    r"eingabefeld|eingabeobjekt|eingangsobjekt|"
    r"\bfeld\s*['\u2019\"]|\bschema\b|\bjson\b|\btoken\b|"
    r"\bnr\.?\s*\d+\s*(?:des|im)\s*eingang",
    re.IGNORECASE)


def spricht_ueber_das_system(text):
    """Redet der Text ueber die Analyse statt ueber das Vorhaben?"""
    return bool(_SYSTEMSPRACHE.search(str(text or "")))


def massstaebe(wuerdigung):
    """Die angelegten Pruefmassstaebe – kurz und ohne Systemsprache.

    Das Modell schrieb hierher ganze Absaetze samt Meta-Kommentar ueber die
    Eingabedaten. Ein Massstab ist eine Norm, kein Aufsatz: was lang ist oder
    ueber die Analyse spricht, gehoert nicht in diese Zeile.
    """
    raus = []
    for m in (wuerdigung or {}).get("geprueft_an") or []:
        t = str(m or "").strip()
        if not t or spricht_ueber_das_system(t):
            continue
        # Nur den Kopf bis zum ersten Doppelpunkt/Gedankenstrich: dort steht
        # die Norm, danach beginnt die Begruendung.
        kopf = re.split(r"\s[–—-]\s|:\s", t, maxsplit=1)[0].strip(" .")
        if kopf and len(kopf) <= 120:
            raus.append(kopf)
    return raus


def eingriff_von(kartierung, wuerdigung):
    """Die MASSGEBLICHE Eingriffstiefe – und ob die Schichten sich einig sind.

    Rueckgabe: (tiefe, abweichung_oder_None)

    Die Kartierung sieht eine Taetigkeit zuerst, die Wuerdigung sieht sie
    genauer. Gemessen stufte die Kartierung eine flaechendeckende
    Videoueberwachung als «keiner» ein; die Wuerdigung erkannte den Fehler und
    schrieb ihn als Fliesstext ins Dokument - waehrend der Code weiter mit
    «keiner» rechnete und die Stufen-Sperre gar nicht greifen konnte.

    Massgeblich ist die spaetere, genauere Einschaetzung. Der Widerspruch
    verschwindet aber nicht: er wird als Befund ausgewiesen.
    """
    aus_kart = str((kartierung or {}).get("eingriff", {}).get("tiefe", "")).strip().lower()
    korrektur = (wuerdigung or {}).get("eingriff_korrigiert") or {}
    aus_wuerd = str(korrektur.get("tiefe", "")).strip().lower()
    if aus_wuerd and aus_wuerd in EINGRIFF_MINDESTSTUFE and aus_wuerd != aus_kart:
        return aus_wuerd, {
            "kartierung": aus_kart or "(nicht bestimmt)",
            "wuerdigung": aus_wuerd,
            "begruendung": str(korrektur.get("begruendung", "")).strip(),
        }
    return aus_kart, None


def sicherheit_von(eintrag, vorgabe="offen"):
    """Der Sicherheitsgrad eines Eintrags – Unbekanntes wird zu «offen».

    Bewusst vorsichtig: fehlt die Angabe, ist die Aussage NICHT eindeutig.
    """
    wert = str((eintrag or {}).get("sicherheit", "")).strip().lower()
    for grad in SICHERHEITSGRADE:
        if wert == grad.lower():
            return grad
    return vorgabe


def _quellen(eintrag):
    """Die Normen, auf die sich ein Eintrag stützt – als lesbarer Zusatz."""
    normen = [str(n).strip() for n in (eintrag or {}).get("stuetzt_sich_auf") or []
              if str(n).strip()]
    return f" Gestützt auf: {', '.join(normen)}." if normen else ""


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
    '"grundrechtseingriff_denkbar":true,"weichenbegruendung":"",'
    '"fachrecht":[""],'
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
        # Die Nummer stammt vom AUFRUFER und wird nie neu vergeben. Hier stand
        # eine eigene Nummerierung - und weil die Schicht stueckweise laeuft
        # (ein Element je Aufruf), wurde daraus jedes Mal «nr: 0». Alle
        # Kartierungen landeten damit auf der ersten Taetigkeit, die uebrigen
        # blieben leer. Im erzeugten Dokument trug eine Beschaffung die
        # beruehrten Rechte und die Grundlagen einer Freiheitsstrafe.
        "taetigkeiten": [dict(t, nr=t.get("nr", i))
                         for i, t in enumerate(liste or [])],
        "ebene": wissen.ebene or "nicht angegeben",
        "kanton": wissen.kanton or "nicht angegeben",
        "im_pia_genannte_erlasse": wissen.genannte_rechtsgrundlagen(),
        "bereits_verifizierte_fundstellen": gefundene or {},
    }
    user = (
        "Kartiere die Rechtsgrundlagen für JEDE dieser Tätigkeiten einzeln. "
        "Gib je Tätigkeit einen Eintrag mit ihrer Nummer zurück.\n\n"
        f"{json.dumps(eingang, ensure_ascii=False)}\n\n"
        "Stelle je Tätigkeit ZUERST die Weichenfrage: Ist ein staatlicher "
        "Grundrechtseingriff überhaupt denkbar? Eine Beschaffung, eine "
        "behördeninterne Koordination oder eine Systemablösung als solche "
        "greift in der Regel in keine Grundrechte ein. Lautet die Antwort "
        "NEIN, setze 'grundrechtseingriff_denkbar' auf false, begründe das "
        "kurz und nenne unter 'fachrecht' das einschlägige Spezialrecht "
        "(etwa das Beschaffungs-, Archiv- oder Organisationsrecht). Der "
        "Prüfpfad ist dann viel kürzer – das ist gewollt.\n"
        "Bestimme je Tätigkeit sodann, wie stark sie in Rechte und Pflichten "
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
    '"deckungsvorschlag":"",'
    '"sicherheit":"eindeutig|überwiegend wahrscheinlich|vertretbare Auffassung|offen",'
    '"stuetzt_sich_auf":[""],'
    '"confidence":{"stufe":"hoch|mittel|tief","begruendung":""}}]}')


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
    "- Sagt die Kartierung 'grundrechtseingriff_denkbar: false', ist die "
    "Weiche gestellt: prüfe NUR das Legalitätsprinzip und das genannte "
    "Fachrecht. Keine Normstufenherleitung, keine Verhältnismässigkeit, keine "
    "Kerngehaltsprüfung – und keine Begründung, warum du sie weglässt. Halte "
    "dich kurz; ein kurzer Prüfpfad ist bei einer solchen Tätigkeit das "
    "richtige Ergebnis, kein Mangel.\n"
    "- Berührt die Tätigkeit keine Grundrechte, prüfst du KEINE "
    "Grundrechtsschranke. Erfinde keinen Eingriff, um etwas zu prüfen zu haben – "
    "die meisten Verwaltungsvorhaben schränken keine Grundrechte ein, und für "
    "sie ist das Legalitätsprinzip der ganze Massstab.\n"
    "- Eine Grundlage zu HABEN heisst nicht, zulässig zu sein: sie muss die "
    "Tätigkeit auch decken.\n"
    "- Du erfindest keine Gerichtsentscheide und keine Fundstellen.\n"
    "- Deine Einschätzung ist BERATEND und ersetzt den Rechtsdienst nicht. "
    "Sag das im Feld 'vorbehalt'.\n"
    "- Hältst du die mitgelieferte Eingriffseinstufung für unzutreffend, "
    "KORRIGIERE sie im Feld 'eingriff_korrigiert' mit kurzer Begründung. "
    "Schreibe das NICHT in den Fliesstext: der Leser sieht die Zwischenschritte "
    "dieser Analyse nicht, und ein Hinweis auf Felder oder Eingabedaten ist für "
    "ihn wertlos. Deine Texte sprechen über das VORHABEN, nie über diese "
    "Analyse.\n"
    "- 'geprueft_an' nennt die angelegten MASSSTÄBE knapp – die Norm, nicht die "
    "Begründung. Die Begründung gehört in 'pruefung' und 'begruendung'.\n"
    "- JEDE Aussage traegt ihren SICHERHEITSGRAD: 'eindeutig' (die Rechtslage "
    "ist klar), 'überwiegend wahrscheinlich', 'vertretbare Auffassung' (andere "
    "Lesart begründbar) oder 'offen'. Im Recht ist dieser Unterschied der halbe "
    "Befund. Nutze 'eindeutig' sparsam – nur, wo Norm und Auslegung wirklich "
    "keinen Spielraum lassen.\n"
    "- JEDE Aussage nennt unter 'stuetzt_sich_auf' die NORMEN, die sie tragen – "
    "so genau wie möglich, mit Artikel und Absatz, wenn du ihn sicher kennst. "
    "Kennst du ihn nicht sicher, nenne nur den Erlass. Erfinde keine "
    "Fundstelle.\n"
    "- Sagst du 'kerngehalt_verletzt', gib zusätzlich "
    "'kerngehalt_sicherheit' und 'kerngehalt_stuetzt_sich_auf' an. Das ist die "
    "stärkste Aussage, die du treffen kannst – sie muss ihre Grundlage nennen.\n"
    "Antworte AUSSCHLIESSLICH mit validem JSON nach dem vorgegebenen Schema."
)

_SCHEMA_WUERDIGUNG = (
    '{"wuerdigungen":[{"nr":0,"rechtsgueter":[""],"geprueft_an":[""],'
    '"pruefung":[{"kriterium":"","ergebnis":"erfüllt|fraglich|nicht erfüllt",'
    '"begruendung":"","stuetzt_sich_auf":[""],'
    '"sicherheit":"eindeutig|überwiegend wahrscheinlich|vertretbare Auffassung|offen"}],'
    '"ergebnis":"zulässig|bedingt zulässig|nicht zulässig",'
    '"sicherheit":"eindeutig|überwiegend wahrscheinlich|vertretbare Auffassung|offen",'
    '"stuetzt_sich_auf":[""],'
    '"eingriff_korrigiert":{"tiefe":"schwer|leicht|keiner","begruendung":""},'
    '"kerngehalt_verletzt":false,'
    '"kerngehalt_sicherheit":"eindeutig|überwiegend wahrscheinlich|vertretbare Auffassung|offen",'
    '"kerngehalt_stuetzt_sich_auf":[""],'
    '"begruendung":"","vorbehalt":"",'
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
    "- JEDE Option legt ihre HERKUNFT offen: 'aus bestehender Norm abgeleitet' "
    "(eine geltende Norm trägt sie bereits), 'bekannte Praxis' (so wird es "
    "andernorts gemacht), 'hypothetische Gesetzgebungsoption' (setzt eine erst "
    "zu schaffende Norm voraus) oder 'Schlussfolgerung dieser Analyse'. Ohne "
    "diese Angabe liest sich eine hypothetische Option wie geltendes Recht.\n"
    "- Dazu je Option die tragenden Normen ('stuetzt_sich_auf') und den "
    "Sicherheitsgrad.\n"
    "Antworte AUSSCHLIESSLICH mit validem JSON nach dem vorgegebenen Schema."
)

_SCHEMA_OPTIONEN = (
    '{"faelle":[{"nr":0,"eigentliches_ziel":"",'
    '"optionen":[{"option":"","grundlage":"","voraussetzungen":"","grenzen":"",'
    '"herkunft":"aus bestehender Norm abgeleitet|bekannte Praxis|'
    'hypothetische Gesetzgebungsoption|Schlussfolgerung dieser Analyse",'
    '"stuetzt_sich_auf":[""],'
    '"sicherheit":"eindeutig|überwiegend wahrscheinlich|vertretbare Auffassung|offen"}],'
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

        # MASSGEBLICH ist die spaetere, genauere Einschaetzung. Rechnete man
        # weiter mit der Kartierung, griffe die Stufen-Sperre genau dort nicht,
        # wo die Kartierung sich geirrt hat - also im gefaehrlichsten Fall.
        eingriff, abweichung = eingriff_von(kart, wuerd)
        if abweichung:
            raus.append({
                "gewicht": "Vorbehalt", "taetigkeit": name,
                "meldung": (
                    f"Die Kartierung stufte den Eingriff als "
                    f"«{abweichung['kartierung']}» ein, die vertiefte Würdigung "
                    f"als «{abweichung['wuerdigung']}». Massgeblich ist die "
                    f"Würdigung. {abweichung['begruendung']}").strip(),
            })
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
                    "meldung": (f"Für diese Tätigkeit "
                                f"({EINGRIFF_TEXT.get(eingriff, eingriff)}) ist "
                                f"keine Grundlage auf Stufe «{noetig}» "
                                f"nachgewiesen. {warum}"),
                })

        # 3. Der Kerngehalt ist unantastbar – auch ein Gesetz hilft dann nicht.
        #    Das ist die staerkste Aussage der ganzen Analyse. Sie muss deshalb
        #    sagen, WORAUF sie sich stuetzt und wie sicher sie ist - sonst liest
        #    sie sich wie eine bewiesene Tatsache statt wie eine Einschaetzung.
        if wuerd.get("kerngehalt_verletzt"):
            grad = sicherheit_von({"sicherheit": wuerd.get("kerngehalt_sicherheit")})
            quellen = _quellen({"stuetzt_sich_auf":
                                wuerd.get("kerngehalt_stuetzt_sich_auf")})
            raus.append({
                "gewicht": "Muss", "taetigkeit": name,
                "meldung": (f"Nach der vorgängigen Würdigung ist der Kerngehalt "
                            f"eines Grundrechts verletzt (Sicherheit: {grad}). "
                            f"Trifft das zu, wäre die Tätigkeit auch mit einer "
                            f"gesetzlichen Grundlage unzulässig und das Vorhaben "
                            f"in dieser Form nicht umsetzbar.{quellen}"),
            })

        # 4. Als unzulässig gewürdigt.
        if str(wuerd.get("ergebnis", "")).lower().startswith("nicht zulässig"):
            grad = sicherheit_von(wuerd)
            raus.append({
                "gewicht": "Muss", "taetigkeit": name,
                "meldung": (f"Die Würdigung kommt zum Ergebnis, dass diese "
                            f"Tätigkeit nach den vorliegenden Projektangaben "
                            f"nicht zulässig wäre (Sicherheit: {grad})."
                            f"{_quellen(wuerd)}"),
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


def zuordnungsluecken(lauf):
    """Taetigkeiten, zu denen eine Schicht KEIN Ergebnis geliefert hat.

    Eine stille Fehlzuordnung ist die gefaehrlichste Art von Fehler: das
    Dokument sieht vollstaendig aus und ordnet Befunde der falschen Taetigkeit
    zu. Gemessen war genau das der Fall.
    """
    taet = _mit_nr((lauf.get("taetigkeiten") or {}).get("taetigkeiten"))
    fehlend = []
    for schluessel, liste in (("kartierung", "kartierungen"),
                              ("wuerdigung", "wuerdigungen")):
        vorhanden = set(_nach_nr(lauf.get(schluessel), liste))
        for i, t in enumerate(taet):
            if i not in vorhanden:
                fehlend.append((schluessel, i, t.get("taetigkeit", "")))
    return fehlend


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

def _text(wert):
    """Der Text, unveraendert.

    Hier stand eine Kuerzung auf 400 bzw. 320 Zeichen. Sie schnitt Begruendungen
    mitten im Satz ab - gemessen im Kapitel «Beurteilung der Konsequenzen». Die
    Regel gilt auf BEIDEN Seiten: was am Eingang nicht gekuerzt werden darf,
    darf es am Ausgang auch nicht. Ein halber Satz ist im Recht schlimmer als
    ein langer.
    """
    return str(wert or "").strip()


# Artikelangaben sind NICHT verifiziert. Die Anwendung prueft Erlasse gegen die
# amtlichen Sammlungen (Fedlex/lexfind), einzelne Artikel nicht. Gemessen stand
# im Dokument «StPO Art. 351 ff., insb. Art. 354» fuer die Vollstreckung von
# Bussen - Art. 354 StPO regelt die Einsprache gegen den Strafbefehl. Eine
# falsche Artikelangabe ist gefaehrlicher als gar keine: sie sieht praeziser
# aus, als sie belegt ist.
_ARTIKEL = re.compile(r"\bArt\.\s*\d", re.IGNORECASE)

ARTIKEL_HINWEIS = {
    "rechtsgrundlage": "Hinweis zu den Fundstellen",
    "beschreibung": ("Die aufgeführten ERLASSE sind gegen die amtlichen "
                     "Sammlungen geprüft. Die ARTIKELANGABEN sind es nicht – "
                     "sie stammen aus der Analyse und sind vor einer Freigabe "
                     "einzeln zu verifizieren."),
}


def nennt_artikel(text):
    """Enthält der Text eine Artikelangabe? (Die ist nie verifiziert.)"""
    return bool(_ARTIKEL.search(str(text or "")))


def nicht_heilbar(wuerdigung):
    """Ist die Tätigkeit durch KEINE Normstufe zu retten?

    Bei einer Kerngehaltsverletzung hilft weder ein Gesetz noch eine
    Verfassungsänderung: Art. 36 Abs. 4 BV erklärt den Kerngehalt für
    unantastbar. Gemessen stand im Dokument «Kerngehalt verletzt» und eine
    Zeile darunter «zu schaffen auf Stufe gesetz» – ein Weg, den es nicht
    gibt, direkt neben der Feststellung, dass es ihn nicht gibt.

    Die Gap-Analyse kann das nicht wissen: sie läuft VOR der Würdigung.
    Auflösen muss es deshalb der Code beim Zusammenbauen.
    """
    return bool((wuerdigung or {}).get("kerngehalt_verletzt"))


def _kontextvorbehalte(lauf):
    """Vorbehalte, die aus fehlenden PROJEKTANGABEN folgen.

    Ohne Kanton bleibt jede Aussage zum kantonalen Recht hypothetisch - das
    Dokument sprach dann von «dem kantonalen Polizeigesetz», ohne sagen zu
    koennen, welches gemeint ist. Das gehoert an den Anfang, nicht zwischen
    die Befunde.
    """
    kontext = lauf.get("_kontext") or {}
    ebene = str(kontext.get("ebene") or "").lower()
    raus = []
    if ("kanton" in ebene or "kommun" in ebene) and not (kontext.get("kanton") or "").strip():
        raus.append({
            "gewicht": "Vorbehalt", "taetigkeit": "(ganzes Vorhaben)",
            "meldung": ("Der Kanton ist nicht angegeben. Alle Aussagen zum "
                        "kantonalen Recht sind deshalb VORLÄUFIG – welcher "
                        "Erlass gilt, lässt sich ohne diese Angabe nicht "
                        "bestimmen. Die Analyse ist nach Angabe des Kantons zu "
                        "wiederholen."),
        })
    return raus


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
    meldungen = _kontextvorbehalte(lauf) + sperren(befunde)
    # Fehlende Schichtergebnisse werden AUSGEWIESEN, nicht verschwiegen: eine
    # Taetigkeit ohne Kartierung oder ohne Wuerdigung ist nicht geprueft, und
    # das Dokument darf nicht so tun, als waere sie es.
    for schicht, _nr, name in zuordnungsluecken(lauf):
        meldungen.append({
            "gewicht": "Vorbehalt", "taetigkeit": name,
            "meldung": (f"Zu dieser Tätigkeit liegt kein Ergebnis der Schicht "
                        f"«{schicht}» vor. Sie ist insoweit ungeprüft."),
        })
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
                                f"Deckt ab: {_text(e['taetigkeit'].get('taetigkeit'))}",
            })
    if bestehende and any(nennt_artikel(z["beschreibung"]) for z in bestehende):
        bestehende.append(dict(ARTIKEL_HINWEIS))
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
                                    f"{_text(g.get('geltung'))}".strip(),
                    "auswirkung": "neutral",
                })
    if not bevorstehend:
        # Eine LEERE Liste laesst die Vorlagenzeile stehen - im erzeugten
        # Dokument standen dort die Platzhalter «…» der Vorlage, und das sieht
        # aus wie ein Abbruch. Eine leere Tabelle muss sagen, dass sie leer ist.
        bevorstehend = [{
            "rechtsgrundlage": "Keine bevorstehende Änderung erhoben",
            "beschreibung": "Diese Analyse hat den Status der aufgeführten "
                            "Erlasse festgehalten, aber laufende Revisionen "
                            "nicht systematisch abgefragt. Aus dem Fehlen von "
                            "Einträgen folgt deshalb nicht, dass keine Änderung "
                            "bevorsteht.",
            "auswirkung": "neutral",
        }]

    # ---- Identifizierte Lücken ------------------------------------------ #
    # Je Taetigkeit EINE Zeile. Vorher erzeugte jede Sperre ihre eigene, und
    # dieselbe Taetigkeit stand vier- bis fuenfmal untereinander - mit
    # teilweise wortgleichem Text. Das erschwerte das Lesen erheblich.
    luecken = []
    gesammelt = {}
    for m in muss:
        gesammelt.setdefault(_text(m["taetigkeit"]), []).append(m["meldung"])
    begruendungen = {_text((e.get("taetigkeit") or {}).get("taetigkeit")):
                     _text((e.get("wuerdigung") or {}).get("begruendung"))
                     for e in befunde}
    for name, meldungstexte in gesammelt.items():
        # Die ausformulierte Begruendung steht bei der Luecke, die sie traegt -
        # nicht ein zweites Mal im Entscheid-Kapitel.
        text = " ".join(meldungstexte)
        if begruendungen.get(name):
            text = f"{text} {begruendungen[name]}"
        luecken.append({"luecke": name, "beschreibung": text})
    for e in befunde:
        art = str((e["kartierung"].get("luecke") or {}).get("art", "")).lower()
        if art == "rechtsluecke" and e["gap"].get("bestaetigt"):
            stufe = e["gap"].get("erforderliche_normstufe", "")
            organ, referendum = NORMSTUFE_VERFAHREN.get(str(stufe).lower(), ("", ""))
            if nicht_heilbar(e["wuerdigung"]):
                zusatz = ("Diese Lücke ist durch KEINE Normstufe zu schliessen: "
                          "die Würdigung sieht den Kerngehalt verletzt, und der "
                          "Kerngehalt ist nach Art. 36 Abs. 4 BV unantastbar – "
                          "auch eine Verfassungsänderung hülfe nicht.")
            else:
                zusatz = (f"Erforderliche Normstufe: {stufe}"
                          f"{f' ({organ}, {referendum})' if organ else ''}.")
            luecken.append({
                "luecke": _text(e["taetigkeit"].get("taetigkeit")),
                "beschreibung": f"{_text(e['gap'].get('begruendung'))} {zusatz}",
            })
    offen_gesammelt = {}
    for m in offen:
        offen_gesammelt.setdefault(_text(m["taetigkeit"]), []).append(m["meldung"])
    for name, meldungstexte in offen_gesammelt.items():
        luecken.append({"luecke": f"Offen: {name}",
                        "beschreibung": " ".join(meldungstexte)})
    if not luecken:
        luecken = [{"luecke": "Keine Lücke identifiziert",
                    "beschreibung": "Jede geprüfte Tätigkeit ist durch eine "
                                    "ermächtigende Grundlage der erforderlichen "
                                    "Normstufe gedeckt und wurde gewürdigt."}]

    # ---- Vorschläge zur Deckung ----------------------------------------- #
    vorschlaege = []
    for e in befunde:
        name = _text(e["taetigkeit"].get("taetigkeit"))
        # Ist der Kerngehalt verletzt, ist JEDER Normweg versperrt - ein
        # Deckungsvorschlag darf dann nicht wie eine gangbare Loesung dastehen.
        sperrvermerk = (
            " ACHTUNG: Die Würdigung sieht den Kerngehalt verletzt. Solange "
            "die Tätigkeit so ausgestaltet ist, führt auch dieser Weg nicht zur "
            "Zulässigkeit – der Kerngehalt ist nach Art. 36 Abs. 4 BV "
            "unantastbar."
        ) if nicht_heilbar(e["wuerdigung"]) else ""
        if e["gap"].get("deckungsvorschlag"):
            vorschlaege.append({
                "luecke": name,
                "vorschlag": _text(e["gap"]["deckungsvorschlag"]) + sperrvermerk})
        for o in (e["optionen"].get("optionen") or []):
            if isinstance(o, dict) and o.get("option"):
                # Ohne Herkunftsangabe liest sich eine hypothetische
                # Gesetzgebungsoption wie geltendes Recht.
                herkunft = str(o.get("herkunft", "")).strip() or \
                    "Schlussfolgerung dieser Analyse"
                vorschlaege.append({
                    "luecke": name,
                    "vorschlag": (
                        f"{_text(o['option'])}\n"
                        f"Herkunft: {herkunft} · Sicherheit: {sicherheit_von(o)}\n"
                        f"Grundlage: {o.get('grundlage') or '–'}\n"
                        f"Voraussetzungen: {o.get('voraussetzungen') or '–'}\n"
                        f"Grenzen: {o.get('grenzen') or '–'}"
                        f"{_quellen(o)}"
                        f"{sperrvermerk if 'Gesetzgebungsoption' in herkunft else ''}"),
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
    # Der BEGRUENDUNGSGRAPH: die Kette Taetigkeit -> Recht -> Massstab ->
    # Wuerdigung -> Rechtslage -> Alternative -> Folge, je Taetigkeit. Diese
    # Stationen durchlaeuft die Analyse ohnehin; sichtbar gemacht kann der
    # Leser eine Empfehlung bis zu ihrem Ursprung zurueckverfolgen und dort
    # widersprechen. Vorher stand hier ein Absatz je Taetigkeit, in dem alles
    # vermischt war.
    # Kapitel 6 ist ein MANAGEMENTENTSCHEID, keine zweite Herleitung. Es
    # wiederholte zuvor Eingriff, Würdigung, Alternativen und Vorbehalte –
    # alles Dinge, die in den Kapiteln 2–5 bereits stehen. Für den Entscheid
    # eines Projektausschusses genügen fünf Angaben je Tätigkeit; der
    # zurückgelegte Prüfpfad hält die Nachvollziehbarkeit in einer Zeile.
    zeilen = [managemententscheid(befunde, meldungen)] if befunde else []
    konsequenzen = "\n".join(zeilen) or (
        "Die Konsequenzen wurden nicht beurteilt. Dieses Dokument ist insoweit "
        "unvollständig und ohne die Beurteilung nicht freigabefähig.")

    # ---- Empfehlung ------------------------------------------------------ #
    if not befunde:
        empfehlung = ("Es liegt keine Empfehlung vor: aus dem Projektauftrag "
                      "liessen sich keine zu prüfenden Tätigkeiten ableiten.")
    elif muss:
        # DIFFERENZIEREN statt pauschal stoppen. Ein Muss-Befund betrifft EINE
        # Taetigkeit, nicht das Vorhaben. Und in der Initialisierung ist «zu
        # klaeren» die richtige Anweisung - nicht «Stopp»: die Phase dient
        # genau dieser Klaerung. Etwas anderes gilt nur beim Kerngehalt, denn
        # den kann keine Klaerung heilen.
        betroffen = sorted({m["taetigkeit"] for m in muss})
        sauber = sorted({_text((e.get("taetigkeit") or {}).get("taetigkeit"))
                         for e in befunde} - set(betroffen))
        endgueltig = [e for e in befunde if nicht_heilbar(e.get("wuerdigung"))]
        teile = []
        if endgueltig:
            teile.append(
                "Für mindestens eine Tätigkeit sieht die Würdigung den "
                "Kerngehalt eines Grundrechts verletzt. Diese Tätigkeit ist in "
                "der vorgesehenen Form nicht umsetzbar – dort hilft keine "
                "weitere Abklärung, sondern nur eine Änderung des Vorhabens.")
        teile.append(
            f"Zwingend zu klären ({len(betroffen)} von {len(befunde)} "
            f"Tätigkeiten): {'; '.join(betroffen)}.")
        if sauber:
            teile.append(
                f"Ohne Einwände aus Sicht der Rechtsgrundlagen sind: "
                f"{'; '.join(sauber)}. Diese Tätigkeiten können unabhängig "
                f"weiterverfolgt werden.")
        if not endgueltig:
            teile.append(
                "Für die Initialisierungsphase heisst das nicht Abbruch, "
                "sondern Klärungsauftrag: die genannten Punkte sind in dieser "
                "Phase zu bereinigen, bevor der Durchführungsauftrag "
                "freigegeben wird.")
        teile.append(
            "Diese Einschätzung stützt sich auf die vorstehende Würdigung und "
            "auf die im PIA beschriebenen Tätigkeiten; ändern sich diese, ist "
            "sie neu zu bilden. Die Analyse ist beratend und ersetzt die "
            "Beurteilung durch den Rechtsdienst nicht.")
        empfehlung = " ".join(teile)
    elif darf_entwarnen(befunde):
        empfehlung = (
            "Für jede geprüfte Tätigkeit besteht eine ermächtigende Grundlage der "
            "erforderlichen Normstufe, und jede wurde gewürdigt. Diese Analyse "
            "ist beratend; die Beurteilung ist mit dem Rechtsdienst abzustimmen.")
    else:
        empfehlung = (
            "Die Analyse ist nicht abgeschlossen: einzelne Punkte sind offen. "
            "Bis zu ihrer Klärung kann diese Analyse keine Freigabe tragen.")

    # ---- Product Compliance --------------------------------------------- #
    # Sie war «nicht Gegenstand dieser Analyse», obwohl der PIA die Beschaffung
    # ausdruecklich behandelt. Das Fachrecht, das die Kartierung je Taetigkeit
    # nennt, IST der Anknuepfungspunkt - es aufzufuehren ist ehrlicher, als das
    # Kapitel leer zu lassen.
    compliance, gesehen_fach = [], set()
    for e in befunde:
        name = _text((e.get("taetigkeit") or {}).get("taetigkeit"))
        for f in (e["kartierung"].get("fachrecht") or []):
            schluessel = str(f).strip()
            if not schluessel or schluessel.lower() in gesehen_fach:
                continue
            gesehen_fach.add(schluessel.lower())
            compliance.append({
                "compliance": schluessel,
                "beschreibung": (f"Einschlägig für: {name}. Die Anforderungen "
                                 f"dieses Erlasses sind im weiteren Verlauf "
                                 f"einzuhalten; diese Analyse hat sie nicht "
                                 f"im Einzelnen erhoben."),
            })
    if not compliance:
        compliance = [{
            "compliance": "Kein Fachrecht mit Produktbezug erhoben",
            "beschreibung": ("Die Kartierung hat zu den geprüften Tätigkeiten "
                             "kein Fachrecht mit Anforderungen an die "
                             "Produktkonformität benannt. Erhoben wurde es "
                             "nicht eigens – das Fehlen von Einträgen ist "
                             "deshalb kein Nachweis."),
        }]

    return {
        "product_compliance": compliance,
        "bestehende_rechtsgrundlagen": bestehende,
        "bevorstehende_aenderungen": bevorstehend,
        "identifizierte_luecken": luecken,
        "vorschlaege_deckung": vorschlaege,
        "konsequenzen": konsequenzen,
        "empfehlung": empfehlung,
        "_sperren": meldungen,
    }


# ======================================================================== #
#  Der Begründungsgraph
# ======================================================================== #

def pruefpfad(eintrag):
    """Der zurückgelegte Weg in EINER Zeile.

    Der ausführliche Begründungsgraph wiederholte, was in den Kapiteln 2–5
    ohnehin steht – Eingriff, Würdigung, Alternativen, Vorbehalte. Für den
    Entscheid genügt der Weg; die Einzelheiten stehen dort, wo sie hingehören.
    """
    kart = eintrag.get("kartierung") or {}
    wuerd = eintrag.get("wuerdigung") or {}
    tiefe, _ = eingriff_von(kart, wuerd)
    stationen = ["Tätigkeit"]
    if kart.get("grundrechtseingriff_denkbar") is False:
        # Die frühe Weiche: kein Grundrechtseingriff denkbar -> direkt Fachrecht.
        fach = ", ".join(str(f) for f in (kart.get("fachrecht") or []) if str(f).strip())
        stationen.append("kein Grundrechtseingriff")
        stationen.append(f"Fachrecht ({fach})" if fach else "Fachrecht")
    else:
        rechte = [str(r) for r in (kart.get("eingriff") or {}).get("grundrechte") or []
                  if str(r).strip()]
        if rechte:
            stationen.append(", ".join(rechte))
        if tiefe:
            stationen.append(EINGRIFF_TEXT.get(tiefe, tiefe))
        noetig = EINGRIFF_MINDESTSTUFE.get(tiefe, "")
        if noetig:
            stationen.append(f"Normstufe {noetig}")
    if wuerd.get("ergebnis"):
        stationen.append(str(wuerd["ergebnis"]))
    return " → ".join(stationen)


def managemententscheid(befunde, meldungen=None):
    """Kapitel «Beurteilung der Konsequenzen» für den Projektausschuss.

    Fünf Angaben je Tätigkeit – Zulässigkeit, Unsicherheit, Handlungsbedarf,
    Empfehlung und der zurückgelegte Prüfpfad. Mehr braucht ein Ausschuss für
    seinen Entscheid nicht; die Herleitung steht in den Kapiteln davor.
    """
    nach_taetigkeit = {}
    for m in meldungen or []:
        nach_taetigkeit.setdefault(m.get("taetigkeit"), []).append(m)

    bloecke = []
    for e in befunde or []:
        t = e.get("taetigkeit") or {}
        name = _text(t.get("taetigkeit"))
        w = e.get("wuerdigung") or {}
        eigene = nach_taetigkeit.get(name, [])
        muss = [m for m in eigene if m["gewicht"] == "Muss"]
        offen = [m for m in eigene if m["gewicht"] == "Vorbehalt"]

        if muss:
            entscheid = ("So nicht weiterführen – die zwingenden Punkte sind "
                         "vor jedem weiteren Schritt zu klären.")
        elif offen:
            entscheid = ("Weiterführen möglich, sobald die offenen Punkte "
                         "geklärt sind.")
        elif w.get("ergebnis"):
            entscheid = "Keine Einwände aus Sicht der Rechtsgrundlagen."
        else:
            entscheid = "Kein Entscheid möglich – diese Tätigkeit wurde nicht gewürdigt."

        handlungsbedarf = [m["meldung"] for m in muss] or \
                          [m["meldung"] for m in offen] or ["keiner"]

        zeilen = [
            f"Tätigkeit: {name}",
            f"Zulässig: {w.get('ergebnis') or 'nicht beurteilt'}",
            f"Unsicherheit: {sicherheit_von(w)}",
            "Handlungsbedarf: " + " · ".join(handlungsbedarf),
            f"Entscheidungsempfehlung: {entscheid}",
            f"Prüfpfad: {pruefpfad(e)}",
        ]
        # Die ausformulierte Begründung steht bei der Lücke, die sie trägt.
        # Gibt es keine Lücke, gibt es dort auch keinen Platz – dann gehört sie
        # hierher, sonst stünde «zulässig» völlig unbegründet da.
        if not eigene and _text(w.get("begruendung")):
            zeilen.append(f"Begründung: {_text(w.get('begruendung'))}")
        bloecke.append("\n".join(zeilen))
    return "\n\n".join(bloecke)
