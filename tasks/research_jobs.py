import html
import inspect
import re
from datetime import datetime

try:
    from rq.timeouts import BaseTimeoutException
except ImportError:  # pragma: no cover - older/newer RQ layouts
    class BaseTimeoutException(Exception):
        pass

import core_extensions
from core_extensions import db, trending, logger, send_telegram_notification
from database import (
    category_key, read_research_charge, release_research_lock, restore_research_charge,
    take_research_charge, update_research_charge,
)
from models import WordPressSite
from services.content_planner import load_search_metrics, text_matches_topic
from services.wp_publisher import WordPressPublisher

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

TOPIC_SUGGESTION_COUNT = 10
SCHEDULED_FAILURE_NOTICE_TTL_SECONDS = 2 * 86400


def _redis():
    # Looked up at call time so tests can patch core_extensions.redis_conn.
    return getattr(core_extensions, 'redis_conn', None)


def _current_job():
    try:
        from rq import get_current_job
        return get_current_job()
    except Exception as e:
        logger.debug(f"Could not resolve the current RQ job: {e}")
        return None


def _report_progress(job, progress, message):
    """Expose real progress to /api/job-status (job.meta progress/message)."""
    if job is None:
        return
    try:
        job.meta['progress'] = max(0, min(100, int(progress)))
        job.meta['message'] = message
        job.save_meta()
    except Exception as e:
        logger.debug(f"Could not save research job progress: {e}")


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
        with db.get_session() as session:
            current_rows, _ = load_search_metrics(session, user_id, site_id)
        return _aggregate_queries(current_rows)
    except Exception as e:
        logger.warning(f"Could not load Search Console evidence for site {site_id}: {e}")
        return []


def _search_console_evidence(gsc_queries, category_name):
    """Distinct queries about the category, so the match is explainable.

    Uses the same relevance rule as the article and title paths
    (content_planner.text_matches_topic): a shared distinctive word, or the
    category name as a phrase. A generic word such as "tips", "cara" or
    "online" no longer validates an unrelated category.
    """
    matches = []
    # Aggregating again is idempotent and protects against callers passing raw
    # per-page rows, which would count one query several times.
    for item in _aggregate_queries(gsc_queries):
        if text_matches_topic(item['query'], category_name):
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
    """Selected categories by normalized name (database.category_key), first occurrence wins."""
    seen, unique = set(), []
    for cat in categories or []:
        name = cat.get('name') if isinstance(cat, dict) else None
        key = category_key(name) if isinstance(name, str) else ''
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(cat)
    return unique


def _confidence_level(quality_score, real_provider_count):
    if quality_score >= 75 and real_provider_count >= 5:
        return 'high'
    if quality_score >= 50 and real_provider_count >= 3:
        return 'medium'
    if quality_score >= MIN_RESEARCH_QUALITY_SCORE and real_provider_count >= 2:
        return 'low'
    return 'insufficient'


def _score_research(seo_data, trending_data, gsc_queries, category_name):
    """Combine SEOResearch's quality with related queries and Search Console.

    Returns (source_metadata, quality_score, confidence_level). Raises
    RuntimeError when the evidence is insufficient to write from.
    """
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
    # Search Console is first-party evidence: real queries that really reached
    # this site. It does not depend on scraping Google Trends or DuckDuckGo, both
    # of which block server IPs, so it keeps a category viable when the scraped
    # providers are unavailable.
    gsc_matches = _search_console_evidence(gsc_queries, category_name)
    source_metadata['search_console'] = {
        'status': 'real' if gsc_matches else 'unavailable',
        'count': len(gsc_matches),
        'queries': gsc_matches[:10],
    }

    # Related queries come from pytrends, the same provider that evaluate_quality
    # already scores as google_trends. They used to add up to 10 points and a
    # whole extra provider on top of it, double-counting Google Trends. Now Trends
    # counts once: only when SEOResearch's own Trends call did not already succeed.
    trends_points, trends_providers = _google_trends_top_up(source_metadata, related_count)
    gsc_score = min(GSC_MAX_WEIGHT, len(gsc_matches) * GSC_POINTS_PER_MATCH)
    quality_score = min(100, int(quality.get('score', 0)) + trends_points + gsc_score)
    real_provider_count = (int(quality.get('real_provider_count', 0))
                           + trends_providers
                           + (1 if gsc_matches else 0))
    confidence_level = _confidence_level(quality_score, real_provider_count)
    if confidence_level == 'insufficient':
        raise RuntimeError(
            f'Insufficient research evidence (quality={quality_score}, '
            f'real_providers={real_provider_count})'
        )
    return source_metadata, quality_score, confidence_level


