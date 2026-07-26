"""Die D-Regeln des Invarianten-Katalogs auf der Ebene «Daten».

Jede Regel ist eine kleine Funktion mit genau einer Zuständigkeit und ohne
Sprachmodell – was eine Regel entscheiden kann, entscheidet die Regel
(Briefing, Leitplanken). Registriert wird über @regel; die Reihenfolge im
Ergebnis bestimmt das Gewicht, nicht die Definitionsreihenfolge.

**Bearbeitungsstand statt leeres Dokument** (Katalog 2.2): Ist ein Kapitel noch
gar nicht bearbeitet, ist eine leere Angabe KEIN Befund. Dafür prüft jede Regel
zuerst, ob ihr Abschnitt überhaupt vorliegt.

Regeln, die mangels Datenfeld noch nicht laufen können, melden sich als
`nicht_pruefbar` – sichtbar statt still übersprungen.
"""
import re
from datetime import date, timedelta

from app.domains.qualitaet import katalog as K
from app.domains.qualitaet.modell import DATEN, HINWEIS, MUSS, VORBEHALT, Befund

REGELN = []


def regel(rid, gewicht, ebene=DATEN):
    def deko(fn):
        fn.rid, fn.gewicht, fn.ebene = rid, gewicht, ebene
        REGELN.append(fn)
        return fn
    return deko


# ---- Hilfen -------------------------------------------------------------- #

def _zeilen(ctx, sid):
    """Tabellenzeilen eines Abschnitts – oder None, wenn nicht bearbeitet."""
    eintrag = ctx.answers.get(sid)
    if not isinstance(eintrag, dict):
        return None
    rows = eintrag.get("extracted")
    return rows if isinstance(rows, list) else None


def _text(ctx, sid):
    eintrag = ctx.answers.get(sid)
    if not isinstance(eintrag, dict):
        return None
    ex = eintrag.get("extracted")
    if isinstance(ex, dict):
        return ex.get("text") or ""
    return eintrag.get("raw_text") or ""


def _zahl(wert):
    """Erste Zahl aus einem Feld ('12 PT', 'CHF 1'200.50') – None wenn keine."""
    if isinstance(wert, (int, float)):
        return float(wert)
    t = str(wert or "").replace("'", "").replace("’", "").replace(" ", "")
    m = re.search(r"-?\d+(?:[.,]\d+)?", t)
    return float(m.group().replace(",", ".")) if m else None


def _gefuellt(row, feld):
    w = str((row or {}).get(feld, "") or "").strip()
    if not w:
        return False
    return not any(p in w.lower() for p in K.PLATZHALTER)


def _ist_meilenstein(row):
    return "meilenstein" in str((row or {}).get("ergebnis", "")).lower()


def _datum(wert):
    """'01.03.2026' | '2026-03-01' -> date; sonst None."""
    t = str(wert or "").strip()
    for muster in ("%d.%m.%Y", "%Y-%m-%d", "%d.%m.%y"):
        try:
            from datetime import datetime
            return datetime.strptime(t, muster).date()
        except ValueError:
            continue
    return None


def _arbeitstage(von, bis):
    """Arbeitstage zwischen zwei Daten (Mo–Fr, ohne Feiertage)."""
    if not von or not bis or bis < von:
        return 0
    tage, lauf = 0, von
    while lauf < bis:
        lauf += timedelta(days=1)
        if lauf.weekday() < 5:
            tage += 1
    return tage


def _rollen_pt(ctx):
    """{rolle_lower: summe_pt} aus Kap. 3.1 – mehrfach besetzte Rollen summiert
    (Katalog Abschnitt 11)."""
    out = {}
    for r in (_zeilen(ctx, "personalaufwand") or []):
        rolle = str(r.get("rolle", "")).strip().lower()
        pt = _zahl(r.get("aufwand"))
        if rolle and pt is not None:
            out[rolle] = out.get(rolle, 0.0) + pt
    return out


# ---- 3 · Dokumentweite Regeln -------------------------------------------- #

