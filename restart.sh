#!/usr/bin/env sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
"$ROOT_DIR/stop.sh"
exec "$ROOT_DIR/start.sh"
