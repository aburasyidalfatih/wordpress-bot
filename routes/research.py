import json
import re
import uuid
from difflib import SequenceMatcher
from datetime import datetime
from flask import Blueprint, request, jsonify
from rq.exceptions import NoSuchJobError
from rq.job import Job
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import load_only

import core_extensions
import rate_limit
from core_extensions import db, trending, logger, load_config, require_jwt
from routes.prompts import check_ai_helper_quota
from database import (
    LOCK_ACTIVE, LOCK_FREE, LOCK_STARTING, MAX_RESEARCH_AGE_DAYS, USABLE_CONFIDENCE_LEVELS,
    acquire_research_lock, category_key, is_research_fresh, record_research_charge, release_research_lock,
    research_job_timeout, research_lock_state, research_lock_ttl, restore_research_charge, take_research_charge,
)
from models import ContentQueue, PostLog, ResearchData, User, WordPressSite
from services.research_notes import evidence_warnings, optional_notes
from services.ai_providers import describe_provider_error, text_provider_name
from services.article_generator import ArticleGenerator
from services.article_prompts import public_category_description
from services.search_console import build_search_opportunities
from services.content_planner import (
    load_search_metrics, plan_from_opportunities, topic_candidates_from_opportunities,
    keyword_demand_map, annotate_keywords_with_demand, filter_opportunities_for_topic,
    find_content_gaps, classify_intent, intent_guidance,
)
from services.topic_similarity import drop_core_repeats

research_bp = Blueprint('research', __name__)

MAX_TITLE_CATEGORY_CHARS = 200
RESEARCH_DATE_FORMAT = '%d %b %Y, %H:%M'

# Reasons a category cannot be used for title generation, shared by the
# Research page (title_block_reason) and /api/generate-titles.
TITLE_BLOCK_NO_RESEARCH = 'Belum ada riset'
TITLE_BLOCK_WEAK_EVIDENCE = 'Bukti riset belum cukup'
TITLE_BLOCK_STALE = f'Data riset sudah lebih dari {MAX_RESEARCH_AGE_DAYS} hari'

# Title generation: only the newest queue titles take part in the near-duplicate
# check (SequenceMatcher per pair is quadratic), and the model output is capped.
TITLE_DEDUPE_QUEUE_LIMIT = 300
MAX_AI_TITLES_PROCESSED = 40
MAX_TITLE_CHARS = 300
TITLE_PARSE_ERROR = 'Respons AI tidak dapat dibaca sebagai daftar judul. Silakan coba lagi.'
TITLE_QUOTA_BUCKET = 'ai_titles'
TITLE_QUOTA_LIMIT = 200

# /api/trending and /api/suggest-topics scrape Google Trends without charging,
# so each user gets a small hourly budget.
TREND_LOOKUP_RATE_LIMIT = 10
TREND_LOOKUP_RATE_WINDOW_SECONDS = 3600
# Bounded wait for the process-wide Google Trends lock (trending_research), so a
# web request cannot tie up a gunicorn thread behind research traffic.
TRENDS_WEB_LOCK_TIMEOUT_SECONDS = 20

RESEARCH_BUSY_MESSAGE = 'Riset untuk website ini masih berjalan.'
RESEARCH_STARTING_MESSAGE = 'Riset sedang dimulai, coba lagi sebentar.'
RESEARCH_UNAVAILABLE_MESSAGE = 'Layanan riset sedang tidak aktif. Hubungi admin.'

AI_BUSY_MESSAGE = 'Server Google AI sedang sibuk karena lonjakan permintaan. Silakan coba lagi beberapa saat.'

TITLE_PROMPT_EN = """Create {count} highly engaging, natural (like written by a professional journalist or blogger), click-worthy (High CTR), and SEO-optimized blog article titles for the category "{category}" on the website {site_name}. All titles MUST BE IN ENGLISH.

TITLE WRITING GUIDELINES (CRITICAL):
1. DO NOT use repetitive robotic formula formats like "[Keyword]: [Subtitle]". Create natural flowing sentences.
2. DO NOT use AI cliché words like: "Complete Guide", "Smart Solution", "Effective Strategy", "Must Know", "In the Digital Era", "Towards the Future".
3. DO NOT create titles that just define the category name itself.
4. Create titles that evoke curiosity (curiosity gap), solve practical problems, or discuss hot trends with a fresh human perspective.

Additional Context:
- Category Description: {category_desc}
- Current year: {current_year} (use this year naturally if relevant).
- Related keywords: {keywords}
- Frequently asked questions: {questions}

{evidence}
Output format must be a JSON list of strings without markdown formatting like this:
["Article Title 1", "Article Title 2", "Article Title 3"]"""

TITLE_PROMPT_ID = """Buatlah {count} judul artikel blog berbahasa INDONESIA yang sangat menarik, natural (seperti ditulis oleh jurnalis atau blogger profesional), click-worthy (High CTR), dan SEO-optimized untuk kategori "{category}" pada website {site_name}.

PANDUAN GAYA PENULISAN JUDUL (SANGAT PENTING):
1. JANGAN gunakan format formula robotik berulang seperti "[Kata Kunci]: [Sub-judul]". Buatlah kalimat mengalir yang natural.
2. JANGAN gunakan kata-kata klise AI/robotik berikut: "Panduan Lengkap", "Solusi Cerdas", "Strategi Efektif", "Era 2026", "Wajib Diketahui", "Meningkatkan Kualitas", "Di Era Digital", "Menuju Masa Depan".
3. JANGAN membuat judul berupa definisi dari nama kategori itu sendiri.
4. Buatlah judul yang mengundang rasa ingin tahu (curiosity gap), memecahkan masalah praktis, atau membahas tren hangat dengan sudut pandang manusiawi yang segar.

Konteks Tambahan:
- Deskripsi Kategori: {category_desc}
- Tahun saat ini: {current_year} (gunakan tahun ini secara natural jika relevan). Jangan gunakan tahun lama kecuali dibutuhkan sebagai konteks historis.
- Kata kunci terkait: {keywords}
- Isu/pertanyaan yang sering dicari: {questions}

{evidence}
Format output harus berupa JSON list of strings tanpa markdown formatting seperti ini:
["Judul Artikel 1", "Judul Artikel 2", "Judul Artikel 3"]"""