@regel("D-001", MUSS)
def d001_pt_stimmen_mit_monatsverteilung(ctx):
    """Kap. 3.1 je Rolle == Summe der Monatswerte derselben Rolle in Kap. 5."""
    aufwand = _rollen_pt(ctx)
    verteilung = _zeilen(ctx, "projektorganisation")
    if not aufwand or verteilung is None:
        return
    je_rolle = {}
    for r in verteilung:
        rolle = str(r.get("rolle_person", "")).split("/")[0].split("(")[0].strip().lower()
        summe = sum(_zahl(r.get(f"monat_{i}")) or 0.0 for i in range(1, 10))
        if rolle:
            je_rolle[rolle] = je_rolle.get(rolle, 0.0) + summe
    for rolle, pt in aufwand.items():
        ist = je_rolle.get(rolle)
        if ist is None:
            continue                      # Zuordnung prüft D-040
        if abs(pt - ist) > K.TOLERANZ_PT:
            yield Befund("D-001", MUSS, DATEN,
                         f"Personalaufwand und Monatsverteilung stimmen nicht überein: "
                         f"{rolle} 3.1 = {pt:g} PT, Kap. 5 = {ist:g} PT.",
                         "Kap. 3.1 / Kap. 5")


@regel("D-002", MUSS)
def d002_kosten_aus_aufwand_herleitbar(ctx):
    """Interne Personalkosten = Summe(PT × Kostensatz); Total stimmig."""
    kosten = _zeilen(ctx, "kosten")
    aufwand = _rollen_pt(ctx)
    if kosten is None or not aufwand or not ctx.tarife:
        return
    intern_satz = _zahl(ctx.tarife.get("intern")) or 0.0
    extern_satz = _zahl(ctx.tarife.get("extern")) or 0.0
    if not intern_satz:
        return
    # Externe Rollen rechnen in der externen Kategorie (Katalog Abschnitt 11).
    erwartet = sum(pt * (extern_satz if "extern" in rolle else intern_satz)
                   for rolle, pt in aufwand.items())
    ausgewiesen = None
    for r in kosten:
        if K.enthaelt(r.get("phase"), ("total", "summe", "gesamt")):
            ausgewiesen = _zahl(r.get("betrag"))
    if ausgewiesen is None:
        summen = [_zahl(r.get("betrag")) for r in kosten]
        summen = [s for s in summen if s is not None]
        ausgewiesen = sum(summen) if summen else None
    if ausgewiesen is None:
        return
    # Sachmittel duerfen zusaetzlich enthalten sein -> nur Unterdeckung melden.
    if erwartet - ausgewiesen > max(K.TOLERANZ_KOSTEN, erwartet * 0.02):
        yield Befund("D-002", MUSS, DATEN,
                     f"Die Kosten in Kap. 3.3 lassen sich aus Aufwand und Kostensätzen "
                     f"nicht herleiten: erwartet {erwartet:,.0f}, ausgewiesen "
                     f"{ausgewiesen:,.0f}.".replace(",", "'"),
                     "Kap. 3.3")


@regel("D-006", MUSS)
def d006_ergebniszeilen_sind_benannte_ergebnisse(ctx):
    """Jede Zeile bezeichnet ein HERMES-Ergebnis oder ist als projektspezifisch
    gekennzeichnet. Das Kennzeichen fehlt im Datenmodell (Katalog 12)."""
    rows = _zeilen(ctx, "termine")
    if rows is None:
        return
    if not ctx.hat_feld("ergebnis_projektspezifisch"):
        yield Befund("D-006", MUSS, DATEN,
                     "Katalog- und projektspezifische Ergebnisse sind nicht unterscheidbar.",
                     "Kap. 4.1", nicht_pruefbar=True,
                     grund="Feld «projektspezifisch» fehlt im Datenmodell (Katalog 12)")
        return
    bekannt = [s for _, sw in K.PFLICHTERGEBNISSE for s in sw]
    bekannt += list(K.BESCHAFFUNG_ERGEBNIS[1]) + [s for _, sw in K.MEILENSTEINE for s in sw]
    for i, r in enumerate(rows, 1):
        name = str(r.get("ergebnis", "")).strip()
        if not name or r.get("projektspezifisch"):
            continue
        if not K.enthaelt(name, bekannt):
            yield Befund("D-006", MUSS, DATEN,
                         f"Zeile {i} der Ergebnisliste ist kein benanntes Ergebnis: "
                         f"«{name}».", "Kap. 4.1")


