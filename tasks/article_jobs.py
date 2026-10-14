import html
import re
from datetime import datetime

from rq import get_current_job
from rq.exceptions import NoSuchJobError
from rq.job import Job

import core_extensions
from core_extensions import (
    db, logger, load_config, send_telegram_notification, post_to_telegram_channel,
    post_to_facebook_page, post_to_twitter, post_to_threads, post_to_pinterest
)
from database import USABLE_CONFIDENCE_LEVELS, add_credits, debit_credits, research_fresh_cutoff
from models import ResearchData, PostLog, ContentQueue, WordPressSite, User
from services.ai_providers import AIProviderError
from services.article_generator import ArticleGenerator, ArticleQualityError
from services.article_review import (
    ArticleReviewRejected, JobTimeoutException, build_publisher_context, build_review_evidence, review_article,
)
from services.content_planner import (
    load_search_metrics, topic_candidates_from_opportunities,
    keyword_demand_map, annotate_keywords_with_demand, find_content_gaps,
    classify_intent, intent_guidance, filter_opportunities_for_topic,
)
from services.quality_gate import check_article, link_host, strip_invalid_internal_links
from services.search_console import build_search_opportunities
from services.topic_similarity import find_similar_published
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

    def combine(key, limit, category_key=None):
        # Topic-specific evidence first, category evidence as backfill.
        values = list(topic_data.get(key) or []) + list(merged.get(category_key or key) or [])
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
    # Category research stores these as 'long_tail' (see _load_category_research).
    merged['long_tail'] = combine('long_tail_keywords', 12, category_key='long_tail')
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
            # Search Console data is site-wide: only queries about this article's
            # category or topic may steer it.
            opportunities = filter_opportunities_for_topic(
                build_search_opportunities(current_rows, previous_rows, limit=100),
                category_name, topic,
            )
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


TREND_TOPIC_TYPES = ('rising', 'popular', 'trending')

# A research topic whose article failed for reasons unrelated to its content is
# handed back at most this many times before it is consumed.
MAX_TOPIC_RESTORES = 2

# Research topics tried per scheduled article before one that does not repeat a
# published article is found; after that the article falls back to the category.
MAX_TOPIC_CLAIMS = 3

# Published titles compared against new topics (PostLog history of the site).
PUBLISHED_TITLES_LIMIT = 200


class TopicTooSimilar(Exception):
    """The topic or title repeats an article the site already published (a content failure)."""

    def __init__(self, existing_title, article_title=None):
        self.existing_title = existing_title
        self.article_title = article_title
        super().__init__(f"Topik terlalu mirip dengan artikel yang sudah terbit: '{existing_title}'")


# Failures shown in the history as a deliberate "not published", not a crash.
EDITORIAL_FAILURES = (ArticleReviewRejected, TopicTooSimilar)


def _is_content_failure(error):
    """True when an article failed because of what was generated, so retrying the
    same topic would fail the same way: quality gate and AI review rejections, a
    topic repeating a published article, and a provider refusing the topic."""
    if isinstance(error, (ArticleQualityError, QualityGateRejection) + EDITORIAL_FAILURES):
        return True
    return isinstance(error, AIProviderError) and 'menolak' in str(error).lower()


def _topic_is_trending(raw_topic):
    """True when a stored research suggestion came from Google Trends.

    New suggestions carry is_trending; older ones only their type. Plain-string
    topics carry no evidence either way and stay neutral (False).
    """
    if not isinstance(raw_topic, dict):
        return False
    if 'is_trending' in raw_topic:
        return bool(raw_topic.get('is_trending'))
    return raw_topic.get('type') in TREND_TOPIC_TYPES


