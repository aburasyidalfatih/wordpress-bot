import json
import re
from difflib import SequenceMatcher
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify
from sqlalchemy.exc import SQLAlchemyError

from core_extensions import db, q, trending, logger, load_config, require_jwt
from routes.prompts import check_ai_helper_quota
from config import DEFAULT_GEMINI_MODEL, DEFAULT_GEMINI_IMAGE_MODEL
from database import MAX_RESEARCH_AGE_DAYS, USABLE_CONFIDENCE_LEVELS
from models import ContentQueue, PostLog, ResearchData, User, WordPressSite
from services.article_generator import ArticleGenerator
from services.search_console import build_search_opportunities
from services.content_planner import (
    load_search_metrics, plan_from_opportunities, topic_candidates_from_opportunities,
    keyword_demand_map, annotate_keywords_with_demand,
    find_content_gaps, classify_intent, intent_guidance,
)

research_bp = Blueprint('research', __name__)

# Generous per-category budget: a category can spend ~20-30s across Trends,
# autocomplete, competitor scraping, social, YouTube and news, and a slow or
# rate-limited provider stretches that further.
RESEARCH_SECONDS_PER_CATEGORY = 180
RESEARCH_MIN_TIMEOUT_SECONDS = 600
MAX_TITLE_CATEGORY_CHARS = 200
STALE_RESEARCH_HOURS = 168
RESEARCH_DATE_FORMAT = '%d %b %Y, %H:%M'

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


def _latest_runs_by_category(session, user_id, site_id, category_names):
    """The latest two research runs per category, loaded in ONE query."""
    runs_by_category = {}
    if not category_names:
        return runs_by_category
    all_runs = session.query(ResearchData).filter(
        ResearchData.user_id == user_id,
        ResearchData.site_id == site_id,
        ResearchData.category.in_(category_names)
    ).order_by(ResearchData.created_at.desc()).all()
    for run in all_runs:
        bucket = runs_by_category.setdefault(run.category, [])
        if len(bucket) < 2:  # latest + previous is all the UI needs
            bucket.append(run)
    return runs_by_category


def _research_entry(latest, previous, now):
    researched_at = latest.researched_at or latest.created_at
    age_hours = max(0, int((now - researched_at).total_seconds() / 3600)) if researched_at else None
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
        'semantic_context': latest.semantic_context or '',
        'source_metadata': latest.source_metadata or {},
        'quality_score': latest.quality_score or 0,
        'confidence_level': latest.confidence_level or 'unknown',
        'is_fallback': bool(latest.is_fallback),
        'age_hours': age_hours,
        'is_stale': age_hours is not None and age_hours > STALE_RESEARCH_HOURS,
        'created_at': researched_at.strftime(RESEARCH_DATE_FORMAT) if researched_at else None,
        'change_since_last_run': _research_delta(latest, previous),
    }


def _load_research_data(user_id, site_id, selected_categories):
    research_data = {}
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with db.get_session() as session:
        category_names = [c['name'] for c in selected_categories if c.get('name')]
        runs_by_category = _latest_runs_by_category(session, user_id, site_id, category_names)
        for category in selected_categories:
            runs = runs_by_category.get(category['name']) or []
            if runs:
                previous = runs[1] if len(runs) > 1 else None
                research_data[category['name']] = _research_entry(runs[0], previous, now)
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


@research_bp.route('/api/trending/<category>')
@require_jwt
def get_trending(user_id, category):
    """API endpoint to get trending topics for a category"""
    site_id = request.args.get('site_id', type=int)
    language = _site_language(user_id, site_id) if site_id else 'id'
    try:
        data = trending.get_trending_topics(category, limit=15, language=language)
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
        if not isinstance(category, str) or not category.strip() or len(category) > 200:
            return jsonify({'success': False, 'error': 'Kategori wajib diisi.'}), 400
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

        suggestions = trending.suggest_article_topics(category, count, language=language)
        return jsonify({'suggestions': suggestions})
    except Exception as e:
        logger.error(f"Suggest topics error: {e}")
        if _is_ai_busy_error(e):
            return jsonify({'error': AI_BUSY_MESSAGE}), 500
        return jsonify({'error': 'Gagal mengambil saran topik. Silakan coba lagi.'}), 500


