"""Laedt und stellt das Methodenmodell (z.B. HERMES PIA) bereit."""
from app.shared.config_loader import load_method


class MethodService:
    def __init__(self, methods_dir):
        self.methods_dir = methods_dir
        self._cache = {}

    def get(self, method_id):
        if method_id not in self._cache:
            self._cache[method_id] = load_method(self.methods_dir, method_id)
        return self._cache[method_id]

    def sections(self, method_id):
        return self.get(method_id).get("sections", [])

    def gap_check_sections(self, method_id):
        """Abschnitte, fuer die HERMES PIA aktiv nachfragt."""
        return [s for s in self.sections(method_id) if s.get("gap_check")]
