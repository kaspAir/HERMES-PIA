"""Datenwege zu externen KI-Diensten – je Übermittlung ausdrücklich bestimmt.

HERMES PIA übermittelt Text an drei Arten externer Dienste:

  llm         Sprachmodell (Interview, Formulierung, Prüfung)
  embeddings  Vektoren für das RAG (Korpus beim Indexieren, Suchanfragen)
  stt         Spracherkennung (Diktat)

Für llm und embeddings gibt es drei Modi:

  schutzschicht  über eine vorgeschaltete Schutzschicht (Pseudonymisierung).
                 DAS ist die Integrationsstelle für das spätere Standardwerkzeug:
                 je Dienst eine anbieterkompatible Basis-URL
                 (SCHUTZSCHICHT_LLM_URL, SCHUTZSCHICHT_EMBEDDING_URL; beide
                 abgeleitet aus PSEUDO_BASIS_URL, wenn nicht einzeln gesetzt).
                 Welches Werkzeug dahinter steht, ist hier nicht festgelegt.
  direkt         ohne Schutzschicht direkt an den Anbieter – NUR, wenn das
                 ausdrücklich eingeschaltet ist UND ein Schlüssel vorliegt
                 (LLM: PSEUDO_UMGEHEN=1 + ANTHROPIC_API_KEY;
                  Embeddings: EMBEDDING_DIREKT=1 + VOYAGE_API_KEY).
  aus            kein Weg; die Funktion meldet sich als nicht verfügbar.

Regeln, die nicht verhandelbar sind:

- Ist eine Schutzschicht konfiguriert, gilt sie. Direktschalter sind dann
  WIRKUNGSLOS – für alle Wege – und das wird als Konflikt ausgewiesen.
- Fällt die Schutzschicht aus, gibt es einen Fehler, KEINEN Ausweichweg zum
  Anbieter (siehe embeddings.py und llm/client.py).
- Der Modus wird aus der Konfiguration beantwortet und so angezeigt, wie er
  ist: «direkt» heisst «ohne Pseudonymisierung», nicht «geschützt».
"""
SCHUTZSCHICHT = "schutzschicht"
DIREKT = "direkt"
AUS = "aus"

TEXT = {
    SCHUTZSCHICHT: "über die Schutzschicht",
    DIREKT: "DIREKT an den Anbieter – ohne Pseudonymisierung",
    AUS: "nicht verfügbar",
}


def _wert(cfg, schluessel):
    return str(cfg.get(schluessel) or "").strip()


def _schalter(cfg, schluessel):
    w = cfg.get(schluessel)
    return w is True or str(w or "").strip() in ("1", "true", "True", "ja")


def bestimme(cfg):
    """Die Datenwege aus einer Konfiguration (dict-artig, z.B. app.config)."""
    basis = _wert(cfg, "PSEUDO_BASIS_URL").rstrip("/")
    llm_url = _wert(cfg, "SCHUTZSCHICHT_LLM_URL") or (f"{basis}/anthropic" if basis else "")
    emb_url = _wert(cfg, "SCHUTZSCHICHT_EMBEDDING_URL") or (f"{basis}/voyage" if basis else "")
    schutz = bool(llm_url or emb_url)
    hinweise = []

    llm_direkt_verlangt = _schalter(cfg, "PSEUDO_UMGEHEN")
    emb_direkt_verlangt = _schalter(cfg, "EMBEDDING_DIREKT")
    if schutz and (llm_direkt_verlangt or emb_direkt_verlangt):
        hinweise.append("Eine Schutzschicht ist konfiguriert – die Direktschalter "
                        "(PSEUDO_UMGEHEN / EMBEDDING_DIREKT) sind deshalb wirkungslos.")

    def weg(url, verlangt, schluessel_name, schalter_name):
        if schutz:
            if url:
                return {"modus": SCHUTZSCHICHT, "url": url, "schluessel": None}
            return {"modus": AUS, "grund": "Schutzschicht für diesen Dienst nicht konfiguriert"}
        if verlangt:
            key = _wert(cfg, schluessel_name)
            if key:
                return {"modus": DIREKT, "url": None, "schluessel": key}
            return {"modus": AUS, "grund": f"{schalter_name}=1, aber {schluessel_name} fehlt"}
        return {"modus": AUS, "grund": "weder Schutzschicht noch ausdrücklicher Direktzugang"}

    llm = weg(llm_url, llm_direkt_verlangt, "ANTHROPIC_API_KEY", "PSEUDO_UMGEHEN")
    emb = weg(emb_url, emb_direkt_verlangt, "VOYAGE_API_KEY", "EMBEDDING_DIREKT")
    stt = {"modus": DIREKT if _wert(cfg, "STT_API_KEY") else AUS,
           "grund": "Spracherkennung läuft nicht über die Schutzschicht (offener Punkt)"}
    return {"llm": llm, "embeddings": emb, "stt": stt, "hinweise": hinweise,
            "schutzschicht_konfiguriert": schutz}


def oeffentlich(wege):
    """Für Anzeige und /health: ohne Schlüssel und ohne URLs mit Zugangsdaten."""
    aus = {}
    for name in ("llm", "embeddings", "stt"):
        w = wege[name]
        aus[name] = {"modus": w["modus"], "text": TEXT[w["modus"]]}
        if w.get("grund") and w["modus"] == AUS:
            aus[name]["grund"] = w["grund"]
    aus["stt"]["hinweis"] = wege["stt"]["grund"]
    aus["hinweise"] = list(wege["hinweise"])
    aus["schutzschicht_konfiguriert"] = wege["schutzschicht_konfiguriert"]
    return aus


def irgendwo_direkt(wege):
    return any(wege[n]["modus"] == DIREKT for n in ("llm", "embeddings"))
