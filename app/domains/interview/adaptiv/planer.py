"""Gesprächsplaner: wählt die nächste Gesprächsaktion.

Nicht die nächste Kapitelnummer bestimmt den Fortgang, sondern der
Wissensstand und der noch fehlende Beitrag zum PIA (Auftrag Abschnitt 5).

Die Wahl ist DETERMINISTISCH und nachvollziehbar: jede Aktion trägt einen
knappen Entscheidungshinweis (offener Punkt, Gewicht, Konflikt, RAG-Thema).
Das Sprachmodell formuliert anschliessend nur noch die Frage; fällt es aus,
gibt es eine Vorlagenfrage. Ein Denkprotokoll des Modells wird nicht gebraucht
und nicht gespeichert.

Aktionsarten – echtes, unterschiedliches Verhalten, nicht nur andere Wörter:
  erkunden        offene Frage zu einem noch unbesprochenen Bereich
  konkretisieren  Bekanntes präzisieren (fehlende Felder, unvollständiges Datum)
  widerspruch     zwei Angaben widersprechen sich – welche gilt?
  rueckspiegeln   eine Interpretation oder Idee/Entscheid bestätigen lassen
  klaeren         Bezug einer Korrektur ist unklar – worauf bezieht sie sich?
  vorschlag       der Benutzer weiss es nicht – Vorschlag/Untersuchungsauftrag anbieten
  hinweis         etwas fehlt, das nicht im Gespräch zu klären ist (z.B. Kostensatz)
  abschluss       keine Blocker mehr – Abschlussprüfung anbieten
"""
from app.domains.interview.adaptiv.vollstaendigkeit import profil

# Priorität (kleiner = früher). Wesentliche Konflikte und Lücken für die
# Beauftragung zuerst, dann weitere Klärungen, zuletzt Vertiefungen
# (Auftrag Abschnitt 9).
# Kriterien, deren Vorschlag das System berechnet (vorschlaege.FUER_KRITERIUM).
BERECHENBAR = ("K-PO-1", "K-TE-1")

PRIO = {
    "start": -1,
    "klaeren": 0,
    "widerspruch": 0,
    "rueckspiegeln_entscheid": 1,
    "wesentlich": 2,
    "rueckspiegeln": 3,
    "vorschlag": 3,
    "rag": 4,
    "erforderlich": 5,
    "hinweis": 6,
    "vertiefung": 7,
}


def _letzte_systemaktionen(nachrichten, n=6):
    return [m for m in nachrichten if m["rolle"] == "system" and m.get("aktion")][-n:]


def _wiederholungen(nachrichten, ziel_id):
    """Wie oft wurde zuletzt genau dieser Punkt gefragt, OHNE dass sich an ihm
    etwas geändert hat? (Endlosschleifen-Schutz, AT07)"""
    zaehler = 0
    for m in reversed(_letzte_systemaktionen(nachrichten, 12)):
        bezug = m.get("bezug") or {}
        if bezug.get("ziel") == ziel_id and bezug.get("schon_beantwortet"):
            return 99           # vom Benutzer als schon beantwortet markiert
        if bezug.get("ziel") == ziel_id and not bezug.get("bearbeitet"):
            zaehler += 1
        elif bezug.get("ziel") == ziel_id:
            break
    return zaehler


