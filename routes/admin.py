import math
import os
import threading
from flask import Blueprint, request, jsonify
from sqlalchemy import func

from core_extensions import (
    db, q, logger, require_admin, send_email_notification, revoke_user_tokens, bump_settings_version,
    load_config, save_config,
)
from database import Config as DBConfig
from models import User, Transaction, WordPressSite, PostLog, ResearchData, ContentQueue
from config import Config, DEFAULT_GEMINI_MODEL, DEFAULT_GEMINI_IMAGE_MODEL
from routes.payments import fulfill_transaction

admin_bp = Blueprint('admin', __name__)

ENV_FILE_PATH = '.env'
PAYMENT_TOGGLE_KEYS = ('PAYMENT_TRIPAY_ENABLED', 'PAYMENT_PAYPAL_ENABLED', 'PAYMENT_MANUAL_ENABLED')
# System settings the admin may edit, in the order they are processed.
EDITABLE_SYSTEM_SETTINGS = (
    'TRIPAY_API_KEY', 'TRIPAY_PRIVATE_KEY', 'TRIPAY_MERCHANT_CODE', 'TRIPAY_API_URL',
    'PAYPAL_CLIENT_ID', 'PAYPAL_SECRET', 'PAYPAL_API_URL', 'PAYMENT_USD_RATE',
    'GOOGLE_CLIENT_ID', 'GOOGLE_CLIENT_SECRET',
    'SMTP_HOST', 'SMTP_PORT', 'SMTP_USER', 'SMTP_PASSWORD', 'SMTP_SENDER_EMAIL',
    'STARSENDER_API_KEY', 'STARSENDER_DEVICE_ID',
    'MANUAL_BANK_NAME', 'MANUAL_BANK_ACCOUNT', 'MANUAL_BANK_HOLDER', 'ADMIN_WHATSAPP',
) + PAYMENT_TOGGLE_KEYS

SENSITIVE_ADMIN_KEYS = {
    'TRIPAY_API_KEY',
    'TRIPAY_PRIVATE_KEY',
    'PAYPAL_SECRET',
    'GOOGLE_CLIENT_SECRET',
    'SMTP_PASSWORD',
    'STARSENDER_API_KEY',
}

def _secret_response(config_dict, key):
    value = config_dict.get(key)
    has_value = bool(value) and not str(value).startswith('MOCK_')
    return {
        key: '',
        f'has_{key}': has_value
    }

@admin_bp.route('/api/admin/bulk_update_year', methods=['POST'])
@require_admin
def bulk_update_year_endpoint(user_id):
    data = request.json or {}
    site_id = data.get('site_id')
    from_year = data.get('from_year')
    to_year = data.get('to_year')

    if not all([site_id, from_year, to_year]):
        return jsonify({'success': False, 'error': 'site_id, from_year, dan to_year wajib diisi.'}), 400

    try:
        # Enqueue by dotted path against the shared queue. The previous version
        # imported redis_conn from a worker.py that no longer exists and pulled the
        # task from app.py, where it has never lived, so this always failed.
        job = q.enqueue(
            'tasks.research_jobs.bulk_update_year_task',
            user_id, site_id, from_year, to_year,
            job_timeout='1h'
        )
        return jsonify({'success': True, 'message': 'Pembaruan tahun massal dimulai.', 'job_id': job.id})
    except Exception as e:
        logger.error(f"Failed to start bulk update task: {e}")
        return jsonify({'success': False, 'error': 'Gagal memulai pembaruan tahun massal.'}), 500


@admin_bp.route('/api/admin/pending-payments', methods=['GET'])
@require_admin
def get_pending_payments(user_id):
    with db.get_session() as session:
        # Get transactions awaiting approval, including user details
        transactions = session.query(Transaction).filter_by(
            status='awaiting_approval'
        ).order_by(Transaction.created_at.desc()).limit(200).all()

        # Batch-load the users instead of one query per transaction.
        user_ids = {tx.user_id for tx in transactions if tx.user_id}
        users_by_id = {}
        if user_ids:
            users_by_id = {
                u.id: u for u in session.query(User).filter(User.id.in_(user_ids)).all()
            }

        result = []
        for tx in transactions:
            user = users_by_id.get(tx.user_id)
            result.append({
                'id': tx.id,
                'user_id': tx.user_id,
                'user_email': user.email if user else 'Unknown',
                'user_name': user.name if user else 'Unknown',
                'payment_method': tx.payment_method,
                'invoice_id': tx.invoice_id,
                'credits_purchased': tx.credits_purchased,
                'amount': tx.amount,
                'receipt_url': tx.receipt_url,
                'status': tx.status,
                'created_at': tx.created_at.strftime('%Y-%m-%d %H:%M:%S')
            })
        return jsonify({'success': True, 'transactions': result})

