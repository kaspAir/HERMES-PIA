"""Synthetische Interviewfälle – erfundene Organisationen, erfundene Personen.

WAS DIESE FÄLLE SIND: deterministische Drehbücher. Zu jedem Benutzerbeitrag
steht die Modellantwort, die der VERTRAG erwartet (Operationen im JSON-Format).
Damit lassen sich Zustand, Projektion, Planer, Anzeige und Export
reproduzierbar durchspielen.

WAS SIE NICHT SIND: ein Nachweis der Interviewqualität eines echten
Sprachmodells. Ob ein Modell aus diesen Beiträgen dieselben Operationen
ableitet, ist eine eigene Prüfung (tools/evaluation_interview.py --live, nur
mit autorisiertem Kostenrahmen) und eine fachliche Abnahme.

Alle Namen sind erfunden («Musterkanton», «Beispielstadt»). Keine echten
Kunden, keine echten Personen.
"""

# Erfahrungskorpus: erfundene Passagen im Stil früherer HERMES-5.1-Aufträge.
KORPUS = [
    {"projekt": "Vergleich-A (Ablösung Registeranwendung)",
     "text": ("1 Ausgangslage\nDie Ablösung der Fachanwendung zeigte, dass die Migration der "
              "Datenbestände unterschätzt wurde. Die Schnittstelle zum Grundbuch war nicht "
              "dokumentiert; [Person_3] von [Org_2] bezifferte den Mehraufwand auf CHF 480'000.\n"
              "2 Erkenntnisse\nDie Datenbestände sollten früh auf Qualität und Umfang untersucht "
              "werden, bevor über eine Lösung entschieden wird.")},
    {"projekt": "Vergleich-B (Ersatz Fachanwendung Bewilligungen)",
     "text": ("1 Ausgangslage\nBei der Ablösung der Fachanwendung für Bewilligungen waren die "
              "Schnittstellen zu Grundbuch und Gebäuderegister der grösste Unsicherheitsfaktor. "
              "Die Migration der Datenbestände verzögerte die Einführung.")},
    {"projekt": "Vergleich-C (Verfahren nach HERMES 5.1)",
     "text": ("2 Vorgehen\nGemäss HERMES 5.1 folgt nach der Voranalyse der Projektauftrag. "
              "Die Voranalyse ist zwingend vor dem Projektauftrag abzuschliessen; der "
              "Phasenbericht der Initialisierung wird dem Projektausschuss vorgelegt.")},
]

