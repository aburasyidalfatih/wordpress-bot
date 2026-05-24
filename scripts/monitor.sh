#!/bin/bash
# Health check and monitoring script

BOT_URL="http://localhost:5000/health"
LOG_FILE="/home/ubuntu/wordpress-bot/monitor.log"
TELEGRAM_BOT_TOKEN=""  # Will be read from .env
TELEGRAM_CHAT_ID=""    # Will be read from .env

# Load env variables
if [ -f "/home/ubuntu/wordpress-bot/.env" ]; then
    export $(cat /home/ubuntu/wordpress-bot/.env | grep -v '^#' | xargs)
fi

# Check health endpoint
RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" $BOT_URL --max-time 10)

if [ "$RESPONSE" != "200" ]; then
    echo "[$(date)] ❌ Health check failed - HTTP $RESPONSE" >> $LOG_FILE
    
    # Try to restart service
    sudo systemctl restart wordpress-bot
    echo "[$(date)] 🔄 Service restarted" >> $LOG_FILE
    
    # Send alert if Telegram configured
    if [ ! -z "$TELEGRAM_BOT_TOKEN" ] && [ ! -z "$TELEGRAM_CHAT_ID" ]; then
        MESSAGE="🚨 <b>WordPress Bot Alert</b>%0A%0A❌ Health check failed%0A🔄 Service auto-restarted%0A⏰ $(date)"
        curl -s -X POST "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/sendMessage" \
            -d "chat_id=$TELEGRAM_CHAT_ID" \
            -d "text=$MESSAGE" \
            -d "parse_mode=HTML" > /dev/null
    fi
else
    echo "[$(date)] ✅ Health check passed" >> $LOG_FILE
fi

# Check disk space
DISK_USAGE=$(df -h /home/ubuntu/wordpress-bot | awk 'NR==2 {print $5}' | sed 's/%//')
if [ "$DISK_USAGE" -gt 80 ]; then
    echo "[$(date)] ⚠️ Disk usage high: ${DISK_USAGE}%" >> $LOG_FILE
fi

# Keep log file size under control
if [ -f "$LOG_FILE" ]; then
    tail -1000 $LOG_FILE > ${LOG_FILE}.tmp && mv ${LOG_FILE}.tmp $LOG_FILE
fi
