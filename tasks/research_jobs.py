import re

try:
    from rq.timeouts import BaseTimeoutException
except ImportError:  # pragma: no cover - older/newer RQ layouts
    class BaseTimeoutException(Exception):
        pass

from core_extensions import db, trending, logger, send_telegram_notification

MIN_RESEARCH_QUALITY_SCORE = 35

# Search Console is the ninth provider in the quality model; evaluate_quality
# covers the other eight and totals 85, leaving this 15.
#
# It is worth a full weight because it is first-party: queries that genuinely
# reached this site, from an authenticated API rather than scraping. A couple of
# matching queries is strong validation, so the scale reaches full weight quickly
# instead of requiring the volume an established site would have.
GSC_MAX_WEIGHT = 15
GSC_POINTS_PER_MATCH = 5


def _aggregate_queries(rows):
    """Collapse Search Console rows to one entry per distinct query.

    Metrics are stored per (query, page), so a query ranking with three pages
    appeared three times and counted as three matches. Impressions and clicks are
    summed across pages; the best (lowest non-zero) position is kept.
    """
    merged = {}
    for row in rows or []:
        query = ' '.join(str(row.get('query') or '').split())
        if not query:
            continue
        key = query.lower()
        impressions = float(row.get('impressions') or 0)
        clicks = float(row.get('clicks') or 0)
        position = row.get('position')
        position = float(position) if position else None
        entry = merged.get(key)
        if entry is None:
            merged[key] = {'query': query, 'impressions': impressions,
                           'clicks': clicks, 'position': position}
            continue
        entry['impressions'] += impressions
        entry['clicks'] += clicks
        if position is not None and (entry['position'] is None or position < entry['position']):
            entry['position'] = position
    return list(merged.values())


def _load_search_console_queries(user_id, site_id):
    """Distinct queries this site already receives impressions for. Empty when GSC is unused."""
    try:
        from services.content_planner import load_search_metrics
        with db.get_session() as session:
            current_rows, _ = load_search_metrics(session, user_id, site_id)
        return _aggregate_queries(current_rows)
    except Exception as e:
        logger.warning(f"Could not load Search Console evidence for site {site_id}: {e}")
        return []


def _search_console_evidence(gsc_queries, category_name):
    """Distinct queries whose wording overlaps the category, so the match is explainable."""
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
    # Aggregating again is idempotent and protects against callers passing raw
    # per-page rows, which would count one query several times.
    for item in _aggregate_queries(gsc_queries):
        if tokens(item['query']) & wanted:
            matches.append(item)
    matches.sort(key=lambda i: i.get('impressions') or 0, reverse=True)
    return matches


# Google Trends' weight inside SEOResearch.evaluate_quality, and the points it
# already awarded per status. trending.get_trending_topics() is pytrends too, so
# its related queries are the same provider, not an extra one.
GOOGLE_TRENDS_WEIGHT = 10
_TRENDS_POINTS_BY_STATUS = {'real': 10, 'partial': 5, 'fallback': 1.5}


def _google_trends_top_up(source_metadata, related_count):
    """Extra (points, providers) for related queries, counting Google Trends once.

    If SEOResearch already counted Google Trends as real, related queries add
    nothing. If its Trends call failed but the related-queries call succeeded,
    the provider is credited once, up to its normal weight.
    """
    if not related_count:
        return 0, 0
    status = ((source_metadata or {}).get('google_trends') or {}).get('status', 'unavailable')
    if status == 'real':
        return 0, 0
    already = _TRENDS_POINTS_BY_STATUS.get(status, 0)
    return int(round(GOOGLE_TRENDS_WEIGHT - already)), 1


def _dedupe_categories(categories):
    """Selected categories by name, first occurrence wins."""
    seen, unique = set(), []
    for cat in categories or []:
        name = (cat.get('name') if isinstance(cat, dict) else None) or ''
        key = name.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(cat)
    return unique

