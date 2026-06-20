import os
import logging
from flask import Blueprint, request, jsonify

from core_extensions import db, logger, require_admin, send_email_notification, send_whatsapp_notification
from database import User, Transaction, Config as DBConfig, WordPressSite, PostLog, ResearchData, ContentQueue

admin_bp = Blueprint('admin', __name__)

@admin_bp.route('/api/admin/pending-payments', methods=['GET'])
@require_admin
def get_pending_payments(user_id):
    with db.get_session() as session:
        # Get transactions awaiting approval, including user details
        transactions = session.query(Transaction).filter_by(status='awaiting_approval').order_by(Transaction.created_at.desc()).all()
        result = []
        for tx in transactions:
            user = session.query(User).filter_by(id=tx.user_id).first()
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
            return jsonify({'success': False, 'error': 'Transaction not found'}), 404
            
        if tx.status != 'awaiting_approval':
            return jsonify({'success': False, 'error': f'Transaction status is {tx.status}, cannot approve'}), 400
            
        tx.status = 'success'
        user = session.query(User).filter_by(id=tx.user_id).first()
        if user:
            user.credits = (user.credits or 0) + tx.credits_purchased
            user.tier = 'pro'
            logger.info(f"Admin {user_id} approved payment for {tx.invoice_id}. Added {tx.credits_purchased} credits to User {user.email}")
            
            # Notify user
            try:
                import threading
                subject = f"AutoWP Top-Up Approved - {tx.invoice_id}"
                body = f"Hello {user.name or 'User'},\n\nGood news! Your top-up order of {tx.credits_purchased} credits (invoice: {tx.invoice_id}) has been approved.\nYour credit balance is now: {user.credits}.\n\nThank you for using AutoWP!"
                threading.Thread(target=send_email_notification, args=(user.email, subject, body)).start()
            except Exception as e:
                logger.error(f"Error launching payment approval email thread: {e}")
                
        session.commit()
        return jsonify({'success': True, 'message': 'Payment approved successfully'})

@admin_bp.route('/api/admin/payments/<int:transaction_id>/reject', methods=['POST'])
@require_admin
def reject_payment(user_id, transaction_id):
    with db.get_session() as session:
        tx = session.query(Transaction).filter_by(id=transaction_id).first()
        if not tx:
            return jsonify({'success': False, 'error': 'Transaction not found'}), 404
            
        if tx.status != 'awaiting_approval':
            return jsonify({'success': False, 'error': f'Transaction status is {tx.status}, cannot reject'}), 400
            
        tx.status = 'failed'
        logger.info(f"Admin {user_id} rejected payment for {tx.invoice_id}")
        session.commit()
        return jsonify({'success': True, 'message': 'Payment rejected'})

@admin_bp.route('/api/admin/users', methods=['GET'])
@require_admin
def get_users(user_id):
    with db.get_session() as session:
        users = session.query(User).order_by(User.id.asc()).all()
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
            return jsonify({'success': False, 'error': 'User not found'}), 404
            
        if 'name' in data:
            user.name = data['name']
        if 'role' in data:
            # Enforce that you cannot demote yourself
            if target_user_id == user_id and data['role'] != 'admin':
                return jsonify({'success': False, 'error': 'You cannot remove your own admin status'}), 400
            user.role = data['role']
        if 'tier' in data:
            user.tier = data['tier']
        if 'credits' in data:
            user.credits = int(data['credits'])
        if 'is_active' in data:
            if target_user_id == user_id and not data['is_active']:
                return jsonify({'success': False, 'error': 'You cannot suspend yourself'}), 400
            user.is_active = bool(data['is_active'])
            
        session.commit()
        logger.info(f"Admin {user_id} updated User {target_user_id}")
        return jsonify({'success': True, 'message': 'User updated successfully'})

@admin_bp.route('/api/admin/users/<int:target_user_id>', methods=['DELETE'])
@require_admin
def delete_user(user_id, target_user_id):
    if target_user_id == user_id:
        return jsonify({'success': False, 'error': 'You cannot delete yourself'}), 400
        
    with db.get_session() as session:
        user = session.query(User).filter_by(id=target_user_id).first()
        if not user:
            return jsonify({'success': False, 'error': 'User not found'}), 404
            
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
        return jsonify({'success': True, 'message': 'User deleted successfully'})

