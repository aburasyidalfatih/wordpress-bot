import json
from flask import Blueprint, request, jsonify

from core_extensions import db, q, trending, logger, load_config, require_jwt

research_bp = Blueprint('research', __name__)

@research_bp.route('/api/research_data')
@require_jwt
def api_research(user_id):
    """Trending topics research page"""
    site_id = request.args.get('site_id', type=int)
    if not site_id:
        return jsonify({'success': False, 'error': 'site_id is required', 'code': 400}), 400
        
    with db.get_session() as session:
        from database import WordPressSite
        site = session.query(WordPressSite).filter_by(id=site_id, user_id=user_id).first()
        if not site:
            return jsonify({'success': False, 'error': 'Site not found', 'code': 404}), 404
            
        selected_categories = site.selected_categories or []
    
    # Get latest research data for each category
    research_data = {}
    for category in selected_categories:
        with db.get_session() as session:
            from database import ResearchData
            latest = session.query(ResearchData).filter(
                ResearchData.user_id == user_id,
                ResearchData.site_id == site_id,
                ResearchData.category == category['name']
            ).order_by(ResearchData.created_at.desc()).first()
            
            if latest:
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
                    'created_at': latest.created_at.strftime('%d %b %Y, %H:%M')
                }
    
    return jsonify({'success': True, 'categories': selected_categories, 'research_data': research_data})

@research_bp.route('/api/trending/<category>')
@require_jwt
def get_trending(user_id, category):
    """API endpoint to get trending topics for a category"""
    site_id = request.args.get('site_id', type=int)
    language = 'id'
    if site_id:
        with db.get_session() as session:
            from database import WordPressSite
            site = session.query(WordPressSite).filter_by(id=site_id, user_id=user_id).first()
            if site:
                language = site.language or 'id'
    try:
        data = trending.get_trending_topics(category, limit=15, language=language)
        return jsonify(data)
    except Exception as e:
        logger.error(f"Trending API error: {e}")
        return jsonify({'error': str(e)}), 500

@research_bp.route('/api/suggest-topics', methods=['POST'])
@require_jwt
def suggest_topics(user_id):
    """API endpoint to suggest article topics"""
    try:
        data = request.json
        category = data.get('category')
        count = data.get('count', 5)
        site_id = data.get('site_id') or request.args.get('site_id')
        language = 'id'
        if site_id:
            with db.get_session() as session:
                from database import WordPressSite
                site = session.query(WordPressSite).filter_by(id=int(site_id), user_id=user_id).first()
                if site:
                    language = site.language or 'id'
        
        suggestions = trending.suggest_article_topics(category, count, language=language)
        return jsonify({'suggestions': suggestions})
    except Exception as e:
        logger.error(f"Suggest topics error: {e}")
        return jsonify({'error': str(e)}), 500

@research_bp.route('/manual-research', methods=['POST'])
@require_jwt
def manual_research(user_id):
    site_id = request.args.get('site_id')
    if not site_id and request.is_json:
        site_id = request.json.get('site_id')
        
    if not site_id:
        return jsonify({'success': False, 'error': 'site_id is required', 'code': 400}), 400
        
    try:
        job = q.enqueue('app.deep_research_job', user_id, True, site_id)
        return jsonify({'success': True, 'job_id': job.id, 'message': 'Research queued'})
    except Exception as e:
        logger.error(f"Manual research error: {e}")
        return jsonify({'success': False, 'error': str(e)})

@research_bp.route('/api/generate-titles/<category>', methods=['POST'])
@require_jwt
def generate_titles(user_id, category):
    data = request.json or {}
    count = data.get('count', 5)
    site_id = data.get('site_id') or request.args.get('site_id', type=int)
    config = load_config(user_id)
    
    if not site_id:
        return jsonify({'success': False, 'error': 'site_id is required', 'code': 400}), 400
    
    try:
        # Get keywords from research data
        with db.get_session() as session:
            from database import ResearchData, ContentQueue, WordPressSite
            site = session.query(WordPressSite).filter_by(id=site_id, user_id=user_id).first()
            if not site:
                return jsonify({'success': False, 'error': 'Site not found'}), 404
                
            latest = session.query(ResearchData).filter(
                ResearchData.user_id == user_id,
                ResearchData.site_id == site_id,
                ResearchData.category == category
            ).order_by(ResearchData.created_at.desc()).first()
            
            keywords = latest.keywords if latest and latest.keywords else []
            questions = latest.questions if latest and latest.questions else []
            site_name = site.site_name
        
        # Use ArticleGenerator to suggest titles
        from bot import ArticleGenerator
        generator = ArticleGenerator(config['gemini_api_key'], config.get('gemini_model', 'gemini-2.5-pro'))
        
        # Prompt Gemini to generate titles
        prompt = f"""Buatlah {count} judul artikel blog yang sangat menarik, click-worthy, dan SEO-optimized untuk kategori "{category}" pada website {site_name}.
Fokuskan pada audiens yang relevan.
Tahun saat ini: 2026. Jangan gunakan tahun 2024 atau 2025.
Kata kunci terkait: {', '.join(keywords[:5]) if keywords else category}
Pertanyaan yang sering dicari: {', '.join(questions[:3]) if questions else ''}

Format output harus berupa JSON list of strings tanpa markdown formatting seperti ini:
["Judul 1", "Judul 2", "Judul 3"]"""

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
        return jsonify({'success': False, 'error': f'Gagal men-generate judul: {str(e)}'}), 500