@admin_bp.route('/api/admin/payments/<int:transaction_id>/approve', methods=['POST'])
@require_admin
def approve_payment(user_id, transaction_id):
    with db.get_session() as session:
        tx = session.query(Transaction).filter_by(id=transaction_id).first()
        if not tx:
            return jsonify({'success': False, 'error': 'Transaksi tidak ditemukan.'}), 404

        if tx.status != 'awaiting_approval':
            return jsonify({'success': False, 'error': f'Status transaksi {tx.status}, tidak dapat disetujui.'}), 400

        invoice_id = tx.invoice_id
        # Atomic: a double-clicked approve (or two admins) can only credit once.
        credits = fulfill_transaction(session, tx.id, ('awaiting_approval',))
        if credits is None:
            session.rollback()
            return jsonify({'success': False, 'error': 'Transaksi sudah diproses.'}), 409
        session.commit()

        user = session.query(User).filter_by(id=tx.user_id).first()
        if user:
            logger.info(f"Admin {user_id} approved payment for {invoice_id}. Added {credits} credits to User {user.email}")

            # Notify user
            try:
                subject = f"AutoWP Top-Up Approved - {invoice_id}"
                body = f"Hello {user.name or 'User'},\n\nGood news! Your top-up order of {credits} credits (invoice: {invoice_id}) has been approved.\nYour credit balance is now: {user.credits}.\n\nThank you for using AutoWP!"
                threading.Thread(target=send_email_notification, args=(user.email, subject, body)).start()
            except Exception as e:
                logger.error(f"Error launching payment approval email thread: {e}")

        return jsonify({'success': True, 'message': 'Pembayaran berhasil disetujui.'})

@admin_bp.route('/api/admin/payments/<int:transaction_id>/reject', methods=['POST'])
@require_admin
def reject_payment(user_id, transaction_id):
    with db.get_session() as session:
        tx = session.query(Transaction).filter_by(id=transaction_id).first()
        if not tx:
            return jsonify({'success': False, 'error': 'Transaksi tidak ditemukan.'}), 404

        if tx.status != 'awaiting_approval':
            return jsonify({'success': False, 'error': f'Status transaksi {tx.status}, tidak dapat ditolak.'}), 400

        updated = session.query(Transaction).filter(
            Transaction.id == tx.id,
            Transaction.status == 'awaiting_approval',
        ).update({Transaction.status: 'failed'}, synchronize_session=False)
        if updated != 1:
            session.rollback()
            return jsonify({'success': False, 'error': 'Transaksi sudah diproses.'}), 409
        session.commit()
        logger.info(f"Admin {user_id} rejected payment for {tx.invoice_id}")
        return jsonify({'success': True, 'message': 'Pembayaran ditolak.'})

@admin_bp.route('/api/admin/users', methods=['GET'])
@require_admin
def get_users(user_id):
    with db.get_session() as session:
        users = session.query(User).order_by(User.id.asc()).limit(500).all()
        result = []
        for u in users:
            result.append({
                'id': u.id,
                'name': u.name,
                'email': u.email,
                'role': u.role,
                'tier': u.tier,
                'credits': u.credits if u.credits is not None else 5,
                'is_active': u.is_active,
                'created_at': u.created_at.strftime('%Y-%m-%d %H:%M:%S') if u.created_at else ''
            })
        return jsonify({'success': True, 'users': result})

