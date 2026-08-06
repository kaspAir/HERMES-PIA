"""Ablage der Kopfdaten eines Projekts.

Die zwölf Angaben, die jedes HERMES-Dokument im Kopf trägt, standen bisher an
drei Stellen verteilt – im Projekt-Datensatz, in der Interview-Sitzung und im
hochgeladenen Auftrag – und wurden bei jedem Dokument neu zusammengerechnet.
Das hatte zwei Folgen, die beide gegen den Zustand sprachen:

* Die **Anrede** wurde bei jedem Herunterladen neu vom Sprachmodell geschätzt.
  Ein Modellaufruf für eine Antwort, die sich nie ändert – und der Name
  verliess das System jedes Mal aufs Neue.
* Eine **falsche Schätzung liess sich nicht richtigstellen.** Bei «Andrea»,
  «Kim» oder «Dominique» rät jedes Modell. Eine Vermutung, die man nicht
  korrigieren kann, ist schlimmer als eine Lücke.

Hier liegen sie einmal, bestätigt und änderbar. Damit daraus keine zweite
Wahrheit neben dem freigegebenen Auftrag wird, gibt es den Abgleich: weicht
ein hochgeladenes Dokument ab, wird gefragt – nicht still überschrieben und
nicht still ignoriert.
"""
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String

from app.shared.database import Base

# Die Felder, die den Kopf ausmachen. Eine Liste, damit Abgleich, Formular und
# Übernahme nicht auseinanderlaufen können.
FELDER = (
    "projektname", "projektnummer", "projektleiter", "auftraggeber",
    "verwaltungseinheit", "geschaeftsbereich", "innenauftragsnummer",
    "klassifizierung",
)

# Anreden als kontrolliertes Vokabular: weiblich, männlich, unbekannt.
# «Unbekannt» ist ein gültiger Wert – dann behält die Vorlage ihre Doppelform.
ANREDEN = {"w": "weiblich", "m": "männlich", "u": "unbekannt"}


class Kopfdaten(Base):
    """Ein Datensatz je Projekt – die Kopfangaben aller seiner Dokumente."""
    __tablename__ = "kopfdaten"

    id = Column(Integer, primary_key=True)
    projekt_id = Column(Integer, ForeignKey("projekt.id"), nullable=False,
                        index=True, unique=True)

    projektname = Column(String(200), nullable=True)
    projektnummer = Column(String(100), nullable=True)
    projektleiter = Column(String(200), nullable=True)
    projektleiter_anrede = Column(String(1), default="u")
    auftraggeber = Column(String(200), nullable=True)
    auftraggeber_anrede = Column(String(1), default="u")
    verwaltungseinheit = Column(String(200), nullable=True)
    geschaeftsbereich = Column(String(200), nullable=True)
    innenauftragsnummer = Column(String(100), nullable=True)
    klassifizierung = Column(String(60), default="Nicht klassifiziert")

    erstellt_am = Column(DateTime, default=datetime.utcnow)
    aktualisiert_am = Column(DateTime, default=datetime.utcnow,
                             onupdate=datetime.utcnow)
    aktualisiert_durch = Column(String(200), nullable=True)
