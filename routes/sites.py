import requests
from flask import Blueprint, request, jsonify
from core_extensions import db, logger, require_jwt, send_telegram_notification
from services.wp_publisher import WordPressPublisher
from services.url_safety import validate_public_http_url

sites_bp = Blueprint('sites', __name__)

MAX_SELECTED_CATEGORIES = 500
MAX_CATEGORIES = 500

def _secret_status(value):
    return bool(value)

def _should_update_secret(value):
    return isinstance(value, str) and bool(value.strip())


class _InvalidField(ValueError):
    pass


def _clean_str(data, key, max_len, allow_empty=True):
    """Return a stripped string (or None when blank) for data[key]."""
    value = data.get(key)
    if value is None:
        if not allow_empty:
            raise _InvalidField(f'{key} wajib diisi.')
        return None
    if not isinstance(value, str):
        raise _InvalidField(f'{key} harus berupa teks.')
    value = value.strip()
    if not value and not allow_empty:
        raise _InvalidField(f'{key} wajib diisi.')
    if len(value) > max_len:
        raise _InvalidField(f'{key} maksimal {max_len} karakter.')
    return value or None


def _clean_bool(data, key):
    value = data.get(key)
    if not isinstance(value, bool):
        raise _InvalidField(f'{key} harus bernilai true/false.')
    return value


def _clean_wordpress_url(value):
    ok, result = validate_public_http_url(value)
    if not ok:
        raise _InvalidField(f'URL WordPress tidak valid: {result}')
    return result


DEFAULT_SCHEDULE_HOURS = '0,6,12,18'


def _clean_schedule_hours(value):
    """Accept "0, 6, 12" or [0, 6, 12]; store the canonical "0,6,12" string.

    A blank string falls back to the default schedule (what the dispatcher
    used to do), and "07:00"-style tokens are read as the hour.
    """
    if isinstance(value, str):
        tokens = [t.strip() for t in value.split(',') if t.strip()]
        if not tokens:
            return DEFAULT_SCHEDULE_HOURS
        try:
            hours = [int(t[:-3] if t.endswith(':00') else t) for t in tokens]
        except ValueError:
            raise _InvalidField('Jadwal posting harus berupa jam 0-23 dipisahkan koma.')
    elif isinstance(value, list):
        if not all(isinstance(h, int) and not isinstance(h, bool) for h in value):
            raise _InvalidField('Jadwal posting harus berupa daftar jam 0-23.')
        hours = value
    else:
        raise _InvalidField('Jadwal posting harus berupa jam 0-23 dipisahkan koma.')
    if not hours or any(h < 0 or h > 23 for h in hours):
        raise _InvalidField('Jadwal posting harus berisi jam 0-23.')
    return ','.join(str(h) for h in sorted(set(hours)))


def _clean_timezone(value):
    from zoneinfo import ZoneInfo
    if not isinstance(value, str) or not value.strip() or len(value) > 100:
        raise _InvalidField('Timezone tidak valid.')
    try:
        ZoneInfo(value.strip())
    except Exception:
        raise _InvalidField('Timezone tidak valid.')
    return value.strip()


def _clean_language(value):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 10:
        raise _InvalidField('Bahasa tidak valid.')
    return value.strip()


def _clean_category_list(value, max_items, field):
    """Validate a list of WordPress categories, deduplicated by id.

    WordPress only requires names to be unique per parent, so two categories may
    share a name; the id is the real identity.
    """
    if value is None:
        return []
    if not isinstance(value, list):
        raise _InvalidField(f'{field} harus berupa daftar.')
    cleaned = []
    seen_ids = set()
    for cat in value:
        if not isinstance(cat, dict):
            raise _InvalidField(f'{field} berisi data kategori yang tidak valid.')
        cat_id = cat.get('id')
        name = cat.get('name')
        if not isinstance(cat_id, int) or isinstance(cat_id, bool):
            raise _InvalidField(f'{field}: id kategori harus berupa angka.')
        if not isinstance(name, str) or not name.strip():
            raise _InvalidField(f'{field}: nama kategori wajib diisi.')
        name = name.strip()[:200]
        if cat_id in seen_ids:
            continue
        seen_ids.add(cat_id)
        description = cat.get('description')
        count = cat.get('count')
        cleaned.append({
            'id': cat_id,
            'name': name,
            'description': description[:2000] if isinstance(description, str) else '',
            'count': count if isinstance(count, int) and not isinstance(count, bool) else 0,
        })
    if len(cleaned) > max_items:
        raise _InvalidField(f'{field} maksimal {max_items} kategori.')
    return cleaned

