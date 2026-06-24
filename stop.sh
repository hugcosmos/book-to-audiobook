#!/usr/bin/env bash
# Stop the background server started by start.sh.
#
# uvicorn with reload=True spawns a child process (the actual server); the
# recorded PID is the reloader parent. So we kill BOTH the PID and its direct
# children (pkill -P) to fully release the port. If reload is off (the
# start.sh default), there's no child and pkill -P is a harmless no-op.
#
# The port-sweep is a last resort, used only when no PID file is available —
# it can't tell our process apart from anything else bound to the port.
set -euo pipefail
cd "$(dirname "$0")"

PIDFILE=".server.pid"
PORT="${B2A_PORT:-8000}"
STOPPED=0

if [ -f "$PIDFILE" ]; then
    PID=$(cat "$PIDFILE")
    if kill -0 "$PID" 2>/dev/null; then
        # Kill reload-spawned children first, then the parent itself.
        pkill -P "$PID" 2>/dev/null || true
        kill "$PID" 2>/dev/null || true
        echo "Server stopped (PID $PID)"
        STOPPED=1
    else
        echo "PID $PID not running (stale PID file)"
    fi
    rm -f "$PIDFILE"
fi

# Last resort: only if we never managed a clean stop (e.g. PID file lost),
# sweep the port. Avoids blindly killing unrelated processes on 8000.
if [ "$STOPPED" = "0" ]; then
    LEFTOVER=$(lsof -ti:"$PORT" 2>/dev/null || true)
    if [ -n "$LEFTOVER" ]; then
        echo "No PID file; killing leftover processes on port $PORT: $LEFTOVER"
        echo "$LEFTOVER" | xargs kill -9 2>/dev/null || true
    fi
fi
