import logging
from cryptography.fernet import Fernet

from config import load_or_create_runtime_secret

logger = logging.getLogger(__name__)

# Lazily created; the key is 32 bytes, URL-safe base64 encoded.
_fernet_instance = None

def get_fernet():
    global _fernet_instance
    if _fernet_instance is not None:
        return _fernet_instance

    key = load_or_create_runtime_secret(
        'FERNET_KEY',
        'fernet_key',
        lambda: Fernet.generate_key().decode()
    )

    try:
        _fernet_instance = Fernet(key.encode())
    except Exception as e:
        raise RuntimeError('Fernet encryption key is corrupt or invalid. Restore from backup. DO NOT auto-regenerate or all encrypted data will be lost.') from e

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
            logger.critical(f"Decryption failed for ciphertext (prefix gAAAAA). FERNET_KEY has likely changed. "
                          f"Restore from backup or re-enter the credential. Error: {e}")
            raise ValueError(f"Decryption failed for sensitive value: {e}")
        # Value is not fernet-encoded — assume plaintext from migration or legacy data
        logger.warning("Value is not encrypted; storing plaintext is deprecated. Please re-save this configuration.")
        return value
