#!/usr/bin/env bash
# Launch Prayers AI on a single port (default 8080).
# Uses a local .venv so it works on Homebrew Python (PEP 668) and Linux alike.
set -e
cd "$(dirname "$0")"
[ -f .env ] && { set -a; . ./.env; set +a; }
export PORT="${PORT:-8080}"
export SCRAPE_INTERVAL_HOURS="${SCRAPE_INTERVAL_HOURS:-12}"

PY="${PYTHON:-python3}"
VENV=".venv"

if [ ! -x "$VENV/bin/python" ]; then
  echo "[start] Creating virtualenv at $VENV"
  $PY -m venv "$VENV"
fi

"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet -r scraper/requirements.txt

exec "$VENV/bin/python" server.py
