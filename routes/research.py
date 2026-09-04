import json
import re
from difflib import SequenceMatcher
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify
from sqlalchemy.exc import SQLAlchemyError

from core_extensions import db, q, trending, logger, load_config, require_jwt
from config import DEFAULT_GEMINI_MODEL, DEFAULT_GEMINI_IMAGE_MODEL
from database import MAX_RESEARCH_AGE_DAYS, USABLE_CONFIDENCE_LEVELS
from models import SearchConsoleMetric
from services.search_console import build_search_opportunities
from services.content_planner import (
    plan_from_opportunities, topic_candidates_from_opportunities,
    keyword_demand_map, annotate_keywords_with_demand,
    find_content_gaps, classify_intent, intent_guidance,
)

research_bp = Blueprint('research', __name__)

@research_bp.route('/api/research_data')
@require_jwt
def api_research(user_id):
    """Trending topics research page"""
    site_id = request.args.get('site_id', type=int)
    if not site_id:
        return jsonify({'success': False, 'error': 'site_id is required', 'code': 400}), 400
        
    with db.get_session() as session:
        from models import WordPressSite
        site = session.query(WordPressSite).filter_by(id=site_id, user_id=user_id).first()
        if not site:
            return jsonify({'success': False, 'error': 'Site not found', 'code': 404}), 404
            
        selected_categories = site.selected_categories or []
        # Snapshot these values while the ORM instance is still attached. The
        # response is assembled after other sessions have committed and closed.
        gsc_connected = bool(site.gsc_refresh_token)
        gsc_property_url = site.gsc_property_url
        gsc_last_synced_at = site.gsc_last_synced_at
    
    # Get latest research data for each category
    research_data = {}
    with db.get_session() as session:
        from models import ResearchData
        for category in selected_categories:
            latest = session.query(ResearchData).filter(
                ResearchData.user_id == user_id,
                ResearchData.site_id == site_id,
                ResearchData.category == category['name']
            ).order_by(ResearchData.created_at.desc()).first()
            
            if latest:
                researched_at = latest.researched_at or latest.created_at
                now = datetime.now(timezone.utc).replace(tzinfo=None)
                age_hours = max(0, int((now - researched_at).total_seconds() / 3600)) if researched_at else None
                research_data[category['name']] = {
                    'trending_count': len(latest.trending_topics) if latest.trending_topics else 0,
                    'rising_count': len(latest.rising_topics) if latest.rising_topics else 0,
                    'top_count': len(latest.top_topics) if latest.top_topics else 0,
                    'suggestions': latest.suggested_topics[:5] if latest.suggested_topics else [],
                    'suggestions_count': len(latest.suggested_topics) if latest.suggested_topics else 0,
                    'keywords': latest.keywords[:10] if hasattr(latest, 'keywords') and latest.keywords else [],
                    'keywords_count': len(latest.keywords) if hasattr(latest, 'keywords') and latest.keywords else 0,
                    'questions': latest.questions[:5] if hasattr(latest, 'questions') and latest.questions else [],
                    'questions_count': len(latest.questions) if hasattr(latest, 'questions') and latest.questions else 0,
                    'trend_score': latest.trend_score if hasattr(latest, 'trend_score') and latest.trend_score is not None else 0,
                    'social_insights': latest.social_insights if hasattr(latest, 'social_insights') and latest.social_insights else [],
                    'competitor_outlines': latest.competitor_outlines if hasattr(latest, 'competitor_outlines') and latest.competitor_outlines else [],
                    'youtube_insights': latest.youtube_insights if hasattr(latest, 'youtube_insights') and latest.youtube_insights else [],
                    'long_tail_keywords': latest.long_tail_keywords or [],
                    'news_insights': latest.news_insights or [],
                    'semantic_context': latest.semantic_context or '',
                    'source_metadata': latest.source_metadata or {},
                    'quality_score': latest.quality_score or 0,
                    'confidence_level': latest.confidence_level or 'unknown',
                    'is_fallback': bool(latest.is_fallback),
                    'age_hours': age_hours,
                    'is_stale': age_hours is not None and age_hours > 168,
                    'created_at': researched_at.strftime('%d %b %Y, %H:%M') if researched_at else None,
                }
    
    gsc_opportunities = []
    gsc_metrics_error = None
    current_metrics = []
    try:
        with db.get_session() as session:
            metrics = session.query(SearchConsoleMetric).filter_by(
                user_id=user_id, site_id=site_id
            ).order_by(SearchConsoleMetric.synced_at.desc()).all()
            current_metrics = [_gsc_metric_dict(row) for row in metrics if row.period_label == 'current']
            previous_metrics = [_gsc_metric_dict(row) for row in metrics if row.period_label == 'previous']
            raw_opportunities = build_search_opportunities(current_metrics, previous_metrics, limit=20)
            # Each opportunity now carries the action it actually calls for, so the
            # UI can distinguish "write something new" from "fix the title".
            gsc_opportunities = plan_from_opportunities(raw_opportunities, limit=10)
    except SQLAlchemyError as exc:
        # Search Console is additive intelligence. A migration/runtime problem in
        # its metric store must not take the existing Research page offline.
        logger.error(f'Could not load Search Console metrics for site_id={site_id}: {exc}')
        gsc_metrics_error = 'Data Search Console belum tersedia. Coba sinkronkan kembali.'

    # Content gaps: competitor subtopics we have never published about. Uses data
    # already stored on both sides, so it costs one extra query per category.
    try:
        with db.get_session() as session:
            from models import PostLog
            published_titles = [
                row[0] for row in session.query(PostLog.title).filter(
                    PostLog.user_id == user_id,
                    PostLog.site_id == site_id,
                    PostLog.success.is_(True)
                ).order_by(PostLog.created_at.desc()).limit(200).all()
                if row[0]
            ]
        demand = keyword_demand_map(current_metrics)
        for name, entry in research_data.items():
            entry['content_gaps'] = find_content_gaps(
                entry.get('competitor_outlines'), published_titles
            )
            entry['keywords'] = annotate_keywords_with_demand(entry.get('keywords'), demand)
            entry['intent'] = classify_intent(name)
            entry['change_since_last_run'] = _research_delta(user_id, site_id, name)
    except SQLAlchemyError as exc:
        logger.error(f'Could not build content gaps for site_id={site_id}: {exc}')

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