def _build_topic_suggestions(category_name, trending_data, evidence):
    """Article topics for a category from one trend snapshot plus observed evidence.

    build_topic_suggestions only received the Trends snapshot, so a category
    whose Trends call came back empty (common: Google blocks server IPs) saved
    zero topics. Observed autocomplete suggestions, questions and long-tail
    keywords are passed to the optional parameters TrendingResearch accepts
    (suggestions/questions/long_tail); each topic it returns carries is_trending.
    """
    build = trending.build_topic_suggestions
    try:
        params = inspect.signature(build).parameters
    except (TypeError, ValueError):
        params = {}
    kwargs = {
        name: value for name, value in evidence.items()
        if name in params and params[name].kind in (
            inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
    }
    return list(build(category_name, trending_data, count=TOPIC_SUGGESTION_COUNT, **kwargs) or [])


def _research_category(seo, user_id, site_id, category_name, language, gsc_queries):
    """Research one category and save it. Returns the number of article topics found.

    Raises when it fails or lacks evidence. Research with enough evidence is
    saved even when it yields no topic: its keywords, questions and competitor
    outlines still ground titles and articles.
    """
    trending_data = trending.get_trending_topics(category_name, limit=15, language=language)

    try:
        seo_data = seo.research_category(category_name, language=language)
        source_metadata, quality_score, confidence_level = _score_research(
            seo_data, trending_data, gsc_queries, category_name
        )
    except Exception as e:
        logger.error(f"SEO research error for {category_name}: {e}")
        raise

    # Fallback-generated keywords/questions are invented; store only observed
    # evidence so the article generator never sees them.
    keywords = seo_data.get('evidence_suggestions', seo_data.get('suggestions', []))
    questions = seo_data.get('evidence_questions', seo_data.get('questions', []))
    long_tail = seo_data.get('long_tail_keywords', [])
    trend_score = seo_data.get('trend_score', 0)
    logger.info(f"SEO research: {len(keywords)} keywords, {len(questions)} questions, trend score: {trend_score}")

    # Derived from the same Trends snapshot as above: no second Google Trends
    # request, so no inconsistent results or extra rate limiting. Only observed
    # (non-fallback) evidence may become a topic; the offline fallback phrases
    # are invented.
    suggestions = _build_topic_suggestions(category_name, trending_data, {
        'suggestions': list(seo_data.get('evidence_suggestions') or []),
        'questions': list(seo_data.get('evidence_questions') or []),
        'long_tail': list(long_tail or []),
    })

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
        competitor_outlines=seo_data.get('competitor_outlines', []),
        youtube_insights=seo_data.get('youtube_insights', []),
        social_insights=seo_data.get('social_insights', []),
        trend_score=trend_score,
        semantic_context=seo_data.get('semantic_context', ''),
        news_insights=seo_data.get('news_insights', []),
        source_metadata=source_metadata,
        quality_score=quality_score,
        confidence_level=confidence_level,
        is_fallback=any(
            meta.get('status') == 'fallback'
            for meta in source_metadata.values()
            if isinstance(meta, dict)
        ),
    )
    if suggestions:
        logger.info(f"Research completed for {category_name}: {len(suggestions)} topics found")
    else:
        logger.warning(
            f"Research completed for {category_name} but found no article topic; the evidence is "
            "saved for titles/articles and the row is skipped when picking a topic."
        )
    return len(suggestions)


