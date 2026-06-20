from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, Text, JSON, Float, Index, ForeignKey, event, exc
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.pool import QueuePool
from contextlib import contextmanager
from datetime import datetime
from cryptography.fernet import Fernet
import os
import logging

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
    user_id = Column(Integer, index=True)
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
    user_id = Column(Integer, index=True)
    _gemini_api_key = Column('gemini_api_key', String(500))
    gemini_model = Column(String(100), default='gemini-2.5-pro')
    gemini_image_model = Column(String(100), default='gemini-3.1-flash-image')
    
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
    user_id = Column(Integer, index=True)
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

class PostLog(Base):
    __tablename__ = 'post_logs'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, index=True)
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
    user_id = Column(Integer, index=True)
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
    used = Column(Boolean, default=False, index=True)
    created_at = Column(DateTime, default=datetime.now, index=True)

class ContentQueue(Base):
    __tablename__ = 'content_queue'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, index=True)
    site_id = Column(Integer, ForeignKey('wordpress_sites.id', ondelete='CASCADE'), index=True, nullable=True)
    category = Column(String(200), index=True)
    title = Column(String(500))
    target_keywords = Column(String(500))
    status = Column(String(50), default='pending') # pending, posting, posted, failed
    post_url = Column(String(500))
    created_at = Column(DateTime, default=datetime.now)

class SystemSetting(Base):
    __tablename__ = 'system_settings'
    
    key = Column(String(100), primary_key=True)
    value = Column(Text, nullable=True)

