"""Die Prüfpunkte der Checkliste Projektinitialisierungsfreigabe.

Kapitel 1.1 der HERMES-Vorlage nennt sechs generelle Prüfpunkte. Zu fünf davon
weiss HERMES PIA etwas Belegbares – nicht weil es die Sachlage beurteilt,
sondern weil der Projektinitialisierungsauftrag die Angaben enthält, auf die
sich der Prüfpunkt bezieht.

**Was dieses Modul tut und was nicht.** Es liest Struktur, nicht Bedeutung: Ist
Kapitel 2.1 befüllt? Trägt eine Rolle in Kapitel 3.1 einen Namen? Steht in
Kapitel 5 eine Bestätigung? Daraus wird eine Bewertung und eine Erläuterung,
die sagt, WORAUF sie beruht. Kein Sprachmodell, kein Sachurteil, keine
Fachgebietskenntnis – dieselbe Rechnung für jedes Projekt.

**Die ehrliche Grenze.** Manche Kriterien fragen nach Vorgängen ausserhalb des
Systems: ob unterschrieben wurde, ob jemand tatsächlich informiert ist. Diese
Prüfpunkte bekommen kein Häkchen, sondern die Bewertung «zu bestätigen» und
eine Erläuterung, was HERMES PIA sehen kann und was nicht. Eine Checkliste,
die sich selbst grün färbt, prüft nichts.
"""

# Kontrolliertes Vokabular der Spalte «Bewertung». Vier Werte, mehr nicht –
# damit die Auswertung nachrechenbar bleibt und nicht an Formulierungen hängt.
ERFUELLT = "erfüllt"
TEILWEISE = "teilweise erfüllt"
NICHT_ERFUELLT = "nicht erfüllt"
ZU_BESTAETIGEN = "zu bestätigen"

# Nur diese beiden halten die Freigabe auf. «Teilweise» und «zu bestätigen»
# verlangen eine Entscheidung des Auftraggebers – sie sind kein Nein.
BLOCKIEREND = (NICHT_ERFUELLT,)


def _zeilen(wissen, abschnitt):
    """Die Tabellenzeilen eines Abschnitts – oder eine leere Liste."""
    wert = ((wissen or {}).get(abschnitt) or {}).get("extracted")
    return [z for z in wert if isinstance(z, dict)] if isinstance(wert, list) else []


def _text(wissen, abschnitt):
    wert = ((wissen or {}).get(abschnitt) or {}).get("extracted")
    if isinstance(wert, dict):
        return str(wert.get("text", "")).strip()
    return ""


def _feld(zeile, *namen):
    for n in namen:
        w = str(zeile.get(n, "") or "").strip()
        if w:
            return w
    return ""


def _anzahl(n, einzahl, mehrzahl):
    return f"{n} {einzahl}" if n == 1 else f"{n} {mehrzahl}"


# ---- Die sechs generellen Prüfpunkte -------------------------------------- #

def _g01(wissen, dokumente):
    """Unterschrift – ausserhalb des Systems, immer."""
    if dokumente.get("freigegeben"):
        return ZU_BESTAETIGEN, (
            "Eine freigegebene Fassung des Projektinitialisierungsauftrags "
            "wurde hochgeladen. Ob sie unterschrieben vorliegt, kann HERMES "
            "PIA nicht feststellen – das bestätigt der Auftraggeber.")
    if dokumente.get("freigabe"):
        return ZU_BESTAETIGEN, (
            "Eine freigabebereite Fassung liegt vor, aber keine freigegebene. "
            "Ob unterschrieben wurde, kann HERMES PIA nicht feststellen.")
    return ZU_BESTAETIGEN, (
        "Es wurde keine Fassung des Projektinitialisierungsauftrags "
        "hochgeladen. Ob eine unterschriebene Fassung vorliegt, kann HERMES "
        "PIA nicht feststellen.")


def _g02(wissen, dokumente):
    """Ressourcen definiert, abgestimmt und freigegeben."""
    personal = _zeilen(wissen, "personalaufwand")
    mit_aufwand = [z for z in personal if _feld(z, "aufwand")]
    kosten = _zeilen(wissen, "kosten")
    org = _zeilen(wissen, "projektorganisation")
    bestaetigt = [z for z in org
                  if _feld(z, "bestaetigung").lower() not in ("", "ausstehend", "offen")]

    teile = []
    if mit_aufwand:
        teile.append(f"Kapitel 3.1 weist für {_anzahl(len(mit_aufwand), 'Rolle', 'Rollen')} "
                     "einen Aufwand aus.")
    if kosten:
        teile.append(f"Kapitel 3.3 enthält {_anzahl(len(kosten), 'Kostenzeile', 'Kostenzeilen')}.")
    if bestaetigt:
        teile.append(f"In Kapitel 5 liegt für {_anzahl(len(bestaetigt), 'Rolle', 'Rollen')} "
                     "eine Bestätigung der vorgesetzten Stelle vor.")
    else:
        teile.append("In Kapitel 5 ist keine Bestätigung der vorgesetzten Stelle "
                     "eingetragen – die Abstimmung ist damit nicht belegt.")

    if mit_aufwand and kosten and bestaetigt:
        return ERFUELLT, " ".join(teile)
    if mit_aufwand or kosten:
        return TEILWEISE, " ".join(teile)
    return NICHT_ERFUELLT, ("Weder Personalaufwand (Kapitel 3.1) noch Kosten "
                            "(Kapitel 3.3) sind ausgewiesen.")


