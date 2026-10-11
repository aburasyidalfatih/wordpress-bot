import html as html_module
import os
import secrets
import sys
import logging
import threading
import uuid
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler
from functools import wraps
from time import time
import jwt
import requests
from flask import request, jsonify
from redis import Redis
from rq import Queue

from database import Database
from ml_optimizer import ContentOptimizer
from trending_research import TrendingResearch
from config import Config, DEFAULT_GEMINI_MODEL, DEFAULT_GEMINI_IMAGE_MODEL

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        RotatingFileHandler(Config.LOG_FILE, maxBytes=Config.LOG_MAX_BYTES, backupCount=Config.LOG_BACKUP_COUNT),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Initialize Redis & Queue
redis_conn = Redis.from_url(Config.REDIS_URL, protocol=2)
q = Queue('default', connection=redis_conn)

# Initialize database using Config
db = Database(Config.DATABASE_URL)

optimizer = ContentOptimizer(db)
trending = TrendingResearch()

# Cache settings. Both caches are LRU-bounded so they cannot grow without limit
# as the number of users increases (each gunicorn worker holds its own copy).
CACHE_TTL_SECONDS = 5
CACHE_MAX_ENTRIES = 512

_config_cache = OrderedDict()
_stats_cache = OrderedDict()


def _cache_get(cache, key):
    """Return the cached value for key if it is still fresh, else None."""
    entry = cache.get(key)
    if entry and time() - entry['timestamp'] < CACHE_TTL_SECONDS:
        cache.move_to_end(key)
        return entry['data']
    return None


def _cache_put(cache, key, value):
    cache[key] = {'data': value, 'timestamp': time()}
    cache.move_to_end(key)
    while len(cache) > CACHE_MAX_ENTRIES:
        cache.popitem(last=False)


def _get_admin_user_id():
    """Return the id of the admin account, or None if there is no admin."""
    try:
        from models import User
        with db.get_session() as session:
            admin = session.query(User).filter_by(role='admin').order_by(User.id).first()
            return admin.id if admin else None
    except Exception as e:
        logger.error(f"Error querying admin user: {e}")
        return None


def load_config(user_id=None):
    """Load configuration for the specific user.
    Falls back to the admin account if user_id is not provided.
    """
    # RQ workers never run app.py's startup loader; this also picks up admin
    # setting changes made in another process (throttled, cheap).
    refresh_system_settings_if_changed()

    target_id = user_id
    if target_id is None:
        target_id = _get_admin_user_id()

    if target_id is None:
        logger.error("load_config: no user_id given and no admin account exists.")
        return {'gemini_api_key': '', 'gemini_model': DEFAULT_GEMINI_MODEL,
                'gemini_image_model': DEFAULT_GEMINI_IMAGE_MODEL}

    cached = _cache_get(_config_cache, target_id)
    if cached is not None:
        return cached

    config = db.get_config(target_id)

    # Fall back to the admin's API key if this user has none of their own.
    if not config.get('gemini_api_key'):
        admin_id = _get_admin_user_id()
        if admin_id is not None and admin_id != target_id:
            admin_config = db.get_config(admin_id)
            if admin_config and admin_config.get('gemini_api_key'):
                config['gemini_api_key'] = admin_config['gemini_api_key']

    _cache_put(_config_cache, target_id, config)
    return config


def get_cached_stats(user_id, site_id=None):
    cache_key = f"{user_id}_{site_id}" if site_id else str(user_id)

    cached = _cache_get(_stats_cache, cache_key)
    if cached is not None:
        return cached

    stats = db.get_stats(user_id, site_id=site_id)
    _cache_put(_stats_cache, cache_key, stats)
    return stats

def save_config(user_id, config_data):
    # If the user is saving, check if they are the admin, but this save_config is used on db.
    # The route handler will enforce the admin check.
    db.save_config(user_id, config_data)
    _config_cache.clear()


