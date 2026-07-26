#!/usr/bin/env bash
# =====================================================================
# HERMES PIA – Betriebssteuerung (Deploy · Start · Watchdog)
# =====================================================================
# EINE Quelle der Wahrheit, wie eine Umgebung gestartet und geprueft wird.
# Wird per SSH-stdin vom Jenkins-Deploy ausgefuehrt UND als Cron-Watchdog,
# der abgestuerzte Prozesse automatisch neu startet (Managed Hosting ohne
# systemd/Supervisor).
#
#   hermes_ctl.sh deploy <env> [repo] [venv]   Vollausrollung einer Umgebung
#   hermes_ctl.sh start  <env>                  (Neu-)Start einer Umgebung
#   hermes_ctl.sh stop   <env>                  Prozess sauber stoppen
#   hermes_ctl.sh watchdog                      alle Umgebungen pruefen/heilen
#   hermes_ctl.sh health <env>                  /health pruefen (Exit 0/1)
#
# env: prod | test | int | dev
#
# Sicherheitsprinzipien (beibehalten aus dem alten Jenkinsfile):
#   - Kill NUR, wenn /proc/PID/cmdline wirklich "gunicorn" enthaelt.
#   - NIE blind `kill $(cat PID)`, NIE `pkill -f` (killt die eigene Sitzung).
#   - `fuser -k <port>/tcp` nur als zweites Netz.
#   - `--capture-output`, damit Tracebacks im error.log landen.
set -u

HOME_DIR="${HOME:?HOME nicht gesetzt}"
REPO_URL_DEFAULT="https://github.com/kaspAir/HERMES-PIA"
VENV="$HOME_DIR/venv"
SHARED_ENV="$HOME_DIR/methodos/.env"     # ANTHROPIC_API_KEY, FLASK_SECRET_KEY, STT_API_KEY ...
CTL_DIR="$HOME_DIR/bin/hermes"
LOG="$HOME_DIR/logs/watchdog.log"
TMP="$HOME_DIR/tmp"
mkdir -p "$TMP" "$HOME_DIR/logs" 2>/dev/null || true

hp_log() { echo "$(date '+%F %T') [$1] $2" >> "$LOG" 2>/dev/null; }

# env -> HP_BRANCH / HP_PORT / HP_DIR / HP_WORKERS / HP_PID / HP_DB
hp_config() {
  case "${1:-}" in
    prod) HP_BRANCH=main;        HP_PORT=8000; HP_DIR="$HOME_DIR/methodos";
          HP_WORKERS=2; HP_PID="$TMP/gunicorn.pid";      HP_DB="" ;;
    test) HP_BRANCH=test;        HP_PORT=8001; HP_DIR="$HOME_DIR/methodos-test";
          HP_WORKERS=3; HP_PID="$TMP/gunicorn-test.pid"; HP_DB="$HOME_DIR/methodos-test/data/methodos-test.db" ;;
    int)  HP_BRANCH=integration; HP_PORT=8002; HP_DIR="$HOME_DIR/methodos-int";
          HP_WORKERS=1; HP_PID="$TMP/gunicorn-int.pid";  HP_DB="$HOME_DIR/methodos-int/data/methodos-int.db" ;;
    dev)  HP_BRANCH=develop;     HP_PORT=8003; HP_DIR="$HOME_DIR/methodos-dev";
          HP_WORKERS=1; HP_PID="$TMP/gunicorn-dev.pid";  HP_DB="$HOME_DIR/methodos-dev/data/methodos-dev.db" ;;
    *) echo "Unbekannte Umgebung: ${1:-<leer>} (prod|test|int|dev)" >&2; return 2 ;;
  esac
}

hp_health() {   # 0, wenn /health der Umgebung antwortet (flach: nur HTTP, keine DB)
  hp_config "${1:-}" || return 2
  curl -sf --max-time 8 "http://127.0.0.1:$HP_PORT/health" >/dev/null 2>&1
}

