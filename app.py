from flask import Flask, render_template, request, jsonify, redirect, url_for, session, send_from_directory
from bot import ArticleGenerator, WordPressPublisher
from database import Database, ResearchData, PostLog
from ml_optimizer import ContentOptimizer
from trending_research import TrendingResearch
from dotenv import load_dotenv
import os
import requests
from datetime import datetime
import logging
import signal
import atexit
import sys
from functools import lru_cache, wraps
from time import time
import jwt
from redis import Redis
from rq import Queue
from rq.job import Job
from rq.exceptions import NoSuchJobError

from config import Config
from core_extensions import (
    db, q, redis_conn, optimizer, trending, logger,
    load_config, save_config, get_cached_stats,
    require_jwt, require_pin,
    send_telegram_notification, post_to_telegram_channel,
    post_to_facebook_page, post_to_twitter, post_to_threads
)

# Import blueprints
from routes.auth import auth_bp
from routes.queue import queue_bp
from routes.research import research_bp
from routes.dashboard import dashboard_bp
from routes.settings import settings_bp
from routes.monitor import monitor_bp
from routes.sites import sites_bp
from routes.prompts import prompts_bp
from routes.payments import payments_bp
from routes.admin import admin_bp

load_dotenv()

# Load system settings from database and override Config values on startup
try:
    system_settings = db.get_system_settings()
    for k, v in system_settings.items():
        if v is not None:
            if k in ['PAYMENT_TRIPAY_ENABLED', 'PAYMENT_PAYPAL_ENABLED', 'PAYMENT_MANUAL_ENABLED']:
                setattr(Config, k, v.lower() == 'true')
            elif k == 'SMTP_PORT':
                try:
                    setattr(Config, k, int(v))
                except ValueError:
                    pass
            elif k == 'PAYMENT_USD_RATE':
                try:
                    setattr(Config, k, float(v))
                except ValueError:
                    pass
            else:
                setattr(Config, k, v)
            os.environ[k] = v
    logger.info(f"Loaded {len(system_settings)} system settings from database.")
except Exception as e:
    logger.error(f"Failed to load system settings from database: {e}")

app = Flask(__name__)
app.config.from_object(Config)


# Register Blueprints
app.register_blueprint(auth_bp)
app.register_blueprint(queue_bp)
app.register_blueprint(research_bp)
app.register_blueprint(dashboard_bp)
app.register_blueprint(settings_bp)
app.register_blueprint(monitor_bp)
app.register_blueprint(sites_bp)
app.register_blueprint(prompts_bp)
app.register_blueprint(payments_bp)
app.register_blueprint(admin_bp)

# Background tasks & workers retained in app namespace for RQ compatibility

