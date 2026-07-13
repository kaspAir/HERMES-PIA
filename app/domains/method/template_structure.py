"""Ableiten einer Interview-/Dokumentstruktur aus einer hochgeladenen Word-Vorlage.

Kernidee **"verankern statt auflösen"**: Die Kapitel einer Kundenvorlage werden –
umlaut- und synonymtolerant – auf die kanonischen HERMES-Abschnitte abgebildet.

- **Erkanntes Kapitel** → behält den vollständigen kanonischen Abschnitt aus der
  method.yaml und damit die gesamte HERMES-Intelligenz (Komplexität, Kosten aus
  Kap. 3.1, Kataloge/Gap-Checks, deterministische Nachbearbeitung), die an der
  kanonischen Section-ID hängt.
- **Unbekanntes / umbenanntes Kapitel** → wird generisch als Fliesstext erfragt;
  die Fragen entstehen aus dem Kapiteltitel (LLM mit robustem Fallback).

Das Modul ist bewusst frei von Flask/DB: docx-Bytes rein, Struktur raus. So bleibt
die Kernlogik – das Risikostück – isoliert testbar.
"""
import re
import zipfile
from io import BytesIO
from xml.etree import ElementTree as ET

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_P = f"{{{_W}}}p"
_PPR = f"{{{_W}}}pPr"
_PSTYLE = f"{{{_W}}}pStyle"
_OUTLINE = f"{{{_W}}}outlineLvl"
_T = f"{{{_W}}}t"
_VAL = f"{{{_W}}}val"

# Führende Nummerierung wie "1", "1.", "2.1", "0.2 " vor dem eigentlichen Titel.
_LEADING_NUMBER = re.compile(r"^\s*\d+(?:[.\)]\d+)*[.\)]?\s+")


def _normalize(s):
    """Kleinschreibung + Umlaut-Transkription; führende Kapitelnummer entfernt."""
    s = (s or "").strip()
    s = _LEADING_NUMBER.sub("", s)
    s = s.lower().replace("-", " ")
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        s = s.replace(a, b)
    # Mehrfach-Leerzeichen und Rand-Satzzeichen glätten
    s = re.sub(r"\s+", " ", s).strip(" .:-")
    return s


# Strukturelle Überschriften, die nie ein inhaltliches Kapitel sind (allgemeine
# Dokumentstruktur, nicht HERMES-spezifisch) – werden nicht interviewt.
_STRUKTUR_STOPWORTE = {
    "inhaltsverzeichnis", "table of contents", "inhalt",
    "dokument protokoll", "aenderungsverzeichnis", "aenderungsprotokoll",
    "aenderungshistorie", "revisionsverzeichnis", "protokoll",
    "abbildungsverzeichnis", "tabellenverzeichnis",
}


# Synonyme (normalisiert) → kanonische Section-ID. HERMES-Varianten benennen
# Kapitel häufig um; diese Tabelle fängt die geläufigen Abweichungen ab, ohne
# dass wir dafür ein LLM brauchen. Erweiterbar ohne Codeumbau.
_SYNONYME = {
    # Ausgangslage
    "ausgangssituation": "ausgangslage",
    "ausgangslage und kontext": "ausgangslage",
    "kontext": "ausgangslage",
    "anlass": "ausgangslage",
    "anlass und kontext": "ausgangslage",
    "problemstellung": "ausgangslage",
    "hintergrund": "ausgangslage",
    # Ziele
    "zielsetzung": "ziele",
    "zielsetzungen": "ziele",
    "projektziele": "ziele",
    "ziele des projekts": "ziele",
    "ziele der initialisierung": "ziele",
    # Rahmenbedingungen
    "rahmenbedingungen und vorgaben": "rahmenbedingungen",
    "vorgaben": "rahmenbedingungen",
    "vorgaben und rahmenbedingungen": "rahmenbedingungen",
    # Ergebnisse / Termine
    "ergebnisse": "termine",
    "lieferergebnisse": "termine",
    "ergebnisse und termine": "termine",
    "liefergegenstaende": "termine",
    "meilensteine": "termine",
    "termine": "termine",
    # Personalaufwand
    "aufwand": "personalaufwand",
    "personalaufwand": "personalaufwand",
    "aufwaende": "personalaufwand",
    "aufwandschaetzung": "personalaufwand",
    "personal": "personalaufwand",
    # Sachmittel
    "sachmittel und infrastruktur": "sachmittel",
    "infrastruktur": "sachmittel",
    "hilfsmittel": "sachmittel",
    # Kosten
    "kosten": "kosten",
    "kostenschaetzung": "kosten",
    "budget": "kosten",
    "kosten und budget": "kosten",
    # Projektorganisation
    "organisation": "projektorganisation",
    "projektorganisation und personal": "projektorganisation",
    "aufbauorganisation": "projektorganisation",
    "rollen und verantwortlichkeiten": "projektorganisation",
    # Kommunikation
    "kommunikation und information": "kommunikation",
    "kommunikationsplan": "kommunikation",
    "information und kommunikation": "kommunikation",
    # Risiken
    "risiken": "risiken",
    "risikoanalyse": "risiken",
    "risiken und massnahmen": "risiken",
    "chancen und risiken": "risiken",
    # Referenzen / Definitionen
    "referenzen": "referenzierte_dokumente",
    "referenzierte dokumente": "referenzierte_dokumente",
    "mitgeltende unterlagen": "mitgeltende_unterlagen",
    "definitionen": "definitionen",
    "definitionen und abkuerzungen": "definitionen",
    "abkuerzungen": "definitionen",
    "abkuerzungen und glossar": "definitionen",
    "glossar": "definitionen",
    "abkuerzungsverzeichnis": "definitionen",
}