DEFAULT_CATEGORY_DESC = {
    'en': 'Write about specific and hot topics in this field.',
    'id': 'Tulis tentang topik-topik spesifik dan hangat di bidang ini.',
}
GSC_BLOCK_HEADER = {
    'en': ("\n\nREAL SEARCH QUERIES this site already gets impressions for. These are\n"
           "the highest-value topics; prioritise them:\n"),
    'id': ("\n\nQUERY PENCARIAN NYATA yang sudah mendatangkan impression ke situs ini.\n"
           "Ini topik paling bernilai, prioritaskan:\n"),
}
GAP_BLOCK_HEADER = {
    'en': "\n\nCONTENT GAPS - competitors cover these, this site does not:\n",
    'id': "\n\nCELAH KONTEN - dibahas kompetitor tapi belum ada di situs ini:\n",
}
# Distinct intents: every new title must answer a search none of the site's
# titles (published or queued) answers, and must not repeat the category's
# head term or a used title prefix. Generated titles that still do are dropped
# (services.topic_similarity.drop_core_repeats).
DISTINCT_INTENT_RULES = {
    'en': ("\n\nDISTINCT SEARCH INTENTS (CRITICAL):\n"
           "- Every title must answer a different search intent (a different problem, audience or question) "
           "from every other title in your list and from the existing titles below; a new angle, framing or "
           "year on the same subject is NOT a new intent.\n"
           "- Do not open a title with the category name \"{category}\" or its head term, and do not reuse "
           "the part before ':' of an existing title. Name the specific sub-topic instead.\n"
           "- Do not dress up the same subject with framing words such as guide, roadmap, blueprint, "
           "strategy, rules, steps or basics.\n"),
    'id': ("\n\nMAKSUD PENCARIAN BERBEDA (SANGAT PENTING):\n"
           "- Setiap judul wajib menjawab maksud pencarian (search intent) yang berbeda (masalah, pembaca, "
           "atau pertanyaan yang lain) dari judul lain di daftar Anda dan dari judul yang sudah ada di bawah; "
           "sudut pandang, pembingkaian, atau tahun baru untuk subjek yang sama BUKAN maksud baru.\n"
           "- Jangan membuka judul dengan nama kategori \"{category}\" atau istilah utamanya, dan jangan "
           "memakai ulang bagian sebelum ':' dari judul yang sudah ada. Sebut subtopik spesifiknya.\n"
           "- Jangan membungkus subjek yang sama dengan kata pembingkai seperti panduan, peta jalan, "
           "blueprint, strategi, siasat, aturan, langkah, atau dasar-dasar.\n"),
}
EXISTING_TITLES_HEADER = {
    'en': "\nEXISTING TITLES ON THIS SITE (published or queued) - do not repeat their topics:\n",
    'id': "\nJUDUL YANG SUDAH ADA DI SITUS INI (terbit atau dalam antrean) - jangan ulangi topiknya:\n",
}
# Existing titles listed in the title prompt (the newest published first).
MAX_PROMPT_EXISTING_TITLES = 30


class _TitleRequestError(Exception):
    """A generate-titles request that cannot proceed; carries the JSON error."""

    def __init__(self, message, status):
        super().__init__(message)
        self.message = message
        self.status = status


def _is_ai_busy_error(error):
    error_msg = str(error)
    return '503' in error_msg or 'high demand' in error_msg.lower()


def _published_titles(session, user_id, site_id, limit):
    """Titles of the site's successfully published posts, newest first."""
    return [
        row[0] for row in session.query(PostLog.title).filter(
            PostLog.user_id == user_id,
            PostLog.site_id == site_id,
            PostLog.success.is_(True)
        ).order_by(PostLog.created_at.desc()).limit(limit).all()
        if row[0]
    ]


# Columns of the previous run that _research_delta reads; its large JSON
# columns (competitors, social, news, ...) are never needed.
_PREVIOUS_RUN_COLUMNS = (
    ResearchData.id, ResearchData.category, ResearchData.keywords, ResearchData.trend_score,
    ResearchData.quality_score, ResearchData.confidence_level, ResearchData.researched_at,
    ResearchData.created_at,
)


def _latest_runs_by_category(session, user_id, site_id, category_names):
    """The latest two research runs per category (latest + previous is all the UI needs).

    Rows are ranked per category in SQL (ROW_NUMBER) instead of loading every
    run ever stored. The latest run is loaded whole; the previous one only with
    the columns the comparison uses.
    """
    runs_by_category = {}
    if not category_names:
        return runs_by_category
    ranked = session.query(
        ResearchData.id.label('id'),
        func.row_number().over(
            partition_by=ResearchData.category,
            order_by=(ResearchData.created_at.desc(), ResearchData.id.desc()),
        ).label('rn'),
    ).filter(
        ResearchData.user_id == user_id,
        ResearchData.site_id == site_id,
        ResearchData.category.in_(category_names)
    ).subquery()

    latest_runs = session.query(ResearchData).join(
        ranked, ResearchData.id == ranked.c.id
    ).filter(ranked.c.rn == 1).all()
    previous_runs = session.query(ResearchData).options(load_only(*_PREVIOUS_RUN_COLUMNS)).join(
        ranked, ResearchData.id == ranked.c.id
    ).filter(ranked.c.rn == 2).all()

    for run in latest_runs:
        runs_by_category[run.category] = [run]
    for run in previous_runs:
        if run.category in runs_by_category:
            runs_by_category[run.category].append(run)
    return runs_by_category


