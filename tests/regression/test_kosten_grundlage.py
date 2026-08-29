"""Beweist: Kosten ohne Personentage kommen nicht mehr durch.

Der Anlass ist ein echter Projektinitialisierungsauftrag. Kapitel 3.3 wies
74'000 CHF interne Personalkosten für Projektleiter, Auftraggeber, ISDS-
Verantwortliche/r und Anwendervertretung aus. Kapitel 3.1 enthielt EINE Zeile —
«Externe Fachexpertise», ohne Namen, ohne Personentage. Kapitel 5 hatte nur
eine Überschrift und keine Tabelle.

Jedes Kapitel für sich sah plausibel aus. Erst zusammen ergaben sie Kosten ohne
Grundlage. Die vorhandenen Regeln schwiegen aus zwei Gründen, die beide
strukturell sind und nicht zufällig:

  * D-002 steigt aus, sobald Kap. 3.1 keine Personentage trägt (`not aufwand`) —
    ihr fehlt dann der Massstab. Ausgerechnet die gefährlichste Lage.
  * D-002 meldet ausserdem nur Unterdeckung, nie den umgekehrten Fall.
  * D-001 vergleicht 3.1 mit Kap. 5 — aber nur, wo BEIDE etwas sagen. Ein ganz
    leeres Kapitel 5 vergleicht sie mit nichts.
"""
from app.domains.qualitaet.pruefung import pruefe

TARIFE = {"intern": 1200, "extern": 1800}


def _regeln(ergebnis, *gesucht):
    return sorted({b.regel for b in ergebnis.befunde if b.regel in gesucht})


# ---- Der gemessene Fall --------------------------------------------------- #

DER_ECHTE_FALL = {
    "personalaufwand": {"extracted": [
        {"rolle": "Externe Fachexpertise", "name": "", "aufwand": ""}]},
    "kosten": {"extracted": [
        {"phase": "Interne Personalkosten – Projektleiter (20 PT)", "betrag": "24000"},
        {"phase": "Interne Personalkosten – Auftraggeber (5 PT)", "betrag": "6000"},
        {"phase": "Interne Personalkosten – ISDS-Verantwortliche/r", "betrag": "8000"},
        {"phase": "Interne Personalkosten – Anwendervertretung", "betrag": "6000"},
        {"phase": "Total Initialisierung", "betrag": "44000"}]},
    "projektorganisation": {"extracted": []},
}


def test_kosten_ohne_personentage_blockieren_die_ausgabe():
    ergebnis = pruefe(DER_ECHTE_FALL, tarife=TARIFE)
    assert "D-007" in _regeln(ergebnis, "D-007")
    assert not ergebnis.ausgabe_moeglich, "ein Muss-Befund muss die Ausgabe sperren"


def test_jede_grundlose_zeile_wird_einzeln_benannt():
    """Eine Sammelmeldung sagt nicht, WELCHE Zeile zu beheben ist."""
    ergebnis = pruefe(DER_ECHTE_FALL, tarife=TARIFE)
    treffer = [b for b in ergebnis.befunde if b.regel == "D-007"]
    assert len(treffer) == 4
    assert any("Anwendervertretung" in b.meldung for b in treffer)


# ---- Die Gegenprobe: stimmige Angaben bleiben still ----------------------- #

STIMMIG = {
    "personalaufwand": {"extracted": [
        {"rolle": "Projektleiter", "name": "A. Muster", "aufwand": "20"},
        {"rolle": "Auftraggeber", "name": "B. Beispiel", "aufwand": "5"}]},
    "kosten": {"extracted": [
        {"phase": "Interne Personalkosten – Projektleiter", "betrag": "24000"},
        {"phase": "Interne Personalkosten – Auftraggeber", "betrag": "6000"},
        {"phase": "Total Initialisierung", "betrag": "30000"}]},
    "projektorganisation": {"extracted": [
        {"rolle_person": "Projektleiter / A. Muster", "monat_1": "20"},
        {"rolle_person": "Auftraggeber / B. Beispiel", "monat_1": "5"}]},
}


def test_stimmige_angaben_werden_nicht_gemeldet():
    assert _regeln(pruefe(STIMMIG, tarife=TARIFE), "D-007", "D-063") == []


def test_summen_und_sachmittel_sind_keine_personalzeilen():
    """Sonst meldete jede Zwischensumme und jeder Lizenzposten einen Befund."""
    fall = dict(STIMMIG, kosten={"extracted": [
        {"phase": "Interne Personalkosten – Projektleiter", "betrag": "24000"},
        {"phase": "Zwischentotal Personalkosten", "betrag": "24000"},
        {"phase": "Lizenzen und Sachmittel", "betrag": "5000"},
        {"phase": "Total Initialisierung", "betrag": "29000"}]})
    assert _regeln(pruefe(fall, tarife=TARIFE), "D-007") == []


# ---- Kapitel 5 ------------------------------------------------------------ #

def test_personentage_ohne_monatsverteilung_werden_gemeldet():
    """D-001 schweigt hier: sie vergleicht 3.1 mit Kap. 5, und ein leeres
    Kapitel 5 vergleicht sie mit nichts."""
    fall = dict(STIMMIG, projektorganisation={"extracted": []})
    ergebnis = pruefe(fall, tarife=TARIFE)
    assert "D-063" in _regeln(ergebnis, "D-063")
    assert not ergebnis.ausgabe_moeglich


def test_unbearbeitetes_kapitel_5_ist_etwas_anderes_als_ein_leeres():
    """Fehlt der Abschnitt ganz, ist das Sache von D-040 – nicht von D-063.
    Sonst meldete jeder halbfertige Auftrag denselben Befund doppelt."""
    fall = {k: v for k, v in STIMMIG.items() if k != "projektorganisation"}
    assert _regeln(pruefe(fall, tarife=TARIFE), "D-063") == []
