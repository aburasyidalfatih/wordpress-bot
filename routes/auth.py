import os
from flask import Blueprint, request, jsonify, make_response
from flask import session
from werkzeug.security import check_password_hash
import requests

from core_extensions import (
    db, logger, require_jwt, send_email_notification, send_whatsapp_notification, redis_conn,
    issue_access_token, revoke_token, decode_access_token, get_request_token,
)
from config import Config

auth_bp = Blueprint('auth', __name__)

LOGIN_MAX_FAILURES_PER_ACCOUNT = 5
LOGIN_MAX_FAILURES_PER_IP = 30
LOGIN_FAILURE_WINDOW_SECONDS = 300

def _login_rate_limit_keys(email):
    """Failed-login counters: one per IP+email (lockout) and a looser one per IP (spraying)."""
    client_ip = request.remote_addr or '127.0.0.1'
    normalized_email = (email or '').strip().lower()
    return (
        (f"ratelimit:login:{client_ip}:{normalized_email}", LOGIN_MAX_FAILURES_PER_ACCOUNT),
        (f"ratelimit:login-ip:{client_ip}", LOGIN_MAX_FAILURES_PER_IP),
    )

def _check_rate_limit(email):
    """Returns (is_allowed, retry_after_seconds). Only failed attempts are counted."""
    if redis_conn is None:
        return True, 0
    try:
        for key, max_failures in _login_rate_limit_keys(email):
            current = redis_conn.get(key)
            if current and int(current) >= max_failures:
                ttl = redis_conn.ttl(key)
                return False, max(ttl, 1)
    except Exception as e:
        logger.warning(f"Login rate limit check failed: {e}")
    return True, 0

def _record_failed_login(email):
    if redis_conn is None:
        return
    try:
        pipe = redis_conn.pipeline()
        for key, _ in _login_rate_limit_keys(email):
            pipe.incr(key)
            pipe.expire(key, LOGIN_FAILURE_WINDOW_SECONDS)
        pipe.execute()
    except Exception as e:
        logger.warning(f"Could not record failed login: {e}")

def _clear_failed_logins(email):
    if redis_conn is None:
        return
    try:
        redis_conn.delete(_login_rate_limit_keys(email)[0][0])
    except Exception as e:
        logger.warning(f"Could not clear failed login counter: {e}")

def is_configured_admin_email(email):
    return (email or '').strip().lower() in Config.ADMIN_EMAILS

def configured_google_client_id():
    client_id = Config.GOOGLE_CLIENT_ID
    try:
        system_settings = db.get_system_settings()
        if system_settings.get('GOOGLE_CLIENT_ID'):
            client_id = system_settings['GOOGLE_CLIENT_ID']
    except Exception as e:
        logger.error(f"Error reading Google client ID from system settings: {e}")
    return client_id or ''

GOOGLE_ISSUERS = ('accounts.google.com', 'https://accounts.google.com')

def verify_google_token(token):
    client_id = configured_google_client_id()
    if not client_id:
        # Without an expected audience any Google ID token (minted for any app)
        # would be accepted, so refuse rather than skip the check.
        logger.error("Rejected Google login: GOOGLE_CLIENT_ID is not configured")
        return None
    try:
        resp = requests.get("https://oauth2.googleapis.com/tokeninfo", params={'id_token': token}, timeout=10)
        if resp.status_code == 200:
            token_info = resp.json()
            if token_info.get('aud') != client_id:
                logger.warning("Rejected Google token with invalid audience")
                return None
            if token_info.get('iss') not in GOOGLE_ISSUERS:
                logger.warning("Rejected Google token with invalid issuer")
                return None
            if str(token_info.get('email_verified', '')).lower() != 'true':
                logger.warning("Rejected Google token with unverified email")
                return None
            return token_info
    except Exception as e:
        logger.error(f"Google token verification error: {e}")
    return None

@auth_bp.route('/api/register', methods=['POST'])
def api_auth_register():
    return jsonify({'success': False, 'error': 'Pendaftaran manual dinonaktifkan. Silakan mendaftar menggunakan Google Login.'}), 403

