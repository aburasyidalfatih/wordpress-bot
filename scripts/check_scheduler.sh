#!/bin/bash
# WordPress Bot Scheduler Monitor
# Checks if bot is running and scheduler is active

echo "🔍 Checking WordPress Bot Scheduler..."
echo ""

BOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Check if bot is running
if lsof -i :5003 >/dev/null 2>&1; then
    PID=$(lsof -ti :5003)
    UPTIME=$(ps -p $PID -o etime= 2>/dev/null | tr -d ' ')
    echo "✅ Bot Running (PID: $PID, Uptime: $UPTIME)"
else
    echo "❌ Bot NOT running!"
    echo "   Restarting..."
    cd "$BOT_DIR"
    source venv/bin/activate
    nohup python app.py > dashboard.log 2>&1 &
    sleep 3
    echo "✅ Bot restarted"
fi

# Check scheduler config
cd "$BOT_DIR"
source venv/bin/activate
python3 << 'EOF'
import sqlite3
from datetime import datetime
import pytz

conn = sqlite3.connect('wordpress_bot.db')
cursor = conn.cursor()
cursor.execute("SELECT auto_post, schedule_hours FROM config LIMIT 1")
config = cursor.fetchone()
conn.close()

if config:
    auto_post, schedule_hours = config
    if auto_post:
        hours = [int(h.strip()) for h in schedule_hours.split(',')]
        wib = pytz.timezone('Asia/Jakarta')
        now = datetime.now(wib)
        current_hour = now.hour
        
        next_hours = [h for h in hours if h > current_hour]
        if next_hours:
            next_hour = next_hours[0]
            hours_left = next_hour - current_hour
        else:
            next_hour = hours[0]
            hours_left = (24 - current_hour) + next_hour
        
        print(f"✅ Scheduler Active")
        print(f"   Next post: {next_hour:02d}:00 WIB ({hours_left}h)")
    else:
        print("⚠️  Auto-post disabled")
else:
    print("❌ No config found")
EOF

echo ""
echo "✅ Check complete"
