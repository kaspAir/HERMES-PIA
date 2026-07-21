"""Deterministische Nachbearbeitung eines Whisper-Transkripts.

Zwei Artefakte, die nichts mit dem Gesagten zu tun haben:

**Prompt-Echo.** Whisper bekommt einen Vokabular-Hinweis mit (Basis-Prompt plus
projektspezifischer Kontext, siehe kontext.py). Ist der Ton undeutlich oder eine
Pause zu lang, gibt das Modell Teile dieses Prompts als Transkript aus. Gemessen
am 21.07.2026: der Satz «Das Projekt heisst BKI Test 4.» stand dreimal im
Transkript, ohne je gesprochen worden zu sein.

**Wiederholungsschleife.** Derselbe Satz mehrfach hintereinander -- ein bekanntes
Verhalten autoregressiver Modelle bei schwachem Signal.

Beides wird hier entfernt, BEVOR der Text im Antwortfeld landet. Bewusst
deterministisch und eng: entfernt wird nur, was dem mitgeschickten Prompt
entspricht oder unmittelbar wiederholt ist. Alles andere bleibt stehen -- auch
Versprecher und Füllwörter, die gehören dem Sprecher.
"""
import re

_SATZ_ENDE = re.compile(r"(?<=[.!?])\s+")


def _normalisiert(satz):
    """Vergleichsform: Kleinschreibung, ohne Satzzeichen, einfache Abstände."""
    return " ".join(re.sub(r"[^\wäöüàéèç ]+", " ", satz.lower()).split())


def _saetze(text):
    return [s.strip() for s in _SATZ_ENDE.split(text or "") if s.strip()]


_MIN_ECHO_WOERTER = 4          # kürzere Übereinstimmungen sind Zufall, kein Echo


def _echo_muster(prompt):
    """Suchmuster für die Sätze des Prompts – wortweise, tolerant gegen
    Gross-/Kleinschreibung und Satzzeichen dazwischen."""
    muster = []
    for satz in _saetze(prompt):
        woerter = _normalisiert(satz).split()
        if len(woerter) < _MIN_ECHO_WOERTER:
            continue
        muster.append(re.compile(
            r"[^\w]*".join(re.escape(w) for w in woerter), re.IGNORECASE))
    return muster


def _ohne_echo(satz, muster):
    """Schneidet Prompt-Echo AUS dem Satz heraus.

    Bewusst nicht den ganzen Satz verwerfen: Whisper verklebt das Echo gern mit
    echter Sprache («… in unserem eigenen rechenzentrum das projekt heisst bki
    test 4»). Wer hier den Satz wegwirft, verliert das Diktat.
    """
    for m in muster:
        satz = m.sub(" ", satz)
    return " ".join(satz.split()).strip(" ,;:-–—")


def bereinige(text, prompt="", max_wiederholungen=1):
    """Entfernt Prompt-Echo und unmittelbare Satzwiederholungen."""
    saetze = _saetze(text)
    if not saetze:
        return (text or "").strip()

    muster = _echo_muster(prompt)
    behalten, letzte_norm, wie_oft = [], None, 0
    for satz in saetze:
        satz = _ohne_echo(satz, muster)
        if len(satz.split()) < 2:             # nach dem Schnitt bleibt nichts Sinnvolles
            continue
        norm = _normalisiert(satz)
        if norm == letzte_norm:
            wie_oft += 1
            if wie_oft >= max_wiederholungen:
                continue                      # Schleife des Modells
        else:
            letzte_norm, wie_oft = norm, 0
        behalten.append(satz)

    ergebnis = " ".join(behalten).strip()
    # Nie alles wegwerfen: bleibt nichts übrig, war die Erkennung unbrauchbar –
    # dann lieber das Rohtranskript zeigen als ein leeres Feld, das wie ein
    # Aufnahmefehler aussieht.
    return ergebnis or (text or "").strip()
