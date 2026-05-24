from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, Text, JSON, Float, Index
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

class Config(Base):
    __tablename__ = 'config'
    
    id = Column(Integer, primary_key=True)
    gemini_api_key = Column(String(500))
    gemini_model = Column(String(100), default='gemini-2.5-pro')
    wordpress_url = Column(String(500))
    wordpress_username = Column(String(200))
    wordpress_password = Column(String(500))
    interval_hours = Column(Integer, default=6)  # Deprecated, kept for backward compatibility
    schedule_hours = Column(String(100), default='0,6,12,18')  # Comma-separated hours
    categories = Column(JSON, default=[])
    selected_categories = Column(JSON, default=[])
    auto_post = Column(Boolean, default=False)
    
    # Telegram settings
    telegram_bot_token = Column(String(500))
    telegram_chat_id = Column(String(200))
    telegram_enabled = Column(Boolean, default=False)
    telegram_channel_id = Column(String(200))
    telegram_post_to_channel = Column(Boolean, default=False)
    
    # Facebook settings
    facebook_page_id = Column(String(200))
    facebook_access_token = Column(String(500))
    facebook_enabled = Column(Boolean, default=False)
    
    # Twitter/X settings
    twitter_api_key = Column(String(500))
    twitter_api_secret = Column(String(500))
    twitter_access_token = Column(String(500))
    twitter_access_secret = Column(String(500))
    twitter_enabled = Column(Boolean, default=False)
    
    # Threads settings
    threads_user_id = Column(String(200))
    threads_access_token = Column(String(500))
    threads_enabled = Column(Boolean, default=False)
    
    # Auto Research settings
    auto_research_enabled = Column(Boolean, default=False)
    use_research_topics = Column(Boolean, default=False)

    article_prompt = Column(Text, default=None)
    image_prompt = Column(Text, default=None)
    
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

class PostLog(Base):
    __tablename__ = 'post_logs'
    
    id = Column(Integer, primary_key=True)
    post_id = Column(Integer)
    post_url = Column(String(500))
    category_id = Column(Integer)
    category_name = Column(String(200))
    title = Column(String(500), index=True)
    success = Column(Boolean, index=True)
    result = Column(Text)
    
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
    category = Column(String(200), index=True)
    trending_topics = Column(JSON)
    rising_topics = Column(JSON)
    top_topics = Column(JSON)
    suggested_topics = Column(JSON)
    keywords = Column(JSON)
    questions = Column(JSON)
    long_tail_keywords = Column(JSON)
    used = Column(Boolean, default=False, index=True)
    created_at = Column(DateTime, default=datetime.now, index=True)