@admin_bp.route('/api/admin/users/<int:target_user_id>', methods=['PUT'])
@require_admin
def update_user(user_id, target_user_id):
    data = request.json or {}
    with db.get_session() as session:
        user = session.query(User).filter_by(id=target_user_id).first()
        if not user:
            return jsonify({'success': False, 'error': 'Pengguna tidak ditemukan.'}), 404

        if 'name' in data:
            user.name = str(data['name']).strip()
        if 'role' in data:
            if data['role'] not in ('admin', 'user'):
                return jsonify({'success': False, 'error': 'Role tidak valid.'}), 400
            # Enforce that you cannot demote yourself
            if target_user_id == user_id and data['role'] != 'admin':
                return jsonify({'success': False, 'error': 'Anda tidak dapat mencabut status admin Anda sendiri.'}), 400
            user.role = data['role']
        if 'tier' in data:
            if data['tier'] not in ('free', 'pro'):
                return jsonify({'success': False, 'error': 'Tier tidak valid.'}), 400
            user.tier = data['tier']
        if 'credits' in data:
            try:
                user.credits = max(0, int(data['credits']))
            except (TypeError, ValueError):
                return jsonify({'success': False, 'error': 'Nilai kredit tidak valid.'}), 400
        suspended = False
        if 'is_active' in data:
            if target_user_id == user_id and not data['is_active']:
                return jsonify({'success': False, 'error': 'Anda tidak dapat menangguhkan akun Anda sendiri.'}), 400
            suspended = bool(user.is_active) and not bool(data['is_active'])
            user.is_active = bool(data['is_active'])

        session.commit()
        if suspended:
            # Kill existing sessions; re-activation still requires a fresh login.
            revoke_user_tokens(target_user_id)
        logger.info(f"Admin {user_id} updated User {target_user_id}")
        return jsonify({'success': True, 'message': 'Pengguna berhasil diperbarui.'})

@admin_bp.route('/api/admin/users/<int:target_user_id>', methods=['DELETE'])
@require_admin
def delete_user(user_id, target_user_id):
    if target_user_id == user_id:
        return jsonify({'success': False, 'error': 'Anda tidak dapat menghapus akun Anda sendiri.'}), 400

    with db.get_session() as session:
        user = session.query(User).filter_by(id=target_user_id).first()
        if not user:
            return jsonify({'success': False, 'error': 'Pengguna tidak ditemukan.'}), 404

        # Cascade delete user data
        session.query(DBConfig).filter_by(user_id=target_user_id).delete()
        session.query(WordPressSite).filter_by(user_id=target_user_id).delete()
        session.query(PostLog).filter_by(user_id=target_user_id).delete()
        session.query(ResearchData).filter_by(user_id=target_user_id).delete()
        session.query(ContentQueue).filter_by(user_id=target_user_id).delete()
        session.query(Transaction).filter_by(user_id=target_user_id).delete()
        session.delete(user)

        session.commit()
        logger.info(f"Admin {user_id} deleted User {target_user_id}")
        return jsonify({'success': True, 'message': 'Pengguna berhasil dihapus.'})

@admin_bp.route('/api/admin/stats', methods=['GET'])
@require_admin
def get_admin_stats(user_id):
    with db.get_session() as session:
        total_users = session.query(User).count()
        total_pro = session.query(User).filter_by(tier='pro').count()

        # Aggregate in SQL rather than loading every successful transaction just to
        # sum two columns.
        earnings, credits_purchased = session.query(
            func.coalesce(func.sum(Transaction.amount), 0),
            func.coalesce(func.sum(Transaction.credits_purchased), 0)
        ).filter(Transaction.status == 'success').one()
        total_earnings = float(earnings or 0)
        total_credits_purchased = int(credits_purchased or 0)

        # Active queue count
        queue_count = session.query(ContentQueue).count()

        # Total generated articles
        total_articles = session.query(PostLog).count()

        return jsonify({
            'success': True,
            'stats': {
                'total_users': total_users,
                'total_pro': total_pro,
                'total_earnings_idr': total_earnings,
                'total_credits_purchased': total_credits_purchased,
                'queue_count': queue_count,
                'total_articles': total_articles
            }
        })

@admin_bp.route('/api/admin/logs', methods=['GET'])
@require_admin
def get_system_logs(user_id):
    limit = int(request.args.get('limit', 500))
    log_file = 'bot.log'
    if not os.path.exists(log_file):
        return jsonify({'success': True, 'logs': ['File log tidak ditemukan.']})

    try:
        with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
            # Return last `limit` lines
            last_lines = lines[-limit:]
            return jsonify({'success': True, 'logs': last_lines})
    except Exception as e:
        logger.error(f"Could not read {log_file}: {e}")
        return jsonify({'success': False, 'error': 'Gagal membaca file log.'}), 500