hp_stop() {     # PID-verifizierter Kill + fuser-Fallback
  hp_config "${1:-}" || return 2
  if [ -f "$HP_PID" ]; then
    local old; old=$(cat "$HP_PID" 2>/dev/null || true)
    if [ -n "$old" ] && grep -qa gunicorn "/proc/$old/cmdline" 2>/dev/null; then
      kill "$old" 2>/dev/null || true
      local i; for i in $(seq 1 20); do kill -0 "$old" 2>/dev/null || break; sleep 1; done
    fi
    rm -f "$HP_PID"
  fi
  fuser -k "$HP_PORT/tcp" 2>/dev/null || true
}

# Roher (Neu-)Start ohne Lock – immer via hp_start/Watchdog aufrufen.
hp_launch() {
  hp_config "${1:-}" || return 2
  if [ ! -d "$HP_DIR" ]; then hp_log ERR "$1: Verzeichnis $HP_DIR fehlt"; return 1; fi
  hp_stop "$1"
  sleep 2
  mkdir -p "$HP_DIR/data" "$HP_DIR/logs"
  # Gemeinsame Secrets laden, DATABASE_URL je Umgebung ueberschreiben (prod nutzt .env).
  set -a
  [ -f "$SHARED_ENV" ] && . "$SHARED_ENV"
  [ -n "$HP_DB" ] && DATABASE_URL="sqlite:///$HP_DB"
  set +a
  (
    cd "$HP_DIR" || exit 1
    # shellcheck disable=SC1091
    . "$VENV/bin/activate"
    # WICHTIG: 8>&- 9>&- schliesst etwaige Lock-FDs fuer den Daemon. Ein per
    # nohup gestarteter Gunicorn wuerde ein geerbtes flock-FD sonst DAUERHAFT
    # halten und den naechsten Deploy/Watchdog blockieren.
    nohup gunicorn run:app \
      --bind "127.0.0.1:$HP_PORT" --workers "$HP_WORKERS" \
      # 120 s waren zu knapp: ein Pruefschritt mit grosszuegigem Token-Budget
      # darf laenger dauern, ohne dass gunicorn den Worker abschiesst (dann ist
      # der ganze Schritt verloren statt nur gekuerzt).
      --timeout 300 --graceful-timeout 30 \
      --max-requests 800 --max-requests-jitter 200 \
      --access-logfile "$HP_DIR/logs/access.log" \
      --error-logfile "$HP_DIR/logs/error.log" --capture-output \
      >/dev/null 2>&1 8>&- 9>&- &
    echo $! > "$HP_PID"
  )
  # Start + evtl. DB-Migration brauchen einen Moment.
  local i
  for i in $(seq 1 15); do
    sleep 2
    if hp_health "$1"; then hp_log OK "$1: laeuft (Port $HP_PORT)"; return 0; fi
  done
  hp_log ERR "$1: Start fehlgeschlagen (Port $HP_PORT) – siehe $HP_DIR/logs/error.log"
  return 1
}

# Marker signalisiert dem Watchdog «Deploy läuft» – bewusst KEINE flock-Sperre um
# den Start (der nohup-Daemon würde ein Lock-FD erben und dauerhaft halten).
hp_marker() { echo "$TMP/hermes-deploying-$1"; }

# (Neu-)Start EINER Umgebung. Deploy-Pfad: autoritativ. Rückgabe = Gesundheit;
# scheitert NUR an echter Ungesundheit, nie an Contention.
hp_start() {
  hp_config "${1:-}" || return 2
  local mk; mk=$(hp_marker "$1")
  : > "$mk" 2>/dev/null || true       # Watchdog während des Deploys fernhalten
  hp_launch "$1"; local rc=$?
  rm -f "$mk" 2>/dev/null || true
  return "$rc"
}

