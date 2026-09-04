import os
from datetime import datetime
from flask import Blueprint, jsonify, send_file
import psutil

from core_extensions import db, logger, get_cached_stats, require_admin, redis_conn
from config import Config

monitor_bp = Blueprint('monitor', __name__)

# Must match dispatcher.py.
SCHEDULER_HEARTBEAT_KEY = 'scheduler:heartbeat'


def _scheduler_status():
    """Real scheduler state from the dispatcher's heartbeat.

    Previously this was hardcoded to True, so a dead dispatcher still showed as
    healthy — exactly when you most need to know it is not.
    """
    try:
        raw = redis_conn.get(SCHEDULER_HEARTBEAT_KEY)
    except Exception as e:
        logger.warning(f"Could not read scheduler heartbeat: {e}")
        return {'running': None, 'last_heartbeat': None, 'detail': 'Redis tidak dapat dihubungi'}

    if not raw:
        return {'running': False, 'last_heartbeat': None,
                'detail': 'Tidak ada heartbeat. Scheduler kemungkinan mati.'}

    last = raw.decode() if isinstance(raw, bytes) else str(raw)
    return {'running': True, 'last_heartbeat': last, 'detail': None}


def _queued_job_count():
    try:
        from core_extensions import q
        return q.count
    except Exception as e:
        logger.warning(f"Could not read queue depth: {e}")
        return None


def _database_size_mb():
    try:
        from sqlalchemy import text
        with db.get_session() as session:
            size = session.execute(
                text("SELECT pg_database_size(current_database())")
            ).scalar()
        return round((size or 0) / 1024 / 1024, 1)
    except Exception as e:
        logger.warning(f"Could not read database size: {e}")
        return None

@monitor_bp.route('/api/monitor')
@require_admin
def api_monitor(user_id):
    """Monitoring dashboard"""
    from flask import request
    site_id = request.args.get('site_id', type=int)
    stats = get_cached_stats(user_id, site_id=site_id)
    
    try:
        disk_percent = psutil.disk_usage('/').percent
    except OSError:
        disk_percent = psutil.disk_usage('C:\\').percent
    
    # Get system info
    system_info = {
        'cpu_percent': psutil.cpu_percent(interval=0.1),
        'memory_percent': psutil.virtual_memory().percent,
        'disk_percent': disk_percent,
        'uptime': str(datetime.now() - datetime.fromtimestamp(psutil.boot_time())).split('.')[0]
    }
    
    # Resolve log path dynamically using Config
    log_path = Config.LOG_FILE
    # If config file is a relative name, check common directories (like logs/)
    if not os.path.isabs(log_path):
        if os.path.exists(os.path.join('logs', log_path)):
            log_path = os.path.join('logs', log_path)
            
    log_size = os.path.getsize(log_path) / 1024 / 1024 if os.path.exists(log_path) else 0
    
    scheduler = _scheduler_status()
    service_info = {
        'scheduler_running': scheduler['running'],
        'scheduler_last_heartbeat': scheduler['last_heartbeat'],
        'scheduler_detail': scheduler['detail'],
        'scheduler_jobs': _queued_job_count(),
        'database_size': _database_size_mb(),
        'log_size': log_size
    }
    
    # Gemini status - don't test on page load, use cached status
    gemini_status = {'status': 'unknown', 'message': 'Check via API endpoint'}
    
    # Get recent errors from log (limit to last 50 lines for speed)
    recent_errors = []
    try:
        if os.path.exists(log_path):
            with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                # Read only last 10KB instead of whole file
                f.seek(0, 2)  # Go to end
                file_size = f.tell()
                f.seek(max(0, file_size - 10000), 0)
                lines = f.readlines()
                for line in lines[-50:]:
                    if 'ERROR' in line:
                        # Sanitize line to avoid exposing internal paths
                        sanitized = line.strip()
                        import re
                        sanitized = re.sub(r'(?:[a-zA-Z]:\\|/)[^\s]*\.(?:py|js|tsx?|html|css)', '[FILE]', sanitized)
                        recent_errors.append(sanitized)
    except Exception as e:
        logger.error(f"Error reading log file: {e}")
    
    return jsonify({
        'system_info': system_info,
        'service_info': service_info,
        'gemini_status': gemini_status,
        'recent_errors': recent_errors[-10:]
    })

@monitor_bp.route('/api/health-metrics')
@require_admin
def health_metrics(user_id):
    """API endpoint for real-time health metrics"""
    try:
        # Resolve log path dynamically
        log_path = Config.LOG_FILE
        if not os.path.isabs(log_path) and os.path.exists(os.path.join('logs', log_path)):
            log_path = os.path.join('logs', log_path)
            
        log_size = os.path.getsize(log_path) / 1024 / 1024 if os.path.exists(log_path) else 0
        
        try:
            _disk_percent = psutil.disk_usage('/').percent
        except OSError:
            _disk_percent = psutil.disk_usage('C:\\').percent
        
        scheduler = _scheduler_status()
        return jsonify({
            'timestamp': datetime.now().isoformat(),
            'service': {
                'status': 'healthy' if scheduler['running'] else 'degraded',
                'scheduler_running': scheduler['running'],
                'scheduler_last_heartbeat': scheduler['last_heartbeat'],
                'scheduler_detail': scheduler['detail'],
                'scheduler_jobs': _queued_job_count(),
                'log_size': log_size
            },
            'system': {
                'cpu_percent': psutil.cpu_percent(interval=0.1),
                'memory_percent': psutil.virtual_memory().percent,
                'disk_percent': _disk_percent
            }
        })
    except Exception as e:
        logger.error(f"Health metrics error: {e}")
        return jsonify({'error': 'Internal health check error occurred'}), 500

@monitor_bp.route('/download-logs')
@require_admin
def download_logs(user_id):
    """Download log file"""
    try:
        log_path = Config.LOG_FILE
        if not os.path.isabs(log_path) and os.path.exists(os.path.join('logs', log_path)):
            log_path = os.path.join('logs', log_path)
            
        if not os.path.exists(log_path):
            return jsonify({'error': 'Log file not found'}), 404
            
        return send_file(log_path, 
                        as_attachment=True,
                        download_name=f'bot_log_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log')
    except Exception as e:
        logger.error(f"Download logs error: {e}")
        return jsonify({'error': 'Could not read the log file'}), 500

@monitor_bp.route('/health')
def health():
    """Health check endpoint"""
    try:
        # Check DB connection
        with db.get_session() as session:
            from models import User
            session.query(User).first()
        
        redis_conn.ping()

        scheduler = _scheduler_status()
        return jsonify({
            'status': 'healthy' if scheduler['running'] else 'degraded',
            'scheduler_running': scheduler['running'],
            'database_connected': True,
            'redis_connected': True
        }), 200
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return jsonify({
            'status': 'unhealthy',
            'error': 'Internal health check error occurred'
        }), 500
