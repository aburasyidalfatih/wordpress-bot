import os
import re
from datetime import datetime
from flask import Blueprint, jsonify, send_file
import psutil
from sqlalchemy import text

from core_extensions import db, q, logger, require_admin, redis_conn
from config import Config
from models import User

monitor_bp = Blueprint('monitor', __name__)

# Must match dispatcher.py.
SCHEDULER_HEARTBEAT_KEY = 'scheduler:heartbeat'
SOURCE_PATH_RE = re.compile(r'(?:[a-zA-Z]:\\|/)[^\s]*\.(?:py|js|tsx?|html|css)')
HEALTH_CHECK_ERROR = 'Terjadi kesalahan internal pada pemeriksaan kesehatan sistem.'


def _log_path():
    """Config.LOG_FILE, preferring logs/<name> when the name is relative and that file exists."""
    log_path = Config.LOG_FILE
    if not os.path.isabs(log_path) and os.path.exists(os.path.join('logs', log_path)):
        log_path = os.path.join('logs', log_path)
    return log_path


def _log_size_mb(log_path):
    return os.path.getsize(log_path) / 1024 / 1024 if os.path.exists(log_path) else 0


def _disk_percent():
    try:
        return psutil.disk_usage('/').percent
    except OSError:
        return psutil.disk_usage('C:\\').percent


def _recent_errors(log_path, limit=10):
    """ERROR lines from the tail of the log, with source file paths masked."""
    recent_errors = []
    try:
        if os.path.exists(log_path):
            with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                # Read only the last 10KB instead of the whole file.
                f.seek(0, 2)
                file_size = f.tell()
                f.seek(max(0, file_size - 10000), 0)
                for line in f.readlines()[-50:]:
                    if 'ERROR' in line:
                        # Avoid exposing internal paths.
                        recent_errors.append(SOURCE_PATH_RE.sub('[FILE]', line.strip()))
    except Exception as e:
        logger.error(f"Error reading log file: {e}")
    return recent_errors[-limit:]


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
        return q.count
    except Exception as e:
        logger.warning(f"Could not read queue depth: {e}")
        return None


def _database_size_mb():
    try:
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
    system_info = {
        'cpu_percent': psutil.cpu_percent(interval=0.1),
        'memory_percent': psutil.virtual_memory().percent,
        'disk_percent': _disk_percent(),
        'uptime': str(datetime.now() - datetime.fromtimestamp(psutil.boot_time())).split('.')[0]
    }

    log_path = _log_path()
    scheduler = _scheduler_status()
    service_info = {
        'scheduler_running': scheduler['running'],
        'scheduler_last_heartbeat': scheduler['last_heartbeat'],
        'scheduler_detail': scheduler['detail'],
        'scheduler_jobs': _queued_job_count(),
        'database_size': _database_size_mb(),
        'log_size': _log_size_mb(log_path)
    }

    # Gemini status - don't test on page load, use cached status
    gemini_status = {'status': 'unknown', 'message': 'Periksa melalui endpoint API.'}

    return jsonify({
        'system_info': system_info,
        'service_info': service_info,
        'gemini_status': gemini_status,
        'recent_errors': _recent_errors(log_path)
    })

@monitor_bp.route('/api/health-metrics')
@require_admin
def health_metrics(user_id):
    """API endpoint for real-time health metrics"""
    try:
        log_size = _log_size_mb(_log_path())
        disk_percent = _disk_percent()
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
                'disk_percent': disk_percent
            }
        })
    except Exception as e:
        logger.error(f"Health metrics error: {e}")
        return jsonify({'error': HEALTH_CHECK_ERROR}), 500

@monitor_bp.route('/download-logs')
@require_admin
def download_logs(user_id):
    """Download log file"""
    try:
        log_path = _log_path()
        if not os.path.exists(log_path):
            return jsonify({'error': 'File log tidak ditemukan.'}), 404

        return send_file(log_path,
                        as_attachment=True,
                        download_name=f'bot_log_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log')
    except Exception as e:
        logger.error(f"Download logs error: {e}")
        return jsonify({'error': 'Gagal membaca file log.'}), 500

@monitor_bp.route('/health')
def health():
    """Health check endpoint"""
    try:
        # Check DB connection
        with db.get_session() as session:
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
            'error': HEALTH_CHECK_ERROR
        }), 500