def _load_category_research(user_id, site_id, category_name):
    """Fresh, confident category research usable as evidence, or None.

    Same freshness and confidence rules as the title gate (database.is_research_fresh).
    """
    try:
        with db.get_session() as session:
            research = session.query(ResearchData).filter(
                ResearchData.user_id == user_id,
                ResearchData.site_id == site_id,
                ResearchData.category == category_name,
                ResearchData.confidence_level.in_(USABLE_CONFIDENCE_LEVELS),
                ResearchData.researched_at >= research_fresh_cutoff(),
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
                'news_insights': research.news_insights or [],
                # Where the evidence came from (e.g. which Wikipedia article the
                # background text is from), so the prompt can list it as a source.
                'source_metadata': research.source_metadata if isinstance(research.source_metadata, dict) else {},
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
    return ArticleGenerator.from_config(config)


def _recent_posts_for_links(publisher):
    """Recent posts for internal linking: [] when the site has none, None when the
    fetch failed (then the article's links are left alone instead of every link
    being unwrapped against an empty allow-list)."""
    try:
        posts = publisher.get_recent_posts(limit=30)
        posts = list(posts or [])
        logger.info(f"Fetched {len(posts)} recent posts for internal linking.")
        return posts
    except Exception as e:
        logger.error(f"Failed to fetch recent posts for linking: {e}")
        return None


_PROMPT_URL_RE = re.compile(r'https?://[^\s"\'<>()\[\]{}]+', re.IGNORECASE)


def _link_allowances(article_prompt, wordpress_url):
    """(extra allowed URLs, allowed hosts) for link stripping.

    URLs the user wrote into their custom article prompt were asked for on
    purpose, and links to the site's own domain are never foreign.
    """
    urls = [url.rstrip('.,;:!?') for url in _PROMPT_URL_RE.findall(article_prompt or '')]
    hosts = [wordpress_url] if wordpress_url else []
    return urls, hosts


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


def _published_titles(user_id, site_id, recent_posts, extra_titles=()):
    """Titles a new article must not cannibalize: the site's successful post
    history (newest PUBLISHED_TITLES_LIMIT), the recent WordPress posts fetched
    for internal linking (which include posts made outside AutoWP) and
    extra_titles. Never raises: an empty list only disables the check."""
    titles = list(extra_titles or [])
    try:
        titles += db.get_existing_titles(user_id, site_id, None, limit=PUBLISHED_TITLES_LIMIT) or []
    except JobTimeoutException:
        raise
    except Exception as e:
        logger.warning(f"Could not load published titles for site {site_id}: {e}")
    titles += [post.get('title') for post in recent_posts or [] if isinstance(post, dict)]
    seen, output = set(), []
    for title in titles:
        title = str(title or '').strip()
        if title and title.lower() not in seen:
            seen.add(title.lower())
            output.append(title)
    return output


def _cited_source_urls(article, internal_posts):
    """Research source URLs the writer was allowed to cite: the article's link
    allow-list minus the site's own posts. None when no allow-list was built."""
    allowed = article.get('allowed_link_urls')
    if allowed is None:
        return None
    internal = {post.get('url') for post in internal_posts or [] if isinstance(post, dict)}
    return [url for url in allowed if url and url not in internal]


def _protected_review_links(internal_posts, extra_allowed_urls, allowed_hosts):
    """Hosts and URLs whose links the reviewer must leave alone: the site's own
    domain, its posts and the URLs the custom article prompt asks for."""
    links = [link_host(h) if '//' in str(h or '') else h for h in allowed_hosts or []]
    links += [post.get('url') for post in internal_posts or [] if isinstance(post, dict)]
    links += list(extra_allowed_urls or [])
    return [link for link in links if link]


def _review_generated_article(generator, article, seo_data, *, language, category_name, site_name, context,
                              internal_posts=None, extra_allowed_urls=None, allowed_hosts=None,
                              article_prompt=None, category_description=None):
    """AI editorial review (fact-check, YMYL safety, title honesty) before publishing.

    The reviewer sees the research the writer saw plus the source URLs it was
    allowed to cite (so cited links can be checked against the evidence), the
    publisher's own context (category description, custom article prompt) as
    trusted facts, and the links it must not touch (site domain, internal posts,
    URLs from the custom prompt).
    Edits the article in place. When the review changed anything the quality gate
    (and link stripping) runs again; failing it now is a review rejection.
    Raises ArticleReviewRejected (content failure) or ArticleReviewUnavailable.
    """
    evidence = build_review_evidence(seo_data, language, source_urls=_cited_source_urls(article, internal_posts))
    result = review_article(
        generator, article, evidence, language=language, category=category_name, site_name=site_name,
        publisher_context=build_publisher_context(article_prompt, category_description),
        protected_links=_protected_review_links(internal_posts, extra_allowed_urls, allowed_hosts),
    )
    logger.info(f"AI review ({context}): {result.log_line()}")
    if result.changed:
        try:
            _apply_quality_gate(article, f"{context} after AI review", "",
                                extra_allowed_urls=extra_allowed_urls, allowed_hosts=allowed_hosts)
        except QualityGateRejection as e:
            raise ArticleReviewRejected([f"hasil perbaikan tidak lolos quality gate: {e}"],
                                        article.get('title')) from e
    return result


class QualityGateRejection(Exception):
    """The generated article failed the pre-publish quality gate (a content failure)."""


def _apply_quality_gate(article, warning_context, rejection_prefix, extra_allowed_urls=None, allowed_hosts=None):
    """Block truncated, too-short, template-leaking or fabricated-credential output.

    Raises QualityGateRejection with rejection_prefix plus the gate errors;
    otherwise drops any link the model invented, keeping the anchor text. Links
    in extra_allowed_urls or to allowed_hosts are always kept.
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
        raise QualityGateRejection(rejection_prefix + "; ".join(gate_errors))
    # An empty list is a real allow-list (the site has no internal posts yet):
    # every link outside it, external ones included, is unwrapped. None means no
    # list was built (or the recent posts could not be fetched) and leaves the
    # content untouched.
    if allowed_link_urls is not None:
        article['content'] = strip_invalid_internal_links(
            article['content'], list(allowed_link_urls) + list(extra_allowed_urls or []),
            allowed_hosts=allowed_hosts,
        )


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


def _tg(value):
    """Escape text going into a Telegram message sent with parse_mode=HTML."""
    return html.escape(str(value if value is not None else ''), quote=False)


def _start_message(site_config, category, custom_topic):
    return (
        f"🤖 <b>WordPress Auto Post Bot</b>\n\n"
        f"🌐 <b>Website:</b> {_tg(site_config['site_name'])}\n"
        f"📝 Mulai generate artikel...\n"
        f"📂 Kategori: {_tg(category['name'])}" + (f"\n🎯 Judul: {_tg(custom_topic)}" if custom_topic else "")
    )


def _published_message(site_config, article, category, post_url, image_data, review_note=None):
    file_size = len(image_data.getvalue()) / 1024 if image_data else 0
    return (
        f"✅ <b>Artikel Berhasil Dipublish!</b>\n\n"
        f"🌐 <b>Website:</b> {_tg(site_config['site_name'])}\n"
        f"📝 <b>Judul:</b> {_tg(article.get('title', ''))}\n"
        f"📂 <b>Kategori:</b> {_tg(category['name'])}\n"
        f"📊 <b>Panjang:</b> {len(article.get('content', '').split())} kata\n"
        f"🎨 <b>Featured Image:</b> WebP ({file_size:.1f} KB)\n"
        + (f"🔎 <b>Tinjauan:</b> {_tg(review_note)}\n" if review_note else "")
        + f"🔗 <b>URL:</b> {_tg(post_url)}\n\n"
        f"🎉 Status: Terbit"
    )


def _publish_failed_message(site_config, article, category, result):
    return (
        f"❌ <b>Posting Gagal!</b>\n\n"
        f"🌐 <b>Website:</b> {_tg(site_config['site_name'])}\n"
        f"📝 <b>Judul:</b> {_tg(article.get('title', ''))}\n"
        f"📂 <b>Kategori:</b> {_tg(category['name'])}\n"
        f"⚠️ <b>Error:</b> {_tg(str(result)[:200])}"
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
        # (research_id, raw_topic) of a research topic taken for this article;
        # handed back if the article does not go out.
        self.topic_claim = None
        # Published titles this article must not repeat, and those its skipped
        # research topics matched (passed to the writer as titles to avoid).
        self.published_titles = []
        self.avoid_titles = []
        self.review = None

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
            site_name=site_config.get('site_name'),
            language=site_config.get('language') or 'id',
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
        self.published_titles = _published_titles(self.user_id, self.site_id, recent_posts, existing_titles)
        if self.item_id:
            # A user-chosen title that repeats a published article is not
            # written at all (checked before any research or generation cost).
            self._check_topic_is_new(generator, self.custom_topic)
        seo_data = self._gather_seo_data(generator)
        self._generate_article(generator, existing_titles, seo_data, recent_posts)
        if recent_posts is None:
            # The recent posts could not be fetched: no allow-list was really
            # built, so stripping against an empty one would unwrap every link.
            self.article['allowed_link_urls'] = None
        extra_urls, hosts = _link_allowances(site_config.get('article_prompt'), site_config.get('wordpress_url'))
        _apply_quality_gate(self.article, f"site {self.site_id}", "Artikel ditolak quality gate: ",
                            extra_allowed_urls=extra_urls, allowed_hosts=hosts)
        # Nothing is published without the AI editorial review.
        title_before_review = self.article.get('title', '')
        self.review = _review_generated_article(
            generator, self.article, seo_data, language=self._language(), category_name=self.category['name'],
            site_name=site_config.get('site_name'), context=f"site {self.site_id}", internal_posts=recent_posts,
            extra_allowed_urls=extra_urls, allowed_hosts=hosts,
            article_prompt=site_config.get('article_prompt'),
            category_description=_category_description(site_config, self.category['name']),
        )
        self._keep_reviewed_title_distinct(generator, title_before_review)

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

    def _language(self):
        return (self.site_config or {}).get('language') or 'id'

    def _similar_published(self, generator, title):
        """(published title, score) that `title` would cannibalize, or None."""
        return find_similar_published(title, self.published_titles, language=self._language(),
                                      generator=generator)

    def _check_topic_is_new(self, generator, topic):
        match = self._similar_published(generator, topic)
        if match:
            logger.warning(f"Topic '{topic}' repeats published article '{match[0]}' (score {match[1]}).")
            raise TopicTooSimilar(match[0])

    def _keep_reviewed_title_distinct(self, generator, title_before_review):
        """A title the reviewer rewrote must not repeat a published article either.

        The pre-review title already passed that check, so a reviewer title that
        fails it is dropped and the original kept.
        """
        if not (self.review and self.review.title_changed):
            return
        match = self._similar_published(generator, self.article.get('title', ''))
        if match:
            logger.warning(
                f"Reviewer title '{self.article.get('title')}' repeats published article '{match[0]}'; "
                f"keeping '{title_before_review}'."
            )
            self.article['title'] = title_before_review
            self.review.title_changed = False

    def _claim_new_research_topic(self, generator, category_name):
        """Claim the next research topic that does not repeat a published article.

        A topic too similar to a published title is consumed (not handed back)
        and the next one is tried, MAX_TOPIC_CLAIMS at most. Returns the claim, or
        None when no distinct topic was found; only then are the published titles
        the skipped topics matched kept in avoid_titles, so the category article
        written instead steers away from them. A distinct topic is written
        normally (no avoid_similar).
        """
        matched = []
        for _ in range(MAX_TOPIC_CLAIMS):
            claim = db.get_unused_research_topic(self.user_id, self.site_id, category_name,
                                                 return_claim=True)
            if not claim:
                break
            # Held while it is checked, so a failure here still hands it back.
            self.topic_claim = (claim[0], claim[2])
            match = self._similar_published(generator, claim[1])
            if not match:
                return claim
            self.topic_claim = None
            logger.warning(
                f"Research topic '{claim[1]}' consumed: too similar to published article "
                f"'{match[0]}' (score {match[1]})."
            )
            matched.append(match[0])
        if matched:
            logger.warning(
                f"No research topic for '{category_name}' distinct from published articles "
                f"({len(matched)} skipped); writing a category article that avoids them."
            )
            self.avoid_titles = matched
        return None

    def _gather_seo_data(self, generator=None):
        category_name = self.category['name']
        topic_is_trending = False
        if not self.item_id:
            # Scheduled/category posts take an unused research topic, if any. It
            # is only spent for good once the article is published.
            claim = self._claim_new_research_topic(generator, category_name)
            if claim:
                research_id, self.custom_topic, raw_topic = claim
                self.topic_claim = (research_id, raw_topic)
                topic_is_trending = _topic_is_trending(raw_topic)
                logger.info(f"Using research topic: {self.custom_topic}")
        # Category research is the background evidence for every article. Queue
        # items carry their own title (the topic, researched below) but used to
        # be written without any of their category's research.
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
        seo_data = _attach_search_evidence(seo_data, self.user_id, self.site_id, category_name,
                                           topic=self.custom_topic,
                                           language=self.site_config.get('language') or 'id')
        # The prompt labels the topic "trending" only when it really came from
        # Google Trends; queue titles and other topics stay neutral.
        if topic_is_trending and isinstance(seo_data, dict):
            seo_data['topic_is_trending'] = True
        return seo_data

    def _generate_article(self, generator, existing_titles, seo_data, recent_posts):
        """Generate the article, once more with avoid_similar if its title repeats a
        published article; a second repeat fails the job (TopicTooSimilar)."""
        site_config = self.site_config
        category_name = self.category['name']
        options = dict(
            custom_prompt=site_config.get('article_prompt') or None,
            site_name=site_config.get('site_name'),
            language=site_config.get('language', 'id'),
            category_desc=_category_description(site_config, category_name),
            internal_links_context=recent_posts
        )

        def titles_to_avoid(*matched):
            # The prompt lists the last 10 titles given, so the ones that must
            # be avoided go at the end.
            avoid = [t for t in list(self.avoid_titles) + list(matched) if t]
            return [t for t in existing_titles or [] if t not in avoid] + avoid

        if self.avoid_titles:
            # No distinct research topic was found: this is a category article
            # that must steer clear of the published titles the topics matched.
            self.article = generator.generate_checked_article(
                category_name, titles_to_avoid(), self.custom_topic, seo_data, avoid_similar=True, **options
            )
        else:
            self.article = generator.generate_checked_article(
                category_name, existing_titles, self.custom_topic, seo_data, **options
            )

        match = self._similar_published(generator, self.article.get('title', ''))
        if match:
            logger.warning(
                f"Similar title detected (score {match[1]}): '{self.article.get('title')}' ~ '{match[0]}'. "
                "Regenerating..."
            )
            self.article = generator.generate_checked_article(
                category_name, titles_to_avoid(match[0]), self.custom_topic, seo_data, avoid_similar=True,
                **options
            )
            match = self._similar_published(generator, self.article.get('title', ''))
            if match:
                raise TopicTooSimilar(match[0], article_title=self.article.get('title'))

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
            if self.review:
                result_msg = f"{result_msg} {self.review.note}"
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
                self.site_config, _published_message(self.site_config, article, category, post_url, image_data,
                                                     review_note=self.review.note if self.review else None)
            )
            _share_published_post(self.site_config, article, post_url, image_data)
            logger.info(f"Article published successfully: {article.get('title', '')}")
        else:
            send_telegram_notification(
                self.site_config, _publish_failed_message(self.site_config, article, category, result)
            )
            logger.error(f"Article publish failed: {result}")

    def restore_research_topic(self, error=None):
        """Settle an unpublished research topic after a failure.

        A failure caused by the content itself (quality gate, refusal) would
        repeat with the same topic, so the topic is consumed. Anything else
        (WordPress/network/publish errors, timeouts, transient provider errors)
        hands it back, at most MAX_TOPIC_RESTORES times, so a topic can never
        block the category's rotation for days.
        """
        claim, self.topic_claim = self.topic_claim, None
        if not claim:
            return
        if error is not None and _is_content_failure(error):
            logger.info(f"Research topic '{self.custom_topic}' consumed: the article failed on its content.")
            return
        try:
            if db.restore_research_topic(*claim, max_restores=MAX_TOPIC_RESTORES):
                logger.info(f"Research topic '{self.custom_topic}' returned for a later article.")
            else:
                logger.info(f"Research topic '{self.custom_topic}' consumed after repeated failures.")
        except Exception as e:
            logger.error(f"Could not return research topic '{self.custom_topic}': {e}")

    def _settle_after_publish(self, success, unconfirmed, post_url):
        """Settle the queue item and credit right after publishing, before any
        further step that could raise and send this job into the failure path."""
        if success or unconfirmed:
            # The topic is spent: the post went out (or may have).
            self.topic_claim = None
            if self.item_claimed and not self.item_settled:
                _settle_queue_item(self.user_id, self.item_id, self.job_id,
                                   status='posted' if success else 'failed',
                                   refund=False, post_url=post_url)
                self.item_settled = True
            self.credit_reserved = False
        else:
            self.release_credit('failed')
            self.restore_research_topic()

    def _handle_failure(self, error):
        error_msg = str(error)
        logger.error(f"Error in generate_and_post for site {self.site_id}: {error_msg}", exc_info=True)
        # Refunds an unconsumed reservation once and marks the item failed. A
        # no-op when the outcome was already settled (e.g. the post went live
        # and a later notification step raised).
        self.release_credit('failed')
        # A no-op once the post went out (_settle_after_publish spent the topic).
        self.restore_research_topic(error)

        # Category values for the history, even if the job failed early.
        log_category_id = self.category['id'] if self.category else None
        log_category_name = self.category['name'] if self.category else "Kategori tidak diketahui"
        log_title = (
            getattr(error, 'article_title', None)
            or (self.article.get('title') if self.article else None)
            or self.custom_topic
            or f"Artikel kategori {log_category_name}"
        )

        # A rejection by the editorial checks is a decision, not a crash.
        result_prefix = (
            "Artikel tidak diterbitkan" if isinstance(error, EDITORIAL_FAILURES) else "Sistem Berhenti Tiba-tiba"
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
                result=f"{result_prefix}: {error_msg}"[:500],
                post_id=None,
                post_url=None
            )
        except Exception as log_e:
            logger.error(f"Failed to save error log: {log_e}")

        try:
            send_telegram_notification(self.site_config or {},
                                       f"❌ <b>Gagal Generate &amp; Post</b>\n\n"
                                       f"⚠️ {_tg(error_msg[:200])}")
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
            'category_description': _category_description({'categories': site.categories}, log.category_name),
            'site_id': site.id,
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
    return WordPressPublisher(target['wordpress_url'], target['wordpress_username'], target['wordpress_password'],
                              language=target.get('language') or 'id')


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
        recent_posts = _recent_posts_for_links(publisher)
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
            internal_links_context=recent_posts
        )
        if recent_posts is None:
            article['allowed_link_urls'] = None  # fetch failed: leave links alone
        extra_urls, hosts = _link_allowances(target['article_prompt'], target['wordpress_url'])
        _apply_quality_gate(article, f"regenerate log {log_id}", "Artikel hasil regenerasi ditolak quality gate: ",
                            extra_allowed_urls=extra_urls, allowed_hosts=hosts)
        # The writer gets no research here, but the reviewer checks claims against
        # the category's fresh research when there is some, plus the publisher's
        # own context.
        review = _review_generated_article(
            generator, article, _load_category_research(user_id, target['site_id'], target['category_name']),
            language=target['language'] or 'id', category_name=target['category_name'],
            site_name=target['site_name'], context=f"regenerate log {log_id}", internal_posts=recent_posts,
            extra_allowed_urls=extra_urls, allowed_hosts=hosts,
            article_prompt=target['article_prompt'], category_description=target['category_description'],
        )

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
        _set_log_result(log_id, f"{RESULT_REGENERATED} {review.note}")
        logger.info(f"Consumed reserved credit for user_id={user_id}, log_id={log_id}")
    except Exception as e:
        _fail_regeneration(user_id, log_id, e, 'regenerate_article_job', 'article regen', 'Regenerasi artikel gagal')
