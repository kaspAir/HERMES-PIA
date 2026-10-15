"""Synthetischer Erfahrungskorpus für Tests mit echten Embeddings (dev).

Erfundene Vorhaben im Stil früherer Aufträge nach HERMES 5.1 – keine realen
Projekte, Organisationen oder Personen. Sie sind deshalb ausdrücklich zur
externen Verarbeitung geeignet (Entscheid vom 15.10.2026: Direktzugang auf dev
nur für synthetische, geeignet öffentliche oder freigegebene Daten).

Bewusst enthalten:
- projektfachliche Erfahrungen, die als Klärungsthema für eine Initialisierung
  taugen (Migration, Schnittstellen, Verfügbarkeit, Personalvertretung …),
- HERMES-5.1-Methodenaussagen («Projektauftrag», «Voranalyse», «Phasenbericht
  der Initialisierung»), an denen die Versionsgrenze greifen muss,
- Beträge, die nicht als aktuelle Fakten übernommen werden dürfen.
"""

METHODENVERSION = "HERMES 5.1"
HERKUNFT = "synthetisch erstellt (HERMES PIA, 15.10.2026) – keine realen Projekte"

DOKUMENTE = [
    {"projekt": "Synthetik-01 Ablösung Registeranwendung",
     "text": """1 Ausgangslage
Die Fachanwendung für das Personenregister des Beispielamts war zwölf Jahre im Betrieb. Der Hersteller kündigte die Wartung an. Im Projektauftrag wurde die Ablösung innerhalb von achtzehn Monaten vorgesehen.
2 Erkenntnisse
Die Migration der Datenbestände wurde deutlich unterschätzt. Rund ein Drittel der Datensätze war unvollständig oder doppelt erfasst. Die Bereinigung band zwei Fachpersonen über ein halbes Jahr. Die Mehrkosten betrugen CHF 380'000.
3 Empfehlung
Datenbestände früh auf Qualität und Umfang untersuchen, bevor über eine Lösung entschieden wird. Die Untersuchung gehört in die erste Phase, nicht in die Realisierung."""},
    {"projekt": "Synthetik-02 Ersatz Bewilligungssystem",
     "text": """1 Ausgangslage
Das Bewilligungssystem der Beispielstadt hatte Schnittstellen zum Grundbuch, zum Gebäuderegister und zur Finanzbuchhaltung. Keine davon war dokumentiert.
2 Erkenntnisse
Die Schnittstellen waren der grösste Unsicherheitsfaktor. Zwei Schnittstellen mussten neu entwickelt werden, weil die Gegenstellen ihre Formate inzwischen geändert hatten. Die Einführung verzögerte sich um vier Monate.
3 Empfehlung
Schnittstellen und ihre Verantwortlichen früh erheben und mit den Gegenstellen abstimmen."""},
    {"projekt": "Synthetik-03 Zusammenlegung Schalterdienste",
     "text": """1 Ausgangslage
Drei Schalterdienste der Beispielgemeinde sollten an einem Standort zusammengeführt werden. Der Gemeinderat hatte den Grundsatzentscheid gefällt.
2 Erkenntnisse
Die Personalvertretung wurde erst nach dem Konzept einbezogen. Daraus entstand Widerstand, der die Umsetzung um ein halbes Jahr verzögerte. Unklare Rollen am gemeinsamen Schalter führten zu Doppelarbeit.
3 Empfehlung
Personalvertretung und Mitarbeitende von Beginn an einbeziehen. Rollen und Abläufe am gemeinsamen Schalter früh klären."""},
    {"projekt": "Synthetik-04 Digitale Gesuchseingabe",
     "text": """1 Ausgangslage
Gesuche wurden auf Papier eingereicht und von Hand erfasst. Ein Onlineportal sollte die Eingabe digitalisieren.
2 Erkenntnisse
Die Fachleute der Bewilligungsabteilung waren in der Hochsaison kaum verfügbar. Workshops mussten mehrfach verschoben werden. Die Anforderungen blieben dadurch lange unvollständig.
3 Empfehlung
Verfügbarkeit der Fachleute vor dem Start verbindlich planen und saisonale Spitzen berücksichtigen."""},
    {"projekt": "Synthetik-05 Erneuerung Fallführung",
     "text": """1 Ausgangslage
Die Fallführung im Sozialdienst des Beispielkantons sollte erneuert werden. Mehrere Lösungen waren auf dem Markt.
2 Vorgehen nach HERMES 5.1
Nach der Voranalyse folgte der Projektauftrag. Die Voranalyse war zwingend vor dem Projektauftrag abzuschliessen. Der Phasenbericht der Initialisierung wurde dem Projektausschuss vorgelegt.
3 Erkenntnisse
Die Varianten wurden zu früh auf ein Produkt eingeengt. Eine echte Variantenbewertung fand nicht statt."""},
    {"projekt": "Synthetik-06 Archivlösung Akten",
     "text": """1 Ausgangslage
Elektronische Akten mussten langfristig archiviert werden. Die Anforderungen des Staatsarchivs waren nicht bekannt.
2 Erkenntnisse
Die Archivierungsanforderungen und die rechtlichen Aufbewahrungsfristen wurden erst spät geklärt. Ein Teil der Lösung musste umgebaut werden.
3 Empfehlung
Rechtsgrundlagen und Aufbewahrungsfristen früh mit den zuständigen Stellen klären."""},
    {"projekt": "Synthetik-07 Beschaffung Plattform",
     "text": """1 Ausgangslage
Für eine neue Fachplattform war eine öffentliche Beschaffung nötig. Der Zeitplan ging von einer Vergabe innerhalb von drei Monaten aus.
2 Erkenntnisse
Die Beschaffung dauerte neun Monate, einschliesslich einer Beschwerde gegen den Zuschlag. Die Pflichtenhefte waren zu wenig präzise.
3 Empfehlung
Die Beschaffungsart und ihren realistischen Zeitbedarf früh klären und die Anforderungen vor der Ausschreibung reif machen."""},
    {"projekt": "Synthetik-08 Informationssicherheit Fachanwendung",
     "text": """1 Ausgangslage
Eine Fachanwendung verarbeitete besonders schützenswerte Personendaten. Der Schutzbedarf war nicht erhoben.
2 Erkenntnisse
Die Schutzbedarfsanalyse wurde erst nach der Lösungswahl erstellt. Die gewählte Cloud-Lösung erfüllte die Anforderungen nicht und musste ersetzt werden.
3 Empfehlung
Den Schutzbedarf vor der Lösungswahl erheben."""},
    {"projekt": "Synthetik-09 Organisationsentwicklung Amt",
     "text": """1 Ausgangslage
Ein Amt sollte neu organisiert werden. Ziel war eine klarere Aufgabenteilung zwischen zwei Abteilungen.
2 Erkenntnisse
Die Ziele blieben lange vage. Erst messbare Ziele mit Messgrössen schufen eine gemeinsame Grundlage für Entscheide. Die Kommunikation an die Mitarbeitenden war zu selten.
3 Empfehlung
Ziele mit Messgrössen festlegen und regelmässig, mindestens monatlich, informieren."""},
    {"projekt": "Synthetik-10 Betrieb und Übergabe",
     "text": """1 Ausgangslage
Eine neue Anwendung sollte dem Betrieb übergeben werden. Die Betriebsorganisation war im Projekt nicht vertreten.
2 Erkenntnisse
Der Betrieb kannte die Anwendung bei der Einführung kaum. Betriebskosten waren nicht budgetiert und überstiegen die Erwartung um CHF 120'000 pro Jahr.
3 Empfehlung
Die Betriebsorganisation früh einbeziehen und die Betriebskosten von Beginn an schätzen."""},
]