@sites_bp.route('/api/sites', methods=['GET'])
@require_jwt
def get_sites(user_id):
    with db.get_session() as session:
        from models import WordPressSite
        sites = session.query(WordPressSite).filter_by(user_id=user_id).order_by(WordPressSite.created_at.desc()).limit(100).all()
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
                'pinterest_enabled': site.pinterest_enabled,
                'pinterest_board_id': site.pinterest_board_id,
                'pinterest_access_token': '',
                'has_pinterest_access_token': _secret_status(site.pinterest_access_token),
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

                'gsc_connected': _secret_status(site.gsc_refresh_token),
                'gsc_client_id': site.gsc_client_id or '',
                'gsc_client_secret': '',
                'has_gsc_client_secret': _secret_status(site.gsc_client_secret),
                'gsc_property_url': site.gsc_property_url,
                'gsc_permission_level': site.gsc_permission_level,
                'gsc_connected_at': site.gsc_connected_at.isoformat() if site.gsc_connected_at else None,
                'gsc_last_synced_at': site.gsc_last_synced_at.isoformat() if site.gsc_last_synced_at else None,
                'gsc_last_error': site.gsc_last_error,

                'article_prompt': site.article_prompt,
                'image_prompt': site.image_prompt
            } for site in sites]
        })

@sites_bp.route('/api/sites', methods=['POST'])
@require_jwt
def create_site(user_id):
    data = request.get_json(silent=True) or {}
    if not data or not data.get('wordpress_url'):
        return jsonify({'success': False, 'error': 'WordPress URL is required'}), 400
        
    try:
        wordpress_url = _clean_wordpress_url(data.get('wordpress_url'))
        site_name = _clean_str(data, 'site_name', 200) or 'New Website'
        wordpress_username = _clean_str(data, 'wordpress_username', 200) or ''
        wordpress_password = data['wordpress_password'] if _should_update_secret(data.get('wordpress_password')) else ''
        schedule_hours = _clean_schedule_hours(data['schedule_hours']) if data.get('schedule_hours') is not None else DEFAULT_SCHEDULE_HOURS
        timezone_name = _clean_timezone(data['timezone']) if data.get('timezone') else 'Asia/Jakarta'
        language = _clean_language(data['language']) if data.get('language') else 'id'
        auto_post = _clean_bool(data, 'auto_post') if data.get('auto_post') is not None else False
        gsc_client_id = _clean_str(data, 'gsc_client_id', 500)
    except _InvalidField as exc:
        return jsonify({'success': False, 'error': str(exc)}), 400

    with db.get_session() as session:
        from models import WordPressSite
        site = WordPressSite(
            user_id=user_id,
            site_name=site_name,
            wordpress_url=wordpress_url,
            wordpress_username=wordpress_username,
            wordpress_password=wordpress_password, # Virtual setter

            schedule_hours=schedule_hours,
            timezone=timezone_name,
            language=language,
            auto_post=auto_post
        )
        if gsc_client_id:
            site.gsc_client_id = gsc_client_id
        if _should_update_secret(data.get('gsc_client_secret')):
            site.gsc_client_secret = data['gsc_client_secret']
        session.add(site)
        session.commit()
        return jsonify({'success': True, 'site_id': site.id, 'message': 'Site added successfully'})