def _g03(wissen, dokumente):
    """PIA mit Zielen, Vorgaben und Rahmenbedingungen erstellt."""
    hat = {
        "Ziele (Kapitel 2.1)": len(_zeilen(wissen, "ziele")),
        "Rahmenbedingungen (Kapitel 2.2)": len(_zeilen(wissen, "rahmenbedingungen")),
        "Vorgaben, Methoden und Werkzeuge (Kapitel 0.5)":
            len(_zeilen(wissen, "vorgaben_methoden")),
    }
    da = [f"{name}: {n}" for name, n in hat.items() if n]
    fehlt = [name for name, n in hat.items() if not n]
    if not fehlt:
        return ERFUELLT, "Alle drei Bestandteile sind befüllt – " + "; ".join(da) + "."
    if da:
        return TEILWEISE, ("Befüllt: " + "; ".join(da) + ". Ohne Eintrag: "
                           + ", ".join(fehlt) + ".")
    return NICHT_ERFUELLT, "Keiner der drei Bestandteile ist befüllt."


def _g04(wissen, dokumente):
    """Projektleiter und Team bestimmt, Erwartungen geklärt."""
    personal = _zeilen(wissen, "personalaufwand")
    pl = [z for z in personal
          if "projektleit" in _feld(z, "rolle").lower() and _feld(z, "name")]
    benannt = [z for z in personal if _feld(z, "name")]
    rollen = [z for z in personal if _feld(z, "rolle")]

    if pl and len(benannt) > 1:
        return TEILWEISE, (
            f"Die Projektleitung ist namentlich benannt, und {_anzahl(len(benannt), 'Rolle ist', 'Rollen sind')} "
            "mit Namen hinterlegt. Ob die gegenseitigen Erwartungen geklärt "
            "sind, ist im Projektinitialisierungsauftrag nicht festgehalten – "
            "das bestätigt der Auftraggeber.")
    if rollen:
        return TEILWEISE, (
            f"Kapitel 3.1 führt {_anzahl(len(rollen), 'Rolle', 'Rollen')}, davon "
            f"{_anzahl(len(benannt), 'mit Namen', 'mit Namen')}. "
            "Solange die Projektleitung nicht namentlich benannt ist, gilt der "
            "Prüfpunkt als offen.")
    return NICHT_ERFUELLT, "Kapitel 3.1 führt keine Rollen."


def _g05(wissen, dokumente):
    """Ansprechpersonen informiert."""
    komm = _zeilen(wissen, "kommunikation")
    if komm:
        empfaenger = {_feld(z, "empfaenger") for z in komm if _feld(z, "empfaenger")}
        return ZU_BESTAETIGEN, (
            f"Das Kommunikationskonzept (Kapitel 6) nennt "
            f"{_anzahl(len(empfaenger), 'Empfänger', 'Empfänger')} und die "
            "vorgesehenen Zeitpunkte. Ob die Information bereits erfolgt ist, "
            "geht aus dem Projektinitialisierungsauftrag nicht hervor – er "
            "plant sie, er belegt sie nicht.")
    return NICHT_ERFUELLT, "Kapitel 6 enthält keine Kommunikationsplanung."


def _g06(wissen, dokumente):
    """Dokumentenablage und Governance-Vorgaben geklärt."""
    vorgaben = _zeilen(wissen, "vorgaben_methoden")
    if len(vorgaben) > 1:
        titel = [_feld(z, "titel") for z in vorgaben if _feld(z, "titel")]
        return ERFUELLT, ("Kapitel 0.5 führt "
                          + _anzahl(len(vorgaben), "Vorgabe", "Vorgaben")
                          + (": " + ", ".join(titel) + "." if titel else "."))
    if vorgaben:
        return TEILWEISE, ("Kapitel 0.5 enthält nur die Projektmanagementmethode. "
                           "Dokumentenablage und weitere Governance-Vorgaben sind "
                           "nicht festgehalten.")
    return NICHT_ERFUELLT, "Kapitel 0.5 ist leer."


