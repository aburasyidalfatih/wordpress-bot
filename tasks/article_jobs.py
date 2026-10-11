from datetime import datetime, timedelta

import requests

from services.article_generator import ArticleGenerator
from services.quality_gate import check_article, strip_invalid_internal_links
from services.wp_publisher import WordPressPublisher, is_unconfirmed_post_result
from models import ResearchData, PostLog, ContentQueue, WordPressSite, User
from config import DEFAULT_GEMINI_MODEL, DEFAULT_GEMINI_IMAGE_MODEL
from core_extensions import (
    db, logger, load_config, send_telegram_notification, post_to_telegram_channel,
    post_to_facebook_page, post_to_twitter, post_to_threads, post_to_pinterest
)

def _merge_topic_research(seo_data, topic, category_name, language='id'):
    """Run topic-level research and merge it ahead of the category-level evidence.

    Returns seo_data unchanged on failure; this is an enrichment step and must not
    be able to fail an article.
    """
    try:
        from seo_research import SEOResearch
        topic_data = SEOResearch().research_topic(topic, category_name, language=language)
    except Exception as e:
        logger.warning(f"Topic-level research failed for '{topic}': {e}")
        return seo_data

    merged = dict(seo_data or {})

    def combine(key, limit):
        # Topic-specific evidence first, category evidence as backfill.
        values = list(topic_data.get(key) or []) + list(merged.get(key) or [])
        seen, output = set(), []
        for value in values:
            marker = value.get('url') if isinstance(value, dict) and value.get('url') else str(value)
            marker = marker.lower()
            if marker in seen:
                continue
            seen.add(marker)
            output.append(value)
            if len(output) >= limit:
                break
        return output

    merged['keywords'] = combine('keywords', 12)
    merged['questions'] = combine('questions', 8)
    merged['competitor_outlines'] = combine('competitor_outlines', 4)
    merged['social_insights'] = combine('social_insights', 6)
    merged['long_tail'] = combine('long_tail_keywords', 12)
    logger.info(
        f"Merged topic research for '{topic}': "
        f"{len(merged['keywords'])} keywords, {len(merged['competitor_outlines'])} competitors"
    )
    return merged


def _attach_search_evidence(seo_data, user_id, site_id, category_name, topic=None, language='id'):
    """Add Search Console queries, content gaps and intent to the research payload.

    Returns seo_data unchanged on any failure: this is additive intelligence and
    must never block article generation.
    """
    try:
        from services.search_console import build_search_opportunities
        from services.content_planner import (
            load_search_metrics, topic_candidates_from_opportunities,
            keyword_demand_map, annotate_keywords_with_demand, find_content_gaps,
            classify_intent, intent_guidance,
        )

        with db.get_session() as session:
            current_rows, previous_rows = load_search_metrics(session, user_id, site_id)
            published_titles = [
                row[0] for row in session.query(PostLog.title).filter(
                    PostLog.user_id == user_id,
                    PostLog.site_id == site_id,
                    PostLog.success.is_(True)
                ).order_by(PostLog.created_at.desc()).limit(200).all()
                if row[0]
            ]

        data = dict(seo_data or {})
        if current_rows:
            opportunities = build_search_opportunities(current_rows, previous_rows, limit=20)
            data['search_queries'] = topic_candidates_from_opportunities(opportunities, limit=6)
            data['keywords'] = annotate_keywords_with_demand(
                data.get('keywords'), keyword_demand_map(current_rows)
            )
        data['content_gaps'] = find_content_gaps(data.get('competitor_outlines'), published_titles, limit=5)
        # Intent belongs to the article topic, not the category. A category name
        # is usually one or two words and was classified 'navigational', whose
        # guidance asked for brevity against the 2000+ word target. Without a
        # topic the article is a broad category piece, i.e. informational.
        data['intent'] = classify_intent(topic) if topic else 'informational'
        data['intent_guidance'] = intent_guidance(data['intent'], language)
        return data
    except Exception as e:
        logger.warning(f"Could not attach search evidence for site {site_id}: {e}")
        return seo_data


# RQ statuses in which a job may still run or is running.
LIVE_JOB_STATUSES = {'queued', 'started', 'scheduled', 'deferred', 'created'}


def _current_job():
    try:
        from rq import get_current_job
        return get_current_job()
    except Exception:
        return None


