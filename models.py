from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, JSON, Float, Index, ForeignKey, UniqueConstraint
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime
import logging
from config import DEFAULT_GEMINI_MODEL, DEFAULT_GEMINI_IMAGE_MODEL

logger = logging.getLogger(__name__)
Base = declarative_base()

class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True)
    name = Column(String(100))
    email = Column(String(120), unique=True, index=True)
    password_hash = Column(String(255), nullable=True) # Google-only users might not have a password hash
    created_at = Column(DateTime, default=datetime.now)
    is_active = Column(Boolean, default=True)
    role = Column(String(50), default='user') # 'admin' or 'user'
    tier = Column(String(50), default='free') # 'free' or 'pro'
    credits = Column(Integer, default=5)
    google_id = Column(String(255), unique=True, nullable=True)

class Transaction(Base):
    __tablename__ = 'transactions'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), index=True)
    payment_method = Column(String(50)) # 'manual', 'tripay', 'paypal'
    invoice_id = Column(String(255), unique=True)
    credits_purchased = Column(Integer)
    amount = Column(Float)
    receipt_url = Column(String(500), nullable=True)
    status = Column(String(50), default='pending') # 'pending', 'awaiting_approval', 'success', 'failed'
    created_at = Column(DateTime, default=datetime.now)

class Config(Base):
    __tablename__ = 'config'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), index=True)
    _gemini_api_key = Column('gemini_api_key', String(500))
    gemini_model = Column(String(100), default=DEFAULT_GEMINI_MODEL)
    gemini_image_model = Column(String(100), default=DEFAULT_GEMINI_IMAGE_MODEL)
    
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    @property
    def gemini_api_key(self):
        from security import decrypt_value
        return decrypt_value(self._gemini_api_key)
        
    @gemini_api_key.setter
    def gemini_api_key(self, value):
        from security import encrypt_value
        self._gemini_api_key = encrypt_value(value)

class WordPressSite(Base):
    __tablename__ = 'wordpress_sites'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), index=True)
    site_name = Column(String(200), default="My Website")
    wordpress_url = Column(String(500))
    wordpress_username = Column(String(200))
    _wordpress_password = Column('wordpress_password', String(500))

    schedule_hours = Column(String(100), default='0,6,12,18')
    timezone = Column(String(100), default='Asia/Jakarta')
    language = Column(String(50), default='id')
    categories = Column(JSON, default=[])
    selected_categories = Column(JSON, default=[])
    auto_post = Column(Boolean, default=False)
    
    # Telegram settings
    _telegram_bot_token = Column('telegram_bot_token', String(500))
    telegram_chat_id = Column(String(200))
    telegram_enabled = Column(Boolean, default=False)
    telegram_channel_id = Column(String(200))
    telegram_post_to_channel = Column(Boolean, default=False)
    
    # Facebook settings
    facebook_page_id = Column(String(200))
    _facebook_access_token = Column('facebook_access_token', String(500))
    facebook_enabled = Column(Boolean, default=False)
    
    # Pinterest settings
    pinterest_board_id = Column(String(200))
    _pinterest_access_token = Column('pinterest_access_token', String(500))
    pinterest_enabled = Column(Boolean, default=False)
    
    # Twitter/X settings
    _twitter_api_key = Column('twitter_api_key', String(500))
    _twitter_api_secret = Column('twitter_api_secret', String(500))
    _twitter_access_token = Column('twitter_access_token', String(500))
    _twitter_access_secret = Column('twitter_access_secret', String(500))
    twitter_enabled = Column(Boolean, default=False)
    
    # Threads settings
    threads_user_id = Column(String(200))
    _threads_access_token = Column('threads_access_token', String(500))
    threads_enabled = Column(Boolean, default=False)

    # Google Search Console (read-only OAuth)
    gsc_client_id = Column(String(500))
    _gsc_client_secret = Column('gsc_client_secret', Text)
    _gsc_refresh_token = Column('gsc_refresh_token', Text)
    gsc_property_url = Column(String(500))
    gsc_permission_level = Column(String(50))
    gsc_connected_at = Column(DateTime)
    gsc_last_synced_at = Column(DateTime)
    gsc_last_error = Column(Text)
    
    # Auto Research settings


    article_prompt = Column(Text, default=None)
    image_prompt = Column(Text, default=None)
    
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    @property
    def wordpress_password(self):
        from security import decrypt_value
        return decrypt_value(self._wordpress_password)
        
    @wordpress_password.setter
    def wordpress_password(self, value):
        from security import encrypt_value
        self._wordpress_password = encrypt_value(value)
        
    @property
    def telegram_bot_token(self):
        from security import decrypt_value
        return decrypt_value(self._telegram_bot_token)
        
    @telegram_bot_token.setter
    def telegram_bot_token(self, value):
        from security import encrypt_value
        self._telegram_bot_token = encrypt_value(value)
        
    @property
    def facebook_access_token(self):
        from security import decrypt_value
        return decrypt_value(self._facebook_access_token)
        
    @facebook_access_token.setter
    def facebook_access_token(self, value):
        from security import encrypt_value
        self._facebook_access_token = encrypt_value(value)
        
    @property
    def pinterest_access_token(self):
        from security import decrypt_value
        if not self._pinterest_access_token:
            return None
        return decrypt_value(self._pinterest_access_token)

    @pinterest_access_token.setter
    def pinterest_access_token(self, value):
        from security import encrypt_value
        if not value:
            self._pinterest_access_token = None
            return
        self._pinterest_access_token = encrypt_value(value)
        
    @property
    def twitter_api_key(self):
        from security import decrypt_value
        return decrypt_value(self._twitter_api_key)
        
    @twitter_api_key.setter
    def twitter_api_key(self, value):
        from security import encrypt_value
        self._twitter_api_key = encrypt_value(value)
        
    @property
    def twitter_api_secret(self):
        from security import decrypt_value
        return decrypt_value(self._twitter_api_secret)
        
    @twitter_api_secret.setter
    def twitter_api_secret(self, value):
        from security import encrypt_value
        self._twitter_api_secret = encrypt_value(value)
        
    @property
    def twitter_access_token(self):
        from security import decrypt_value
        return decrypt_value(self._twitter_access_token)
        
    @twitter_access_token.setter
    def twitter_access_token(self, value):
        from security import encrypt_value
        self._twitter_access_token = encrypt_value(value)
        
    @property
    def twitter_access_secret(self):
        from security import decrypt_value
        return decrypt_value(self._twitter_access_secret)
        
    @twitter_access_secret.setter
    def twitter_access_secret(self, value):
        from security import encrypt_value
        self._twitter_access_secret = encrypt_value(value)
        
    @property
    def threads_access_token(self):
        from security import decrypt_value
        return decrypt_value(self._threads_access_token)
        
    @threads_access_token.setter
    def threads_access_token(self, value):
        from security import encrypt_value
        self._threads_access_token = encrypt_value(value)

    @property
    def gsc_refresh_token(self):
        from security import decrypt_value
        return decrypt_value(self._gsc_refresh_token)

    @gsc_refresh_token.setter
    def gsc_refresh_token(self, value):
        from security import encrypt_value
        self._gsc_refresh_token = encrypt_value(value) if value else None

    @property
    def gsc_client_secret(self):
        from security import decrypt_value
        return decrypt_value(self._gsc_client_secret)

    @gsc_client_secret.setter
    def gsc_client_secret(self, value):
        from security import encrypt_value
        self._gsc_client_secret = encrypt_value(value) if value else None


