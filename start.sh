#!/usr/bin/env sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
to_absolute() {
  case "$1" in
    /*) printf '%s\n' "$1" ;;
    *) printf '%s/%s\n' "$ROOT_DIR" "$1" ;;
  esac
}
if ! command -v uv >/dev/null 2>&1; then
  echo "错误：未找到 uv。请先安装 uv（例如：brew install uv）。" >&2
  exit 1
fi

STATE_DIR=${STATE_DIR:-"$ROOT_DIR/state"}
STATE_DIR=$(to_absolute "$STATE_DIR")
PID_FILE=${PID_FILE:-"$STATE_DIR/backend.pid"}
LOG_FILE=${LOG_FILE:-"$STATE_DIR/backend.log"}
FRONTEND_DIR=${FRONTEND_DIR:-"$ROOT_DIR/frontend"}
FRONTEND_DIR=$(to_absolute "$FRONTEND_DIR")
FRONTEND_STATE_DIR=${FRONTEND_STATE_DIR:-"$STATE_DIR"}
FRONTEND_STATE_DIR=$(to_absolute "$FRONTEND_STATE_DIR")
FRONTEND_PID_FILE=${FRONTEND_PID_FILE:-"$FRONTEND_STATE_DIR/frontend.pid"}
FRONTEND_LOG_FILE=${FRONTEND_LOG_FILE:-"$FRONTEND_STATE_DIR/frontend.log"}
FRONTEND_MODE=${FRONTEND_MODE:-dev}
FRONTEND_HOST=${FRONTEND_HOST:-127.0.0.1}
FRONTEND_PORT=${FRONTEND_PORT:-5173}
HOST=${HOST:-0.0.0.0}
PORT=${PORT:-8000}
ENV_FILE=${ENV_FILE:-"$ROOT_DIR/.env"}
ENV_FILE=$(to_absolute "$ENV_FILE")

if ! command -v npm >/dev/null 2>&1; then
  echo "错误：未找到 npm，无法启动 React/Vite 前端。" >&2
  exit 1
fi
case "$FRONTEND_MODE" in
  dev|preview) ;;
  *) echo "错误：FRONTEND_MODE 只能是 dev 或 preview。" >&2; exit 1 ;;
esac

umask 077
mkdir -p "$STATE_DIR" "${DOWNLOAD_ROOT:-$ROOT_DIR/downloads}"
export UV_CACHE_DIR=${UV_CACHE_DIR:-"$STATE_DIR/uv-cache"}

pid_is_backend() {
  pid_to_check=$1
  kill -0 "$pid_to_check" 2>/dev/null || return 1
  ps -p "$pid_to_check" -o command= 2>/dev/null | grep -F "backend.app.main:app" >/dev/null 2>&1
}

backend_running=0
if [ -f "$PID_FILE" ]; then
  pid=$(sed -n '1p' "$PID_FILE")
  case "$pid" in
    ''|*[!0-9]*) rm -f "$PID_FILE" ;;
    *)
      if pid_is_backend "$pid"; then
        echo "后端已在运行（PID ${pid}，端口 ${PORT}）。"
        backend_running=1
      else
        rm -f "$PID_FILE"
      fi
      ;;
  esac
fi

cd "$ROOT_DIR"
if [ "$backend_running" -eq 0 ]; then
  echo "正在使用 uv 同步后端隔离环境..."
  uv sync --project "$ROOT_DIR/backend"

  echo "正在启动后端（http://${HOST}:${PORT}）..."
  if [ -f "$ENV_FILE" ]; then
    # 使用 uv 的 dotenv 解析器，避免 User-Agent 等值被 shell 错误解释。
    PYTHONPATH="$ROOT_DIR:$ROOT_DIR/yt-dlp${PYTHONPATH:+:$PYTHONPATH}" \
      nohup uv run --project "$ROOT_DIR/backend" --env-file "$ENV_FILE" python -m uvicorn backend.app.main:app \
        --host "$HOST" --port "$PORT" >>"$LOG_FILE" 2>&1 &
  else
    PYTHONPATH="$ROOT_DIR:$ROOT_DIR/yt-dlp${PYTHONPATH:+:$PYTHONPATH}" \
      nohup uv run --project "$ROOT_DIR/backend" python -m uvicorn backend.app.main:app \
        --host "$HOST" --port "$PORT" >>"$LOG_FILE" 2>&1 &
  fi
  pid=$!
  printf '%s\n' "$pid" >"$PID_FILE"

  sleep 1
  if ! kill -0 "$pid" 2>/dev/null; then
    echo "后端启动失败，请查看日志：$LOG_FILE" >&2
    rm -f "$PID_FILE"
    exit 1
  fi

  echo "后端已启动（PID ${pid}）。日志：$LOG_FILE"
fi

if [ -f "$FRONTEND_PID_FILE" ]; then
  frontend_pid=$(sed -n '1p' "$FRONTEND_PID_FILE")
  case "$frontend_pid" in
    ''|*[!0-9]*) rm -f "$FRONTEND_PID_FILE" ;;
    *)
      if kill -0 "$frontend_pid" 2>/dev/null \
        && ps -p "$frontend_pid" -o command= 2>/dev/null | grep -F "$FRONTEND_DIR/vite.config.js" >/dev/null 2>&1; then
        echo "前端已在运行（PID ${frontend_pid}，地址 http://${FRONTEND_HOST}:${FRONTEND_PORT}）。"
        exit 0
      fi
      rm -f "$FRONTEND_PID_FILE"
      ;;
  esac
fi

if [ ! -x "$FRONTEND_DIR/node_modules/.bin/vite" ]; then
  echo "未找到前端依赖，正在执行 npm ci..."
  (cd "$FRONTEND_DIR" && npm ci)
fi

echo "正在启动前端（${FRONTEND_MODE}，http://${FRONTEND_HOST}:${FRONTEND_PORT}）..."
cd "$FRONTEND_DIR"
if [ "$FRONTEND_MODE" = "preview" ]; then
  if [ ! -d "$FRONTEND_DIR/dist" ]; then
    echo "错误：FRONTEND_MODE=preview 需要先执行 (cd frontend && npm run build)。" >&2
    exit 1
  fi
  nohup npm run preview -- --host "$FRONTEND_HOST" --port "$FRONTEND_PORT" --config "$FRONTEND_DIR/vite.config.js" >>"$FRONTEND_LOG_FILE" 2>&1 &
else
  nohup npm run dev -- --host "$FRONTEND_HOST" --port "$FRONTEND_PORT" --config "$FRONTEND_DIR/vite.config.js" >>"$FRONTEND_LOG_FILE" 2>&1 &
fi
frontend_pid=$!
cd "$ROOT_DIR"
printf '%s\n' "$frontend_pid" >"$FRONTEND_PID_FILE"

sleep 1
if ! kill -0 "$frontend_pid" 2>/dev/null; then
  echo "前端启动失败，请查看日志：$FRONTEND_LOG_FILE" >&2
  rm -f "$FRONTEND_PID_FILE"
  exit 1
fi

echo "前端已启动（PID ${frontend_pid}）。日志：$FRONTEND_LOG_FILE"
