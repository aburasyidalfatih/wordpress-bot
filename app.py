from flask import Flask, render_template, request, jsonify, redirect, url_for, session
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from bot import ArticleGenerator, WordPressPublisher
from database import Database, ResearchData
from ml_optimizer import ContentOptimizer
from trending_research import TrendingResearch
from dotenv import load_dotenv
import os
import requests
from datetime import datetime
import logging
from logging.handlers import RotatingFileHandler
import signal
import atexit
import sys
from functools import lru_cache, wraps
from time import time

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        RotatingFileHandler('logs/bot.log', maxBytes=10485760, backupCount=5),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', os.urandom(24).hex())

# PIN Protection
PIN_CODE = "888888"

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

# Initialize scheduler with persistent jobstore
jobstores = {
    'default': SQLAlchemyJobStore(url='sqlite:///scheduler_jobs.db')
}
scheduler = BackgroundScheduler(jobstores=jobstores)
scheduler.start()
logger.info("Scheduler started")

# Initialize database
DB_URL = os.getenv('DATABASE_URL', 'sqlite:///wordpress_bot.db')
db = Database(DB_URL)
optimizer = ContentOptimizer(db)
trending = TrendingResearch()

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
        
        message = f"""📰 <b>{title}</b>

{excerpt_clean}...

👉 <a href="{post_url}">Baca artikel lengkap</a>

#SekolahDigital #Pendidikan #KelasMaster"""
        
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
        message = f"""{first_3_paragraphs.strip()}

#Pendidikan #SekolahDigital #KelasMaster #ManajemenSekolah"""
        
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
            tweet = f"{title}\n\n{post_url}\n\n#SekolahDigital #Pendidikan"
        
        if image_data:
            auth = tweepy.OAuth1UserHandler(api_key, api_secret, access_token, access_secret)
            api = tweepy.API(auth)
            media = api.media_upload(filename='image.jpg', file=image_data)
            response = client.create_tweet(text=tweet, media_ids=[media.media_id])
        else:
            response = client.create_tweet(text=tweet)
        
        return response.data is not None
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
        text = f"""{first_paragraph}

📖 {post_url}

#Pendidikan #KelasMaster #SekolahDigital"""
        
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
        
        # Create container with image
        data = {
            'media_type': 'IMAGE' if image_url else 'TEXT',
            'text': text,
            'access_token': access_token
        }
        
        if image_url:
            data['image_url'] = image_url
        
        response = requests.post(
            f"https://graph.threads.net/v1.0/{user_id}/threads",
            data=data,
            timeout=10
        )
        
        if response.status_code != 200:
            logger.error(f"Threads container error: {response.json()}")
            return False
        
        container_id = response.json().get('id')
        
        # Publish the post
        publish_response = requests.post(
            f"https://graph.threads.net/v1.0/{user_id}/threads_publish",
            data={
                'creation_id': container_id,
                'access_token': access_token
            },
            timeout=10
        )
        
        if publish_response.status_code == 200:
            thread_id = publish_response.json().get('id')
            logger.info(f"Threads post successful, Thread ID: {thread_id}")
            return True
        else:
            logger.error(f"Threads publish error: {publish_response.json()}")
            return False
            
    except Exception as e:
        logger.error(f"Threads post error: {e}")
        return False

# Cache for config and stats (5 seconds TTL)
_config_cache = {'data': None, 'timestamp': 0}
_stats_cache = {'data': None, 'timestamp': 0}

def load_config():
    now = time()
    if now - _config_cache['timestamp'] < 5:  # 5 second cache
        return _config_cache['data']
    
    config = db.get_config()
    _config_cache['data'] = config
    _config_cache['timestamp'] = now
    return config

def get_cached_stats():
    now = time()
    if now - _stats_cache['timestamp'] < 5:  # 5 second cache
        return _stats_cache['data']
    
    stats = db.get_stats()
    _stats_cache['data'] = stats
    _stats_cache['timestamp'] = now
    return stats

def save_config(config):
    db.save_config(config)

