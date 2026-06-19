import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Flask
    DEBUG = False
    SECRET_KEY = os.getenv('SECRET_KEY', os.urandom(24).hex())
    
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