class _ResearchRefund:
    """Refund bookkeeping for one deep_research_job run.

    Every refund is bounded by what was charged: in total the job refunds
    exactly the charge minus the categories researched successfully, never more,
    however many failure paths call settle(). Scheduled runs (force=False) were
    never charged and never refund.

    A manual run's reservation is also recorded in Redis (research_charge:{job_id})
    so the dispatcher can refund it if this job is killed without running any
    of its own code. Settling first takes that record atomically; whoever takes
    it (this job or the dispatcher) is the only one that refunds.
    """

    def __init__(self, user_id, force, charged_credits, charge_job_id=None):
        self.user_id = user_id
        self.force = force
        self.charged = None
        self.refunded = 0
        self.successful = 0
        self.charge_job_id = charge_job_id
        self.charge_record = None
        self.taken_record = None
        self.settlement_owned = None
        if force and charged_credits is not None:
            self.set_charged(charged_credits)

    def set_charged(self, value):
        self.charged = max(0, int(value or 0)) if self.force else 0

    def load_charge_record(self):
        if not self.charge_job_id:
            return
        try:
            self.charge_record = read_research_charge(_redis(), self.charge_job_id)
        except Exception as e:
            logger.warning(f"Could not read research reservation {self.charge_job_id}: {e}")

    def record_progress(self):
        """Store the successful count on the reservation record, so a reconciliation
        after a kill refunds only the categories that were not researched."""
        if not (self.charge_job_id and self.charge_record):
            return
        self.charge_record['successful'] = self.successful
        try:
            update_research_charge(_redis(), self.charge_job_id, self.charge_record)
        except Exception as e:
            logger.warning(f"Could not record research progress for {self.charge_job_id}: {e}")

    def _owns_settlement(self):
        if self.settlement_owned is not None:
            return self.settlement_owned
        if not self.charge_job_id:
            self.settlement_owned = True
            return True
        try:
            record = take_research_charge(_redis(), self.charge_job_id)
        except Exception as e:
            # Redis unreachable: this job settles. The dispatcher only refunds a
            # record whose job is not 'finished', and this job finishes.
            logger.warning(f"Could not take research reservation {self.charge_job_id}: {e}; settling here.")
            self.settlement_owned = True
            return True
        if record is None:
            logger.warning(
                f"Research reservation {self.charge_job_id} was already settled by the "
                "dispatcher; not refunding again."
            )
            self.settlement_owned = False
            return False
        self.taken_record = record
        self.settlement_owned = True
        return True

    def settle(self):
        """Refund whatever is still owed. Idempotent; returns the amount refunded now."""
        if self.force and not self._owns_settlement():
            return 0
        charged = self.charged or 0
        owed = max(0, charged - self.successful) - self.refunded
        owed = min(owed, charged - self.refunded)
        if owed <= 0:
            return 0
        try:
            db.refund_user_credits(self.user_id, owed)
            self.refunded += owed
            logger.info(f"Refunded {owed} research credit(s) to user {self.user_id} (charged {charged}).")
            return owed
        except Exception as refund_err:
            logger.error(f"Failed to refund {owed} research credit(s) to user {self.user_id}: {refund_err}")
            self._hand_back_record(owed)
            return 0

    def _hand_back_record(self, owed):
        """After a failed refund, put the taken reservation record back (marked
        needs_refund with what is owed) so the dispatcher's reconciliation retries."""
        if not (self.charge_job_id and self.taken_record):
            return
        try:
            restore_research_charge(_redis(), self.charge_job_id, self.taken_record, owed=owed)
            self.taken_record = None
        except Exception as e:
            logger.error(f"Could not hand research reservation {self.charge_job_id} back: {e}")