def _research_delta(user_id, site_id, category):
    """Compare the two most recent research runs for a category.

    The history is already stored; surfacing the movement turns a snapshot into a
    trend, e.g. "trend score up 12, 3 new keywords since the last run".
    """
    try:
        from models import ResearchData
        with db.get_session() as session:
            runs = session.query(ResearchData).filter(
                ResearchData.user_id == user_id,
                ResearchData.site_id == site_id,
                ResearchData.category == category
            ).order_by(ResearchData.created_at.desc()).limit(2).all()

            if len(runs) < 2:
                return None

            latest, previous = runs[0], runs[1]
            latest_kw = {str(k).lower() for k in (latest.keywords or [])}
            previous_kw = {str(k).lower() for k in (previous.keywords or [])}

            return {
                'trend_score_change': (latest.trend_score or 0) - (previous.trend_score or 0),
                'quality_score_change': (latest.quality_score or 0) - (previous.quality_score or 0),
                'new_keywords': sorted(latest_kw - previous_kw)[:5],
                'lost_keywords': sorted(previous_kw - latest_kw)[:5],
                'previous_confidence': previous.confidence_level,
                'previous_researched_at': (
                    previous.researched_at.strftime('%d %b %Y, %H:%M')
                    if previous.researched_at else None
                ),
            }
    except SQLAlchemyError as exc:
        logger.error(f'Could not compute research delta for {category}: {exc}')
        return None


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


def _gsc_metric_dict(row):
    return {
        'query': row.query,
        'page': row.page,
        'clicks': row.clicks,
        'impressions': row.impressions,
        'ctr': row.ctr,
        'position': row.position,
    }

@research_bp.route('/api/trending/<category>')
@require_jwt
def get_trending(user_id, category):
    """API endpoint to get trending topics for a category"""
    site_id = request.args.get('site_id', type=int)
    language = 'id'
    if site_id:
        with db.get_session() as session:
            from models import WordPressSite
            site = session.query(WordPressSite).filter_by(id=site_id, user_id=user_id).first()
            if site:
                language = site.language or 'id'
    try:
        data = trending.get_trending_topics(category, limit=15, language=language)
        return jsonify(data)
    except Exception as e:
        logger.error(f"Trending API error: {e}")
        error_msg = str(e)
        if '503' in error_msg or 'high demand' in error_msg.lower():
            error_msg = 'Server Google AI sedang sibuk karena lonjakan permintaan. Silakan coba lagi beberapa saat.'
        return jsonify({'error': error_msg}), 500

