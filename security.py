import os
from cryptography.fernet import Fernet
from dotenv import load_dotenv

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
        print(f"Warning: Failed to persist {env_name} to {secret_file}: {e}")
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
        # Fallback in case key is corrupted
        print(f"Error initializing Fernet: {e}. Re-generating key...")
        new_key = Fernet.generate_key().decode()
        _fernet_instance = Fernet(new_key.encode())
        os.environ['FERNET_KEY'] = new_key
        
    return _fernet_instance

def encrypt_value(value: str) -> str:
    """Encrypt a string value using Fernet."""
    if not value:
        return value
    try:
        f = get_fernet()
        return f.encrypt(value.encode()).decode()
    except Exception as e:
        print(f"Encryption error: {e}")
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
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Decryption failed for ciphertext. The FERNET_KEY has likely changed. Error: {e}")
            # If we return ciphertext, it gets re-encrypted by the UI. Return empty string so user knows to re-enter it.
            return ""
        # Assume it's plain-text already
        return value