def _load_research_plan(user_id, site_id, category, categories, force, refund):
    """Returns (site_config, language, categories to research, skip_reason).

    site_config is None when the site no longer exists; the category list is
    empty (with an Indonesian skip_reason) when there is nothing to research.
    """
    with db.get_session() as session:
        site = session.query(WordPressSite).filter_by(id=site_id, user_id=user_id).first()
        if not site:
            logger.error(f"Site {site_id} not found")
            return None, None, [], 'Website tidak ditemukan.'

        raw_categories = site.selected_categories or []
        if force and refund.charged is None:
            # Legacy enqueue without charged_credits: the route charged one credit
            # per selected category (or one for a single category).
            refund.set_charged(1 if category else len(raw_categories))

        selected_categories = _dedupe_categories(raw_categories)
        if category:
            # Same normalization as the route, so a category it accepted cannot
            # silently match nothing here.
            wanted = category_key(category)
            selected_categories = [cat for cat in selected_categories if category_key(cat['name']) == wanted]
        if categories is not None:
            wanted_keys = {category_key(name) for name in categories}
            selected_categories = [cat for cat in selected_categories if category_key(cat['name']) in wanted_keys]
        if force:
            # Never research more categories than were paid for.
            selected_categories = selected_categories[:refund.charged or 0]

        site_config = {
            'telegram_enabled': site.telegram_enabled,
            'telegram_bot_token': site.telegram_bot_token,
            'telegram_chat_id': site.telegram_chat_id,
            'site_name': site.site_name,
            'wordpress_url': getattr(site, 'wordpress_url', None),
        }
        skip_reason = None
        if not selected_categories:
            logger.info(f"No categories to research for site {site.site_name}")
            skip_reason = (f"Kategori '{category}' tidak lagi dipilih untuk website ini."
                           if category else 'Tidak ada kategori yang perlu diriset.')
        return site_config, site.language or 'id', selected_categories, skip_reason


def _research_categories(job, refund, outcome, user_id, site_id, site_name, language, selected_categories,
                         exclude_hosts=None):
    """Research each category in turn, recording progress and outcome.

    exclude_hosts: the site's own host(s), never counted as a competitor or source.
    """
    total = len(selected_categories)
    outcome['total'] = total
    logger.info(f"Starting research job for site {site_name} (language={language}, categories={total})")

    # Local import: seo_research pulls in pytrends/pandas, which are heavy
    # and do not import in every environment.
    from seo_research import SEOResearch
    seo = SEOResearch()
    # The site's own pages must not be researched as its competitors. Set as an
    # attribute (the default for every SEOResearch lookup), not passed per call.
    seo.exclude_hosts = exclude_hosts

    # Loaded once for the whole job rather than per category.
    gsc_queries = _load_search_console_queries(user_id, site_id)
    if gsc_queries:
        logger.info(f"Search Console evidence available: {len(gsc_queries)} queries for site {site_id}")
    else:
        logger.info(
            f"No Search Console evidence for site {site_id}. Connecting Search Console "
            "would keep categories viable when Trends/DuckDuckGo block this server."
        )

    for index, cat in enumerate(selected_categories):
        category_name = cat['name']
        _report_progress(job, round(index / total * 100),
                         f"Meriset kategori '{category_name}' ({index + 1}/{total})...")
        logger.info(f"Researching category: {category_name} on {site_name}")
        try:
            topic_count = _research_category(seo, user_id, site_id, category_name, language, gsc_queries)
            refund.successful += 1
            refund.record_progress()
            if not topic_count:
                outcome['without_topics'].append(category_name)
        except BaseTimeoutException:
            # RQ's death penalty raises inside the job and is an Exception
            # subclass, so the per-category handler below used to swallow it and
            # keep looping past the deadline. Let it propagate: the caller
            # refunds every category that was not completed.
            logger.error(
                f"Research job hit its time limit while processing '{category_name}'. "
                f"Completed {refund.successful} categories."
            )
            raise
        except Exception as cat_error:
            logger.error(f"Failed to research category {category_name}: {cat_error}")
            outcome['failed'] += 1


def _release_site_lock(site_id, job_id):
    if not site_id or not job_id:
        return
    try:
        release_research_lock(_redis(), site_id, job_id)
    except Exception as e:
        logger.warning(f"Could not release the research lock of site {site_id}: {e}")