def generate_and_post():
    config = load_config()
    
    if not config['selected_categories'] or not config['auto_post']:
        logger.info("Auto post disabled or no categories selected")
        return
    
    try:
        logger.info("Starting generate and post job")
        generator = ArticleGenerator(config['gemini_api_key'], config.get('gemini_model', 'gemini-2.5-pro'), config.get('gemini_image_model', 'gemini-3.1-flash-image-preview'))
        publisher = WordPressPublisher(
            config['wordpress_url'],
            config['wordpress_username'],
            config['wordpress_password']
        )
        
        category = config['selected_categories'][0]
        logger.info(f"Selected category: {category['name']} (position 1 of {len(config['selected_categories'])})")
        
        # Rotate: move first to last
        config['selected_categories'] = config['selected_categories'][1:] + [category]
        save_config(config)
        
        # Verify rotation saved
        config_verify = load_config()
        next_category = config_verify['selected_categories'][0]['name']
        logger.info(f"Rotation complete. Next category will be: {next_category}")
        
        send_telegram_notification(config, 
            f"🤖 <b>WordPress Auto Post Bot</b>\n\n"
            f"📝 Mulai generate artikel...\n"
            f"📂 Kategori: {category['name']}")
        
        existing_titles = db.get_existing_titles(category['name'], limit=50)
        
        # Check if should use research topic
        custom_topic = None
        seo_data = None
        if config.get('use_research_topics'):
            custom_topic = db.get_unused_research_topic(category['name'])
            if custom_topic:
                logger.info(f"Using research topic: {custom_topic}")
            
            # Get SEO research data
            try:
                with db.get_session() as session:
                    research = session.query(ResearchData).filter(
                        ResearchData.category == category['name']
                    ).order_by(ResearchData.created_at.desc()).first()
                    
                    if research:
                        seo_data = {
                            'keywords': research.keywords if hasattr(research, 'keywords') else [],
                            'questions': research.questions if hasattr(research, 'questions') else [],
                            'long_tail': research.long_tail_keywords if hasattr(research, 'long_tail_keywords') else []
                        }
                        logger.info(f"Using SEO data: {len(seo_data.get('keywords', []))} keywords, {len(seo_data.get('questions', []))} questions")
            except Exception as e:
                logger.error(f"Error getting SEO data: {e}")
        
        custom_article_prompt = config.get('article_prompt') or None
        custom_image_prompt = config.get('image_prompt') or None
        article = generator.generate_article(category['name'], existing_titles, custom_topic, seo_data, custom_prompt=custom_article_prompt)
        
        # Check for duplicate or similar titles
        def is_similar_title(new_title, existing_titles):
            """Check if title is duplicate or too similar"""
            import re
            from difflib import SequenceMatcher
            
            # Normalize title for comparison
            def normalize(text):
                text = re.sub(r'\d+', '', text.lower())
                text = re.sub(r'[^\w\s]', '', text)
                return ' '.join(text.split())
            
            # Extract main topic (first 5-6 words usually contain main topic)
            def get_main_topic(text):
                words = normalize(text).split()[:6]
                return ' '.join(words)
            
            new_normalized = normalize(new_title)
            new_main = get_main_topic(new_title)
            
            for existing in existing_titles:
                existing_normalized = normalize(existing)
                existing_main = get_main_topic(existing)
                
                # Check exact match
                if new_normalized == existing_normalized:
                    return True, existing, "exact"
                
                # Check character similarity (>60% = too similar)
                char_similarity = SequenceMatcher(None, new_normalized, existing_normalized).ratio()
                if char_similarity > 0.6:
                    return True, existing, f"char {char_similarity:.0%}"
                
                # Check main topic similarity (>75% = same topic)
                topic_similarity = SequenceMatcher(None, new_main, existing_main).ratio()
                if topic_similarity > 0.75:
                    return True, existing, f"topic {topic_similarity:.0%}"
            
            return False, None, None
        
        is_dup, similar_to, reason = is_similar_title(article.get('title', ''), existing_titles)
        
        if is_dup:
            logger.warning(f"Similar title detected ({reason}): '{article.get('title')}' ~ '{similar_to}'. Regenerating...")
            article = generator.generate_article(
                category['name'], 
                existing_titles, 
                custom_topic, 
                seo_data,
                avoid_similar=True,
                custom_prompt=custom_article_prompt
            )
        
        image_data = generator.generate_image(
            category['name'], 
            article.get('title', ''),
            article.get('content', ''),
            custom_prompt=custom_image_prompt
        )
        featured_image_id = None
        
        if image_data:
            featured_image_id = publisher.upload_image(image_data, article.get('title', ''))
        
        success, result = publisher.create_post(
            article.get('title', ''),
            article.get('content', ''),
            category['id'],
            featured_image_id,
            article.get('meta_description'),
            article.get('excerpt'),
            article.get('focus_keyword')
        )
        
        post_id = None
        post_url = None
        if success and isinstance(result, dict):
            post_id = result.get('id')
            post_url = result.get('link')
        
        db.add_log(
            category['id'],
            category['name'],
            article.get('title', ''),
            success,
            str(result),
            post_id,
            post_url
        )
        
        if success:
            file_size = len(image_data.getvalue())/1024 if image_data else 0
            send_telegram_notification(config,
                f"✅ <b>Artikel Berhasil Dipublish!</b>\n\n"
                f"📝 <b>Judul:</b> {article.get('title', '')}\n"
                f"📂 <b>Kategori:</b> {category['name']}\n"
                f"📊 <b>Panjang:</b> {len(article.get('content', '').split())} kata\n"
                f"🎨 <b>Featured Image:</b> WebP ({file_size:.1f} KB)\n"
                f"🔗 <b>URL:</b> {post_url}\n\n"
                f"🎉 Status: Published")
            
            post_to_telegram_channel(config, article, post_url, image_data)
            post_to_facebook_page(config, article, post_url, image_data)
            post_to_twitter(config, article, post_url, image_data)
            post_to_threads(config, article, post_url, image_data)
            
            logger.info(f"Article published successfully: {article.get('title', '')}")
        else:
            send_telegram_notification(config,
                f"❌ <b>Posting Gagal!</b>\n\n"
                f"📝 <b>Judul:</b> {article.get('title', '')}\n"
                f"📂 <b>Kategori:</b> {category['name']}\n"
                f"⚠️ <b>Error:</b> {str(result)[:200]}")
            logger.error(f"Article publish failed: {result}")
            
    except Exception as e:
        logger.error(f"Error in generate_and_post: {e}", exc_info=True)
        try:
            send_telegram_notification(config,
                f"❌ <b>Error Generate & Post</b>\n\n"
                f"⚠️ {str(e)[:200]}")
        except:
            pass

