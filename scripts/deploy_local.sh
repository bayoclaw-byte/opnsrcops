#!/usr/bin/env bash
set -euo pipefail

# Deploy + restart for Gulf AOR tunnel origin
# - pulls latest code
# - restarts Flask on 127.0.0.1:5050
# - writes PID to /tmp/gulf_aor_flask.pid

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PIDFILE="/tmp/gulf_aor_flask.pid"
LOGFILE="$ROOT_DIR/../../logs/gulf_aor_flask.log"

cd "$ROOT_DIR"
echo "[deploy] repo: $ROOT_DIR"

# Pull latest
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "[deploy] git pull..."
  git pull --rebase origin main
fi

# Stop existing
if [[ -f "$PIDFILE" ]]; then
  PID="$(cat "$PIDFILE" || true)"
  if [[ -n "${PID:-}" ]] && kill -0 "$PID" >/dev/null 2>&1; then
    echo "[deploy] stopping pid $PID"
    kill "$PID" || true
    sleep 1
  fi
fi

# Fallback stop (in case PIDFILE is missing)
# Only targets flask run on port 5050
pkill -f "flask run --host 127.0.0.1 --port 5050" >/dev/null 2>&1 || true

# Start
export FLASK_APP=app.py
export FLASK_ENV=production
mkdir -p "$(dirname "$LOGFILE")"
PY_BIN="${PY_BIN:-/opt/homebrew/opt/python@3.14/bin/python3.14}"
nohup "$PY_BIN" -m flask run --host 127.0.0.1 --port 5050 >>"$LOGFILE" 2>&1 &
NEWPID=$!
echo "$NEWPID" > "$PIDFILE"

sleep 0.5
if kill -0 "$NEWPID" >/dev/null 2>&1; then
  echo "[deploy] started pid $NEWPID"
else
  echo "[deploy] failed to start" >&2
  exit 1
fi

echo "[deploy] done"
