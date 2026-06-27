import os
import secrets
from dotenv import load_dotenv

load_dotenv()

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
    except Exception:
        value = generator()
        os.environ[env_name] = value
        return value

class Config:
    # Flask
    DEBUG = False
    SECRET_KEY = _load_or_create_runtime_secret(
        'SECRET_KEY',
        'secret_key',
        lambda: secrets.token_urlsafe(48)
    )
    
    # Database
    DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///wordpress_bot.db')
    
    # Redis
    REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
    
    # Scheduler
    SCHEDULER_JOBSTORE_URL = 'sqlite:///scheduler_jobs.db'
    
    # Logging
    LOG_FILE = 'bot.log'
    LOG_MAX_BYTES = 10485760  # 10MB
    LOG_BACKUP_COUNT = 5
    
    # API Timeouts
    API_TIMEOUT_SHORT = 10
    API_TIMEOUT_LONG = 60
    
    # Retry Configuration
    MAX_RETRIES = 3
    RETRY_BACKOFF = 2
    
    # Rate Limiting
    GEMINI_RATE_LIMIT = 60  # requests per minute
    WORDPRESS_RATE_LIMIT = 100

    # Payment Gateways (Tripay, Paypal, Manual)
    PAYMENT_TRIPAY_ENABLED = os.getenv('PAYMENT_TRIPAY_ENABLED', 'true').lower() == 'true'
    PAYMENT_PAYPAL_ENABLED = os.getenv('PAYMENT_PAYPAL_ENABLED', 'true').lower() == 'true'
    PAYMENT_MANUAL_ENABLED = os.getenv('PAYMENT_MANUAL_ENABLED', 'true').lower() == 'true'
    
    TRIPAY_API_KEY = os.getenv('TRIPAY_API_KEY', 'MOCK_TRIPAY_API_KEY')
    TRIPAY_PRIVATE_KEY = os.getenv('TRIPAY_PRIVATE_KEY', 'MOCK_TRIPAY_PRIVATE_KEY')
    TRIPAY_MERCHANT_CODE = os.getenv('TRIPAY_MERCHANT_CODE', 'MOCK_MERCHANT_CODE')
    TRIPAY_API_URL = os.getenv('TRIPAY_API_URL', 'https://tripay.co.id/api-sandbox')
    
    PAYPAL_CLIENT_ID = os.getenv('PAYPAL_CLIENT_ID', 'MOCK_PAYPAL_CLIENT_ID')
    PAYPAL_SECRET = os.getenv('PAYPAL_SECRET', 'MOCK_PAYPAL_SECRET')
    PAYPAL_API_URL = os.getenv('PAYPAL_API_URL', 'https://api-m.sandbox.paypal.com')
    
    PAYMENT_USD_RATE = float(os.getenv('PAYMENT_USD_RATE', '16000.0'))
    
    # Google OAuth
    GOOGLE_CLIENT_ID = os.getenv('GOOGLE_CLIENT_ID', '')
    GOOGLE_CLIENT_SECRET = os.getenv('GOOGLE_CLIENT_SECRET', '')
    
    # SMTP Settings (SMTP Mailketing)
    SMTP_HOST = os.getenv('SMTP_HOST', '')
    SMTP_PORT = int(os.getenv('SMTP_PORT', '587'))
    SMTP_USER = os.getenv('SMTP_USER', '')
    SMTP_PASSWORD = os.getenv('SMTP_PASSWORD', '')
    SMTP_SENDER_EMAIL = os.getenv('SMTP_SENDER_EMAIL', '')
    
    # Starsender WA Gateway
    STARSENDER_API_KEY = os.getenv('STARSENDER_API_KEY', '')
    STARSENDER_DEVICE_ID = os.getenv('STARSENDER_DEVICE_ID', '')

    # Manual Bank Settings
    MANUAL_BANK_NAME = os.getenv('MANUAL_BANK_NAME', 'Bank Mandiri')
    MANUAL_BANK_ACCOUNT = os.getenv('MANUAL_BANK_ACCOUNT', '12345-67890-123')
    MANUAL_BANK_HOLDER = os.getenv('MANUAL_BANK_HOLDER', 'ADMIN AUTOWP')
    ADMIN_WHATSAPP = os.getenv('ADMIN_WHATSAPP', '628123456789')