# ---- System settings (admin-editable, shared by every process) ----
# Admin saves land in the system_settings table. Each gunicorn worker / RQ worker
# keeps its own copy in Config + os.environ, so a version row is bumped on save and
# every process re-applies the table when it sees a new version.
SETTINGS_VERSION_KEY = '__settings_version__'
SETTINGS_REFRESH_INTERVAL_SECONDS = 5
_BOOL_SYSTEM_SETTINGS = ('PAYMENT_TRIPAY_ENABLED', 'PAYMENT_PAYPAL_ENABLED', 'PAYMENT_MANUAL_ENABLED')
_NOT_LOADED = object()
_settings_state = {'version': _NOT_LOADED, 'checked_at': 0.0}
_settings_lock = threading.Lock()


def apply_system_settings(system_settings):
    """Copy system_settings rows onto Config and os.environ."""
    applied = 0
    for k, v in system_settings.items():
        if k.startswith('__'):
            continue  # internal bookkeeping (e.g. __schema_version__), not app config
        if v is None:
            continue
        if k in _BOOL_SYSTEM_SETTINGS:
            setattr(Config, k, str(v).lower() == 'true')
        elif k == 'SMTP_PORT':
            try:
                setattr(Config, k, int(v))
            except ValueError:
                continue
        elif k == 'PAYMENT_USD_RATE':
            try:
                rate = float(v)
            except ValueError:
                continue
            if rate <= 0:
                continue
            setattr(Config, k, rate)
        else:
            setattr(Config, k, v)
        os.environ[k] = str(v)
        applied += 1
    return applied


def load_system_settings():
    """Load every system setting into Config. Returns the settings version seen."""
    system_settings = db.get_system_settings()
    applied = apply_system_settings(system_settings)
    version = system_settings.get(SETTINGS_VERSION_KEY)
    _settings_state['version'] = version
    _settings_state['checked_at'] = time()
    logger.info(f"Loaded {applied} system settings from database.")
    return version


def _read_settings_version():
    from sqlalchemy import text
    with db.get_session() as session:
        return session.execute(
            text("SELECT value FROM system_settings WHERE key = :k"),
            {'k': SETTINGS_VERSION_KEY}
        ).scalar()


def bump_settings_version():
    """Signal every process that system settings changed."""
    db.save_system_settings({SETTINGS_VERSION_KEY: uuid.uuid4().hex})


def refresh_system_settings_if_changed(force=False):
    """Cheap, throttled check for settings saved by another process."""
    now = time()
    if not force and now - _settings_state['checked_at'] < SETTINGS_REFRESH_INTERVAL_SECONDS:
        return False
    if not _settings_lock.acquire(blocking=False):
        return False  # another thread of this worker is already checking
    try:
        if not force and time() - _settings_state['checked_at'] < SETTINGS_REFRESH_INTERVAL_SECONDS:
            return False
        _settings_state['checked_at'] = time()
        try:
            version = _read_settings_version()
        except Exception as e:
            logger.warning(f"Could not read system settings version: {e}")
            return False
        if version == _settings_state['version']:
            return False
        load_system_settings()
        _config_cache.clear()
        return True
    except Exception as e:
        logger.error(f"Failed to refresh system settings: {e}")
        return False
    finally:
        _settings_lock.release()


# ---- Access tokens ----
ACCESS_TOKEN_TYPE = 'access'
ACCESS_TOKEN_TTL = timedelta(days=7)
USER_AUTH_CACHE_TTL_SECONDS = 5
_user_auth_cache = OrderedDict()


def _tokens_valid_after_key(user_id):
    return f"user:{user_id}:tokens_valid_after"


def issue_access_token(user_id):
    """Create a login token. 'iat' lets logout / password change revoke it."""
    now = datetime.now(timezone.utc)
    return jwt.encode({
        'user_id': user_id,
        'typ': ACCESS_TOKEN_TYPE,
        'iat': now,
        'exp': now + ACCESS_TOKEN_TTL,
        'jti': secrets.token_urlsafe(16),
    }, Config.SECRET_KEY, algorithm='HS256')


def _revoked_jti_key(jti):
    return f"revoked_jti:{jti}"


