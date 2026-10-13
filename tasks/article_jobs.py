import re
from datetime import datetime, timedelta
from difflib import SequenceMatcher

from rq import get_current_job
from rq.exceptions import NoSuchJobError
from rq.job import Job

import core_extensions
from config import DEFAULT_GEMINI_MODEL, DEFAULT_GEMINI_IMAGE_MODEL
from core_extensions import (
    db, logger, load_config, send_telegram_notification, post_to_telegram_channel,
    post_to_facebook_page, post_to_twitter, post_to_threads, post_to_pinterest
)
from database import add_credits, debit_credits
from models import ResearchData, PostLog, ContentQueue, WordPressSite, User
from services.article_generator import ArticleGenerator
from services.content_planner import (
    load_search_metrics, topic_candidates_from_opportunities,
    keyword_demand_map, annotate_keywords_with_demand, find_content_gaps,
    classify_intent, intent_guidance,
)
from services.quality_gate import check_article, strip_invalid_internal_links
from services.search_console import build_search_opportunities
from services.wp_publisher import WordPressPublisher, is_unconfirmed_post_result

# RQ statuses in which a job may still run or is running.
LIVE_JOB_STATUSES = {'queued', 'started', 'scheduled', 'deferred', 'created'}

# WordPressSite columns copied into a plain dict, so the job can keep using them
# after the session closes.
SITE_CONFIG_FIELDS = (
    'wordpress_url', 'wordpress_username', 'wordpress_password',
    'selected_categories', 'categories',
    'telegram_enabled', 'telegram_bot_token', 'telegram_chat_id',
    'telegram_channel_id', 'telegram_post_to_channel',
    'facebook_enabled', 'facebook_page_id', 'facebook_access_token',
    'pinterest_enabled', 'pinterest_board_id', 'pinterest_access_token',
    'twitter_enabled', 'twitter_api_key', 'twitter_api_secret',
    'twitter_access_token', 'twitter_access_secret',
    'threads_enabled', 'threads_user_id', 'threads_access_token',
    'article_prompt', 'image_prompt', 'language', 'auto_post', 'site_name',
)

# PostLog results shown to the user in the post history.
RESULT_PUBLISHED = "Artikel dan featured image berhasil dipublikasikan."
RESULT_PUBLISHED_NO_IMAGE = "Artikel berhasil dipublikasikan, tetapi featured image gagal dibuat atau diunggah."
RESULT_REGENERATED = "Artikel berhasil diregenerasi."


# ---------------------------------------------------------------------------
# Research enrichment
# ---------------------------------------------------------------------------

def _merge_topic_research(seo_data, topic, category_name, language='id'):
    """Run topic-level research and merge it ahead of the category-level evidence.

    Returns seo_data unchanged on failure; this is an enrichment step and must not
    be able to fail an article.
    """
    try:
        # Local import: seo_research pulls in pytrends/pandas, which are heavy
        # and do not import in every environment.
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


def _load_category_research(user_id, site_id, category_name):
    """Recent (7 days) category research usable as evidence, or None."""
    try:
        with db.get_session() as session:
            research = session.query(ResearchData).filter(
                ResearchData.user_id == user_id,
                ResearchData.site_id == site_id,
                ResearchData.category == category_name,
                ResearchData.confidence_level.in_(['high', 'medium', 'low']),
                ResearchData.researched_at >= datetime.now() - timedelta(days=7),
            ).order_by(ResearchData.created_at.desc()).first()
            if not research:
                return None
            seo_data = {
                # `or` defaults: a NULL column must not become None, or the len()
                # in the log line below raised inside the session, rolling it back
                # and discarding the research.
                'keywords': research.keywords or [],
                'questions': research.questions or [],
                'long_tail': research.long_tail_keywords or [],
                'competitor_outlines': research.competitor_outlines or [],
                'social_insights': research.social_insights or [],
                'youtube_insights': research.youtube_insights or [],
                'semantic_context': research.semantic_context or '',
                'news_insights': research.news_insights or []
            }
            logger.info(
                f"Using SEO data: {len(seo_data['keywords'])} keywords, {len(seo_data['questions'])} questions, "
                f"{len(seo_data['competitor_outlines'])} competitors, {len(seo_data['social_insights'])} social, "
                f"{len(seo_data['youtube_insights'])} youtube"
            )
            return seo_data
    except Exception as e:
        logger.error(f"Error getting SEO data: {e}")
        return None


