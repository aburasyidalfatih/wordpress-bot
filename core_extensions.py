import os
import sys
import logging
from logging.handlers import RotatingFileHandler
from functools import lru_cache, wraps
from time import time
import jwt
import requests
from flask import request, jsonify, redirect, url_for, session
from redis import Redis
from rq import Queue

from database import Database
from ml_optimizer import ContentOptimizer
from trending_research import TrendingResearch
from config import Config

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

# Cache settings
_config_cache = {'data': None, 'timestamp': 0}
_stats_cache = {'data': None, 'timestamp': 0}

def load_config(user_id=None):
    now = time()
    if now - _config_cache['timestamp'] < 5:  # 5 second cache
        return _config_cache['data']
    
    admin_id = None
    try:
        from database import User
        with db.get_session() as session:
            admin = session.query(User).filter_by(role='admin').first()
            if admin:
                admin_id = admin.id
    except Exception as e:
        logger.error(f"Error querying admin for config: {e}")
        
    target_id = admin_id if admin_id is not None else user_id
    if target_id is None:
        target_id = 1
        
    config = db.get_config(target_id)
    _config_cache['data'] = config
    _config_cache['timestamp'] = now
    return config

def get_cached_stats(user_id, site_id=None):
    now = time()
    cache_key = f"{user_id}_{site_id}" if site_id else str(user_id)
    
    if cache_key not in _stats_cache:
        _stats_cache[cache_key] = {'data': None, 'timestamp': 0}
        
    if now - _stats_cache[cache_key]['timestamp'] < 5:  # 5 second cache
        return _stats_cache[cache_key]['data']
    
    stats = db.get_stats(user_id, site_id=site_id)
    _stats_cache[cache_key]['data'] = stats
    _stats_cache[cache_key]['timestamp'] = now
    return stats

def save_config(user_id, config_data):
    # If the user is saving, check if they are the admin, but this save_config is used on db. 
    # The route handler will enforce the admin check.
    db.save_config(user_id, config_data)

# JWT decorator
def require_jwt(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        logger.info(f"JWT Check for path: {request.path}, auth_header: {auth_header[:20] + '...' if auth_header else None}")
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({'success': False, 'error': 'Missing or invalid token'}), 401
            
        token = auth_header.split(' ')[1]
        try:
            payload = jwt.decode(token, Config.SECRET_KEY, algorithms=['HS256'])
            user_id = payload.get('user_id')
            if not user_id:
                raise ValueError('Invalid user_id in token')
        except Exception as e:
            logger.error(f"JWT verification error on path {request.path}: {e}", exc_info=True)
            return jsonify({'success': False, 'error': f'Invalid token: {e}'}), 401
            
        return f(user_id, *args, **kwargs)
            
    return decorated_function

# Admin decorator
def require_admin(f):
    @wraps(f)
    @require_jwt
    def decorated_function(user_id, *args, **kwargs):
        from database import User
        with db.get_session() as session:
            user = session.query(User).filter_by(id=user_id).first()
            if not user or user.role != 'admin':
                return jsonify({'success': False, 'error': 'Admin privilege required'}), 403
        return f(user_id, *args, **kwargs)
    return decorated_function

# PIN Protection decorator
def require_pin(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('authenticated'):
            # Check if it's an AJAX/API request
            if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': False, 'error': 'Not authenticated', 'redirect': '/login'}), 401
            return redirect(url_for('login'))
        return f(*args, **kwargs)
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
        title = article.get('title', '')
        excerpt = article.get('excerpt', '')
        excerpt_clean = re.sub('<[^<]+?>', '', excerpt).strip()[:400]
        
        message = f"""📰 <b>{title}</b>\n\n{excerpt_clean}...\n\n👉 <a href="{post_url}">Baca artikel lengkap</a>\n\n#SekolahDigital #Pendidikan #KelasMaster"""
        
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
        
        # Build message: Just 3 paragraphs + hashtags (NO title, NO link)
        message = f"{first_3_paragraphs.strip()}\n\n#Pendidikan #SekolahDigital #KelasMaster #ManajemenSekolah"
        
        # Get image URL from WordPress post
        image_url = None
        if post_url:
            try:
                resp = requests.get(post_url, timeout=5)
                img_match = re.search(r'<meta property="og:image" content="([^"]+)"', resp.text)
                if img_match:
                    image_url = img_match.group(1)
            except:
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
                    comment_url = f"https://graph.facebook.com/v18.0/{post_id}/comments"
                    comment_data = {
                        'access_token': access_token,
                        'message': f"📖 Baca artikel lengkapnya:\n{post_url}"
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
        
        tweet = f"{title}\n\n{excerpt_clean}...\n\n{post_url}\n\n#SekolahDigital #Pendidikan"
        
        if len(tweet) > 280:
            tweet = f"{title[:100]}...\n\n{post_url}\n\n#SekolahDigital #Pendidikan"
            
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
        
        # Remove HTML tags and decode entities
        content_clean = re.sub('<[^<]+?>', '', content)
        content_clean = html.unescape(content_clean)
        content_clean = re.sub(r'\s+', ' ', content_clean).strip()
        
        # Get first paragraph (first 3-4 sentences)
        sentences = re.split(r'(?<=[.!?])\s+', content_clean)
        first_para_sentences = []
        
        for sentence in sentences[:4]:
            if len(sentence.strip()) > 20:
                first_para_sentences.append(sentence.strip())
                if len(' '.join(first_para_sentences)) > 300:
                    break
        
        first_paragraph = ' '.join(first_para_sentences[:3])
        
        # Build text: 1 paragraph + link + hashtags
        text = f"{first_paragraph}\n\n📖 {post_url}\n\n#Pendidikan #KelasMaster #SekolahDigital"
        
        # Limit to 500 chars
        if len(text) > 500:
            text = first_paragraph[:450] + "...\n\n#Pendidikan #KelasMaster"
        
        # Get image URL from WordPress post
        image_url = None
        if post_url:
            try:
                resp = requests.get(post_url, timeout=5)
                img_match = re.search(r'<meta property="og:image" content="([^"]+)"', resp.text)
                if img_match:
                    image_url = img_match.group(1)
            except:
                pass
        
        # Step 1: Create container
        if image_url:
            url = f"https://graph.threads.net/v1.0/{user_id}/threads"
            params = {
                'media_type': 'IMAGE',
                'image_url': image_url,
                'text': text,
                'access_token': access_token
            }
        else:
            url = f"https://graph.threads.net/v1.0/{user_id}/threads"
            params = {
                'media_type': 'TEXT',
                'text': text,
                'access_token': access_token
            }
            
        response = requests.post(url, params=params, timeout=30)
        if response.status_code != 200:
            logger.error(f"Threads container failed: {response.text}")
            return False
            
        creation_id = response.json().get('id')
        
        # Step 2: Publish container
        url = f"https://graph.threads.net/v1.0/{user_id}/threads_publish"
        params = {
            'creation_id': creation_id,
            'access_token': access_token
        }
        response = requests.post(url, params=params, timeout=30)
        
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