def _rq_job_is_alive(job_id, connection):
    """True while job_id can still run or is running. Unknown counts as alive,
    so a Redis hiccup makes a duplicate back off instead of double-processing."""
    if not job_id:
        return False
    try:
        from rq.job import Job
        from rq.exceptions import NoSuchJobError
        try:
            job = Job.fetch(job_id, connection=connection)
        except NoSuchJobError:
            return False
        status = job.get_status(refresh=True)
        return str(getattr(status, 'value', status) or '') in LIVE_JOB_STATUSES
    except Exception as e:
        logger.warning(f"Could not check RQ job {job_id}: {e}; assuming it is still alive.")
        return True


def _refund_in_session(session, user_id, amount=1):
    """Refund inside the caller's transaction, so it commits atomically with the
    queue item update that records the reservation as settled."""
    from sqlalchemy import text
    session.execute(
        text("UPDATE users SET credits = COALESCE(credits, 0) + :amount WHERE id = :user_id"),
        {'user_id': user_id, 'amount': amount}
    )


def _claim_queue_item(user_id, item_id, job_id, credit_pre_reserved, connection):
    """Claim a queue item for this job under a row lock.

    Returns (outcome, info). outcome is 'claimed', 'missing', 'done' (already
    posted/failed) or 'busy' (another live job owns it). On 'claimed', info has
    the item fields the job needs and whether a credit is held for it.
    """
    with db.get_session() as session:
        item = session.query(ContentQueue).filter(
            ContentQueue.id == item_id,
            ContentQueue.user_id == user_id
        ).with_for_update().first()
        if not item:
            return 'missing', None
        if item.status not in ('pending', 'posting'):
            return 'done', item.status
        if item.job_id and item.job_id != job_id and _rq_job_is_alive(item.job_id, connection):
            return 'busy', item.job_id

        same_job = item.job_id == job_id
        if item.credit_held and not same_job:
            # The previous owner died without settling its reservation and the
            # dispatcher sweep has not reached it yet. This attempt is taking the
            # row over, so settle (refund) the dead attempt's credit here.
            logger.warning(
                f"Queue item {item_id}: previous job {item.job_id} died holding a credit; refunding it."
            )
            _refund_in_session(session, user_id, 1)
            item.credit_held = False

        item.job_id = job_id
        item.status = 'posting'
        # Measured from job start (not dispatch) by the stuck-item sweep.
        item.posting_started_at = datetime.now()
        # A re-run of the same job keeps the reservation it already holds.
        item.credit_held = bool(credit_pre_reserved) or bool(same_job and item.credit_held)
        return 'claimed', {
            'site_id': item.site_id,
            'title': item.title,
            'category': item.category,
            'credit_held': bool(item.credit_held),
        }


def _reserve_item_credit(user_id, item_id, job_id):
    """Reserve 1 credit for a claimed item, recorded on the row in one transaction.

    Returns 'reserved', 'insufficient', or 'lost' (the item is no longer ours).
    """
    from sqlalchemy import text
    with db.get_session() as session:
        item = session.query(ContentQueue).filter(
            ContentQueue.id == item_id,
            ContentQueue.user_id == user_id
        ).with_for_update().first()
        if not item or item.job_id != job_id or item.status != 'posting':
            return 'lost'
        result = session.execute(
            text(
                "UPDATE users SET credits = COALESCE(credits, 0) - 1 "
                "WHERE id = :user_id AND COALESCE(credits, 0) >= 1"
            ),
            {'user_id': user_id}
        )
        if result.rowcount != 1:
            return 'insufficient'
        item.credit_held = True
        return 'reserved'


def _settle_queue_item(user_id, item_id, job_id, status=None, refund=False, post_url=None):
    """Settle this job's reservation on a queue item, atomically with its status.

    refund=True gives the held credit back, refund=False consumes it; either way
    credit_held is cleared under the row lock, so the dispatcher's stuck-item
    sweep cannot refund it again. Does nothing if the sweep or another job has
    taken the item over (they settle the reservation themselves). Returns True
    when a credit was refunded.
    """
    with db.get_session() as session:
        item = session.query(ContentQueue).filter(
            ContentQueue.id == item_id,
            ContentQueue.user_id == user_id
        ).with_for_update().first()
        if item is None:
            # Deleted while this job worked; nobody else can settle it now.
            if refund:
                _refund_in_session(session, user_id, 1)
            return refund
        if item.job_id != job_id:
            logger.warning(
                f"Queue item {item_id} is now owned by {item.job_id!r}, not this job "
                f"({job_id!r}); leaving its status and credit alone."
            )
            return False
        refunded = False
        if refund and item.credit_held:
            _refund_in_session(session, user_id, 1)
            refunded = True
        item.credit_held = False
        if status:
            item.status = status
            if status != 'posting':
                item.posting_started_at = None
                item.job_id = None
            if post_url:
                item.post_url = post_url
        return refunded