class SearchConsoleMetric(Base):
    __tablename__ = 'search_console_metrics'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), index=True)
    site_id = Column(Integer, ForeignKey('wordpress_sites.id', ondelete='CASCADE'), index=True)
    property_url = Column(String(500))
    period_start = Column(DateTime, index=True)
    period_end = Column(DateTime, index=True)
    period_label = Column(String(20), index=True)  # current / previous
    query = Column(String(1000), index=True)
    page = Column(String(1500))
    clicks = Column(Float, default=0)
    impressions = Column(Float, default=0)
    ctr = Column(Float, default=0)
    position = Column(Float, default=0)
    synced_at = Column(DateTime, default=datetime.now, index=True)

    __table_args__ = (
        UniqueConstraint(
            'site_id', 'period_start', 'period_end', 'query', 'page',
            name='uq_gsc_metric_period_query_page'
        ),
        Index('idx_gsc_site_period', 'site_id', 'period_label', 'period_end'),
    )

class PostLog(Base):
    __tablename__ = 'post_logs'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), index=True)
    site_id = Column(Integer, ForeignKey('wordpress_sites.id', ondelete='CASCADE'), index=True, nullable=True)
    post_id = Column(Integer)
    post_url = Column(String(500))
    category_id = Column(Integer)
    category_name = Column(String(200))
    title = Column(String(500), index=True)
    success = Column(Boolean, index=True)
    result = Column(Text)
    image_failed = Column(Boolean, default=False)
    
    # Engagement metrics
    views = Column(Integer, default=0)
    comments = Column(Integer, default=0)
    likes = Column(Integer, default=0)
    shares = Column(Integer, default=0)
    engagement_score = Column(Float, default=0.0, index=True)
    
    created_at = Column(DateTime, default=datetime.now, index=True)
    last_synced = Column(DateTime)
    
    __table_args__ = (
        Index('idx_category_created', 'category_name', 'created_at'),
    )

class ResearchData(Base):
    __tablename__ = 'research_data'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), index=True)
    site_id = Column(Integer, ForeignKey('wordpress_sites.id', ondelete='CASCADE'), index=True, nullable=True)
    category = Column(String(200), index=True)
    trending_topics = Column(JSON)
    rising_topics = Column(JSON)
    top_topics = Column(JSON)
    suggested_topics = Column(JSON)
    keywords = Column(JSON)
    questions = Column(JSON)
    long_tail_keywords = Column(JSON)
    competitor_outlines = Column(JSON)
    youtube_insights = Column(JSON)
    social_insights = Column(JSON)
    trend_score = Column(Integer, default=0)
    semantic_context = Column(Text)
    news_insights = Column(JSON)
    source_metadata = Column(JSON)
    quality_score = Column(Integer, default=0)
    confidence_level = Column(String(20), default='unknown')
    is_fallback = Column(Boolean, default=False)
    researched_at = Column(DateTime, default=datetime.now, index=True)
    used = Column(Boolean, default=False, index=True)
    created_at = Column(DateTime, default=datetime.now, index=True)

class ContentQueue(Base):
    __tablename__ = 'content_queue'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), index=True)
    site_id = Column(Integer, ForeignKey('wordpress_sites.id', ondelete='CASCADE'), index=True, nullable=True)
    category = Column(String(200), index=True)
    title = Column(String(500))
    target_keywords = Column(String(500))
    status = Column(String(50), default='pending') # pending, posting, posted, failed
    post_url = Column(String(500))
    created_at = Column(DateTime, default=datetime.now)
    # Set when the item transitions to 'posting' so the dispatcher can detect and
    # recover items abandoned by a dead worker.
    posting_started_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index('idx_content_queue_user_site_status', 'user_id', 'site_id', 'status'),
    )

class SystemSetting(Base):
    __tablename__ = 'system_settings'
    
    key = Column(String(100), primary_key=True)
    value = Column(Text, nullable=True)

