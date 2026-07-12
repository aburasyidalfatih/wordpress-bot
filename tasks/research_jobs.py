import os, json, time, random
from datetime import datetime
from services.article_generator import ArticleGenerator
from services.wp_publisher import WordPressPublisher
from models import ResearchData, PostLog, ContentQueue, WordPressSite, User
from ml_optimizer import ContentOptimizer
from trending_research import TrendingResearch
from core_extensions import db, q, redis_conn, optimizer, trending, logger, load_config, save_config, send_telegram_notification, post_to_telegram_channel, post_to_facebook_page, post_to_twitter, post_to_threads, post_to_pinterest
from config import Config

def deep_research_job(user_id, force=True, site_id=None, category=None):
    """Deep research job to find trending topics"""
    config = load_config(user_id)
    
    if not site_id:
        logger.error("No site_id provided for deep_research_job")
        return
        
    with db.get_session() as session:
        from models import WordPressSite
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
        
        successful_categories = 0
        failed_categories = 0
        
        for cat in selected_categories:
            category_name = cat['name']
            logger.info(f"Researching category: {category_name} on {site_name}")
            
            try:
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
                    logger.error(f"SEO research error for {category_name}: {e}")
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
                successful_categories += 1
                
            except Exception as cat_error:
                logger.error(f"Failed to research category {category_name}: {cat_error}")
                failed_categories += 1
        
        # Process refunds if manual and there were failures
        if force and failed_categories > 0:
            db.refund_user_credits(user_id, failed_categories)
            logger.info(f"Refunded {failed_categories} credits to user {user_id} due to research failures.")
        
        # Send notification
        if successful_categories > 0:
            category_str = f"category '{category}'" if category else f"{successful_categories} categories"
            msg = (f"🔍 <b>Research Completed</b>\n\n"
                   f"🌐 <b>Website:</b> {site_name}\n"
                   f"✅ Researched {category_str}\n"
                   f"📊 Trending topics saved for tomorrow's articles")
            if failed_categories > 0:
                msg += f"\n⚠️ Failed to research {failed_categories} categories (credits refunded if manual)."
            
            send_telegram_notification(site_config, msg)
        else:
            send_telegram_notification(site_config,
                f"❌ <b>Research Failed</b>\n\n"
                f"🌐 <b>Website:</b> {site_name}\n"
                f"⚠️ Failed to research any categories. Credits refunded if manual.")
                
    except Exception as e:
        logger.error(f"Auto research error: {e}", exc_info=True)
        # If the entire job fails drastically before looping completes
        if force:
            # We don't exactly know how many were left, so refund the ones we haven't succeeded on yet
            total_charged = len(selected_categories)
            refund_amount = total_charged - successful_categories if 'successful_categories' in locals() else total_charged
            if refund_amount > 0:
                db.refund_user_credits(user_id, refund_amount)
                logger.info(f"Refunded {refund_amount} credits to user {user_id} due to total job failure.")
                
        send_telegram_notification(site_config,
            f"❌ <b>Research System Error</b>\n\n"
            f"🌐 <b>Website:</b> {site_name}\n"
            f"Error: {str(e)[:150]}")


def bulk_update_year_task(user_id, site_id, from_year, to_year):
    """Background task to bulk update year in WordPress posts"""
    logger.info(f"Starting bulk update year from {from_year} to {to_year} for site_id {site_id}")
    try:
        from models import WordPressSite
        with db.get_session() as session:
            site = session.query(WordPressSite).filter_by(id=site_id, user_id=user_id).first()
            if not site:
                logger.error(f"Site {site_id} not found")
                return
            
            site_config = {
                'wordpress_url': site.wordpress_url,
                'wordpress_username': site.wordpress_username,
                'wordpress_password': site.wordpress_password,
                'site_name': site.site_name
            }
        
        from bot import WordPressPublisher
        bot = WordPressPublisher(site_config['wordpress_url'], site_config['wordpress_username'], site_config['wordpress_password'])
        
        # Get all posts
        page = 1
        total_updated = 0
        while True:
            success, response, total_pages = bot.get_posts(page=page, per_page=100)
            if not success:
                logger.error(f"Failed to fetch posts: {response}")
                break
                
            for post in response:
                title = post.get('title', {}).get('raw', post.get('title', {}).get('rendered', ''))
                content = post.get('content', {}).get('raw', post.get('content', {}).get('rendered', ''))
                
                if str(from_year) in title:
                    new_title = title.replace(str(from_year), str(to_year))
                    new_content = content.replace(str(from_year), str(to_year))
                    
                    update_data = {
                        'title': new_title,
                        'content': new_content
                    }
                    
                    up_success, up_res = bot.update_post(post['id'], update_data)
                    if up_success:
                        total_updated += 1
                        logger.info(f"Updated post ID {post['id']}: {new_title}")
                    else:
                        logger.error(f"Failed to update post ID {post['id']}: {up_res}")
            
            if page >= total_pages:
                break
            page += 1
            
        logger.info(f"Finished bulk update. Total updated: {total_updated}")
        try:
            send_telegram_notification(site_config,
                f"✅ <b>Bulk Update Selesai</b>\n\n"
                f"🌐 <b>Website:</b> {site_config['site_name']}\n"
                f"🔄 <b>Tahun:</b> {from_year} ➡️ {to_year}\n"
                f"📊 <b>Total Update:</b> {total_updated} Artikel")
        except Exception as e:
            logger.error(f"Failed to send Telegram notification: {e}")
            
    except Exception as e:
        logger.error(f"Error in bulk_update_year_task: {e}", exc_info=True)


