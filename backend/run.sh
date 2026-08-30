#!/usr/bin/env sh
set -eu
ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT_DIR"
STATE_DIR=${STATE_DIR:-"$ROOT_DIR/state"}
mkdir -p "$STATE_DIR"
export UV_CACHE_DIR=${UV_CACHE_DIR:-"$STATE_DIR/uv-cache"}
ENV_FILE=${ENV_FILE:-"$ROOT_DIR/.env"}
if [ -f "$ENV_FILE" ]; then
  PYTHONPATH="$ROOT_DIR:$ROOT_DIR/yt-dlp${PYTHONPATH:+:$PYTHONPATH}" \
    exec uv run --project "$ROOT_DIR/backend" --env-file "$ENV_FILE" python -m uvicorn backend.app.main:app \
      --host "${HOST:-0.0.0.0}" --port "${PORT:-8000}"
fi
PYTHONPATH="$ROOT_DIR:$ROOT_DIR/yt-dlp${PYTHONPATH:+:$PYTHONPATH}" \
  exec uv run --project "$ROOT_DIR/backend" python -m uvicorn backend.app.main:app \
    --host "${HOST:-0.0.0.0}" --port "${PORT:-8000}"