@regel("D-007", HINWEIS)
def d007_rollen_statt_personennamen(ctx):
    """Nur Verantwortlichkeits-SPALTEN in Tabellen – Deckblattnamen sind richtig
    (Katalog Abschnitt 11)."""
    felder = (("termine", "abnahme", "Kap. 4.1"),
              ("risiken", "verantwortung", "Kap. 7"),
              ("kommunikation", "verantwortlich", "Kap. 6"))
    for sid, feld, ort in felder:
        for r in (_zeilen(ctx, sid) or []):
            wert = str(r.get(feld, "")).strip()
            if wert and not K.ist_rolle(wert, ctx.zusatzrollen):
                yield Befund("D-007", HINWEIS, DATEN,
                             f"In {ort} steht ein Personenname statt einer Rolle: "
                             f"«{wert}».", ort)


@regel("D-008", MUSS)
def d008_provenienz_anhang(ctx):
    """Nachweis der Herkunft je Kapitel – Stufe 2 des Stufenplans."""
    yield Befund("D-008", MUSS, DATEN,
                 "Der Nachweis der Herkunft je Kapitel wird noch nicht geführt.",
                 "Anhang", nicht_pruefbar=True,
                 grund="Provenienz-Anhang ist Stufe 2 (Briefing Abschnitt 3)")


@regel("D-009", MUSS)
def d009_termine_innerhalb_der_phase(ctx):
    """Alle Liefertermine zwischen Phasenstart und -ende."""
    rows = _zeilen(ctx, "termine")
    start = _datum(ctx.phasenstart)
    if rows is None or not start:
        return
    ende = max((_datum(r.get("termin")) for r in rows
                if _datum(r.get("termin"))), default=None)
    for r in rows:
        t = _datum(r.get("termin"))
        if t and (t < start or (ende and t > ende)):
            yield Befund("D-009", MUSS, DATEN,
                         f"Der Termin von «{r.get('ergebnis', '')}» liegt ausserhalb "
                         f"der Initialisierungsphase.", "Kap. 4.1")


@regel("D-010", MUSS)
def d010_version_stimmt_mit_aenderungskontrolle(ctx):
    a, b = (ctx.deckblatt_version or "").strip(), (ctx.changelog_version or "").strip()
    if a and b and a != b:
        yield Befund("D-010", MUSS, DATEN,
                     f"Deckblatt-Version {a} und Änderungskontrolle {b} stimmen "
                     f"nicht überein.", "Deckblatt / Kap. 8")


# ---- 4 · Kapitel 0 ------------------------------------------------------- #

@regel("D-021", MUSS)
def d021_nummer_nur_mit_quelle(ctx):
    """Nie ein Wert ohne hinterlegte Quelle."""
    for sid, ort in (("referenzierte_dokumente", "Kap. 0.2"),
                     ("mitgeltende_unterlagen", "Kap. 0.3")):
        for r in (_zeilen(ctx, sid) or []):
            name = str(r.get("name", "")).strip()
            link = str(r.get("link", "")).strip()
            if name and link and not re.search(r"https?://|SR\s|\b[A-Z]{2}\s\d", link):
                yield Befund("D-021", MUSS, DATEN,
                             f"Zu «{name}» ist eine Nummer/ein Link angegeben, für die "
                             f"keine Quelle hinterlegt ist.", ort)


