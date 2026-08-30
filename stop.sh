#!/usr/bin/env sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
STATE_DIR=${STATE_DIR:-"$ROOT_DIR/state"}
case "$STATE_DIR" in
  /*) ;;
  *) STATE_DIR="$ROOT_DIR/$STATE_DIR" ;;
esac
PID_FILE=${PID_FILE:-"$STATE_DIR/backend.pid"}
FRONTEND_PID_FILE=${FRONTEND_PID_FILE:-"$STATE_DIR/frontend.pid"}

pid_matches() {
  pid_to_check=$1
  process_pattern=$2
  kill -0 "$pid_to_check" 2>/dev/null || return 1
  ps -p "$pid_to_check" -o command= 2>/dev/null | grep -F "$process_pattern" >/dev/null 2>&1
}

stop_one() {
  service_label=$1
  service_pid_file=$2
  service_pattern=$3

  if [ ! -f "$service_pid_file" ]; then
    echo "${service_label}未运行（没有 PID 文件）。"
    return 0
  fi

  service_pid=$(sed -n '1p' "$service_pid_file")
  case "$service_pid" in
    ''|*[!0-9]*)
      echo "${service_label}检测到无效的 PID 文件，已清理。" >&2
      rm -f "$service_pid_file"
      return 1
      ;;
  esac

  if ! pid_matches "$service_pid" "$service_pattern"; then
    if kill -0 "$service_pid" 2>/dev/null; then
      echo "PID ${service_pid} 当前不是${service_label}进程，拒绝停止该进程。" >&2
      return 1
    fi
    rm -f "$service_pid_file"
    echo "${service_label}已经停止，已清理 PID 文件。"
    return 0
  fi

  echo "正在停止${service_label}（PID ${service_pid}）..."
  kill "$service_pid"
  i=0
  while pid_matches "$service_pid" "$service_pattern"; do
    i=$((i + 1))
    if [ "$i" -ge 30 ]; then
      echo "${service_label}未在 30 秒内退出，发送强制停止信号。" >&2
      kill -KILL "$service_pid" 2>/dev/null || true
      break
    fi
    sleep 1
  done

  rm -f "$service_pid_file"
  echo "${service_label}已停止。"
  return 0
}

result=0
stop_one "后端" "$PID_FILE" "backend.app.main:app" || result=1
stop_one "前端" "$FRONTEND_PID_FILE" "vite.config.js" || result=1
exit "$result"
