#!/bin/bash
# Automated backup script for WordPress Bot

BOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKUP_DIR="$BOT_DIR/backups"
DATE=$(date +%Y%m%d_%H%M%S)

set -a
[ -f "$BOT_DIR/.env" ] && . "$BOT_DIR/.env"
set +a

POSTGRES_USER="${POSTGRES_USER:-autowp}"
POSTGRES_DB="${POSTGRES_DB:-autowpdb}"

# Create backup directory if not exists
mkdir -p "$BACKUP_DIR"

# Backup PostgreSQL database
if command -v docker >/dev/null 2>&1 && docker compose ps postgres >/dev/null 2>&1; then
    docker compose exec -T postgres pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" > "$BACKUP_DIR/autowp_$DATE.sql"
    echo "✅ PostgreSQL database backed up: autowp_$DATE.sql"
else
    echo "⚠️ Docker compose postgres service not available. Skipping database backup."
fi

# Keep only last 7 days of backups
find "$BACKUP_DIR" -name "*.sql" -mtime +7 -delete
echo "✅ Old backups cleaned (kept last 7 days)"

# Backup logs
if [ -f "$BOT_DIR/bot.log" ]; then
    cp "$BOT_DIR/bot.log" "$BACKUP_DIR/bot_log_$DATE.log"
    echo "✅ Log backed up: bot_log_$DATE.log"
fi

echo "✅ Backup completed at $(date)"
