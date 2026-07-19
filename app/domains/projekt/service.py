"""Anwendungslogik der Projektstruktur.

Hält die Struktur (Projekt > Phase > Modul > Ergebnis + Meilensteine) und kennt
den Referenz-Katalog. Bewusst ohne Kenntnis der Interview-/PIA-Domäne – die
Verknüpfung der `InterviewSession` an ihren Ergebnis-Knoten setzt der Aufrufer
(über `ergebnis_id`). So bleibt die Container-Domäne von ihren Inhalten entkoppelt.
"""
from app.domains.projekt.models import (
    Ergebnis,
    ErgebnisDokument,
    Kostensatz,
    Meilenstein,
    MethodenVorlage,
    Modul,
    Phase,
    PraesentationsVorlage,
    Projekt,
)
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

    def delete_projekt(self, projekt_id):
        """Löscht ein Projekt samt seiner Struktur (Phasen/Module/Ergebnisse/
        Meilensteine). Verknüpfte PIA-Sessions löscht der Aufrufer zuvor."""
        db = SessionLocal()
        projekt = db.get(Projekt, int(projekt_id))
        if projekt is None:
            return False
        phase_ids = [ph.id for ph in db.query(Phase).filter(
            Phase.projekt_id == projekt.id).all()]
        if phase_ids:
            modul_ids = [m.id for m in db.query(Modul).filter(
                Modul.phase_id.in_(phase_ids)).all()]
            if modul_ids:
                ergebnis_ids = [e.id for e in db.query(Ergebnis).filter(
                    Ergebnis.modul_id.in_(modul_ids)).all()]
                if ergebnis_ids:
                    db.query(ErgebnisDokument).filter(
                        ErgebnisDokument.ergebnis_id.in_(ergebnis_ids)).delete(
                        synchronize_session=False)
                db.query(Ergebnis).filter(Ergebnis.modul_id.in_(modul_ids)).delete(
                    synchronize_session=False)
                db.query(Modul).filter(Modul.id.in_(modul_ids)).delete(
                    synchronize_session=False)
            db.query(Meilenstein).filter(Meilenstein.phase_id.in_(phase_ids)).delete(
                synchronize_session=False)
            db.query(Phase).filter(Phase.id.in_(phase_ids)).delete(
                synchronize_session=False)
        db.query(PraesentationsVorlage).filter(
            PraesentationsVorlage.projekt_id == projekt.id).delete(
            synchronize_session=False)
        db.query(MethodenVorlage).filter(
            MethodenVorlage.projekt_id == projekt.id).delete(
            synchronize_session=False)
        db.delete(projekt)
        db.commit()
        return True

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

    def projekt_for_ergebnis(self, ergebnis_id):
        """Findet das Projekt, zu dem ein Ergebnis-Knoten gehört (für Breadcrumbs)."""
        if not ergebnis_id:
            return None
        return SessionLocal().query(Projekt).join(
            Phase, Phase.projekt_id == Projekt.id
        ).join(Modul, Modul.phase_id == Phase.id).join(
            Ergebnis, Ergebnis.modul_id == Modul.id
        ).filter(Ergebnis.id == int(ergebnis_id)).first()

    # ------------------------------------------------------------------ #
    # Dokumente am Ergebnis (z.B. freigabebereiter PIA)                    #
    # ------------------------------------------------------------------ #

    def add_dokument(self, ergebnis_id, filename, data, mimetype=None,
                     art="freigabe", uploaded_by=None):
        """Hängt eine hochgeladene Datei an ein Ergebnis. Bei art='freigabe'
        wechselt der Ergebnis-Status auf 'zur Freigabe'."""
        db = SessionLocal()
        ergebnis = db.get(Ergebnis, int(ergebnis_id))
        if ergebnis is None:
            return None
        dok = ErgebnisDokument(
            ergebnis_id=ergebnis.id, art=art, filename=filename,
            mimetype=mimetype, size=len(data or b""), data=data,
            uploaded_by=uploaded_by,
        )
        db.add(dok)
        if art == "freigabe":
            ergebnis.status = "zur Freigabe"
        db.commit()
        db.refresh(dok)
        return dok

    def get_dokument(self, dokument_id):
        return SessionLocal().get(ErgebnisDokument, int(dokument_id))

    def dokumente_for_ergebnis(self, ergebnis_id, art=None):
        q = SessionLocal().query(ErgebnisDokument).filter(
            ErgebnisDokument.ergebnis_id == int(ergebnis_id))
        if art:
            q = q.filter(ErgebnisDokument.art == art)
        return q.order_by(ErgebnisDokument.created_at.desc()).all()

    def latest_dokument(self, ergebnis_id, art="freigabe"):
        docs = self.dokumente_for_ergebnis(ergebnis_id, art=art)
        return docs[0] if docs else None

    # ------------------------------------------------------------------ #
    # Präsentationsvorlagen (Projekt-Vorlage schlägt Org-Vorlage)          #
    # ------------------------------------------------------------------ #

    def add_vorlage(self, filename, data, org_id=None, projekt_id=None, uploaded_by=None):
        db = SessionLocal()
        v = PraesentationsVorlage(
            org_id=org_id, projekt_id=projekt_id, filename=filename,
            size=len(data or b""), data=data, uploaded_by=uploaded_by,
        )
        db.add(v)
        db.commit()
        db.refresh(v)
        return v

    def org_vorlage(self, org_id):
        """Neueste PMO-Vorlage der Organisationseinheit (projektunabhängig)."""
        return SessionLocal().query(PraesentationsVorlage).filter(
            PraesentationsVorlage.org_id == org_id,
            PraesentationsVorlage.projekt_id.is_(None),
        ).order_by(PraesentationsVorlage.created_at.desc()).first()

    def projekt_vorlage(self, projekt_id):
        """Neueste projektspezifische Vorlage (übersteuert die PMO-Vorlage)."""
        return SessionLocal().query(PraesentationsVorlage).filter(
            PraesentationsVorlage.projekt_id == int(projekt_id)
        ).order_by(PraesentationsVorlage.created_at.desc()).first()

    def resolve_vorlage(self, projekt):
        """Massgebliche Vorlage: Projekt-Vorlage übersteuert die PMO-Vorlage der
        Organisationseinheit; sonst None (dann leere Standard-Präsentation)."""
        return self.projekt_vorlage(projekt.id) or self.org_vorlage(projekt.org_id)

    # ------------------------------------------------------------------ #
    # Methoden-/Word-Vorlagen (Projekt-Vorlage schlägt Org-Vorlage)        #
    # ------------------------------------------------------------------ #

    def add_methoden_vorlage(self, filename, data, org_id=None, projekt_id=None,
                             uploaded_by=None):
        db = SessionLocal()
        v = MethodenVorlage(
            org_id=org_id, projekt_id=projekt_id, filename=filename,
            size=len(data or b""), data=data, uploaded_by=uploaded_by,
        )
        db.add(v)
        db.commit()
        db.refresh(v)
        return v

    def org_methoden_vorlage(self, org_id):
        """Neueste PMO-Wortvorlage der Organisationseinheit (projektunabhängig)."""
        if not org_id:
            return None
        return SessionLocal().query(MethodenVorlage).filter(
            MethodenVorlage.org_id == org_id,
            MethodenVorlage.projekt_id.is_(None),
        ).order_by(MethodenVorlage.created_at.desc()).first()

    def projekt_methoden_vorlage(self, projekt_id):
        """Neueste projektspezifische Wortvorlage (übersteuert die PMO-Vorlage)."""
        return SessionLocal().query(MethodenVorlage).filter(
            MethodenVorlage.projekt_id == int(projekt_id)
        ).order_by(MethodenVorlage.created_at.desc()).first()

    def resolve_methoden_vorlage(self, projekt):
        """Massgebliche Wortvorlage: Projekt übersteuert Org; sonst None
        (dann treibt die kanonische HERMES-Struktur das Interview)."""
        return (self.projekt_methoden_vorlage(projekt.id)
                or self.org_methoden_vorlage(projekt.org_id))

    # ------------------------------------------------------------------ #
    # Kostensätze (Projekt übersteuert Org; Einheit Stunde/Tag)            #
    # ------------------------------------------------------------------ #

    # Standard-Tagessätze (CHF/PT), wenn nichts hinterlegt ist – extern teurer.
    DEFAULT_TARIFE = {"intern": 1200, "extern": 1800}

    def set_kostensatz(self, satz_intern, satz_extern, einheit="tag",
                       stunden_pro_tag=8, org_id=None, projekt_id=None):
        """Legt den Kostensatz einer Ebene an oder aktualisiert ihn (ein Eintrag je
        Org bzw. Projekt)."""
        db = SessionLocal()
        pid = int(projekt_id) if projekt_id else None
        q = db.query(Kostensatz)
        q = q.filter(Kostensatz.projekt_id == pid) if pid else \
            q.filter(Kostensatz.org_id == org_id, Kostensatz.projekt_id.is_(None))
        row = q.first()
        if row is None:
            row = Kostensatz(org_id=org_id, projekt_id=pid)
            db.add(row)
        row.satz_intern = int(satz_intern) if satz_intern not in (None, "") else None
        row.satz_extern = int(satz_extern) if satz_extern not in (None, "") else None
        row.einheit = "stunde" if str(einheit).lower().startswith("stund") else "tag"
        row.stunden_pro_tag = int(stunden_pro_tag) if stunden_pro_tag else 8
        db.commit()
        db.refresh(row)
        return row

    def org_kostensatz(self, org_id):
        if not org_id:
            return None
        return SessionLocal().query(Kostensatz).filter(
            Kostensatz.org_id == org_id, Kostensatz.projekt_id.is_(None),
        ).order_by(Kostensatz.updated_at.desc()).first()

    def projekt_kostensatz(self, projekt_id):
        if not projekt_id:
            return None
        return SessionLocal().query(Kostensatz).filter(
            Kostensatz.projekt_id == int(projekt_id)
        ).order_by(Kostensatz.updated_at.desc()).first()

    def effective_tarife(self, org_id=None, projekt_id=None):
        """Massgebliche Tagessätze (CHF/PT) für die Kostenberechnung: Projekt
        übersteuert Org, sonst Standard. Stundensätze werden auf den Tag umgerechnet."""
        row = self.projekt_kostensatz(projekt_id) or self.org_kostensatz(org_id)
        if not row or not (row.satz_intern or row.satz_extern):
            return dict(self.DEFAULT_TARIFE)
        faktor = (row.stunden_pro_tag or 8) if row.einheit == "stunde" else 1

        def tag(v, fallback):
            return int(v) * faktor if v else fallback
        return {
            "intern": tag(row.satz_intern, self.DEFAULT_TARIFE["intern"]),
            "extern": tag(row.satz_extern, self.DEFAULT_TARIFE["extern"]),
        }

    def get_methoden_vorlage(self, vorlage_id):
        return SessionLocal().get(MethodenVorlage, int(vorlage_id))

    def set_methoden_mapping(self, vorlage_id, mapping):
        """Speichert die bestätigte Kapitel-Zuordnung (Liste) als JSON."""
        import json
        db = SessionLocal()
        v = db.get(MethodenVorlage, int(vorlage_id))
        if v is None:
            return None
        v.mapping_json = json.dumps(mapping, ensure_ascii=False)
        db.commit()
        return v

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
