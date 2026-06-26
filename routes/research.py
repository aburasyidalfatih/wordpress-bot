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
        with db.get_session() as session:
            from database import WordPressSite, User
            site = session.query(WordPressSite).filter_by(id=int(site_id), user_id=user_id).first()
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
                
            # Deduct credits
            user.credits = max(0, user_credits - required_credits)
            session.commit()
            
            # Enqueue job with category
            job = q.enqueue('app.deep_research_job', user_id, True, site_id, category)
            return jsonify({
                'success': True, 
                'job_id': job.id, 
                'message': f'Riset berhasil masuk antrean. {required_credits} kredit didebit.',
                'credits_deducted': required_credits,
                'remaining_credits': user.credits
            })
    except Exception as e:
        logger.error(f"Manual research error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

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
            
            category_desc = ""
            for cat in (site.categories or []):
                if cat.get('name') == category:
                    category_desc = cat.get('description', '')
                    break
        
        # Use ArticleGenerator to suggest titles
        from bot import ArticleGenerator
        generator = ArticleGenerator(
            config['gemini_api_key'], 
            config.get('gemini_model', 'gemini-2.5-pro'),
            config.get('gemini_image_model', 'gemini-3.1-flash-image')
        )
        
        language = site.language or 'id'
        
        if language == 'en':
            prompt = f"""Create {count} highly engaging, natural (like written by a professional journalist or blogger), click-worthy (High CTR), and SEO-optimized blog article titles for the category "{category}" on the website {site_name}. All titles MUST BE IN ENGLISH.

TITLE WRITING GUIDELINES (CRITICAL):
1. DO NOT use repetitive robotic formula formats like "[Keyword]: [Subtitle]". Create natural flowing sentences.
2. DO NOT use AI cliché words like: "Complete Guide", "Smart Solution", "Effective Strategy", "Must Know", "In the Digital Era", "Towards the Future".
3. DO NOT create titles that just define the category name itself.
4. Create titles that evoke curiosity (curiosity gap), solve practical problems, or discuss hot trends with a fresh human perspective.

Additional Context:
- Category Description: {category_desc if category_desc else 'Write about specific and hot topics in this field.'}
- Current year: 2026 (use this year naturally if relevant).
- Related keywords: {', '.join(keywords[:5]) if keywords else category}
- Frequently asked questions: {', '.join(questions[:3]) if questions else ''}

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
- Tahun saat ini: 2026 (gunakan tahun ini secara natural jika relevan). Jangan gunakan tahun 2024 atau 2025.
- Kata kunci terkait: {', '.join(keywords[:5]) if keywords else category}
- Isu/pertanyaan yang sering dicari: {', '.join(questions[:3]) if questions else ''}

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
