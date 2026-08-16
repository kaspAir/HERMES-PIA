"""Der EINE nächste Schritt – was die Startseite vorschlägt.

Aus der Benutzerführungs-Richtlinie, Abschnitt 03 und 08:

  *«Genau eine Aufgabe wird hervorgehoben. Mehrere gleichrangige Aktionen
  erzeugen dieselbe Lähmung wie keine.»*

  *«Aufwand vorher nennen. ‹Etappe 4 von 6 · ca. 15 Minuten› entscheidet
  darüber, ob jemand jetzt anfängt oder wieder zumacht.»*

  *«Stille als Information. ‹Alle aktuell ohne offene Aufgabe für dich› ist
  eine echte Aussage – besser als eine Liste, die man selbst prüfen muss.»*

Dieses Modul rechnet den Vorschlag aus dem ZUSTAND, nicht aus einer Meinung.
Es ruft kein Modell und trifft keine fachliche Entscheidung: Es sagt, was
offen ist, in der Reihenfolge, in der es die Methode verlangt. Wo nichts offen
ist, sagt es das – Stille ist hier eine Aussage und kein Fehlerfall.

**Warum die Schätzung grob sein darf, aber nicht fehlen.** Eine Zeitangabe,
die zehn Minuten danebenliegt, ändert die Entscheidung «jetzt oder später»
kaum; eine fehlende Angabe verhindert sie ganz. Die Werte hier sind gemessene
Grössenordnungen, keine Versprechen – und sie stehen an EINER Stelle, damit
sie nicht auseinanderlaufen.
"""

# Grobe Dauer je Aufgabenart, in Minuten. Bewusst rund: die Zahl soll die
# Entscheidung «jetzt anfangen?» stützen, nicht eine Zusage sein.
DAUER = {
    "interview": 15,
    "pruefung": 5,
    "befunde": 20,
    "rechtsgrundlagen": 10,
    "freigabe": 5,
}


def _minuten(art, faktor=1):
    return max(5, int(DAUER.get(art, 10) * max(1, faktor)))


def schritte_fuer(zustand):
    """Alle offenen Aufgaben eines Projekts – wichtigste zuerst.

    ``zustand`` ist ein schlichtes Wörterbuch, damit dieses Modul weder
    Datenbank noch Sitzung kennt:

        {"projekt_id", "name",
         "offene_abschnitte", "abschnitte_total",   # Interview
         "pruefung_vorhanden", "muss_befunde",      # fachliche Prüfung
         "rga_vorhanden", "rga_laeuft"}             # Rechtsgrundlagenanalyse
    """
    z = zustand or {}
    name = z.get("name") or "Projekt"
    raus = []

    offen = int(z.get("offene_abschnitte") or 0)
    total = int(z.get("abschnitte_total") or 0)
    if offen:
        erledigt = max(0, total - offen)
        raus.append({
            "art": "interview",
            "projekt_id": z.get("projekt_id"),
            "session_id": z.get("session_id"),
            "titel": f"Angaben zu «{name}» vervollständigen",
            "wo": (f"Etappe {erledigt + 1} von {total}" if total else "Interview"),
            "minuten": _minuten("interview", offen),
            "warum": f"{offen} von {total} Abschnitten sind noch offen." if total
                     else f"{offen} Abschnitte sind noch offen.",
        })

    muss = int(z.get("muss_befunde") or 0)
    if muss:
        raus.append({
            "art": "befunde",
            "projekt_id": z.get("projekt_id"),
            "session_id": z.get("session_id"),
            "titel": f"Zwingende Befunde zu «{name}» klären",
            "wo": "Fachliche Prüfung",
            "minuten": _minuten("befunde", muss),
            "warum": (f"{muss} Punkt muss vor der Freigabe geklärt sein."
                      if muss == 1 else
                      f"{muss} Punkte müssen vor der Freigabe geklärt sein."),
        })
    # «Erfasst» heisst: die Abschnitte sind BEKANNT und keiner ist offen. Ohne
    # bekannte Abschnittszahl wissen wir nichts – und schlagen dann auch nichts
    # vor. Ein Vorschlag aus Unkenntnis ist schlimmer als keiner: er behauptet,
    # die Erfassung sei fertig.
    erfasst = total > 0 and not offen

    if erfasst and not muss and not z.get("pruefung_vorhanden"):
        raus.append({
            "art": "pruefung",
            "projekt_id": z.get("projekt_id"),
            "session_id": z.get("session_id"),
            "titel": f"«{name}» fachlich prüfen lassen",
            "wo": "Prüfung aus Auftraggeber-Sicht",
            "minuten": _minuten("pruefung"),
            "warum": "Die Angaben sind vollständig – die Prüfung ist der nächste Schritt.",
        })

    if erfasst and not z.get("rga_vorhanden") and not z.get("rga_laeuft"):
        raus.append({
            "art": "rechtsgrundlagen",
            "projekt_id": z.get("projekt_id"),
            "session_id": z.get("session_id"),
            "titel": f"Rechtsgrundlagen für «{name}» klären",
            "wo": "Rechtsgrundlagenanalyse",
            "minuten": _minuten("rechtsgrundlagen"),
            "warum": "Für dieses Projekt liegt noch keine Rechtsgrundlagenanalyse vor.",
        })
    return raus


# Rangfolge der Aufgabenarten. Was die Freigabe blockiert, kommt zuerst.
_RANG = {"befunde": 0, "interview": 1, "pruefung": 2, "rechtsgrundlagen": 3}


def naechster_schritt(zustaende):
    """(Vorschlag, weitere, ruhige) – genau EIN Vorschlag.

    ``weitere`` sind die übrigen offenen Aufgaben (für die zweite Reihe),
    ``ruhige`` die Zahl der Projekte ganz ohne offene Aufgabe. Letztere wird
    mitgeführt, damit die Oberfläche «alle aktuell ohne offene Aufgabe für
    dich» sagen kann, statt zu schweigen.
    """
    alle, ruhig = [], 0
    for z in zustaende or []:
        offene = schritte_fuer(z)
        if offene:
            alle.extend(offene)
        else:
            ruhig += 1
    alle.sort(key=lambda s: (_RANG.get(s["art"], 9), s["minuten"]))
    return (alle[0] if alle else None), alle[1:], ruhig


def begruessung(stunde):
    """«Guten Morgen» ist keine Höflichkeit, sondern eine Ortsangabe in der Zeit."""
    if stunde < 11:
        return "Guten Morgen"
    if stunde < 18:
        return "Guten Tag"
    return "Guten Abend"
