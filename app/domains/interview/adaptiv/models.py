"""Der gemeinsame Projektzustand des adaptiven Interviews.

Vier getrennte Dinge, vier Tabellen – wer sie zusammenlegt, kann später nicht
mehr zeigen, was gesagt, was verstanden, was vorgeschlagen und was strittig war:

- PiaNachricht  Gesprächsverlauf. Originalbeiträge werden nie umgeschrieben.
- PiaAussage    strukturierte Projektangaben mit stabiler ID. Herkunft,
                Aussageart, Bestätigung und Beleglage sind GETRENNTE Merkmale:
                eine bestätigte Benutzerangabe ist nicht extern belegt, eine
                bestätigte Schätzung bleibt eine Schätzung.
- PiaKonflikt   erkannte Widersprüche. Sie werden angezeigt, nicht willkürlich
                aufgelöst.
- PiaRagThema   Themenkandidaten aus dem Erfahrungskorpus, mit Übertragungs-
                status und den tatsächlich verwendeten Fundstellen.

Dazu PiaRueckmeldung: Korrekturen und Hinweise des Benutzers als Grundlage
der kontrollierten Verbesserung – nie als automatische Regeländerung.

Alles additiv: bestehende Sessions und Tabellen bleiben unverändert.
"""
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text

from app.shared.database import Base

# ---- Kontrollierte Werte ---------------------------------------------------- #

# Herkunft: WER die Angabe beigebracht hat.
HERKUNFT = ("benutzer", "system", "rag", "altbestand", "vorlage")

# Aussageart: WAS für eine Angabe es ist (Auftrag Abschnitt 7).
ARTEN = (
    "benutzerangabe",   # vom Benutzer so gesagt
    "belegt",           # mit hinterlegtem Beleg (nie vom Modell gesetzt)
    "annahme",          # vom Benutzer als unsicher/unbestätigt genannt
    "schaetzung",       # Grösse mit Unsicherheit
    "interpretation",   # vom System gefolgert, nicht wörtlich gesagt
    "systemvorschlag",  # vom System vorgeschlagen
    "unbekannt",        # ausdrücklich nicht bekannt / zurückgestellt
)

STATUS = ("aktiv", "ersetzt", "verworfen")

# Bezug: Initialisierung oder späteres Gesamtvorhaben (Auftrag Abschnitte 2, 7).
BEZUG = ("initialisierung", "gesamtvorhaben", "unklar")

# Entscheid-Charakter einer Lösungsaussage (Auftrag Abschnitt 5, AT03).
ENTSCHEID = ("idee", "entscheid", "unklar")

# Übertragbarkeit eines RAG-Themas (Auftrag Abschnitt 6.2).
UEBERTRAGBARKEIT = ("nutzbar", "eingeschraenkt", "methodisch_klaeren", "nicht_uebernehmen")

# Interne Bearbeitungszustände – NICHT Prüfung, Abnahme oder Freigabe.
PIA_STATUS = ("laufend", "entwurf_offen", "bereit_zur_pruefung", "fertiggestellt")


class PiaNachricht(Base):
    __tablename__ = "pia_nachricht"

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, nullable=False, index=True)
    rolle = Column(String(12), nullable=False)          # benutzer | system
    # beitrag | frage | korrektur | hinweis | abschluss
    art = Column(String(20), nullable=False, default="beitrag")
    text = Column(Text, nullable=False)
    # Nur bei Systemnachrichten: die gewählte Gesprächsaktion und ihr knapper
    # Entscheidungshinweis (offener Punkt, Relevanz, Konflikt oder RAG-Thema).
    # KEIN Modell-Denkprotokoll.
    aktion = Column(String(30), nullable=True)
    begruendung = Column(Text, nullable=True)
    bezug_json = Column(Text, nullable=True)            # Aussage-/Themen-/Konflikt-IDs
    # Idempotenz: dieselbe Anfrage-ID (Doppelklick, Wiederholung) wird nur
    # einmal verarbeitet.
    anfrage_id = Column(String(64), nullable=True, index=True)
    # eingegangen -> verarbeitet | fehler
    status = Column(String(20), nullable=False, default="eingegangen")
    fehler = Column(Text, nullable=True)
    revision = Column(Integer, nullable=True)           # Zustand nach Verarbeitung
    versionen_json = Column(Text, nullable=True)        # Prompt-/Regel-/Vertragsversionen
    erstellt_am = Column(DateTime, default=datetime.utcnow)