def revoke_token(payload):
    """Invalidate one token (this device only), e.g. on logout.

    Tokens issued before 'jti' existed cannot be singled out, so those fall back
    to revoking every token of the user.
    """
    jti = payload.get('jti')
    if not jti:
        revoke_user_tokens(payload['user_id'])
        return
    ttl = int(payload.get('exp') or 0) - int(time())
    if ttl <= 0:
        return
    try:
        redis_conn.set(_revoked_jti_key(jti), 1, ex=ttl)
    except Exception as e:
        logger.error(f"Could not revoke token for user {payload.get('user_id')}: {e}")


def revoke_user_tokens(user_id):
    """Invalidate every token issued to user_id up to now."""
    try:
        redis_conn.set(
            _tokens_valid_after_key(user_id),
            int(time()),
            ex=int(ACCESS_TOKEN_TTL.total_seconds()) + 86400
        )
    except Exception as e:
        logger.error(f"Could not revoke tokens for user {user_id}: {e}")
    _user_auth_cache.pop(user_id, None)


def decode_access_token(token):
    """Decode a login token. Rejects tokens minted for another purpose (e.g. OAuth state)."""
    payload = jwt.decode(token, Config.SECRET_KEY, algorithms=['HS256'])
    if 'purpose' in payload:
        raise jwt.InvalidTokenError('Token is not a login token')
    # Tokens issued before 'typ' existed have no typ claim and are still accepted.
    if payload.get('typ', ACCESS_TOKEN_TYPE) != ACCESS_TOKEN_TYPE:
        raise jwt.InvalidTokenError('Token is not a login token')
    user_id = payload.get('user_id')
    if not isinstance(user_id, int) or isinstance(user_id, bool) or user_id <= 0:
        raise jwt.InvalidTokenError('Invalid user_id in token')
    return payload


def _user_auth_state(user_id):
    """Return {'is_active', 'role', 'valid_after'} or None if the user is gone.

    Cached per worker for a few seconds so this costs at most one query per user
    per USER_AUTH_CACHE_TTL_SECONDS.
    """
    entry = _user_auth_cache.get(user_id)
    if entry and time() - entry['timestamp'] < USER_AUTH_CACHE_TTL_SECONDS:
        return entry['data']

    from models import User
    with db.get_session() as session:
        row = session.query(User.is_active, User.role).filter(User.id == user_id).first()
    state = None
    if row is not None:
        valid_after = 0
        try:
            raw = redis_conn.get(_tokens_valid_after_key(user_id))
            if raw:
                valid_after = int(raw)
        except Exception as e:
            # Fail open on a Redis outage rather than locking every user out.
            logger.warning(f"Could not read token revocation state for user {user_id}: {e}")
        state = {'is_active': bool(row.is_active), 'role': row.role, 'valid_after': valid_after}

    _user_auth_cache[user_id] = {'data': state, 'timestamp': time()}
    _user_auth_cache.move_to_end(user_id)
    while len(_user_auth_cache) > CACHE_MAX_ENTRIES:
        _user_auth_cache.popitem(last=False)
    return state


def authenticate_token(token):
    """Return the user_id for a valid, unrevoked login token of an active user, else None."""
    try:
        payload = decode_access_token(token)
    except Exception as e:
        logger.warning(f'JWT decode failed: {e}')
        return None
    user_id = payload['user_id']
    state = _user_auth_state(user_id)
    if not state or not state['is_active']:
        return None
    if state['valid_after'] and int(payload.get('iat') or 0) < state['valid_after']:
        return None
    jti = payload.get('jti')
    if jti:
        try:
            if redis_conn.exists(_revoked_jti_key(jti)):
                return None
        except Exception as e:
            # Fail open on a Redis outage, like the per-user revocation check.
            logger.warning(f"Could not read token revocation state: {e}")
    return user_id


def get_request_token():
    token = request.cookies.get('auth_token')
    auth_header = request.headers.get('Authorization')
    if not token and auth_header and auth_header.startswith('Bearer '):
        token = auth_header.split(' ', 1)[1]
    return token


