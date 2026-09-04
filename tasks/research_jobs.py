import re

try:
    from rq.timeouts import BaseTimeoutException
except ImportError:  # pragma: no cover - older/newer RQ layouts
    class BaseTimeoutException(Exception):
        pass

from core_extensions import db, trending, logger, send_telegram_notification

MIN_RESEARCH_QUALITY_SCORE = 35

# Search Console evidence is capped so a site with lots of impressions cannot pass
# on that alone, but it is weighted enough to keep a category viable when Google
# Trends and DuckDuckGo block the server IP.
GSC_MAX_BONUS = 20


def _load_search_console_queries(user_id, site_id):
    """Queries this site already receives impressions for. Empty when GSC is unused."""
    try:
        from services.content_planner import load_search_metrics
        with db.get_session() as session:
            current_rows, _ = load_search_metrics(session, user_id, site_id)
        return [
            {'query': row['query'], 'impressions': row['impressions'], 'position': row['position']}
            for row in current_rows if row.get('query')
        ]
    except Exception as e:
        logger.warning(f"Could not load Search Console evidence for site {site_id}: {e}")
        return []


def _search_console_evidence(gsc_queries, category_name):
    """Queries whose wording overlaps the category, so the match is explainable."""
    stopwords = {'and', 'the', 'for', 'with', 'your', 'dan', 'untuk', 'yang', 'dengan'}

    def tokens(text):
        words = re.findall(r'\w+', (text or '').lower())
        # Crude singular form so "beginner" matches "beginners" and "saving"
        # matches "savings"; without it obvious matches were missed.
        return {
            re.sub(r's$', '', w)
            for w in words if len(w) > 3 and w not in stopwords
        }

    wanted = tokens(category_name)
    if not wanted:
        return []

    matches = []
    for item in gsc_queries:
        if tokens(item['query']) & wanted:
            matches.append(item)
    matches.sort(key=lambda i: i.get('impressions') or 0, reverse=True)
    return matches