def regenerate_image_job(user_id, log_id):
    from database import PostLog, WordPressSite
    from bot import ArticleGenerator, WordPressPublisher
    try:
        config = load_config(user_id)
        generator = ArticleGenerator(
            config['gemini_api_key'], 
            config.get('gemini_model', 'gemini-2.5-pro'),
            config.get('gemini_image_model', 'gemini-3.1-flash-image')
        )
        
        with db.get_session() as session:
            log = session.query(PostLog).filter_by(id=log_id, user_id=user_id).first()
            if not log:
                logger.error(f"Post log not found for ID {log_id}")
                return
            
            title = log.title
            category_name = log.category_name
            post_id = log.post_id
            site_id = log.site_id
            
            if not site_id:
                # Fallback to first active site if site_id is missing from log
                site = session.query(WordPressSite).filter_by(user_id=user_id, is_active=True).first()
            else:
                site = session.query(WordPressSite).filter_by(id=site_id, user_id=user_id).first()
                
            if not site:
                logger.error(f"No active WordPress site found for user {user_id} and site {site_id}")
                return
                
            wordpress_url = site.wordpress_url
            wordpress_username = site.wordpress_username
            wordpress_password = site.wordpress_password
            site_name = site.site_name
            site_image_prompt = site.image_prompt
            
        if not post_id:
            logger.error("No post ID found in post log")
            return
            
        publisher = WordPressPublisher(
            wordpress_url,
            wordpress_username,
            wordpress_password
        )
            
        logger.info(f"Regenerating image for post {post_id} - {title}")
        custom_image_prompt = site_image_prompt or None
        
        image_data = generator.generate_image(
            category_name,
            title,
            "",
            custom_prompt=custom_image_prompt,
            site_name=site_name
        )
        
        if image_data:
            logger.info("Image generated, uploading to WordPress...")
            featured_image_id = publisher.upload_image(image_data, title)
            if featured_image_id:
                # Make HTTP POST to attach image to post
                headers = publisher._get_auth()
                headers['Content-Type'] = 'application/json'
                response = requests.post(
                    f"{publisher.api_url}/posts/{post_id}",
                    headers=headers,
                    json={'featured_media': featured_image_id},
                    timeout=30
                )
                if response.status_code == 200:
                    logger.info(f"Successfully attached image {featured_image_id} to post {post_id}")
                    with db.get_session() as session:
                        log = session.query(PostLog).filter_by(id=log_id).first()
                        if log:
                            log.image_failed = False
                            log.result = "Article and Featured Image published successfully."
                            session.commit()
                    return
                else:
                    raise Exception(f"WordPress attach media failed ({response.status_code}): {response.text}")
            else:
                raise Exception("WordPress image upload failed (check credentials or media library size)")
        else:
            raise Exception("Gemini image model failed to generate image data (verify API Key / Image Model)")
            
    except Exception as e:
        logger.error(f"Error in regenerate_image_job: {e}", exc_info=True)
        try:
            with db.get_session() as session:
                log = session.query(PostLog).filter_by(id=log_id).first()
                if log:
                    log.result = f"Image regeneration failed: {str(e)}"
                    session.commit()
        except Exception as db_err:
            logger.error(f"Failed to save error status: {db_err}")