@app.route('/health')
def health():
    """Health check endpoint"""
    try:
        stats = db.get_stats()
        
        # Get next post time
        next_post = None
        jobs = scheduler.get_jobs()
        for job in jobs:
            if job.id == 'auto_post':
                next_post = job.next_run_time.strftime('%Y-%m-%d %H:%M:%S') if job.next_run_time else None
                break
        
        return jsonify({
            'status': 'healthy',
            'scheduler_running': scheduler.running,
            'database_connected': True,
            'total_posts': stats.get('total_posts', 0),
            'next_post_time': next_post
        }), 200
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return jsonify({
            'status': 'unhealthy',
            'error': str(e)
        }), 500

@app.route('/research')
@require_pin
def research():
    """Trending topics research page"""
    config = load_config()
    
    # Get latest research data for each category
    research_data = {}
    for category in config.get('selected_categories', []):
        with db.get_session() as session:
            from database import ResearchData
            latest = session.query(ResearchData).filter(
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
                    'created_at': latest.created_at.strftime('%d %b %Y, %H:%M')
                }
    
    return render_template('research.html', config=config, research_data=research_data)

@app.route('/api/trending/<category>')
@require_pin
def get_trending(category):
    """API endpoint to get trending topics for a category"""
    try:
        data = trending.get_trending_topics(category, limit=15)
        return jsonify(data)
    except Exception as e:
        logger.error(f"Trending API error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/suggest-topics', methods=['POST'])
@require_pin
def suggest_topics():
    """API endpoint to suggest article topics"""
    try:
        data = request.json
        category = data.get('category')
        count = data.get('count', 5)
        
        suggestions = trending.suggest_article_topics(category, count)
        return jsonify({'suggestions': suggestions})
    except Exception as e:
        logger.error(f"Suggest topics error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        pin = request.form.get('pin')
        if pin == PIN_CODE:
            session['authenticated'] = True
            return redirect(url_for('index'))
        else:
            return render_template('login.html', error='PIN salah!')
    return render_template('login.html')

@app.route('/logout', methods=['GET', 'POST'])
def logout():
    session.pop('authenticated', None)
    if request.method == 'POST':
        return jsonify({'success': True})
    return redirect(url_for('login'))

@app.route('/')
@require_pin
def index():
    config = load_config()
    logs = db.get_logs(limit=20)
    stats = db.get_stats()
    insights = optimizer.get_content_recommendations()
    performance = db.get_category_performance()
    
    # Get next scheduled post time
    next_post_time = None
    jobs = scheduler.get_jobs()
    for job in jobs:
        if job.id == 'auto_post':
            next_post_time = job.next_run_time
            break
    
    return render_template('index.html', 
                         config=config, 
                         logs=logs, 
                         stats=stats,
                         insights=insights,
                         performance=performance,
                         next_post_time=next_post_time)

@app.route('/settings')
@require_pin
def settings():
    config = load_config()
    return render_template('settings.html', config=config)

@app.route('/prompts')
@require_pin
def prompts():
    config = load_config()
    default_article_prompt = """Buatkan artikel blog SEO-optimized berkualitas tinggi untuk website kelasmaster.id tentang: {topic}
{existing_titles}{research_note}{seo_section}
TARGET AUDIENCE: Kepala sekolah, founder yayasan, pengelola lembaga pendidikan di Indonesia

⚠️ PENTING - TAHUN SAAT INI: 2026
- Jika menyebutkan tahun, gunakan 2026 atau "saat ini"
- Jangan gunakan tahun 2024 atau 2025

STRUKTUR ARTIKEL (2000-2500 KATA):

1. HOOK PEMBUKA (100 kata):
   ⚠️ WAJIB VARIATIF - Gunakan salah satu pendekatan ini (JANGAN selalu pakai statistik):
   A. Story/Anekdot: "Pak Budi, kepala sekolah di Bandung, hampir putus asa ketika..."
   B. Problem Statement: "Bayangkan: SPP sudah naik 20%, tapi guru tetap resign..."
   C. Pertanyaan Provokatif: "Apa yang membuat 3 dari 5 sekolah swasta gagal bertahan?"
   D. Fakta Mengejutkan: "Tahun 2026, lebih banyak sekolah tutup daripada yang buka..."
   E. Kontras: "Sekolah A penuh siswa, Sekolah B sepi. Bedanya hanya satu hal..."
   ✓ Akhiri dengan promise: "Artikel ini akan memandu Anda..."
   ✗ JANGAN selalu mulai dengan "Data internal kami di KelasMaster..."

2. CONTEXT (200 kata):
   - Situasi pendidikan Indonesia saat ini terkait topik
   - Mengapa topik ini urgent dan penting
   - Siapa yang paling membutuhkan solusi ini

3. KONTEN UTAMA (1500-1700 kata):
   H2: Konsep Dasar & Pentingnya (300 kata)
   - Definisi clear dengan bahasa praktis
   - Mengapa ini critical untuk lembaga pendidikan
   - Contoh konkret dari sekolah Indonesia

   H2: Implementasi Praktis Step-by-Step (600 kata)
   - Panduan actionable dengan numbered list
   - Timeline realistis (minggu/bulan)
   - Tools/template yang bisa digunakan
   - Checklist untuk memulai

   H2: Studi Kasus Nyata (400 kata)
   - Sekolah X di Kota Y, Indonesia (nama & lokasi realistis)
   - Challenge → Solution → Result (dengan angka spesifik)
   - WAJIB: Quote langsung dari kepala sekolah
     Format: "Quote," ujar Nama Lengkap, Kepala Sekolah X di Kota Y.

   H2: Tips & Best Practices (300 kata)
   - Do's and Don'ts dalam format HTML table
   - Common mistakes yang harus dihindari
   - Quick wins yang bisa langsung diterapkan

4. KESIMPULAN (150 kata):
   - Recap 3-5 key takeaways
   - CTA: ajakan konsultasi/download resource

5. FAQ (150 kata):
   - 3-5 pertanyaan umum dengan jawaban singkat

GAYA PENULISAN:
✓ Tone: Profesional tapi approachable, gunakan "Anda"
✓ Variasikan panjang kalimat untuk rhythm natural
✓ Contoh selalu dari konteks Indonesia
✓ Transisi natural: "Hasilnya?", "Yang terjadi?", "Faktanya:"
✗ Hindari: "Dengan demikian", "Oleh karena itu", "Pada akhirnya"
✗ Hindari: "Penting untuk dicatat bahwa...", "Perlu diingat bahwa..."
✗ JANGAN gunakan ASCII art atau Unicode box drawing
✗ Gunakan HTML table (<table>) untuk tabel, BUKAN ASCII art

FORMAT OUTPUT (JSON valid, tanpa markdown code blocks):
{
    "title": "Judul CTR tinggi dengan angka + power word + benefit (50-60 karakter)",
    "meta_description": "Meta description 150-160 karakter dengan CTA dan keyword",
    "content": "Konten HTML lengkap 2000-2500 kata",
    "focus_keyword": "keyword utama artikel",
    "excerpt": "Ringkasan engaging 2-3 kalimat",
    "reading_time": "estimasi menit",
    "key_takeaways": ["takeaway 1", "takeaway 2", "takeaway 3"]
}"""

    default_image_prompt = """Create a professional featured image for this article about {topic}.

Article Title: "{title}"

Design Requirements:
- Modern, clean design in landscape orientation (16:9) - perfect for blog featured image
- Professional color scheme (blues, greens, education colors)
- Include the title text: "{title}"
- Add relevant visual elements, icons, or illustrations
- "kelasmaster.id" branding subtly placed
- High quality, eye-catching design
- Suitable as blog header/featured image

Style: Modern, professional, suitable for educational blog featured image."""

    return render_template('prompts.html', config=config,
                           default_article_prompt=default_article_prompt,
                           default_image_prompt=default_image_prompt)

@app.route('/save-prompts', methods=['POST'])
@require_pin
def save_prompts():
    config = load_config()
    config['article_prompt'] = request.form.get('article_prompt', '').strip() or None
    config['image_prompt'] = request.form.get('image_prompt', '').strip() or None
    save_config(config)
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'success': True, 'message': 'Prompts saved!'})
    return redirect(url_for('prompts'))