class PiaAussage(Base):
    __tablename__ = "pia_aussage"

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, nullable=False, index=True)
    schluessel = Column(String(12), nullable=False)     # stabil, z.B. "A-0007"
    inhalt = Column(Text, nullable=False)
    thema = Column(String(120), nullable=True)
    art = Column(String(20), nullable=False)
    herkunft = Column(String(20), nullable=False)
    bestaetigt = Column(Boolean, nullable=False, default=False)
    beleg = Column(Text, nullable=True)                 # genannte Quelle; nie erfunden
    bezug = Column(String(20), nullable=False, default="initialisierung")
    entscheid = Column(String(10), nullable=True)
    zurueckgestellt = Column(Boolean, nullable=False, default=False)
    # [{"abschnitt": "risiken", "felder": {"beschreibung": "…", "ew": "Hoch = 3"}}]
    ziele_json = Column(Text, nullable=False, default="[]")
    status = Column(String(12), nullable=False, default="aktiv")
    ersetzt_durch = Column(String(12), nullable=True)
    ersetzt = Column(String(12), nullable=True)
    nachricht_id = Column(Integer, nullable=True)       # Originalbeitrag
    thema_id = Column(Integer, nullable=True)           # RAG-Thema, aus dem sie entstand
    revision_neu = Column(Integer, nullable=True)
    revision_geaendert = Column(Integer, nullable=True)
    erstellt_am = Column(DateTime, default=datetime.utcnow)
    geaendert_am = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PiaKonflikt(Base):
    __tablename__ = "pia_konflikt"

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, nullable=False, index=True)
    aussagen_json = Column(Text, nullable=False)        # ["A-0003", "A-0011"]
    beschreibung = Column(Text, nullable=False)
    # deterministisch erkannt (z.B. PT-Summe) oder aus dem Gespräch gemeldet
    quelle = Column(String(20), nullable=False, default="gespraech")
    status = Column(String(12), nullable=False, default="offen")   # offen | geloest
    loesung = Column(Text, nullable=True)
    revision_erkannt = Column(Integer, nullable=True)
    revision_geloest = Column(Integer, nullable=True)
    erstellt_am = Column(DateTime, default=datetime.utcnow)


class PiaRagThema(Base):
    __tablename__ = "pia_rag_thema"

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, nullable=False, index=True)
    thema = Column(String(200), nullable=False)
    frage_ansatz = Column(Text, nullable=True)
    uebertragbarkeit = Column(String(24), nullable=False)
    regel_id = Column(String(20), nullable=True)
    regel_version = Column(String(20), nullable=True)
    begruendung = Column(Text, nullable=True)
    pia_ziele_json = Column(Text, nullable=False, default="[]")
    offene_aspekte = Column(Text, nullable=True)
    # Tatsächlich verwendete Fundstellen: Chunk-ID, Projekt, Abschnitt,
    # Auszug, Dokument-Hash, Methodenversion samt Herkunft, Korpusversion.
    quellen_json = Column(Text, nullable=False, default="[]")
    n_projekte = Column(Integer, nullable=False, default=0)
    # kandidat | gefragt | bestaetigt | verworfen | erledigt
    status = Column(String(12), nullable=False, default="kandidat")
    revision = Column(Integer, nullable=True)
    erstellt_am = Column(DateTime, default=datetime.utcnow)


class PiaRueckmeldung(Base):
    __tablename__ = "pia_rueckmeldung"

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, nullable=False, index=True)
    org_id = Column(Integer, nullable=True, index=True)
    # falsch_verstanden | falsch_zugeordnet | schon_beantwortet | rag_unpassend
    # | frage_unklar | vorschlag_verworfen | korrektur
    art = Column(String(30), nullable=False)
    bezug = Column(String(40), nullable=True)           # Aussage-, Themen- oder Nachricht-ID
    # Minimal nötiger Kontext – keine ganzen Gespräche.
    kontext_json = Column(Text, nullable=True)
    versionen_json = Column(Text, nullable=True)
    # Nur ausdrücklich freigegebene Rückmeldungen fliessen in eine Auswertung.
    freigegeben = Column(Boolean, nullable=False, default=False)
    erstellt_am = Column(DateTime, default=datetime.utcnow)
