import os
import logging
from cryptography.fernet import Fernet
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()

# Key length for Fernet is 32 bytes URL-safe base64 encoded
_fernet_instance = None

def _load_or_create_runtime_secret(env_name, filename, generator):
    value = os.getenv(env_name)
    if value:
        return value

    runtime_dir = os.getenv('AUTOWP_RUNTIME_DIR', 'runtime')
    secret_file = os.getenv(f'{env_name}_FILE', os.path.join(runtime_dir, filename))

    try:
        secret_dir = os.path.dirname(secret_file)
        if secret_dir:
            os.makedirs(secret_dir, exist_ok=True)

        if os.path.exists(secret_file):
            with open(secret_file, 'r', encoding='utf-8') as f:
                value = f.read().strip()
                if value:
                    os.environ[env_name] = value
                    return value

        value = generator()
        try:
            with open(secret_file, 'x', encoding='utf-8') as f:
                f.write(value)
            try:
                os.chmod(secret_file, 0o600)
            except OSError:
                pass
        except FileExistsError:
            with open(secret_file, 'r', encoding='utf-8') as f:
                existing = f.read().strip()
                if existing:
                    value = existing

        os.environ[env_name] = value
        return value
    except Exception as e:
        logger.warning(f"Failed to persist {env_name} to {secret_file}: {e}")
        value = generator()
        os.environ[env_name] = value
        return value

def get_fernet():
    global _fernet_instance
    if _fernet_instance is not None:
        return _fernet_instance

    key = _load_or_create_runtime_secret(
        'FERNET_KEY',
        'fernet_key',
        lambda: Fernet.generate_key().decode()
    )
            
    try:
        _fernet_instance = Fernet(key.encode())
    except Exception as e:
        raise RuntimeError('Fernet encryption key is corrupt or invalid. Restore from backup. DO NOT auto-regenerate or all encrypted data will be lost.')
        
    return _fernet_instance

def encrypt_value(value: str) -> str:
    """Encrypt a string value using Fernet."""
    if not value:
        return value
    try:
        f = get_fernet()
        return f.encrypt(value.encode()).decode()
    except Exception as e:
        logger.error(f"Encryption error: {e}")
        return value

def decrypt_value(value: str) -> str:
    """Decrypt a string value using Fernet. Returns original value if not encrypted."""
    if not value:
        return value
    try:
        f = get_fernet()
        # If it's encrypted, decrypt it. If it fails, it might be plain-text
        return f.decrypt(value.encode()).decode()
    except Exception as e:
        if isinstance(value, str) and value.startswith('gAAAAA'):
            logger.warning(f"Decryption failed for ciphertext. The FERNET_KEY has likely changed. Error: {e}")
            return ""
        # Assume it's plain-text already
        return value

import secrets
from functools import wraps
from flask import session, request, abort

def generate_csrf_token():
    if '_csrf_token' not in session:
        session['_csrf_token'] = secrets.token_hex(32)
    return session['_csrf_token']

def csrf_protect(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if request.method == 'POST':
            token = request.form.get('_csrf_token') or request.headers.get('X-CSRF-Token')
            if not token or token != session.get('_csrf_token'):
                abort(403)
        return f(*args, **kwargs)
    return decorated
