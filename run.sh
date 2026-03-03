#!/usr/bin/env bash
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Try workspace venv first, then system pip
VENV="$HOME/.openclaw/workspace/.venv"
if [ -f "$VENV/bin/python" ]; then
  PYTHON="$VENV/bin/python"
  PIP="$VENV/bin/pip"
else
  PYTHON="python3"
  PIP="pip3"
fi

# Install deps if needed
$PIP install -q flask

echo "Starting Iran AOR Dashboard on http://localhost:5050"
$PYTHON app.py
