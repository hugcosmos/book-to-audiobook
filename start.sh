#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

HOST="${B2A_HOST:-0.0.0.0}"
PORT="${B2A_PORT:-8000}"

export HF_HUB_ENABLE_HF_TRANSFER=1
export HF_TOKEN="${HF_TOKEN:-}"
# Uncomment next line if hf-mirror.com is faster for you:
# export HF_ENDPOINT=https://hf-mirror.com

mkdir -p uploads output

PIDFILE=".server.pid"
LOGFILE=".server.log"

# Kill old instance if any
if [ -f "$PIDFILE" ]; then
    OLD_PID=$(cat "$PIDFILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "Stopping old server (PID $OLD_PID)..."
        kill "$OLD_PID" 2>/dev/null || true
        sleep 1
    fi
    rm -f "$PIDFILE"
fi

# Start server in background, write real PID after launch
python -m app.main > "$LOGFILE" 2>&1 &
SERVER_PID=$!
echo "$SERVER_PID" > "$PIDFILE"

# Wait briefly and verify it started
sleep 1
if kill -0 "$SERVER_PID" 2>/dev/null; then
    echo "Server started (PID $SERVER_PID)"
    echo "  http://${HOST}:${PORT}"
    echo "  Log: tail -f $LOGFILE"
    echo "  Stop: ./stop.sh"
else
    echo "Server failed to start. Check $LOGFILE"
    rm -f "$PIDFILE"
    exit 1
fi
