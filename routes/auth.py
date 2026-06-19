import datetime
import jwt
from flask import Blueprint, request, jsonify
from werkzeug.security import check_password_hash

from core_extensions import db, logger, require_jwt
from config import Config

auth_bp = Blueprint('auth', __name__)

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
        if user and check_password_hash(user.password_hash, password):
            token = jwt.encode({
                'user_id': user.id,
                'exp': datetime.datetime.utcnow() + datetime.timedelta(days=7)
            }, Config.SECRET_KEY, algorithm='HS256')
            return jsonify({'success': True, 'token': token, 'user': {'id': user.id, 'email': user.email}})
    return jsonify({'success': False, 'error': 'Invalid email or password', 'code': 401}), 401

@auth_bp.route('/api/auth/status', methods=['GET'])
@require_jwt
def api_auth_verify(user_id):
    return jsonify({'authenticated': True, 'user_id': user_id})