# JWT decorator
def require_jwt(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = get_request_token()

        logger.debug(f"JWT Check for path: {request.path}, token_present: {bool(token)}")
        if not token:
            return jsonify({'success': False, 'error': 'Missing or invalid token'}), 401

        try:
            user_id = authenticate_token(token)
        except Exception as e:
            logger.error(f'JWT user lookup failed: {e}')
            return jsonify({'success': False, 'error': 'Authentication temporarily unavailable'}), 503
        if not user_id:
            return jsonify({'success': False, 'error': 'Invalid or expired token'}), 401

        return f(user_id, *args, **kwargs)

    return decorated_function

# Admin decorator
def require_admin(f):
    @wraps(f)
    @require_jwt
    def decorated_function(user_id, *args, **kwargs):
        from models import User
        with db.get_session() as session:
            user = session.query(User).filter_by(id=user_id).first()
            if not user or user.role != 'admin':
                return jsonify({'success': False, 'error': 'Admin privilege required'}), 403
        return f(user_id, *args, **kwargs)
    return decorated_function

# Social media posting helpers
def send_telegram_notification(config, message):
    """Send notification to Telegram"""
    if not config.get('telegram_enabled'):
        return False
    
    bot_token = config.get('telegram_bot_token')
    chat_id = config.get('telegram_chat_id')
    
    if not bot_token or not chat_id:
        return False
    
    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        data = {
            'chat_id': chat_id,
            'text': message,
            'parse_mode': 'HTML'
        }
        response = requests.post(url, data=data, timeout=10)
        return response.status_code == 200
    except Exception as e:
        logger.error(f"Telegram notification error: {e}")
        return False

def post_to_telegram_channel(config, article, post_url, image_data=None):
    """Post article to Telegram channel"""
    if not config.get('telegram_post_to_channel'):
        return False
    
    bot_token = config.get('telegram_bot_token')
    channel_id = config.get('telegram_channel_id')
    
    if not bot_token or not channel_id:
        logger.warning("Telegram channel: Missing bot_token or channel_id")
        return False
    
    # Ensure channel_id has @ prefix if it's a username
    if not channel_id.startswith('@') and not channel_id.startswith('-'):
        channel_id = f"@{channel_id}"
    
    try:
        import re
        title = html_module.escape(article.get('title', ''))
        excerpt = article.get('excerpt', '')
        excerpt_clean = re.sub('<[^<]+?>', '', excerpt).strip()[:400]
        language = config.get('language', 'id')
        read_more_text = "Read the full article:" if language == 'en' else "Baca artikel lengkap"
        
        keyword = article.get('focus_keyword', '').replace(' ', '').title()
        hashtags = f"#{keyword}" if keyword else ""
        
        message = f"""📰 <b>{title}</b>\n\n{excerpt_clean}...\n\n👉 <a href="{post_url}">{read_more_text}</a>\n\n{hashtags}"""
        
        # M9: Truncate caption to Telegram's 1024-char limit for photo captions
        if len(message) > 1024:
            message = message[:1021] + '...'
        
        if image_data:
            url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
            files = {'photo': ('image.jpg', image_data.getvalue(), 'image/jpeg')}
            data = {
                'chat_id': channel_id,
                'caption': message,
                'parse_mode': 'HTML'
            }
            response = requests.post(url, data=data, files=files, timeout=30)
        else:
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            data = {
                'chat_id': channel_id,
                'text': message,
                'parse_mode': 'HTML',
                'disable_web_page_preview': False
            }
            response = requests.post(url, data=data, timeout=10)
        
        if response.status_code == 200:
            logger.info(f"Telegram channel post successful to {channel_id}")
            return True
        else:
            logger.error(f"Telegram channel post failed: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        logger.error(f"Telegram channel post error: {e}")
        return False

def post_to_facebook_page(config, article, post_url, image_data=None):
    """Post article to Facebook Page with image and engaging long caption"""
    if not config.get('facebook_enabled'):
        logger.info("Facebook posting disabled")
        return False
    
    page_id = config.get('facebook_page_id')
    access_token = config.get('facebook_access_token')
    
    if not page_id or not access_token:
        logger.warning("Facebook Page ID or Access Token not configured")
        return False
    
    try:
        import re
        import html
        
        # Get content - handle both dict and string
        content = article.get('content', '')
        if isinstance(content, dict):
            content = content.get('rendered', '')
        
        # Remove HTML tags
        content_clean = re.sub('<[^<]+?>', '', content)
        # Decode HTML entities (&#8216; -> ')
        content_clean = html.unescape(content_clean)
        # Remove extra whitespace
        content_clean = re.sub(r'\s+', ' ', content_clean).strip()
        
        # Split by sentence to get proper paragraphs
        sentences = re.split(r'(?<=[.!?])\s+', content_clean)
        
        # Build 3 paragraphs (3-4 sentences each)
        paragraphs = []
        current_para = []
        sentence_count = 0
        
        for sentence in sentences:
            if len(sentence.strip()) < 20:  # Skip very short sentences
                continue
            current_para.append(sentence.strip())
            sentence_count += 1
            
            # Complete paragraph after 3-4 sentences
            if sentence_count >= 3:
                para_text = ' '.join(current_para)
                if len(para_text) > 100:  # Only add if substantial
                    paragraphs.append(para_text)
                    current_para = []
                    sentence_count = 0
                    
                if len(paragraphs) >= 3:  # Stop after 3 paragraphs
                    break
        
        # If we have remaining sentences, add as last paragraph
        if current_para and len(paragraphs) < 3:
            paragraphs.append(' '.join(current_para))
        
        # Take only first 3 paragraphs
        first_3_paragraphs = '\n\n'.join(paragraphs[:3])
        
        # If no paragraphs found, use excerpt
        if not first_3_paragraphs:
            excerpt = article.get('excerpt', '')
            first_3_paragraphs = html.unescape(re.sub('<[^<]+?>', '', excerpt).strip()[:500])
            
        keyword = article.get('focus_keyword', '').replace(' ', '').title()
        hashtags = f"#{keyword}" if keyword else ""
        
        # Build message: Just 3 paragraphs + hashtags (NO title, NO link)
        message = f"{first_3_paragraphs.strip()}\n\n{hashtags}"
        
        # Get image URL from WordPress post
        image_url = None
        if post_url:
            try:
                resp = requests.get(post_url, timeout=5)
                img_match = re.search(r'<meta property="og:image" content="([^"]+)"', resp.text)
                if img_match:
                    image_url = img_match.group(1)
            except Exception:
                pass
        
        # Post with photo
        post_id = None
        if image_url:
            url = f"https://graph.facebook.com/v18.0/{page_id}/photos"
            data = {
                'access_token': access_token,
                'message': message,
                'url': image_url
            }
            response = requests.post(url, data=data, timeout=30)
        else:
            # Fallback to feed post without link
            url = f"https://graph.facebook.com/v18.0/{page_id}/feed"
            data = {
                'access_token': access_token,
                'message': message
            }
            response = requests.post(url, data=data, timeout=10)
        
        if response.status_code == 200:
            post_id = response.json().get('id')
            logger.info(f"Facebook post successful to Page ID: {page_id}, Post ID: {post_id}")
            
            # Post link as comment
            if post_id and post_url:
                try:
                    language = config.get('language', 'id')
                    read_more_text = "Read the full article:" if language == 'en' else "Baca artikel lengkapnya:"
                    comment_url = f"https://graph.facebook.com/v18.0/{post_id}/comments"
                    comment_data = {
                        'access_token': access_token,
                        'message': f"📖 {read_more_text}\n{post_url}"
                    }
                    comment_response = requests.post(comment_url, data=comment_data, timeout=10)
                    if comment_response.status_code == 200:
                        logger.info(f"Facebook comment with link posted successfully")
                    else:
                        logger.warning(f"Facebook comment failed: {comment_response.text}")
                except Exception as e:
                    logger.error(f"Facebook comment error: {e}")
            
            return True
        else:
            logger.error(f"Facebook post failed: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        logger.error(f"Facebook post error: {e}")
        return False

def post_to_pinterest(config, article, post_url, image_data=None):
    """Post article to Pinterest Board with image and description"""
    if not config.get('pinterest_enabled'):
        logger.info("Pinterest posting disabled")
        return False
    
    board_id = config.get('pinterest_board_id')
    access_token = config.get('pinterest_access_token')
    
    if not board_id or not access_token:
        logger.warning("Pinterest Board ID or Access Token not configured")
        return False
        
    if not image_data:
        logger.warning("Pinterest requires an image, but no image data was provided")
        return False
        
    try:
        import html
        import base64
        
        # Get content - handle both dict and string
        content = article.get('content', '')
        if isinstance(content, dict):
            content = content.get('rendered', '')
            
        title = article.get('title', '')
        if isinstance(title, dict):
            title = title.get('rendered', '')
        
        title = html.unescape(title)
        
        # We can extract a description from excerpt or just use the title
        description = html.unescape(article.get('excerpt', title))
        # Remove HTML from description
        import re
        description = re.sub('<[^<]+>', '', description).strip()
        if len(description) > 490:
            description = description[:490] + '...'
            
        # Encode image to base64
        img_bytes = image_data.getvalue()
        base64_img = base64.b64encode(img_bytes).decode('utf-8')
        
        url = "https://api.pinterest.com/v5/pins"
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }
        
        payload = {
            "board_id": board_id,
            "title": title[:100],  # Pinterest title max length is 100
            "description": description,
            "link": post_url,
            "media_source": {
                "source_type": "image_base64",
                "content_type": "image/jpeg",
                "data": base64_img
            }
        }
        
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        
        if response.status_code in (200, 201):
            pin_data = response.json()
            pin_id = pin_data.get('id')
            logger.info(f"Pinterest post successful to Board ID: {board_id}, Pin ID: {pin_id}")
            return True
        else:
            logger.error(f"Pinterest post failed: {response.status_code} - {response.text}")
            return False
            
    except Exception as e:
        logger.error(f"Pinterest post error: {e}")
        return False

def post_to_twitter(config, article, post_url, image_data=None):
    """Post article to Twitter/X"""
    if not config.get('twitter_enabled'):
        return False
    
    api_key = config.get('twitter_api_key')
    api_secret = config.get('twitter_api_secret')
    access_token = config.get('twitter_access_token')
    access_secret = config.get('twitter_access_secret')
    
    if not all([api_key, api_secret, access_token, access_secret]):
        return False
    
    try:
        import tweepy
        import re
        
        client = tweepy.Client(
            consumer_key=api_key,
            consumer_secret=api_secret,
            access_token=access_token,
            access_token_secret=access_secret
        )
        
        title = article.get('title', '')
        excerpt = article.get('excerpt', '')
        excerpt_clean = re.sub('<[^<]+?>', '', excerpt).strip()[:200]
        
        keyword = article.get('focus_keyword', '').replace(' ', '').title()
        hashtags = f"#{keyword}" if keyword else ""
        
        tweet = f"{title}\n\n{excerpt_clean}...\n\n{post_url}\n\n{hashtags}"
        
        if len(tweet) > 280:
            tweet = f"{title[:100]}...\n\n{post_url}\n\n{hashtags}"
            
        response = client.create_tweet(text=tweet)
        logger.info(f"Twitter post successful, Tweet ID: {response.data.get('id')}")
        return True
    except Exception as e:
        logger.error(f"Twitter post error: {e}")
        return False

def post_to_threads(config, article, post_url, image_data=None):
    """Post article to Threads with 1 paragraph + image, link in comment"""
    if not config.get('threads_enabled'):
        return False
    
    user_id = config.get('threads_user_id')
    access_token = config.get('threads_access_token')
    
    if not user_id or not access_token:
        return False
    
    try:
        import re
        import html
        
        # Get content - handle both dict and string
        content = article.get('content', '')
        if isinstance(content, dict):
            content = content.get('rendered', '')
        
        # Get excerpt or fallback to first paragraph
        excerpt = article.get('excerpt', '')
        if excerpt:
            content_clean = html.unescape(re.sub('<[^<]+?>', '', excerpt)).strip()
            first_paragraph = content_clean
        else:
            # Fallback
            content_clean = re.sub('<[^<]+?>', '', content)
            content_clean = html.unescape(content_clean)
            content_clean = re.sub(r'\s+', ' ', content_clean).strip()
            sentences = re.split(r'(?<=[.!?])\s+', content_clean)
            first_para_sentences = [s.strip() for s in sentences[:4] if len(s.strip()) > 20]
            first_paragraph = ' '.join(first_para_sentences[:3])
            
        keyword = article.get('focus_keyword', '').replace(' ', '').title()
        hashtags = f"#{keyword}" if keyword else ""
        
        language = config.get('language', 'id')
        read_more_text = "Read more:" if language == 'en' else "Baca selengkapnya:"
        
        # Build text: engaging excerpt + link + dynamic hashtags
        text = f"{first_paragraph}\n\n📖 {read_more_text}\n{post_url}\n\n{hashtags}"
        
        # Limit to 500 chars (Threads limit)
        if len(text) > 500:
            text = first_paragraph[:430] + f"...\n\n📖 {post_url}\n\n{hashtags}"
        
        # Get image URL from WordPress post
        image_url = None
        if post_url:
            try:
                resp = requests.get(post_url, timeout=5)
                img_match = re.search(r'<meta property="og:image" content="([^"]+)"', resp.text)
                if img_match:
                    image_url = img_match.group(1)
            except Exception:
                pass
        
        # Step 1: Create container
        url = f"https://graph.threads.net/v1.0/{user_id}/threads"
        if image_url:
            post_data = {
                'media_type': 'IMAGE',
                'image_url': image_url,
                'text': text,
                'access_token': access_token
            }
        else:
            post_data = {
                'media_type': 'TEXT',
                'text': text,
                'access_token': access_token
            }
            
        response = requests.post(url, data=post_data, timeout=30)
        if response.status_code != 200:
            logger.error(f"Threads container failed: {response.text}")
            return False
            
        creation_id = response.json().get('id')
        
        # Step 2: Publish container
        url = f"https://graph.threads.net/v1.0/{user_id}/threads_publish"
        publish_data = {
            'creation_id': creation_id,
            'access_token': access_token
        }
        response = requests.post(url, data=publish_data, timeout=30)
        
        if response.status_code == 200:
            logger.info(f"Threads post successful, Post ID: {response.json().get('id')}")
            return True
        else:
            logger.error(f"Threads publish failed: {response.text}")
            return False
    except Exception as e:
        logger.error(f"Threads post error: {e}")
        return False

def send_email_notification(to_email, subject, body_text):
    """Send an email notification using SMTP Mailketing"""
    from config import Config
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart
    
    if not Config.SMTP_HOST or not Config.SMTP_USER or not Config.SMTP_PASSWORD:
        logger.info("SMTP settings not configured. Skipping email notification.")
        return False
        
    try:
        msg = MIMEMultipart()
        msg['From'] = Config.SMTP_SENDER_EMAIL or Config.SMTP_USER
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body_text, 'plain'))
        
        server = smtplib.SMTP(Config.SMTP_HOST, Config.SMTP_PORT or 587, timeout=15)
        server.starttls()
        server.login(Config.SMTP_USER, Config.SMTP_PASSWORD)
        server.sendmail(msg['From'], to_email, msg.as_string())
        server.quit()
        logger.info(f"Email sent successfully to {to_email}")
        return True
    except Exception as e:
        logger.error(f"Failed to send email via SMTP: {e}", exc_info=True)
        return False

def send_whatsapp_notification(to_number, message):
    """Send WhatsApp notification using Starsender WA Gateway"""
    from config import Config
    
    if not Config.STARSENDER_API_KEY or not Config.STARSENDER_DEVICE_ID:
        logger.info("Starsender WA Gateway settings not configured. Skipping WhatsApp notification.")
        return False
        
    to_number = str(to_number).strip()
    if to_number.startswith('0'):
        to_number = '62' + to_number[1:]
    elif to_number.startswith('+'):
        to_number = to_number[1:]
        
    try:
        url = "https://starsender.online/api/sendText"
        headers = {
            'Content-Type': 'application/json'
        }
        payload = {
            'apikey': Config.STARSENDER_API_KEY,
            'tujuan': to_number,
            'message': message
        }
        response = requests.post(url, json=payload, headers=headers, timeout=15)
        if response.status_code == 200:
            logger.info(f"WhatsApp notification sent successfully to {to_number}")
            return True
        else:
            logger.error(f"Starsender WA Gateway returned status code {response.status_code}: {response.text}")
            return False
    except Exception as e:
        logger.error(f"Failed to send WhatsApp notification via Starsender: {e}", exc_info=True)
        return False
