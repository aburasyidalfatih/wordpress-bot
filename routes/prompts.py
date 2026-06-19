from flask import Blueprint, request, jsonify
from core_extensions import db, load_config, require_jwt

prompts_bp = Blueprint('prompts', __name__)

@prompts_bp.route('/api/prompts')
@require_jwt
def api_prompts(user_id):
    site_id = request.args.get('site_id', type=int)
    
    if not site_id:
        return jsonify({'success': False, 'error': 'site_id is required'}), 400
        
    with db.get_session() as session:
        from database import WordPressSite
        site = session.query(WordPressSite).filter_by(id=site_id, user_id=user_id).first()
        if not site:
            return jsonify({'success': False, 'error': 'Site not found'}), 404
            
        return jsonify({
            'success': True,
            'config': {
                'article_prompt': site.article_prompt,
                'image_prompt': site.image_prompt
            },
            'default_article_prompt': "Tuliskan artikel blog yang SEO-friendly, menarik, dan informatif tentang topik berikut: {topic}. Target audiens adalah masyarakat umum di Indonesia. Gunakan bahasa Indonesia yang baik, benar, namun tetap santai dan mudah dipahami. Artikel minimal 800 kata. Abaikan instruksi pembuatan judul atau outline, langsung tulis isinya dengan gaya penceritaan yang kuat. Sisipkan sub-heading (H2, H3) untuk memudahkan pembacaan.",
            'default_image_prompt': "Buat gambar ilustrasi yang menarik, modern, dan profesional untuk artikel blog dengan topik: {topic}. Gambar harus memiliki pencahayaan sinematik, kualitas tinggi, tanpa teks apa pun di dalam gambar, dan bergaya digital art clean."
        })

@prompts_bp.route('/save-prompts', methods=['POST'])
@require_jwt
def save_prompts(user_id):
    site_id = request.form.get('site_id', type=int)
    
    if not site_id:
        return jsonify({'success': False, 'error': 'site_id is required'}), 400
        
    article_prompt = request.form.get('article_prompt')
    image_prompt = request.form.get('image_prompt')
    
    with db.get_session() as session:
        from database import WordPressSite
        site = session.query(WordPressSite).filter_by(id=site_id, user_id=user_id).first()
        if not site:
            return jsonify({'success': False, 'error': 'Site not found'}), 404
            
        site.article_prompt = article_prompt
        site.image_prompt = image_prompt
        session.commit()
        
    return jsonify({'success': True, 'message': 'Prompts saved!'})