def _title_block_reason(latest, now=None):
    """Why titles cannot be generated from this research run, or None when they can.

    The one rule used by both the Research page and /api/generate-titles.
    """
    if latest is None:
        return TITLE_BLOCK_NO_RESEARCH
    if (latest.confidence_level or 'unknown') not in USABLE_CONFIDENCE_LEVELS:
        return TITLE_BLOCK_WEAK_EVIDENCE
    if not is_research_fresh(latest.researched_at or latest.created_at, now):
        return TITLE_BLOCK_STALE
    return None


def _research_entry(latest, previous, now):
    researched_at = latest.researched_at or latest.created_at
    # now and researched_at are both local naive time (see database.is_research_fresh).
    age_hours = max(0, int((now - researched_at).total_seconds() / 3600)) if researched_at else None
    block_reason = _title_block_reason(latest, now)
    source_metadata = latest.source_metadata if isinstance(latest.source_metadata, dict) else {}
    warnings = evidence_warnings(source_metadata)
    return {
        'trending_count': len(latest.trending_topics) if latest.trending_topics else 0,
        'rising_count': len(latest.rising_topics) if latest.rising_topics else 0,
        'top_count': len(latest.top_topics) if latest.top_topics else 0,
        'suggestions': latest.suggested_topics[:5] if latest.suggested_topics else [],
        'suggestions_count': len(latest.suggested_topics) if latest.suggested_topics else 0,
        'keywords': latest.keywords[:10] if latest.keywords else [],
        'keywords_count': len(latest.keywords) if latest.keywords else 0,
        'questions': latest.questions[:5] if latest.questions else [],
        'questions_count': len(latest.questions) if latest.questions else 0,
        'trend_score': latest.trend_score if latest.trend_score is not None else 0,
        'social_insights': latest.social_insights or [],
        'competitor_outlines': latest.competitor_outlines or [],
        'youtube_insights': latest.youtube_insights or [],
        'long_tail_keywords': latest.long_tail_keywords or [],
        'news_insights': latest.news_insights or [],
        'official_sources': latest.official_sources or [],
        'semantic_context': latest.semantic_context or '',
        'source_metadata': source_metadata,
        'quality_score': latest.quality_score or 0,
        'confidence_level': latest.confidence_level or 'unknown',
        # Which writer evidence is missing (warning) and which optional sources
        # were unavailable (information); derived from the stored provider
        # statuses so older rows get the precise wording too.
        'is_fallback': bool(warnings) if source_metadata else bool(latest.is_fallback),
        'fallback_warnings': warnings,
        'missing_optional_sources': optional_notes(source_metadata),
        'age_hours': age_hours,
        'is_stale': not is_research_fresh(researched_at, now),
        'created_at': researched_at.strftime(RESEARCH_DATE_FORMAT) if researched_at else None,
        'change_since_last_run': _research_delta(latest, previous),
        'eligible_for_titles': block_reason is None,
        'title_block_reason': block_reason,
    }


def _load_research_data(user_id, site_id, selected_categories):
    research_data = {}
    # Local naive time: the clock researched_at is written with. Comparing it with
    # UTC skewed age_hours/is_stale by the server's UTC offset.
    now = datetime.now()
    with db.get_session() as session:
        category_names = [c['name'] for c in selected_categories
                          if isinstance(c, dict) and isinstance(c.get('name'), str) and c.get('name')]
        runs_by_category = _latest_runs_by_category(session, user_id, site_id, category_names)
        # Same normalization as the research job, which saves a duplicate entry
        # ("Tips" / "tips ") under the first spelling only.
        runs_by_key = {}
        for name in category_names:
            if name in runs_by_category:
                runs_by_key.setdefault(category_key(name), runs_by_category[name])
        for name in category_names:
            runs = runs_by_category.get(name) or runs_by_key.get(category_key(name)) or []
            if runs:
                previous = runs[1] if len(runs) > 1 else None
                research_data[name] = _research_entry(runs[0], previous, now)
    return research_data


def _load_search_console_opportunities(user_id, site_id):
    """Returns (current_metrics, opportunities, error_message_or_None)."""
    try:
        with db.get_session() as session:
            current_metrics, previous_metrics = load_search_metrics(session, user_id, site_id)
            raw_opportunities = build_search_opportunities(current_metrics, previous_metrics, limit=20)
            # Each opportunity carries the action it actually calls for, so the
            # UI can distinguish "write something new" from "fix the title".
            return current_metrics, plan_from_opportunities(raw_opportunities, limit=10), None
    except SQLAlchemyError as exc:
        # Search Console is additive intelligence. A migration/runtime problem in
        # its metric store must not take the existing Research page offline.
        logger.error(f'Could not load Search Console metrics for site_id={site_id}: {exc}')
        return [], [], 'Data Search Console belum tersedia. Coba sinkronkan kembali.'


def _annotate_research_data(user_id, site_id, research_data, current_metrics):
    """Add content gaps, keyword demand and search intent to each category entry.

    Content gaps are competitor subtopics we have never published about; they
    use data already stored on both sides.
    """
    try:
        with db.get_session() as session:
            published_titles = _published_titles(session, user_id, site_id, 200)
        demand = keyword_demand_map(current_metrics)
        for name, entry in research_data.items():
            entry['content_gaps'] = find_content_gaps(
                entry.get('competitor_outlines'), published_titles
            )
            entry['keywords'] = annotate_keywords_with_demand(entry.get('keywords'), demand)
            entry['intent'] = classify_intent(name)
    except SQLAlchemyError as exc:
        logger.error(f'Could not build content gaps for site_id={site_id}: {exc}')