@regel("D-022", HINWEIS)
def d022_abkuerzungen_erklaert(ctx):
    """Verwendete Abkürzung ist in Kap. 0.4 erklärt."""
    defs = _zeilen(ctx, "definitionen")
    text = _text(ctx, "ausgangslage")
    if defs is None or not text:
        return
    erklaert = {str(r.get("abkuerzung", "")).strip().upper() for r in defs}
    # Nur eindeutige Abkuerzungen: >=3 Grossbuchstaben, keine gaengigen Woerter.
    for kuerzel in set(re.findall(r"\b[A-ZÄÖÜ]{3,6}\b", text)):
        if kuerzel not in erklaert and kuerzel not in {"HERMES", "PIA", "CHF"}:
            yield Befund("D-022", HINWEIS, DATEN,
                         f"Die Abkürzung «{kuerzel}» wird verwendet, ist aber nicht "
                         f"erklärt.", "Kap. 0.4")


# ---- 5 · Kapitel 2 ------------------------------------------------------- #

@regel("D-030", MUSS)
def d030_beide_zielarten(ctx):
    rows = _zeilen(ctx, "ziele")
    if not rows:
        return
    system = sum(1 for r in rows if K.enthaelt(r.get("kategorie"), K.SYSTEMZIEL))
    vorgehen = sum(1 for r in rows if K.enthaelt(r.get("kategorie"), K.VORGEHENSZIEL))
    if not system:
        yield Befund("D-030", MUSS, DATEN,
                     "Es fehlt mindestens ein Systemziel – der PIA braucht beide "
                     "Zielarten.", "Kap. 2.1")
    if not vorgehen:
        yield Befund("D-030", MUSS, DATEN,
                     "Es fehlt mindestens ein Vorgehensziel – der PIA braucht beide "
                     "Zielarten.", "Kap. 2.1")


@regel("D-031", MUSS)
def d031_zielzeilen_vollstaendig(ctx):
    for i, r in enumerate(_zeilen(ctx, "ziele") or [], 1):
        if not any(str(v).strip() for v in r.values()):
            continue
        for feld, label in (("kategorie", "Kategorie"), ("beschreibung", "Beschreibung"),
                            ("messgroesse", "Messgrösse"), ("prioritaet", "Priorität")):
            if not _gefuellt(r, feld):
                yield Befund("D-031", MUSS, DATEN, f"Ziel {i}: {label} fehlt.", "Kap. 2.1")


@regel("D-032", HINWEIS)
def d032_systemziele_ueberwiegen(ctx):
    rows = _zeilen(ctx, "ziele")
    if not rows:
        return
    system = sum(1 for r in rows if K.enthaelt(r.get("kategorie"), K.SYSTEMZIEL))
    vorgehen = sum(1 for r in rows if K.enthaelt(r.get("kategorie"), K.VORGEHENSZIEL))
    if vorgehen > system:          # Gleichstand meldet die Regel bewusst NICHT
        yield Befund("D-032", HINWEIS, DATEN,
                     f"Es sind mehr Vorgehens- als Systemziele erfasst ({vorgehen} zu "
                     f"{system}) – üblicherweise überwiegen die Systemziele. Bewusst so?",
                     "Kap. 2.1")


@regel("D-033", HINWEIS)
def d033_rahmenbedingung_vorhanden(ctx):
    rows = _zeilen(ctx, "rahmenbedingungen")
    if rows is None:
        return
    if not [r for r in rows if any(str(v).strip() for v in r.values())]:
        yield Befund("D-033", HINWEIS, DATEN, "Es sind keine Rahmenbedingungen erfasst.",
                     "Kap. 2.2")


# ---- 6 · Kapitel 3 ------------------------------------------------------- #

@regel("D-040", MUSS)
def d040_abnahmerollen_haben_aufwand(ctx):
    """Rollen aus Kap. 4.1 kommen in Kap. 3.1 mit Aufwand vor."""
    rows = _zeilen(ctx, "termine")
    aufwand = _rollen_pt(ctx)
    if rows is None or not aufwand:
        return
    for r in rows:
        rolle = str(r.get("abnahme", "")).strip()
        if not rolle or _ist_meilenstein(r):
            continue
        if not any(rolle.lower() in k or k in rolle.lower() for k in aufwand):
            yield Befund("D-040", MUSS, DATEN,
                         f"Die Rolle {rolle} wirkt an «{r.get('ergebnis', '')}» mit, hat "
                         f"aber keinen Aufwand in Kap. 3.1.", "Kap. 3.1 / Kap. 4.1")


