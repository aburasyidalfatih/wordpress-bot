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
    """Encrypt a string value using Fernet. Raises RuntimeError on failure — never returns plaintext."""
    if not value:
        return value
    try:
        f = get_fernet()
        return f.encrypt(value.encode()).decode()
    except Exception as e:
        logger.critical(f"Encryption error: {e}. Refusing to store plaintext; configuration may not be saved.")
        raise RuntimeError(f"Failed to encrypt sensitive value: {e}") from e

def decrypt_value(value: str) -> str:
    """Decrypt a string value using Fernet. Returns empty string for ciphertext that cannot be decrypted
    (FERNET_KEY has changed). Returns plaintext as-is if value is not fernet-encoded."""
    if not value:
        return value
    try:
        f = get_fernet()
        return f.decrypt(value.encode()).decode()
    except Exception as e:
        if isinstance(value, str) and value.startswith('gAAAAA'):
            # This is fernet ciphertext but decryption failed — key has likely changed.
            # Return empty string rather than passing through ciphertext.
            logger.critical(f"Decryption failed for ciphertext (prefix gAAAAA). FERNET_KEY has likely changed. "
                          f"Restore from backup or re-enter the credential. Error: {e}")
            return ""
        # Value is not fernet-encoded — assume plaintext from migration or legacy data
        logger.warning(f"Value is not encrypted; storing plaintext is deprecated. Please re-save this configuration.")
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
