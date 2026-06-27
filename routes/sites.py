import requests
from flask import Blueprint, request, jsonify
from core_extensions import db, logger, require_jwt, send_telegram_notification
from bot import WordPressPublisher

sites_bp = Blueprint('sites', __name__)

def _secret_status(value):
    return bool(value)

def _should_update_secret(value):
    return isinstance(value, str) and bool(value.strip())

@sites_bp.route('/api/sites', methods=['GET'])
@require_jwt
def get_sites(user_id):
    with db.get_session() as session:
        from database import WordPressSite
        sites = session.query(WordPressSite).filter_by(user_id=user_id).order_by(WordPressSite.created_at.desc()).all()
        return jsonify({
            'success': True,
            'sites': [{
                'id': site.id,
                'site_name': site.site_name,
                'wordpress_url': site.wordpress_url,
                'wordpress_username': site.wordpress_username,
                'is_active': site.is_active,

                'schedule_hours': site.schedule_hours,
                'timezone': site.timezone,
                'language': site.language,
                'auto_post': site.auto_post,
                'categories': site.categories,
                'selected_categories': site.selected_categories,
                'telegram_enabled': site.telegram_enabled,
                'wordpress_password': '',
                'has_wordpress_password': _secret_status(site.wordpress_password),
                'telegram_bot_token': '',
                'has_telegram_bot_token': _secret_status(site.telegram_bot_token),
                'telegram_chat_id': site.telegram_chat_id,
                'telegram_channel_id': site.telegram_channel_id,
                'telegram_post_to_channel': site.telegram_post_to_channel,
                'facebook_enabled': site.facebook_enabled,
                'facebook_page_id': site.facebook_page_id,
                'facebook_access_token': '',
                'has_facebook_access_token': _secret_status(site.facebook_access_token),
                'twitter_enabled': site.twitter_enabled,
                'twitter_api_key': '',
                'twitter_api_secret': '',
                'twitter_access_token': '',
                'twitter_access_secret': '',
                'has_twitter_api_key': _secret_status(site.twitter_api_key),
                'has_twitter_api_secret': _secret_status(site.twitter_api_secret),
                'has_twitter_access_token': _secret_status(site.twitter_access_token),
                'has_twitter_access_secret': _secret_status(site.twitter_access_secret),
                'threads_enabled': site.threads_enabled,
                'threads_user_id': site.threads_user_id,
                'threads_access_token': '',
                'has_threads_access_token': _secret_status(site.threads_access_token),

                'article_prompt': site.article_prompt,
                'image_prompt': site.image_prompt
            } for site in sites]
        })

@sites_bp.route('/api/sites', methods=['POST'])
@require_jwt
def create_site(user_id):
    data = request.json
    if not data or not data.get('wordpress_url'):
        return jsonify({'success': False, 'error': 'WordPress URL is required'}), 400
        
    with db.get_session() as session:
        from database import WordPressSite
        site = WordPressSite(
            user_id=user_id,
            site_name=data.get('site_name', 'New Website'),
            wordpress_url=data.get('wordpress_url'),
            wordpress_username=data.get('wordpress_username', ''),
            wordpress_password=data.get('wordpress_password', ''), # Virtual setter

            schedule_hours=data.get('schedule_hours', '0,6,12,18'),
            timezone=data.get('timezone', 'Asia/Jakarta'),
            language=data.get('language', 'id'),
            auto_post=data.get('auto_post', False)
        )
        session.add(site)
        session.commit()
        return jsonify({'success': True, 'site_id': site.id, 'message': 'Site added successfully'})

