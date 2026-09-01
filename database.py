import os
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.pool import QueuePool
from contextlib import contextmanager
import logging
from sqlalchemy import exc, event

from models import Base, Config, WordPressSite, PostLog, ResearchData, SystemSetting
from config import DEFAULT_GEMINI_MODEL, DEFAULT_GEMINI_IMAGE_MODEL

logger = logging.getLogger(__name__)

# Arbitrary but fixed key for the pg advisory lock that serialises migrations.
MIGRATION_LOCK_ID = 4207311001

# Bump this whenever a new migration step is added to _run_migrations_locked so
# that already-migrated databases re-run the set exactly once.
SCHEMA_VERSION = 4
SCHEMA_VERSION_KEY = '__schema_version__'


class Database:
    def __init__(self, db_url):
        if not db_url.startswith(('postgresql://', 'postgresql+psycopg2://')):
            raise ValueError('Database requires a PostgreSQL URL.')

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
            self.session_factory = sessionmaker(bind=self.engine)
            self.Session = scoped_session(self.session_factory)
            
            logger.info("Database initialized successfully")
        except Exception as e:
            logger.error(f"Database initialization failed: {e}")
            raise
            
    def run_migrations(self):
        """Run schema/data migrations under a PostgreSQL advisory lock.

        Several processes (4 gunicorn workers, the RQ worker, the scheduler) start at
        the same time and gunicorn recycles workers periodically. Without this guard
        they race on the same ALTER TABLE statements and re-run the full-table data
        migrations on every worker respawn. pg_try_advisory_lock lets exactly one
        process do the work; everyone else returns immediately.
        """
        from sqlalchemy import text

        conn = self.engine.connect()
        acquired = False
        try:
            acquired = bool(conn.execute(
                text("SELECT pg_try_advisory_lock(:lock_id)"),
                {'lock_id': MIGRATION_LOCK_ID}
            ).scalar())
            conn.commit()

            if not acquired:
                logger.info("Migrations already running in another process; skipping.")
                return

            if self._schema_version_matches(conn):
                logger.info(f"Schema already at version {SCHEMA_VERSION}; skipping migrations.")
                return

            self._run_migrations_locked()
            self._record_schema_version(conn)
        finally:
            if acquired:
                try:
                    conn.rollback()
                    conn.execute(
                        text("SELECT pg_advisory_unlock(:lock_id)"),
                        {'lock_id': MIGRATION_LOCK_ID}
                    )
                    conn.commit()
                except Exception as e:
                    logger.error(f"Failed to release migration advisory lock: {e}")
            conn.close()

    def _schema_version_matches(self, conn):
        """True when the database is already at the current schema version."""
        from sqlalchemy import text
        try:
            current = conn.execute(
                text("SELECT value FROM system_settings WHERE key = :k"),
                {'k': SCHEMA_VERSION_KEY}
            ).scalar()
            conn.commit()
            return current == str(SCHEMA_VERSION)
        except Exception as e:
            # system_settings does not exist yet on a brand new database.
            conn.rollback()
            logger.info(f"Could not read schema version ({e}); running migrations.")
            return False

    def _record_schema_version(self, conn):
        from sqlalchemy import text
        try:
            conn.execute(
                text(
                    "INSERT INTO system_settings (key, value) VALUES (:k, :v) "
                    "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
                ),
                {'k': SCHEMA_VERSION_KEY, 'v': str(SCHEMA_VERSION)}
            )
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.warning(f"Could not record schema version: {e}")

    def _run_migrations_locked(self):
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
            self.migrate_add_posting_started_at_column()
        except Exception as em:
            logger.warning(f"Database posting_started_at migration warning: {em}")

        try:
            self.migrate_research_quality_columns()
        except Exception as em:
            logger.warning(f"Database research quality migration warning: {em}")

        try:
            self.migrate_search_console_foundation()
        except Exception as em:
            logger.warning(f"Database Search Console migration warning: {em}")

        try:
            self.migrate_credit_system_tables()
        except Exception as em:
            logger.warning(f"Database credit system migration warning: {em}")
            
        try:
            self.migrate_add_foreign_keys()
        except Exception as em:
            logger.warning(f"Database foreign keys migration warning: {em}")
        logger.info("Database migrations completed successfully")
    
    @contextmanager
    def get_session(self):
        session = self.session_factory()
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
        from security import decrypt_value
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
                    '_pinterest_access_token': 'pinterest_access_token',
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
                res = session.execute(text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name='wordpress_sites' AND column_name='timezone'"
                )).fetchone()
                if not res:
                    session.execute(text("ALTER TABLE wordpress_sites ADD COLUMN timezone VARCHAR(100) DEFAULT 'Asia/Jakarta'"))
                    session.commit()
                    logger.info("Added column 'timezone' to 'wordpress_sites' table")
            except Exception as e:
                logger.warning(f"Timezone migration warning: {e}")

    def migrate_add_language_column(self):
        from sqlalchemy import text
        with self.get_session() as session:
            try:
                res = session.execute(text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name='wordpress_sites' AND column_name='language'"
                )).fetchone()
                if not res:
                    session.execute(text("ALTER TABLE wordpress_sites ADD COLUMN language VARCHAR(50) DEFAULT 'id'"))
                    session.commit()
                    logger.info("Added column 'language' to 'wordpress_sites' table")
            except Exception as e:
                logger.warning(f"Language migration warning: {e}")

    def migrate_add_posting_started_at_column(self):
        """Track when a queue item entered 'posting' so stuck items can be recovered."""
        from sqlalchemy import text
        with self.get_session() as session:
            try:
                res = session.execute(text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name='content_queue' AND column_name='posting_started_at'"
                )).fetchone()
                if not res:
                    session.execute(text(
                        "ALTER TABLE content_queue ADD COLUMN posting_started_at TIMESTAMP NULL"
                    ))
                    # Backfill existing in-flight rows so the reaper has a baseline and
                    # does not treat them as abandoned forever.
                    session.execute(text(
                        "UPDATE content_queue SET posting_started_at = created_at "
                        "WHERE status = 'posting'"
                    ))
                    session.commit()
                    logger.info("Added column 'posting_started_at' to 'content_queue' table")
            except Exception as e:
                logger.warning(f"posting_started_at migration warning: {e}")

    def migrate_research_quality_columns(self):
        """Add auditable research metadata without invalidating legacy rows."""
        from sqlalchemy import text
        columns = {
            'semantic_context': 'TEXT',
            'news_insights': 'JSON',
            'source_metadata': 'JSON',
            'quality_score': 'INTEGER DEFAULT 0',
            'confidence_level': "VARCHAR(20) DEFAULT 'unknown'",
            'is_fallback': 'BOOLEAN DEFAULT FALSE',
            'researched_at': 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP',
        }
        with self.get_session() as session:
            for name, sql_type in columns.items():
                session.execute(text(
                    f'ALTER TABLE research_data ADD COLUMN IF NOT EXISTS {name} {sql_type}'
                ))
            session.execute(text(
                'CREATE INDEX IF NOT EXISTS idx_research_researched_at '
                'ON research_data (researched_at)'
            ))

    def migrate_search_console_foundation(self):
        """Add encrypted GSC connection fields and analytics snapshot table."""
        from sqlalchemy import text
        site_columns = {
            'gsc_client_id': 'VARCHAR(500)',
            'gsc_client_secret': 'TEXT',
            'gsc_refresh_token': 'TEXT',
            'gsc_property_url': 'VARCHAR(500)',
            'gsc_permission_level': 'VARCHAR(50)',
            'gsc_connected_at': 'TIMESTAMP',
            'gsc_last_synced_at': 'TIMESTAMP',
            'gsc_last_error': 'TEXT',
        }
        with self.get_session() as session:
            for name, sql_type in site_columns.items():
                session.execute(text(
                    f'ALTER TABLE wordpress_sites ADD COLUMN IF NOT EXISTS {name} {sql_type}'
                ))

    def migrate_credit_system_tables(self):
        from sqlalchemy import text
        with self.get_session() as session:
            try:
                for col, col_type, default_val in [
                    ('role', 'VARCHAR(50)', "'user'"),
                    ('tier', 'VARCHAR(50)', "'free'"),
                    ('credits', 'INTEGER', "5"),
                    ('google_id', 'VARCHAR(255)', "NULL")
                ]:
                    res = session.execute(text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name='users' AND column_name=:col"
                    ), {'col': col}).fetchone()
                    if not res:
                        # col, col_type, default_val are from a hardcoded whitelist above, not user input
                        session.execute(text(f"ALTER TABLE users ADD COLUMN {col} {col_type} DEFAULT {default_val}"))
                        session.commit()
                        logger.info(f"Added column '{col}' to 'users' table")

                res_config = session.execute(text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name='config' AND column_name='gemini_image_model'"
                )).fetchone()
                if not res_config:
                    session.execute(text("ALTER TABLE config ADD COLUMN gemini_image_model VARCHAR(100) DEFAULT 'gemini-3.1-flash-image'"))
                    session.commit()
                    logger.info("Added column 'gemini_image_model' to 'config' table")

                # Auto-migrate old imagen models to gemini-3.1-flash-image
                session.execute(text("UPDATE config SET gemini_image_model = 'gemini-3.1-flash-image' WHERE gemini_image_model LIKE 'imagen-%'"))
                session.execute(text("UPDATE system_settings SET value = 'gemini-3.1-flash-image' WHERE key = 'gemini_image_model' AND value LIKE 'imagen-%'"))
                session.commit()
            except Exception as e:
                logger.warning(f"Credit system user/config migration warning: {e}")
                
    def migrate_add_foreign_keys(self):
        from sqlalchemy import text
        with self.get_session() as session:
            try:
                tables = ['transactions', 'config', 'wordpress_sites', 'post_logs', 'research_data', 'content_queue']
                for table in tables:
                    # Check if foreign key exists
                    res = session.execute(text(f"""
                        SELECT constraint_name 
                        FROM information_schema.table_constraints 
                        WHERE table_name='{table}' AND constraint_type='FOREIGN KEY' AND constraint_name='fk_{table}_user_id'
                    """)).fetchone()
                    
                    if not res:
                        # Clean up orphans before adding constraint
                        session.execute(text(f"DELETE FROM {table} WHERE user_id NOT IN (SELECT id FROM users)"))
                        # Add constraint
                        session.execute(text(f"ALTER TABLE {table} ADD CONSTRAINT fk_{table}_user_id FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE"))
                        session.commit()
                        logger.info(f"Added foreign key constraint fk_{table}_user_id to {table}")
            except Exception as e:
                logger.warning(f"Foreign keys migration warning: {e}")
    
    def get_config(self, user_id):
        with self.get_session() as session:
            config = session.query(Config).filter_by(user_id=user_id).first()
            if not config:
                config = Config(
                    user_id=user_id,
                    gemini_api_key='',
                    gemini_model=DEFAULT_GEMINI_MODEL,
                    gemini_image_model=DEFAULT_GEMINI_IMAGE_MODEL
                )
                session.add(config)
                session.commit()
            return {
                'gemini_api_key': config.gemini_api_key or '',
                'gemini_model': config.gemini_model or DEFAULT_GEMINI_MODEL,
                'gemini_image_model': config.gemini_image_model or DEFAULT_GEMINI_IMAGE_MODEL
            }
    
    def save_config(self, user_id, data):
        with self.get_session() as session:
            config = session.query(Config).filter_by(user_id=user_id).first()
            if not config:
                config = Config(user_id=user_id)
                session.add(config)
            
            if 'gemini_api_key' in data and data.get('gemini_api_key'):
                config.gemini_api_key = data['gemini_api_key']
            if 'gemini_model' in data:
                config.gemini_model = data.get('gemini_model') or DEFAULT_GEMINI_MODEL
            if 'gemini_image_model' in data:
                config.gemini_image_model = data.get('gemini_image_model') or DEFAULT_GEMINI_IMAGE_MODEL
    
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

    def reserve_user_credits(self, user_id, amount=1):
        if amount <= 0:
            return True

        from sqlalchemy import text
        with self.get_session() as session:
            result = session.execute(
                text(
                    "UPDATE users "
                    "SET credits = COALESCE(credits, 0) - :amount "
                    "WHERE id = :user_id AND COALESCE(credits, 0) >= :amount"
                ),
                {'user_id': user_id, 'amount': amount}
            )
            return result.rowcount == 1

    def refund_user_credits(self, user_id, amount=1):
        if amount <= 0:
            return True

        from sqlalchemy import text
        with self.get_session() as session:
            result = session.execute(
                text(
                    "UPDATE users "
                    "SET credits = COALESCE(credits, 0) + :amount "
                    "WHERE id = :user_id"
                ),
                {'user_id': user_id, 'amount': amount}
            )
            return result.rowcount == 1
    
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
                'timestamp': log.created_at.isoformat() + ('Z' if log.created_at.tzinfo is None else ''),
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
                PostLog.success.is_(True)
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
                PostLog.success.is_(True)
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
                'created_at': log.created_at.isoformat() + ('Z' if log.created_at.tzinfo is None else '')
            } for log in logs]
    
    def get_existing_titles(self, user_id, site_id=None, category_name=None, limit=50):
        with self.get_session() as session:
            query = session.query(PostLog.title).filter(PostLog.user_id == user_id, PostLog.success.is_(True))
            
            if site_id is not None:
                query = query.filter(PostLog.site_id == site_id)
                
            if category_name:
                query = query.filter(PostLog.category_name == category_name)
            
            logs = query.order_by(PostLog.created_at.desc()).limit(limit).all()
            return [log.title for log in logs]
    
    def save_research_data(self, user_id, site_id, category, trending, rising, top,
                           suggestions, keywords=None, questions=None, long_tail=None,
                           competitor_outlines=None, youtube_insights=None,
                           social_insights=None, trend_score=0, semantic_context='',
                           news_insights=None, source_metadata=None, quality_score=0,
                           confidence_level='unknown', is_fallback=False,
                           researched_at=None):
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
            research.semantic_context = semantic_context or ''
            research.news_insights = news_insights or []
            research.source_metadata = source_metadata or {}
            research.quality_score = int(quality_score or 0)
            research.confidence_level = confidence_level or 'unknown'
            research.is_fallback = bool(is_fallback)
            research.researched_at = researched_at or datetime.now()
            
            session.add(research)
            session.commit()
            logger.info(f"Research data saved for category: {category}")
    
    def get_unused_research_topic(self, user_id, site_id, category):
        with self.get_session() as session:
            research = session.query(ResearchData).filter(
                ResearchData.user_id == user_id,
                ResearchData.site_id == site_id,
                ResearchData.category == category,
                ResearchData.used.is_(False)
            ).order_by(ResearchData.created_at.desc()).first()
            
            if research and research.suggested_topics:
                topics_list = list(research.suggested_topics) if research.suggested_topics else []
                topic = topics_list[0] if topics_list else None
                if topic:
                    topics_list.pop(0)
                    research.suggested_topics = topics_list
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
