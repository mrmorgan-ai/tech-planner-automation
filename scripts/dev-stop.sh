#!/usr/bin/env bash
# Stop the background API and web processes started by scripts/dev.sh.
set -euo pipefail

cd "$(dirname "$0")/.."

PID_DIR=".planify/pids"

stop() {
  local name="$1"
  local pidfile="$PID_DIR/$name.pid"
  if [ ! -f "$pidfile" ]; then
    echo "$name not running (no pidfile)"
    return
  fi
  local pid; pid="$(cat "$pidfile")"
  if kill -0 "$pid" 2>/dev/null; then
    # Kill the whole process group so child processes (e.g. Vite) go too.
    kill "$pid" 2>/dev/null || true
    pkill -P "$pid" 2>/dev/null || true
    echo "$name stopped (pid $pid)"
  else
    echo "$name not running (stale pidfile)"
  fi
  rm -f "$pidfile"
}

stop api
stop web