@auth_bp.route('/api/auth/google', methods=['POST'])
def api_auth_google():
    data = request.json or {}
    id_token = data.get('id_token')
    if not id_token:
        return jsonify({'success': False, 'error': 'id_token is required'}), 400
    if not configured_google_client_id():
        return jsonify({'success': False, 'error': 'Google login is not configured. Contact the administrator.'}), 503

    token_info = verify_google_token(id_token)
    if not token_info:
        return jsonify({'success': False, 'error': 'Invalid Google token'}), 400

    email = token_info.get('email')
    google_id = token_info.get('sub')
    name = token_info.get('name', '')

    if not email:
        return jsonify({'success': False, 'error': 'Google token did not provide an email'}), 400

    with db.get_session() as session:
        from models import User
        user = session.query(User).filter_by(google_id=google_id).first()
        if not user:
            user = session.query(User).filter_by(email=email).first()
            if user and user.google_id and user.google_id != google_id:
                return jsonify({'success': False, 'error': 'Email is already linked to another Google account'}), 400

        if not user:
            user_count = session.query(User).count()
            role = 'admin' if (user_count == 0 or is_configured_admin_email(email)) else 'user'

            user = User(
                email=email,
                name=name,
                google_id=google_id,
                role=role,
                tier='free',
                credits=5,
                is_active=True
            )
            session.add(user)
            session.commit()

            from database import Config as DBConfig
            config = DBConfig(user_id=user.id, gemini_api_key='', gemini_model='gemini-3.5-flash')
            session.add(config)
            session.commit()

            logger.info(f"Registered new user via Google: {email} with role {role}")

            # Send notifications
            try:
                import threading

                # Welcome email to user
                welcome_subj = "Welcome to AutoWP!"
                welcome_body = f"Hello {name},\n\nThank you for registering on AutoWP! Your account has been initialized with 5 free credits."
                threading.Thread(target=send_email_notification, args=(email, welcome_subj, welcome_body)).start()

                # WhatsApp/Email alert to Admin
                admin_subj = "AutoWP - New User Registered (Google)"
                admin_body = f"Halo Admin,\n\nUser baru telah mendaftar di AutoWP via Google:\n- Nama: {name}\n- Email: {email}\n- Role: {role}\n\nSilakan periksa dashboard admin untuk detailnya."

                admin_email = Config.SMTP_SENDER_EMAIL or Config.SMTP_USER
                if admin_email:
                    threading.Thread(target=send_email_notification, args=(admin_email, admin_subj, admin_body)).start()
                if Config.STARSENDER_DEVICE_ID:
                    threading.Thread(target=send_whatsapp_notification, args=(Config.STARSENDER_DEVICE_ID, admin_body)).start()
            except Exception as ex:
                logger.error(f"Error launching Google registration notification threads: {ex}")
        else:
            if not user.google_id:
                user.google_id = google_id
            if is_configured_admin_email(email) and user.role != 'admin':
                user.role = 'admin'
                logger.info(f"Updated configured admin user {email} role to admin on login")
            session.commit()

        if not user.is_active:
            return jsonify({'success': False, 'error': 'Account is suspended'}), 403

        token = issue_access_token(user.id)

        resp = make_response(jsonify({
            'success': True,
            'token': token,
            'user': {
                'id': user.id,
                'email': user.email,
                'role': user.role,
                'tier': user.tier,
                'credits': user.credits
            }
        }))
        resp.set_cookie('auth_token', token, httponly=True, samesite='Lax', secure=os.environ.get('FLASK_ENV') != 'development', max_age=7*24*60*60)
        return resp