def _is_heading(p_el):
    """(is_heading, level) – erkennt Heading-Styles versch. Vorlagen + outlineLvl."""
    ppr = p_el.find(_PPR)
    if ppr is None:
        return (False, None)
    style_el = ppr.find(_PSTYLE)
    style = (style_el.get(_VAL, "") if style_el is not None else "")
    norm = style.lower()
    # Deckt "Heading1", "Überschrift1", das HERMES-Style "Hberschrift1105pt" u.ä. ab.
    if "heading" in norm or "berschrift" in norm or "titel" in norm:
        m = re.search(r"(\d)", norm)
        return (True, int(m.group(1)) if m else 1)
    outline = ppr.find(_OUTLINE)
    if outline is not None:
        try:
            lvl = int(outline.get(_VAL, "0"))
        except (TypeError, ValueError):
            lvl = 0
        # outlineLvl 0..8 → Ebene 1..9; 9 = "kein Gliederungstext"
        if lvl <= 4:
            return (True, lvl + 1)
    return (False, None)


def _p_text(p_el):
    return "".join(t.text or "" for t in p_el.iter(_T)).strip()


def extract_headings(docx_bytes):
    """Liest die Kapitelüberschriften einer .docx in Dokumentreihenfolge.

    Rückgabe: Liste von {"level": int, "text": str}. Robust gegenüber
    unterschiedlichen Heading-Style-Namen und leeren/kaputten Dateien
    (dann leere Liste, nie Exception nach aussen).
    """
    try:
        with zipfile.ZipFile(BytesIO(docx_bytes)) as zf:
            with zf.open("word/document.xml") as fh:
                xml = fh.read()
    except (zipfile.BadZipFile, KeyError, OSError):
        return []
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return []

    headings = []
    for p_el in root.iter(_P):
        is_h, level = _is_heading(p_el)
        if not is_h:
            continue
        text = _p_text(p_el)
        if text:
            headings.append({"level": level, "text": text})
    return headings


def match_canonical(heading_text, canonical_sections):
    """Ordnet eine Überschrift einer kanonischen Section-ID zu (oder None).

    Reihenfolge: exakter/teilweiser Titelvergleich (umlauttolerant) vor der
    Synonymtabelle – ein wörtlicher Treffer ist immer verlässlicher.
    """
    h = _normalize(heading_text)
    if not h:
        return None
    # 1) Titelvergleich gegen die kanonischen Abschnitte
    for sect in canonical_sections:
        title = _normalize(sect.get("title", ""))
        if title and (h == title or h.endswith(title) or title in h or h in title):
            return sect["id"]
    # 2) Synonymtabelle
    if h in _SYNONYME:
        return _SYNONYME[h]
    return None


def _slug(text, used):
    base = re.sub(r"[^a-z0-9]+", "_", _normalize(text)).strip("_") or "kapitel"
    slug = f"custom_{base}"[:60]
    n = 2
    while slug in used:
        slug = f"custom_{base}_{n}"[:60]
        n += 1
    used.add(slug)
    return slug


def _fallback_questions(title):
    return [
        f"Was gehört inhaltlich in das Kapitel «{title}»?",
        "Welche Punkte sind dabei für Ihr Vorhaben besonders wichtig?",
    ]