def deep_research_job(user_id, force=True, site_id=None, category=None):
    """Deep research job to find trending topics"""
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
        
        # Loaded once for the whole job rather than per category.
        gsc_queries = _load_search_console_queries(user_id, site_id)
        if gsc_queries:
            logger.info(f"Search Console evidence available: {len(gsc_queries)} queries for site {site_id}")
        else:
            logger.info(
                f"No Search Console evidence for site {site_id}. Connecting Search Console "
                "would keep categories viable when Trends/DuckDuckGo block this server."
            )

        successful_categories = 0
        failed_categories = 0
        
        for cat in selected_categories:
            category_name = cat['name']
            logger.info(f"Researching category: {category_name} on {site_name}")
            
            try:
                # Get trending data
                trending_data = trending.get_trending_topics(category_name, limit=15, language=language)
                
                # Derive suggestions from the same snapshot. This avoids a second
                # Google Trends request and inconsistent results/rate limiting.
                suggestions = trending.build_topic_suggestions(
                    category_name, trending_data, count=10
                )
                
                # Get SEO research data
                try:
                    seo_data = seo.research_category(category_name, language=language)
                    # Fallback-generated keywords/questions are invented; store only
                    # observed evidence so the article generator never sees them.
                    keywords = seo_data.get('evidence_suggestions', seo_data.get('suggestions', []))
                    questions = seo_data.get('evidence_questions', seo_data.get('questions', []))
                    competitor_outlines = seo_data.get('competitor_outlines', [])
                    youtube_insights = seo_data.get('youtube_insights', [])
                    social_insights = seo_data.get('social_insights', [])
                    trend_score = seo_data.get('trend_score', 0)
                    long_tail = seo_data.get('long_tail_keywords', [])
                    semantic_context = seo_data.get('semantic_context', '')
                    news_insights = seo_data.get('news_insights', [])
                    source_metadata = seo_data.get('source_metadata', {})
                    source_metadata['trend_analysis'] = seo_data.get('trend_analysis', {})
                    quality = seo_data.get('quality', {})

                    related_count = sum(len((trending_data or {}).get(key, [])) for key in (
                        'trending_now', 'related_rising', 'related_top'
                    ))
                    source_metadata['google_related_queries'] = {
                        'status': 'real' if related_count else 'unavailable',
                        'count': related_count,
                        'checked_at': (trending_data or {}).get('timestamp'),
                    }
                    # Search Console is first-party evidence: real queries that really
                    # reached this site. It does not depend on scraping Google Trends
                    # or DuckDuckGo, both of which block server IPs, so it keeps a
                    # category viable when the scraped providers are unavailable.
                    gsc_matches = _search_console_evidence(gsc_queries, category_name)
                    source_metadata['search_console'] = {
                        'status': 'real' if gsc_matches else 'unavailable',
                        'count': len(gsc_matches),
                        'queries': gsc_matches[:10],
                    }

                    # Related queries are direct category evidence and add a small,
                    # bounded bonus to the research evidence score.
                    quality_score = min(100, int(quality.get('score', 0))
                                        + min(10, related_count)
                                        + min(GSC_MAX_BONUS, len(gsc_matches) * 2))
                    real_provider_count = (int(quality.get('real_provider_count', 0))
                                           + (1 if related_count else 0)
                                           + (1 if gsc_matches else 0))
                    if quality_score >= 75 and real_provider_count >= 5:
                        confidence_level = 'high'
                    elif quality_score >= 50 and real_provider_count >= 3:
                        confidence_level = 'medium'
                    elif quality_score >= MIN_RESEARCH_QUALITY_SCORE and real_provider_count >= 2:
                        confidence_level = 'low'
                    else:
                        confidence_level = 'insufficient'

                    if confidence_level == 'insufficient':
                        raise RuntimeError(
                            f'Insufficient research evidence (quality={quality_score}, '
                            f'real_providers={real_provider_count})'
                        )
                    
                    logger.info(f"SEO research: {len(keywords)} keywords, {len(questions)} questions, trend score: {trend_score}")
                except Exception as e:
                    logger.error(f"SEO research error for {category_name}: {e}")
                    keywords = []
                    questions = []
                    competitor_outlines = []
                    youtube_insights = []
                    social_insights = []
                    trend_score = 0
                    long_tail = []
                    semantic_context = ''
                    news_insights = []
                    source_metadata = {}
                    quality_score = 0
                    confidence_level = 'insufficient'
                    raise
                
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
                    long_tail=long_tail,
                    competitor_outlines=competitor_outlines,
                    youtube_insights=youtube_insights,
                    social_insights=social_insights,
                    trend_score=trend_score,
                    semantic_context=semantic_context,
                    news_insights=news_insights,
                    source_metadata=source_metadata,
                    quality_score=quality_score,
                    confidence_level=confidence_level,
                    is_fallback=any(
                        meta.get('status') == 'fallback'
                        for meta in source_metadata.values()
                        if isinstance(meta, dict)
                    ),
                )
                
                logger.info(f"Research completed for {category_name}: {len(suggestions)} topics found")
                successful_categories += 1
                
            except BaseTimeoutException:
                # RQ's death penalty raises inside the job and is an Exception
                # subclass, so the per-category handler below used to swallow it and
                # keep looping past the deadline. Let it propagate: the outer handler
                # refunds every category that was not completed.
                logger.error(
                    f"Research job hit its time limit while processing '{category_name}'. "
                    f"Completed {successful_categories} categories."
                )
                raise
            except Exception as cat_error:
                logger.error(f"Failed to research category {category_name}: {cat_error}")
                failed_categories += 1
        
        # Process refunds if manual and there were failures
        if force and failed_categories > 0:
            db.refund_user_credits(user_id, failed_categories)
            logger.info(f"Refunded {failed_categories} credits to user {user_id} due to research failures.")
        
        # Expose a machine-readable outcome to the job status endpoint.
        result = {
            'successful_categories': successful_categories,
            'failed_categories': failed_categories,
            'refunded_credits': failed_categories if force else 0,
        }

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
        return result
                
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
        
        from services.wp_publisher import WordPressPublisher
        bot = WordPressPublisher(
            site_config['wordpress_url'],
            site_config['wordpress_username'],
            site_config['wordpress_password'],
            site_name=site_config.get('site_name')
        )
        
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


