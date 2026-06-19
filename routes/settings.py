from flask import Blueprint, request, jsonify
from core_extensions import db, load_config, save_config, require_jwt, require_admin

settings_bp = Blueprint('settings', __name__)

@settings_bp.route('/api/settings')
@require_jwt
def api_settings(user_id):
    from database import User
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
        config['gemini_model'] = data.get('gemini_model', 'gemini-2.5-pro')
    else:
        config['gemini_api_key'] = request.form.get('gemini_api_key', '')
        config['gemini_model'] = request.form.get('gemini_model', 'gemini-2.5-pro')
    
    # Save the config under the current user (which is the admin)
    save_config(user_id, config)

    # Return JSON success response
    return jsonify({'success': True, 'message': 'Configuration saved!'})

@settings_bp.route('/api/profile', methods=['GET', 'POST'])
@require_jwt
def api_profile(user_id):
    from database import User
    from werkzeug.security import generate_password_hash
    with db.get_session() as session:
        user = session.query(User).filter_by(id=user_id).first()
        if not user:
            return jsonify({'success': False, 'error': 'User not found'}), 404
            
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
            user.name = name
        if email is not None and email != user.email:
            # Check if email is already taken
            existing = session.query(User).filter_by(email=email).first()
            if existing:
                return jsonify({'success': False, 'error': 'Email already in use'}), 400
            user.email = email
            
        if password:
            user.password_hash = generate_password_hash(password)
            
        session.commit()
        return jsonify({'success': True, 'message': 'Profile updated successfully'})