# ---------------------------------------------------------------------------
# Queue item ownership and credit settlement
# ---------------------------------------------------------------------------

def _current_job():
    try:
        return get_current_job()
    except Exception as e:
        logger.debug(f"Could not resolve the current RQ job: {e}")
        return None


def _rq_job_is_alive(job_id, connection):
    """True while job_id can still run or is running. Unknown counts as alive,
    so a Redis hiccup makes a duplicate back off instead of double-processing."""
    if not job_id:
        return False
    try:
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
    add_credits(session, user_id, amount)


def _locked_queue_item(session, user_id, item_id):
    return session.query(ContentQueue).filter(
        ContentQueue.id == item_id,
        ContentQueue.user_id == user_id
    ).with_for_update().first()


def _claim_queue_item(user_id, item_id, job_id, credit_pre_reserved, connection):
    """Claim a queue item for this job under a row lock.

    Returns (outcome, info). outcome is 'claimed', 'missing', 'done' (already
    posted/failed) or 'busy' (another live job owns it). On 'claimed', info has
    the item fields the job needs and whether a credit is held for it.
    """
    with db.get_session() as session:
        item = _locked_queue_item(session, user_id, item_id)
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
    with db.get_session() as session:
        item = _locked_queue_item(session, user_id, item_id)
        if not item or item.job_id != job_id or item.status != 'posting':
            return 'lost'
        if not debit_credits(session, user_id, 1):
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
        item = _locked_queue_item(session, user_id, item_id)
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


# ---------------------------------------------------------------------------
# Article pipeline helpers
# ---------------------------------------------------------------------------

def _build_generator(config):
    return ArticleGenerator(
        config['gemini_api_key'],
        config.get('gemini_model', DEFAULT_GEMINI_MODEL),
        config.get('gemini_image_model', DEFAULT_GEMINI_IMAGE_MODEL)
    )


def _recent_posts_for_links(publisher):
    try:
        posts = publisher.get_recent_posts(limit=30)
        logger.info(f"Fetched {len(posts)} recent posts for internal linking.")
        return posts
    except Exception as e:
        logger.error(f"Failed to fetch recent posts for linking: {e}")
        return []


def _find_site_category(site_config, category_name):
    for cat in site_config.get('categories') or []:
        if cat.get('name') == category_name:
            return cat
    return None


def _category_for_item(site_config, category_name):
    """Category dict for a queue item; WordPress category 1 when the name is unknown."""
    cat = _find_site_category(site_config, category_name)
    return {'name': category_name, 'id': (cat.get('id') if cat else None) or 1}


def _category_description(site_config, category_name):
    cat = _find_site_category(site_config, category_name)
    return cat.get('description', '') if cat else ""


def _normalize_title(text):
    text = re.sub(r'\d+', '', text.lower())
    text = re.sub(r'[^\w\s]', '', text)
    return ' '.join(text.split())


