"""Nur-Lese-Sicht auf das im PIA erfasste Projektwissen.

Liest den PIA-Output (answers) und die querschnittlichen Fakten (Ebene/Kanton),
verändert aber NICHTS am PIA. Grundlage für das Seeding der weiteren Ergebnisse.
"""


class Projektwissen:
    def __init__(self, pia_answers=None, metadata=None, ebene=None, kanton=None):
        self.pia = pia_answers or {}
        self.metadata = metadata or {}
        self.ebene = ebene
        self.kanton = kanton

    def _extracted(self, sid):
        entry = self.pia.get(sid)
        return entry.get("extracted") if isinstance(entry, dict) else None

    # --- Freitext-/Listen-Zugriffe --------------------------------------- #
    def ausgangslage_text(self):
        ausg = self._extracted("ausgangslage")
        if isinstance(ausg, dict):
            return (ausg.get("text") or "").strip()
        return ""

    def ziele(self):
        z = self._extracted("ziele")
        return z if isinstance(z, list) else []

    def referenzierte(self):
        r = self._extracted("referenzierte_dokumente")
        return [x for x in r if isinstance(x, dict)] if isinstance(r, list) else []

    def mitgeltende(self):
        m = self._extracted("mitgeltende_unterlagen")
        return [x for x in m if isinstance(x, dict)] if isinstance(m, list) else []

    def rahmenbedingungen(self):
        rb = self._extracted("rahmenbedingungen")
        return [x for x in rb if isinstance(x, dict)] if isinstance(rb, list) else []

    def definitionen(self):
        d = self._extracted("definitionen")
        return [x for x in d if isinstance(x, dict)] if isinstance(d, list) else []

    def ziel_beschreibungen(self):
        """Die geplanten Tätigkeiten des Projekts (Ziel-Beschreibungen) – Grundlage der
        Rechtsgrundlagen-Prüfung: existiert je Ziel eine Rechtsgrundlage?"""
        return [str(z.get("beschreibung", "")).strip()
                for z in self.ziele() if isinstance(z, dict) and str(z.get("beschreibung", "")).strip()]

    def genannte_rechtsgrundlagen(self):
        """Namen der im PIA genannten Gesetze/Vorgaben (aus Referenzierten/Mitgeltenden).
        Dient als ehrlicher Ausgangspunkt für 'Bestehende Rechtsgrundlagen' – ohne
        erfundene Fundstellen."""
        namen = []
        for r in self.referenzierte() + self.mitgeltende():
            name = str(r.get("name", "")).strip()
            if name and name not in namen:
                namen.append(name)
        return namen
