#!/usr/bin/env bash
# Start the API and the web app together in the background.
#
# The Makefile keeps recipes to one command per line (GNU Make 3.81, no
# .ONESHELL), so the multi-process orchestration lives here instead. Both
# processes are detached, their output is tee'd to .planify/logs/, and
# their PIDs are recorded so `make dev-stop` can reap them.
set -euo pipefail

cd "$(dirname "$0")/.."

LOG_DIR=".planify/logs"
PID_DIR=".planify/pids"
mkdir -p "$LOG_DIR" "$PID_DIR"

start() {
  local name="$1"; shift
  local pidfile="$PID_DIR/$name.pid"
  if [ -f "$pidfile" ] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
    echo "$name already running (pid $(cat "$pidfile"))"
    return
  fi
  "$@" >"$LOG_DIR/$name.log" 2>&1 &
  echo $! >"$pidfile"
  echo "$name started (pid $!) -> $LOG_DIR/$name.log"
}

start api uv run planify-api --config "${CONFIG:-config/settings.py}" --port "${PORT:-8787}"
start web bash -c 'cd apps/web && exec npm run dev'

echo
echo "Both running in the background:"
echo "  web -> http://localhost:5173"
echo "  api -> http://localhost:${PORT:-8787}"
echo
echo "Tail logs with:"
echo "  tail -f $LOG_DIR/api.log $LOG_DIR/web.log"
echo "Stop them with: make stop"