# Ein vollständiger Fall: Ablösevorhaben im erfundenen Musterkanton.
ABLOESUNG = {
    "id": "F-01",
    "titel": "Ablösung der Fachanwendung für Baugesuche (Musterkanton)",
    "kopf": {"projektname": "Ablösung BauGesuch", "auftraggeber": "Andrea Beispiel",
             "projektleiter": "Sam Muster"},
    "tarife": {"intern": 1200, "extern": 1800},
    "schritte": [
        {
            "text": ("Unsere Fachanwendung für Baugesuche ist vierzehn Jahre alt. Gesuche werden "
                     "doppelt erfasst, weil das Grundbuch nicht angebunden ist. Ich habe gehört, "
                     "der Hersteller stellt den Support Ende 2027 ein. Die Initialisierung soll am "
                     "2. November 2026 starten und Ende Februar 2027 abgeschlossen sein. Für mich "
                     "rechne ich mit etwa 25 Personentagen. Ein Risiko: die Fachleute der "
                     "Bewilligungsabteilung sind im Winter kaum verfügbar."),
            "aussagen": {"operationen": [
                {"op": "neu", "inhalt": "Die Fachanwendung für Baugesuche ist vierzehn Jahre alt",
                 "art": "benutzerangabe", "quelle": "wortlaut", "thema": "Altsystem",
                 "ziele": [{"abschnitt": "ausgangslage", "felder": {}}]},
                {"op": "neu", "inhalt": "Gesuche werden doppelt erfasst, weil das Grundbuch nicht angebunden ist",
                 "art": "benutzerangabe", "quelle": "wortlaut", "thema": "Doppelerfassung",
                 "ziele": [{"abschnitt": "ausgangslage", "felder": {}}]},
                {"op": "neu", "inhalt": "Der Hersteller stellt den Support Ende 2027 ein",
                 "art": "annahme", "quelle": "wortlaut", "thema": "Supportende",
                 "ziele": [{"abschnitt": "ausgangslage", "felder": {}}]},
                {"op": "neu", "inhalt": "Die Initialisierung läuft vom 2. November 2026 bis Ende Februar 2027",
                 "art": "benutzerangabe", "quelle": "wortlaut", "thema": "Zeitrahmen",
                 "ziele": [{"abschnitt": "eckdaten",
                            "felder": {"start_initialisierung": "2026-11-02",
                                       "ende_initialisierung": "2027-02-26"}}]},
                {"op": "neu", "inhalt": "Die Projektleitung rechnet mit etwa 25 Personentagen",
                 "art": "schaetzung", "quelle": "wortlaut", "thema": "Aufwand PL",
                 "ziele": [{"abschnitt": "personalaufwand",
                            "felder": {"rolle": "PL", "aufwand": "25"}}]},
                {"op": "neu", "inhalt": "Fachleute der Bewilligungsabteilung sind im Winter kaum verfügbar",
                 "art": "benutzerangabe", "quelle": "wortlaut", "thema": "Verfügbarkeit",
                 "ziele": [{"abschnitt": "risiken",
                            "felder": {"beschreibung": "Fachleute der Bewilligungsabteilung sind im Winter kaum verfügbar"}}]},
                {"op": "neu", "inhalt": "Es handelt sich um ein Ablösevorhaben mit Datenmigration",
                 "art": "benutzerangabe", "quelle": "gefolgert", "thema": "Vorhabenstyp",
                 "ziele": [{"abschnitt": "ausgangslage", "felder": {}}]},
            ]},
            "themen": {"themen": [
                {"thema": "Datenbestände und Schnittstellen untersuchen", "regel": "R1",
                 "uebertragbarkeit": "nutzbar",
                 "begruendung": "Zwei Ablösevorhaben unterschätzten Migration und Schnittstellen",
                 "frage_ansatz": "Welche Datenbestände und Schnittstellen soll die Initialisierung "
                                 "untersuchen, damit der Umfang der Ablösung abschätzbar wird?",
                 "pia_ziele": ["ziele", "risiken"], "offene_aspekte": "Datenqualität, Grundbuch",
                 "quellen": "@migration"},
                {"thema": "Voranalyse vor dem Projektauftrag", "regel": "R2",
                 "uebertragbarkeit": "nicht_uebernehmen",
                 "begruendung": "Methodenaussage HERMES 5.1 – in HERMES 2022 nicht übernehmen",
                 "frage_ansatz": "", "pia_ziele": ["termine"], "quellen": "@methode"},
            ]},
            "frage": "Welche Datenbestände und Schnittstellen soll die Initialisierung untersuchen, "
                     "damit der Umfang der Ablösung abschätzbar wird?",
        },
        {
            "text": "Korrektur: Die Initialisierung endet Ende März 2027, nicht im Februar.",
            "aussagen": {"operationen": [
                {"op": "korrektur", "aussage": "A-0004",
                 "inhalt": "Die Initialisierung läuft vom 2. November 2026 bis 31. März 2027",
                 "art": "benutzerangabe", "quelle": "wortlaut",
                 "ziele": [{"abschnitt": "eckdaten",
                            "felder": {"start_initialisierung": "2026-11-02",
                                       "ende_initialisierung": "2027-03-31"}}]},
            ]},
            "frage": "Was soll am Ende der Initialisierung erreicht sein – woran erkennst Du, "
                     "dass die Phase erfolgreich war?",
        },
        {
            "text": ("Wir müssen den Datenbestand und die Grundbuch-Schnittstelle untersuchen, das ist "
                     "wichtig. Ziele: eine Studie mit mindestens zwei Lösungsvarianten bis Ende Januar, "
                     "und ein Entscheid des Auftraggebers über das weitere Vorgehen. Der Auftraggeber "
                     "braucht etwa 6 Tage."),
            "aussagen": {"operationen": [
                {"op": "rag_bewerten", "thema_id": 1, "passt": True},
                {"op": "neu", "inhalt": "Datenbestand und Grundbuch-Schnittstelle untersuchen",
                 "art": "benutzerangabe", "quelle": "wortlaut", "thema": "Untersuchungsauftrag Daten",
                 "ziele": [{"abschnitt": "ziele",
                            "felder": {"kategorie": "Vorgehensziel",
                                       "beschreibung": "Datenbestand und Grundbuch-Schnittstelle untersuchen",
                                       "messgroesse": "Bericht zu Umfang und Qualität liegt vor",
                                       "prioritaet": "Hoch"}}]},
                {"op": "neu", "inhalt": "Studie mit mindestens zwei Lösungsvarianten bis Ende Januar",
                 "art": "benutzerangabe", "quelle": "wortlaut", "thema": "Studie",
                 "ziele": [{"abschnitt": "ziele",
                            "felder": {"kategorie": "Systemziel",
                                       "beschreibung": "Studie mit mindestens zwei Lösungsvarianten",
                                       "messgroesse": "Studie abgenommen",
                                       "prioritaet": "Muss"}}]},
                {"op": "neu", "inhalt": "Der Auftraggeber braucht etwa 6 Personentage",
                 "art": "schaetzung", "quelle": "wortlaut", "thema": "Aufwand AG",
                 "ziele": [{"abschnitt": "personalaufwand",
                            "felder": {"rolle": "AG", "aufwand": "6"}}]},
            ]},
            "frage": "Wer muss während der Initialisierung worüber informiert werden?",
        },
    ],
}