@research_bp.route('/manual-research', methods=['POST'])
@require_jwt
def manual_research(user_id):
    site_id = request.args.get('site_id')
    category = request.args.get('category')
    if not site_id and request.is_json:
        data = request.get_json(silent=True) or {}
        site_id = data.get('site_id')
        category = data.get('category')

    if not site_id:
        return jsonify({'success': False, 'error': 'site_id wajib diisi.', 'code': 400}), 400

    if category in ("", "all", "All"):
        category = None

    try:
        try:
            site_id_int = int(site_id)
        except (TypeError, ValueError):
            return jsonify({'success': False, 'error': 'Format site_id tidak valid.'}), 400

        with db.get_session() as session:
            site = session.query(WordPressSite).filter_by(id=site_id_int, user_id=user_id).first()
            if not site:
                return jsonify({'success': False, 'error': 'Website tidak ditemukan.'}), 404

            user = session.query(User).filter_by(id=user_id).first()
            if not user:
                return jsonify({'success': False, 'error': 'Pengguna tidak ditemukan.'}), 404

            # The research job researches each category name once, so charge per
            # unique name; duplicate entries must not be billed twice.
            selected_category_names = list(dict.fromkeys(
                cat.get('name') for cat in (site.selected_categories or [])
                if isinstance(cat, dict) and isinstance(cat.get('name'), str) and cat.get('name')
            ))
            if not selected_category_names:
                return jsonify({'success': False, 'error': 'Silakan pilih kategori target terlebih dahulu di Pengaturan Website.'}), 400

            if category:
                if not isinstance(category, str) or category not in selected_category_names:
                    return jsonify({'success': False, 'error': f'Kategori "{category}" tidak terpilih untuk website ini.'}), 400
                required_credits = 1
            else:
                required_credits = len(selected_category_names)

            user_credits = user.credits if user.credits is not None else 0
            if user_credits < required_credits:
                return jsonify({
                    'success': False,
                    'error': f'Kredit tidak mencukupi. Riset membutuhkan {required_credits} kredit, tetapi Anda hanya memiliki {user_credits} kredit.'
                }), 400

        if not db.reserve_user_credits(user_id, required_credits):
            return jsonify({
                'success': False,
                'error': f'Kredit tidak mencukupi. Riset membutuhkan {required_credits} kredit.'
            }), 400

        # Enqueue outside the validation query. If Redis/RQ fails, refund the user.
        # The timeout must be explicit: RQ's 180s default kills a multi-category
        # run after the first category or two (each takes roughly 20-30s).
        timeout_seconds = max(
            RESEARCH_MIN_TIMEOUT_SECONDS,
            required_credits * RESEARCH_SECONDS_PER_CATEGORY
        )
        try:
            job = q.enqueue(
                'tasks.research_jobs.deep_research_job',
                user_id, True, site_id_int, category,
                charged_credits=required_credits,
                job_timeout=timeout_seconds
            )
        except Exception as enqueue_error:
            db.refund_user_credits(user_id, required_credits)
            logger.error(f"Manual research enqueue failed, refunded {required_credits} credits: {enqueue_error}")
            return jsonify({'success': False, 'error': 'Gagal memasukkan riset ke antrean. Kredit sudah dikembalikan.'}), 500

        return jsonify({
            'success': True,
            'job_id': job.id,
            'message': f'Riset berhasil masuk antrean. {required_credits} kredit didebit.',
            'credits_deducted': required_credits,
            'remaining_credits': max(0, user_credits - required_credits)
        })
    except Exception as e:
        logger.error(f"Manual research error: {e}")
        return jsonify({'success': False, 'error': 'Terjadi kesalahan saat memulai riset.'}), 500


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

    latest = session.query(ResearchData).filter(
        ResearchData.user_id == user_id,
        ResearchData.site_id == site_id,
        ResearchData.category == category
    ).order_by(ResearchData.created_at.desc()).first()

    if not latest:
        return None, ('Jalankan riset berkualitas terlebih dahulu.', 400)
    confidence = latest.confidence_level or 'unknown'
    research_time = latest.researched_at or latest.created_at
    age_days = (datetime.now() - research_time).days if research_time else 999
    if confidence not in USABLE_CONFIDENCE_LEVELS or age_days > MAX_RESEARCH_AGE_DAYS:
        reason = ('bukti riset belum terverifikasi' if confidence not in USABLE_CONFIDENCE_LEVELS
                  else f'data riset sudah lebih dari {MAX_RESEARCH_AGE_DAYS} hari')
        return None, (f'Tidak aman membuat judul dari data ini: {reason}. Silakan riset ulang.', 400)

    category_desc = ""
    for cat in (site.categories or []):
        if isinstance(cat, dict) and cat.get('name') == category:
            category_desc = str(cat.get('description') or '')[:1000]
            break

    return {
        'keywords': latest.keywords or [],
        'questions': latest.questions or [],
        'competitor_outlines': latest.competitor_outlines or [],
        'site_name': site.site_name,
        'language': site.language or 'id',
        'category_desc': category_desc,
    }, None


