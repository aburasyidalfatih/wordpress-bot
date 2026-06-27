# 🔍 MONITORING DASHBOARD - USER GUIDE

## Overview

Monitoring Dashboard adalah fitur baru yang memungkinkan Anda memantau kesehatan aplikasi secara real-time langsung dari UI.

---

## 🎯 Features

### Real-Time Metrics (Auto-refresh 5 detik)

1. **Service Status**
   - Health status (Healthy/Unhealthy)
   - Scheduler status (Running/Stopped)
   - Active jobs count
   - Auto-post status

2. **System Resources**
   - CPU usage (%)
   - Memory usage (%)
   - Disk usage (%)
   - Visual progress bars dengan color coding:
     - 🟢 Green: < 70% (Normal)
     - 🟡 Yellow: 70-90% (Warning)
     - 🔴 Red: > 90% (Critical)

3. **Database Info**
   - Connection status
   - Database size (MB)
   - Log file size (MB)
   - Total posts count

4. **Performance Stats**
   - Total posts
   - Successful posts
   - Failed posts
   - Success rate (%)

5. **Recent Errors**
   - Last 10 error messages from log
   - Real-time error monitoring

---

## 🚀 How to Access

### Via Web UI
```
http://YOUR_IP:5003/monitor
```

### Via Navigation
1. Open dashboard: `http://YOUR_IP:5003`
2. Click "🔍 Monitor" in navigation menu

---

## 📊 API Endpoints

### Health Check
```bash
curl http://localhost:5003/health
```

Response:
```json
{
    "status": "healthy",
    "scheduler_running": true,
    "database_connected": true,
    "total_posts": 5
}
```

### Health Metrics (Detailed)
```bash
curl http://localhost:5003/api/health-metrics
```

Response:
```json
{
    "timestamp": "2026-03-03T08:13:18.736405",
    "service": {
        "status": "healthy",
        "scheduler_running": true,
        "scheduler_jobs": 1
    },
    "system": {
        "cpu_percent": 20.0,
        "memory_percent": 27.9,
        "disk_percent": 65.8
    },
    "database": {
        "connected": true,
        "size_mb": 0.01
    },
    "stats": {
        "total_posts": 5,
        "successful_posts": 5,
        "failed_posts": 0
    }
}
```

---

## 🔧 Quick Actions

### 1. Refresh Now
- Manual refresh metrics
- Useful for immediate status check

### 2. Health Check
- Opens `/health` endpoint in new tab
- Shows raw JSON health data

### 3. Download Logs
- Downloads current log file
- Filename: `bot_log_YYYYMMDD_HHMMSS.log`
- Useful for offline analysis

---

## 📈 Monitoring Best Practices

### Daily Checks
- [ ] Check health status (should be "Healthy")
- [ ] Verify scheduler is running
- [ ] Check system resources (< 70%)
- [ ] Review recent errors

### Warning Signs

🟡 **Warning Level**
- CPU > 70%
- Memory > 70%
- Disk > 70%
- Success rate < 90%

🔴 **Critical Level**
- CPU > 90%
- Memory > 90%
- Disk > 90%
- Scheduler stopped
- Health status "Unhealthy"

### Actions on Warnings

**High CPU/Memory:**
```bash
# Check processes
htop

# Restart service
sudo systemctl restart wordpress-bot
```

**High Disk Usage:**
```bash
# Clean old backups
find /home/ubuntu/wordpress-bot/backups/ -mtime +7 -delete

# Rotate logs
cd /home/ubuntu/wordpress-bot
mv bot.log bot.log.old
sudo systemctl restart wordpress-bot
```

**Scheduler Stopped:**
```bash
# Check logs
tail -100 /home/ubuntu/wordpress-bot/bot.log

# Restart service
sudo systemctl restart wordpress-bot
```

---

## 🔔 Alert Thresholds

### Automatic Monitoring (via monitor.sh)
- Runs every 5 minutes
- Auto-restarts on health check failure
- Sends Telegram alert (if configured)

### Manual Monitoring (via Dashboard)
- Real-time updates every 5 seconds
- Visual indicators for quick assessment
- Error log streaming

---

## 📱 Mobile Access

Dashboard is mobile-responsive:
- Access from phone/tablet
- Same URL: `http://YOUR_IP:5003/monitor`
- Auto-refresh works on mobile
- Touch-friendly interface

---

## 🔐 Security Notes

- Monitor page requires same access as dashboard
- No authentication by default (add if needed)
- Consider using VPN for remote access
- Don't expose port 5003 to public internet

---

## 🐛 Troubleshooting

### Monitor Page Not Loading
```bash
# Check service
sudo systemctl status wordpress-bot

# Check logs
tail -50 /home/ubuntu/wordpress-bot/bot.log

# Restart service
sudo systemctl restart wordpress-bot
```

### Metrics Not Updating
- Check browser console for errors
- Verify `/api/health-metrics` endpoint works:
  ```bash
  curl http://localhost:5003/api/health-metrics
  ```
- Clear browser cache
- Try different browser

### High Resource Usage
```bash
# Check what's using resources
htop

# Check database size
ls -lh /home/ubuntu/wordpress-bot/*.db

# Check log size
ls -lh /home/ubuntu/wordpress-bot/bot.log
```

---

## 📊 Integration with External Monitoring

### Prometheus
```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'wordpress-bot'
    metrics_path: '/api/health-metrics'
    static_configs:
      - targets: ['localhost:5003']
```

### Uptime Robot
- Monitor URL: `http://YOUR_IP:5003/health`
- Check interval: 5 minutes
- Alert on: Status != 200

### Grafana
- Use Prometheus as data source
- Create dashboard with:
  - CPU/Memory/Disk graphs
  - Success rate gauge
  - Error count panel

---

## 🎨 Customization

### Change Refresh Interval
Edit `/home/ubuntu/wordpress-bot/templates/monitor.html`:
```javascript
// Change from 5000ms (5s) to desired interval
setInterval(refreshMetrics, 10000); // 10 seconds
```

### Add Custom Metrics
Edit `/home/ubuntu/wordpress-bot/app.py`:
```python
@app.route('/api/health-metrics')
def health_metrics():
    # Add your custom metrics here
    return jsonify({
        # ... existing metrics
        'custom': {
            'your_metric': value
        }
    })
```

---

## 📝 Changelog

### Version 2.1 (2026-03-03)
- ✅ Added monitoring dashboard
- ✅ Real-time metrics API
- ✅ Auto-refresh every 5 seconds
- ✅ System resource monitoring
- ✅ Error log streaming
- ✅ Download logs feature
- ✅ Mobile-responsive design

---

## 🎯 Next Steps

1. Access monitor page: `http://YOUR_IP:5003/monitor`
2. Bookmark for quick access
3. Check daily for health status
4. Set up external monitoring (optional)
5. Configure alerts (optional)

---

**Last Updated**: 2026-03-03
**Version**: 2.1
**Status**: ✅ PRODUCTION READY