@app.route('/monitor')
@require_pin
def monitor():
    """Monitoring dashboard"""
    config = load_config()
    stats = get_cached_stats()
    
    # Get system info
    import psutil
    import os
    
    system_info = {
        'cpu_percent': psutil.cpu_percent(interval=0.1),  # Reduced from 1s to 0.1s
        'memory_percent': psutil.virtual_memory().percent,
        'disk_percent': psutil.disk_usage('/').percent,
        'uptime': datetime.now() - datetime.fromtimestamp(psutil.boot_time())
    }
    
    # Get service info
    service_info = {
        'scheduler_running': scheduler.running,
        'scheduler_jobs': len(scheduler.get_jobs()),
        'database_size': 0,  # PostgreSQL - size not tracked locally
        'log_size': os.path.getsize('/home/ubuntu/wordpress-bot/logs/bot.log') / 1024 / 1024 if os.path.exists('/home/ubuntu/wordpress-bot/logs/bot.log') else 0
    }
    
    # Gemini status - don't test on page load, use cached status
    gemini_status = {'status': 'unknown', 'message': 'Check via API endpoint'}
    
    # Get recent errors from log (limit to last 50 lines for speed)
    recent_errors = []
    try:
        with open('/home/ubuntu/wordpress-bot/logs/bot.log', 'r') as f:
            # Read only last 1000 bytes instead of whole file
            f.seek(0, 2)  # Go to end
            file_size = f.tell()
            f.seek(max(0, file_size - 10000), 0)  # Read last 10KB
            lines = f.readlines()
            for line in lines[-50:]:
                if 'ERROR' in line:
                    recent_errors.append(line.strip())
    except:
        pass
    
    return render_template('monitor.html', 
                         config=config,
                         stats=stats,
                         system_info=system_info,
                         service_info=service_info,
                         gemini_status=gemini_status,
                         recent_errors=recent_errors[-10:])