def generate_and_post(user_id, item_id=None, site_id=None):
    config = load_config(user_id)
    from database import WordPressSite, User
    
    with db.get_session() as session:
        user = session.query(User).filter_by(id=user_id).first()
        if not user:
            logger.error(f"User {user_id} not found. Aborting generation.")
            return
        if (user.credits or 0) <= 0:
            logger.warning(f"User {user.email} has insufficient credits ({user.credits}). Aborting generation.")
            if item_id:
                from database import ContentQueue
                db_item = session.query(ContentQueue).filter_by(id=item_id).first()
                if db_item:
                    db_item.status = 'failed'
                    session.commit()
            return
            
        if item_id:
            from database import ContentQueue
            queue_item = session.query(ContentQueue).filter_by(id=item_id, user_id=user_id).first()
            if queue_item:
                site_id = queue_item.site_id
                
        if not site_id:
            logger.error("No site_id provided for generate_and_post")
            return
            
        site = session.query(WordPressSite).filter_by(id=site_id, user_id=user_id).first()
        if not site:
            logger.error(f"Site {site_id} not found")
            return
            
        # Create dictionary for legacy compatibility if needed
        site_config = {
            'wordpress_url': site.wordpress_url,
            'wordpress_username': site.wordpress_username,
            'wordpress_password': site.wordpress_password,
            'selected_categories': site.selected_categories,
            'categories': site.categories,
            'telegram_enabled': site.telegram_enabled,
            'telegram_bot_token': site.telegram_bot_token,
            'telegram_chat_id': site.telegram_chat_id,
            'telegram_channel_id': site.telegram_channel_id,
            'telegram_post_to_channel': site.telegram_post_to_channel,
            'facebook_enabled': site.facebook_enabled,
            'facebook_page_id': site.facebook_page_id,
            'facebook_access_token': site.facebook_access_token,
            'twitter_enabled': site.twitter_enabled,
            'twitter_api_key': site.twitter_api_key,
            'twitter_api_secret': site.twitter_api_secret,
            'twitter_access_token': site.twitter_access_token,
            'twitter_access_secret': site.twitter_access_secret,
            'threads_enabled': site.threads_enabled,
            'threads_user_id': site.threads_user_id,
            'threads_access_token': site.threads_access_token,
            'article_prompt': site.article_prompt,
            'image_prompt': site.image_prompt,
            'language': site.language,
            'auto_post': site.auto_post,
            'site_name': site.site_name
        }
    
    # Auto post check is bypassed if manual post (item_id provided)
    if not item_id and (not site_config['selected_categories'] or not site_config['auto_post']):
        logger.info(f"Auto post disabled or no categories selected for site {site_id}")
        return
    
    try:
        logger.info(f"Starting generate and post job for site {site_id}")
        generator = ArticleGenerator(
            config['gemini_api_key'], 
            config.get('gemini_model', 'gemini-2.5-pro'),
            config.get('gemini_image_model', 'gemini-3.1-flash-image')
        )
        publisher = WordPressPublisher(
            site_config['wordpress_url'],
            site_config['wordpress_username'],
            site_config['wordpress_password']
        )
        
        queue_item = None
        category = None
        custom_topic = None
        
        if item_id:
            from database import ContentQueue
            with db.get_session() as session:
                queue_item = session.query(ContentQueue).filter_by(id=item_id, user_id=user_id).first()
                if queue_item:
                    # Update status to posting
                    queue_item.status = 'posting'
                    session.commit()
                    
                    custom_topic = queue_item.title
                    category_name = queue_item.category
                    
                    # Find category dict
                    category_id = None
                    for cat in site_config.get('categories', []):
                        if cat['name'] == category_name:
                            category_id = cat['id']
                            break
                    if not category_id:
                        category_id = 1
                    category = {'name': category_name, 'id': category_id}
            
            if not category:
                logger.error(f"Queue item {item_id} not found or invalid.")
                return
        else:
            category = site_config['selected_categories'][0]
            logger.info(f"Selected category: {category['name']} (position 1 of {len(site_config['selected_categories'])})")
            
            # Rotate: move first to last
            with db.get_session() as session:
                site = session.query(WordPressSite).filter_by(id=site_id).first()
                if site and site.selected_categories:
                    site.selected_categories = site.selected_categories[1:] + [category]
                    session.commit()
            
            logger.info(f"Rotation complete.")
        
        send_telegram_notification(site_config, 
            f"🤖 <b>WordPress Auto Post Bot</b>\n\n"
            f"🌐 <b>Website:</b> {site_config['site_name']}\n"
            f"📝 Mulai generate artikel...\n"
            f"📂 Kategori: {category['name']}" + (f"\n🎯 Judul: {custom_topic}" if custom_topic else ""))
        
        existing_titles = db.get_existing_titles(user_id, site_id, category['name'], limit=50)
        
        # Check if should use research topic (only if not a manual queue item)
        seo_data = None
        if not item_id:
            custom_topic = db.get_unused_research_topic(user_id, site_id, category['name'])
            if custom_topic:
                logger.info(f"Using research topic: {custom_topic}")
            
            # Get SEO research data
            try:
                with db.get_session() as session:
                    research = session.query(ResearchData).filter(
                        ResearchData.site_id == site_id,
                        ResearchData.category == category['name']
                    ).order_by(ResearchData.created_at.desc()).first()
                    
                    if research:
                        seo_data = {
                            'keywords': research.keywords if hasattr(research, 'keywords') else [],
                            'questions': research.questions if hasattr(research, 'questions') else [],
                            'long_tail': research.long_tail_keywords if hasattr(research, 'long_tail_keywords') else []
                        }
                        logger.info(f"Using SEO data: {len(seo_data.get('keywords', []))} keywords, {len(seo_data.get('questions', []))} questions")
            except Exception as e:
                logger.error(f"Error getting SEO data: {e}")
        
        custom_article_prompt = site_config.get('article_prompt') or None
        custom_image_prompt = site_config.get('image_prompt') or None
        
        # Get category description from site categories list
        category_desc = ""
        for cat in site_config.get('categories', []):
            if cat.get('name') == category['name']:
                category_desc = cat.get('description', '')
                break
                
        article = generator.generate_article(
            category['name'], 
            existing_titles, 
            custom_topic, 
            seo_data,
            custom_prompt=custom_article_prompt,
            site_name=site_config.get('site_name'),
            language=site_config.get('language', 'id'),
            category_desc=category_desc
        )
        
        # Check for duplicate or similar titles
        def is_similar_title(new_title, existing_titles):
            """Check if title is duplicate or too similar"""
            import re
            from difflib import SequenceMatcher
            
            # Normalize title for comparison
            def normalize(text):
                text = re.sub(r'\d+', '', text.lower())
                text = re.sub(r'[^\w\s]', '', text)
                return ' '.join(text.split())
            
            # Extract main topic (first 5-6 words usually contain main topic)
            def get_main_topic(text):
                words = normalize(text).split()[:6]
                return ' '.join(words)
            
            new_normalized = normalize(new_title)
            new_main = get_main_topic(new_title)
            
            for existing in existing_titles:
                existing_normalized = normalize(existing)
                existing_main = get_main_topic(existing)
                
                # Check exact match
                if new_normalized == existing_normalized:
                    return True, existing, "exact"
                
                # Check character similarity (>60% = too similar)
                char_similarity = SequenceMatcher(None, new_normalized, existing_normalized).ratio()
                if char_similarity > 0.6:
                    return True, existing, f"char {char_similarity:.0%}"
                
                # Check main topic similarity (>75% = same topic)
                topic_similarity = SequenceMatcher(None, new_main, existing_main).ratio()
                if topic_similarity > 0.75:
                    return True, existing, f"topic {topic_similarity:.0%}"
            
            return False, None, None
        
        is_dup, similar_to, reason = is_similar_title(article.get('title', ''), existing_titles)
        
        if is_dup:
            logger.warning(f"Similar title detected ({reason}): '{article.get('title')}' ~ '{similar_to}'. Regenerating...")
            article = generator.generate_article(
                category['name'], 
                existing_titles, 
                custom_topic, 
                seo_data,
                avoid_similar=True,
                custom_prompt=custom_article_prompt,
                site_name=site_config.get('site_name'),
                language=site_config.get('language', 'id'),
                category_desc=category_desc
            )
        
        image_failed = False
        featured_image_id = None
        image_data = None
        
        try:
            logger.info("Generating featured image...")
            image_data = generator.generate_image(
                category['name'], 
                article.get('title', ''),
                article.get('content', ''),
                custom_prompt=custom_image_prompt,
                site_name=site_config.get('site_name')
            )
            if image_data:
                logger.info("Uploading featured image...")
                featured_image_id = publisher.upload_image(image_data, article.get('title', ''))
                if not featured_image_id:
                    image_failed = True
            else:
                image_failed = True
        except Exception as img_err:
            logger.error(f"Image generation or upload failed: {img_err}", exc_info=True)
            image_failed = True
        
        success, result = publisher.create_post(
            article.get('title', ''),
            article.get('content', ''),
            category['id'],
            featured_image_id,
            article.get('meta_description'),
            article.get('excerpt'),
            article.get('focus_keyword')
        )
        
        post_id = None
        post_url = None
        if success and isinstance(result, dict):
            post_id = result.get('id')
            post_url = result.get('link')
            if image_failed:
                result_msg = "Article published successfully, but Featured Image failed to generate or upload."
            else:
                result_msg = "Article and Featured Image published successfully."
        else:
            result_msg = str(result)
        
        db.add_log(
            user_id,
            site_id,
            category['id'],
            category['name'],
            article.get('title', ''),
            success,
            result_msg,
            post_id,
            post_url,
            image_failed=(image_failed if success else False)
        )
        
        if item_id:
            from database import ContentQueue
            with db.get_session() as session:
                db_item = session.query(ContentQueue).filter_by(id=item_id).first()
                if db_item:
                    db_item.status = 'posted' if success else 'failed'
                    if success and post_url:
                        db_item.post_url = post_url
                    session.commit()
        
        if success:
            # Deduct 1 credit from user
            from database import User
            with db.get_session() as session:
                user = session.query(User).filter_by(id=user_id).first()
                if user:
                    user.credits = max(0, (user.credits or 0) - 1)
                    session.commit()
                    logger.info(f"Deducted 1 credit from User {user.email}. Remaining: {user.credits}")
            
            file_size = len(image_data.getvalue())/1024 if image_data else 0
            send_telegram_notification(site_config,
                f"✅ <b>Artikel Berhasil Dipublish!</b>\n\n"
                f"🌐 <b>Website:</b> {site_config['site_name']}\n"
                f"📝 <b>Judul:</b> {article.get('title', '')}\n"
                f"📂 <b>Kategori:</b> {category['name']}\n"
                f"📊 <b>Panjang:</b> {len(article.get('content', '').split())} kata\n"
                f"🎨 <b>Featured Image:</b> WebP ({file_size:.1f} KB)\n"
                f"🔗 <b>URL:</b> {post_url}\n\n"
                f"🎉 Status: Published")
            
            post_to_telegram_channel(site_config, article, post_url, image_data)
            post_to_facebook_page(site_config, article, post_url, image_data)
            post_to_twitter(site_config, article, post_url, image_data)
            post_to_threads(site_config, article, post_url, image_data)
            
            logger.info(f"Article published successfully: {article.get('title', '')}")
        else:
            send_telegram_notification(site_config,
                f"❌ <b>Posting Gagal!</b>\n\n"
                f"🌐 <b>Website:</b> {site_config['site_name']}\n"
                f"📝 <b>Judul:</b> {article.get('title', '')}\n"
                f"📂 <b>Kategori:</b> {category['name']}\n"
                f"⚠️ <b>Error:</b> {str(result)[:200]}")
            logger.error(f"Article publish failed: {result}")
            
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error in generate_and_post for site {site_id}: {error_msg}", exc_info=True)
        
        # Determine category values for logging even if it failed early
        log_category_id = category['id'] if 'category' in locals() and category else None
        log_category_name = category['name'] if 'category' in locals() and category else "Unknown Category"
        log_title = custom_topic if 'custom_topic' in locals() and custom_topic else "Unknown Title"
        
        # Add to history so user sees the failure
        try:
            db.add_log(
                user_id=user_id,
                site_id=site_id,
                category_id=log_category_id,
                category_name=log_category_name,
                title=f"ERROR: {log_title}"[:500],
                success=False,
                result=f"Sistem Berhenti Tiba-tiba: {error_msg}"[:500],
                post_id=None,
                post_url=None
            )
        except Exception as log_e:
            logger.error(f"Failed to save error log: {log_e}")
        
        if item_id:
            try:
                from database import ContentQueue
                with db.get_session() as session:
                    db_item = session.query(ContentQueue).filter_by(id=item_id).first()
                    if db_item:
                        db_item.status = 'failed'
                        session.commit()
            except:
                pass
        try:
            send_telegram_notification(site_config if 'site_config' in locals() else config,
                f"❌ <b>Error Generate & Post</b>\n\n"
                f"⚠️ {str(e)[:200]}")
        except:
            pass