def _result_reason(result, outcome):
    if result['reason'] or result['skipped']:
        return result['reason']
    if result['successful_categories'] == 0:
        return 'Tidak ada kategori yang berhasil diriset.'
    if outcome['without_topics']:
        return ('Riset tersimpan, tetapi tidak ditemukan topik artikel baru untuk: '
                + ', '.join(outcome['without_topics']) + '.')
    return None


def _should_notify(force, site_id, result):
    """Manual runs always report. The scheduler's daily refresh stays quiet on
    success and reports a failure only when every category failed, at most once
    a day per site."""
    if force:
        return True
    if result['skipped'] or result['successful_categories'] > 0 or not result['failed_categories']:
        return False
    key = f"research_fail_notice:{site_id}:{datetime.now().strftime('%Y-%m-%d')}"
    try:
        return bool(_redis().set(key, '1', nx=True, ex=SCHEDULED_FAILURE_NOTICE_TTL_SECONDS))
    except Exception as e:
        logger.warning(f"Could not check the research failure notice of site {site_id}: {e}")
        return True


def _notify_research_result(site_config, category, result, error_message=None):
    """Telegram summary. Never raises: a notification failure must not turn a
    successful research run into a failed job."""
    if not site_config or result['skipped']:
        return
    try:
        site_name = html.escape(str(site_config.get('site_name') or ''))
        successful = result['successful_categories']
        failed = result['failed_categories']
        refunded = result['refunded_credits']
        without_topics = result.get('categories_without_topics') or []
        if error_message and not successful:
            msg = (f"❌ <b>Kesalahan Sistem Riset</b>\n\n"
                   f"🌐 <b>Website:</b> {site_name}\n"
                   f"Error: {html.escape(error_message[:150])}")
        elif successful > 0:
            category_str = (f"kategori '{html.escape(category)}'" if category
                            else f"{successful} kategori")
            msg = (f"🔍 <b>Riset Selesai</b>\n\n"
                   f"🌐 <b>Website:</b> {site_name}\n"
                   f"✅ Berhasil meriset {category_str}")
            if without_topics:
                names = html.escape(', '.join(without_topics))
                msg += (f"\n⚠️ Tidak ditemukan topik artikel baru untuk: {names}. "
                        f"Data riset tetap disimpan untuk judul dan artikel.")
            if len(without_topics) < successful:
                msg += "\n📊 Topik trending disimpan untuk artikel berikutnya"
            if failed > 0:
                msg += f"\n⚠️ Gagal meriset {failed} kategori."
        else:
            msg = (f"❌ <b>Riset Gagal</b>\n\n"
                   f"🌐 <b>Website:</b> {site_name}\n"
                   f"⚠️ {html.escape(result.get('reason') or 'Tidak ada kategori yang berhasil diriset.')}")
        if refunded > 0:
            msg += f"\n💰 {refunded} kredit dikembalikan."
        send_telegram_notification(site_config, msg)
    except Exception as notify_err:
        logger.error(f"Failed to send research notification: {notify_err}")


