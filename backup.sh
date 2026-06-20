#!/bin/bash
# Automated backup script for WordPress Bot

BOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKUP_DIR="$BOT_DIR/backups"
DATE=$(date +%Y%m%d_%H%M%S)
DB_FILE="$BOT_DIR/wordpress_bot.db"
SCHEDULER_DB="$BOT_DIR/scheduler_jobs.db"

# Create backup directory if not exists
mkdir -p $BACKUP_DIR

# Backup databases
if [ -f "$DB_FILE" ]; then
    cp $DB_FILE "$BACKUP_DIR/wordpress_bot_$DATE.db"
    echo "✅ Database backed up: wordpress_bot_$DATE.db"
fi

if [ -f "$SCHEDULER_DB" ]; then
    cp $SCHEDULER_DB "$BACKUP_DIR/scheduler_jobs_$DATE.db"
    echo "✅ Scheduler DB backed up: scheduler_jobs_$DATE.db"
fi

# Keep only last 7 days of backups
find $BACKUP_DIR -name "*.db" -mtime +7 -delete
echo "✅ Old backups cleaned (kept last 7 days)"

# Backup logs
if [ -f "$BOT_DIR/bot.log" ]; then
    cp "$BOT_DIR/bot.log" "$BACKUP_DIR/bot_log_$DATE.log"
    echo "✅ Log backed up: bot_log_$DATE.log"
fi

echo "✅ Backup completed at $(date)"
