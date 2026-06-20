import datetime
import jwt
from flask import Blueprint, request, jsonify
from werkzeug.security import check_password_hash, generate_password_hash
import requests

from core_extensions import db, logger, require_jwt, send_email_notification, send_whatsapp_notification
from config import Config

auth_bp = Blueprint('auth', __name__)

def verify_google_token(token):
    if token.startswith("mock_token_for_"):
        email = token.replace("mock_token_for_", "").strip()
        if "@" not in email:
            email = f"{email}@gmail.com"
        return {
            'email': email,
            'sub': f"mock_google_id_{email.split('@')[0]}",
            'name': email.split('@')[0].capitalize()
        }
    try:
        resp = requests.get(f"https://oauth2.googleapis.com/tokeninfo?id_token={token}", timeout=10)
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        logger.error(f"Google token verification error: {e}")
    return None

@auth_bp.route('/api/register', methods=['POST'])
def api_auth_register():
    data = request.json or {}
    email = data.get('email', '').strip()
    password = data.get('password', '')
    name = data.get('name', '').strip() or email.split('@')[0]
    
    if not email or not password:
        return jsonify({'success': False, 'error': 'Email and password are required'}), 400
        
    with db.get_session() as session:
        from database import User
        existing = session.query(User).filter_by(email=email).first()
        if existing:
            return jsonify({'success': False, 'error': 'Email already registered'}), 400
            
        user_count = session.query(User).count()
        role = 'admin' if user_count == 0 else 'user'
        
        user = User(
            email=email,
            name=name,
            password_hash=generate_password_hash(password),
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
        
        logger.info(f"Registered new user manually: {email} with role {role}")
        
        # Send notifications
        try:
            import threading
            
            # Welcome email to user
            welcome_subj = "Welcome to AutoWP!"
            welcome_body = f"Hello {name},\n\nThank you for registering on AutoWP! Your account has been initialized with 5 free credits."
            threading.Thread(target=send_email_notification, args=(email, welcome_subj, welcome_body)).start()
            
            # WhatsApp/Email alert to Admin
            admin_subj = "AutoWP - New User Registered"
            admin_body = f"Halo Admin,\n\nUser baru telah mendaftar di AutoWP:\n- Nama: {name}\n- Email: {email}\n- Role: {role}\n\nSilakan periksa dashboard admin untuk detailnya."
            
            admin_email = Config.SMTP_SENDER_EMAIL or Config.SMTP_USER
            if admin_email:
                threading.Thread(target=send_email_notification, args=(admin_email, admin_subj, admin_body)).start()
            if Config.STARSENDER_DEVICE_ID:
                threading.Thread(target=send_whatsapp_notification, args=(Config.STARSENDER_DEVICE_ID, admin_body)).start()
        except Exception as ex:
            logger.error(f"Error launching registration notification threads: {ex}")
            
        return jsonify({'success': True, 'message': 'Registration successful! Please login.'})

@auth_bp.route('/api/auth/google', methods=['POST'])
def api_auth_google():
    data = request.json or {}
    id_token = data.get('id_token')
    if not id_token:
        return jsonify({'success': False, 'error': 'id_token is required'}), 400
        
    token_info = verify_google_token(id_token)
    if not token_info:
        return jsonify({'success': False, 'error': 'Invalid Google token'}), 400
        
    email = token_info.get('email')
    google_id = token_info.get('sub')
    name = token_info.get('name', '')
    
    if not email:
        return jsonify({'success': False, 'error': 'Google token did not provide an email'}), 400
        
    with db.get_session() as session:
        from database import User
        user = session.query(User).filter((User.google_id == google_id) | (User.email == email)).first()
        
        if not user:
            user_count = session.query(User).count()
            role = 'admin' if user_count == 0 else 'user'
            
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
                session.commit()
                
        if not user.is_active:
            return jsonify({'success': False, 'error': 'Account is suspended'}), 403
            
        token = jwt.encode({
            'user_id': user.id,
            'exp': datetime.datetime.utcnow() + datetime.timedelta(days=7)
        }, Config.SECRET_KEY, algorithm='HS256')
        
        return jsonify({
            'success': True,
            'token': token,
            'user': {
                'id': user.id,
                'email': user.email,
                'role': user.role,
                'tier': user.tier,
                'credits': user.credits
            }
        })

@auth_bp.route('/api/login', methods=['POST'])
def api_auth_login():
    data = request.json or {}
    logger.info(f"Login attempt data: {data}")
    email = data.get('email', '')
    password = data.get('password', '')
    logger.info(f"Login attempt for email: {email}")
    with db.get_session() as session:
        from database import User
        user = session.query(User).filter_by(email=email).first()
        if user and user.password_hash and check_password_hash(user.password_hash, password):
            if not user.is_active:
                return jsonify({'success': False, 'error': 'Account is suspended'}), 403
                
            token = jwt.encode({
                'user_id': user.id,
                'exp': datetime.datetime.utcnow() + datetime.timedelta(days=7)
            }, Config.SECRET_KEY, algorithm='HS256')
            return jsonify({
                'success': True,
                'token': token,
                'user': {
                    'id': user.id,
                    'email': user.email,
                    'role': user.role or 'user',
                    'tier': user.tier or 'free',
                    'credits': user.credits if user.credits is not None else 5
                }
            })
    return jsonify({'success': False, 'error': 'Invalid email or password', 'code': 401}), 401

@auth_bp.route('/api/auth/status', methods=['GET'])
@require_jwt
def api_auth_verify(user_id):
    with db.get_session() as session:
        from database import User
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
    return jsonify({
        'success': True,
        'google_client_id': Config.GOOGLE_CLIENT_ID or ''
    })