def deep_research_job(user_id, force=True, site_id=None, category=None, charged_credits=None,
                      categories=None, charge_recorded=False):
    """Research a site's selected categories and store the evidence.

    force=True is a manual run: charged_credits is what the route reserved, and
    every refund is bounded by it. In total the job refunds exactly
    charged_credits minus the categories it researched successfully, never more,
    however many failure paths run. charge_recorded=True means the route also
    recorded the reservation in Redis for the dispatcher's reconciliation.

    force=False is the scheduler's free daily refresh: never charged, never
    refunds. categories optionally restricts the run to those names.

    Always returns {"successful_categories", "failed_categories",
    "refunded_credits", "skipped", "reason", "categories_without_topics"} and
    releases the site's research lock (research_lock:{site_id}) when it ends.
    """
    job = _current_job()
    job_id = getattr(job, 'id', None)
    refund = _ResearchRefund(user_id, force, charged_credits,
                             charge_job_id=job_id if (force and charge_recorded) else None)
    outcome = {'total': 0, 'failed': 0, 'skipped': False, 'reason': None, 'without_topics': []}
    site_config = None
    error_message = None

    try:
        # Everything that can fail is inside this try, so every path settles the
        # reservation and releases the lock in the finally below.
        refund.load_charge_record()
        _report_progress(job, 0, 'Menyiapkan riset...')
        if not site_id:
            logger.error("No site_id provided for deep_research_job")
            outcome.update(skipped=True, reason='site_id tidak diberikan.')
        else:
            site_config, language, selected_categories, skip_reason = _load_research_plan(
                user_id, site_id, category, categories, force, refund
            )
            if not selected_categories:
                outcome.update(skipped=True, reason=skip_reason)
            else:
                outcome['total'] = len(selected_categories)
                _research_categories(job, refund, outcome, user_id, site_id,
                                     site_config['site_name'], language, selected_categories,
                                     exclude_hosts=[site_config.get('wordpress_url')])
    except BaseTimeoutException:
        outcome['failed'] = max(0, outcome['total'] - refund.successful)
        outcome['reason'] = (f'Riset melewati batas waktu setelah {refund.successful} '
                             f'kategori berhasil diriset.')
        error_message = outcome['reason']
    except Exception as e:
        logger.error(f"Research job error: {e}", exc_info=True)
        outcome['failed'] = max(0, outcome['total'] - refund.successful)
        outcome['reason'] = 'Terjadi kesalahan sistem saat riset.'
        error_message = str(e)
    finally:
        # Refund every charged credit that did not produce research: failed
        # categories, categories never reached, and any surplus charged for
        # duplicate category entries. Bounded by charged_credits.
        refund.settle()
        _release_site_lock(site_id, job_id)

    result = {
        'successful_categories': refund.successful,
        'failed_categories': outcome['failed'],
        'refunded_credits': refund.refunded,
        'skipped': outcome['skipped'],
        'reason': outcome['reason'],
        'categories_without_topics': list(outcome['without_topics']),
    }
    result['reason'] = _result_reason(result, outcome)
    _report_progress(job, 100, 'Riset selesai.' if result['successful_categories'] else
                     (result['reason'] or 'Riset selesai.'))
    if _should_notify(force, site_id, result):
        _notify_research_result(site_config, category, result, error_message)
    return result


# ---------------------------------------------------------------------------
# Bulk year update
# ---------------------------------------------------------------------------

YEAR_MIN = 2000
YEAR_MAX = 2100

# Markup whose text is never visible prose: comments (Gutenberg block comments
# carry JSON with image URLs), script/style/pre/code/textarea blocks, any tag
# (attributes hold href/src/srcset URLs) and shortcodes.
_PROTECTED_MARKUP_RE = re.compile(
    r'<!--.*?-->'
    r'|<(script|style|pre|code|textarea)\b[^>]*>.*?</\1\s*>'
    r'|<[^>]*>'
    r'|\[[^\[\]\n]*\]',
    re.IGNORECASE | re.DOTALL,
)
# URLs, e-mail addresses and path-like tokens inside plain text.
_PROTECTED_TOKEN_RE = re.compile(
    r'(?:[a-z][a-z0-9+.\-]*:)?//\S+|www\.\S+|\S*[/\\@]\S*',
    re.IGNORECASE,
)