@sites_bp.route('/api/sites/<int:site_id>', methods=['PUT'])
@require_jwt
def update_site(user_id, site_id):
    data = request.json
    with db.get_session() as session:
        from database import WordPressSite
        site = session.query(WordPressSite).filter_by(id=site_id, user_id=user_id).first()
        if not site:
            return jsonify({'success': False, 'error': 'Site not found'}), 404
            
        # Update basic info
        if 'site_name' in data: site.site_name = data['site_name']
        if 'wordpress_url' in data: site.wordpress_url = data['wordpress_url']
        if 'wordpress_username' in data: site.wordpress_username = data['wordpress_username']
        if 'wordpress_password' in data and _should_update_secret(data['wordpress_password']): 
            site.wordpress_password = data['wordpress_password']
            
        # Update schedule

        if 'schedule_hours' in data: site.schedule_hours = data['schedule_hours']
        if 'timezone' in data: site.timezone = data['timezone']
        if 'language' in data: site.language = data['language']
        if 'auto_post' in data: site.auto_post = data['auto_post']
        
        # Update categories
        if 'categories' in data: site.categories = data['categories']
        if 'selected_categories' in data: site.selected_categories = data['selected_categories']
        
        # Prompts
        if 'article_prompt' in data: site.article_prompt = data['article_prompt'] or None
        if 'image_prompt' in data: site.image_prompt = data['image_prompt'] or None
        
        # Update social
        if 'telegram_bot_token' in data and _should_update_secret(data['telegram_bot_token']): site.telegram_bot_token = data['telegram_bot_token']
        if 'telegram_chat_id' in data: site.telegram_chat_id = data['telegram_chat_id']
        if 'telegram_channel_id' in data: site.telegram_channel_id = data['telegram_channel_id']
        if 'telegram_enabled' in data: site.telegram_enabled = data['telegram_enabled']
        if 'telegram_post_to_channel' in data: site.telegram_post_to_channel = data['telegram_post_to_channel']
        
        if 'facebook_page_id' in data: site.facebook_page_id = data['facebook_page_id']
        if 'facebook_access_token' in data and _should_update_secret(data['facebook_access_token']): site.facebook_access_token = data['facebook_access_token']
        if 'facebook_enabled' in data: site.facebook_enabled = data['facebook_enabled']
        
        if 'twitter_api_key' in data and _should_update_secret(data['twitter_api_key']): site.twitter_api_key = data['twitter_api_key']
        if 'twitter_api_secret' in data and _should_update_secret(data['twitter_api_secret']): site.twitter_api_secret = data['twitter_api_secret']
        if 'twitter_access_token' in data and _should_update_secret(data['twitter_access_token']): site.twitter_access_token = data['twitter_access_token']
        if 'twitter_access_secret' in data and _should_update_secret(data['twitter_access_secret']): site.twitter_access_secret = data['twitter_access_secret']
        if 'twitter_enabled' in data: site.twitter_enabled = data['twitter_enabled']
        
        if 'threads_user_id' in data: site.threads_user_id = data['threads_user_id']
        if 'threads_access_token' in data and _should_update_secret(data['threads_access_token']): site.threads_access_token = data['threads_access_token']
        if 'threads_enabled' in data: site.threads_enabled = data['threads_enabled']
        

        if 'is_active' in data: site.is_active = data['is_active']
        
        session.commit()
        return jsonify({'success': True, 'message': 'Site updated successfully'})

@sites_bp.route('/api/sites/<int:site_id>', methods=['DELETE'])
@require_jwt
def delete_site(user_id, site_id):
    with db.get_session() as session:
        from database import WordPressSite
        site = session.query(WordPressSite).filter_by(id=site_id, user_id=user_id).first()
        if not site:
            return jsonify({'success': False, 'error': 'Site not found'}), 404
            
        session.delete(site)
        session.commit()
        return jsonify({'success': True, 'message': 'Site deleted successfully'})

@sites_bp.route("/api/sites/<int:site_id>/fetch-categories", methods=["POST"])
@require_jwt
def fetch_categories(user_id, site_id):
    with db.get_session() as session:
        from database import WordPressSite
        site = session.query(WordPressSite).filter_by(id=site_id, user_id=user_id).first()
        if not site:
            return jsonify({'success': False, 'error': 'Site not found'}), 404
            
        if not site.wordpress_url or not site.wordpress_username or not site.wordpress_password:
            return jsonify({'success': False, 'error': 'Mohon isi kredensial WordPress terlebih dahulu.'}), 400
        
        try:
            publisher = WordPressPublisher(
                site.wordpress_url,
                site.wordpress_username,
                site.wordpress_password
            )
            categories = publisher.get_categories()
            
            if categories:
                site.categories = categories
                
                # Sync descriptions and counts in selected_categories
                selected_cats = site.selected_categories or []
                updated_selected = []
                for sel_cat in selected_cats:
                    matching = next((c for c in categories if c['id'] == sel_cat['id']), None)
                    if matching:
                        updated_selected.append({
                            'id': matching['id'],
                            'name': matching['name'],
                            'description': matching.get('description', ''),
                            'count': matching.get('count', 0)
                        })
                    else:
                        updated_selected.append(sel_cat)
                
                site.selected_categories = updated_selected
                session.commit()
                return jsonify({'success': True, 'categories': categories})
            else:
                return jsonify({'success': False, 'error': 'Tidak dapat mengambil kategori. Periksa kredensial.'}), 400
        except Exception as e:
            logger.error(f"Fetch categories error: {e}")
            return jsonify({'success': False, 'error': f'Error: {str(e)}'}), 500