@app.route('/api/health-metrics')
def health_metrics():
    """API endpoint for real-time health metrics"""
    import psutil
    import os
    
    try:
        return jsonify({
            'timestamp': datetime.now().isoformat(),
            'service': {
                'status': 'healthy',
                'scheduler_running': scheduler.running,
                'scheduler_jobs': len(scheduler.get_jobs())
            },
            'system': {
                'cpu_percent': psutil.cpu_percent(interval=0.1),
                'memory_percent': psutil.virtual_memory().percent,
                'disk_percent': psutil.disk_usage('/').percent
            },
            'database': {
                'connected': True,
                'size_mb': 0
            },
            'stats': get_cached_stats()
        })
    except Exception as e:
        logger.error(f"Health metrics error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route("/sync-engagement", methods=["POST"])
@require_pin
def sync_engagement():
    """Sync engagement metrics from WordPress"""
    config = load_config()
    
    try:
        publisher = WordPressPublisher(
            config['wordpress_url'],
            config['wordpress_username'],
            config['wordpress_password']
        )
        
        logs = db.get_logs(limit=50)
        synced = 0
        
        for log in logs:
            if log.get('post_id'):
                stats = publisher.get_post_stats(log['post_id'])
                if stats:
                    db.update_engagement(
                        log['id'],
                        views=stats.get('views', 0),
                        comments=stats.get('comments', 0),
                        likes=stats.get('likes', 0),
                        shares=stats.get('shares', 0)
                    )
                    synced += 1
        
        return jsonify({
            'success': True,
            'message': f'Berhasil sync {synced} artikel',
            'synced': synced
        })
    except Exception as e:
        logger.error(f"Sync engagement error: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route("/optimize-categories", methods=["POST"])
@require_pin
def optimize_categories():
    """Auto-optimize category order based on performance"""
    config = load_config()
    
    try:
        optimized = optimizer.optimize_category_order(config['selected_categories'])
        config['selected_categories'] = optimized
        save_config(config)
        
        return jsonify({
            'success': True,
            'message': 'Kategori berhasil dioptimasi berdasarkan performa',
            'categories': [c['name'] for c in optimized]
        })
    except Exception as e:
        logger.error(f"Optimize categories error: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route("/save-config", methods=["POST"])
@require_pin
def save_config_route():
    config = load_config()
    
    config['gemini_api_key'] = request.form.get('gemini_api_key', '')
    config['gemini_model'] = request.form.get('gemini_model', 'gemini-2.5-pro')
    config['gemini_image_model'] = request.form.get('gemini_image_model', 'gemini-3.1-flash-image-preview')
    config['wordpress_url'] = request.form.get('wordpress_url', '')
    config['wordpress_username'] = request.form.get('wordpress_username', '')
    config['wordpress_password'] = request.form.get('wordpress_password', '')
    config['interval_hours'] = int(request.form.get('interval_hours', 6))
    
    config['telegram_bot_token'] = request.form.get('telegram_bot_token', '')
    config['telegram_chat_id'] = request.form.get('telegram_chat_id', '')
    config['telegram_enabled'] = request.form.get('telegram_enabled') == 'on'
    config['telegram_channel_id'] = request.form.get('telegram_channel_id', '')
    config['telegram_post_to_channel'] = request.form.get('telegram_post_to_channel') == 'on'
    
    config['facebook_page_id'] = request.form.get('facebook_page_id', '')
    config['facebook_access_token'] = request.form.get('facebook_access_token', '')
    config['facebook_enabled'] = request.form.get('facebook_enabled') == 'on'
    
    config['twitter_api_key'] = request.form.get('twitter_api_key', '')
    config['twitter_api_secret'] = request.form.get('twitter_api_secret', '')
    config['twitter_access_token'] = request.form.get('twitter_access_token', '')
    config['twitter_access_secret'] = request.form.get('twitter_access_secret', '')
    config['twitter_enabled'] = request.form.get('twitter_enabled') == 'on'
    
    config['threads_user_id'] = request.form.get('threads_user_id', '')
    config['threads_access_token'] = request.form.get('threads_access_token', '')
    config['threads_enabled'] = request.form.get('threads_enabled') == 'on'
    
    config['auto_research_enabled'] = request.form.get('auto_research_enabled') == 'on'
    config['use_research_topics'] = request.form.get('use_research_topics') == 'on'
    
    selected_cat_ids = request.form.getlist('selected_categories')
    config['selected_categories'] = [cat for cat in config['categories'] if str(cat['id']) in selected_cat_ids]
    
    config['schedule_hours'] = request.form.get('schedule_hours', '0,6,12,18')
    config['auto_post'] = request.form.get('auto_post') == 'on'
    
    save_config(config)

    # Return JSON if AJAX request
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'success': True, 'message': 'Configuration saved!'})
    
    scheduler.remove_all_jobs()
    if config['auto_post'] and config['selected_categories']:
        # Parse schedule hours
        schedule_hours = config.get('schedule_hours', '0,6,12,18')
        hours_list = [int(h.strip()) for h in schedule_hours.split(',') if h.strip().isdigit()]
        
        # Add cron job for each hour
        scheduler.add_job(
            generate_and_post,
            'cron',
            hour=','.join(map(str, hours_list)),
            minute=0,
            id='auto_post',
            replace_existing=True
        )
        logger.info(f"Scheduled job added at hours: {hours_list}")
    
    if config.get('auto_research_enabled'):
        scheduler.add_job(
            auto_research_job,
            'cron',
            hour=0,
            minute=0,
            id='auto_research',
            replace_existing=True
        )
        logger.info("Daily auto-research scheduled at 00:00")
    
    # Return JSON if AJAX, else redirect
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'success': True, 'message': 'Configuration saved!'})
    return redirect(url_for('index'))