def build_derived_method(docx_bytes, canonical_method, question_gen=None):
    """Baut aus einer hochgeladenen Vorlage die abgeleitete Methode.

    - Behält die kanonische method.yaml (Vokabulare, Metadaten) unverändert.
    - Ersetzt nur ``sections`` durch die Reihenfolge/Auswahl der Vorlage:
      erkannte Kapitel = voller kanonischer Abschnitt, unbekannte = generischer
      Fliesstext-Abschnitt.

    ``question_gen`` ist optional ``(title) -> [str]`` (z.B. LLM-gestützt). Fehler
    oder None → deterministischer Fallback. Nie blockierend.

    Rückgabe: ``(method_dict, report)`` mit
    ``report = {"matched": [...], "generic": [...], "missing_canonical": [...]}``.
    """
    canonical_sections = list(canonical_method.get("sections", []))
    by_id = {s["id"]: s for s in canonical_sections}
    headings = extract_headings(docx_bytes)

    derived = []
    used_slugs = set()
    matched, generic, skipped = [], [], []
    seen_canonical = set()

    # Kandidaten für den Dokumenttitel (Methodenname/Framework, versch. Ablageorte).
    meta = canonical_method.get("method") or {}
    titel_kandidaten = {
        _normalize(v) for v in (meta.get("name"), canonical_method.get("name"),
                                meta.get("framework")) if v
    }

    # Vorspann/Hilfstexte erkennen: Kapitel VOR dem ersten echten HERMES-Kapitel
    # (z.B. «Hinweise zum HERMES-Dokument», «Beschreibung», Änderungsverzeichnis)
    # sind fixe Anleitungstexte – sie werden weder erfragt noch je überschrieben.
    # Default 0: ohne kanonischen Anker gibt es keinen Vorspann (sonst würde bei
    # einer Vorlage ohne erkannte Kapitel fälschlich ALLES übersprungen).
    first_canon = 0
    for i, h in enumerate(headings):
        sid = match_canonical(h["text"], canonical_sections)
        if sid and sid in by_id:
            first_canon = i
            break

    for idx, h in enumerate(headings):
        title = h["text"]
        norm = _normalize(title)

        # Container-Überschrift: die nächste Überschrift liegt tiefer → sie
        # gruppiert nur Unterkapitel und hat keinen eigenen Inhalt.
        nxt = headings[idx + 1] if idx + 1 < len(headings) else None
        if nxt and nxt["level"] > h["level"]:
            skipped.append({"heading": title, "grund": "container"})
            continue
        # Strukturelle Überschrift (Inhaltsverzeichnis, Protokoll …) oder der
        # Dokumenttitel selbst → kein Interviewkapitel.
        if norm in _STRUKTUR_STOPWORTE or norm in titel_kandidaten:
            skipped.append({"heading": title, "grund": "struktur"})
            continue

        sid = match_canonical(title, canonical_sections)
        if sid and sid in by_id and sid not in seen_canonical:
            seen_canonical.add(sid)
            derived.append(by_id[sid])
            matched.append({"heading": title, "section_id": sid})
            continue
        if sid and sid in seen_canonical:
            # Kapitel doppelt (z.B. Unterüberschrift) – nicht erneut aufnehmen.
            continue
        # Vorspann: ein nicht-kanonisches Kapitel VOR dem ersten HERMES-Kapitel
        # ist fixer Hilfstext (Hinweise/Beschreibung/Anleitung) → nie erfragen.
        if idx < first_canon:
            skipped.append({"heading": title, "grund": "vorspann"})
            continue
        # Generisches Kapitel: Fragen aus dem Titel ableiten.
        try:
            questions = question_gen(title) if question_gen else None
        except Exception:
            questions = None
        if not questions:
            questions = _fallback_questions(title)
        slug = _slug(title, used_slugs)
        derived.append({
            "id": slug,
            "number": "",
            "title": title,
            "type": "free_text",
            "required": False,
            "generic": True,
            "interview": {
                "intent": f"Den Inhalt des Kapitels «{title}» erarbeiten.",
                "questions": list(questions),
                "completeness": [],
            },
        })
        generic.append({"heading": title, "section_id": slug})

    missing = [s["id"] for s in canonical_sections
               if s.get("type") in ("free_text", "table")
               and s["id"] not in seen_canonical]

    # Ausgangslage zuerst erfragen: Komplexitäts- und Projekttyp-Einschätzung
    # leiten sich aus ihr ab und dienen allen nachgelagerten Vorschlägen als
    # Kontext. Betrifft nur die INTERVIEW-Reihenfolge – das erzeugte Dokument
    # folgt der Vorlage (die Erzeugung matcht Kapitel über den Titel, nicht die
    # Reihenfolge). Stabil: alle übrigen Kapitel behalten die Vorlagenreihenfolge.
    derived.sort(key=lambda s: 0 if s.get("id") == "ausgangslage" else 1)

    method = dict(canonical_method)
    method["sections"] = derived
    report = {"matched": matched, "generic": generic,
              "skipped": skipped, "missing_canonical": missing}
    return method, report