def parse_year(value):
    """A year between YEAR_MIN and YEAR_MAX from an int or a 4-digit string, else None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        year = value
    elif isinstance(value, str) and re.fullmatch(r'\d{4}', value.strip()):
        year = int(value.strip())
    else:
        return None
    return year if YEAR_MIN <= year <= YEAR_MAX else None


def validate_year_change(from_year, to_year):
    """Returns (from_year, to_year, None) or (None, None, Indonesian error message)."""
    parsed_from, parsed_to = parse_year(from_year), parse_year(to_year)
    if parsed_from is None or parsed_to is None:
        return None, None, f'Tahun harus berupa 4 digit antara {YEAR_MIN} dan {YEAR_MAX}.'
    if parsed_from == parsed_to:
        return None, None, 'Tahun asal dan tahun tujuan tidak boleh sama.'
    return parsed_from, parsed_to, None


def _year_pattern(year):
    # Not part of a longer number, word, path, URL slug or file name: no word
    # character, '/', '.', '-', '#', '=', '+' or '%' before it, and no word
    # character, '/', '-', '=', '%' or ".x" after it. A sentence-ending period
    # ("Panduan 2025.") is still allowed.
    return re.compile(
        r'(?<![\w/.\-#=+%])' + re.escape(str(year)) + r'(?![\w/\-=%])(?!\.\w)'
    )


def _replace_in_plain_text(text, pattern, replacement):
    parts, pos = [], 0
    for match in _PROTECTED_TOKEN_RE.finditer(text):
        parts.append(pattern.sub(replacement, text[pos:match.start()]))
        parts.append(match.group(0))
        pos = match.end()
    parts.append(pattern.sub(replacement, text[pos:]))
    return ''.join(parts)


def replace_year_in_title(title, from_year, to_year):
    """Replace a standalone year in a plain-text title, never inside a URL or path."""
    return _replace_in_plain_text(title or '', _year_pattern(from_year), str(to_year))


def replace_year_in_content(content, from_year, to_year):
    """Replace a standalone year in the visible text of post HTML only.

    Tags and their attributes (href/src), comments, script/style/pre/code
    blocks, shortcodes, URLs and path-like tokens are copied unchanged, so
    /wp-content/uploads/2025/06/x.jpg and links keep working.
    """
    content = content or ''
    pattern = _year_pattern(from_year)
    replacement = str(to_year)
    parts, pos = [], 0
    for match in _PROTECTED_MARKUP_RE.finditer(content):
        parts.append(_replace_in_plain_text(content[pos:match.start()], pattern, replacement))
        parts.append(match.group(0))
        pos = match.end()
    parts.append(_replace_in_plain_text(content[pos:], pattern, replacement))
    return ''.join(parts)


def bulk_update_year_task(user_id, site_id, from_year, to_year):
    """Background task to bulk update the year in WordPress post titles and text."""
    from_year, to_year, error = validate_year_change(from_year, to_year)
    if error:
        logger.error(f"bulk_update_year_task rejected: {error}")
        return {'updated': 0, 'error': error}

    logger.info(f"Starting bulk update year from {from_year} to {to_year} for site_id {site_id}")
    total_updated = 0
    try:
        with db.get_session() as session:
            site = session.query(WordPressSite).filter_by(id=site_id, user_id=user_id).first()
            if not site:
                logger.error(f"Site {site_id} not found")
                return {'updated': 0, 'error': 'Website tidak ditemukan.'}

            site_config = {
                'wordpress_url': site.wordpress_url,
                'wordpress_username': site.wordpress_username,
                'wordpress_password': site.wordpress_password,
                'site_name': site.site_name,
                'telegram_enabled': getattr(site, 'telegram_enabled', False),
                'telegram_bot_token': getattr(site, 'telegram_bot_token', None),
                'telegram_chat_id': getattr(site, 'telegram_chat_id', None),
            }

        bot = WordPressPublisher(
            site_config['wordpress_url'],
            site_config['wordpress_username'],
            site_config['wordpress_password'],
            site_name=site_config.get('site_name')
        )

        page = 1
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

                new_title = replace_year_in_title(title, from_year, to_year)
                if new_title == title:
                    continue
                update_data = {
                    'title': new_title,
                    'content': replace_year_in_content(content, from_year, to_year),
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
                f"🌐 <b>Website:</b> {html.escape(str(site_config['site_name'] or ''))}\n"
                f"🔄 <b>Tahun:</b> {from_year} ➡️ {to_year}\n"
                f"📊 <b>Total Update:</b> {total_updated} Artikel")
        except Exception as e:
            logger.error(f"Failed to send Telegram notification: {e}")

    except Exception as e:
        logger.error(f"Error in bulk_update_year_task: {e}", exc_info=True)
    return {'updated': total_updated}