@regel("D-041", HINWEIS)
def d041_auftraggeber_hat_aufwand(ctx):
    aufwand = _rollen_pt(ctx)
    if not aufwand:
        return
    if not any("auftraggeber" in r and pt > 0 for r, pt in aufwand.items()):
        yield Befund("D-041", HINWEIS, DATEN,
                     "Für den Auftraggeber ist kein Aufwand ausgewiesen – Steuerung "
                     "und Entscheide brauchen Zeit.", "Kap. 3.1")


@regel("D-042", MUSS)
def d042_kosten_intern_extern_getrennt(ctx):
    rows = _zeilen(ctx, "kosten")
    if not rows:
        return
    text = " ".join(str(r.get("phase", "")) for r in rows).lower()
    if "intern" not in text or "extern" not in text:
        yield Befund("D-042", MUSS, DATEN,
                     "In Kap. 3.3 fehlt die Trennung intern/extern oder eine "
                     "Zwischensumme.", "Kap. 3.3")


@regel("D-043", VORBEHALT)
def d043_kostensaetze_bestaetigt(ctx):
    if not ctx.hat_feld("kostensatz_status"):
        yield Befund("D-043", VORBEHALT, DATEN,
                     "Ob die Kostensätze bestätigt sind, ist nicht hinterlegt.",
                     "Kap. 3.3", nicht_pruefbar=True,
                     grund="Statusfeld «bestätigt/offen» fehlt im Datenmodell (Katalog 12)")


# ---- 7 · Kapitel 4.1 ----------------------------------------------------- #

@regel("D-050", MUSS)
def d050_pflichtergebnisse_vorhanden(ctx):
    rows = _zeilen(ctx, "termine")
    if not rows:
        return
    namen = " | ".join(str(r.get("ergebnis", "")) for r in rows).lower()
    pflicht = list(K.PFLICHTERGEBNISSE)
    if ctx.beschaffung_vorgesehen:
        pflicht.append(K.BESCHAFFUNG_ERGEBNIS)
    for label, stichworte in pflicht:
        if not K.enthaelt(namen, stichworte):
            yield Befund("D-050", MUSS, DATEN,
                         f"Das Pflichtergebnis «{label}» fehlt in der Terminliste.",
                         "Kap. 4.1")


@regel("D-051", MUSS)
def d051_meilensteine_vorhanden(ctx):
    rows = _zeilen(ctx, "termine")
    if not rows:
        return
    namen = " | ".join(str(r.get("ergebnis", "")) for r in rows).lower()
    for label, stichworte in K.MEILENSTEINE:
        if not K.enthaelt(namen, stichworte):
            yield Befund("D-051", MUSS, DATEN,
                         f"Der Meilenstein «{label}» fehlt.", "Kap. 4.1")


@regel("D-052", MUSS)
def d052_ergebniszeilen_vollstaendig(ctx):
    """Meilensteinzeilen: Entscheidrolle statt Prüfmethode (Katalog Abschnitt 11)."""
    for r in (_zeilen(ctx, "termine") or []):
        name = str(r.get("ergebnis", "")).strip()
        if not name:
            continue
        for feld, label in (("termin", "Liefertermin"), ("abnahme", "Abnahmerolle")):
            if not _gefuellt(r, feld):
                yield Befund("D-052", MUSS, DATEN, f"Zeile «{name}»: {label} fehlt.",
                             "Kap. 4.1")
        # Auch ein Meilenstein braucht hier einen Eintrag – die Entscheidform.
        if not _gefuellt(r, "pruefmethode"):
            fehlt = "Entscheidform" if _ist_meilenstein(r) else "Prüfmethode"
            yield Befund("D-052", MUSS, DATEN, f"Zeile «{name}»: {fehlt} fehlt.",
                         "Kap. 4.1")


@regel("D-053", MUSS)
def d053_abnahmerolle_aus_katalog(ctx):
    for r in (_zeilen(ctx, "termine") or []):
        wert = str(r.get("abnahme", "")).strip()
        if wert and not K.ist_rolle(wert, ctx.zusatzrollen):
            yield Befund("D-053", MUSS, DATEN, f"«{wert}» ist keine bekannte Rolle.",
                         "Kap. 4.1")


