#!/bin/bash
# WordPress Bot Log Rotation Script
# Runs daily to manage log files

BOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="$BOT_DIR/bot.log"
LOG_DIR="$BOT_DIR"

echo "[$(date)] Starting log rotation..."

# 1. Rotate current log if > 10MB
if [ -f "$LOG_FILE" ]; then
    SIZE=$(du -m "$LOG_FILE" | cut -f1)
    if [ $SIZE -gt 10 ]; then
        mv "$LOG_FILE" "$LOG_FILE.$(date +%Y%m%d_%H%M%S)"
        touch "$LOG_FILE"
        echo "✓ Rotated bot.log (${SIZE}MB)"
    fi
fi

# 2. Compress old logs (>7 days)
find "$LOG_DIR" -name "bot.log.*" -type f ! -name "*.gz" -mtime +7 -exec gzip {} \;
echo "✓ Compressed logs older than 7 days"

# 3. Delete compressed logs (>30 days)
find "$LOG_DIR" -name "bot.log.*.gz" -type f -mtime +30 -delete
echo "✓ Deleted compressed logs older than 30 days"

# 4. Keep only last 5 uncompressed logs
ls -t "$LOG_DIR"/bot.log.* 2>/dev/null | grep -v ".gz$" | tail -n +6 | xargs -r rm
echo "✓ Kept only last 5 uncompressed logs"

# 5. Show current usage
echo "Current log usage:"
du -sh "$LOG_DIR"/bot.log* 2>/dev/null

echo "[$(date)] Log rotation completed"
