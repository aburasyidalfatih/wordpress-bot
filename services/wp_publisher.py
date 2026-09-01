from services.article_generator import sanitize_filename
import requests
import base64
import json
import re
import urllib.parse
from io import BytesIO
import logging
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

logger = logging.getLogger(__name__)


class WordPressPublisher:
    def __init__(self, url, username, password):
        self.url = url.rstrip('/')
        self.username = username
        self.password = password
        self.api_url = f"{self.url}/wp-json/wp/v2"
    
    def _get_auth(self):
        credentials = f"{self.username}:{self.password}"
        token = base64.b64encode(credentials.encode()).decode()
        return {'Authorization': f'Basic {token}'}
    
    def get_post_stats(self, post_id):
        """Get post statistics from WordPress"""
        try:
            response = requests.get(
                f"{self.api_url}/posts/{post_id}",
                headers=self._get_auth(),
                timeout=10
            )
            
            if response.status_code == 200:
                post = response.json()
                
                # Get comments count
                comments_response = requests.get(
                    f"{self.api_url}/comments",
                    params={'post': post_id},
                    timeout=10
                )
                comments_count = len(comments_response.json()) if comments_response.status_code == 200 else 0
                
                return {
                    'views': post.get('meta', {}).get('views', 0),  # Requires view counter plugin
                    'comments': comments_count,
                    'likes': post.get('meta', {}).get('likes', 0),  # Requires like plugin
                    'shares': post.get('meta', {}).get('shares', 0)  # Requires share counter
                }
            return None
        except Exception as e:
            logger.error(f"Error getting post stats: {e}")
            return None

    def get_recent_posts(self, limit=30):
        """Get recent posts for internal linking"""
        try:
            response = requests.get(
                f"{self.api_url}/posts",
                params={'per_page': limit, '_fields': 'id,title,link'},
                headers=self._get_auth(),
                timeout=10
            )
            if response.status_code == 200:
                posts = []
                import html as html_mod
                for p in response.json():
                    title_rendered = p.get('title', {}).get('rendered', '')
                    title_rendered = html_mod.unescape(title_rendered)
                    posts.append({
                        'title': title_rendered,
                        'url': p.get('link', '')
                    })
                return posts
            return []
        except Exception as e:
            logger.error(f"Error getting recent posts: {e}")
            return []
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((requests.exceptions.ConnectionError, requests.exceptions.Timeout))
    )
    def upload_image(self, image_data, title):
        """Upload image via WordPress REST API.
        
        Transient network errors (ConnectionError, Timeout) propagate to trigger retry.
        Non-transient errors (bad status, data issues) are caught and return None immediately."""
        if isinstance(image_data, BytesIO):
            image_bytes = image_data.getvalue()
            sanitized_title = sanitize_filename(title[:50])
            filename = f'{sanitized_title}.webp'
            mime_type = 'image/webp'
        else:
            # Download image from URL — transient errors propagate for retry
            response = requests.get(image_data, timeout=30)
            if response.status_code != 200:
                logger.error(f"Failed to download image: {response.status_code}")
                return None
            image_bytes = response.content
            sanitized_title = sanitize_filename(title[:50])
            filename = f'{sanitized_title}.jpg'
            mime_type = 'image/jpeg'
        
        # Upload via WordPress REST API — transient errors propagate for retry
        headers = self._get_auth()
        headers['Content-Disposition'] = f'attachment; filename="{filename}"'
        headers['Content-Type'] = mime_type
        
        try:
            response = requests.post(
                f"{self.api_url}/media",
                headers=headers,
                data=image_bytes,
                timeout=60
            )
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            raise  # Let @retry handle transient errors
        except Exception as e:
            logger.error(f"Error uploading image (non-retryable): {e}")
            return None
        
        if response.status_code == 201:
            media_data = response.json()
            media_id = media_data['id']
            logger.info(f"Image uploaded successfully via REST API: {media_id}")
            
            # Update SEO metadata (Alt Text, Description, Title)
            try:
                update_headers = self._get_auth()
                update_headers['Content-Type'] = 'application/json'
                metadata_payload = {
                    'title': title,
                    'alt_text': title,
                    'description': f"Illustration for article about: {title}"
                }
                requests.post(
                    f"{self.api_url}/media/{media_id}",
                    headers=update_headers,
                    json=metadata_payload,
                    timeout=30
                )
                logger.info(f"Image SEO metadata updated for media ID: {media_id}")
            except Exception as meta_e:
                logger.error(f"Failed to update image metadata: {meta_e}")
                
            return media_id
        else:
            logger.error(f"Failed to upload image: {response.status_code} - {response.text}")
            return None
    
    def get_categories(self):
        """Fetch all categories from WordPress"""
        try:
            response = requests.get(
                f"{self.api_url}/categories",
                headers=self._get_auth(),
                params={'per_page': 100},
                timeout=30
            )
            
            if response.status_code == 200:
                categories = response.json()
                return [{'id': cat['id'], 'name': cat['name'], 'description': cat.get('description', ''), 'count': cat.get('count', 0)} for cat in categories]
            else:
                logger.error(f"Failed to fetch categories: {response.status_code}")
                return []
        except Exception as e:
            logger.error(f"Error fetching categories: {e}")
            return []
    
    def _prepare_post_payload(self, title, content, category_id=None, featured_image_id=None, meta_description=None, excerpt=None, focus_keyword=None, key_takeaways=None, faqs=None):
        import urllib.parse
        import json
        
        # Remove placeholder patterns
        placeholders = [
            r'\[FLOWCHART:.*?\]',
            r'\[INFOGRAPHIC:.*?\]',
            r'\[CHECKLIST:.*?\]',
            r'\[DIAGRAM:.*?\]',
            r'\[IMAGE:.*?\]',
            r'\[CHART:.*?\]',
            r'\[TABLE:.*?\]',
        ]
        for pattern in placeholders:
            content = re.sub(pattern, '', content, flags=re.IGNORECASE)
        
        # Remove ASCII art tables
        content = re.sub(r'<pre[^>]*>.*?[\u2500-\u257F].*?</pre>', '', content, flags=re.DOTALL)
        content = re.sub(r'[\u2500-\u257F]', '', content)
        
        # Remove empty paragraphs
        content = re.sub(r'<p>\s*</p>', '', content)
        content = re.sub(r'<p>\s*\\n\s*</p>', '', content)
        
        # Remove JSON artifacts at the beginning
        content = re.sub(r'^\s*\{\s*"[^"]*"\s*:', '', content)
        content = re.sub(r'"\s*\}\s*$', '', content)
        
        content = content.strip()
        
        # HTML Sanitizer (Fix broken tags)
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(content, 'html.parser')
            for a in soup.find_all('a'):
                if not a.get('href') or a.get('href').startswith('http') == False:
                    pass
            content = str(soup)
        except Exception as e:
            from core_extensions import logger
            logger.warning(f"Failed to sanitize HTML: {e}")
            
        # Inject Key Takeaways Box
        if key_takeaways and isinstance(key_takeaways, list):
            box = f"""<div class="key-takeaways" style="background:#f0f9ff; padding:20px; border-radius:8px; border-left:5px solid #0ea5e9; margin-bottom:25px;">
    <h3 style="margin-top:0; color:#0369a1;">✨ Key Takeaways</h3>
    <ul style="margin-bottom:0;">
        {''.join([f'<li>{k}</li>' for k in key_takeaways])}
    </ul>
</div>"""
            content = box + "\n" + content
            
        # Inject FAQ Schema (JSON-LD)
        if faqs and isinstance(faqs, list):
            schema = {
                "@context": "https://schema.org",
                "@type": "FAQPage",
                "mainEntity": []
            }
            for faq in faqs:
                if 'question' in faq and 'answer' in faq:
                    schema["mainEntity"].append({
                        "@type": "Question",
                        "name": faq["question"],
                        "acceptedAnswer": {
                            "@type": "Answer",
                            "text": faq["answer"]
                        }
                    })
            if schema["mainEntity"]:
                schema_html = f'\n<script type="application/ld+json">{json.dumps(schema)}</script>\n'
                content += schema_html
                
        # YouTube Auto-Embed
        try:
            from duckduckgo_search import DDGS
            search_term = focus_keyword if focus_keyword else title
            ddgs = DDGS()
            results = ddgs.text(f"site:youtube.com {search_term}", max_results=1)
            if results:
                url = results[0].get('href', '')
                parsed = urllib.parse.urlparse(url)
                video_id = None
                if 'youtube.com/watch' in url:
                    qs = urllib.parse.parse_qs(parsed.query)
                    video_id = qs.get('v', [None])[0]
                elif 'youtu.be/' in url:
                    video_id = parsed.path.lstrip('/')
                
                if video_id and re.match(r'^[a-zA-Z0-9_-]{11}$', video_id):
                    iframe = f'\n<div class="video-container" style="position: relative; padding-bottom: 56.25%; height: 0; overflow: hidden; max-width: 100%;"><iframe style="position: absolute; top: 0; left: 0; width: 100%; height: 100%;" src="https://www.youtube.com/embed/{video_id}" frameborder="0" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" allowfullscreen></iframe></div>\n'
                    parts = re.split(r'(<h2.*?>)', content)
                    if len(parts) >= 3:
                        mid_idx = len(parts) // 2
                        if mid_idx % 2 == 0:
                            mid_idx += 1
                        parts.insert(mid_idx, iframe)
                        content = "".join(parts)
                    else:
                        content += iframe
        except Exception as e:
            from core_extensions import logger
            logger.warning(f"Failed to embed YouTube video: {e}")
        
        clean_slug = re.sub(r'\b20[2-9][0-9]\b', '', title).strip()
        
        post_data = {
            'title': title,
            'content': content,
            'status': 'publish',
            'slug': clean_slug
        }
        
        if category_id:
            post_data['categories'] = [category_id]
        if featured_image_id:
            post_data['featured_media'] = featured_image_id
        if excerpt:
            post_data['excerpt'] = excerpt
            
        meta_fields = {}
        if meta_description:
            meta_fields['_yoast_wpseo_metadesc'] = meta_description
            meta_fields['rank_math_description'] = meta_description
        if focus_keyword:
            meta_fields['_yoast_wpseo_focuskw'] = focus_keyword
            meta_fields['rank_math_focus_keyword'] = focus_keyword
            
        if meta_fields:
            post_data['meta'] = meta_fields
            
        return post_data, meta_fields

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((requests.exceptions.ConnectionError, requests.exceptions.Timeout))
    )
    def create_post(self, title, content, category_id=None, featured_image_id=None, meta_description=None, excerpt=None, focus_keyword=None, key_takeaways=None, faqs=None):
        headers = self._get_auth()
        headers['Content-Type'] = 'application/json'
        post_data, meta_fields = self._prepare_post_payload(title, content, category_id, featured_image_id, meta_description, excerpt, focus_keyword, key_takeaways, faqs)
        try:
            response = requests.post(
                f"{self.api_url}/posts",
                headers=headers,
                json=post_data,
                timeout=30
            )
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            # WordPress might have saved it, but took too long to respond, or network failure.
            logger.error("Transient error while waiting for WordPress to publish the post.")
            raise  # Let @retry handle it
        except Exception as e:
            logger.error(f"Error publishing post to WordPress: {e}")
            return False, str(e)
            
        # If post created successfully, try to update Yoast meta separately
        if response.status_code == 201 and meta_fields:
            post_id = response.json().get('id')
            try:
                # Update post meta using WordPress REST API
                update_response = requests.post(
                    f"{self.api_url}/posts/{post_id}",
                    headers=headers,
                    json={'meta': meta_fields},
                    timeout=30
                )
                logger.info(f"Yoast meta update: {update_response.status_code}")
            except Exception as e:
                logger.warning(f"Could not update Yoast meta: {e}")
        
        return response.status_code == 201, response.json() if response.status_code == 201 else response.text
        
    def update_post_content(self, post_id, title, content, category_id=None, featured_image_id=None, meta_description=None, excerpt=None, focus_keyword=None, key_takeaways=None, faqs=None):
        headers = self._get_auth()
        headers['Content-Type'] = 'application/json'
        post_data, meta_fields = self._prepare_post_payload(title, content, category_id, featured_image_id, meta_description, excerpt, focus_keyword, key_takeaways, faqs)
        response = requests.post(
            f"{self.api_url}/posts/{post_id}",
            headers=headers,
            json=post_data,
            timeout=30
        )
        
        # If post updated successfully, try to update Yoast meta separately
        if response.status_code == 200 and meta_fields:
            try:
                # Update post meta using WordPress REST API
                update_response = requests.post(
                    f"{self.api_url}/posts/{post_id}",
                    headers=headers,
                    json={'meta': meta_fields},
                    timeout=30
                )
                logger.info(f"Yoast meta update: {update_response.status_code}")
            except Exception as e:
                logger.warning(f"Could not update Yoast meta: {e}")
        
        return response.status_code == 200, response.json() if response.status_code == 200 else response.text
        

    def get_posts(self, page=1, per_page=100, search=None):
        headers = self._get_auth()
        params = {'page': page, 'per_page': per_page}
        if search:
            params['search'] = search
        
        response = requests.get(
            f"{self.api_url}/posts",
            headers=headers,
            params=params,
            timeout=30
        )
        if response.status_code == 200:
            total_pages = int(response.headers.get('X-WP-TotalPages', 1))
            return True, response.json(), total_pages
        return False, response.text, 0
        
    def update_post(self, post_id, data):
        headers = self._get_auth()
        headers['Content-Type'] = 'application/json'
        
        response = requests.post(
            f"{self.api_url}/posts/{post_id}",
            headers=headers,
            json=data,
            timeout=30
        )
        return response.status_code == 200, response.json() if response.status_code == 200 else response.text

