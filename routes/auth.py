import threading

import requests
from flask import Blueprint, request, jsonify, make_response
from flask import session
from werkzeug.security import check_password_hash

import rate_limit
from core_extensions import (
    db, logger, require_jwt, send_email_notification, send_whatsapp_notification,
    issue_access_token, revoke_token, decode_access_token, get_request_token, set_auth_cookie,
)
from config import Config
from database import Config as DBConfig
from models import User
from routes.payments import get_payment_settings, tripay_is_mock, paypal_is_mock

auth_bp = Blueprint('auth', __name__)

LOGIN_MAX_FAILURES_PER_ACCOUNT = 5
LOGIN_MAX_FAILURES_PER_IP = 30
LOGIN_FAILURE_WINDOW_SECONDS = 300
NEW_USER_CREDITS = 5

GOOGLE_ISSUERS = ('accounts.google.com', 'https://accounts.google.com')


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
    is_blocked, retry_after = rate_limit.blocked(_login_rate_limit_keys(email))
    return not is_blocked, retry_after


def _record_failed_login(email):
    keys = [key for key, _ in _login_rate_limit_keys(email)]
    rate_limit.record(keys, LOGIN_FAILURE_WINDOW_SECONDS)


def _clear_failed_logins(email):
    # Only the per-account lockout is cleared; the per-IP counter keeps
    # protecting against password spraying across accounts.
    rate_limit.clear(_login_rate_limit_keys(email)[0][0])


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


def _start_background(target, *args):
    threading.Thread(target=target, args=args).start()


def _notify_google_registration(email, name, role):
    """Welcome the new user and alert the admin; failures are only logged."""
    try:
        welcome_subj = "Welcome to AutoWP!"
        welcome_body = (
            f"Hello {name},\n\nThank you for registering on AutoWP! "
            f"Your account has been initialized with {NEW_USER_CREDITS} free credits."
        )
        _start_background(send_email_notification, email, welcome_subj, welcome_body)

        admin_subj = "AutoWP - New User Registered (Google)"
        admin_body = (
            f"Halo Admin,\n\nUser baru telah mendaftar di AutoWP via Google:\n- Nama: {name}\n"
            f"- Email: {email}\n- Role: {role}\n\nSilakan periksa dashboard admin untuk detailnya."
        )
        admin_email = Config.SMTP_SENDER_EMAIL or Config.SMTP_USER
        if admin_email:
            _start_background(send_email_notification, admin_email, admin_subj, admin_body)
        if Config.STARSENDER_DEVICE_ID:
            _start_background(send_whatsapp_notification, Config.STARSENDER_DEVICE_ID, admin_body)
    except Exception as ex:
        logger.error(f"Error launching Google registration notification threads: {ex}")


def _register_google_user(session, email, google_id, name):
    user_count = session.query(User).count()
    role = 'admin' if (user_count == 0 or is_configured_admin_email(email)) else 'user'

    user = User(
        email=email,
        name=name,
        google_id=google_id,
        role=role,
        tier='free',
        credits=NEW_USER_CREDITS,
        is_active=True
    )
    session.add(user)
    session.commit()

    session.add(DBConfig(user_id=user.id, gemini_api_key='', gemini_model='gemini-3.5-flash'))
    session.commit()

    logger.info(f"Registered new user via Google: {email} with role {role}")
    _notify_google_registration(email, name, role)
    return user


def _link_existing_google_user(session, user, email, google_id):
    if not user.google_id:
        user.google_id = google_id
    if is_configured_admin_email(email) and user.role != 'admin':
        user.role = 'admin'
        logger.info(f"Updated configured admin user {email} role to admin on login")
    session.commit()


def _login_response(user_id, user_payload):
    """Issue a token for user_id and return it in both the body and the auth cookie."""
    token = issue_access_token(user_id)
    resp = make_response(jsonify({'success': True, 'token': token, 'user': user_payload}))
    return set_auth_cookie(resp, token)