hp_watchdog() {
  # Nur eine Watchdog-Instanz gleichzeitig (globaler Lock; NICHT um einen Start).
  exec 9>"$TMP/hermes-watchdog.lock"
  if command -v flock >/dev/null 2>&1; then flock -n 9 || exit 0; fi
  local e mk
  for e in prod test int dev; do
    hp_config "$e" || continue
    [ -d "$HP_DIR" ] || continue         # Umgebung nicht ausgerollt -> ignorieren
    mk=$(hp_marker "$e")
    # Läuft gerade ein Deploy (frischer Marker < 15 Min)? Dann auslassen.
    if [ -f "$mk" ] && [ -z "$(find "$mk" -mmin +15 2>/dev/null)" ]; then continue; fi
    hp_health "$e" && continue
    sleep 3
    hp_health "$e" && continue           # transienten Aussetzer nicht ueberreagieren
    hp_log WARN "$e: /health nicht erreichbar -> Neustart durch Watchdog"
    hp_launch "$e"
  done
}

# Steuerskript an stabilen Ort kopieren + Cron-Watchdog (idempotent) einrichten.
hp_install_self() {
  local src="$1"
  mkdir -p "$CTL_DIR"
  if [ -f "$src" ]; then
    cp -f "$src" "$CTL_DIR/hermes_ctl.sh" && chmod +x "$CTL_DIR/hermes_ctl.sh"
  fi
  if ! command -v crontab >/dev/null 2>&1; then
    hp_log ERR "crontab nicht verfuegbar – Watchdog-Cron nicht eingerichtet"
    return 0
  fi
  local line="*/2 * * * * /bin/bash $CTL_DIR/hermes_ctl.sh watchdog >/dev/null 2>&1"
  local rest; rest=$(crontab -l 2>/dev/null | grep -v 'hermes_ctl.sh watchdog' || true)
  { [ -n "$rest" ] && printf '%s\n' "$rest"; printf '%s\n' "$line"; } | crontab - 2>/dev/null \
    && hp_log OK "Watchdog-Cron aktiv (alle 2 Minuten)" \
    || hp_log ERR "Cron-Installation fehlgeschlagen"
}

hp_bootstrap_dev_proxy() {   # einmaliger PHP-Proxy fuer dev.hermespia.ch (8001 -> 8003)
  local sites="$HOME_DIR/sites"
  if [ -d "$sites/dev.hermespia.ch" ]; then
    if [ ! -f "$sites/dev.hermespia.ch/index.php" ] && [ -f "$sites/test.hermespia.ch/index.php" ]; then
      cp -a "$sites/test.hermespia.ch/." "$sites/dev.hermespia.ch/"
      grep -rIl 8001 "$sites/dev.hermespia.ch" | while read -r f; do sed -i 's/8001/8003/g' "$f"; done
      echo "Proxy fuer dev.hermespia.ch aus test kopiert (8001 -> 8003)"
    fi
  else
    echo "WARNUNG: $sites/dev.hermespia.ch fehlt – Proxy manuell einrichten"
  fi
}

hp_deploy() {   # <env> [repo] [venv]
  hp_config "${1:-}" || return 2
  local env="$1" repo="${2:-$REPO_URL_DEFAULT}"
  [ -n "${3:-}" ] && VENV="$3"
  [ "$env" = dev ] && hp_bootstrap_dev_proxy
  [ -d "$HP_DIR/.git" ] || git clone "$repo" "$HP_DIR"
  ( cd "$HP_DIR" && git remote set-url origin "$repo" && git fetch origin \
      && git reset --hard "origin/$HP_BRANCH" )
  ( cd "$HP_DIR" && . "$VENV/bin/activate" && pip install -r requirements.txt -q )
  hp_install_self "$HP_DIR/deploy/hermes_ctl.sh"   # Watchdog aus frischem Checkout aktualisieren
  hp_start "$env"
}

case "${1:-}" in
  deploy)   shift; hp_deploy "$@" ;;
  start)    shift; hp_start "$@" ;;
  stop)     shift; hp_stop "$@" ;;
  watchdog) hp_watchdog ;;
  health)   shift; if hp_health "${1:-}"; then echo OK; else echo DOWN; exit 1; fi ;;
  *) echo "Usage: hermes_ctl.sh {deploy|start|stop|watchdog|health} [env] [repo] [venv]" >&2; exit 2 ;;
esac
