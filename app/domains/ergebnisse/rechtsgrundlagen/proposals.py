"""Beratender Entwurf der analytischen Abschnitte der Rechtsgrundlagenanalyse.

EIN LLM-Aufruf erzeugt aus dem Projektkontext Vorschläge für die Kern-Abschnitte.
Harte Regel: KEINE erfundenen Fundstellen (SR-/NG-Nummern, Datierungen, Artikel) –
die verifizierte Fundstelle liefert später Phase B (Fedlex). Ohne LLM bleibt der
Entwurf leer (nur das PIA-Seeding greift) – nie wird geraten.
"""
import json
import re
from app.domains.llm.errors import PseudoFehler


def _parse_json(raw):
    if not raw:
        return None
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group())
    except (ValueError, TypeError):
        return None


SYSTEM = (
    "Du bist ein juristisch versierter HERMES-2022-Berater und erstellst die "
    "Rechtsgrundlagenanalyse eines Schweizer Behördenprojekts.\n"
    "GRUNDPRINZIP: Verwaltungshandeln braucht eine gesetzliche Grundlage. Die Analyse "
    "prüft, ob für die im Projekt GEPLANTEN Tätigkeiten (die Ziele) jeweils eine "
    "Rechtsgrundlage besteht.\n"
    "HERMES-2022-METHODENGRENZEN (STRIKT, niemals verletzen):\n"
    "- Diese Analyse betrifft AUSSCHLIESSLICH die Rechtsgrundlagen (Gesetze/Verordnungen) "
    "  für die geplanten Tätigkeiten.\n"
    "- Datenschutz UND Informationssicherheit (DSG, VDSG, ISG, ISV, ISDS, Schutzbedarf) "
    "  sind NICHT Gegenstand dieser Analyse – sie gehören in die SCHUTZBEDARFSANALYSE. "
    "  Führe sie NICHT als Product Compliance auf, erwähne sie NICHT in Konsequenzen/"
    "  Empfehlung, empfiehl NIEMALS 'ISDS abschliessen/erstellen' o.ä. Ob ein ISDS-Konzept "
    "  nötig ist, folgt erst aus der Schutzbedarfsanalyse; das Konzept selbst entsteht in "
    "  einer SPÄTEREN Phase.\n"
    "- Empfiehl NICHTS zu späteren Phasen (Konzept/Realisierung/Einführung/Umsetzung/"
    "  Abschluss) und NICHTS zum Vorgehensentscheid klassisch/agil – dieser wird erst am "
    "  Meilenstein 'Weiteres Vorgehen' getroffen.\n"
    "WEITERE REGELN:\n"
    "- LÜCKEN nur KONSERVATIV: Standard-Verwaltungs- und Justiztätigkeiten haben in "
    "  aller Regel bereits eine Grundlage. Nimm eine Lücke NUR an, wenn für eine KONKRET "
    "  NEUE geplante Tätigkeit keine plausible bestehende Rechtsgrundlage benennbar ist. "
    "  Im Zweifel KEINE Lücke (leere Liste).\n"
    "- Erfinde NIEMALS Fundstellen (SR-/NG-Nummern, Datierungen, Artikel).\n"
    "- Die Empfehlung ist KONKRET und direkt in dieser Analyse umzusetzen (es gibt in "
    "  HERMES KEIN Folgedokument) und bleibt bei RECHTLICHEN Schlussfolgerungen: "
    "  bestehende Grundlagen genügen / Rechtsgrundlage schaffen bzw. ändern (Gesetz "
    "  Legislative, Verordnung Exekutive, Richtlinie Verwaltung) / offene rechtliche "
    "  Punkte klären – alles innerhalb der Phase Initialisierung.\n"
    "- Sachlicher Behördenstil, Hochdeutsch. Antworte NUR mit validem JSON."
)