def _title_evidence(user_id, site_id, competitor_outlines):
    """Search Console quick wins and content gaps to steer the title prompt.

    Search Console queries are the strongest topic signal available: real
    searches that already produced impressions for this exact site.
    """
    gsc_topics = []
    content_gaps = []
    try:
        with db.get_session() as session:
            current_rows, previous_rows = load_search_metrics(session, user_id, site_id)
            opportunities = build_search_opportunities(current_rows, previous_rows, limit=20)
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


def _parse_title_response(text):
    text = text.strip()
    # Clean markdown codeblocks if any
    if text.startswith('```'):
        text = '\n'.join(text.split('\n')[1:-1])
        if text.startswith('json'):
            text = text[4:].strip()

    titles = json.loads(text)
    if not isinstance(titles, list):
        raise ValueError('Respons AI bukan daftar judul')
    titles = [str(title).strip() for title in titles if isinstance(title, str) and title.strip()]
    return list(dict.fromkeys(titles))


def _existing_site_titles(user_id, site_id):
    """Everything this site already has queued or published, across all categories.

    Two categories can otherwise produce near-identical titles that end up
    competing with each other.
    """
    with db.get_session() as session:
        existing = [
            row[0] for row in session.query(ContentQueue.title).filter(
                ContentQueue.user_id == user_id,
                ContentQueue.site_id == site_id
            ).all() if row[0]
        ]
        existing += _published_titles(session, user_id, site_id, 300)
    return existing


def _queue_titles(user_id, site_id, category, titles, keywords):
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


@research_bp.route('/api/generate-titles/<category>', methods=['POST'])
@require_jwt
def generate_titles(user_id, category):
    data = request.get_json(silent=True) or {}
    try:
        count = min(max(int(data.get('count', 5)), 1), 20)
    except (TypeError, ValueError):
        count = 5
    site_id = data.get('site_id') or request.args.get('site_id', type=int)

    if not site_id:
        return jsonify({'success': False, 'error': 'site_id wajib diisi.', 'code': 400}), 400
    if not category.strip() or len(category) > MAX_TITLE_CATEGORY_CHARS:
        return jsonify({'success': False, 'error': 'Kategori tidak valid.', 'code': 400}), 400

    try:
        try:
            context = _load_title_context(user_id, site_id, category)
        except _TitleRequestError as exc:
            return jsonify({'success': False, 'error': exc.message}), exc.status

        # Only gate (and count) the uncharged Gemini call once the request is
        # otherwise valid. Bulk generation sends one request per category, so
        # titles get their own, larger bucket instead of sharing the prompt
        # optimizer's.
        quota_error = check_ai_helper_quota(user_id, bucket='ai_titles', limit=200)
        if quota_error:
            return quota_error
        config = load_config(user_id)

        gsc_topics, content_gaps = _title_evidence(user_id, site_id, context['competitor_outlines'])
        evidence = _title_evidence_blocks(category, context['language'], gsc_topics, content_gaps)
        prompt = _build_title_prompt(count, category, context, evidence)

        generator = ArticleGenerator(
            config['gemini_api_key'],
            config.get('gemini_model', DEFAULT_GEMINI_MODEL),
            config.get('gemini_image_model', DEFAULT_GEMINI_IMAGE_MODEL)
        )
        response = generator.client.models.generate_content(model=generator.model, contents=prompt)
        titles = _parse_title_response(response.text)

        titles = _filter_duplicate_titles(titles, _existing_site_titles(user_id, site_id))[:count]
        if not titles:
            return jsonify({
                'success': False,
                'error': 'Semua judul yang dihasilkan terlalu mirip dengan yang sudah ada. Coba riset ulang atau ganti kategori.'
            }), 409

        _queue_titles(user_id, site_id, category, titles, context['keywords'])
        return jsonify({'success': True, 'message': f'{len(titles)} judul berhasil dibuat dan dimasukkan ke antrean!'})
    except Exception as e:
        logger.error(f"Generate titles error: {e}")
        reason = AI_BUSY_MESSAGE if _is_ai_busy_error(e) else 'terjadi kesalahan, silakan coba lagi.'
        return jsonify({'success': False, 'error': f'Gagal membuat judul: {reason}'}), 500


@research_bp.route('/api/clear-research', methods=['POST'])
@require_jwt
def clear_research(user_id):
    data = request.json or {}
    site_id = data.get('site_id')

    if not site_id:
        return jsonify({'success': False, 'error': 'site_id wajib diisi.'}), 400

    try:
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