def _next_rotated_category(user_id, site_id):
    """Pick the next selected category and rotate it to the back, under a row lock.

    Reading the list from an earlier snapshot and rotating it later let two
    concurrent jobs both pick the same first category, and the second rotation
    then dropped a category from the list.
    """
    with db.get_session() as session:
        site = session.query(WordPressSite).filter_by(
            id=site_id, user_id=user_id
        ).with_for_update().first()
        categories = list(site.selected_categories or []) if site else []
        if not categories:
            return None, 0
        category = categories[0]
        site.selected_categories = categories[1:] + [category]
        return dict(category), len(categories)


def regenerate_image_job(user_id, log_id):
    from models import PostLog, WordPressSite
    from services.article_generator import ArticleGenerator
    from services.wp_publisher import WordPressPublisher
    try:
        config = load_config(user_id)
        generator = ArticleGenerator(
            config['gemini_api_key'], 
            config.get('gemini_model', DEFAULT_GEMINI_MODEL),
            config.get('gemini_image_model', DEFAULT_GEMINI_IMAGE_MODEL)
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
                # Make HTTP POST to attach image to post (via the publisher so the
                # site URL and any redirect are SSRF-checked)
                headers = publisher._get_auth()
                headers['Content-Type'] = 'application/json'
                response = publisher._request(
                    'POST',
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
            config.get('gemini_model', DEFAULT_GEMINI_MODEL),
            config.get('gemini_image_model', DEFAULT_GEMINI_IMAGE_MODEL)
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
            
        article = generator.generate_checked_article(
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
        
        allowed_link_urls = article.get('allowed_link_urls')
        ok, gate_errors, gate_warnings = check_article(
            article,
            focus_keyword=article.get('focus_keyword'),
            allowed_link_urls=allowed_link_urls
        )
        for warning in gate_warnings:
            logger.warning(f"Quality gate warning (regenerate log {log_id}): {warning}")
        if not ok:
            raise Exception("Quality gate rejected the regenerated article: " + "; ".join(gate_errors))

        if allowed_link_urls:
            article['content'] = strip_invalid_internal_links(article['content'], allowed_link_urls)

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
def generate_and_post(user_id, item_id=None, site_id=None, credit_pre_reserved=False, manual=False):
    """Generate an article and publish it to WordPress.

    item_id: a ContentQueue item (the web app flips it to 'posting' and reserves
    the credit before enqueueing; the scheduler flips it and lets the job
    reserve). manual=True is a user-triggered category post: it skips the
    auto-post switch but still needs selected categories.

    Credit accounting: the 1-credit reservation (pre-reserved by the caller or
    taken here) is refunded exactly once on any failure and consumed exactly
    once on success. For queue items the reservation is tracked on the row
    (credit_held) and settled under a row lock, so the dispatcher's stuck-item
    sweep and this job can never both refund it.
    """
    current_job = _current_job()
    job_id = current_job.id if current_job else None
    connection = getattr(current_job, 'connection', None)
    if connection is None:
        import core_extensions
        connection = getattr(core_extensions, 'redis_conn', None)

    credit_reserved = bool(credit_pre_reserved)
    credit_consumed = False
    item_claimed = False
    item_settled = False
    site_config = None
    category = None
    custom_topic = None
    article = None

    def release_credit(status=None):
        """Refund an unconsumed reservation (at most once) and settle the item."""
        nonlocal credit_reserved, item_settled
        owes_refund = credit_reserved and not credit_consumed
        try:
            if item_claimed and not item_settled:
                _settle_queue_item(user_id, item_id, job_id, status=status, refund=owes_refund)
                item_settled = True
            elif owes_refund and not item_claimed:
                db.refund_user_credits(user_id, 1)
            if owes_refund:
                logger.info(f"Refunded reserved credit: user_id={user_id}, site_id={site_id}, item_id={item_id}")
            credit_reserved = False
        except Exception as refund_error:
            logger.error(f"Failed to refund reserved credit for user {user_id}: {refund_error}")

    def abort(message, status='failed', level='error'):
        getattr(logger, level)(message)
        release_credit(status)

    # Claim the queue item before anything else so a duplicate job backs off
    # without generating (and without consuming credit).
    item_info = None
    if item_id:
        try:
            outcome, item_info = _claim_queue_item(user_id, item_id, job_id, credit_pre_reserved, connection)
        except Exception as e:
            logger.error(f"Could not claim queue item {item_id}: {e}", exc_info=True)
            release_credit()
            return
        if outcome != 'claimed':
            if outcome == 'busy':
                logger.warning(f"Queue item {item_id} is already being processed by live job {item_info}; exiting.")
            elif outcome == 'done':
                logger.info(f"Queue item {item_id} is already '{item_info}'; nothing to do.")
            else:
                logger.error(f"Queue item {item_id} not found or invalid.")
            # This job's own pre-reserved credit was never attached to the item.
            release_credit()
            return
        item_claimed = True
        credit_reserved = item_info['credit_held']
        site_id = item_info['site_id'] or site_id

    try:
        # Everything that can fail lives inside this try: load_config and the
        # site's encrypted fields (decrypt can raise ValueError) used to run
        # before it, so a failure there leaked the reserved credit and left the
        # queue item stuck in 'posting'.
        config = load_config(user_id)

        abort_reason = None
        with db.get_session() as session:
            user = session.query(User).filter_by(id=user_id).first()
            site = None
            if not user:
                abort_reason = f"User {user_id} not found. Aborting generation."
            elif not site_id:
                abort_reason = "No site_id provided for generate_and_post"
            else:
                if (user.credits or 0) <= 0 and not credit_reserved:
                    logger.info(f"User {user.email} credits look low ({user.credits}), will confirm with atomic reserve.")
                site = session.query(WordPressSite).filter_by(id=site_id, user_id=user_id).first()
                if not site:
                    abort_reason = f"Site {site_id} not found"

            if site is not None:
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

        if abort_reason:
            abort(abort_reason)
            return

        if not item_id:
            # Queue items carry their own topic. Category posts need selected
            # categories; only scheduled ones also need the auto-post switch.
            if not site_config['selected_categories']:
                abort(f"No categories selected for site {site_id}", level='info')
                return
            if not manual and not site_config['auto_post']:
                abort(f"Auto post disabled for site {site_id}", level='info')
                return

        logger.info(f"Starting generate and post job for site {site_id}")
        generator = ArticleGenerator(
            config['gemini_api_key'],
            config.get('gemini_model', DEFAULT_GEMINI_MODEL),
            config.get('gemini_image_model', DEFAULT_GEMINI_IMAGE_MODEL)
        )
        publisher = WordPressPublisher(
            site_config['wordpress_url'],
            site_config['wordpress_username'],
            site_config['wordpress_password'],
            site_name=site_config.get('site_name')
        )

        try:
            recent_posts_for_links = publisher.get_recent_posts(limit=30)
            logger.info(f"Fetched {len(recent_posts_for_links)} recent posts for internal linking.")
        except Exception as e:
            logger.error(f"Failed to fetch recent posts for linking: {e}")
            recent_posts_for_links = []

        if item_id:
            custom_topic = item_info['title']
            category_name = item_info['category']
            category_id = None
            for cat in site_config.get('categories') or []:
                if cat.get('name') == category_name:
                    category_id = cat.get('id')
                    break
            if not category_id:
                category_id = 1
            category = {'name': category_name, 'id': category_id}

        if not credit_reserved:
            if item_claimed:
                outcome = _reserve_item_credit(user_id, item_id, job_id)
                if outcome == 'lost':
                    # Taken over by the sweep or another job; nothing reserved.
                    logger.warning(f"Queue item {item_id} is no longer owned by this job; exiting.")
                    item_settled = True
                    return
                if outcome == 'insufficient':
                    abort(f"User {user_id} has insufficient credits when reserving post job.",
                          status='pending', level='warning')
                    return
                credit_reserved = True
            else:
                credit_reserved = db.reserve_user_credits(user_id, 1)
                if not credit_reserved:
                    logger.warning(f"User {user_id} has insufficient credits when reserving post job.")
                    return

        if not item_id:
            # Rotate after a credit reservation succeeds so no-credit jobs do not
            # advance the schedule. Selection and rotation share one row lock.
            category, category_count = _next_rotated_category(user_id, site_id)
            if not category:
                abort(f"No categories selected for site {site_id}", level='info')
                return
            logger.info(f"Selected category: {category['name']} (position 1 of {category_count}); rotation complete.")

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
                        ResearchData.user_id == user_id,
                        ResearchData.site_id == site_id,
                        ResearchData.category == category['name'],
                        ResearchData.confidence_level.in_(['high', 'medium', 'low']),
                        ResearchData.researched_at >= datetime.now() - timedelta(days=7),
                    ).order_by(ResearchData.created_at.desc()).first()
                    
                    if research:
                        seo_data = {
                            # hasattr is always true for a mapped column, so it never
                            # guarded anything: a NULL column produced None, and the
                            # len() in the log line below then raised inside the
                            # session, rolling it back and discarding the research.
                            'keywords': research.keywords or [],
                            'questions': research.questions or [],
                            'long_tail': research.long_tail_keywords or [],
                            'competitor_outlines': research.competitor_outlines or [],
                            'social_insights': research.social_insights or [],
                            'youtube_insights': research.youtube_insights or [],
                            'semantic_context': research.semantic_context or '',
                            'news_insights': research.news_insights or []
                        }
                        logger.info(f"Using SEO data: {len(seo_data.get('keywords', []))} keywords, {len(seo_data.get('questions', []))} questions, {len(seo_data.get('competitor_outlines', []))} competitors, {len(seo_data.get('social_insights', []))} social, {len(seo_data.get('youtube_insights', []))} youtube")
            except Exception as e:
                logger.error(f"Error getting SEO data: {e}")

        # Second research stage. Category-level evidence is broad; once the actual
        # topic is known, research that topic directly so the article is grounded in
        # evidence about what it is really about.
        if custom_topic:
            seo_data = _merge_topic_research(seo_data, custom_topic, category['name'],
                                             site_config.get('language', 'id'))

        # Layer first-party Search Console evidence on top of the researched data.
        # These are queries this exact site already ranks for, so they are the most
        # reliable signal available about what the audience actually searches.
        seo_data = _attach_search_evidence(seo_data, user_id, site_id, category['name'],
                                           topic=custom_topic,
                                           language=site_config.get('language') or 'id')


        custom_article_prompt = site_config.get('article_prompt') or None
        custom_image_prompt = site_config.get('image_prompt') or None
        
        # Get category description from site categories list
        category_desc = ""
        for cat in site_config.get('categories', []):
            if cat.get('name') == category['name']:
                category_desc = cat.get('description', '')
                break
                
        article = generator.generate_checked_article(
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
            article = generator.generate_checked_article(
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
        
        # Quality gate. Blocks publishing of truncated, too-short, template-leaking or
        # fabricated-credential output instead of pushing it live and burning a credit.
        allowed_link_urls = article.get('allowed_link_urls')
        ok, gate_errors, gate_warnings = check_article(
            article,
            focus_keyword=article.get('focus_keyword'),
            allowed_link_urls=allowed_link_urls
        )
        for warning in gate_warnings:
            logger.warning(f"Quality gate warning (site {site_id}): {warning}")
        if not ok:
            raise Exception("Quality gate rejected the article: " + "; ".join(gate_errors))

        # Drop any internal link the model invented, keeping the anchor text.
        if allowed_link_urls:
            article['content'] = strip_invalid_internal_links(article['content'], allowed_link_urls)


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
        # TIMEOUT-style results mean the request reached WordPress but the outcome
        # is unknown, so the post may exist: keep the credit (no refund) and mark
        # the item failed rather than pending, so it is not re-posted automatically.
        unconfirmed = (not success) and is_unconfirmed_post_result(result)
        if success:
            credit_consumed = True
            if isinstance(result, dict):
                post_id = result.get('id')
                post_url = result.get('link')
            if image_failed:
                result_msg = "Article published successfully, but Featured Image failed to generate or upload."
            else:
                result_msg = "Article and Featured Image published successfully."
        else:
            result_msg = str(result)
            if unconfirmed:
                credit_consumed = True
                logger.info(f"Not refunding credit due to TIMEOUT (post might exist): user_id={user_id}, site_id={site_id}")

        # Settle the queue item and credit right after publishing, before any
        # further step that could raise and send this job into the failure path.
        if success or unconfirmed:
            if item_claimed and not item_settled:
                _settle_queue_item(user_id, item_id, job_id,
                                   status='posted' if success else 'failed',
                                   refund=False, post_url=post_url)
                item_settled = True
            credit_reserved = False
        else:
            release_credit('failed')

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
        # Refunds an unconsumed reservation once and marks the item failed. A
        # no-op when the outcome was already settled (e.g. the post went live
        # and a later notification step raised).
        release_credit('failed')

        # Determine category values for logging even if it failed early
        log_category_id = category['id'] if category else None
        log_category_name = category['name'] if category else "Unknown Category"
        log_title = (
            getattr(e, 'article_title', None)
            or (article.get('title') if article else None)
            or custom_topic
            or f"Artikel kategori {log_category_name}"
        )

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

        try:
            send_telegram_notification(site_config or {},
                f"❌ <b>Error Generate & Post</b>\n\n"
                f"⚠️ {str(e)[:200]}")
        except Exception as e:
            logger.error(f"Failed to send Telegram error notification: {e}")