def _find_similar_title(new_title, existing_titles):
    """Check whether a title duplicates or is too similar to an existing one.

    Returns (is_similar, matching existing title, reason).
    """
    new_normalized = _normalize_title(new_title)
    # The first ~6 words usually carry the main topic.
    new_main = ' '.join(new_normalized.split()[:6])

    for existing in existing_titles:
        existing_normalized = _normalize_title(existing)
        existing_main = ' '.join(existing_normalized.split()[:6])

        if new_normalized == existing_normalized:
            return True, existing, "exact"

        # Character similarity above 60% is too similar.
        char_similarity = SequenceMatcher(None, new_normalized, existing_normalized).ratio()
        if char_similarity > 0.6:
            return True, existing, f"char {char_similarity:.0%}"

        # Main-topic similarity above 75% is the same topic.
        topic_similarity = SequenceMatcher(None, new_main, existing_main).ratio()
        if topic_similarity > 0.75:
            return True, existing, f"topic {topic_similarity:.0%}"

    return False, None, None


def _apply_quality_gate(article, warning_context, rejection_prefix):
    """Block truncated, too-short, template-leaking or fabricated-credential output.

    Raises with rejection_prefix plus the gate errors; otherwise drops any
    internal link the model invented, keeping the anchor text.
    """
    allowed_link_urls = article.get('allowed_link_urls')
    ok, gate_errors, gate_warnings = check_article(
        article,
        focus_keyword=article.get('focus_keyword'),
        allowed_link_urls=allowed_link_urls
    )
    for warning in gate_warnings:
        logger.warning(f"Quality gate warning ({warning_context}): {warning}")
    if not ok:
        raise Exception(rejection_prefix + "; ".join(gate_errors))
    if allowed_link_urls:
        article['content'] = strip_invalid_internal_links(article['content'], allowed_link_urls)


def _generate_featured_image(generator, publisher, category_name, article, custom_prompt, site_name):
    """Generate and upload the featured image. Returns (image_data, media_id, failed).

    The image is optional: any failure is logged and the post goes out without it.
    """
    image_data = None
    try:
        logger.info("Generating featured image...")
        image_data = generator.generate_image(
            category_name,
            article.get('title', ''),
            article.get('content', ''),
            custom_prompt=custom_prompt,
            site_name=site_name
        )
        if not image_data:
            return None, None, True
        logger.info("Uploading featured image...")
        featured_image_id = publisher.upload_image(image_data, article.get('title', ''))
        return image_data, featured_image_id, not featured_image_id
    except Exception as img_err:
        logger.error(f"Image generation or upload failed: {img_err}", exc_info=True)
        return image_data, None, True


def _share_published_post(site_config, article, post_url, image_data):
    post_to_telegram_channel(site_config, article, post_url, image_data)
    if site_config.get('facebook_enabled'):
        logger.info("Posting to Facebook Page...")
        post_to_facebook_page(site_config, article, post_url, image_data)

    if site_config.get('pinterest_enabled'):
        logger.info("Posting to Pinterest...")
        post_to_pinterest(site_config, article, post_url, image_data)

    post_to_twitter(site_config, article, post_url, image_data)
    post_to_threads(site_config, article, post_url, image_data)


def _start_message(site_config, category, custom_topic):
    return (
        f"🤖 <b>WordPress Auto Post Bot</b>\n\n"
        f"🌐 <b>Website:</b> {site_config['site_name']}\n"
        f"📝 Mulai generate artikel...\n"
        f"📂 Kategori: {category['name']}" + (f"\n🎯 Judul: {custom_topic}" if custom_topic else "")
    )


def _published_message(site_config, article, category, post_url, image_data):
    file_size = len(image_data.getvalue()) / 1024 if image_data else 0
    return (
        f"✅ <b>Artikel Berhasil Dipublish!</b>\n\n"
        f"🌐 <b>Website:</b> {site_config['site_name']}\n"
        f"📝 <b>Judul:</b> {article.get('title', '')}\n"
        f"📂 <b>Kategori:</b> {category['name']}\n"
        f"📊 <b>Panjang:</b> {len(article.get('content', '').split())} kata\n"
        f"🎨 <b>Featured Image:</b> WebP ({file_size:.1f} KB)\n"
        f"🔗 <b>URL:</b> {post_url}\n\n"
        f"🎉 Status: Terbit"
    )


