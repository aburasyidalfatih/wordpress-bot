import os, json, time, random
from datetime import datetime
from services.article_generator import ArticleGenerator
from services.wp_publisher import WordPressPublisher
from models import ResearchData, PostLog, ContentQueue, WordPressSite, User
from ml_optimizer import ContentOptimizer
from trending_research import TrendingResearch
from core_extensions import db, q, redis_conn, optimizer, trending, logger, load_config, save_config, send_telegram_notification, post_to_telegram_channel, post_to_facebook_page, post_to_twitter, post_to_threads, post_to_pinterest
from config import Config

def _set_queue_item_status(item_id, user_id, status, post_url=None):
    if not item_id:
        return

    from models import ContentQueue
    with db.get_session() as session:
        item = session.query(ContentQueue).filter_by(id=item_id, user_id=user_id).first()
        if item:
            item.status = status
            if post_url:
                item.post_url = post_url


def regenerate_image_job(user_id, log_id):
    from models import PostLog, WordPressSite
    from services.article_generator import ArticleGenerator
from services.wp_publisher import WordPressPublisher
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
                db.refund_user_credits(user_id, 1)
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
                db.refund_user_credits(user_id, 1)
                logger.error(f"No active WordPress site found for user {user_id} and site {site_id}")
                return
                
            wordpress_url = site.wordpress_url
            wordpress_username = site.wordpress_username
            wordpress_password = site.wordpress_password
            site_name = site.site_name
            site_image_prompt = site.image_prompt
            
        if not post_id:
            db.refund_user_credits(user_id, 1)
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
            db.refund_user_credits(user_id, 1)
            logger.info(f"Refunded reserved credit for failed image regen: user_id={user_id}, log_id={log_id}")
        except Exception as refund_err:
            logger.error(f"Failed to refund credit for image regen: {refund_err}")
        try:
            with db.get_session() as session:
                log = session.query(PostLog).filter_by(id=log_id).first()
                if log:
                    log.result = f"Image regeneration failed: {str(e)}"
        except Exception as db_err:
            logger.error(f"Failed to save error status: {db_err}")

def regenerate_article_job(user_id, log_id):
    from models import PostLog, WordPressSite
    from services.article_generator import ArticleGenerator
from services.wp_publisher import WordPressPublisher
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
                db.refund_user_credits(user_id, 1)
                logger.error(f"Post log not found for ID {log_id}")
                return
            
            title = log.title
            category_name = log.category_name
            post_id = log.post_id
            site_id = log.site_id
            keyword = title
            
            if not site_id:
                site = session.query(WordPressSite).filter_by(user_id=user_id, is_active=True).first()
            else:
                site = session.query(WordPressSite).filter_by(id=site_id, user_id=user_id).first()
                
            if not site:
                db.refund_user_credits(user_id, 1)
                logger.error(f"No active WordPress site found for user {user_id}")
                return
                
            wordpress_url = site.wordpress_url
            wordpress_username = site.wordpress_username
            wordpress_password = site.wordpress_password
            site_name = site.site_name
            language = site.language
            article_prompt = site.article_prompt
            
        if not post_id:
            db.refund_user_credits(user_id, 1)
            logger.error("No post ID found in post log")
            return
            
        publisher = WordPressPublisher(
            wordpress_url,
            wordpress_username,
            wordpress_password
        )
            
        logger.info(f"Regenerating article for post {post_id} - {title}")
        
        recent_posts_for_links = []
        try:
            recent_posts_for_links = publisher.get_recent_posts(limit=30)
        except Exception:
            pass
            
        article = generator.generate_article(
            category_name, 
            [], 
            keyword, 
            None,
            avoid_similar=False,
            custom_prompt=article_prompt,
            site_name=site_name,
            language=language,
            category_desc=None,
            internal_links_context=recent_posts_for_links
        )
        
        if not article.get('title') or not article.get('content') or len(article.get('content', '').split()) < 50:
            raise Exception("Generated article is empty or too short.")
            
        success, result = publisher.update_post_content(
            post_id,
            article.get('title', title),
            article.get('content'),
            None, # category_id (don't change)
            None, # featured_image_id
            article.get('meta_description'),
            article.get('excerpt'),
            article.get('focus_keyword'),
            key_takeaways=article.get('key_takeaways'),
            faqs=article.get('faqs')
        )
        
        if success:
            logger.info(f"Successfully regenerated article for post {post_id}")
            with db.get_session() as session:
                log = session.query(PostLog).filter_by(id=log_id).first()
                if log:
                    log.result = "Article regenerated successfully."
            # Also, we might want to consume the credit.
            logger.info(f"Consumed reserved credit for user_id={user_id}, log_id={log_id}")
        else:
            raise Exception(f"WordPress update failed: {result}")
            
    except Exception as e:
        logger.error(f"Error in regenerate_article_job: {e}", exc_info=True)
        try:
            db.refund_user_credits(user_id, 1)
            logger.info(f"Refunded reserved credit for failed article regen: user_id={user_id}, log_id={log_id}")
        except Exception as refund_err:
            logger.error(f"Failed to refund credit for article regen: {refund_err}")
        try:
            with db.get_session() as session:
                log = session.query(PostLog).filter_by(id=log_id).first()
                if log:
                    log.result = f"Article regeneration failed: {str(e)}"
        except Exception as db_err:
            logger.error(f"Failed to save error status: {db_err}")
