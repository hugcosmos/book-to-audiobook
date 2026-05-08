#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

PIDFILE=".server.pid"

if [ ! -f "$PIDFILE" ]; then
    echo "No PID file found. Server not running?"
    exit 0
fi

PID=$(cat "$PIDFILE")

if kill -0 "$PID" 2>/dev/null; then
    kill "$PID"
    echo "Server stopped (PID $PID)"
else
    echo "PID $PID not running (stale PID file)"
fi

rm -f "$PIDFILE"
