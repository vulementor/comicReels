#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
if [ ! -d dashboard/node_modules ]; then (cd dashboard && npm install); fi
python -m agent.main &
BACKEND=$!
(cd dashboard && npm run dev) &
FRONTEND=$!
trap 'kill $BACKEND $FRONTEND 2>/dev/null || true' EXIT INT TERM
echo "ComicReels: http://localhost:5173/"
wait
