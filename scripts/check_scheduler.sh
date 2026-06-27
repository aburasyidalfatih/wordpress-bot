#!/bin/bash
# AutoWP scheduler monitor for the Redis/RQ dispatcher architecture.

set -euo pipefail

BOT_PORT="${BOT_PORT:-5003}"
BOT_URL="${BOT_URL:-http://localhost:${BOT_PORT}/health}"

echo "Checking AutoWP services..."
echo ""

if curl -fsS "$BOT_URL" >/dev/null; then
    echo "[OK] Web health endpoint is healthy: $BOT_URL"
else
    echo "[ERROR] Web health endpoint failed: $BOT_URL"
    exit 1
fi

if command -v docker >/dev/null 2>&1 && docker compose ps >/dev/null 2>&1; then
    echo ""
    echo "Docker Compose service status:"
    docker compose ps web worker scheduler redis postgres
else
    echo ""
    echo "Docker Compose not detected. Checking local dispatcher process..."
    if pgrep -f "python.*dispatcher.py" >/dev/null; then
        echo "[OK] dispatcher.py is running"
    else
        echo "[WARN] dispatcher.py process was not found"
    fi
fi

echo ""
echo "Check complete"
