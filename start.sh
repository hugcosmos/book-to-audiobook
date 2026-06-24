#!/usr/bin/env bash
# Start the web server in the BACKGROUND (deployment mode), managed via PID
# file so stop.sh can shut it down cleanly. For day-to-day dev prefer the
# foreground, auto-reloading `book2audio serve`.
#
# Run this from the SAME activated venv/conda env you'd run `book2audio serve`
# in, so `python3` resolves to the interpreter that has the deps. Pin a
# different one with PYTHON=/path/to/python.
set -euo pipefail
cd "$(dirname "$0")"

HOST="${B2A_HOST:-0.0.0.0}"
PORT="${B2A_PORT:-8000}"
# Prod mode = no reload (no reload-spawned child either). Override with
# B2A_RELOAD=1 if you want hot reload while running in the background.
export B2A_RELOAD="${B2A_RELOAD:-0}"

# Pick a Python that actually has the deps. `python3` from a login shell often
# misses them (conda/venv activation isn't reliably inherited by scripts), so
# we probe. Override with PYTHON=/path/to/python to skip the probe.
if [ -z "${PYTHON:-}" ]; then
    for cand in "${VIRTUAL_ENV:-/nonexistent}/bin/python" \
                "${CONDA_PREFIX:-/nonexistent}/bin/python" \
                "$HOME"/miniconda3/envs/book2audio*/bin/python \
                "$HOME"/anaconda3/envs/book2audio*/bin/python \
                /opt/*/envs/book2audio*/bin/python; do
        if [ -x "$cand" ] && "$cand" -c "import uvicorn" >/dev/null 2>&1; then
            PYTHON="$cand"; break
        fi
    done
fi
PYTHON="${PYTHON:-python3}"

# Faster HF downloads for qwen3 MLX; harmless for other providers.
export HF_HUB_ENABLE_HF_TRANSFER=1
export HF_TOKEN="${HF_TOKEN:-}"
# Uncomment if hf-mirror.com is faster for you (mainland China):
# export HF_ENDPOINT=https://hf-mirror.com

mkdir -p uploads output

PIDFILE=".server.pid"
LOGFILE=".server.log"

# Kill old instance if any (best-effort; stop.sh is the canonical shutdown).
if [ -f "$PIDFILE" ]; then
    OLD_PID=$(cat "$PIDFILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "Stopping old server (PID $OLD_PID)..."
        ./stop.sh || bash stop.sh || true
        sleep 1
    else
        rm -f "$PIDFILE"
    fi
fi

# nohup detaches from the terminal so the server survives logout.
nohup "$PYTHON" -m app.main > "$LOGFILE" 2>&1 &
SERVER_PID=$!
echo "$SERVER_PID" > "$PIDFILE"

# Verify it started. Poll for up to ~15s: the process must stay alive AND the
# port must come up (app boot + model preload can take several seconds). A
# fixed `sleep 1` is too eager — uvicorn is mid-boot at 1s.
PORT_UP=0
for _ in $(seq 1 30); do
    if ! kill -0 "$SERVER_PID" 2>/dev/null; then
        break  # process exited — boot failed
    fi
    if lsof -ti:"$PORT" >/dev/null 2>&1; then
        PORT_UP=1
        break
    fi
    sleep 0.5
done

if [ "$PORT_UP" = "1" ]; then
    echo "Server started (PID $SERVER_PID, $PYTHON)"
    echo "  http://${HOST}:${PORT}"
    echo "  Log: tail -f $LOGFILE"
    echo "  Stop: ./stop.sh"
else
    echo "Server failed to start. Check $LOGFILE" >&2
    # Only drop the PID file if the process is actually gone; otherwise leave
    # it so the user can still ./stop.sh the half-running instance.
    if ! kill -0 "$SERVER_PID" 2>/dev/null; then
        rm -f "$PIDFILE"
    fi
    exit 1
fi
