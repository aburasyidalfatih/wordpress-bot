from flask import Flask, request, send_from_directory
from dotenv import load_dotenv
import os
import signal
import atexit
import jwt

from config import Config
from core_extensions import db, logger

# ---- Rate Limiting ----
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# RATELIMIT_STORAGE_URI can be set via env var to point to Redis
_rate_limit_uri = os.getenv('RATELIMIT_STORAGE_URI', Config.REDIS_URL)

def _rate_limit_key():
    """Use user_id from JWT if available, otherwise fall back to IP."""
    try:
        token = request.cookies.get('auth_token') or (
            request.headers.get('Authorization', '').removeprefix('Bearer ')
        )
        if token:
            payload = jwt.decode(token, Config.SECRET_KEY, algorithms=['HS256'])
            user_id = payload.get('user_id')
            if user_id:
                return f"user:{user_id}"
    except Exception:
        pass
    return get_remote_address()

limiter = Limiter(
    key_func=_rate_limit_key,
    storage_uri=_rate_limit_uri,
    default_limits=["5000 per day", "1000 per hour"],
    strategy="fixed-window"
)
# ---- End Rate Limiting ----

# Import blueprints
from routes.auth import auth_bp
from routes.queue import queue_bp
from routes.research import research_bp
from routes.dashboard import dashboard_bp
from routes.settings import settings_bp
from routes.monitor import monitor_bp
from routes.sites import sites_bp
from routes.prompts import prompts_bp
from routes.payments import payments_bp
from routes.admin import admin_bp

load_dotenv()

# Load system settings from database and override Config values on startup
try:
    system_settings = db.get_system_settings()
    for k, v in system_settings.items():
        if k.startswith('__'):
            continue  # internal bookkeeping (e.g. __schema_version__), not app config
        if v is not None:
            if k in ['PAYMENT_TRIPAY_ENABLED', 'PAYMENT_PAYPAL_ENABLED', 'PAYMENT_MANUAL_ENABLED']:
                setattr(Config, k, v.lower() == 'true')
            elif k == 'SMTP_PORT':
                try:
                    setattr(Config, k, int(v))
                except ValueError:
                    pass
            elif k == 'PAYMENT_USD_RATE':
                try:
                    setattr(Config, k, float(v))
                except ValueError:
                    pass
            else:
                setattr(Config, k, v)
            os.environ[k] = v
    logger.info(f"Loaded {len(system_settings)} system settings from database.")
except Exception as e:
    logger.error(f"Failed to load system settings from database: {e}")


def _warn_on_sandbox_payment_urls():
    """Loudly flag live payment credentials still pointed at a sandbox endpoint.

    Both gateway URLs default to sandbox, so a deployment that sets real API keys
    but forgets the URL would silently transact against sandbox.
    """
    from routes.payments import get_payment_settings, tripay_is_mock, paypal_is_mock

    settings = get_payment_settings()

    if not tripay_is_mock(settings) and 'sandbox' in (settings['TRIPAY_API_URL'] or '').lower():
        logger.warning(
            "PAYMENT MISCONFIGURATION: live Tripay credentials are configured but "
            f"TRIPAY_API_URL still points at sandbox ({settings['TRIPAY_API_URL']}). "
            "Real payments will NOT be processed."
        )
    if not paypal_is_mock(settings) and 'sandbox' in (settings['PAYPAL_API_URL'] or '').lower():
        logger.warning(
            "PAYMENT MISCONFIGURATION: live PayPal credentials are configured but "
            f"PAYPAL_API_URL still points at sandbox ({settings['PAYPAL_API_URL']}). "
            "Real payments will NOT be processed."
        )


try:
    _warn_on_sandbox_payment_urls()
except Exception as e:
    logger.error(f"Could not check payment gateway URLs: {e}")

app = Flask(__name__)
app.config.from_object(Config)
limiter.init_app(app)

from security import generate_csrf_token
app.jinja_env.globals['csrf_token'] = generate_csrf_token

# Register Blueprints
app.register_blueprint(auth_bp)
app.register_blueprint(queue_bp)
app.register_blueprint(research_bp)
app.register_blueprint(dashboard_bp)
app.register_blueprint(settings_bp)
app.register_blueprint(monitor_bp)
app.register_blueprint(sites_bp)
app.register_blueprint(prompts_bp)
app.register_blueprint(payments_bp)
app.register_blueprint(admin_bp)

# Background tasks & workers retained in app namespace for RQ compatibility

def shutdown():
    """Graceful shutdown"""
    logger.info("Shutting down gracefully...")
    try:
        db.close()
        logger.info("Shutdown complete")
    except Exception as e:
        logger.error(f"Error during shutdown: {e}")


# Register shutdown handlers
atexit.register(shutdown)
signal.signal(signal.SIGTERM, lambda s, f: (shutdown(), os._exit(0)))
signal.signal(signal.SIGINT, lambda s, f: (shutdown(), os._exit(0)))


# Static frontend serving
@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
@limiter.exempt
def serve_frontend(path):
    frontend_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'frontend', 'dist')
    if path != "" and os.path.exists(os.path.join(frontend_dir, path)):
        return send_from_directory(frontend_dir, path)
    else:
        return send_from_directory(frontend_dir, 'index.html')


@app.after_request
def add_security_headers(response):
    """Add security headers to all responses."""
    response.headers.setdefault('X-Content-Type-Options', 'nosniff')
    response.headers.setdefault('X-Frame-Options', 'DENY')
    response.headers.setdefault('X-XSS-Protection', '1; mode=block')
    response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
    response.headers.setdefault('Permissions-Policy', 'camera=(), microphone=(), geolocation=()')
    # CSP: allow self, google APIs (fonts/auth), and inline styles for dynamic content
    if 'Content-Type' in response.headers and 'text/html' in response.headers['Content-Type']:
        response.headers.setdefault(
            'Content-Security-Policy',
            "default-src 'self'; script-src 'self' 'unsafe-inline' https://accounts.google.com https://static.cloudflareinsights.com; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data: blob: https:; connect-src 'self' https:; frame-src 'self' https://www.youtube.com;"
        )
    return response


if __name__ == '__main__':
    # Production mode
    app.run(debug=False, host='0.0.0.0', port=5005)