@regel("D-054", MUSS)
def d054_reihenfolge_stimmig(ctx):
    rows = _zeilen(ctx, "termine")
    if not rows:
        return
    termin_je = {}
    for r in rows:
        t = _datum(r.get("termin"))
        name = str(r.get("ergebnis", "")).lower()
        if t:
            for stichwort in {s for _, sw in K.PFLICHTERGEBNISSE for s in sw} | \
                             set(K.BESCHAFFUNG_ERGEBNIS[1]) | \
                             {s for _, sw in K.MEILENSTEINE for s in sw}:
                if stichwort in name:
                    # frühester Termin je Stichwort
                    if stichwort not in termin_je or t < termin_je[stichwort][0]:
                        termin_je[stichwort] = (t, str(r.get("ergebnis", "")))
    for vorher, nachher in K.REIHENFOLGE:
        a, b = termin_je.get(vorher), termin_je.get(nachher)
        if a and b and a[0] > b[0]:
            yield Befund("D-054", MUSS, DATEN,
                         f"«{a[1]}» ist nach «{b[1]}» terminiert, obwohl es davor "
                         f"liegen muss.", "Kap. 4.1")


@regel("D-055", MUSS)
def d055_zeit_fuer_review(ctx):
    rows = _zeilen(ctx, "termine")
    if not rows:
        return
    meilensteine = [(_datum(r.get("termin")), str(r.get("ergebnis", "")))
                    for r in rows if _ist_meilenstein(r) and _datum(r.get("termin"))]
    if not meilensteine:
        return
    for r in rows:
        if _ist_meilenstein(r):
            continue
        t = _datum(r.get("termin"))
        if not t:
            continue
        spaeter = sorted((m for m in meilensteine if m[0] >= t))
        if not spaeter:
            continue
        ms_datum, ms_name = spaeter[0]
        if _arbeitstage(t, ms_datum) < ctx.mindestabstand:
            yield Befund("D-055", MUSS, DATEN,
                         f"Zwischen «{r.get('ergebnis', '')}» und «{ms_name}» bleibt "
                         f"keine Zeit für Review und Freigabe.", "Kap. 4.1")


@regel("D-056", MUSS)
def d056_aufwand_passt_in_die_phasendauer(ctx):
    aufwand = _rollen_pt(ctx)
    tage = ctx.phasendauer_arbeitstage
    if not aufwand or not tage:
        return
    rolle, pt = max(aufwand.items(), key=lambda kv: kv[1])
    if pt > tage:
        yield Befund("D-056", MUSS, DATEN,
                     f"{rolle} hat {pt:g} PT bei einer Phasendauer von {tage} "
                     f"Arbeitstagen – die Termine sind aus Aufwand statt Dauer "
                     f"gerechnet.", "Kap. 3.1 / Kap. 4.1")


@regel("D-057", MUSS)
def d057_phasenende_gleich_letzter_meilenstein(ctx):
    rows = _zeilen(ctx, "termine")
    ende = _datum(ctx.phasenende)
    if rows is None or not ende:
        return
    ms = [_datum(r.get("termin")) for r in rows
          if _ist_meilenstein(r) and _datum(r.get("termin"))]
    if ms and max(ms) != ende:
        yield Befund("D-057", MUSS, DATEN,
                     f"Das Phasenende {ende:%d.%m.%Y} passt nicht zum letzten "
                     f"Meilenstein {max(ms):%d.%m.%Y}.", "Kap. 4.1")


# ---- 8 · Kapitel 5 ------------------------------------------------------- #

@regel("D-060", HINWEIS)
def d060_monatsspalten_decken_die_phase(ctx):
    rows = _zeilen(ctx, "projektorganisation")
    monate = ctx.phasendauer_monate
    if rows is None or not monate:
        return
    genutzt = 0
    for r in rows:
        for i in range(1, 10):
            if _zahl(r.get(f"monat_{i}")):
                genutzt = max(genutzt, i)
    if genutzt and genutzt < monate:
        yield Befund("D-060", HINWEIS, DATEN,
                     f"Die Monatsverteilung deckt nur {genutzt} von {monate} Monaten ab.",
                     "Kap. 5")


