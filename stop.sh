#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

PIDFILE=".server.pid"

# Kill PID from file if exists
if [ -f "$PIDFILE" ]; then
    PID=$(cat "$PIDFILE")
    if kill -0 "$PID" 2>/dev/null; then
        kill -- -"$PID" 2>/dev/null || kill "$PID" 2>/dev/null || true
        echo "Server stopped (PID $PID)"
    else
        echo "PID $PID not running (stale PID file)"
    fi
    rm -f "$PIDFILE"
fi

# Ensure port 8000 is fully released — kill any lingering processes
PORT="${B2A_PORT:-8000}"
LEFTOVER=$(lsof -ti:"$PORT" 2>/dev/null || true)
if [ -n "$LEFTOVER" ]; then
    echo "Killing leftover processes on port $PORT: $LEFTOVER"
    echo "$LEFTOVER" | xargs kill -9 2>/dev/null || true
fi