FAELLE = [ABLOESUNG]


# ---- Drehbuch-Modell ---------------------------------------------------------- #

import json as _json
import re as _re


class DrehbuchModell:
    """Bedient einen Fall Schritt für Schritt – über dieselbe Schnittstelle wie
    der echte Modell-Client (`complete(system, messages, max_tokens)`).

    Quellen für RAG-Themen werden aus den TATSÄCHLICH gezeigten Passagen
    gewählt («@migration» -> Chunks, deren Auszug «Migration» enthält). Ein
    Thema ohne passende Passage bekommt keine Quelle und wird vom Vertrag
    verworfen – genau wie bei einem echten Modell.
    """

    def __init__(self, fall):
        self.fall = fall
        self.schritt = -1
        self.aufrufe = []

    def _aktuell(self):
        return self.fall["schritte"][max(self.schritt, 0)]

    def complete(self, system, messages, max_tokens=1024, **kw):
        inhalt = messages[-1]["content"] if messages else ""
        if "ÄNDERUNGEN am Stand" in system:
            self.schritt += 1
            self.aufrufe.append("aussagen")
            return _json.dumps(self._aktuell()["aussagen"], ensure_ascii=False)
        if "THEMENKANDIDATEN" in system:
            self.aufrufe.append("themen")
            vorlage = self._aktuell().get("themen") or {"themen": []}
            passagen = _json.loads(inhalt.split("PASSAGEN (Daten):", 1)[1])
            themen = []
            for t in vorlage["themen"]:
                t = dict(t)
                wort = {"@migration": "migration", "@methode": "voranalyse"}.get(t.get("quellen"), "")
                t["quellen"] = [p["chunk_id"] for p in passagen if wort and wort in p["auszug"].lower()]
                themen.append(t)
            return _json.dumps({"themen": themen}, ensure_ascii=False)
        if "WAS als Nächstes zu klären ist" in system:
            self.aufrufe.append("frage")
            return _json.dumps({"frage": self._aktuell().get("frage") or "Was ist Dir noch wichtig?"},
                               ensure_ascii=False)
        if "Kapitel «Ausgangslage»" in system:
            self.aufrufe.append("ausgangslage")
            saetze, verwendet = [], []
            for zeile in inhalt.split("\n"):
                m = _re.match(r"(A-\d{4}): (.*?)(?: \[(.*)\])?$", zeile.strip())
                if not m:
                    continue
                verwendet.append(m.group(1))
                satz = m.group(2).rstrip(".")
                if m.group(3) and "unbestätigt" in m.group(3):
                    satz = f"Nach bisherigem, noch nicht bestätigtem Kenntnisstand gilt: {satz}"
                saetze.append(satz + ".")
            return _json.dumps({"text": " ".join(saetze), "verwendet": verwendet}, ensure_ascii=False)
        return "{}"


class WortEmbedder:
    """Deterministische Wortzähl-Vektoren – nur für synthetische Läufe."""
    available = True
    model = "synthetisch-wort-v1"
    _WORTE = ["migration", "schnittstelle", "datenbestand", "ablösung", "fachanwendung",
              "grundbuch", "bewilligung", "voranalyse", "projektauftrag", "gesuch", "support"]

    def _v(self, t):
        t = (t or "").lower()
        return [float(t.count(w)) for w in self._WORTE] + [0.5]

    def embed(self, texte, input_type="document"):
        return [self._v(t) for t in ([texte] if isinstance(texte, str) else texte)]

    def embed_one(self, text, input_type="query"):
        return self._v(text)