@admin_bp.route('/api/admin/config', methods=['GET'])
@require_admin
def get_admin_config(user_id):
    db_config = load_config(user_id)

    system_settings = {}
    try:
        system_settings = db.get_system_settings()
    except Exception as e:
        logger.error(f"Error loading system settings in get_admin_config: {e}")

    # Stored settings are strings; convert them back to their types.
    def is_enabled(key, default_val):
        if key in system_settings:
            return system_settings[key].lower() == 'true'
        return default_val

    # Helper to convert float
    def get_float(key, default_val):
        if key in system_settings:
            try:
                return float(system_settings[key])
            except ValueError:
                pass  # unparsable stored value: fall back to the default
        return default_val

    # Helper to convert int
    def get_int(key, default_val):
        if key in system_settings:
            try:
                return int(system_settings[key])
            except ValueError:
                pass  # unparsable stored value: fall back to the default
        return default_val

    config_response = {
        'TRIPAY_MERCHANT_CODE': system_settings.get('TRIPAY_MERCHANT_CODE', Config.TRIPAY_MERCHANT_CODE),
        'TRIPAY_API_URL': system_settings.get('TRIPAY_API_URL', Config.TRIPAY_API_URL),
        'PAYPAL_CLIENT_ID': system_settings.get('PAYPAL_CLIENT_ID', Config.PAYPAL_CLIENT_ID),
        'PAYPAL_API_URL': system_settings.get('PAYPAL_API_URL', Config.PAYPAL_API_URL),
        'PAYMENT_USD_RATE': get_float('PAYMENT_USD_RATE', Config.PAYMENT_USD_RATE),
        'GOOGLE_CLIENT_ID': system_settings.get('GOOGLE_CLIENT_ID', Config.GOOGLE_CLIENT_ID),
        'SMTP_HOST': system_settings.get('SMTP_HOST', Config.SMTP_HOST),
        'SMTP_PORT': get_int('SMTP_PORT', Config.SMTP_PORT),
        'SMTP_USER': system_settings.get('SMTP_USER', Config.SMTP_USER),
        'SMTP_SENDER_EMAIL': system_settings.get('SMTP_SENDER_EMAIL', Config.SMTP_SENDER_EMAIL),
        'STARSENDER_DEVICE_ID': system_settings.get('STARSENDER_DEVICE_ID', Config.STARSENDER_DEVICE_ID),
        'MANUAL_BANK_NAME': system_settings.get('MANUAL_BANK_NAME', Config.MANUAL_BANK_NAME),
        'MANUAL_BANK_ACCOUNT': system_settings.get('MANUAL_BANK_ACCOUNT', Config.MANUAL_BANK_ACCOUNT),
        'MANUAL_BANK_HOLDER': system_settings.get('MANUAL_BANK_HOLDER', Config.MANUAL_BANK_HOLDER),
        'ADMIN_WHATSAPP': system_settings.get('ADMIN_WHATSAPP', Config.ADMIN_WHATSAPP),
        'PAYMENT_TRIPAY_ENABLED': is_enabled('PAYMENT_TRIPAY_ENABLED', Config.PAYMENT_TRIPAY_ENABLED),
        'PAYMENT_PAYPAL_ENABLED': is_enabled('PAYMENT_PAYPAL_ENABLED', Config.PAYMENT_PAYPAL_ENABLED),
        'PAYMENT_MANUAL_ENABLED': is_enabled('PAYMENT_MANUAL_ENABLED', Config.PAYMENT_MANUAL_ENABLED),
        # Gemini database-backed configs
        'gemini_api_key': '',
        'has_gemini_api_key': bool(db_config.get('gemini_api_key')),
        'gemini_model': db_config.get('gemini_model', DEFAULT_GEMINI_MODEL),
        'gemini_image_model': db_config.get('gemini_image_model', DEFAULT_GEMINI_IMAGE_MODEL)
    }

    raw_sensitive = {
        'TRIPAY_API_KEY': system_settings.get('TRIPAY_API_KEY', Config.TRIPAY_API_KEY),
        'TRIPAY_PRIVATE_KEY': system_settings.get('TRIPAY_PRIVATE_KEY', Config.TRIPAY_PRIVATE_KEY),
        'PAYPAL_SECRET': system_settings.get('PAYPAL_SECRET', Config.PAYPAL_SECRET),
        'GOOGLE_CLIENT_SECRET': system_settings.get('GOOGLE_CLIENT_SECRET', Config.GOOGLE_CLIENT_SECRET),
        'SMTP_PASSWORD': system_settings.get('SMTP_PASSWORD', Config.SMTP_PASSWORD),
        'STARSENDER_API_KEY': system_settings.get('STARSENDER_API_KEY', Config.STARSENDER_API_KEY),
    }
    for key in SENSITIVE_ADMIN_KEYS:
        config_response.update(_secret_response(raw_sensitive, key))

    return jsonify({
        'success': True,
        'config': config_response
    })