# Reihenfolge und Wortlaut folgen der HERMES-Vorlage. Der Prüfpunkt-Text steht
# nur bei G-01 – so ist es in der Vorlage; die übrigen Zeilen tragen ihn leer.
GENERELLE = (
    ("G-01", "Projektinitialisierungsauftrag",
     "Projektinitialisierungsauftrag liegt vollständig vom Auftraggeber "
     "unterschrieben vor?", _g01),
    ("G-02", "",
     "Ressourcen (personell und finanziell) für die Initialisierung definiert, "
     "abgestimmt und freigegeben?", _g02),
    ("G-03", "",
     "Projektinitialisierungsauftrag mit Zielen der Initialisierung, Vorgaben "
     "und Rahmenbedingungen erstellt?", _g03),
    ("G-04", "",
     "Projektleiter und Team für die Phase Initialisierung bestimmt und "
     "Erwartungen geklärt?", _g04),
    ("G-05", "",
     "Ansprechpersonen innerhalb und ausserhalb der Stammorganisation "
     "informiert?", _g05),
    ("G-06", "",
     "Dokumentenablage und Governance-Vorgaben geklärt und bekannt?", _g06),
)


def generelle_pruefpunkte(wissen, dokumente=None):
    """Kapitel 1.1 – bewertet aus dem Projektinitialisierungsauftrag."""
    dokumente = dokumente or {}
    raus = []
    for nr, pruefpunkt, kriterium, bewerte in GENERELLE:
        bewertung, erlaeuterung = bewerte(wissen or {}, dokumente)
        raus.append({
            "nr": nr,
            "pruefpunkt": pruefpunkt,
            "kriterium": kriterium,
            "bewertung": bewertung,
            "erlaeuterung": erlaeuterung,
            "verantwortlich": "",
            "datum": "",
            "herkunft": "HERMES PIA",
        })
    return raus


# ---- Vorschläge für 1.2 und 1.3 ------------------------------------------- #
#
# Vorschläge, nicht Antworten. Sie entstehen aus dem, was im Auftrag steht –
# HERMES PIA fügt keinen Sachverhalt hinzu, es formt vorhandene Angaben zu
# einer Frage um. Bewertung und Verantwortung bleiben leer: sie gehören
# denen, die die Checkliste ausfüllen.

def organisationsspezifische_vorschlaege(wissen):
    """Kapitel 1.2 – aus den Vorgaben der Stammorganisation (Kapitel 0.5)."""
    raus = []
    for zeile in _zeilen(wissen, "vorgaben_methoden"):
        titel = _feld(zeile, "titel")
        vorgabe = _feld(zeile, "vorgabe")
        if not titel or "stammorganisation" not in vorgabe.lower():
            continue
        raus.append({
            "nr": f"O-{len(raus) + 1:02d}",
            "pruefpunkt": titel,
            "kriterium": f"Ist die Vorgabe der Stammorganisation zu «{titel}» "
                         "bekannt und für dieses Projekt geklärt?",
            "bewertung": "", "erlaeuterung": "", "verantwortlich": "", "datum": "",
            "herkunft": "Vorschlag aus Kapitel 0.5",
        })
    return raus


def projektspezifische_vorschlaege(wissen):
    """Kapitel 1.3 – aus den Risiken (Kapitel 7) mit der höchsten Risikozahl."""
    def zahl(zeile):
        roh = _feld(zeile, "risikozahl", "rz")
        try:
            return int("".join(c for c in roh if c.isdigit()) or 0)
        except ValueError:
            return 0

    risiken = sorted(_zeilen(wissen, "risiken"), key=zahl, reverse=True)
    raus = []
    for zeile in risiken:
        massnahme = _feld(zeile, "massnahmen", "massnahme")
        if not massnahme:
            continue
        # Die Massnahme wird zur Frage – gekürzt auf den ersten Satz, damit die
        # Zeile lesbar bleibt. Der Wortlaut stammt aus dem Auftrag, nicht von hier.
        erster_satz = massnahme.split(". ")[0].rstrip(".")
        raus.append({
            "nr": f"P-{len(raus) + 1:02d}",
            "pruefpunkt": f"Risiko {_feld(zeile, 'nr') or '?'}",
            "kriterium": f"Ist die vorgesehene Massnahme eingeleitet: "
                         f"«{erster_satz}»?",
            "bewertung": "", "erlaeuterung": "", "verantwortlich": "", "datum": "",
            "herkunft": "Vorschlag aus Kapitel 7",
        })
        if len(raus) >= 5:      # die Checkliste ist kein zweites Risikoregister
            break
    return raus


# ---- Das Tor -------------------------------------------------------------- #

def offene_punkte(zeilen):
    """Zeilen, die der Freigabe im Weg stehen – «nicht erfüllt» und Leerstellen.

    Eine unbewertete Zeile ist kein stilles Ja. Wer 1.2 oder 1.3 ergänzt, muss
    sie auch bewerten, sonst wäre der Vorschlag ein Weg, die Prüfung zu
    verkürzen statt sie zu vertiefen.
    """
    offen = []
    for z in zeilen or []:
        if not isinstance(z, dict):
            continue
        bewertung = str(z.get("bewertung", "") or "").strip()
        if not bewertung or bewertung in BLOCKIEREND:
            offen.append(z)
    return offen


def freigabe_moeglich(zeilen):
    return not offene_punkte(zeilen)