@research_bp.route('/api/research_data')
@require_jwt
def api_research(user_id):
    """Trending topics research page"""
    site_id = request.args.get('site_id', type=int)
    if not site_id:
        return jsonify({'success': False, 'error': 'site_id wajib diisi.', 'code': 400}), 400

    with db.get_session() as session:
        site = session.query(WordPressSite).filter_by(id=site_id, user_id=user_id).first()
        if not site:
            return jsonify({'success': False, 'error': 'Website tidak ditemukan.', 'code': 404}), 404

        selected_categories = site.selected_categories or []
        # Snapshot these values while the ORM instance is still attached. The
        # response is assembled after other sessions have committed and closed.
        gsc_connected = bool(site.gsc_refresh_token)
        gsc_property_url = site.gsc_property_url
        gsc_last_synced_at = site.gsc_last_synced_at

    research_data = _load_research_data(user_id, site_id, selected_categories)
    current_metrics, gsc_opportunities, gsc_metrics_error = _load_search_console_opportunities(user_id, site_id)
    _annotate_research_data(user_id, site_id, research_data, current_metrics)

    return jsonify({
        'success': True,
        'categories': selected_categories,
        'research_data': research_data,
        'search_console': {
            'connected': gsc_connected,
            'property_url': gsc_property_url,
            'last_synced_at': gsc_last_synced_at.isoformat() if gsc_last_synced_at else None,
            'opportunities': gsc_opportunities,
            'topic_candidates': topic_candidates_from_opportunities(gsc_opportunities),
            'error': gsc_metrics_error,
        },
    })


def _research_delta(latest, previous):
    """Compare two already-loaded research runs.

    Takes the ORM rows rather than fetching them, so the caller can load every
    category's runs in a single query.
    """
    if not latest or not previous:
        return None

    def keyword_set(run):
        return {
            str(k.get('keyword') if isinstance(k, dict) else k).lower()
            for k in (run.keywords or [])
        }

    latest_kw = keyword_set(latest)
    previous_kw = keyword_set(previous)

    return {
        'trend_score_change': (latest.trend_score or 0) - (previous.trend_score or 0),
        'quality_score_change': (latest.quality_score or 0) - (previous.quality_score or 0),
        'new_keywords': sorted(latest_kw - previous_kw)[:5],
        'lost_keywords': sorted(previous_kw - latest_kw)[:5],
        'previous_confidence': previous.confidence_level,
        'previous_researched_at': (
            previous.researched_at.strftime(RESEARCH_DATE_FORMAT)
            if previous.researched_at else None
        ),
    }


def _normalize_title(title):
    text = re.sub(r'\d+', '', (title or '').lower())
    text = re.sub(r'[^\w\s]', ' ', text)
    return ' '.join(text.split())


def _filter_duplicate_titles(candidates, existing_titles, threshold=0.72):
    """Drop candidate titles too similar to existing ones, or to each other."""
    normalized_existing = [_normalize_title(t) for t in existing_titles if t]
    kept = []
    kept_normalized = []
    for title in candidates:
        norm = _normalize_title(title)
        if not norm:
            continue
        pool = normalized_existing + kept_normalized
        if any(SequenceMatcher(None, norm, other).ratio() >= threshold for other in pool):
            logger.info(f"Skipping near-duplicate title: {title}")
            continue
        kept.append(title)
        kept_normalized.append(norm)
    return kept


def _site_language(user_id, site_id):
    language = 'id'
    with db.get_session() as session:
        site = session.query(WordPressSite).filter_by(id=site_id, user_id=user_id).first()
        if site:
            language = site.language or 'id'
    return language


def _trend_lookup_limited(user_id):
    """429 response when the user exhausted the hourly trend lookup budget, else None."""
    allowed, retry_sec = rate_limit.hit(
        f'ratelimit:trend_lookup:{user_id}', TREND_LOOKUP_RATE_LIMIT, TREND_LOOKUP_RATE_WINDOW_SECONDS
    )
    if allowed:
        return None
    return jsonify({
        'success': False,
        'error': f'Terlalu banyak permintaan tren. Coba lagi dalam {retry_sec // 60 + 1} menit.'
    }), 429


@research_bp.route('/api/trending/<path:category>')
@require_jwt
def get_trending(user_id, category):
    """API endpoint to get trending topics for a category"""
    if not category.strip() or len(category) > MAX_TITLE_CATEGORY_CHARS:
        return jsonify({'success': False, 'error': 'Kategori tidak valid.'}), 400
    limited = _trend_lookup_limited(user_id)
    if limited:
        return limited
    site_id = request.args.get('site_id', type=int)
    language = _site_language(user_id, site_id) if site_id else 'id'
    try:
        data = trending.get_trending_topics(category, limit=15, language=language,
                                            lock_timeout=TRENDS_WEB_LOCK_TIMEOUT_SECONDS)
        return jsonify(data)
    except Exception as e:
        logger.error(f"Trending API error: {e}")
        if _is_ai_busy_error(e):
            return jsonify({'error': AI_BUSY_MESSAGE}), 500
        return jsonify({'error': 'Gagal mengambil topik trending. Silakan coba lagi.'}), 500


@research_bp.route('/api/suggest-topics', methods=['POST'])
@require_jwt
def suggest_topics(user_id):
    """API endpoint to suggest article topics"""
    try:
        data = request.get_json(silent=True) or {}
        category = data.get('category')
        if not isinstance(category, str) or not category.strip() or len(category) > MAX_TITLE_CATEGORY_CHARS:
            return jsonify({'success': False, 'error': 'Kategori wajib diisi.'}), 400
        limited = _trend_lookup_limited(user_id)
        if limited:
            return limited
        try:
            count = min(max(int(data.get('count', 5)), 1), 20)
        except (TypeError, ValueError):
            count = 5
        site_id = data.get('site_id') or request.args.get('site_id')
        language = 'id'
        if site_id:
            try:
                site_id = int(site_id)
            except (TypeError, ValueError):
                return jsonify({'success': False, 'error': 'site_id tidak valid.'}), 400
            language = _site_language(user_id, site_id)

        suggestions = trending.suggest_article_topics(category, count, language=language,
                                                     lock_timeout=TRENDS_WEB_LOCK_TIMEOUT_SECONDS)
        return jsonify({'suggestions': suggestions})
    except Exception as e:
        logger.error(f"Suggest topics error: {e}")
        if _is_ai_busy_error(e):
            return jsonify({'error': AI_BUSY_MESSAGE}), 500
        return jsonify({'error': 'Gagal mengambil saran topik. Silakan coba lagi.'}), 500


