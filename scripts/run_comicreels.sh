#!/usr/bin/env bash
set -euo pipefail

SOURCE_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CACHE_BASE="${XDG_CACHE_HOME:-$HOME/.cache}"
RUNTIME_ROOT="${COMICREELS_RUNTIME_DIR:-$CACHE_BASE/comicreels/runtime}"
VENV="${COMICREELS_VENV:-$CACHE_BASE/comicreels/venv}"
RUNTIME_REF="${COMICREELS_RUNTIME_REF:-HEAD}"

mkdir -p "$RUNTIME_ROOT" "$(dirname "$VENV")"

COMMIT="$(git -C "$SOURCE_ROOT" rev-parse "$RUNTIME_REF^{commit}")"
MANIFEST="$RUNTIME_ROOT/.comicreels-tracked-files"
if [ -f "$MANIFEST" ]; then
  while IFS= read -r rel; do
    [ -n "$rel" ] && rm -f "$RUNTIME_ROOT/$rel"
  done < "$MANIFEST"
fi

git -C "$SOURCE_ROOT" ls-tree -r --name-only "$COMMIT" > "$MANIFEST.new"
git -C "$SOURCE_ROOT" archive --format=tar "$COMMIT" | tar -xf - -C "$RUNTIME_ROOT"
mv "$MANIFEST.new" "$MANIFEST"

cd "$RUNTIME_ROOT"

PYTHON_BIN="${COMICREELS_PYTHON:-}"
if [ -z "$PYTHON_BIN" ]; then
  if command -v python3.12 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3.12)"
  else
    PYTHON_BIN="$(command -v python3)"
  fi
fi

if [ ! -x "$VENV/bin/python" ]; then
  "$PYTHON_BIN" -m venv "$VENV"
fi

hash_file() {
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  else
    sha256sum "$1" | awk '{print $1}'
  fi
}

REQ_HASH="$(hash_file requirements.txt)"
REQ_STAMP="$VENV/.comicreels-requirements.sha"
if [ ! -f "$REQ_STAMP" ] || [ "$(cat "$REQ_STAMP")" != "$REQ_HASH" ]; then
  "$VENV/bin/python" -m pip install -r requirements.txt
  printf '%s' "$REQ_HASH" > "$REQ_STAMP"
fi

LOCK_HASH="$(hash_file dashboard/package-lock.json)"
LOCK_STAMP="$RUNTIME_ROOT/.comicreels-package-lock.sha"
if [ ! -d dashboard/node_modules ] || [ ! -f "$LOCK_STAMP" ] || [ "$(cat "$LOCK_STAMP")" != "$LOCK_HASH" ]; then
  rm -rf dashboard/node_modules
  (cd dashboard && npm ci)
  printf '%s' "$LOCK_HASH" > "$LOCK_STAMP"
fi

"$VENV/bin/python" -m agent.main &
BACKEND=$!
(cd dashboard && npm run dev -- --host 127.0.0.1) &
FRONTEND=$!

trap 'kill $BACKEND $FRONTEND 2>/dev/null || true' EXIT INT TERM
echo "ComicReels source:  $SOURCE_ROOT"
echo "Runtime commit:     $COMMIT"
echo "ComicReels runtime: $RUNTIME_ROOT"
echo "Backend PID: $BACKEND"
echo "Frontend PID: $FRONTEND"
echo "Open http://127.0.0.1:5173/"
wait
