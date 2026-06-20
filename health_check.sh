#!/bin/bash
# Comprehensive health check script

BOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOT_URL="http://localhost:5000/health"
LOG_FILE="$BOT_DIR/health_check.log"

# Load env
if [ -f "$BOT_DIR/.env" ]; then
    export $(cat $BOT_DIR/.env | grep -v '^#' | xargs)
fi

# Function to send Telegram alert
send_alert() {
    local message=$1
    if [ ! -z "$TELEGRAM_BOT_TOKEN" ] && [ ! -z "$TELEGRAM_CHAT_ID" ]; then
        curl -s -X POST "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/sendMessage" \
            -d "chat_id=$TELEGRAM_CHAT_ID" \
            -d "text=$message" \
            -d "parse_mode=HTML" > /dev/null
    fi
}

# Check 1: Health endpoint
HEALTH_CODE=$(curl -s -o /dev/null -w "%{http_code}" $BOT_URL --max-time 10)
if [ "$HEALTH_CODE" != "200" ]; then
    echo "[$(date)] ❌ Health check failed - HTTP $HEALTH_CODE" >> $LOG_FILE
    sudo systemctl restart wordpress-bot
    echo "[$(date)] 🔄 Service restarted" >> $LOG_FILE
    send_alert "🚨 <b>Bot Health Alert</b>%0A%0A❌ Health check failed (HTTP $HEALTH_CODE)%0A🔄 Service auto-restarted%0A⏰ $(date)"
    exit 1
fi

# Check 2: Process running
if ! pgrep -f "wordpress-bot/app.py" > /dev/null; then
    echo "[$(date)] ❌ Process not running" >> $LOG_FILE
    sudo systemctl restart wordpress-bot
    echo "[$(date)] 🔄 Service restarted" >> $LOG_FILE
    send_alert "🚨 <b>Bot Process Alert</b>%0A%0A❌ Process not found%0A🔄 Service auto-restarted%0A⏰ $(date)"
    exit 1
fi

# Check 3: Database accessible
if [ -f "$BOT_DIR/wordpress_bot.db" ]; then
    if ! sqlite3 "$BOT_DIR/wordpress_bot.db" "SELECT 1;" > /dev/null 2>&1; then
        echo "[$(date)] ❌ Database not accessible" >> $LOG_FILE
        send_alert "🚨 <b>Database Alert</b>%0A%0A❌ Database not accessible%0A⏰ $(date)"
    fi
fi

# Check 4: Disk space
DISK_USAGE=$(df -h / | awk 'NR==2 {print $5}' | sed 's/%//')
if [ "$DISK_USAGE" -gt 90 ]; then
    echo "[$(date)] ⚠️ Critical disk usage: ${DISK_USAGE}%" >> $LOG_FILE
    send_alert "🔴 <b>Critical Disk Alert</b>%0A%0A📊 Usage: ${DISK_USAGE}%%0A⚠️ Threshold: 90%%0A⏰ $(date)"
fi

# Check 5: Memory usage
MEM_USAGE=$(free | grep Mem | awk '{print int($3/$2 * 100)}')
if [ "$MEM_USAGE" -gt 90 ]; then
    echo "[$(date)] ⚠️ High memory usage: ${MEM_USAGE}%" >> $LOG_FILE
    send_alert "⚠️ <b>Memory Alert</b>%0A%0A📊 Usage: ${MEM_USAGE}%%0A⏰ $(date)"
fi

# All checks passed
echo "[$(date)] ✅ All health checks passed" >> $LOG_FILE

# Keep log size under control
if [ -f "$LOG_FILE" ]; then
    tail -2000 $LOG_FILE > ${LOG_FILE}.tmp && mv ${LOG_FILE}.tmp $LOG_FILE
fi
