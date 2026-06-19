import os
from cryptography.fernet import Fernet
from dotenv import load_dotenv

load_dotenv()

# Key length for Fernet is 32 bytes URL-safe base64 encoded
_fernet_instance = None

def get_fernet():
    global _fernet_instance
    if _fernet_instance is not None:
        return _fernet_instance

    key = os.getenv('FERNET_KEY')
    env_file = '.env'

    if not key:
        # Random sleep if .env does not exist to let another concurrent container write it
        if not os.path.exists(env_file):
            import time
            import random
            time.sleep(random.uniform(0.1, 0.6))
            
        # Re-check if key is now in .env file
        if os.path.exists(env_file):
            try:
                with open(env_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        if line.startswith('FERNET_KEY='):
                            candidate = line.split('=', 1)[1].strip()
                            if candidate:
                                key = candidate
                                os.environ['FERNET_KEY'] = key
                                break
            except Exception as e:
                print(f"Error reading existing FERNET_KEY from .env: {e}")

    if not key:
        # Generate new key if still not found
        new_key = Fernet.generate_key().decode()
        key = new_key
        
        # Append to .env file if it exists, otherwise create it
        try:
            # Check if FERNET_KEY is already defined but empty
            if os.path.exists(env_file):
                with open(env_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                if 'FERNET_KEY=' in content:
                    # Replace it
                    import re
                    content = re.sub(r'FERNET_KEY=.*', f'FERNET_KEY={new_key}', content)
                    with open(env_file, 'w', encoding='utf-8') as f:
                        f.write(content)
                else:
                    # Append it
                    with open(env_file, 'a', encoding='utf-8') as f:
                        if not content.endswith('\n'):
                            f.write('\n')
                        f.write(f'FERNET_KEY={new_key}\n')
            else:
                with open(env_file, 'w', encoding='utf-8') as f:
                    f.write(f'FERNET_KEY={new_key}\n')
            
            # Update current env
            os.environ['FERNET_KEY'] = new_key
        except Exception as e:
            # If writing fails, we still use the key in memory
            print(f"Warning: Failed to write FERNET_KEY to .env: {e}")
            
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
            logger.warning(f"Value looks like encrypted ciphertext but decryption failed (InvalidToken): {e}. "
                           "This usually means the FERNET_KEY has changed or was generated differently across processes. "
                           "Please update/re-save your credentials in settings.")
        # Assume it's plain-text already
        return value
