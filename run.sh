#!/usr/bin/env bash
# Local dev launcher. For production use the systemd units in deploy/.
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Prefer a local .venv, then an explicit $VENV, then system python3.
if [ -f ".venv/bin/python" ]; then
  PYTHON=".venv/bin/python"; PIP=".venv/bin/pip"
elif [ -n "${VENV:-}" ] && [ -f "$VENV/bin/python" ]; then
  PYTHON="$VENV/bin/python"; PIP="$VENV/bin/pip"
else
  PYTHON="python3"; PIP="pip3"
fi

# Load API keys etc. if present (KEY=VALUE lines).
[ -f .env ] && set -a && . ./.env && set +a

$PIP install -q -r requirements.txt

# Optional: prime the data once before serving (no-op for feeds missing keys).
if [ "${1:-}" = "--with-ingest" ]; then
  echo "Priming feeds (ingest --once)..."
  $PYTHON scripts/ingest.py --once || true
fi

echo "Starting Gulf AOR Dashboard on http://localhost:${PORT:-5050}"
echo "  ingestion daemon:  $PYTHON scripts/ingest.py --daemon"
echo "  feed health:       curl localhost:${PORT:-5050}/api/health"
$PYTHON app.py
