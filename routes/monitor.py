import os
from datetime import datetime
from flask import Blueprint, jsonify, send_file
import psutil

from core_extensions import db, logger, get_cached_stats, require_jwt, load_config
from config import Config

monitor_bp = Blueprint('monitor', __name__)

@monitor_bp.route('/api/monitor')
@require_jwt
def api_monitor(user_id):
    """Monitoring dashboard"""
    from flask import request
    site_id = request.args.get('site_id', type=int)
    stats = get_cached_stats(user_id, site_id=site_id)
    
    # Get system info
    system_info = {
        'cpu_percent': psutil.cpu_percent(interval=0.1),
        'memory_percent': psutil.virtual_memory().percent,
        'disk_percent': psutil.disk_usage('/').percent,
        'uptime': str(datetime.now() - datetime.fromtimestamp(psutil.boot_time())).split('.')[0]
    }
    
    # Resolve log path dynamically using Config
    log_path = Config.LOG_FILE
    # If config file is a relative name, check common directories (like logs/)
    if not os.path.isabs(log_path):
        if os.path.exists(os.path.join('logs', log_path)):
            log_path = os.path.join('logs', log_path)
            
    log_size = os.path.getsize(log_path) / 1024 / 1024 if os.path.exists(log_path) else 0
    
    # Get service info
    service_info = {
        'scheduler_running': True,
        'scheduler_jobs': len([]),
        'database_size': 0,  # Size not tracked locally
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
                        recent_errors.append(line.strip())
    except Exception as e:
        logger.error(f"Error reading log file: {e}")
    
    return jsonify({
        'system_info': system_info,
        'service_info': service_info,
        'gemini_status': gemini_status,
        'recent_errors': recent_errors[-10:]
    })

@monitor_bp.route('/api/health-metrics')
def health_metrics():
    """API endpoint for real-time health metrics"""
    try:
        # Resolve log path dynamically
        log_path = Config.LOG_FILE
        if not os.path.isabs(log_path) and os.path.exists(os.path.join('logs', log_path)):
            log_path = os.path.join('logs', log_path)
            
        log_size = os.path.getsize(log_path) / 1024 / 1024 if os.path.exists(log_path) else 0
        
        return jsonify({
            'timestamp': datetime.now().isoformat(),
            'service': {
                'status': 'healthy',
                'scheduler_running': True,
                'scheduler_jobs': len([]),
                'log_size': log_size
            },
            'system': {
                'cpu_percent': psutil.cpu_percent(interval=0.1),
                'memory_percent': psutil.virtual_memory().percent,
                'disk_percent': psutil.disk_usage('/').percent
            }
        })
    except Exception as e:
        logger.error(f"Health metrics error: {e}")
        return jsonify({'error': str(e)}), 500

@monitor_bp.route('/download-logs')
@require_jwt
def download_logs():
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
        return jsonify({'error': str(e)}), 500

@monitor_bp.route('/health')
def health():
    """Health check endpoint"""
    try:
        # Check DB connection
        with db.get_session() as session:
            from database import User
            session.query(User).first()
        
        # Check Redis connection
        from core_extensions import redis_conn
        redis_conn.ping()
        
        return jsonify({
            'status': 'healthy',
            'scheduler_running': True,
            'database_connected': True,
            'redis_connected': True
        }), 200
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return jsonify({
            'status': 'unhealthy',
            'error': str(e)
        }), 500