def analysiere(wissen, llm, grounding=None, bestehende_namen=None):
    """Ziele-getriebene Analyse. Gibt Dict zurück (leer ohne LLM):
    {bestehende:[{rechtsgrundlage,beschreibung}], bevorstehende:[{...,auswirkung}],
     luecken:[{luecke,beschreibung}], vorschlaege:[{luecke,vorschlag}],
     compliance:[{compliance,beschreibung}], konsequenzen:str, empfehlung:str}

    `grounding`: {name -> {sr,titel,url}} verifizierter Bundesfundstellen.
    `bestehende_namen`: die (gefilterten) relevanten Gesetze für Kap. 1."""
    if llm is None:
        return {}
    ebene = wissen.ebene or "nicht angegeben"
    kanton = wissen.kanton or "nicht angegeben"
    ziele = wissen.ziel_beschreibungen()
    bestehende_namen = bestehende_namen or wissen.genannte_rechtsgrundlagen()
    verifiziert = ""
    if grounding:
        verifiziert = "Verifizierte Bundes-Fundstellen (Fedlex, gesichert):\n" + "\n".join(
            f"  - {name}: SR {g['sr']} – {g['titel']}" for name, g in grounding.items()
        ) + "\n"
    ziele_txt = "\n".join(f"  - {z}" for z in ziele) or "  (keine Ziele erfasst)"
    user = (
        f"Staatsebene: {ebene}. Kanton: {kanton}.\n"
        f"Ausgangslage: {wissen.ausgangslage_text()[:1200]}\n"
        f"GEPLANTE TÄTIGKEITEN / ZIELE des Projekts:\n{ziele_txt}\n"
        f"Bereits identifizierte Rechtsgrundlagen: {', '.join(bestehende_namen) or 'keine'}\n"
        f"{verifiziert}\n"
        "Prüfe je Ziel, ob eine Rechtsgrundlage besteht. Gib NUR JSON:\n"
        '{"bestehende":[{"rechtsgrundlage":"","beschreibung":""}],'
        '"bevorstehende":[{"rechtsgrundlage":"","beschreibung":"","auswirkung":"positiv|neutral|negativ"}],'
        '"luecken":[{"luecke":"","beschreibung":""}],'
        '"vorschlaege":[{"luecke":"","vorschlag":""}],'
        '"compliance":[{"compliance":"","beschreibung":""}],'
        '"konsequenzen":"","empfehlung":""}\n'
        "- 'bestehende': ERMITTLE SELBST die einschlägigen bestehenden Rechtsgrundlagen "
        "für die geplanten Tätigkeiten – AUCH solche, die oben nicht aufgeführt sind, "
        "sofern du sie sicher kennst (einschlägige Bundesgesetze/-verordnungen des "
        "Fachbereichs, z.B. im Justiz-/Strafregisterumfeld StReG/StReV, StGB, StPO). "
        "Nenne je Eintrag den Gesetzesnamen MIT gebräuchlicher Abkürzung in Klammern und "
        "eine kurze Beschreibung, welche Tätigkeit die Grundlage abdeckt. KEINE erfundene "
        "SR-Nummer/Datierung – die Fundstelle wird separat verifiziert.\n"
        "- 'luecken': führe die Prüfung tatsächlich durch. Eine Lücke NUR, wenn für eine "
        "konkret geplante Tätigkeit KEINE bestehende Rechtsgrundlage benennbar ist. Sind "
        "alle Tätigkeiten gedeckt, gib eine LEERE Liste zurück (es muss keine Lücke "
        "gefunden werden).\n"
        "- 'vorschlaege': je Lücke die passende Normebene zur Deckung – neues/geändertes "
        "GESETZ (Legislative/Parlament), VERORDNUNG (Exekutive/Regierung) oder interne "
        "RICHTLINIE/WEISUNG (Verwaltung), je nach Regelungsgegenstand.\n"
        "- 'bevorstehende': nur wenn eine Rechtsänderung tatsächlich absehbar ist, sonst [].\n"
        "- 'empfehlung': konkret und in dieser Analyse umgesetzt. Fasse dich kurz."
    )
    try:
        raw = llm.complete(SYSTEM, [{"role": "user", "content": user}], max_tokens=3500)
    except PseudoFehler:
        raise                    # MUSS durchschlagen (ANBINDUNG.md 6.2)
    except Exception:  # noqa: BLE001 – LLM-Ausfall: lieber leerer Entwurf als Fehler
        return {}
    return _parse_json(raw) or {}