@auth_bp.route('/api/login', methods=['POST'])
def api_auth_login():
    data = request.get_json(silent=True) or {}
    email = data.get('email', '')
    password = data.get('password', '')
    if not isinstance(email, str) or not isinstance(password, str):
        return jsonify({'success': False, 'error': 'Invalid email or password', 'code': 401}), 401
    allowed, retry_sec = _check_rate_limit(email)
    if not allowed:
        return jsonify({'success': False, 'error': f'Too many login attempts. Try again in {retry_sec} seconds.'}), 429
    logger.info(f"Login attempt for email: {email}")
    with db.get_session() as session:
        from models import User
        user = session.query(User).filter_by(email=email).first()
        if user and user.password_hash and check_password_hash(user.password_hash, password):
            _clear_failed_logins(email)
            if not user.is_active:
                return jsonify({'success': False, 'error': 'Account is suspended'}), 403

            token = issue_access_token(user.id)

            resp = make_response(jsonify({
                'success': True,
                'token': token,
                'user': {
                    'id': user.id,
                    'email': user.email,
                    'role': user.role or 'user',
                    'tier': user.tier or 'free',
                    'credits': user.credits if user.credits is not None else 5
                }
            }))
            resp.set_cookie('auth_token', token, httponly=True, samesite='Lax', secure=os.environ.get('FLASK_ENV') != 'development', max_age=7*24*60*60)
            return resp
    _record_failed_login(email)
    return jsonify({'success': False, 'error': 'Invalid email or password', 'code': 401}), 401

@auth_bp.route('/api/auth/status', methods=['GET'])
@require_jwt
def api_auth_verify(user_id):
    with db.get_session() as session:
        from models import User
        user = session.query(User).filter_by(id=user_id).first()
        if not user:
            return jsonify({'authenticated': False, 'error': 'User not found'}), 404
        if not user.is_active:
            return jsonify({'authenticated': False, 'error': 'Account is suspended'}), 403
        return jsonify({
            'authenticated': True,
            'user_id': user_id,
            'role': user.role or 'user',
            'tier': user.tier or 'free',
            'credits': user.credits if user.credits is not None else 5
        })

@auth_bp.route('/api/auth/config', methods=['GET'])
def api_auth_config():
    google_client_id = Config.GOOGLE_CLIENT_ID
    tripay_enabled = Config.PAYMENT_TRIPAY_ENABLED
    paypal_enabled = Config.PAYMENT_PAYPAL_ENABLED
    manual_enabled = Config.PAYMENT_MANUAL_ENABLED
    mock_payments_enabled = Config.ALLOW_MOCK_PAYMENTS
    tripay_configured = True
    paypal_configured = True

    try:
        system_settings = db.get_system_settings()
        if 'GOOGLE_CLIENT_ID' in system_settings and system_settings['GOOGLE_CLIENT_ID']:
            google_client_id = system_settings['GOOGLE_CLIENT_ID']
        if 'PAYMENT_TRIPAY_ENABLED' in system_settings:
            tripay_enabled = system_settings['PAYMENT_TRIPAY_ENABLED'].lower() == 'true'
        if 'PAYMENT_PAYPAL_ENABLED' in system_settings:
            paypal_enabled = system_settings['PAYMENT_PAYPAL_ENABLED'].lower() == 'true'
        if 'PAYMENT_MANUAL_ENABLED' in system_settings:
            manual_enabled = system_settings['PAYMENT_MANUAL_ENABLED'].lower() == 'true'
    except Exception as e:
        logger.error(f"Error reading system settings in api_auth_config: {e}")

    try:
        from routes.payments import get_payment_settings, tripay_is_mock, paypal_is_mock
        payment_settings = get_payment_settings()
        mock_payments_enabled = payment_settings['ALLOW_MOCK_PAYMENTS']
        tripay_configured = not tripay_is_mock(payment_settings)
        paypal_configured = not paypal_is_mock(payment_settings)
    except Exception as e:
        logger.error(f"Error reading payment gateway availability: {e}")

    return jsonify({
        'success': True,
        'google_client_id': google_client_id or '',
        'payment_tripay_enabled': tripay_enabled and (tripay_configured or mock_payments_enabled),
        'payment_paypal_enabled': paypal_enabled and (paypal_configured or mock_payments_enabled),
        'payment_manual_enabled': manual_enabled,
        'mock_payments_enabled': mock_payments_enabled
    })

@auth_bp.route('/logout', methods=['POST'])
def logout():
    # Revoke this device's token so a copied/stolen copy stops working. POST
    # only, so a link on another site cannot log the user out.
    token = get_request_token()
    if token:
        try:
            revoke_token(decode_access_token(token))
        except Exception:
            pass  # expired/invalid token: nothing to revoke
    session.clear()
    resp = make_response(jsonify({'success': True}))
    resp.delete_cookie('auth_token')
    return resp
