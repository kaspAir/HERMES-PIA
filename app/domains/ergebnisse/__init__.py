"""Ergebnis-Module der Phase Initialisierung (ausser dem PIA).

Bewusst getrennt vom PIA gehalten: jedes weitere Ergebnis (Rechtsgrundlagen-,
Schutzbedarfs-, Beschaffungsanalyse, Studie ...) ist ein eigenes Modul, das nur
über die stabile Infrastruktur (Generierung, Extraktion, Methoden) und einen
NUR-LESE-Zugriff auf das im PIA erfasste Projektwissen andockt. Der PIA-Code
selbst bleibt unangetastet.
"""
