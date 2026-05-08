#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

PIDFILE=".server.pid"
LOGFILE=".server.log"
HOST="${B2A_HOST:-0.0.0.0}"
PORT="${B2A_PORT:-8000}"

if [ -f "$PIDFILE" ]; then
    OLD_PID=$(cat "$PIDFILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "Server already running (PID $OLD_PID)"
        exit 1
    fi
    rm -f "$PIDFILE"
fi

mkdir -p uploads output

nohup python -m app.main > "$LOGFILE" 2>&1 &
echo $! > "$PIDFILE"
echo "Server started on http://${HOST}:${PORT} (PID $(cat "$PIDFILE"))"
echo "Log: tail -f ${LOGFILE}"