def _redis():
    # Looked up at call time so tests can patch core_extensions.redis_conn.
    return getattr(core_extensions, 'redis_conn', None)


def _research_queue():
    return getattr(core_extensions, 'research_q', None)


def _rq_job_status(job_id):
    """RQ status of job_id as a string, 'missing' when the job no longer exists."""
    try:
        job = Job.fetch(job_id, connection=_redis())
    except NoSuchJobError:
        return 'missing'
    status = job.get_status(refresh=True)
    return str(getattr(status, 'value', status) or 'missing')


def _research_lock_state(site_id):
    """(state, job_id) of the site's research lock (database.research_lock_state)."""
    return research_lock_state(_redis(), site_id, _rq_job_status)


def _research_workers_available():
    """False only when RQ positively reports no worker listening on the research queue.

    A failure of the introspection itself does not block research: monitoring
    trouble must not take the feature down.
    """
    try:
        from rq import Worker
        return Worker.count(connection=_redis(), queue=_research_queue()) > 0
    except Exception as e:
        logger.warning(f"Could not count research workers: {e}")
        return True


def _research_busy_response(state, job_id):
    if state == LOCK_STARTING or not job_id:
        # The other request is still enqueueing its job; there is no job to poll yet.
        return jsonify({'success': False, 'error': RESEARCH_STARTING_MESSAGE}), 409
    return jsonify({'success': False, 'error': RESEARCH_BUSY_MESSAGE, 'job_id': job_id}), 409


def _bad_request(message):
    return jsonify({'success': False, 'error': message, 'code': 400}), 400


def _manual_research_params():
    """Returns (site_id, category, error_response); category None means every selected category.

    site_id and category are each read from the query string or, independently,
    from the JSON body. A missing or empty category means "all categories"; no
    category name (not even "all") is special.
    """
    body = request.get_json(silent=True)
    body = body if isinstance(body, dict) else {}
    site_id = request.args.get('site_id') or body.get('site_id')
    category = request.args.get('category') if 'category' in request.args else body.get('category')

    if not site_id:
        return None, None, _bad_request('site_id wajib diisi.')
    try:
        site_id = int(site_id)
    except (TypeError, ValueError):
        return None, None, _bad_request('Format site_id tidak valid.')
    if category is not None and not isinstance(category, str):
        return None, None, _bad_request('Kategori tidak valid.')
    category = (category or '').strip() or None
    if category and len(category) > MAX_TITLE_CATEGORY_CHARS:
        return None, None, _bad_request('Kategori tidak valid.')
    return site_id, category, None


def _research_charge_plan(user_id, site_id, category):
    """Returns ((category_name, required_credits), None) or (None, error_response).

    category_name is the site's own spelling of the requested category (None for
    all). The job researches each normalized name (database.category_key) once,
    so the charge is one credit per unique normalized name.
    """
    with db.get_session() as session:
        site = session.query(WordPressSite).filter_by(id=site_id, user_id=user_id).first()
        if not site:
            return None, (jsonify({'success': False, 'error': 'Website tidak ditemukan.'}), 404)
        user = session.query(User).filter_by(id=user_id).first()
        if not user:
            return None, (jsonify({'success': False, 'error': 'Pengguna tidak ditemukan.'}), 404)

        names_by_key = {}
        for cat in site.selected_categories or []:
            name = cat.get('name') if isinstance(cat, dict) else None
            if isinstance(name, str) and name.strip():
                names_by_key.setdefault(category_key(name), name)
        user_credits = user.credits if user.credits is not None else 0

    if not names_by_key:
        return None, _bad_request('Silakan pilih kategori target terlebih dahulu di Pengaturan Website.')
    if category:
        category_name = names_by_key.get(category_key(category))
        if category_name is None:
            return None, _bad_request(f'Kategori "{category}" tidak terpilih untuk website ini.')
        required_credits = 1
    else:
        category_name = None
        required_credits = len(names_by_key)

    if user_credits < required_credits:
        return None, _bad_request(
            f'Kredit tidak mencukupi. Riset membutuhkan {required_credits} kredit, '
            f'tetapi Anda hanya memiliki {user_credits} kredit.'
        )
    return (category_name, required_credits), None


def _current_credits(user_id):
    with db.get_session() as session:
        user = session.query(User).filter_by(id=user_id).first()
        return max(0, user.credits or 0) if user else 0


def _undo_research_reservation(conn, user_id, site_id, job_id, amount):
    """Refund a reservation whose job was never enqueued, and release the lock.

    The reservation record is taken first so the dispatcher's reconciliation
    cannot refund it a second time.
    """
    record = None
    try:
        record = take_research_charge(conn, job_id)
    except Exception as e:
        logger.warning(f"Could not remove research reservation {job_id}: {e}")
    try:
        db.refund_user_credits(user_id, amount)
    except Exception:
        if record is not None:
            # Hand the reservation back to the dispatcher's reconciliation.
            restore_research_charge(conn, job_id, record, owed=amount)
        raise
    finally:
        try:
            release_research_lock(conn, site_id, job_id)
        except Exception as e:
            logger.warning(f"Could not release the research lock of site {site_id}: {e}")