def deep_research_job(user_id, force=True, site_id=None, category=None):
    """Deep research job to find trending topics"""
    config = load_config(user_id)
    
    if not site_id:
        logger.error("No site_id provided for deep_research_job")
        return
        
    with db.get_session() as session:
        from database import WordPressSite
        site = session.query(WordPressSite).filter_by(id=site_id, user_id=user_id).first()
        if not site:
            logger.error(f"Site {site_id} not found")
            return
            
        selected_categories = site.selected_categories or []
        if category:
            selected_categories = [cat for cat in selected_categories if cat['name'] == category]
            
        if not selected_categories:
            logger.info(f"No categories to research for site {site.site_name}")
            return
            
        site_name = site.site_name
        telegram_enabled = site.telegram_enabled
        telegram_bot_token = site.telegram_bot_token
        telegram_chat_id = site.telegram_chat_id
        language = site.language or 'id'
        
    site_config = {
        'telegram_enabled': telegram_enabled,
        'telegram_bot_token': telegram_bot_token,
        'telegram_chat_id': telegram_chat_id,
        'site_name': site_name
    }
    
    try:
        logger.info(f"Starting auto-research job for site {site_name} (language={language})")
        
        # Import SEO research module
        from seo_research import SEOResearch
        seo = SEOResearch()
        
        for category in selected_categories:
            category_name = category['name']
            logger.info(f"Researching category: {category_name} on {site_name}")
            
            # Get trending data
            trending_data = trending.get_trending_topics(category_name, limit=15, language=language)
            
            # Get suggestions
            suggestions = trending.suggest_article_topics(category_name, count=10, language=language)
            
            # Get SEO research data
            try:
                seo_data = seo.research_category(category_name, language=language)
                keywords = seo_data.get('suggestions', [])
                questions = seo_data.get('questions', [])
                competitor_outlines = seo_data.get('competitor_outlines', [])
                youtube_insights = seo_data.get('youtube_insights', [])
                social_insights = seo_data.get('social_insights', [])
                trend_score = seo_data.get('trend_score', 50)
                
                logger.info(f"SEO research: {len(keywords)} keywords, {len(questions)} questions, trend score: {trend_score}")
            except Exception as e:
                logger.error(f"SEO research error: {e}")
                keywords = []
                questions = []
                competitor_outlines = []
                youtube_insights = []
                social_insights = []
                trend_score = 50
            
            # Save to database with SEO data
            db.save_research_data(
                user_id=user_id,
                site_id=site_id,
                category=category_name,
                trending=trending_data.get('trending_now', []) if trending_data else [],
                rising=trending_data.get('related_rising', []) if trending_data else [],
                top=trending_data.get('related_top', []) if trending_data else [],
                suggestions=suggestions,
                keywords=keywords,
                questions=questions,
                long_tail=[],
                competitor_outlines=competitor_outlines,
                youtube_insights=youtube_insights,
                social_insights=social_insights,
                trend_score=trend_score
            )
            
            logger.info(f"Research completed for {category_name}: {len(suggestions)} topics found")
        
        # Send notification
        category_str = f"category '{category}'" if category else f"{len(selected_categories)} categories"
        send_telegram_notification(site_config,
            f"🔍 <b>Research Completed</b>\n\n"
            f"🌐 <b>Website:</b> {site_name}\n"
            f"✅ Researched {category_str}\n"
            f"📊 Trending topics saved for tomorrow's articles")
        
    except Exception as e:
        logger.error(f"Auto research error: {e}")
        send_telegram_notification(site_config,
            f"❌ <b>Research Failed</b>\n\n"
            f"🌐 <b>Website:</b> {site_name}\n"
            f"Error: {str(e)}")


def shutdown():
    """Graceful shutdown"""
    logger.info("Shutting down gracefully...")
    try:
        db.close()
        logger.info("Shutdown complete")
    except Exception as e:
        logger.error(f"Error during shutdown: {e}")


# Register shutdown handlers
atexit.register(shutdown)
signal.signal(signal.SIGTERM, lambda s, f: shutdown())
signal.signal(signal.SIGINT, lambda s, f: shutdown())


# Static frontend serving
@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve_frontend(path):
    if path != "" and os.path.exists(os.path.join('frontend/dist', path)):
        return send_from_directory('frontend/dist', path)
    else:
        return send_from_directory('frontend/dist', 'index.html')


if __name__ == '__main__':
    # Production mode
    app.run(debug=False, host='0.0.0.0', port=5005)
