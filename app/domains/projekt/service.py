"""Anwendungslogik der Projektstruktur.

Hält die Struktur (Projekt > Phase > Modul > Ergebnis + Meilensteine) und kennt
den Referenz-Katalog. Bewusst ohne Kenntnis der Interview-/PIA-Domäne – die
Verknüpfung der `InterviewSession` an ihren Ergebnis-Knoten setzt der Aufrufer
(über `ergebnis_id`). So bleibt die Container-Domäne von ihren Inhalten entkoppelt.
"""
from app.domains.projekt.models import Ergebnis, Meilenstein, Modul, Phase, Projekt
from app.domains.projekt.reference import (
    ERG_PIA,
    ERGEBNISTYPEN,
    INITIALISIERUNG,
)
from app.shared.database import SessionLocal


class ProjektService:

    # ------------------------------------------------------------------ #
    # Anlegen                                                             #
    # ------------------------------------------------------------------ #

    def create_projekt(self, org_id=None, name="Projekt", projektnummer=None,
                       auftraggeber=None, verwaltungseinheit=None, geschaeftsbereich=None,
                       innenauftragsnummer=None, start_datum=None, created_by=None):
        """Legt ein Projekt an und instanziiert die Phase Initialisierung
        (Module + Meilensteine) aus der Vorlage."""
        db = SessionLocal()
        projekt = self._new_projekt(
            db, org_id=org_id, name=name or "Projekt", projektnummer=projektnummer,
            auftraggeber=auftraggeber, verwaltungseinheit=verwaltungseinheit,
            geschaeftsbereich=geschaeftsbereich, innenauftragsnummer=innenauftragsnummer,
            start_datum=start_datum, created_by=created_by,
        )
        self._instantiate_initialisierung(db, projekt)
        db.commit()
        db.refresh(projekt)
        return projekt

    def add_ergebnis(self, projekt_id, ergebnistyp, titel=None, created_by=None):
        """Legt ein Ergebnis im laut Katalog zuständigen Modul des Projekts an."""
        db = SessionLocal()
        projekt = db.get(Projekt, int(projekt_id))
        if projekt is None:
            return None
        ergebnis = self._add_ergebnis(db, projekt, ergebnistyp, titel=titel,
                                      created_by=created_by)
        db.commit()
        db.refresh(ergebnis)
        return ergebnis

    def backfill_sessions(self, sessions):
        """Wrappt bestehende PIA-Sessions in die Projektstruktur (idempotent).

        Erwartet Objekte mit den PIA-Metadaten (project_name, org_id, …) und einem
        setzbaren `ergebnis_id`. Setzt die Verknüpfung und persistiert sie mit.
        Gibt die Anzahl neu eingewickelter Sessions zurück.
        """
        db = SessionLocal()
        count = 0
        for s in sessions:
            if getattr(s, "ergebnis_id", None):
                continue
            projekt = self._new_projekt(
                db, org_id=getattr(s, "org_id", None),
                name=getattr(s, "project_name", None) or "Projekt",
                projektnummer=getattr(s, "projektnummer", None),
                auftraggeber=getattr(s, "auftraggeber", None),
                verwaltungseinheit=getattr(s, "verwaltungseinheit", None),
                geschaeftsbereich=getattr(s, "geschaeftsbereich", None),
                innenauftragsnummer=getattr(s, "innenauftragsnummer", None),
                start_datum=getattr(s, "start_datum", None),
                created_by=getattr(s, "created_by", None),
            )
            self._instantiate_initialisierung(db, projekt)
            ergebnis = self._add_ergebnis(db, projekt, ERG_PIA,
                                          titel=getattr(s, "project_name", None),
                                          created_by=getattr(s, "created_by", None))
            s.ergebnis_id = ergebnis.id
            db.add(s)
            count += 1
        db.commit()
        return count

    # ------------------------------------------------------------------ #
    # Abfragen                                                            #
    # ------------------------------------------------------------------ #

    def get_projekt(self, projekt_id):
        return SessionLocal().get(Projekt, int(projekt_id))

    def projekte_for_org(self, org_id):
        return SessionLocal().query(Projekt).filter(
            Projekt.org_id == org_id
        ).order_by(Projekt.created_at.desc()).all()

    def phase_initialisierung(self, projekt_id):
        return SessionLocal().query(Phase).filter(
            Phase.projekt_id == int(projekt_id),
            Phase.code == INITIALISIERUNG["code"],
        ).first()

    def module(self, projekt_id):
        return SessionLocal().query(Modul).join(Phase, Modul.phase_id == Phase.id).filter(
            Phase.projekt_id == int(projekt_id)
        ).order_by(Modul.reihenfolge).all()

    def find_modul(self, projekt_id, modul_code):
        return SessionLocal().query(Modul).join(Phase, Modul.phase_id == Phase.id).filter(
            Phase.projekt_id == int(projekt_id), Modul.code == modul_code
        ).first()

    def meilensteine(self, projekt_id):
        return SessionLocal().query(Meilenstein).join(
            Phase, Meilenstein.phase_id == Phase.id
        ).filter(Phase.projekt_id == int(projekt_id)).order_by(Meilenstein.reihenfolge).all()

    def ergebnisse(self, projekt_id):
        return SessionLocal().query(Ergebnis).join(Modul, Ergebnis.modul_id == Modul.id).join(
            Phase, Modul.phase_id == Phase.id
        ).filter(Phase.projekt_id == int(projekt_id)).all()

    def ergebnisse_for_modul(self, modul_id):
        return SessionLocal().query(Ergebnis).filter(
            Ergebnis.modul_id == int(modul_id)
        ).order_by(Ergebnis.created_at).all()

    def structure(self, projekt):
        """Verschachtelte Sicht für die UI: Phase -> Module(+Ergebnisse) + Meilensteine."""
        phase = self.phase_initialisierung(projekt.id)
        if phase is None:
            return {"projekt": projekt, "phase": None, "module": [], "meilensteine": []}
        module = [
            {"modul": m, "ergebnisse": self.ergebnisse_for_modul(m.id)}
            for m in self.module(projekt.id)
        ]
        return {
            "projekt": projekt,
            "phase": phase,
            "module": module,
            "meilensteine": self.meilensteine(projekt.id),
        }

    # ------------------------------------------------------------------ #
    # Interna                                                             #
    # ------------------------------------------------------------------ #

    def _new_projekt(self, db, **meta):
        projekt = Projekt(**meta)
        db.add(projekt)
        db.flush()
        return projekt

    def _instantiate_initialisierung(self, db, projekt):
        tmpl = INITIALISIERUNG
        phase = Phase(projekt_id=projekt.id, code=tmpl["code"], name=tmpl["name"],
                      reihenfolge=0)
        db.add(phase)
        db.flush()
        for i, m in enumerate(tmpl["module"]):
            db.add(Modul(phase_id=phase.id, code=m["code"], name=m["name"], reihenfolge=i))
        for i, ms in enumerate(tmpl["meilensteine"]):
            db.add(Meilenstein(
                phase_id=phase.id, code=ms["code"], name=ms["name"],
                modul_code=ms.get("modul"), rolle=ms.get("rolle"),
                datum=projekt.start_datum if ms.get("ist_start") else None,
                ist_start=1 if ms.get("ist_start") else 0, reihenfolge=i,
            ))
        db.flush()
        return phase

    def _add_ergebnis(self, db, projekt, ergebnistyp, titel=None, created_by=None):
        info = ERGEBNISTYPEN.get(ergebnistyp, {})
        modul_code = info.get("modul")
        modul = db.query(Modul).join(Phase, Modul.phase_id == Phase.id).filter(
            Phase.projekt_id == projekt.id, Modul.code == modul_code
        ).first()
        if modul is None:
            raise ValueError(f"Kein Modul '{modul_code}' für Ergebnistyp '{ergebnistyp}'")
        ergebnis = Ergebnis(
            modul_id=modul.id, ergebnistyp=ergebnistyp,
            titel=titel or info.get("name") or ergebnistyp,
            aufgabe=info.get("aufgabe"), rolle=info.get("rolle"),
            created_by=created_by,
        )
        db.add(ergebnis)
        db.flush()
        return ergebnis