def _start_manual_research(user_id, site_id, category_name, required_credits):
    """Lock the site, reserve credits, record the reservation and enqueue the job."""
    conn = _redis()
    job_id = f"research-{site_id}-{uuid.uuid4().hex}"
    # The timeout must be explicit: RQ's 180s default kills a multi-category
    # run after the first category or two (each takes roughly 20-30s).
    timeout_seconds = research_job_timeout(required_credits)

    # One research run per site. The lock is taken before any credit is reserved,
    # so a second click is answered with 409 without charging. It stays busy for
    # as long as its job is queued or running, however long the queue is.
    state, holder = _research_lock_state(site_id)
    if state != LOCK_FREE:
        return _research_busy_response(state, holder)
    if not acquire_research_lock(conn, site_id, job_id, ttl_seconds=research_lock_ttl(required_credits)):
        return _research_busy_response(*_research_lock_state(site_id))

    try:
        reserved = db.reserve_user_credits(user_id, required_credits)
    except Exception:
        release_research_lock(conn, site_id, job_id)
        raise
    if not reserved:
        release_research_lock(conn, site_id, job_id)
        return _bad_request(f'Kredit tidak mencukupi. Riset membutuhkan {required_credits} kredit.')

    try:
        # Recorded before enqueueing: if the job is later killed without running
        # its own refund, the dispatcher refunds from this record.
        record_research_charge(conn, job_id, user_id, site_id, required_credits, timeout_seconds)
        _research_queue().enqueue(
            'tasks.research_jobs.deep_research_job',
            user_id, True, site_id, category_name,
            charged_credits=required_credits,
            charge_recorded=True,
            job_timeout=timeout_seconds,
            job_id=job_id,
        )
    except Exception as enqueue_error:
        _undo_research_reservation(conn, user_id, site_id, job_id, required_credits)
        logger.error(f"Manual research enqueue failed, refunded {required_credits} credits: {enqueue_error}")
        return jsonify({'success': False, 'error': 'Gagal memasukkan riset ke antrean. Kredit sudah dikembalikan.'}), 500

    return jsonify({
        'success': True,
        'job_id': job_id,
        'message': f'Riset berhasil masuk antrean. {required_credits} kredit didebit.',
        'credits_deducted': required_credits,
        # Read after the reservation, so concurrent spending is reflected.
        'remaining_credits': _current_credits(user_id),
    })


@research_bp.route('/manual-research', methods=['POST'])
@require_jwt
def manual_research(user_id):
    site_id, category, error = _manual_research_params()
    if error:
        return error
    try:
        plan, error = _research_charge_plan(user_id, site_id, category)
        if error:
            return error
        category_name, required_credits = plan
        if not _research_workers_available():
            # Without a worker the job would wait forever with the credits held.
            return jsonify({'success': False, 'error': RESEARCH_UNAVAILABLE_MESSAGE}), 503
        return _start_manual_research(user_id, site_id, category_name, required_credits)
    except Exception as e:
        logger.error(f"Manual research error: {e}")
        return jsonify({'success': False, 'error': 'Terjadi kesalahan saat memulai riset.'}), 500


@research_bp.route('/api/research/active')
@require_jwt
def active_research(user_id):
    """The research job currently queued or running for one of the user's sites."""
    site_id = request.args.get('site_id', type=int)
    if not site_id:
        return _bad_request('site_id wajib diisi.')
    with db.get_session() as session:
        site_exists = session.query(WordPressSite.id).filter_by(id=site_id, user_id=user_id).first() is not None
    if not site_exists:
        return jsonify({'success': False, 'error': 'Website tidak ditemukan.', 'code': 404}), 404
    try:
        state, job_id = _research_lock_state(site_id)
        if state != LOCK_ACTIVE:
            job_id = None  # a job still being enqueued has nothing to poll yet
    except Exception as e:
        logger.error(f"Could not read the research lock of site {site_id}: {e}")
        return jsonify({'success': False, 'error': 'Status riset tidak dapat diperiksa saat ini.'}), 503
    return jsonify({'success': True, 'job_id': job_id})


def _load_title_context(user_id, site_id, category):
    """Validate the site and its latest research for category; raise _TitleRequestError if unusable.

    The error is raised after the session closes: raising inside get_session()
    would log an ordinary validation failure as a database error.
    """
    with db.get_session() as session:
        context, error = _read_title_context(session, user_id, site_id, category)
    if error:
        raise _TitleRequestError(*error)
    return context


def _read_title_context(session, user_id, site_id, category):
    """Returns (context, None) or (None, (message, status))."""
    site = session.query(WordPressSite).filter_by(id=site_id, user_id=user_id).first()
    if not site:
        return None, ('Website tidak ditemukan.', 404)

    # Research is saved under the site's first spelling of a category
    # (normalized with database.category_key), so resolve to that spelling.
    for cat in site.selected_categories or []:
        name = cat.get('name') if isinstance(cat, dict) else None
        if isinstance(name, str) and category_key(name) == category_key(category):
            category = name
            break

    latest = session.query(ResearchData).filter(
        ResearchData.user_id == user_id,
        ResearchData.site_id == site_id,
        ResearchData.category == category
    ).order_by(ResearchData.created_at.desc()).first()

    if not latest:
        return None, ('Jalankan riset berkualitas terlebih dahulu.', 400)
    # Same rule as eligible_for_titles on the Research page.
    reason = _title_block_reason(latest)
    if reason:
        return None, (f'Tidak aman membuat judul dari data ini: {reason.lower()}. Silakan riset ulang.', 400)

    category_desc = ""
    for cat in (site.categories or []):
        if isinstance(cat, dict) and cat.get('name') == category:
            # Writing notes left in the public description ("(Fokus Tambahan:
            # ...)") are dropped; the private per-category AI hint is added.
            category_desc = public_category_description(cat.get('description'))[:1000]
            hint = ' '.join(str(cat.get('ai_hint') or '').split())[:1000]
            if hint:
                label = "Publisher's private instructions" if site.language == 'en' else 'Instruksi pribadi penerbit'
                category_desc = (category_desc + f"\n- {label}: {hint}").strip()
            break

    return {
        'category': category,
        'keywords': latest.keywords or [],
        'questions': latest.questions or [],
        'competitor_outlines': latest.competitor_outlines or [],
        'site_name': site.site_name,
        'language': site.language or 'id',
        'category_desc': category_desc,
    }, None


