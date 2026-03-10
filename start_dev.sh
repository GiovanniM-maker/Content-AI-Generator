#!/usr/bin/env bash
# Dev server wrapper — starts Flask and waits for it to be ready
# Used by .claude/launch.json for preview tool compatibility

DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$DIR/venv/bin/python3"
APP="$DIR/app.py"

# Start Flask in background
"$VENV" "$APP" &
PID=$!

# Wait for server to be ready (max 15 seconds)
for i in $(seq 1 30); do
    if curl -s -o /dev/null http://localhost:5001/ 2>/dev/null; then
        break
    fi
    sleep 0.5
done

# Keep running — forward signals to Flask
trap "kill $PID 2>/dev/null" EXIT INT TERM
wait $PID
