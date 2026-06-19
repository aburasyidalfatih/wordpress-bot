from flask import Blueprint, request, jsonify
from core_extensions import db, load_config, save_config, require_jwt

settings_bp = Blueprint('settings', __name__)

@settings_bp.route('/api/settings')
@require_jwt
def api_settings(user_id):
    config = load_config(user_id)
    return jsonify({'config': config})

@settings_bp.route("/save-config", methods=["POST"])
@require_jwt
def save_config_route(user_id):
    config = load_config(user_id)
    
    config['gemini_api_key'] = request.form.get('gemini_api_key', '')
    config['gemini_model'] = request.form.get('gemini_model', 'gemini-2.5-pro')
    
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
                    'email': user.email or ''
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