def _publish_failed_message(site_config, article, category, result):
    return (
        f"❌ <b>Posting Gagal!</b>\n\n"
        f"🌐 <b>Website:</b> {site_config['site_name']}\n"
        f"📝 <b>Judul:</b> {article.get('title', '')}\n"
        f"📂 <b>Kategori:</b> {category['name']}\n"
        f"⚠️ <b>Error:</b> {str(result)[:200]}"
    )


# ---------------------------------------------------------------------------
# generate_and_post
# ---------------------------------------------------------------------------

class _ArticlePostJob:
    """State and steps of one generate_and_post run.

    Holds the queue-item claim and the 1-credit reservation so every exit path
    settles them exactly once, plus what the failure history needs (category,
    topic, article) as the pipeline progresses.
    """

    def __init__(self, user_id, item_id, site_id, credit_pre_reserved, manual):
        current_job = _current_job()
        self.job_id = current_job.id if current_job else None
        self.connection = getattr(current_job, 'connection', None)
        if self.connection is None:
            self.connection = getattr(core_extensions, 'redis_conn', None)

        self.user_id = user_id
        self.item_id = item_id
        self.site_id = site_id
        self.manual = manual
        self.credit_pre_reserved = bool(credit_pre_reserved)

        self.credit_reserved = bool(credit_pre_reserved)
        self.credit_consumed = False
        self.item_claimed = False
        self.item_settled = False
        self.item_info = None

        self.site_config = None
        self.category = None
        self.custom_topic = None
        self.article = None

    # -- credit / item settlement -------------------------------------------

    def release_credit(self, status=None):
        """Refund an unconsumed reservation (at most once) and settle the item."""
        owes_refund = self.credit_reserved and not self.credit_consumed
        try:
            if self.item_claimed and not self.item_settled:
                _settle_queue_item(self.user_id, self.item_id, self.job_id, status=status, refund=owes_refund)
                self.item_settled = True
            elif owes_refund and not self.item_claimed:
                db.refund_user_credits(self.user_id, 1)
            if owes_refund:
                logger.info(
                    f"Refunded reserved credit: user_id={self.user_id}, site_id={self.site_id}, item_id={self.item_id}"
                )
            self.credit_reserved = False
        except Exception as refund_error:
            logger.error(f"Failed to refund reserved credit for user {self.user_id}: {refund_error}")

    def abort(self, message, status='failed', level='error'):
        getattr(logger, level)(message)
        self.release_credit(status)

    def claim_item(self):
        """Claim the queue item before anything else, so a duplicate job backs off
        without generating (and without consuming credit). False means stop."""
        try:
            outcome, info = _claim_queue_item(
                self.user_id, self.item_id, self.job_id, self.credit_pre_reserved, self.connection
            )
        except Exception as e:
            logger.error(f"Could not claim queue item {self.item_id}: {e}", exc_info=True)
            self.release_credit()
            return False
        if outcome != 'claimed':
            if outcome == 'busy':
                logger.warning(f"Queue item {self.item_id} is already being processed by live job {info}; exiting.")
            elif outcome == 'done':
                logger.info(f"Queue item {self.item_id} is already '{info}'; nothing to do.")
            else:
                logger.error(f"Queue item {self.item_id} not found or invalid.")
            # This job's own pre-reserved credit was never attached to the item.
            self.release_credit()
            return False
        self.item_claimed = True
        self.item_info = info
        self.credit_reserved = info['credit_held']
        self.site_id = info['site_id'] or self.site_id
        return True

    def reserve_credit(self):
        """Take the 1-credit reservation unless already held. False means stop."""
        if self.credit_reserved:
            return True
        if self.item_claimed:
            outcome = _reserve_item_credit(self.user_id, self.item_id, self.job_id)
            if outcome == 'lost':
                # Taken over by the sweep or another job; nothing reserved.
                logger.warning(f"Queue item {self.item_id} is no longer owned by this job; exiting.")
                self.item_settled = True
                return False
            if outcome == 'insufficient':
                self.abort(f"User {self.user_id} has insufficient credits when reserving post job.",
                           status='pending', level='warning')
                return False
            self.credit_reserved = True
            return True
        self.credit_reserved = db.reserve_user_credits(self.user_id, 1)
        if not self.credit_reserved:
            logger.warning(f"User {self.user_id} has insufficient credits when reserving post job.")
        return self.credit_reserved

    # -- pipeline -----------------------------------------------------------

    def run(self):
        if self.item_id and not self.claim_item():
            return
        try:
            # Everything that can fail runs inside this try: load_config and the
            # site's encrypted fields (decrypt can raise ValueError) used to run
            # before it, so a failure there leaked the reserved credit and left the
            # queue item stuck in 'posting'.
            self._run_pipeline()
        except Exception as e:
            self._handle_failure(e)

    def _run_pipeline(self):
        config = load_config(self.user_id)
        if not self._load_site():
            return

        logger.info(f"Starting generate and post job for site {self.site_id}")
        site_config = self.site_config
        generator = _build_generator(config)
        publisher = WordPressPublisher(
            site_config['wordpress_url'],
            site_config['wordpress_username'],
            site_config['wordpress_password'],
            site_name=site_config.get('site_name')
        )
        recent_posts = _recent_posts_for_links(publisher)

        if self.item_id:
            self.custom_topic = self.item_info['title']
            self.category = _category_for_item(site_config, self.item_info['category'])
        if not self.reserve_credit():
            return
        if not self.item_id and not self._rotate_category():
            return

        send_telegram_notification(site_config, _start_message(site_config, self.category, self.custom_topic))
        existing_titles = db.get_existing_titles(self.user_id, self.site_id, self.category['name'], limit=50)
        seo_data = self._gather_seo_data()
        self._generate_article(generator, existing_titles, seo_data, recent_posts)
        _apply_quality_gate(self.article, f"site {self.site_id}", "Artikel ditolak quality gate: ")

        image_data, featured_image_id, image_failed = _generate_featured_image(
            generator, publisher, self.category['name'], self.article,
            site_config.get('image_prompt') or None, site_config.get('site_name')
        )
        self._publish(publisher, image_data, featured_image_id, image_failed)

    def _load_site(self):
        """Load the user and site; abort (refunding) when the job cannot run."""
        abort_reason = None
        with db.get_session() as session:
            user = session.query(User).filter_by(id=self.user_id).first()
            site = None
            if not user:
                abort_reason = f"User {self.user_id} not found. Aborting generation."
            elif not self.site_id:
                abort_reason = "No site_id provided for generate_and_post"
            else:
                if (user.credits or 0) <= 0 and not self.credit_reserved:
                    logger.info(
                        f"User {user.email} credits look low ({user.credits}), will confirm with atomic reserve."
                    )
                site = session.query(WordPressSite).filter_by(id=self.site_id, user_id=self.user_id).first()
                if not site:
                    abort_reason = f"Site {self.site_id} not found"
            if site is not None:
                self.site_config = {field: getattr(site, field) for field in SITE_CONFIG_FIELDS}

        if abort_reason:
            self.abort(abort_reason)
            return False

        if not self.item_id:
            # Queue items carry their own topic. Category posts need selected
            # categories; only scheduled ones also need the auto-post switch.
            if not self.site_config['selected_categories']:
                self.abort(f"No categories selected for site {self.site_id}", level='info')
                return False
            if not self.manual and not self.site_config['auto_post']:
                self.abort(f"Auto post disabled for site {self.site_id}", level='info')
                return False
        return True

    def _rotate_category(self):
        # Rotate after a credit reservation succeeds so no-credit jobs do not
        # advance the schedule. Selection and rotation share one row lock.
        self.category, category_count = _next_rotated_category(self.user_id, self.site_id)
        if not self.category:
            self.abort(f"No categories selected for site {self.site_id}", level='info')
            return False
        logger.info(
            f"Selected category: {self.category['name']} (position 1 of {category_count}); rotation complete."
        )
        return True

    def _gather_seo_data(self):
        category_name = self.category['name']
        seo_data = None
        if not self.item_id:
            # Scheduled/category posts take an unused research topic, if any.
            self.custom_topic = db.get_unused_research_topic(self.user_id, self.site_id, category_name)
            if self.custom_topic:
                logger.info(f"Using research topic: {self.custom_topic}")
            seo_data = _load_category_research(self.user_id, self.site_id, category_name)

        # Second research stage. Category-level evidence is broad; once the actual
        # topic is known, research that topic directly so the article is grounded in
        # evidence about what it is really about.
        if self.custom_topic:
            seo_data = _merge_topic_research(seo_data, self.custom_topic, category_name,
                                             self.site_config.get('language', 'id'))

        # Layer first-party Search Console evidence on top of the researched data.
        # These are queries this exact site already ranks for, so they are the most
        # reliable signal available about what the audience actually searches.
        return _attach_search_evidence(seo_data, self.user_id, self.site_id, category_name,
                                       topic=self.custom_topic,
                                       language=self.site_config.get('language') or 'id')

    def _generate_article(self, generator, existing_titles, seo_data, recent_posts):
        """Generate the article, once more with avoid_similar if the title is a near-duplicate."""
        site_config = self.site_config
        category_name = self.category['name']
        options = dict(
            custom_prompt=site_config.get('article_prompt') or None,
            site_name=site_config.get('site_name'),
            language=site_config.get('language', 'id'),
            category_desc=_category_description(site_config, category_name),
            internal_links_context=recent_posts
        )
        self.article = generator.generate_checked_article(
            category_name, existing_titles, self.custom_topic, seo_data, **options
        )

        is_dup, similar_to, reason = _find_similar_title(self.article.get('title', ''), existing_titles)
        if is_dup:
            logger.warning(
                f"Similar title detected ({reason}): '{self.article.get('title')}' ~ '{similar_to}'. Regenerating..."
            )
            self.article = generator.generate_checked_article(
                category_name, existing_titles, self.custom_topic, seo_data, avoid_similar=True, **options
            )

    def _publish(self, publisher, image_data, featured_image_id, image_failed):
        article, category = self.article, self.category
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
            self.credit_consumed = True
            if isinstance(result, dict):
                post_id = result.get('id')
                post_url = result.get('link')
            result_msg = RESULT_PUBLISHED_NO_IMAGE if image_failed else RESULT_PUBLISHED
        else:
            result_msg = str(result)
            if unconfirmed:
                self.credit_consumed = True
                logger.info(
                    f"Not refunding credit due to TIMEOUT (post might exist): "
                    f"user_id={self.user_id}, site_id={self.site_id}"
                )

        self._settle_after_publish(success, unconfirmed, post_url)

        db.add_log(
            self.user_id,
            self.site_id,
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
            logger.info(f"Consumed reserved credit for user_id={self.user_id}, site_id={self.site_id}")
            send_telegram_notification(
                self.site_config, _published_message(self.site_config, article, category, post_url, image_data)
            )
            _share_published_post(self.site_config, article, post_url, image_data)
            logger.info(f"Article published successfully: {article.get('title', '')}")
        else:
            send_telegram_notification(
                self.site_config, _publish_failed_message(self.site_config, article, category, result)
            )
            logger.error(f"Article publish failed: {result}")

    def _settle_after_publish(self, success, unconfirmed, post_url):
        """Settle the queue item and credit right after publishing, before any
        further step that could raise and send this job into the failure path."""
        if success or unconfirmed:
            if self.item_claimed and not self.item_settled:
                _settle_queue_item(self.user_id, self.item_id, self.job_id,
                                   status='posted' if success else 'failed',
                                   refund=False, post_url=post_url)
                self.item_settled = True
            self.credit_reserved = False
        else:
            self.release_credit('failed')

    def _handle_failure(self, error):
        error_msg = str(error)
        logger.error(f"Error in generate_and_post for site {self.site_id}: {error_msg}", exc_info=True)
        # Refunds an unconsumed reservation once and marks the item failed. A
        # no-op when the outcome was already settled (e.g. the post went live
        # and a later notification step raised).
        self.release_credit('failed')

        # Category values for the history, even if the job failed early.
        log_category_id = self.category['id'] if self.category else None
        log_category_name = self.category['name'] if self.category else "Kategori tidak diketahui"
        log_title = (
            getattr(error, 'article_title', None)
            or (self.article.get('title') if self.article else None)
            or self.custom_topic
            or f"Artikel kategori {log_category_name}"
        )

        # Add to history so the user sees the failure.
        try:
            db.add_log(
                user_id=self.user_id,
                site_id=self.site_id,
                category_id=log_category_id,
                category_name=log_category_name,
                title=f"GAGAL: {log_title}"[:500],
                success=False,
                result=f"Sistem Berhenti Tiba-tiba: {error_msg}"[:500],
                post_id=None,
                post_url=None
            )
        except Exception as log_e:
            logger.error(f"Failed to save error log: {log_e}")

        try:
            send_telegram_notification(self.site_config or {},
                                       f"❌ <b>Gagal Generate & Post</b>\n\n"
                                       f"⚠️ {error_msg[:200]}")
        except Exception as notify_err:
            logger.error(f"Failed to send Telegram error notification: {notify_err}")


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
    _ArticlePostJob(user_id, item_id, site_id, credit_pre_reserved, manual).run()


# ---------------------------------------------------------------------------
# Regeneration jobs (the route reserves 1 credit before enqueueing)
# ---------------------------------------------------------------------------

def _load_regeneration_target(user_id, log_id):
    """Post log and site details for a regeneration job, or None (logged) when unusable."""
    with db.get_session() as session:
        log = session.query(PostLog).filter_by(id=log_id, user_id=user_id).first()
        if not log:
            logger.error(f"Post log not found for ID {log_id}")
            return None

        if log.site_id:
            site = session.query(WordPressSite).filter_by(id=log.site_id, user_id=user_id).first()
        else:
            # Older logs have no site_id: fall back to the user's first active site.
            site = session.query(WordPressSite).filter_by(user_id=user_id, is_active=True).first()
        if not site:
            logger.error(f"No active WordPress site found for user {user_id} and site {log.site_id}")
            return None

        target = {
            'title': log.title,
            'category_name': log.category_name,
            'post_id': log.post_id,
            'wordpress_url': site.wordpress_url,
            'wordpress_username': site.wordpress_username,
            'wordpress_password': site.wordpress_password,
            'site_name': site.site_name,
            'language': site.language,
            'article_prompt': site.article_prompt,
            'image_prompt': site.image_prompt,
        }

    if not target['post_id']:
        logger.error("No post ID found in post log")
        return None
    return target


def _target_publisher(target):
    return WordPressPublisher(target['wordpress_url'], target['wordpress_username'], target['wordpress_password'])


def _set_log_result(log_id, result, image_failed=None):
    with db.get_session() as session:
        log = session.query(PostLog).filter_by(id=log_id).first()
        if log:
            if image_failed is not None:
                log.image_failed = image_failed
            log.result = result


def _fail_regeneration(user_id, log_id, error, job_name, credit_context, result_prefix):
    """Refund the reserved credit and record the failure on the post log.

    Must be called from the job's except block (logs the active traceback).
    """
    logger.error(f"Error in {job_name}: {error}", exc_info=True)
    try:
        db.refund_user_credits(user_id, 1)
        logger.info(f"Refunded reserved credit for failed {credit_context}: user_id={user_id}, log_id={log_id}")
    except Exception as refund_err:
        logger.error(f"Failed to refund credit for {credit_context}: {refund_err}")
    try:
        _set_log_result(log_id, f"{result_prefix}: {str(error)}")
    except Exception as db_err:
        logger.error(f"Failed to save error status: {db_err}")


def _attach_featured_image(publisher, post_id, media_id):
    # Through the publisher, so the site URL and any redirect are SSRF-checked.
    headers = publisher._get_auth()
    headers['Content-Type'] = 'application/json'
    response = publisher._request(
        'POST',
        f"{publisher.api_url}/posts/{post_id}",
        headers=headers,
        json={'featured_media': media_id},
        timeout=30
    )
    if response.status_code != 200:
        raise Exception(f"Gagal memasang gambar ke postingan WordPress ({response.status_code}): {response.text}")
    logger.info(f"Successfully attached image {media_id} to post {post_id}")


def regenerate_image_job(user_id, log_id):
    try:
        generator = _build_generator(load_config(user_id))
        target = _load_regeneration_target(user_id, log_id)
        if target is None:
            db.refund_user_credits(user_id, 1)
            return
        publisher = _target_publisher(target)

        logger.info(f"Regenerating image for post {target['post_id']} - {target['title']}")
        image_data = generator.generate_image(
            target['category_name'],
            target['title'],
            "",
            custom_prompt=target['image_prompt'] or None,
            site_name=target['site_name']
        )
        if not image_data:
            raise Exception("Model gambar Gemini tidak menghasilkan data gambar (cek API key / model gambar).")

        logger.info("Image generated, uploading to WordPress...")
        featured_image_id = publisher.upload_image(image_data, target['title'])
        if not featured_image_id:
            raise Exception("Upload gambar ke WordPress gagal (cek kredensial atau ukuran media library).")

        _attach_featured_image(publisher, target['post_id'], featured_image_id)
        _set_log_result(log_id, RESULT_PUBLISHED, image_failed=False)
    except Exception as e:
        _fail_regeneration(user_id, log_id, e, 'regenerate_image_job', 'image regen', 'Regenerasi gambar gagal')


def regenerate_article_job(user_id, log_id):
    try:
        generator = _build_generator(load_config(user_id))
        target = _load_regeneration_target(user_id, log_id)
        if target is None:
            db.refund_user_credits(user_id, 1)
            return
        publisher = _target_publisher(target)
        post_id, title = target['post_id'], target['title']

        logger.info(f"Regenerating article for post {post_id} - {title}")
        article = generator.generate_checked_article(
            target['category_name'],
            [],
            title,
            None,
            avoid_similar=False,
            custom_prompt=target['article_prompt'],
            site_name=target['site_name'],
            language=target['language'],
            category_desc=None,
            internal_links_context=_recent_posts_for_links(publisher)
        )
        _apply_quality_gate(article, f"regenerate log {log_id}", "Artikel hasil regenerasi ditolak quality gate: ")

        success, result = publisher.update_post_content(
            post_id,
            article.get('title', title),
            article.get('content'),
            None,  # category_id: keep the current one
            None,  # featured_image_id: keep the current one
            article.get('meta_description'),
            article.get('excerpt'),
            article.get('focus_keyword'),
            key_takeaways=article.get('key_takeaways'),
            faqs=article.get('faqs')
        )
        if not success:
            raise Exception(f"Update postingan WordPress gagal: {result}")

        logger.info(f"Successfully regenerated article for post {post_id}")
        _set_log_result(log_id, RESULT_REGENERATED)
        logger.info(f"Consumed reserved credit for user_id={user_id}, log_id={log_id}")
    except Exception as e:
        _fail_regeneration(user_id, log_id, e, 'regenerate_article_job', 'article regen', 'Regenerasi artikel gagal')