@sites_bp.route("/api/sites/<int:site_id>/test-telegram", methods=["POST"])
@require_jwt
def test_telegram(user_id, site_id):
    with db.get_session() as session:
        from database import WordPressSite
        site = session.query(WordPressSite).filter_by(id=site_id, user_id=user_id).first()
        if not site:
            return jsonify({'success': False, 'error': 'Site not found'}), 404
            
        if not site.telegram_bot_token or not site.telegram_chat_id:
            return jsonify({'success': False, 'error': 'Bot Token atau Chat ID belum diisi!'}), 400
        
        try:
            url = f"https://api.telegram.org/bot{site.telegram_bot_token}/getMe"
            response = requests.get(url, timeout=10)
            
            if response.status_code != 200:
                return jsonify({'success': False, 'error': 'Bot Token tidak valid!'}), 400
        except Exception as e:
            return jsonify({'success': False, 'error': f'Error koneksi: {str(e)}'}), 500
        
        # Create a mock config dict for the legacy send_telegram_notification function
        mock_config = {
            'telegram_bot_token': site.telegram_bot_token,
            'telegram_chat_id': site.telegram_chat_id,
            'telegram_channel_id': site.telegram_channel_id,
            'telegram_post_to_channel': site.telegram_post_to_channel,
            'telegram_enabled': site.telegram_enabled
        }
        
        success = send_telegram_notification(mock_config,
            f"🤖 <b>Test Notifikasi</b>\n\n"
            f"✅ Telegram berhasil terhubung untuk {site.site_name}!\n"
            f"📱 Bot siap mengirim notifikasi.")
        
        if success:
            return jsonify({'success': True, 'message': 'Notifikasi test berhasil dikirim!'})
        else:
            return jsonify({'success': False, 'error': 'Chat ID tidak valid atau bot belum di-start!'}), 400

@sites_bp.route('/api/sites/<int:site_id>/next-category', methods=['GET'])
@require_jwt
def next_category(user_id, site_id):
    with db.get_session() as session:
        from database import WordPressSite
        site = session.query(WordPressSite).filter_by(id=site_id, user_id=user_id).first()
        if not site:
            return jsonify({'success': False, 'error': 'Site not found'}), 404
            
        if site.selected_categories and len(site.selected_categories) > 0:
            next_cat = site.selected_categories[0]
            return jsonify({
                'success': True,
                'category': next_cat['name'],
                'category_id': next_cat['id']
            })
        else:
            return jsonify({
                'success': False,
                'error': 'No categories selected',
                'code': 400
            }), 400

@sites_bp.route('/api/sites/<int:site_id>/prompts', methods=['GET'])
@require_jwt
def get_prompts(user_id, site_id):
    with db.get_session() as session:
        from database import WordPressSite
        site = session.query(WordPressSite).filter_by(id=site_id, user_id=user_id).first()
        if not site:
            return jsonify({'success': False, 'error': 'Site not found'}), 404
            
        default_article_prompt = """Buatkan artikel blog SEO-optimized berkualitas tinggi untuk website {site_name} tentang: {topic}
{existing_titles}{research_note}{seo_section}
TARGET AUDIENCE: Pembaca website {site_name}

⚠️ PENTING - TAHUN SAAT INI: 2026
- Jika menyebutkan tahun, gunakan 2026 atau "saat ini"
- Jangan gunakan tahun 2024 atau 2025

STRUKTUR ARTIKEL (2000-2500 KATA):

1. HOOK PEMBUKA (100 kata):
   ⚠️ WAJIB VARIATIF - Gunakan salah satu pendekatan ini:
   A. Story/Anekdot
   B. Problem Statement
   C. Pertanyaan Provokatif
   D. Fakta Mengejutkan
   E. Kontras
   ✓ Akhiri dengan promise: "Artikel ini akan memandu Anda..."

2. CONTEXT (200 kata):
   - Situasi saat ini terkait topik
   - Mengapa topik ini urgent dan penting
   - Siapa yang paling membutuhkan solusi ini

3. KONTEN UTAMA (1500-1700 kata):
   H2: Konsep Dasar & Pentingnya (300 kata)
   - Definisi clear dengan bahasa praktis
   - Mengapa ini critical
   - Contoh konkret
"""
        default_image_prompt = "Fotografi profesional, pencahayaan dramatis, gaya korporat modern, fokus tajam."
        
        return jsonify({
            'success': True,
            'article_prompt': site.article_prompt or default_article_prompt.replace('{site_name}', site.site_name),
            'image_prompt': site.image_prompt or default_image_prompt,
            'default_article_prompt': default_article_prompt.replace('{site_name}', site.site_name),
            'default_image_prompt': default_image_prompt
        })

@sites_bp.route('/api/sites/<int:site_id>/prompts', methods=['POST'])
@require_jwt
def save_prompts(user_id, site_id):
    data = request.json
    with db.get_session() as session:
        from database import WordPressSite
        site = session.query(WordPressSite).filter_by(id=site_id, user_id=user_id).first()
        if not site:
            return jsonify({'success': False, 'error': 'Site not found'}), 404
            
        site.article_prompt = data.get('article_prompt', '').strip() or None
        site.image_prompt = data.get('image_prompt', '').strip() or None
        session.commit()
        return jsonify({'success': True, 'message': 'Prompts saved!'})