def kandidaten(aussagen, konflikte, themen, kriterien, nachrichten, bezug_unklar=""):
    """Alle möglichen nächsten Aktionen mit Priorität und Begründung."""
    k = []
    benutzer = [a for a in aussagen if a["herkunft"] == "benutzer" and a["status"] == "aktiv"]

    if not benutzer:
        k.append({"aktion": "erkunden", "prio": PRIO["start"], "ziel": "start",
                  "abschnitt": "ausgangslage",
                  "begruendung": "Einstieg: noch keine Angaben zum Vorhaben"})

    if bezug_unklar:
        k.append({"aktion": "klaeren", "prio": PRIO["klaeren"], "ziel": "bezug",
                  "begruendung": "Bezug der letzten Korrektur ist unklar",
                  "kontext": {"rueckfrage": bezug_unklar}})

    for kf in konflikte:
        if kf["status"] == "offen":
            k.append({"aktion": "widerspruch", "prio": PRIO["widerspruch"],
                      "ziel": f"K-{kf['id']}",
                      "begruendung": f"Widerspruch: {kf['beschreibung'][:120]}",
                      "kontext": {"konflikt": kf}})

    for a in aussagen:
        if a["status"] != "aktiv":
            continue
        if a.get("entscheid") == "unklar":
            k.append({"aktion": "rueckspiegeln", "prio": PRIO["rueckspiegeln_entscheid"],
                      "ziel": a["schluessel"], "unterart": "entscheid",
                      "begruendung": "Lösungsaussage: Entscheid oder Idee?",
                      "kontext": {"aussage": a}})
        elif a["art"] in ("interpretation",) and not a["bestaetigt"]:
            k.append({"aktion": "rueckspiegeln", "prio": PRIO["rueckspiegeln"],
                      "ziel": a["schluessel"],
                      "begruendung": "Interpretation noch nicht bestätigt",
                      "kontext": {"aussage": a}})

    # Systemvorschläge: EINE Rückfrage je Abschnitt, nicht je Zeile – eine
    # Monatsverteilung über fünf Rollen ist ein Vorschlag, keine fünf Fragen.
    gesehen = set()
    for a in aussagen:
        if a["status"] != "aktiv" or a["art"] != "systemvorschlag" or a["bestaetigt"]:
            continue
        ab = next((z.get("abschnitt") for z in a["ziele"]), None)
        if ab in gesehen:
            continue
        gesehen.add(ab)
        weitere = [b for b in aussagen if b is not a and b["status"] == "aktiv"
                   and b["art"] == "systemvorschlag" and not b["bestaetigt"]
                   and any(z.get("abschnitt") == ab for z in b["ziele"])]
        k.append({"aktion": "rueckspiegeln", "prio": PRIO["rueckspiegeln"],
                  "ziel": a["schluessel"], "unterart": "vorschlag", "abschnitt": ab,
                  "begruendung": "Systemvorschlag noch nicht übernommen",
                  "kontext": {"aussage": a, "weitere": weitere}})

    verworfene_themen = {t["thema"].lower() for t in themen if t["status"] == "verworfen"}
    nutzbare = [t for t in themen
                if t["status"] == "kandidat" and t["uebertragbarkeit"] in ("nutzbar", "eingeschraenkt")
                and t["thema"].lower() not in verworfene_themen]
    verwendet = set()

    def thema_fuer(abschnitt):
        """Ein RAG-Thema, das genau diese Lücke berührt. Es bestimmt dann, WIE
        nach der Lücke gefragt wird – das Thema steht nicht neben der Lücke,
        sondern in ihr (Auftrag 6.3: priorisiere, was eine Lücke schliesst)."""
        for t in nutzbare:
            if abschnitt in (t.get("pia_ziele") or []) and t["id"] not in verwendet:
                return t
        return None

    for reihe, e in enumerate(kriterien):
        if e["zustand"] in ("erfuellt", "nicht_anwendbar", "konflikt", "zurueckgestellt"):
            continue
        if e["zustand"] == "unbekannt":
            # Der Benutzer weiss es nicht: Vorschlag oder Untersuchungsauftrag
            # anbieten – nicht dieselbe Frage erneut stellen.
            k.append({"aktion": "vorschlag", "prio": PRIO["vorschlag"], "ziel": e["id"],
                      "abschnitt": e["abschnitt"],
                      "begruendung": f"«{e['beschreibung']}» ist noch nicht bekannt",
                      "kontext": {"kriterium": e}})
            continue
        aktion = e["aktion"]
        kand = {"aktion": aktion, "prio": PRIO[e["gewicht"]] if aktion != "hinweis" else PRIO["hinweis"],
                "ziel": e["id"], "abschnitt": e["abschnitt"], "reihe": reihe,
                "begruendung": f"{e['gewicht'].capitalize()}: {e['beschreibung']}"
                               + (f" ({e['details'][0]})" if e["details"] else ""),
                "kontext": {"kriterium": e}}
        t = thema_fuer(e["abschnitt"]) if aktion in ("erkunden", "konkretisieren") else None
        if t is not None:
            verwendet.add(t["id"])
            kand["unterart"] = "rag"
            kand["kontext"]["thema"] = t
            kand["begruendung"] += (f"; Anhaltspunkt aus {t['n_projekte']} "
                                    f"Vergleichsprojekt(en): {t['thema']}")
        k.append(kand)

    # Übrige RAG-Themen ohne eigenes offenes Kriterium: nur als Vertiefung zu
    # Zielen oder Risiken der Initialisierung – nie vor den Lücken.
    for t in nutzbare:
        if t["id"] in verwendet:
            continue
        ziele = set(t.get("pia_ziele") or [])
        if not ziele & {"ziele", "risiken"}:
            continue
        k.append({"aktion": "konkretisieren", "prio": PRIO["vertiefung"], "ziel": f"T-{t['id']}",
                  "abschnitt": next(iter(ziele), ""), "unterart": "rag",
                  "begruendung": f"Thema aus {t['n_projekte']} Vergleichsprojekt(en): {t['thema']}",
                  "kontext": {"thema": t}})
    return k