@sites_bp.route('/api/sites/<int:site_id>', methods=['PUT'])
@require_jwt
def update_site(user_id, site_id):
    data = request.get_json(silent=True) or {}
    # Validate and normalize every typed field before touching the row, so a
    # malformed request cannot store data that later crashes the scheduler or
    # the article jobs.
    # The Sites page sends the whole site object back, so a null value for a
    # typed field means "unchanged" rather than "invalid".
    def present(key):
        return key in data and data[key] is not None

    clean = {}
    try:
        if 'site_name' in data: clean['site_name'] = _clean_str(data, 'site_name', 200, allow_empty=False)
        if 'wordpress_username' in data: clean['wordpress_username'] = _clean_str(data, 'wordpress_username', 200) or ''
        if present('schedule_hours'): clean['schedule_hours'] = _clean_schedule_hours(data['schedule_hours'])
        if present('timezone'): clean['timezone'] = _clean_timezone(data['timezone'])
        if present('language'): clean['language'] = _clean_language(data['language'])
        if present('categories'): clean['categories'] = _clean_category_list(data['categories'], MAX_CATEGORIES, 'categories')
        if present('selected_categories'):
            clean['selected_categories'] = _clean_category_list(data['selected_categories'], MAX_SELECTED_CATEGORIES, 'selected_categories')
        if 'gsc_client_id' in data: clean['gsc_client_id'] = _clean_str(data, 'gsc_client_id', 500)
        for key in ('article_prompt', 'image_prompt'):
            if key in data: clean[key] = _clean_str(data, key, 50000)
        for key in ('telegram_chat_id', 'telegram_channel_id', 'facebook_page_id', 'pinterest_board_id', 'threads_user_id'):
            if key in data: clean[key] = _clean_str(data, key, 200)
        for key in ('auto_post', 'telegram_enabled', 'telegram_post_to_channel', 'facebook_enabled',
                    'pinterest_enabled', 'twitter_enabled', 'threads_enabled', 'is_active'):
            if present(key): clean[key] = _clean_bool(data, key)
    except _InvalidField as exc:
        return jsonify({'success': False, 'error': str(exc)}), 400

    with db.get_session() as session:
        from models import WordPressSite, SearchConsoleMetric
        site = session.query(WordPressSite).filter_by(id=site_id, user_id=user_id).first()
        if not site:
            return jsonify({'success': False, 'error': 'Site not found'}), 404

        if 'wordpress_url' in data and data['wordpress_url'] != site.wordpress_url:
            # Only a changed URL is resolved here, so a transient DNS failure
            # does not block unrelated edits; server-side fetches re-validate.
            try:
                clean['wordpress_url'] = _clean_wordpress_url(data['wordpress_url'])
            except _InvalidField as exc:
                return jsonify({'success': False, 'error': str(exc)}), 400

        # Update basic info
        if 'site_name' in clean: site.site_name = clean['site_name']
        if 'wordpress_url' in clean: site.wordpress_url = clean['wordpress_url']
        if 'wordpress_username' in clean: site.wordpress_username = clean['wordpress_username']
        if 'wordpress_password' in data and _should_update_secret(data['wordpress_password']):
            site.wordpress_password = data['wordpress_password']

        # Update schedule

        if 'schedule_hours' in clean: site.schedule_hours = clean['schedule_hours']
        if 'timezone' in clean: site.timezone = clean['timezone']
        if 'language' in clean: site.language = clean['language']
        if 'auto_post' in clean: site.auto_post = clean['auto_post']

        # Update categories
        if 'categories' in clean: site.categories = clean['categories']
        if 'selected_categories' in clean: site.selected_categories = clean['selected_categories']

        # Per-website Search Console OAuth credentials. Blank secret means keep
        # the encrypted value already stored.
        gsc_credentials_changed = False
        if 'gsc_client_id' in clean:
            new_client_id = clean['gsc_client_id']
            if new_client_id != site.gsc_client_id:
                site.gsc_client_id = new_client_id
                gsc_credentials_changed = True
        if 'gsc_client_secret' in data and _should_update_secret(data['gsc_client_secret']):
            if data['gsc_client_secret'] != site.gsc_client_secret:
                site.gsc_client_secret = data['gsc_client_secret']
                gsc_credentials_changed = True
        if gsc_credentials_changed:
            # Refresh tokens belong to one OAuth client and cannot safely be
            # reused after its credentials change.
            site.gsc_refresh_token = None
            site.gsc_property_url = None
            site.gsc_permission_level = None
            site.gsc_connected_at = None
            site.gsc_last_error = None
            # Metrics synced through the old OAuth client may belong to another
            # Google account/property; do not keep serving them.
            session.query(SearchConsoleMetric).filter_by(
                user_id=user_id, site_id=site_id
            ).delete(synchronize_session=False)
            site.gsc_last_synced_at = None

        # Prompts
        if 'article_prompt' in clean: site.article_prompt = clean['article_prompt']
        if 'image_prompt' in clean: site.image_prompt = clean['image_prompt']

        # Update social
        if 'telegram_bot_token' in data and _should_update_secret(data['telegram_bot_token']): site.telegram_bot_token = data['telegram_bot_token']
        if 'telegram_chat_id' in clean: site.telegram_chat_id = clean['telegram_chat_id']
        if 'telegram_channel_id' in clean: site.telegram_channel_id = clean['telegram_channel_id']
        if 'telegram_enabled' in clean: site.telegram_enabled = clean['telegram_enabled']
        if 'telegram_post_to_channel' in clean: site.telegram_post_to_channel = clean['telegram_post_to_channel']

        if 'facebook_page_id' in clean: site.facebook_page_id = clean['facebook_page_id']
        if 'facebook_access_token' in data and _should_update_secret(data['facebook_access_token']): site.facebook_access_token = data['facebook_access_token']
        if 'facebook_enabled' in clean: site.facebook_enabled = clean['facebook_enabled']

        if 'pinterest_board_id' in clean: site.pinterest_board_id = clean['pinterest_board_id']
        if 'pinterest_access_token' in data and _should_update_secret(data['pinterest_access_token']): site.pinterest_access_token = data['pinterest_access_token']
        if 'pinterest_enabled' in clean: site.pinterest_enabled = clean['pinterest_enabled']
        
        if 'twitter_api_key' in data and _should_update_secret(data['twitter_api_key']): site.twitter_api_key = data['twitter_api_key']
        if 'twitter_api_secret' in data and _should_update_secret(data['twitter_api_secret']): site.twitter_api_secret = data['twitter_api_secret']
        if 'twitter_access_token' in data and _should_update_secret(data['twitter_access_token']): site.twitter_access_token = data['twitter_access_token']
        if 'twitter_access_secret' in data and _should_update_secret(data['twitter_access_secret']): site.twitter_access_secret = data['twitter_access_secret']
        if 'twitter_enabled' in clean: site.twitter_enabled = clean['twitter_enabled']

        if 'threads_user_id' in clean: site.threads_user_id = clean['threads_user_id']
        if 'threads_access_token' in data and _should_update_secret(data['threads_access_token']): site.threads_access_token = data['threads_access_token']
        if 'threads_enabled' in clean: site.threads_enabled = clean['threads_enabled']


        if 'is_active' in clean: site.is_active = clean['is_active']
        
        session.commit()
        return jsonify({'success': True, 'message': 'Site updated successfully'})

