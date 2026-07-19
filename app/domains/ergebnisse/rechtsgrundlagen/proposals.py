"""Beratender Entwurf der analytischen Abschnitte der Rechtsgrundlagenanalyse.

EIN LLM-Aufruf erzeugt aus dem Projektkontext Vorschläge für die Kern-Abschnitte.
Harte Regel: KEINE erfundenen Fundstellen (SR-/NG-Nummern, Datierungen, Artikel) –
die verifizierte Fundstelle liefert später Phase B (Fedlex). Ohne LLM bleibt der
Entwurf leer (nur das PIA-Seeding greift) – nie wird geraten.
"""
import json
import re


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
    "Du bist ein juristisch versierter HERMES-2022-Berater und entwirfst die "
    "Rechtsgrundlagenanalyse eines Schweizer Behördenprojekts. "
    "STRIKTE REGELN:\n"
    "- Erfinde NIEMALS Fundstellen: keine SR-/NG-/Ordnungsnummern, keine Datierungen "
    "  ('vom 18. Juni 1993'), keine Artikelnummern. Nenne Gesetze nur mit ihrem Namen "
    "  und einer allgemeinen Beschreibung. Was du nicht sicher weisst, lässt du weg.\n"
    "- Datenschutz und Informationssicherheit gehören NICHT hierher (das ist die "
    "  Schutzbedarfsanalyse) – klammere sie aus.\n"
    "- Sachlicher Behördenstil, Hochdeutsch. Antworte NUR mit validem JSON."
)


def analysiere(wissen, llm):
    """Gibt einen Dict mit Vorschlägen zurück (leer ohne LLM):
    {bestehende:[{rechtsgrundlage,beschreibung}], bevorstehende:[{...,auswirkung}],
     luecken:[{luecke,beschreibung}], vorschlaege:[{luecke,vorschlag}],
     compliance:[{compliance,beschreibung}], konsequenzen:str, empfehlung:str}"""
    if llm is None:
        return {}
    ebene = wissen.ebene or "nicht angegeben"
    kanton = wissen.kanton or "nicht angegeben"
    gesetze = wissen.genannte_rechtsgrundlagen()
    ziele = "; ".join(
        str(z.get("beschreibung", "")).strip()
        for z in wissen.ziele() if isinstance(z, dict) and z.get("beschreibung")
    )
    user = (
        f"Staatsebene: {ebene}. Kanton: {kanton}.\n"
        f"Ausgangslage: {wissen.ausgangslage_text()[:1500]}\n"
        f"Ziele: {ziele[:800]}\n"
        f"Im PIA genannte Rechtsgrundlagen: {', '.join(gesetze) or 'keine'}\n\n"
        "Erstelle einen Entwurf und gib JSON mit genau diesen Schlüsseln zurück:\n"
        '{"bestehende":[{"rechtsgrundlage":"","beschreibung":""}],'
        '"bevorstehende":[{"rechtsgrundlage":"","beschreibung":"","auswirkung":"positiv|neutral|negativ"}],'
        '"luecken":[{"luecke":"","beschreibung":""}],'
        '"vorschlaege":[{"luecke":"","vorschlag":""}],'
        '"compliance":[{"compliance":"","beschreibung":""}],'
        '"konsequenzen":"","empfehlung":""}\n'
        "Bei 'bestehende' die genannten Gesetze aufnehmen und je eine allgemeine "
        "Beschreibung (ohne Fundstelle/Datum) ergänzen. Leere Listen sind erlaubt, "
        "wenn nichts Belastbares vorliegt."
    )
    try:
        raw = llm.complete(SYSTEM, [{"role": "user", "content": user}], max_tokens=2000)
    except Exception:  # noqa: BLE001 – LLM-Ausfall: lieber leerer Entwurf als Fehler
        return {}
    return _parse_json(raw) or {}