@research_bp.route('/api/suggest-topics', methods=['POST'])
@require_jwt
def suggest_topics(user_id):
    """API endpoint to suggest article topics"""
    try:
        data = request.json
        category = data.get('category')
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
                return jsonify({'success': False, 'error': 'Invalid site_id'}), 400
            with db.get_session() as session:
                from models import WordPressSite
                site = session.query(WordPressSite).filter_by(id=site_id, user_id=user_id).first()
                if site:
                    language = site.language or 'id'
        
        suggestions = trending.suggest_article_topics(category, count, language=language)
        return jsonify({'suggestions': suggestions})
    except Exception as e:
        logger.error(f"Trending API error: {e}")
        error_msg = str(e)
        if '503' in error_msg or 'high demand' in error_msg.lower():
            error_msg = 'Server Google AI sedang sibuk karena lonjakan permintaan. Silakan coba lagi beberapa saat.'
        return jsonify({'error': error_msg}), 500

@research_bp.route('/manual-research', methods=['POST'])
@require_jwt
def manual_research(user_id):
    site_id = request.args.get('site_id')
    category = request.args.get('category')
    if not site_id and request.is_json:
        data = request.json or {}
        site_id = data.get('site_id')
        category = data.get('category')
        
    if not site_id:
        return jsonify({'success': False, 'error': 'site_id is required', 'code': 400}), 400
        
    if category == "" or category == "all" or category == "All":
        category = None
        
    try:
        try:
            site_id_int = int(site_id)
        except (TypeError, ValueError):
            return jsonify({'success': False, 'error': 'Format site_id tidak valid.'}), 400
            
        with db.get_session() as session:
            from models import WordPressSite, User
            site = session.query(WordPressSite).filter_by(id=site_id_int, user_id=user_id).first()
            if not site:
                return jsonify({'success': False, 'error': 'Website tidak ditemukan.'}), 404
                
            user = session.query(User).filter_by(id=user_id).first()
            if not user:
                return jsonify({'success': False, 'error': 'User tidak ditemukan.'}), 404
                
            selected_categories = site.selected_categories or []
            if not selected_categories:
                return jsonify({'success': False, 'error': 'Silakan pilih kategori target terlebih dahulu di Pengaturan Website.'}), 400
                
            if category:
                # verify category is selected
                match = [cat for cat in selected_categories if cat['name'] == category]
                if not match:
                    return jsonify({'success': False, 'error': f'Kategori "{category}" tidak terpilih untuk website ini.'}), 400
                required_credits = 1
            else:
                required_credits = len(selected_categories)
                
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
        try:
            job = q.enqueue('tasks.research_jobs.deep_research_job', user_id, True, site_id, category)
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
        return jsonify({'success': False, 'error': str(e)}), 500