def _parse_usd_rate(data):
    """Validated PAYMENT_USD_RATE from the request: (rate_or_None, error_response_or_None)."""
    if 'PAYMENT_USD_RATE' not in data:
        return None, None
    try:
        usd_rate = float(str(data['PAYMENT_USD_RATE']).strip())
    except (TypeError, ValueError):
        usd_rate = None
    if usd_rate is None or not math.isfinite(usd_rate) or usd_rate <= 0:
        return None, (jsonify({'success': False, 'error': 'PAYMENT_USD_RATE harus berupa angka lebih dari 0.'}), 400)
    return usd_rate, None


def _save_gemini_config(user_id, data):
    gemini_data = {}
    if 'gemini_api_key' in data and str(data.get('gemini_api_key') or '').strip():
        gemini_data['gemini_api_key'] = data['gemini_api_key']
    if 'gemini_model' in data:
        gemini_data['gemini_model'] = data['gemini_model']
    if 'gemini_image_model' in data:
        gemini_data['gemini_image_model'] = data['gemini_image_model']
    if gemini_data:
        save_config(user_id, gemini_data)


def _system_setting_updates(data, usd_rate):
    """Normalize the editable system settings present in the request.

    A blank secret means "keep the stored value" and is skipped.
    """
    updates = {}
    for k in EDITABLE_SYSTEM_SETTINGS:
        if k not in data:
            continue
        val = data[k]
        if k in SENSITIVE_ADMIN_KEYS and not str(val or '').strip():
            continue
        if k == 'PAYMENT_USD_RATE':
            val = usd_rate
        elif k == 'SMTP_PORT':
            try:
                val = int(str(val).strip())
            except ValueError:
                val = 587
        elif k in PAYMENT_TOGGLE_KEYS:
            val = 'true' if val is True or str(val).lower() == 'true' else 'false'
        else:
            val = str(val).strip()
        updates[k] = val
    return updates


def _read_env_file(env_path):
    env_vars = {}
    if not os.path.exists(env_path):
        return env_vars
    try:
        with open(env_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except Exception as e:
        logger.error(f"Error reading .env: {e}")
        return env_vars
    for line in lines:
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            key, value = line.split('=', 1)
            env_vars[key.strip()] = value.strip()
    return env_vars


def _apply_to_process(updates):
    """Make the new values effective in this process immediately."""
    for k, v in updates.items():
        os.environ[k] = str(v)
        if k in PAYMENT_TOGGLE_KEYS:
            setattr(Config, k, v == 'true')
        else:
            setattr(Config, k, v)


@admin_bp.route('/api/admin/config', methods=['PUT'])
@require_admin
def update_admin_config(user_id):
    data = request.get_json(silent=True) or {}

    # Validate before saving anything: every PayPal invoice divides by this rate.
    usd_rate, rate_error = _parse_usd_rate(data)
    if rate_error:
        return rate_error

    _save_gemini_config(user_id, data)
    updates = _system_setting_updates(data, usd_rate)

    try:
        db.save_system_settings(updates)
        # Other gunicorn workers / RQ workers re-apply settings when this changes.
        bump_settings_version()
    except Exception as e:
        logger.error(f"Failed to save system settings to DB: {e}")

    env_vars = _read_env_file(ENV_FILE_PATH)
    env_vars.update({k: str(v) for k, v in updates.items()})
    _apply_to_process(updates)

    try:
        with open(ENV_FILE_PATH, 'w', encoding='utf-8') as f:
            for k, v in sorted(env_vars.items()):
                f.write(f"{k}={v}\n")
    except Exception as e:
        logger.error(f"Error writing to .env: {e}")
        return jsonify({'success': False, 'error': 'Gagal menyimpan konfigurasi ke file .env.'}), 500

    logger.info(f"Admin {user_id} updated system settings in .env and memory")
    return jsonify({'success': True, 'message': 'Konfigurasi berhasil diperbarui.'})