def naechste_aktion(aussagen, konflikte, themen, kriterien, nachrichten, bezug_unklar=""):
    """Die nächste Gesprächsaktion – oder die Abschlussprüfung."""
    grenze = profil().get("wiederholungen_bis_zurueckstellen", 2)
    alle = kandidaten(aussagen, konflikte, themen, kriterien, nachrichten, bezug_unklar)
    zurueckgestellt = []
    # Bei gleicher Priorität zuerst die Lücke, zu der der Korpus einen
    # Anhaltspunkt liefert, dann die Reihenfolge des Profils. Früher entschied
    # hier die alphabetische Kennung («K-PA» vor «K-ZI») – Zufall, keine Begründung.
    def ordnung(x):
        return (x["prio"], 0 if x.get("unterart") == "rag" else 1, x.get("reihe", 99), x["ziel"])

    for kand in sorted(alle, key=ordnung):
        if kand["ziel"] not in ("start", "bezug") and \
                _wiederholungen(nachrichten, kand["ziel"]) >= grenze:
            zurueckgestellt.append(kand["ziel"])
            continue
        kand["zurueckgestellt"] = zurueckgestellt
        return kand
    return {"aktion": "abschluss", "prio": 99, "ziel": "abschluss",
            "begruendung": "Keine weiteren offenen Punkte, die im Gespräch zu klären sind",
            "zurueckgestellt": zurueckgestellt,
            "kontext": {"offen": [e for e in kriterien
                                  if e["zustand"] not in ("erfuellt", "nicht_anwendbar")]}}


# ---- Vorlagenfragen (Rückfall ohne Modell) ---------------------------------- #

def vorlagenfrage(aktion):
    """Eine vernünftige Frage ohne Sprachmodell – je Aktionsart."""
    art = aktion["aktion"]
    ktx = aktion.get("kontext") or {}
    if aktion.get("ziel") == "start":
        return ("Worum geht es bei diesem Vorhaben? Erzähl mir vom Anlass, vom Problem, "
                "das gelöst werden soll, und was Du schon weisst – so ausführlich, wie Du magst.")
    if art == "klaeren":
        return ktx.get("rueckfrage") or "Auf welche Angabe bezieht sich Deine Korrektur?"
    if art == "widerspruch":
        return (f"Da passt etwas nicht zusammen: {ktx['konflikt']['beschreibung']} "
                f"Welche Angabe gilt?")
    if art == "rueckspiegeln":
        a = ktx.get("aussage") or {}
        if aktion.get("unterart") == "vorschlag":
            alle = [a] + list(ktx.get("weitere") or [])
            liste = " ".join(f"«{x.get('inhalt', '')}»" for x in alle)
            return (f"Mein Vorschlag: {liste}. Grundlage: {a.get('beleg') or 'siehe Anzeige'} "
                    f"Übernehmen, anpassen oder verwerfen?")
        if aktion.get("unterart") == "entscheid":
            return (f"Du hast gesagt: «{a.get('inhalt', '')}». Ist das bereits entschieden, "
                    f"oder eine Lösungsidee, die die Initialisierung noch prüfen soll?")
        return f"Habe ich richtig verstanden: {a.get('inhalt', '')}?"
    if art == "vorschlag":
        kr = ktx.get("kriterium") or {}
        if kr.get("id") in BERECHENBAR:
            # Diesen Vorschlag berechnet das System, sobald die Grundlage da ist.
            # Ihn als Untersuchungsauftrag anzubieten, lud ein echtes Modell ein,
            # ein Ziel zu erfinden (dev, 15.10.2026).
            return (f"Für «{kr.get('beschreibung', '')}» rechne ich Dir einen Vorschlag aus, "
                    f"sobald die Grundlage vollständig ist: Start und Ende der Initialisierung "
                    f"und die Personentage je Rolle. Was davon fehlt noch?")
        return (f"Zu «{kr.get('beschreibung', '')}» ist noch nichts bekannt. Soll ich einen "
                f"Vorschlag machen, oder nehmen wir die Klärung als Untersuchungsauftrag in die "
                f"Initialisierung auf?")
    if aktion.get("unterart") == "rag":
        t = ktx.get("thema") or {}
        return t.get("frage_ansatz") or f"Ist «{t.get('thema', '')}» für Dein Vorhaben ein Thema?"
    if art == "abschluss":
        return ("Ich habe keine offenen Fragen mehr, die wir im Gespräch klären müssten. "
                "Möchtest Du den Auftrag jetzt prüfen und fertigstellen?")
    kr = ktx.get("kriterium") or {}
    return kr.get("vorlagenfrage") or "Was ist dazu noch wichtig?"
