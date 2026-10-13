from flask import Blueprint, request, jsonify, make_response
from werkzeug.security import generate_password_hash

from core_extensions import (
    db, load_config, save_config, require_jwt, require_admin,
    issue_access_token, revoke_user_tokens, set_auth_cookie,
)
from config import DEFAULT_GEMINI_MODEL
from models import User

settings_bp = Blueprint('settings', __name__)

MIN_PASSWORD_LENGTH = 8


@settings_bp.route('/api/settings')
@require_jwt
def api_settings(user_id):
    is_admin = False
    with db.get_session() as session:
        user = session.query(User).filter_by(id=user_id).first()
        if user and user.role == 'admin':
            is_admin = True

    config = load_config(user_id)
    if not is_admin:
        # Hide the API key for non-admins
        config = config.copy()
        config['gemini_api_key'] = ''

    return jsonify({'config': config})


@settings_bp.route("/save-config", methods=["POST"])
@require_admin
def save_config_route(user_id):
    config = load_config(user_id)

    # Support form-data and json
    if request.is_json:
        data = request.json or {}
        config['gemini_api_key'] = data.get('gemini_api_key', '')
        config['gemini_model'] = data.get('gemini_model', DEFAULT_GEMINI_MODEL)
    else:
        config['gemini_api_key'] = request.form.get('gemini_api_key', '')
        config['gemini_model'] = request.form.get('gemini_model', DEFAULT_GEMINI_MODEL)

    # Save the config under the current user (which is the admin)
    save_config(user_id, config)

    return jsonify({'success': True, 'message': 'Konfigurasi berhasil disimpan.'})


@settings_bp.route('/api/profile', methods=['GET', 'POST'])
@require_jwt
def api_profile(user_id):
    with db.get_session() as session:
        user = session.query(User).filter_by(id=user_id).first()
        if not user:
            return jsonify({'success': False, 'error': 'Pengguna tidak ditemukan.'}), 404

        if request.method == 'GET':
            return jsonify({
                'success': True,
                'profile': {
                    'name': user.name or '',
                    'email': user.email or '',
                    'role': user.role or 'user',
                    'tier': user.tier or 'free',
                    'credits': user.credits if user.credits is not None else 5
                }
            })

        # POST request
        data = request.json or {}
        name = data.get('name')
        email = data.get('email')
        password = data.get('password')

        if name is not None:
            user.name = str(name).strip()[:100]
        if email is not None and email != user.email:
            return jsonify({'success': False, 'error': 'Email tidak dapat diubah dari pengaturan profil.'}), 400

        if password:
            if not isinstance(password, str) or len(password) < MIN_PASSWORD_LENGTH:
                return jsonify({'success': False, 'error': f'Kata sandi minimal {MIN_PASSWORD_LENGTH} karakter.'}), 400
            user.password_hash = generate_password_hash(password)

        session.commit()

    if not password:
        return jsonify({'success': True, 'message': 'Profil berhasil diperbarui.'})

    # Password changed: log out every other session, keep this one with a fresh token.
    revoke_user_tokens(user_id)
    token = issue_access_token(user_id)
    resp = make_response(jsonify({'success': True, 'message': 'Profil berhasil diperbarui.', 'token': token}))
    return set_auth_cookie(resp, token)