class Database:
    def __init__(self, db_url):
        try:
            self.engine = create_engine(
                db_url,
                poolclass=QueuePool,
                pool_size=5,
                max_overflow=10,
                pool_pre_ping=True,
                pool_recycle=3600,
                echo=False
            )
            Base.metadata.create_all(self.engine)
            session_factory = sessionmaker(bind=self.engine)
            self.Session = scoped_session(session_factory)
            logger.info("Database initialized successfully")
        except Exception as e:
            logger.error(f"Database initialization failed: {e}")
            raise
    
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
    
    def get_config(self):
        with self.get_session() as session:
            config = session.query(Config).first()
            if not config:
                config = Config(
                    gemini_api_key='',
                    wordpress_url='',
                    wordpress_username='',
                    wordpress_password='',
                    interval_hours=6,
                    schedule_hours='0,6,12,18',
                    categories=[],
                    selected_categories=[],
                    auto_post=False,
                    telegram_bot_token='',
                    telegram_chat_id='',
                    telegram_enabled=False
                )
                session.add(config)
                session.commit()
            return {
                'gemini_api_key': config.gemini_api_key or '',
                'gemini_model': config.gemini_model or 'gemini-2.5-pro',
                'wordpress_url': config.wordpress_url or '',
                'wordpress_username': config.wordpress_username or '',
                'wordpress_password': config.wordpress_password or '',
                'interval_hours': config.interval_hours,
                'schedule_hours': config.schedule_hours or '0,6,12,18',
                'categories': config.categories or [],
                'selected_categories': config.selected_categories or [],
                'auto_post': config.auto_post,
                'telegram_bot_token': config.telegram_bot_token or '',
                'telegram_chat_id': config.telegram_chat_id or '',
                'telegram_enabled': config.telegram_enabled or False,
                'telegram_channel_id': config.telegram_channel_id or '',
                'telegram_post_to_channel': config.telegram_post_to_channel or False,
                'facebook_page_id': config.facebook_page_id or '',
                'facebook_access_token': config.facebook_access_token or '',
                'facebook_enabled': config.facebook_enabled or False,
                'twitter_api_key': config.twitter_api_key or '',
                'twitter_api_secret': config.twitter_api_secret or '',
                'twitter_access_token': config.twitter_access_token or '',
                'twitter_access_secret': config.twitter_access_secret or '',
                'twitter_enabled': config.twitter_enabled or False,
                'threads_user_id': config.threads_user_id or '',
                'threads_access_token': config.threads_access_token or '',
                'threads_enabled': config.threads_enabled or False,
                'auto_research_enabled': config.auto_research_enabled or False,
                'use_research_topics': config.use_research_topics or False,
                'article_prompt': config.article_prompt or '',
                'image_prompt': config.image_prompt or ''
            }
    
    def save_config(self, data):
        with self.get_session() as session:
            config = session.query(Config).first()
            if not config:
                config = Config()
                session.add(config)
            
            config.gemini_api_key = data.get('gemini_api_key', '')
            config.gemini_model = data.get('gemini_model', 'gemini-2.5-pro')
            config.wordpress_url = data.get('wordpress_url', '')
            config.wordpress_username = data.get('wordpress_username', '')
            config.wordpress_password = data.get('wordpress_password', '')
            config.interval_hours = data.get('interval_hours', 6)
            config.schedule_hours = data.get('schedule_hours', '0,6,12,18')
            config.categories = data.get('categories', [])
            config.selected_categories = data.get('selected_categories', [])
            config.auto_post = data.get('auto_post', False)
            config.telegram_bot_token = data.get('telegram_bot_token', '')
            config.telegram_chat_id = data.get('telegram_chat_id', '')
            config.telegram_enabled = data.get('telegram_enabled', False)
            config.telegram_channel_id = data.get('telegram_channel_id', '')
            config.telegram_post_to_channel = data.get('telegram_post_to_channel', False)
            config.facebook_page_id = data.get('facebook_page_id', '')
            config.facebook_access_token = data.get('facebook_access_token', '')
            config.facebook_enabled = data.get('facebook_enabled', False)
            config.twitter_api_key = data.get('twitter_api_key', '')
            config.twitter_api_secret = data.get('twitter_api_secret', '')
            config.twitter_access_token = data.get('twitter_access_token', '')
            config.twitter_access_secret = data.get('twitter_access_secret', '')
            config.twitter_enabled = data.get('twitter_enabled', False)
            config.threads_user_id = data.get('threads_user_id', '')
            config.threads_access_token = data.get('threads_access_token', '')
            config.threads_enabled = data.get('threads_enabled', False)
            config.auto_research_enabled = data.get('auto_research_enabled', False)
            config.use_research_topics = data.get('use_research_topics', False)
            config.article_prompt = data.get('article_prompt') or None
            config.image_prompt = data.get('image_prompt') or None
    
    def add_log(self, category_id, category_name, title, success, result, post_id=None, post_url=None):
        with self.get_session() as session:
            log = PostLog(
                post_id=post_id,
                post_url=post_url,
                category_id=category_id,
                category_name=category_name,
                title=title,
                success=success,
                result=result[:500]
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
    
    def get_logs(self, limit=50):
        with self.get_session() as session:
            logs = session.query(PostLog).order_by(PostLog.created_at.desc()).limit(limit).all()
            return [{
                'id': log.id,
                'post_id': log.post_id,
                'post_url': log.post_url,
                'category': log.category_name,
                'title': log.title,
                'success': log.success,
                'result': log.result,
                'timestamp': log.created_at.isoformat(),
                'views': log.views,
                'comments': log.comments,
                'engagement_score': round(log.engagement_score, 2)
            } for log in logs]
    
    def get_stats(self):
        with self.get_session() as session:
            total = session.query(PostLog).count()
            success = session.query(PostLog).filter(PostLog.success == True).count()
            return {
                'total_posts': total,
                'successful_posts': success,
                'failed_posts': total - success
            }
    
    def get_category_performance(self):
        from sqlalchemy import func
        with self.get_session() as session:
            results = session.query(
                PostLog.category_name,
                func.count(PostLog.id).label('total_posts'),
                func.avg(PostLog.engagement_score).label('avg_engagement'),
                func.sum(PostLog.views).label('total_views'),
                func.sum(PostLog.comments).label('total_comments')
            ).filter(
                PostLog.success == True
            ).group_by(
                PostLog.category_name
            ).all()
            
            return [{
                'category': r.category_name,
                'total_posts': r.total_posts,
                'avg_engagement': round(r.avg_engagement or 0, 2),
                'total_views': r.total_views or 0,
                'total_comments': r.total_comments or 0
            } for r in results]
    
    def get_top_performing_posts(self, limit=10):
        with self.get_session() as session:
            logs = session.query(PostLog).filter(
                PostLog.success == True
            ).order_by(
                PostLog.engagement_score.desc()
            ).limit(limit).all()
            
            return [{
                'title': log.title,
                'category': log.category_name,
                'engagement_score': round(log.engagement_score, 2),
                'views': log.views,
                'comments': log.comments,
                'created_at': log.created_at.isoformat()
            } for log in logs]
    
    def get_existing_titles(self, category_name=None, limit=50):
        with self.get_session() as session:
            query = session.query(PostLog.title).filter(PostLog.success == True)
            
            if category_name:
                query = query.filter(PostLog.category_name == category_name)
            
            logs = query.order_by(PostLog.created_at.desc()).limit(limit).all()
            return [log.title for log in logs]
    
    def save_research_data(self, category, trending, rising, top, suggestions, keywords=None, questions=None, long_tail=None):
        with self.get_session() as session:
            research = ResearchData(
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
            
            session.add(research)
            session.commit()
            logger.info(f"Research data saved for category: {category}")
    
    def get_unused_research_topic(self, category):
        with self.get_session() as session:
            research = session.query(ResearchData).filter(
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
    
    def get_latest_research(self, category):
        with self.get_session() as session:
            return session.query(ResearchData).filter(
                ResearchData.category == category
            ).order_by(ResearchData.created_at.desc()).first()
    
    def close(self):
        try:
            self.Session.remove()
            self.engine.dispose()
            logger.info("Database connections closed")
        except Exception as e:
            logger.error(f"Error closing database: {e}")