@admin_bp.route('/api/admin/stats', methods=['GET'])
@require_admin
def get_admin_stats(user_id):
    with db.get_session() as session:
        total_users = session.query(User).count()
        total_pro = session.query(User).filter_by(tier='pro').count()
        
        # Calculate earnings and credits
        transactions_success = session.query(Transaction).filter_by(status='success').all()
        total_earnings = sum(tx.amount for tx in transactions_success)
        total_credits_purchased = sum(tx.credits_purchased for tx in transactions_success)
        
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
        return jsonify({'success': True, 'logs': ['Log file not found.']})
        
    try:
        with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
            # Return last `limit` lines
            last_lines = lines[-limit:]
            return jsonify({'success': True, 'logs': last_lines})
    except Exception as e:
        return jsonify({'success': False, 'error': f"Could not read logs: {e}"}), 500

@admin_bp.route('/api/admin/config', methods=['GET'])
@require_admin
def get_admin_config(user_id):
    from config import Config
    from core_extensions import load_config
    db_config = load_config(user_id)
    
    system_settings = {}
    try:
        system_settings = db.get_system_settings()
    except Exception as e:
        logger.error(f"Error loading system settings in get_admin_config: {e}")

    # Helper helper to convert string booleans
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
                pass
        return default_val

    # Helper to convert int
    def get_int(key, default_val):
        if key in system_settings:
            try:
                return int(system_settings[key])
            except ValueError:
                pass
        return default_val

    return jsonify({
        'success': True,
        'config': {
            'TRIPAY_API_KEY': system_settings.get('TRIPAY_API_KEY', Config.TRIPAY_API_KEY),
            'TRIPAY_PRIVATE_KEY': system_settings.get('TRIPAY_PRIVATE_KEY', Config.TRIPAY_PRIVATE_KEY),
            'TRIPAY_MERCHANT_CODE': system_settings.get('TRIPAY_MERCHANT_CODE', Config.TRIPAY_MERCHANT_CODE),
            'TRIPAY_API_URL': system_settings.get('TRIPAY_API_URL', Config.TRIPAY_API_URL),
            'PAYPAL_CLIENT_ID': system_settings.get('PAYPAL_CLIENT_ID', Config.PAYPAL_CLIENT_ID),
            'PAYPAL_SECRET': system_settings.get('PAYPAL_SECRET', Config.PAYPAL_SECRET),
            'PAYPAL_API_URL': system_settings.get('PAYPAL_API_URL', Config.PAYPAL_API_URL),
            'PAYMENT_USD_RATE': get_float('PAYMENT_USD_RATE', Config.PAYMENT_USD_RATE),
            'GOOGLE_CLIENT_ID': system_settings.get('GOOGLE_CLIENT_ID', Config.GOOGLE_CLIENT_ID),
            'GOOGLE_CLIENT_SECRET': system_settings.get('GOOGLE_CLIENT_SECRET', Config.GOOGLE_CLIENT_SECRET),
            'SMTP_HOST': system_settings.get('SMTP_HOST', Config.SMTP_HOST),
            'SMTP_PORT': get_int('SMTP_PORT', Config.SMTP_PORT),
            'SMTP_USER': system_settings.get('SMTP_USER', Config.SMTP_USER),
            'SMTP_PASSWORD': system_settings.get('SMTP_PASSWORD', Config.SMTP_PASSWORD),
            'SMTP_SENDER_EMAIL': system_settings.get('SMTP_SENDER_EMAIL', Config.SMTP_SENDER_EMAIL),
            'STARSENDER_API_KEY': system_settings.get('STARSENDER_API_KEY', Config.STARSENDER_API_KEY),
            'STARSENDER_DEVICE_ID': system_settings.get('STARSENDER_DEVICE_ID', Config.STARSENDER_DEVICE_ID),
            'MANUAL_BANK_NAME': system_settings.get('MANUAL_BANK_NAME', Config.MANUAL_BANK_NAME),
            'MANUAL_BANK_ACCOUNT': system_settings.get('MANUAL_BANK_ACCOUNT', Config.MANUAL_BANK_ACCOUNT),
            'MANUAL_BANK_HOLDER': system_settings.get('MANUAL_BANK_HOLDER', Config.MANUAL_BANK_HOLDER),
            'ADMIN_WHATSAPP': system_settings.get('ADMIN_WHATSAPP', Config.ADMIN_WHATSAPP),
            'PAYMENT_TRIPAY_ENABLED': is_enabled('PAYMENT_TRIPAY_ENABLED', Config.PAYMENT_TRIPAY_ENABLED),
            'PAYMENT_PAYPAL_ENABLED': is_enabled('PAYMENT_PAYPAL_ENABLED', Config.PAYMENT_PAYPAL_ENABLED),
            'PAYMENT_MANUAL_ENABLED': is_enabled('PAYMENT_MANUAL_ENABLED', Config.PAYMENT_MANUAL_ENABLED),
            # Gemini database-backed configs
            'gemini_api_key': db_config.get('gemini_api_key', ''),
            'gemini_model': db_config.get('gemini_model', 'gemini-2.5-pro'),
            'gemini_image_model': db_config.get('gemini_image_model', 'gemini-3.1-flash-image')
        }
    })