@regel("D-061", VORBEHALT)
def d061_besetzung_angegeben(ctx):
    for r in (_zeilen(ctx, "projektorganisation") or []):
        wert = str(r.get("rolle_person", "")).strip()
        if not wert:
            continue
        # «Rolle / Name» – fehlt der Namensteil, ist die Besetzung offen.
        teile = [t.strip() for t in re.split(r"[/(]", wert) if t.strip()]
        if len(teile) < 2:
            yield Befund("D-061", VORBEHALT, DATEN,
                         f"Für die Rolle {teile[0] if teile else wert} ist keine "
                         f"Besetzung angegeben.", "Kap. 5")


@regel("D-062", VORBEHALT)
def d062_verfuegbarkeit_bestaetigt(ctx):
    for r in (_zeilen(ctx, "projektorganisation") or []):
        rolle = str(r.get("rolle_person", "")).strip()
        if rolle and not _gefuellt(r, "bestaetigung"):
            yield Befund("D-062", VORBEHALT, DATEN,
                         f"Die Verfügbarkeit von {rolle} ist nicht bestätigt.", "Kap. 5")


# ---- 9 · Kapitel 7 ------------------------------------------------------- #

@regel("D-070", MUSS)
def d070_risiko_vorhanden(ctx):
    rows = _zeilen(ctx, "risiken")
    if rows is None:
        return
    if not [r for r in rows if str(r.get("beschreibung", "")).strip()]:
        yield Befund("D-070", MUSS, DATEN, "Es sind keine Risiken erfasst.", "Kap. 7")


@regel("D-071", MUSS)
def d071_risikozeilen_vollstaendig(ctx):
    for i, r in enumerate(_zeilen(ctx, "risiken") or [], 1):
        if not str(r.get("beschreibung", "")).strip():
            continue
        for feld, label in (("ew", "Eintrittswahrscheinlichkeit"), ("ag", "Auswirkung"),
                            ("massnahmen", "Massnahme"), ("verantwortung", "Verantwortung"),
                            ("termin", "Termin")):
            if not _gefuellt(r, feld):
                yield Befund("D-071", MUSS, DATEN, f"Risiko {i}: {label} fehlt.", "Kap. 7")


@regel("D-072", MUSS)
def d072_risikozahl_stimmt(ctx):
    for i, r in enumerate(_zeilen(ctx, "risiken") or [], 1):
        ew = K.RISIKO_STUFE.get(str(r.get("ew", "")).strip().lower())
        ag = K.RISIKO_STUFE.get(str(r.get("ag", "")).strip().lower())
        zahl = _zahl(r.get("risikozahl"))
        if ew and ag and zahl is not None and abs(zahl - ew * ag) > 0.01:
            yield Befund("D-072", MUSS, DATEN,
                         f"Risiko {i}: Risikozahl {zahl:g} passt nicht zu "
                         f"{r.get('ew')} × {r.get('ag')} = {ew * ag}.", "Kap. 7")


@regel("D-073", MUSS)
def d073_vorbestimmte_loesung_hat_risiko(ctx):
    if not ctx.hat_feld("loesung_vorbestimmt"):
        yield Befund("D-073", MUSS, DATEN,
                     "Ob in der Ausgangslage eine Lösung vorbestimmt ist, ist nicht "
                     "hinterlegt.", "Kap. 1 / Kap. 7", nicht_pruefbar=True,
                     grund="Kennzeichen «Lösung vorbestimmt» fehlt im Datenmodell (Katalog 12)")


# ---- 10 · Kapitel 8 ------------------------------------------------------ #

@regel("D-080", MUSS)
def d080_aenderungskontrolle_gefuehrt(ctx):
    if ctx.changelog is None:
        return
    if not ctx.changelog:
        yield Befund("D-080", MUSS, DATEN, "Die Änderungskontrolle ist nicht geführt.",
                     "Kap. 8")