class Database:
    def __init__(self, db_url):
        try:
            self.engine = create_engine(
                db_url,
                poolclass=QueuePool,
                pool_size=10,
                max_overflow=20,
                pool_pre_ping=True,
                pool_recycle=1800,
                echo=False
            )
            
            # Dispose of connections after process fork (multiprocessing safety)
            @event.listens_for(self.engine, "connect")
            def connect(dbapi_connection, connection_record):
                connection_record.info['pid'] = os.getpid()

            @event.listens_for(self.engine, "checkout")
            def checkout(dbapi_connection, connection_record, connection_proxy):
                pid = os.getpid()
                if connection_record.info.get('pid') != pid:
                    connection_record.connection = connection_proxy.connection = None
                    raise exc.DisconnectionError(
                        "Connection record belonged to a different process (forked worker)"
                    )
            try:
                Base.metadata.create_all(self.engine)
            except Exception as e:
                logger.warning(f"Database initialization conflict (expected in multi-process startup): {e}")
            session_factory = sessionmaker(bind=self.engine)
            self.Session = scoped_session(session_factory)
            
            try:
                self.migrate_to_project_based()
            except Exception as em:
                logger.warning(f"Project migration warning: {em}")
                
            try:
                self.migrate_plain_configs()
            except Exception as em:
                logger.warning(f"Database plain config migration warning: {em}")
            
            try:
                self.migrate_add_timezone_column()
            except Exception as em:
                logger.warning(f"Database timezone migration warning: {em}")
            
            try:
                self.migrate_add_language_column()
            except Exception as em:
                logger.warning(f"Database language migration warning: {em}")
            
            try:
                self.migrate_credit_system_tables()
            except Exception as em:
                logger.warning(f"Database credit system migration warning: {em}")
            logger.info("Database initialized successfully")
        except Exception as e:
            logger.error(f"Database initialization failed: {e}")
            raise
    
    def migrate_to_project_based(self):
        from sqlalchemy import text
        import json
        with self.get_session() as session:
            # Check if any sites exist
            site_count = session.query(WordPressSite).count()
            if site_count > 0:
                return # Already migrated or new installation

            try:
                # Try to fetch old config using raw SQL (columns might still exist in SQLite)
                result = session.execute(text("SELECT * FROM config")).fetchall()
                if not result:
                    return
                
                # Get column names from the result
                columns = session.execute(text("PRAGMA table_info(config)")).fetchall()
                col_names = [col[1] for col in columns]
                
                migrated = False
                for row in result:
                    row_dict = dict(zip(col_names, row))
                    user_id = row_dict.get('user_id')
                    wp_url = row_dict.get('wordpress_url')
                    
                    if not wp_url:
                        continue
                        
                    # Parse JSON fields safely
                    cats = row_dict.get('categories', [])
                    sel_cats = row_dict.get('selected_categories', [])
                    if isinstance(cats, str): 
                        try: cats = json.loads(cats)
                        except: cats = []
                    if isinstance(sel_cats, str): 
                        try: sel_cats = json.loads(sel_cats)
                        except: sel_cats = []

                    # Create the first site
                    site = WordPressSite(
                        user_id=user_id,
                        site_name="My First Website",
                        wordpress_url=wp_url,
                        wordpress_username=row_dict.get('wordpress_username', ''),
                        _wordpress_password=row_dict.get('wordpress_password', ''),

                        schedule_hours=row_dict.get('schedule_hours', '0,6,12,18'),
                        categories=cats,
                        selected_categories=sel_cats,
                        auto_post=row_dict.get('auto_post', False),
                        _telegram_bot_token=row_dict.get('telegram_bot_token', ''),
                        telegram_chat_id=row_dict.get('telegram_chat_id', ''),
                        telegram_enabled=row_dict.get('telegram_enabled', False),
                        telegram_channel_id=row_dict.get('telegram_channel_id', ''),
                        telegram_post_to_channel=row_dict.get('telegram_post_to_channel', False),
                        facebook_page_id=row_dict.get('facebook_page_id', ''),
                        _facebook_access_token=row_dict.get('facebook_access_token', ''),
                        facebook_enabled=row_dict.get('facebook_enabled', False),
                        _twitter_api_key=row_dict.get('twitter_api_key', ''),
                        _twitter_api_secret=row_dict.get('twitter_api_secret', ''),
                        _twitter_access_token=row_dict.get('twitter_access_token', ''),
                        _twitter_access_secret=row_dict.get('twitter_access_secret', ''),
                        twitter_enabled=row_dict.get('twitter_enabled', False),
                        threads_user_id=row_dict.get('threads_user_id', ''),
                        _threads_access_token=row_dict.get('threads_access_token', ''),
                        threads_enabled=row_dict.get('threads_enabled', False),

                        article_prompt=row_dict.get('article_prompt'),
                        image_prompt=row_dict.get('image_prompt')
                    )
                    
                    session.add(site)
                    session.flush() # To get site.id
                    
                    # Update all related tables
                    session.execute(text(f"UPDATE post_logs SET site_id = {site.id} WHERE user_id = {user_id} AND site_id IS NULL"))
                    session.execute(text(f"UPDATE research_data SET site_id = {site.id} WHERE user_id = {user_id} AND site_id IS NULL"))
                    session.execute(text(f"UPDATE content_queue SET site_id = {site.id} WHERE user_id = {user_id} AND site_id IS NULL"))
                    
                    migrated = True
                    
                if migrated:
                    session.commit()
                    logger.info("Successfully migrated project-based data.")
            except Exception as e:
                logger.error(f"Migration error (ignorable if new install): {e}")

    @contextmanager
    def get_session(self):
        session = self.Session()
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"Database session error: {e}")
            raise
        finally:
            session.close()

    def migrate_plain_configs(self):
        from security import decrypt_value, encrypt_value
        with self.get_session() as session:
            migrated = False
            
            # Migrate Config table
            configs = session.query(Config).all()
            for config in configs:
                val = getattr(config, '_gemini_api_key', None)
                if val and val.strip() and not val.startswith('gAAAAA'):
                    decrypted = decrypt_value(val)
                    if decrypted == val:
                        setattr(config, 'gemini_api_key', val)
                        migrated = True
            
            # Migrate WordPressSite table
            sites = session.query(WordPressSite).all()
            for site in sites:
                field_map = {
                    '_wordpress_password': 'wordpress_password',
                    '_telegram_bot_token': 'telegram_bot_token',
                    '_facebook_access_token': 'facebook_access_token',
                    '_twitter_api_key': 'twitter_api_key',
                    '_twitter_api_secret': 'twitter_api_secret',
                    '_twitter_access_token': 'twitter_access_token',
                    '_twitter_access_secret': 'twitter_access_secret',
                    '_threads_access_token': 'threads_access_token'
                }
                for backing_col, prop_name in field_map.items():
                    val = getattr(site, backing_col, None)
                    if val and val.strip() and not val.startswith('gAAAAA'):
                        decrypted = decrypt_value(val)
                        if decrypted == val:
                            setattr(site, prop_name, val)
                            migrated = True
            
            if migrated:
                session.commit()
                logger.info("Migrated plaintext credentials in database to encrypted format successfully.")

    def migrate_add_timezone_column(self):
        from sqlalchemy import text
        with self.get_session() as session:
            try:
                is_postgres = 'postgresql' in str(self.engine.url)
                if is_postgres:
                    res = session.execute(text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name='wordpress_sites' AND column_name='timezone'"
                    )).fetchone()
                    if not res:
                        session.execute(text("ALTER TABLE wordpress_sites ADD COLUMN timezone VARCHAR(100) DEFAULT 'Asia/Jakarta'"))
                        session.commit()
                        logger.info("Added column 'timezone' to 'wordpress_sites' table in PostgreSQL")
                else:
                    res = session.execute(text("PRAGMA table_info(wordpress_sites)")).fetchall()
                    cols = [col[1] for col in res]
                    if 'timezone' not in cols:
                        session.execute(text("ALTER TABLE wordpress_sites ADD COLUMN timezone VARCHAR(100) DEFAULT 'Asia/Jakarta'"))
                        session.commit()
                        logger.info("Added column 'timezone' to 'wordpress_sites' table in SQLite")
            except Exception as e:
                logger.warning(f"Timezone migration warning: {e}")

    def migrate_add_language_column(self):
        from sqlalchemy import text
        with self.get_session() as session:
            try:
                is_postgres = 'postgresql' in str(self.engine.url)
                if is_postgres:
                    res = session.execute(text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name='wordpress_sites' AND column_name='language'"
                    )).fetchone()
                    if not res:
                        session.execute(text("ALTER TABLE wordpress_sites ADD COLUMN language VARCHAR(50) DEFAULT 'id'"))
                        session.commit()
                        logger.info("Added column 'language' to 'wordpress_sites' table in PostgreSQL")
                else:
                    res = session.execute(text("PRAGMA table_info(wordpress_sites)")).fetchall()
                    cols = [col[1] for col in res]
                    if 'language' not in cols:
                        session.execute(text("ALTER TABLE wordpress_sites ADD COLUMN language VARCHAR(50) DEFAULT 'id'"))
                        session.commit()
                        logger.info("Added column 'language' to 'wordpress_sites' table in SQLite")
            except Exception as e:
                logger.warning(f"Language migration warning: {e}")

    def migrate_credit_system_tables(self):
        from sqlalchemy import text
        with self.get_session() as session:
            try:
                is_postgres = 'postgresql' in str(self.engine.url)
                if is_postgres:
                    for col, col_type, default_val in [
                        ('role', 'VARCHAR(50)', "'user'"),
                        ('tier', 'VARCHAR(50)', "'free'"),
                        ('credits', 'INTEGER', "5"),
                        ('google_id', 'VARCHAR(255)', "NULL")
                    ]:
                        res = session.execute(text(
                            f"SELECT column_name FROM information_schema.columns "
                            f"WHERE table_name='users' AND column_name='{col}'"
                        )).fetchone()
                        if not res:
                            session.execute(text(f"ALTER TABLE users ADD COLUMN {col} {col_type} DEFAULT {default_val}"))
                            session.commit()
                            logger.info(f"Added column '{col}' to 'users' table in PostgreSQL")
                            
                    res_config = session.execute(text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name='config' AND column_name='gemini_image_model'"
                    )).fetchone()
                    if not res_config:
                        session.execute(text("ALTER TABLE config ADD COLUMN gemini_image_model VARCHAR(100) DEFAULT 'gemini-3.1-flash-image'"))
                        session.commit()
                        logger.info("Added column 'gemini_image_model' to 'config' table in PostgreSQL")
                else:
                    res = session.execute(text("PRAGMA table_info(users)")).fetchall()
                    cols = [col[1] for col in res]
                    for col, col_type, default_val in [
                        ('role', 'VARCHAR(50)', "'user'"),
                        ('tier', 'VARCHAR(50)', "'free'"),
                        ('credits', 'INTEGER', "5"),
                        ('google_id', 'VARCHAR(255)', "NULL")
                    ]:
                        if col not in cols:
                            session.execute(text(f"ALTER TABLE users ADD COLUMN {col} {col_type} DEFAULT {default_val}"))
                            session.commit()
                            logger.info(f"Added column '{col}' to 'users' table in SQLite")
                            
                    res_config = session.execute(text("PRAGMA table_info(config)")).fetchall()
                    cols_config = [col[1] for col in res_config]
                    if 'gemini_image_model' not in cols_config:
                        session.execute(text("ALTER TABLE config ADD COLUMN gemini_image_model VARCHAR(100) DEFAULT 'gemini-3.1-flash-image'"))
                        session.commit()
                        logger.info("Added column 'gemini_image_model' to 'config' table in SQLite")
            except Exception as e:
                logger.warning(f"Credit system user/config migration warning: {e}")
    
    def get_config(self, user_id):
        with self.get_session() as session:
            config = session.query(Config).filter_by(user_id=user_id).first()
            if not config:
                config = Config(
                    user_id=user_id,
                    gemini_api_key='',
                    gemini_model='gemini-2.5-pro',
                    gemini_image_model='gemini-3.1-flash-image'
                )
                session.add(config)
                session.commit()
            return {
                'gemini_api_key': config.gemini_api_key or '',
                'gemini_model': config.gemini_model or 'gemini-2.5-pro',
                'gemini_image_model': config.gemini_image_model or 'gemini-3.1-flash-image'
            }
    
    def save_config(self, user_id, data):
        with self.get_session() as session:
            config = session.query(Config).filter_by(user_id=user_id).first()
            if not config:
                config = Config(user_id=user_id)
                session.add(config)
            
            config.gemini_api_key = data.get('gemini_api_key', '')
            config.gemini_model = data.get('gemini_model', 'gemini-2.5-pro')
            config.gemini_image_model = data.get('gemini_image_model', 'gemini-3.1-flash-image')
    
    def get_system_settings(self):
        with self.get_session() as session:
            try:
                settings = session.query(SystemSetting).all()
                return {s.key: s.value for s in settings}
            except Exception as e:
                logger.error(f"Error reading system settings: {e}")
                return {}

    def save_system_settings(self, settings_dict):
        with self.get_session() as session:
            for k, v in settings_dict.items():
                try:
                    setting = session.query(SystemSetting).filter_by(key=k).first()
                    if not setting:
                        setting = SystemSetting(key=k, value=str(v) if v is not None else None)
                        session.add(setting)
                    else:
                        setting.value = str(v) if v is not None else None
                except Exception as e:
                    logger.error(f"Error saving system setting {k}: {e}")
            try:
                session.commit()
            except Exception as e:
                session.rollback()
                logger.error(f"Error committing system settings: {e}")
                raise e
    
    def add_log(self, user_id, site_id, category_id, category_name, title, success, result, post_id=None, post_url=None, image_failed=False):
        with self.get_session() as session:
            log = PostLog(
                user_id=user_id,
                site_id=site_id,
                post_id=post_id,
                post_url=post_url,
                category_id=category_id,
                category_name=category_name,
                title=title,
                success=success,
                result=result[:500],
                image_failed=image_failed
            )
            session.add(log)
            session.flush()
            return log.id
    
    def update_engagement(self, log_id, views=0, comments=0, likes=0, shares=0):
        with self.get_session() as session:
            log = session.query(PostLog).filter(PostLog.id == log_id).first()
            if log:
                log.views = views
                log.comments = comments
                log.likes = likes
                log.shares = shares
                log.engagement_score = (views * 0.1) + (comments * 2) + (likes * 1) + (shares * 3)
                log.last_synced = datetime.now()
    
    def get_logs(self, user_id, site_id=None, limit=50):
        with self.get_session() as session:
            query = session.query(PostLog).filter_by(user_id=user_id)
            if site_id is not None:
                query = query.filter_by(site_id=site_id)
            logs = query.order_by(PostLog.created_at.desc()).limit(limit).all()
            return [{
                'id': log.id,
                'post_id': log.post_id,
                'post_url': log.post_url,
                'category': log.category_name,
                'title': log.title,
                'success': log.success,
                'image_failed': log.image_failed,
                'result': log.result,
                'timestamp': log.created_at.isoformat(),
                'views': log.views,
                'comments': log.comments,
                'engagement_score': round(log.engagement_score, 2)
            } for log in logs]
    
    def get_stats(self, user_id, site_id=None):
        with self.get_session() as session:
            query = session.query(PostLog).filter_by(user_id=user_id)
            if site_id is not None:
                query = query.filter_by(site_id=site_id)
                
            total = query.count()
            success = query.filter_by(success=True).count()
            success_rate = round((success / total * 100), 1) if total > 0 else 0.0
            return {
                'total_posts': total,
                'successful_posts': success,
                'failed_posts': total - success,
                'success_rate': success_rate
            }
    
    def get_category_performance(self, user_id, site_id=None):
        from sqlalchemy import func
        with self.get_session() as session:
            query = session.query(
                PostLog.category_name,
                func.count(PostLog.id).label('total_posts'),
                func.avg(PostLog.engagement_score).label('avg_engagement'),
                func.sum(PostLog.views).label('total_views'),
                func.sum(PostLog.comments).label('total_comments')
            ).filter(
                PostLog.user_id == user_id,
                PostLog.success == True
            )
            
            if site_id is not None:
                query = query.filter(PostLog.site_id == site_id)
                
            results = query.group_by(PostLog.category_name).all()
            
            return [{
                'category': r.category_name,
                'total_posts': r.total_posts,
                'avg_engagement': round(r.avg_engagement or 0, 2),
                'total_views': r.total_views or 0,
                'total_comments': r.total_comments or 0
            } for r in results]
    
    def get_top_performing_posts(self, user_id, site_id=None, limit=10):
        with self.get_session() as session:
            query = session.query(PostLog).filter(
                PostLog.user_id == user_id,
                PostLog.success == True
            )
            
            if site_id is not None:
                query = query.filter(PostLog.site_id == site_id)
                
            logs = query.order_by(PostLog.engagement_score.desc()).limit(limit).all()
            
            return [{
                'title': log.title,
                'category': log.category_name,
                'engagement_score': round(log.engagement_score, 2),
                'views': log.views,
                'comments': log.comments,
                'created_at': log.created_at.isoformat()
            } for log in logs]
    
    def get_existing_titles(self, user_id, site_id=None, category_name=None, limit=50):
        with self.get_session() as session:
            query = session.query(PostLog.title).filter(PostLog.user_id == user_id, PostLog.success == True)
            
            if site_id is not None:
                query = query.filter(PostLog.site_id == site_id)
                
            if category_name:
                query = query.filter(PostLog.category_name == category_name)
            
            logs = query.order_by(PostLog.created_at.desc()).limit(limit).all()
            return [log.title for log in logs]
    
    def save_research_data(self, user_id, site_id, category, trending, rising, top, suggestions, keywords=None, questions=None, long_tail=None, competitor_outlines=None, youtube_insights=None, social_insights=None, trend_score=0):
        with self.get_session() as session:
            research = ResearchData(
                user_id=user_id,
                site_id=site_id,
                category=category,
                trending_topics=trending,
                rising_topics=rising,
                top_topics=top,
                suggested_topics=suggestions
            )
            
            # Add SEO research data if provided
            if keywords:
                research.keywords = keywords
            if questions:
                research.questions = questions
            if long_tail:
                research.long_tail_keywords = long_tail
            if competitor_outlines is not None:
                research.competitor_outlines = competitor_outlines
            if youtube_insights is not None:
                research.youtube_insights = youtube_insights
            if social_insights is not None:
                research.social_insights = social_insights
            research.trend_score = trend_score
            
            session.add(research)
            session.commit()
            logger.info(f"Research data saved for category: {category}")
    
    def get_unused_research_topic(self, user_id, site_id, category):
        with self.get_session() as session:
            research = session.query(ResearchData).filter(
                ResearchData.user_id == user_id,
                ResearchData.site_id == site_id,
                ResearchData.category == category,
                ResearchData.used == False
            ).order_by(ResearchData.created_at.desc()).first()
            
            if research and research.suggested_topics:
                topic = research.suggested_topics[0] if research.suggested_topics else None
                if topic:
                    research.suggested_topics.pop(0)
                    if not research.suggested_topics:
                        research.used = True
                    session.commit()
                    return topic.get('topic') if isinstance(topic, dict) else topic
            return None
    
    def get_latest_research(self, user_id, site_id, category):
        with self.get_session() as session:
            return session.query(ResearchData).filter(
                ResearchData.user_id == user_id,
                ResearchData.site_id == site_id,
                ResearchData.category == category
            ).order_by(ResearchData.created_at.desc()).first()
    
    def close(self):
        try:
            self.Session.remove()
            self.engine.dispose()
            logger.info("Database connections closed")
        except Exception as e:
            logger.error(f"Error closing database: {e}")