def _title_evidence(user_id, site_id, competitor_outlines, category=None):
    """Search Console quick wins and content gaps to steer the title prompt.

    Search Console queries are the strongest topic signal available: real
    searches that already produced impressions for this exact site. They are
    site-wide, so only queries relevant to this category are used.
    """
    gsc_topics = []
    content_gaps = []
    try:
        with db.get_session() as session:
            current_rows, previous_rows = load_search_metrics(session, user_id, site_id)
            opportunities = filter_opportunities_for_topic(
                build_search_opportunities(current_rows, previous_rows, limit=100),
                # The category name only: a free-text description is too broad.
                category,
            )
            gsc_topics = topic_candidates_from_opportunities(opportunities, limit=6)
            published_titles = _published_titles(session, user_id, site_id, 200)
        content_gaps = find_content_gaps(competitor_outlines, published_titles, limit=5)
    except SQLAlchemyError as exc:
        logger.error(f'Could not load search evidence for titles (site_id={site_id}): {exc}')
    return gsc_topics, content_gaps


def _title_evidence_blocks(category, language, gsc_topics, content_gaps):
    lang = 'en' if language == 'en' else 'id'
    gsc_block = ""
    if gsc_topics:
        lines = "\n".join(
            f"- \"{t['query']}\" ({int(t['impressions'] or 0)} impressions, posisi {t['position']})"
            for t in gsc_topics
        )
        gsc_block = GSC_BLOCK_HEADER[lang] + lines + "\n"

    gap_block = ""
    if content_gaps:
        lines = "\n".join(f"- {g['topic']}" for g in content_gaps)
        gap_block = GAP_BLOCK_HEADER[lang] + lines + "\n"

    category_intent = classify_intent(category)
    intent_block = f"\n\nSEARCH INTENT: {category_intent}. {intent_guidance(category_intent, language)}\n"
    return gsc_block + gap_block + intent_block


def _distinct_intent_block(category, language, existing_titles):
    """Rules for distinct intents plus the site's existing titles (newest first)."""
    lang = 'en' if language == 'en' else 'id'
    block = DISTINCT_INTENT_RULES[lang].format(category=category)
    listed, seen = [], set()
    for title in existing_titles or []:
        title = ' '.join(str(title or '').split())
        if title and title.lower() not in seen:
            seen.add(title.lower())
            listed.append(title)
        if len(listed) >= MAX_PROMPT_EXISTING_TITLES:
            break
    if listed:
        block += EXISTING_TITLES_HEADER[lang] + "\n".join(f"- {title}" for title in listed) + "\n"
    return block


def _build_title_prompt(count, category, context, evidence):
    lang = 'en' if context['language'] == 'en' else 'id'
    template = TITLE_PROMPT_EN if lang == 'en' else TITLE_PROMPT_ID
    keywords = context['keywords']
    questions = context['questions']
    return template.format(
        count=count,
        category=category,
        site_name=context['site_name'],
        category_desc=context['category_desc'] or DEFAULT_CATEGORY_DESC[lang],
        current_year=datetime.now().year,
        keywords=', '.join(keywords[:5]) if keywords else category,
        questions=', '.join(questions[:3]) if questions else '',
        evidence=evidence,
    )


class _TitleParseError(ValueError):
    """The model output contained no JSON array of titles."""


def _json_arrays(text):
    """Every JSON array in text, in order, tolerating code fences and prose around it."""
    text = str(text or '')
    decoder = json.JSONDecoder()
    for match in re.finditer(r'\[', text):
        try:
            value, _ = decoder.raw_decode(text, match.start())
        except ValueError:
            continue
        if isinstance(value, list):
            yield value


def _titles_from_array(items):
    titles = []
    for item in items:
        if isinstance(item, dict):
            item = item.get('title') or item.get('judul')
        if not isinstance(item, str):
            continue
        title = ' '.join(item.split())
        if title and len(title) <= MAX_TITLE_CHARS:
            titles.append(title)
    return list(dict.fromkeys(titles))[:MAX_AI_TITLES_PROCESSED]


def _parse_title_response(text):
    """Unique titles from the first JSON array of titles in the model output.

    At most MAX_AI_TITLES_PROCESSED. Raises _TitleParseError when there is none.
    """
    for items in _json_arrays(text):
        titles = _titles_from_array(items)
        if titles:
            return titles
    raise _TitleParseError('Respons AI tidak berisi daftar judul JSON.')


def _refund_title_quota(user_id):
    """Give back the ai_titles quota a request used when the model output was unusable."""
    conn = _redis()
    if conn is None:
        return
    key = f'ratelimit:{TITLE_QUOTA_BUCKET}:{user_id}'
    try:
        # Never below zero: users with their own AI key are not counted at all.
        conn.eval(
            "local v = tonumber(redis.call('GET', KEYS[1]) or '0') "
            "if v > 0 then return redis.call('DECR', KEYS[1]) end return v",
            1, key,
        )
    except Exception as e:
        logger.warning(f"Could not refund the title quota of user {user_id}: {e}")