def deep_research_job(user_id, force=True, site_id=None, category=None, charged_credits=None):
    """Deep research job to find trending topics.

    charged_credits is what the route reserved for a manual (force=True) run.
    Every refund is bounded by it: in total the job refunds exactly
    charged_credits minus the categories it researched successfully, never more,
    however many failure paths run. Scheduled runs (charged_credits None,
    force=False) were never charged and never refund.
    """
    state = {'charged': None, 'refunded': 0, 'successful': 0}

    def set_charged(value):
        state['charged'] = max(0, int(value or 0)) if force else 0

    if force and charged_credits is not None:
        set_charged(charged_credits)

    def settle_refund():
        """Refund whatever is still owed. Idempotent; returns the amount refunded now."""
        charged = state['charged'] or 0
        owed = max(0, charged - state['successful']) - state['refunded']
        owed = min(owed, charged - state['refunded'])
        if owed <= 0:
            return 0
        try:
            db.refund_user_credits(user_id, owed)
            state['refunded'] += owed
            logger.info(f"Refunded {owed} research credit(s) to user {user_id} (charged {charged}).")
            return owed
        except Exception as refund_err:
            logger.error(f"Failed to refund {owed} research credit(s) to user {user_id}: {refund_err}")
            return 0

    if not site_id:
        logger.error("No site_id provided for deep_research_job")
        settle_refund()
        return

    with db.get_session() as session:
        from models import WordPressSite
        site = session.query(WordPressSite).filter_by(id=site_id, user_id=user_id).first()
        if not site:
            logger.error(f"Site {site_id} not found")
            settle_refund()
            return

        raw_categories = site.selected_categories or []
        if force and state['charged'] is None:
            # Legacy enqueue without charged_credits: the route charged one credit
            # per selected category (or one for a single category).
            set_charged(1 if category else len(raw_categories))

        selected_categories = _dedupe_categories(raw_categories)
        if category:
            selected_categories = [cat for cat in selected_categories if cat['name'] == category]

        if force:
            # Never research more categories than were paid for.
            selected_categories = selected_categories[:state['charged'] or 0]

        if not selected_categories:
            logger.info(f"No categories to research for site {site.site_name}")
            settle_refund()
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

                    # Related queries come from pytrends, the same provider that
                    # evaluate_quality already scores as google_trends. They used to
                    # add up to 10 points and a whole extra provider on top of it,
                    # double-counting Google Trends. Now Trends counts once: only
                    # when SEOResearch's own Trends call did not already succeed.
                    trends_points, trends_providers = _google_trends_top_up(
                        source_metadata, related_count
                    )
                    gsc_score = min(GSC_MAX_WEIGHT, len(gsc_matches) * GSC_POINTS_PER_MATCH)
                    quality_score = min(100, int(quality.get('score', 0))
                                        + trends_points
                                        + gsc_score)
                    real_provider_count = (int(quality.get('real_provider_count', 0))
                                           + trends_providers
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
                state['successful'] = successful_categories

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

        # Refund every charged credit that did not produce research: failed
        # categories, and any surplus charged for duplicate category entries.
        settle_refund()

        # Expose a machine-readable outcome to the job status endpoint.
        result = {
            'successful_categories': successful_categories,
            'failed_categories': failed_categories,
            'refunded_credits': state['refunded'],
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
        # Refund whatever was charged and not yet researched or refunded. Bounded
        # by charged_credits, so a failure after the normal refund (for example in
        # the notification) cannot refund a second time.
        settle_refund()

        try:
            send_telegram_notification(site_config,
                f"❌ <b>Research System Error</b>\n\n"
                f"🌐 <b>Website:</b> {site_name}\n"
                f"Error: {str(e)[:150]}")
        except Exception as notify_err:
            logger.error(f"Failed to send research error notification: {notify_err}")


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
            # context=edit returns title.raw/content.raw, the stored source. The
            # rendered HTML must never be written back: it has shortcodes expanded
            # and filters applied, so saving it permanently corrupts the post.
            success, response, total_pages = bot.get_posts(page=page, per_page=100, context='edit')
            if not success:
                logger.error(f"Failed to fetch posts: {response}")
                break

            for post in response:
                title = (post.get('title') or {}).get('raw')
                content = (post.get('content') or {}).get('raw')
                if title is None or content is None:
                    logger.warning(
                        f"Skipping post ID {post.get('id')}: WordPress did not return raw "
                        "title/content (needs an account with edit permission)."
                    )
                    continue

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


