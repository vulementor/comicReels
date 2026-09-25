#!/usr/bin/env bash
set -euo pipefail

SOURCE_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CACHE_BASE="${XDG_CACHE_HOME:-$HOME/.cache}"
RUNTIME_ROOT="${COMICREELS_RUNTIME_DIR:-$CACHE_BASE/comicreels/runtime}"
VENV="${COMICREELS_VENV:-$CACHE_BASE/comicreels/venv}"
RUNTIME_REF="${COMICREELS_RUNTIME_REF:-HEAD}"
GPTFP_REQUIRED_REF="${COMICREELS_GPTFP_REF:-8ae68597232edaf7129a73920d46569e128529b4}"
GPTFP_BRANCH="${COMICREELS_GPTFP_BRANCH:-feature/comicreels-image-attachments}"
GPTFP_REPO="${COMICREELS_GPTFP_REPO:-https://github.com/vulementor/gpt_fullproxy.git}"

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

# Browser-native ChatGPT AI through the private GPT FullProxy SDK.
# The public ComicReels repo does not vendor browser-session material or private source.
if [ -z "${COMICREELS_GPTFP_PROFILE_DIR:-}" ]; then
  ZALO_PROFILE="$HOME/Library/Application Support/ZaloConnect/chatgpt-web-profile"
  if [ -d "$ZALO_PROFILE" ]; then
    export COMICREELS_GPTFP_PROFILE_DIR="$ZALO_PROFILE"
  fi
fi

GPTFP_DIR="${COMICREELS_GPTFP_DIR:-$CACHE_BASE/comicreels/gpt_fullproxy-src}"
if [ ! -d "$GPTFP_DIR/.git" ]; then
  mkdir -p "$(dirname "$GPTFP_DIR")"
  echo "ComicReels: cloning GPT FullProxy from $GPTFP_REPO"
  git clone --filter=blob:none --no-checkout "$GPTFP_REPO" "$GPTFP_DIR"
fi

git -C "$GPTFP_DIR" fetch --force --depth=1 origin "$GPTFP_BRANCH"
git -C "$GPTFP_DIR" checkout --detach "$GPTFP_REQUIRED_REF"
GPTFP_HEAD="$(git -C "$GPTFP_DIR" rev-parse HEAD)"
if [ "${COMICREELS_GPTFP_ALLOW_UNPINNED:-0}" != "1" ] && [ "$GPTFP_HEAD" != "$GPTFP_REQUIRED_REF" ]; then
  echo "ComicReels: GPT FullProxy HEAD $GPTFP_HEAD does not match required $GPTFP_REQUIRED_REF" >&2
  exit 2
fi

GPTFP_STAMP="$VENV/.comicreels-gptfp.sha"
if [ ! -f "$GPTFP_STAMP" ] || [ "$(cat "$GPTFP_STAMP")" != "$GPTFP_HEAD" ]; then
  "$VENV/bin/python" -m pip install -e "${GPTFP_DIR}[browser]"
  "$VENV/bin/python" -m camoufox fetch
  printf '%s' "$GPTFP_HEAD" > "$GPTFP_STAMP"
fi
export COMICREELS_GPTFP_DIR="$GPTFP_DIR"

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
echo "GPT FullProxy:       ${COMICREELS_GPTFP_DIR:-not connected}"
echo "ChatGPT profile:     ${COMICREELS_GPTFP_PROFILE_DIR:-not connected}"
echo "Backend PID: $BACKEND"
echo "Frontend PID: $FRONTEND"
echo "Open http://127.0.0.1:5173/"
wait
