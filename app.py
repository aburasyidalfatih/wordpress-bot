import atexit
import os
import signal

from flask import Flask, request, send_from_directory, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.middleware.proxy_fix import ProxyFix

from config import Config
from core_extensions import db, logger, load_system_settings, refresh_system_settings_if_changed, decode_access_token
from routes.auth import auth_bp
from routes.queue import queue_bp
from routes.research import research_bp
from routes.dashboard import dashboard_bp
from routes.settings import settings_bp
from routes.monitor import monitor_bp
from routes.sites import sites_bp
from routes.prompts import prompts_bp
from routes.payments import payments_bp, tripay_webhook, get_payment_settings, tripay_is_mock, paypal_is_mock
from routes.admin import admin_bp
from routes.search_console import search_console_bp

# ---- Rate Limiting ----
# RATELIMIT_STORAGE_URI can be set via env var to point to Redis
_rate_limit_uri = os.getenv('RATELIMIT_STORAGE_URI', Config.REDIS_URL)

def _rate_limit_key():
    """Use user_id from JWT if available, otherwise fall back to IP."""
    try:
        token = request.cookies.get('auth_token') or (
            request.headers.get('Authorization', '').removeprefix('Bearer ')
        )
        if token:
            payload = decode_access_token(token)
            user_id = payload.get('user_id')
            if user_id:
                return f"user:{user_id}"
    except Exception:
        pass  # missing/invalid/expired token: limit by client IP instead
    return get_remote_address()

limiter = Limiter(
    key_func=_rate_limit_key,
    storage_uri=_rate_limit_uri,
    default_limits=["5000 per day", "1000 per hour"],
    strategy="fixed-window"
)
# ---- End Rate Limiting ----

# Load system settings from database and override Config values on startup.
# Later admin edits are picked up per worker by refresh_system_settings_if_changed().
try:
    load_system_settings()
except Exception as e:
    logger.error(f"Failed to load system settings from database: {e}")


def _warn_on_sandbox_payment_urls():
    """Loudly flag live payment credentials still pointed at a sandbox endpoint.

    Both gateway URLs default to sandbox, so a deployment that sets real API keys
    but forgets the URL would silently transact against sandbox.
    """
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

# Traefik sits in front of gunicorn. Trust exactly that many hops of X-Forwarded-*
# so request.remote_addr (rate limiting) and the scheme/host are the client's.
try:
    _trusted_proxy_count = max(0, int(os.getenv('TRUSTED_PROXY_COUNT', '1')))
except ValueError:
    _trusted_proxy_count = 1
if _trusted_proxy_count:
    app.wsgi_app = ProxyFix(
        app.wsgi_app,
        x_for=_trusted_proxy_count,
        x_proto=_trusted_proxy_count,
        x_host=_trusted_proxy_count,
    )

limiter.init_app(app)

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
app.register_blueprint(search_console_bp)

# Tripay callbacks all come from Tripay's own IPs and are HMAC-verified; the
# per-IP default limits would otherwise start rejecting real payment callbacks.
limiter.exempt(tripay_webhook)


@app.before_request
def refresh_settings_from_other_workers():
    """Re-apply system settings saved by another gunicorn worker (throttled)."""
    refresh_system_settings_if_changed()


@app.errorhandler(413)
def request_too_large(e):
    limit_mb = (app.config.get('MAX_CONTENT_LENGTH') or 0) // (1024 * 1024)
    return jsonify({'success': False, 'error': f'Ukuran permintaan terlalu besar (maksimal {limit_mb} MB).'}), 413


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
    # Client-side routes (e.g. /billing) are handled by the SPA.
    return send_from_directory(frontend_dir, 'index.html')


# Uploaded receipts that may be displayed inline; anything else is forced to download.
UPLOAD_INLINE_MIMETYPES = {'image/jpeg', 'image/png', 'image/webp'}


@app.after_request
def add_security_headers(response):
    """Add security headers to all responses."""
    response.headers.setdefault('X-Content-Type-Options', 'nosniff')
    response.headers.setdefault('X-Frame-Options', 'DENY')
    response.headers.setdefault('X-XSS-Protection', '1; mode=block')
    response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
    response.headers.setdefault('Permissions-Policy', 'camera=(), microphone=(), geolocation=()')
    if request.path.startswith('/static/uploads/'):
        # User-uploaded files: never let them execute script on the app origin.
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Content-Security-Policy'] = "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; sandbox"
        mimetype = response.mimetype or ''
        if mimetype not in UPLOAD_INLINE_MIMETYPES:
            response.headers['Content-Disposition'] = 'attachment'
        return response
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