def _existing_site_titles(user_id, site_id):
    """Recent titles this site already has queued or published, across all categories.

    Two categories can otherwise produce near-identical titles that end up
    competing with each other. Failed queue items are left out (they never went
    out), and only the newest queue titles are compared: the near-duplicate
    check is pairwise, and the whole queue history made it grow without bound.
    Published titles come first (newest first): the title prompt lists the
    head of this list.
    """
    with db.get_session() as session:
        existing = _published_titles(session, user_id, site_id, 300)
        existing += [
            row[0] for row in session.query(ContentQueue.title).filter(
                ContentQueue.user_id == user_id,
                ContentQueue.site_id == site_id,
                ContentQueue.status != 'failed',
            ).order_by(ContentQueue.created_at.desc()).limit(TITLE_DEDUPE_QUEUE_LIMIT).all() if row[0]
        ]
    return existing


def _drop_core_repeats(titles, existing_titles, category, language):
    """Titles whose core topic repeats an existing title, another new title or
    just the category's head term are dropped (see topic_similarity)."""
    kept, dropped = drop_core_repeats(titles, existing_titles, language=language, category=category)
    for title in dropped:
        logger.info(f"Skipping title repeating an existing core topic or the category: {title}")
    return kept


def _queue_titles(user_id, site_id, category, titles, keywords):
    """Add titles to the queue. Returns how many were queued."""
    with db.get_session() as session:
        for title in titles:
            session.add(ContentQueue(
                user_id=user_id,
                site_id=site_id,
                category=category,
                title=title,
                target_keywords=', '.join(keywords[:5]) if keywords else category,
                status='pending'
            ))
        session.commit()
    return len(titles)


def _title_request_params(category):
    """Returns (count, site_id, error_response)."""
    data = request.get_json(silent=True)
    data = data if isinstance(data, dict) else {}
    try:
        count = min(max(int(data.get('count', 5)), 1), 20)
    except (TypeError, ValueError):
        count = 5
    site_id = data.get('site_id') or request.args.get('site_id')
    if not site_id:
        return None, None, _bad_request('site_id wajib diisi.')
    try:
        site_id = int(site_id)
    except (TypeError, ValueError):
        return None, None, _bad_request('Format site_id tidak valid.')
    if not category.strip() or len(category) > MAX_TITLE_CATEGORY_CHARS:
        return None, None, _bad_request('Kategori tidak valid.')
    return count, site_id, None


# <path:category>: a category name may contain "/" (e.g. "Hukum/Perdata"), which
# the default converter rejected with a 404.
@research_bp.route('/api/generate-titles/<path:category>', methods=['POST'])
@require_jwt
def generate_titles(user_id, category):
    count, site_id, error = _title_request_params(category)
    if error:
        return error

    config = {}
    try:
        try:
            context = _load_title_context(user_id, site_id, category)
        except _TitleRequestError as exc:
            return jsonify({'success': False, 'error': exc.message}), exc.status
        category = context['category']

        # Only gate (and count) the uncharged AI call once the request is
        # otherwise valid. Bulk generation sends one request per category, so
        # titles get their own, larger bucket instead of sharing the prompt
        # optimizer's.
        quota_error = check_ai_helper_quota(user_id, bucket=TITLE_QUOTA_BUCKET, limit=TITLE_QUOTA_LIMIT)
        if quota_error:
            return quota_error
        config = load_config(user_id)

        gsc_topics, content_gaps = _title_evidence(user_id, site_id, context['competitor_outlines'], category)
        existing_titles = _existing_site_titles(user_id, site_id)
        evidence = (_title_evidence_blocks(category, context['language'], gsc_topics, content_gaps)
                    + _distinct_intent_block(category, context['language'], existing_titles))
        prompt = _build_title_prompt(count, category, context, evidence)

        generator = ArticleGenerator.from_config(config)
        try:
            titles = _parse_title_response(generator.generate_text(prompt))
        except _TitleParseError as parse_error:
            # The model answered but not with a usable list: not the user's fault,
            # so the request does not count against their title quota.
            logger.warning(f"Unusable title response for user {user_id}: {parse_error}")
            _refund_title_quota(user_id)
            return jsonify({'success': False, 'error': TITLE_PARSE_ERROR}), 502

        titles = _filter_duplicate_titles(titles, existing_titles)
        titles = _drop_core_repeats(titles, existing_titles, category, context['language'])[:count]
        if not titles:
            return jsonify({
                'success': False,
                'error': 'Semua judul yang dihasilkan terlalu mirip dengan yang sudah ada. Coba riset ulang atau ganti kategori.'
            }), 409

        queued = _queue_titles(user_id, site_id, category, titles, context['keywords'])
        return jsonify({
            'success': True,
            'queued': queued,
            'message': f'{queued} judul berhasil dibuat dan dimasukkan ke antrean!',
        })
    except Exception as e:
        logger.error(f"Generate titles error: {e}")
        reason = describe_provider_error(e, text_provider_name(config or {})) or 'terjadi kesalahan, silakan coba lagi.'
        return jsonify({'success': False, 'error': f'Gagal membuat judul: {reason}'}), 500


@research_bp.route('/api/clear-research', methods=['POST'])
@require_jwt
def clear_research(user_id):
    try:
        data = request.get_json(silent=True)
        data = data if isinstance(data, dict) else {}
        site_id = data.get('site_id')
        if site_id is None or site_id == '':
            return _bad_request('site_id wajib diisi.')
        try:
            site_id = int(site_id)
        except (TypeError, ValueError):
            return _bad_request('Format site_id tidak valid.')

        with db.get_session() as session:
            deleted_count = session.query(ResearchData).filter_by(site_id=site_id, user_id=user_id).delete()
            session.commit()

        return jsonify({
            'success': True,
            'message': f'Berhasil membersihkan {deleted_count} data riset.'
        })
    except Exception as e:
        logger.error(f"Clear research error: {e}")
        return jsonify({'success': False, 'error': 'Gagal menghapus data riset. Silakan coba lagi.'}), 500