@app.route("/test-telegram", methods=["POST"])
@require_pin
def test_telegram():
    config = load_config()
    
    if not config.get('telegram_bot_token') or not config.get('telegram_chat_id'):
        return jsonify({'success': False, 'error': 'Bot Token atau Chat ID belum diisi!'})
    
    try:
        bot_token = config.get('telegram_bot_token')
        url = f"https://api.telegram.org/bot{bot_token}/getMe"
        response = requests.get(url, timeout=10)
        
        if response.status_code != 200:
            return jsonify({'success': False, 'error': 'Bot Token tidak valid! Periksa kembali token dari @BotFather'})
    except Exception as e:
        return jsonify({'success': False, 'error': f'Error koneksi: {str(e)}'})
    
    success = send_telegram_notification(config,
        f"🤖 <b>Test Notifikasi</b>\n\n"
        f"✅ Telegram berhasil terhubung!\n"
        f"📱 Bot siap mengirim notifikasi.")
    
    if success:
        return jsonify({'success': True, 'message': 'Notifikasi test berhasil dikirim ke Telegram!'})
    else:
        return jsonify({'success': False, 'error': 'Chat ID tidak valid atau bot belum di-start!'})

@app.route("/fetch-categories", methods=["POST"])
@require_pin
def fetch_categories():
    config = load_config()
    
    if not config['wordpress_url'] or not config['wordpress_username'] or not config['wordpress_password']:
        return jsonify({'success': False, 'error': 'Mohon isi WordPress URL, Username, dan Password terlebih dahulu.'})
    
    try:
        publisher = WordPressPublisher(
            config['wordpress_url'],
            config['wordpress_username'],
            config['wordpress_password']
        )
        categories = publisher.get_categories()
        
        if categories:
            config['categories'] = categories
            save_config(config)
            return jsonify({'success': True, 'categories': categories})
        else:
            return jsonify({'success': False, 'error': 'Tidak dapat mengambil kategori. Periksa kredensial WordPress Anda.'})
    except Exception as e:
        logger.error(f"Fetch categories error: {e}")
        return jsonify({'success': False, 'error': f'Error: {str(e)}'})