@research_bp.route('/api/generate-titles/<category>', methods=['POST'])
@require_jwt
def generate_titles(user_id, category):
    data = request.json or {}
    try:
        count = min(max(int(data.get('count', 5)), 1), 20)
    except (TypeError, ValueError):
        count = 5
    site_id = data.get('site_id') or request.args.get('site_id', type=int)
    config = load_config(user_id)
    
    if not site_id:
        return jsonify({'success': False, 'error': 'site_id is required', 'code': 400}), 400
    
    try:
        # Get keywords from research data
        with db.get_session() as session:
            from models import ResearchData, ContentQueue, WordPressSite
            site = session.query(WordPressSite).filter_by(id=site_id, user_id=user_id).first()
            if not site:
                return jsonify({'success': False, 'error': 'Site not found'}), 404
                
            latest = session.query(ResearchData).filter(
                ResearchData.user_id == user_id,
                ResearchData.site_id == site_id,
                ResearchData.category == category
            ).order_by(ResearchData.created_at.desc()).first()

            if not latest:
                return jsonify({'success': False, 'error': 'Jalankan riset berkualitas terlebih dahulu.'}), 400
            confidence = latest.confidence_level or 'unknown'
            research_time = latest.researched_at or latest.created_at
            age_days = (datetime.now() - research_time).days if research_time else 999
            if confidence not in USABLE_CONFIDENCE_LEVELS or age_days > MAX_RESEARCH_AGE_DAYS:
                reason = ('bukti riset belum terverifikasi' if confidence not in USABLE_CONFIDENCE_LEVELS
                          else f'data riset sudah lebih dari {MAX_RESEARCH_AGE_DAYS} hari')
                return jsonify({
                    'success': False,
                    'error': f'Tidak aman membuat judul dari data ini: {reason}. Silakan riset ulang.'
                }), 400
            
            keywords = latest.keywords or []
            questions = latest.questions or []
            competitor_outlines = latest.competitor_outlines or []
            site_name = site.site_name
            language = site.language or 'id'

            category_desc = ""
            for cat in (site.categories or []):
                if cat.get('name') == category:
                    category_desc = cat.get('description', '')
                    break
        
        # Search Console queries are the strongest topic signal available: real
        # searches that already produced impressions for this exact site. Feed the
        # quick-win queries and the content gaps into the title prompt.
        gsc_topics = []
        content_gaps = []
        try:
            with db.get_session() as session:
                metrics = session.query(SearchConsoleMetric).filter_by(
                    user_id=user_id, site_id=site_id
                ).order_by(SearchConsoleMetric.synced_at.desc()).all()
                current_rows = [_gsc_metric_dict(r) for r in metrics if r.period_label == 'current']
                previous_rows = [_gsc_metric_dict(r) for r in metrics if r.period_label == 'previous']
                opportunities = build_search_opportunities(current_rows, previous_rows, limit=20)
                gsc_topics = topic_candidates_from_opportunities(opportunities, limit=6)

                from models import PostLog
                published_titles = [
                    row[0] for row in session.query(PostLog.title).filter(
                        PostLog.user_id == user_id,
                        PostLog.site_id == site_id,
                        PostLog.success.is_(True)
                    ).order_by(PostLog.created_at.desc()).limit(200).all()
                    if row[0]
                ]
            content_gaps = find_content_gaps(competitor_outlines, published_titles, limit=5)
        except SQLAlchemyError as exc:
            logger.error(f'Could not load search evidence for titles (site_id={site_id}): {exc}')

        gsc_block = ""
        if gsc_topics:
            lines = "\n".join(
                f"- \"{t['query']}\" ({int(t['impressions'] or 0)} impressions, posisi {t['position']})"
                for t in gsc_topics
            )
            if language == 'en':
                gsc_block = (
                    "\n\nREAL SEARCH QUERIES this site already gets impressions for. These are\n"
                    "the highest-value topics; prioritise them:\n" + lines + "\n"
                )
            else:
                gsc_block = (
                    "\n\nQUERY PENCARIAN NYATA yang sudah mendatangkan impression ke situs ini.\n"
                    "Ini topik paling bernilai, prioritaskan:\n" + lines + "\n"
                )

        gap_block = ""
        if content_gaps:
            lines = "\n".join(f"- {g['topic']}" for g in content_gaps)
            if language == 'en':
                gap_block = ("\n\nCONTENT GAPS - competitors cover these, this site does not:\n"
                             + lines + "\n")
            else:
                gap_block = ("\n\nCELAH KONTEN - dibahas kompetitor tapi belum ada di situs ini:\n"
                             + lines + "\n")

        category_intent = classify_intent(category)
        intent_block = f"\n\nSEARCH INTENT: {category_intent}. {intent_guidance(category_intent, language)}\n"

        # Use ArticleGenerator to suggest titles
        from services.article_generator import ArticleGenerator
        generator = ArticleGenerator(
            config['gemini_api_key'], 
            config.get('gemini_model', DEFAULT_GEMINI_MODEL),
            config.get('gemini_image_model', DEFAULT_GEMINI_IMAGE_MODEL)
        )
        current_year = datetime.now().year
        
        if language == 'en':
            prompt = f"""Create {count} highly engaging, natural (like written by a professional journalist or blogger), click-worthy (High CTR), and SEO-optimized blog article titles for the category "{category}" on the website {site_name}. All titles MUST BE IN ENGLISH.

TITLE WRITING GUIDELINES (CRITICAL):
1. DO NOT use repetitive robotic formula formats like "[Keyword]: [Subtitle]". Create natural flowing sentences.
2. DO NOT use AI cliché words like: "Complete Guide", "Smart Solution", "Effective Strategy", "Must Know", "In the Digital Era", "Towards the Future".
3. DO NOT create titles that just define the category name itself.
4. Create titles that evoke curiosity (curiosity gap), solve practical problems, or discuss hot trends with a fresh human perspective.

Additional Context:
- Category Description: {category_desc if category_desc else 'Write about specific and hot topics in this field.'}
- Current year: {current_year} (use this year naturally if relevant).
- Related keywords: {', '.join(keywords[:5]) if keywords else category}
- Frequently asked questions: {', '.join(questions[:3]) if questions else ''}

{gsc_block}{gap_block}{intent_block}
Output format must be a JSON list of strings without markdown formatting like this:
["Article Title 1", "Article Title 2", "Article Title 3"]"""
        else:
            prompt = f"""Buatlah {count} judul artikel blog berbahasa INDONESIA yang sangat menarik, natural (seperti ditulis oleh jurnalis atau blogger profesional), click-worthy (High CTR), dan SEO-optimized untuk kategori "{category}" pada website {site_name}.

PANDUAN GAYA PENULISAN JUDUL (SANGAT PENTING):
1. JANGAN gunakan format formula robotik berulang seperti "[Kata Kunci]: [Sub-judul]". Buatlah kalimat mengalir yang natural.
2. JANGAN gunakan kata-kata klise AI/robotik berikut: "Panduan Lengkap", "Solusi Cerdas", "Strategi Efektif", "Era 2026", "Wajib Diketahui", "Meningkatkan Kualitas", "Di Era Digital", "Menuju Masa Depan".
3. JANGAN membuat judul berupa definisi dari nama kategori itu sendiri.
4. Buatlah judul yang mengundang rasa ingin tahu (curiosity gap), memecahkan masalah praktis, atau membahas tren hangat dengan sudut pandang manusiawi yang segar.

Konteks Tambahan:
- Deskripsi Kategori: {category_desc if category_desc else 'Tulis tentang topik-topik spesifik dan hangat di bidang ini.'}
- Tahun saat ini: {current_year} (gunakan tahun ini secara natural jika relevan). Jangan gunakan tahun lama kecuali dibutuhkan sebagai konteks historis.
- Kata kunci terkait: {', '.join(keywords[:5]) if keywords else category}
- Isu/pertanyaan yang sering dicari: {', '.join(questions[:3]) if questions else ''}

{gsc_block}{gap_block}{intent_block}
Format output harus berupa JSON list of strings tanpa markdown formatting seperti ini:
["Judul Artikel 1", "Judul Artikel 2", "Judul Artikel 3"]"""

        response = generator.client.models.generate_content(
            model=generator.model,
            contents=prompt
        )
        text = response.text.strip()
        # Clean markdown codeblocks if any
        if text.startswith('```'):
            text = '\n'.join(text.split('\n')[1:-1])
            if text.startswith('json'):
                text = text[4:].strip()
        
        titles = json.loads(text)
        if not isinstance(titles, list):
            raise ValueError('Respons AI bukan daftar judul')
        titles = [str(title).strip() for title in titles if isinstance(title, str) and title.strip()]
        titles = list(dict.fromkeys(titles))

        # Deduplicate against everything this site already has queued or published,
        # across all categories. Two categories can otherwise produce near-identical
        # titles that end up competing with each other.
        with db.get_session() as session:
            from models import PostLog
            existing = [
                row[0] for row in session.query(ContentQueue.title).filter(
                    ContentQueue.user_id == user_id,
                    ContentQueue.site_id == site_id
                ).all() if row[0]
            ]
            existing += [
                row[0] for row in session.query(PostLog.title).filter(
                    PostLog.user_id == user_id,
                    PostLog.site_id == site_id,
                    PostLog.success.is_(True)
                ).order_by(PostLog.created_at.desc()).limit(300).all() if row[0]
            ]

        titles = _filter_duplicate_titles(titles, existing)[:count]
        if not titles:
            return jsonify({
                'success': False,
                'error': 'Semua judul yang dihasilkan terlalu mirip dengan yang sudah ada. Coba riset ulang atau ganti kategori.'
            }), 409

        # Save to ContentQueue
        with db.get_session() as session:
            for title in titles:
                queue_item = ContentQueue(
                    user_id=user_id,
                    site_id=site_id,
                    category=category,
                    title=title,
                    target_keywords=', '.join(keywords[:5]) if keywords else category,
                    status='pending'
                )
                session.add(queue_item)
            session.commit()
            
        return jsonify({'success': True, 'message': f'{len(titles)} judul berhasil dibuat dan dimasukkan ke antrean!'})
    except Exception as e:
        logger.error(f"Generate titles error: {e}")
        error_msg = str(e)
        if '503' in error_msg or 'high demand' in error_msg.lower():
            error_msg = 'Server Google AI sedang sibuk karena lonjakan permintaan. Silakan coba lagi beberapa saat.'
        return jsonify({'success': False, 'error': f'Gagal men-generate judul: {error_msg}'}), 500

@research_bp.route('/api/clear-research', methods=['POST'])
@require_jwt
def clear_research(user_id):
    data = request.json or {}
    site_id = data.get('site_id')
    
    if not site_id:
        return jsonify({'success': False, 'error': 'site_id is required'}), 400
        
    try:
        with db.get_session() as session:
            from models import ResearchData
            deleted_count = session.query(ResearchData).filter_by(site_id=site_id, user_id=user_id).delete()
            session.commit()
            
        return jsonify({
            'success': True, 
            'message': f'Berhasil membersihkan {deleted_count} data riset.'
        })
    except Exception as e:
        logger.error(f"Clear research error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