@auth_bp.route('/api/register', methods=['POST'])
def api_auth_register():
    return jsonify({'success': False, 'error': 'Pendaftaran manual dinonaktifkan. Silakan mendaftar menggunakan Google Login.'}), 403


@auth_bp.route('/api/auth/google', methods=['POST'])
def api_auth_google():
    data = request.json or {}
    id_token = data.get('id_token')
    if not id_token:
        return jsonify({'success': False, 'error': 'id_token wajib diisi.'}), 400
    if not configured_google_client_id():
        return jsonify({'success': False, 'error': 'Login Google belum dikonfigurasi. Hubungi administrator.'}), 503

    token_info = verify_google_token(id_token)
    if not token_info:
        return jsonify({'success': False, 'error': 'Token Google tidak valid.'}), 400

    email = token_info.get('email')
    google_id = token_info.get('sub')
    name = token_info.get('name', '')

    if not email:
        return jsonify({'success': False, 'error': 'Token Google tidak menyertakan email.'}), 400

    with db.get_session() as session:
        user = session.query(User).filter_by(google_id=google_id).first()
        if not user:
            user = session.query(User).filter_by(email=email).first()
            if user and user.google_id and user.google_id != google_id:
                return jsonify({'success': False, 'error': 'Email ini sudah terhubung dengan akun Google lain.'}), 400

        if not user:
            user = _register_google_user(session, email, google_id, name)
        else:
            _link_existing_google_user(session, user, email, google_id)

        if not user.is_active:
            return jsonify({'success': False, 'error': 'Akun Anda sedang ditangguhkan.'}), 403

        return _login_response(user.id, {
            'id': user.id,
            'email': user.email,
            'role': user.role,
            'tier': user.tier,
            'credits': user.credits
        })


@auth_bp.route('/api/login', methods=['POST'])
def api_auth_login():
    data = request.get_json(silent=True) or {}
    email = data.get('email', '')
    password = data.get('password', '')
    if not isinstance(email, str) or not isinstance(password, str):
        return jsonify({'success': False, 'error': 'Email atau kata sandi salah.', 'code': 401}), 401
    allowed, retry_sec = _check_rate_limit(email)
    if not allowed:
        return jsonify({'success': False, 'error': f'Terlalu banyak percobaan masuk. Coba lagi dalam {retry_sec} detik.'}), 429
    logger.info(f"Login attempt for email: {email}")
    with db.get_session() as session:
        user = session.query(User).filter_by(email=email).first()
        if user and user.password_hash and check_password_hash(user.password_hash, password):
            _clear_failed_logins(email)
            if not user.is_active:
                return jsonify({'success': False, 'error': 'Akun Anda sedang ditangguhkan.'}), 403

            return _login_response(user.id, {
                'id': user.id,
                'email': user.email,
                'role': user.role or 'user',
                'tier': user.tier or 'free',
                'credits': user.credits if user.credits is not None else NEW_USER_CREDITS
            })
    _record_failed_login(email)
    return jsonify({'success': False, 'error': 'Email atau kata sandi salah.', 'code': 401}), 401


@auth_bp.route('/api/auth/status', methods=['GET'])
@require_jwt
def api_auth_verify(user_id):
    with db.get_session() as session:
        user = session.query(User).filter_by(id=user_id).first()
        if not user:
            return jsonify({'authenticated': False, 'error': 'Pengguna tidak ditemukan.'}), 404
        if not user.is_active:
            return jsonify({'authenticated': False, 'error': 'Akun Anda sedang ditangguhkan.'}), 403
        return jsonify({
            'authenticated': True,
            'user_id': user_id,
            'role': user.role or 'user',
            'tier': user.tier or 'free',
            'credits': user.credits if user.credits is not None else NEW_USER_CREDITS
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
        if system_settings.get('GOOGLE_CLIENT_ID'):
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