@app.route('/test-design')
def test_design():
    return render_template('test_design.html')

@app.route('/test-generate', methods=['POST'])
def test_generate():
    config = load_config()
    category_name = request.json.get('category', '')
    
    try:
        generator = ArticleGenerator(config['gemini_api_key'], config.get('gemini_model', 'gemini-2.5-pro'), config.get('gemini_image_model', 'gemini-3.1-flash-image-preview'))
        article = generator.generate_article(category_name)
        return jsonify({'success': True, 'article': article})
    except Exception as e:
        logger.error(f"Test generate error: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route("/manual-post", methods=["POST"])
@require_pin
def manual_post():
    try:
        generate_and_post()
        return jsonify({'success': True, 'message': 'Artikel berhasil diposting'})
    except Exception as e:
        logger.error(f"Manual post error: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route("/manual-research", methods=["POST"])
@require_pin
def manual_research():
    try:
        auto_research_job()
        return jsonify({'success': True, 'message': 'Research completed for all categories'})
    except Exception as e:
        logger.error(f"Manual research error: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/next-category')
def next_category():
    """Get next category that will be used for posting"""
    try:
        config = load_config()
        if config.get('selected_categories') and len(config['selected_categories']) > 0:
            next_cat = config['selected_categories'][0]
            return jsonify({
                'success': True,
                'category': next_cat['name'],
                'category_id': next_cat['id']
            })
        else:
            return jsonify({
                'success': False,
                'error': 'No categories selected'
            })
    except Exception as e:
        logger.error(f"Next category error: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/download-logs')
def download_logs():
    """Download log file"""
    try:
        from flask import send_file
        return send_file('/home/ubuntu/wordpress-bot/logs/bot.log', 
                        as_attachment=True,
                        download_name=f'bot_log_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log')
    except Exception as e:
        logger.error(f"Download logs error: {e}")
        return jsonify({'error': str(e)}), 500

def shutdown():
    """Graceful shutdown"""
    logger.info("Shutting down gracefully...")
    try:
        scheduler.shutdown(wait=True)
        db.close()
        logger.info("Shutdown complete")
    except Exception as e:
        logger.error(f"Error during shutdown: {e}")

def auto_research_job():
    """Daily research job to find trending topics"""
    config = load_config()
    
    if not config.get('auto_research_enabled') or not config['selected_categories']:
        logger.info("Auto research disabled or no categories")
        return
    
    try:
        logger.info("Starting daily auto-research job")
        
        # Import SEO research module
        from seo_research import SEOResearch
        seo = SEOResearch()
        
        for category in config['selected_categories']:
            category_name = category['name']
            logger.info(f"Researching category: {category_name}")
            
            # Get trending data
            trending_data = trending.get_trending_topics(category_name, limit=15)
            if not trending_data:
                continue
            
            # Get suggestions
            suggestions = trending.suggest_article_topics(category_name, count=10)
            
            # NEW: Get SEO research data
            try:
                seo_data = seo.analyze_keyword(category_name)
                keywords = seo_data.get('suggestions', [])
                questions = seo_data.get('questions', [])
                long_tail = seo_data.get('long_tail', [])
                
                logger.info(f"SEO research: {len(keywords)} keywords, {len(questions)} questions")
            except Exception as e:
                logger.error(f"SEO research error: {e}")
                keywords = []
                questions = []
                long_tail = []
            
            # Save to database with SEO data
            db.save_research_data(
                category_name,
                trending_data.get('trending_now', []),
                trending_data.get('related_rising', []),
                trending_data.get('related_top', []),
                suggestions,
                keywords=keywords,
                questions=questions,
                long_tail=long_tail
            )
            
            logger.info(f"Research completed for {category_name}: {len(suggestions)} topics found")
        
        # Send notification
        send_telegram_notification(config,
            f"🔍 <b>Daily Research Completed</b>\n\n"
            f"✅ Researched {len(config['selected_categories'])} categories\n"
            f"📊 Trending topics saved for tomorrow's articles")
        
    except Exception as e:
        logger.error(f"Auto research error: {e}")
        send_telegram_notification(config,
            f"❌ <b>Research Failed</b>\n\n"
            f"Error: {str(e)}")

# Register shutdown handlers
atexit.register(shutdown)
signal.signal(signal.SIGTERM, lambda s, f: shutdown())
signal.signal(signal.SIGINT, lambda s, f: shutdown())

if __name__ == '__main__':
    config = load_config()
    
    # Schedule auto-post with cron (fixed hours)
    if config['auto_post'] and config['selected_categories']:
        # Parse schedule hours
        schedule_hours = config.get('schedule_hours', '0,6,12,18')
        hours_list = [int(h.strip()) for h in schedule_hours.split(',') if h.strip().isdigit()]
        
        scheduler.add_job(
            generate_and_post,
            'cron',
            hour=','.join(map(str, hours_list)),
            minute=0,
            id='auto_post',
            replace_existing=True
        )
        logger.info(f"Auto post job scheduled at hours: {hours_list}")
    
    # Schedule daily research at 00:00
    if config.get('auto_research_enabled'):
        scheduler.add_job(
            auto_research_job,
            'cron',
            hour=0,
            minute=0,
            id='auto_research',
            replace_existing=True
        )
        logger.info("Daily auto-research scheduled at 00:00")
    
    # Production mode - bind to localhost only (accessed via nginx)
    app.run(debug=False, host='127.0.0.1', port=5003)