@sites_bp.route('/api/sites/<int:site_id>', methods=['DELETE'])
@require_jwt
def delete_site(user_id, site_id):
    with db.get_session() as session:
        from models import WordPressSite
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
        from models import WordPressSite
        site = session.query(WordPressSite).filter_by(id=site_id, user_id=user_id).first()
        if not site:
            return jsonify({'success': False, 'error': 'Site not found'}), 404
            
        if not site.wordpress_url or not site.wordpress_username or not site.wordpress_password:
            return jsonify({'success': False, 'error': 'Mohon isi kredensial WordPress terlebih dahulu.'}), 400
        
        # Re-validate the stored URL: it may predate URL validation, and DNS
        # can change after it was saved.
        url_ok, url_or_error = validate_public_http_url(site.wordpress_url)
        if not url_ok:
            return jsonify({'success': False, 'error': f'URL WordPress tidak valid: {url_or_error}'}), 400

        try:
            publisher = WordPressPublisher(
                url_or_error,
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
                    matching = next((c for c in categories if c['id'] == sel_cat.get('id')), None)
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
            return jsonify({'success': False, 'error': 'Terjadi kesalahan saat mengambil kategori.'}), 500

@sites_bp.route("/api/sites/<int:site_id>/test-telegram", methods=["POST"])
@require_jwt
def test_telegram(user_id, site_id):
    with db.get_session() as session:
        from models import WordPressSite
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
        from models import WordPressSite
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
        from models import WordPressSite
        site = session.query(WordPressSite).filter_by(id=site_id, user_id=user_id).first()
        if not site:
            return jsonify({'success': False, 'error': 'Site not found'}), 404
            
        default_article_prompt = """Buatkan artikel blog SEO-optimized berkualitas tinggi untuk website {site_name} tentang: {topic}
{existing_titles}{research_note}{seo_section}
TARGET AUDIENCE: Pembaca website {site_name}

⚠️ PENTING - TAHUN SAAT INI: 2026
- Jika menyebutkan tahun, gunakan 2026 atau "saat ini"
- Jangan gunakan tahun 2024 atau 2025

STRUKTUR ARTIKEL (MINIMAL 2000-2500 KATA - SANGAT WAJIB!):
⚠️ TULIS DENGAN SANGAT MENDETAIL DAN PANJANG. JANGAN MERINGKAS. SETIAP SUB-HEADING HARUS TERDIRI DARI MINIMAL 4-5 PARAGRAF PANJANG DAN KOMPREHENSIF. BENTUKLAH ARTIKEL YANG SANGAT DALAM. JIKA KURANG DARI 2000 KATA, ARTIKEL INI AKAN DITOLAK.

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
    data = request.get_json(silent=True) or {}
    with db.get_session() as session:
        from models import WordPressSite
        site = session.query(WordPressSite).filter_by(id=site_id, user_id=user_id).first()
        if not site:
            return jsonify({'success': False, 'error': 'Site not found'}), 404
            
        article_prompt = data.get('article_prompt')
        image_prompt = data.get('image_prompt')
        site.article_prompt = (article_prompt.strip() or None) if isinstance(article_prompt, str) else None
        site.image_prompt = (image_prompt.strip() or None) if isinstance(image_prompt, str) else None
        session.commit()
        return jsonify({'success': True, 'message': 'Prompts saved!'})