@admin_bp.route('/api/admin/config', methods=['PUT'])
@require_admin
def update_admin_config(user_id):
    from config import Config
    from core_extensions import save_config, _config_cache
    data = request.json or {}
    
    # Save Gemini DB configs
    gemini_data = {}
    if 'gemini_api_key' in data:
        gemini_data['gemini_api_key'] = data['gemini_api_key']
    if 'gemini_model' in data:
        gemini_data['gemini_model'] = data['gemini_model']
    if 'gemini_image_model' in data:
        gemini_data['gemini_image_model'] = data['gemini_image_model']
        
    if gemini_data:
        save_config(user_id, gemini_data)
        # Invalidate cache
        _config_cache['timestamp'] = 0
        
    keys = [
        'TRIPAY_API_KEY', 'TRIPAY_PRIVATE_KEY', 'TRIPAY_MERCHANT_CODE', 'TRIPAY_API_URL',
        'PAYPAL_CLIENT_ID', 'PAYPAL_SECRET', 'PAYPAL_API_URL', 'PAYMENT_USD_RATE',
        'GOOGLE_CLIENT_ID', 'GOOGLE_CLIENT_SECRET',
        'SMTP_HOST', 'SMTP_PORT', 'SMTP_USER', 'SMTP_PASSWORD', 'SMTP_SENDER_EMAIL',
        'STARSENDER_API_KEY', 'STARSENDER_DEVICE_ID',
        'MANUAL_BANK_NAME', 'MANUAL_BANK_ACCOUNT', 'MANUAL_BANK_HOLDER', 'ADMIN_WHATSAPP',
        'PAYMENT_TRIPAY_ENABLED', 'PAYMENT_PAYPAL_ENABLED', 'PAYMENT_MANUAL_ENABLED'
    ]
    
    updates = {}
    for k in keys:
        if k in data:
            val = data[k]
            if k == 'PAYMENT_USD_RATE':
                try:
                    val = float(str(val).strip())
                except ValueError:
                    val = 16000.0
            elif k == 'SMTP_PORT':
                try:
                    val = int(str(val).strip())
                except ValueError:
                    val = 587
            elif k in ['PAYMENT_TRIPAY_ENABLED', 'PAYMENT_PAYPAL_ENABLED', 'PAYMENT_MANUAL_ENABLED']:
                val = 'true' if val is True or str(val).lower() == 'true' else 'false'
            else:
                val = str(val).strip()
            updates[k] = val

    # Save to PostgreSQL database system_settings table
    try:
        db.save_system_settings(updates)
    except Exception as e:
        logger.error(f"Failed to save system settings to DB: {e}")

    env_path = '.env'

    lines = []
    if os.path.exists(env_path):
        try:
            with open(env_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
        except Exception as e:
            logger.error(f"Error reading .env: {e}")
            
    env_vars = {}
    for line in lines:
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            parts = line.split('=', 1)
            if len(parts) == 2:
                env_vars[parts[0].strip()] = parts[1].strip()
                
    for k, v in updates.items():
        env_vars[k] = str(v)
        os.environ[k] = str(v)
        if k in ['PAYMENT_TRIPAY_ENABLED', 'PAYMENT_PAYPAL_ENABLED', 'PAYMENT_MANUAL_ENABLED']:
            setattr(Config, k, v == 'true')
        else:
            setattr(Config, k, v)
        
    try:
        with open(env_path, 'w', encoding='utf-8') as f:
            for k, v in sorted(env_vars.items()):
                f.write(f"{k}={v}\n")
    except Exception as e:
        logger.error(f"Error writing to .env: {e}")
        return jsonify({'success': False, 'error': f"Failed to save to env: {e}"}), 500
        
    logger.info(f"Admin {user_id} updated system settings in .env and memory")
    return jsonify({'success': True, 'message': 'Configurations updated successfully'})
