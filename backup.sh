#!/bin/bash
# Automated backup script for WordPress Bot

BACKUP_DIR="/home/ubuntu/wordpress-bot/backups"
DATE=$(date +%Y%m%d_%H%M%S)
DB_FILE="/home/ubuntu/wordpress-bot/wordpress_bot.db"
SCHEDULER_DB="/home/ubuntu/wordpress-bot/scheduler_jobs.db"

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
if [ -f "/home/ubuntu/wordpress-bot/bot.log" ]; then
    cp /home/ubuntu/wordpress-bot/bot.log "$BACKUP_DIR/bot_log_$DATE.log"
    echo "✅ Log backed up: bot_log_$DATE.log"
fi

echo "✅ Backup completed at $(date)"