def generate_and_post(user_id, item_id=None, site_id=None, credit_pre_reserved=False):
    config = load_config(user_id)
    from models import WordPressSite, User
    credit_reserved = credit_pre_reserved
    credit_consumed = False
    
    with db.get_session() as session:
        user = session.query(User).filter_by(id=user_id).first()
        if not user:
            if credit_reserved:
                db.refund_user_credits(user_id, 1)
            logger.error(f"User {user_id} not found. Aborting generation.")
            return
        if (user.credits or 0) <= 0:
            logger.info(f"User {user.email} credits look low ({user.credits}), will confirm with atomic reserve.")
            
        if item_id:
            from models import ContentQueue
            queue_item = session.query(ContentQueue).filter_by(id=item_id, user_id=user_id).first()
            if queue_item:
                site_id = queue_item.site_id
                
        if not site_id:
            if credit_reserved:
                db.refund_user_credits(user_id, 1)
            logger.error("No site_id provided for generate_and_post")
            return
            
        site = session.query(WordPressSite).filter_by(id=site_id, user_id=user_id).first()
        if not site:
            if credit_reserved:
                db.refund_user_credits(user_id, 1)
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
            'pinterest_enabled': site.pinterest_enabled,
            'pinterest_board_id': site.pinterest_board_id,
            'pinterest_access_token': site.pinterest_access_token,
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
        if credit_reserved:
            db.refund_user_credits(user_id, 1)
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
        
        try:
            recent_posts_for_links = publisher.get_recent_posts(limit=30)
            logger.info(f"Fetched {len(recent_posts_for_links)} recent posts for internal linking.")
        except Exception as e:
            logger.error(f"Failed to fetch recent posts for linking: {e}")
            recent_posts_for_links = []
        
        queue_item = None
        category = None
        custom_topic = None
        
        if item_id:
            from models import ContentQueue
            with db.get_session() as session:
                queue_item = session.query(ContentQueue).filter(
                    ContentQueue.id == item_id,
                    ContentQueue.user_id == user_id,
                    ContentQueue.status.in_(['pending', 'posting'])
                ).with_for_update().first()
                if queue_item:
                    # Update status to posting
                    queue_item.status = 'posting'
                    
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

        if not credit_reserved:
            credit_reserved = db.reserve_user_credits(user_id, 1)
            if not credit_reserved:
                logger.warning(f"User {user_id} has insufficient credits when reserving post job.")
                if item_id:
                    _set_queue_item_status(item_id, user_id, 'pending')
                return

        if not item_id:
            # Rotate after a credit reservation succeeds so no-credit jobs do not advance the schedule.
            with db.get_session() as session:
                site = session.query(WordPressSite).filter_by(id=site_id, user_id=user_id).with_for_update().first()
                if site and site.selected_categories:
                    site.selected_categories = site.selected_categories[1:] + [category]
            logger.info("Rotation complete.")
        
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
                            'long_tail': research.long_tail_keywords if hasattr(research, 'long_tail_keywords') else [],
                            'competitor_outlines': research.competitor_outlines if hasattr(research, 'competitor_outlines') else [],
                            'social_insights': research.social_insights if hasattr(research, 'social_insights') else [],
                            'youtube_insights': research.youtube_insights if hasattr(research, 'youtube_insights') else [],
                            'semantic_context': '',
                            'news_insights': []
                        }
                        logger.info(f"Using SEO data: {len(seo_data.get('keywords', []))} keywords, {len(seo_data.get('questions', []))} questions, {len(seo_data.get('competitor_outlines', []))} competitors, {len(seo_data.get('social_insights', []))} social, {len(seo_data.get('youtube_insights', []))} youtube")
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
            category_desc=category_desc,
            internal_links_context=recent_posts_for_links
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
                category_desc=category_desc,
                internal_links_context=recent_posts_for_links
            )
        
        # Validate generated article is not empty
        if not article.get('title') or not article.get('content') or len(article.get('content', '').split()) < 50:
            raise Exception(f"Generated article is empty or too short (title='{article.get('title', '')[:50]}', words={len(article.get('content', '').split())})")
        
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
            article.get('focus_keyword'),
            key_takeaways=article.get('key_takeaways'),
            faqs=article.get('faqs')
        )
        
        post_id = None
        post_url = None
        if success and isinstance(result, dict):
            credit_consumed = True
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
            from models import ContentQueue
            with db.get_session() as session:
                db_item = session.query(ContentQueue).filter_by(id=item_id).first()
                if db_item:
                    db_item.status = 'posted' if success else 'failed'
                    if success and post_url:
                        db_item.post_url = post_url
        
        if success:
            logger.info(f"Consumed reserved credit for user_id={user_id}, site_id={site_id}")

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
            if site_config.get('facebook_enabled'):
                logger.info("Posting to Facebook Page...")
                post_to_facebook_page(site_config, article, post_url, image_data)
            
            if site_config.get('pinterest_enabled'):
                logger.info("Posting to Pinterest...")
                post_to_pinterest(site_config, article, post_url, image_data)
            
            post_to_twitter(site_config, article, post_url, image_data)
            post_to_threads(site_config, article, post_url, image_data)
            
            logger.info(f"Article published successfully: {article.get('title', '')}")
        else:
            if credit_reserved and not credit_consumed:
                if isinstance(result, str) and "TIMEOUT" in result:
                    logger.info(f"Not refunding credit due to TIMEOUT (post might exist): user_id={user_id}, site_id={site_id}")
                    # We consider credit consumed to prevent abuse
                    credit_consumed = True
                else:
                    db.refund_user_credits(user_id, 1)
                    credit_reserved = False
                    logger.info(f"Refunded reserved credit for failed post: user_id={user_id}, site_id={site_id}")
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
        if credit_reserved and not credit_consumed:
            try:
                db.refund_user_credits(user_id, 1)
                logger.info(f"Refunded reserved credit after exception: user_id={user_id}, site_id={site_id}")
            except Exception as refund_error:
                logger.error(f"Failed to refund reserved credit for user {user_id}: {refund_error}")
        
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
                from models import ContentQueue
                with db.get_session() as session:
                    db_item = session.query(ContentQueue).filter_by(id=item_id).first()
                    if db_item:
                        db_item.status = 'failed'
            except Exception as e:
                logger.error(f"Failed to update queue item status: {e}")
        try:
            send_telegram_notification(site_config if 'site_config' in locals() else config,
                f"❌ <b>Error Generate & Post</b>\n\n"
                f"⚠️ {str(e)[:200]}")
        except Exception as e:
            logger.error(f"Failed to send Telegram error notification: {e}")


