from datetime import datetime, timedelta, timezone

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

# Prefix of the create_post error text meaning "the request reached WordPress but
# the outcome is unknown, the post may exist".
UNCONFIRMED_POST_MARKER = 'TIMEOUT'


def is_unconfirmed_post_result(result):
    """True when create_post could not confirm whether the post was created."""
    return isinstance(result, str) and result.strip().upper().startswith(UNCONFIRMED_POST_MARKER)


# Redirects are followed manually so every hop is re-checked against SSRF rules.
MAX_REDIRECTS = 3


class UnsafeURLError(requests.exceptions.InvalidURL):
    """The WordPress URL (or a redirect target) is not a public http(s) URL.

    A RequestException subclass, so callers that already handle request errors
    report it through their usual failure path.
    """


def _validate_url(url):
    try:
        from services.url_safety import validate_public_http_url
    except ImportError:  # pragma: no cover - module ships with the routes change
        logger.error("services.url_safety is unavailable; refusing outbound WordPress request.")
        return False, 'URL safety check unavailable'
    return validate_public_http_url(url)


class WordPressPublisher:
    def __init__(self, url, username, password, site_name=None, enable_youtube_embed=False):
        self.url = url.rstrip('/')
        self._raw_url = self.url
        # The base URL is user-supplied and fetched from inside the server
        # network, so it must be a public http(s) URL. The constructor never
        # raises (callers build publishers freely); requests are refused instead.
        self.url_ok, checked = _validate_url(self.url)
        if self.url_ok:
            self.url = checked
            self.url_error = None
        else:
            self.url_error = checked
            logger.error(f"WordPress URL rejected by safety check ({self.url}): {checked}")
        self.username = username
        self.password = password
        self.site_name = site_name
        # Off by default: an auto-picked video is only worth embedding when it is
        # genuinely relevant, so this is opt-in per site.
        self.enable_youtube_embed = enable_youtube_embed
        self.api_url = f"{self.url}/wp-json/wp/v2"

    def _ensure_url_ok(self):
        """Re-run the safety check if it failed earlier.

        The publisher is built before a multi-minute generation; a transient
        DNS failure at that moment must not make the final publish refuse.
        """
        if self.url_ok:
            return True
        ok, checked = _validate_url(self._raw_url)
        if ok:
            self.url_ok, self.url, self.url_error = True, checked, None
            self.api_url = f"{self.url}/wp-json/wp/v2"
        else:
            self.url_error = checked
        return self.url_ok

    def _request(self, method, url, check_base=True, **kwargs):
        """requests.request with SSRF protection.

        Refuses to run when the site URL failed validation, never lets requests
        follow redirects on its own, and follows at most MAX_REDIRECTS hops
        manually after validating each target (http -> https upgrades keep
        working). A redirected POST/PUT is only re-sent for 307/308, which
        preserve the method; otherwise the 3xx response is returned as-is.
        Raises UnsafeURLError when a URL is refused.
        """
        if check_base and not self._ensure_url_ok():
            raise UnsafeURLError(f"Refusing to contact WordPress site: {self.url_error}")
        kwargs['allow_redirects'] = False
        method = method.upper()
        response = requests.request(method, url, **kwargs)
        current_url = url
        for _ in range(MAX_REDIRECTS):
            if not response.is_redirect:
                break
            if method not in ('GET', 'HEAD') and response.status_code not in (307, 308):
                break
            location = urllib.parse.urljoin(current_url, response.headers.get('Location', ''))
            ok, error = _validate_url(location)
            if not ok:
                logger.error(f"Refusing redirect from {current_url} to {location}: {error}")
                raise UnsafeURLError(f"Refusing redirect to non-public URL: {error}")
            if urllib.parse.urlsplit(location).hostname != urllib.parse.urlsplit(current_url).hostname:
                # Never forward credentials to a different host.
                headers = dict(kwargs.get('headers') or {})
                headers.pop('Authorization', None)
                kwargs['headers'] = headers
            current_url = location
            response = requests.request(method, current_url, **kwargs)
        return response

    def _get_auth(self):
        credentials = f"{self.username}:{self.password}"
        token = base64.b64encode(credentials.encode()).decode()
        return {'Authorization': f'Basic {token}'}

    def get_post_stats(self, post_id):
        """Get post statistics from WordPress"""
        try:
            response = self._request('GET',
                f"{self.api_url}/posts/{post_id}",
                headers=self._get_auth(),
                timeout=10
            )

            if response.status_code == 200:
                post = response.json()

                # Get comments count
                comments_response = self._request('GET',
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
            response = self._request('GET',
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
            ok, error = _validate_url(image_data)
            if not ok:
                logger.error(f"Refusing to download image from non-public URL: {error}")
                return None
            response = self._request('GET', image_data, check_base=False, timeout=30)
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
            response = self._request('POST',
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
                self._request('POST',
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

    def _find_relevant_video(self, search_term):
        """Find a YouTube video whose title genuinely overlaps the search term.

        Returns a video id, or None when nothing sufficiently relevant is found.
        Embedding an unrelated video hurts the page more than having no video.
        """
        if not search_term:
            return None

        stopwords = {
            'the', 'and', 'for', 'with', 'that', 'this', 'from', 'what', 'how',
            'yang', 'dan', 'untuk', 'dengan', 'dari', 'apa', 'bagaimana', 'di', 'ke'
        }

        def tokens(text):
            words = re.findall(r'\w+', (text or '').lower())
            return {w for w in words if len(w) > 2 and w not in stopwords}

        wanted = tokens(search_term)
        if not wanted:
            return None

        try:
            from duckduckgo_search import DDGS
            results = DDGS().text(f"site:youtube.com {search_term}", max_results=5) or []
        except Exception as e:
            logger.warning(f"YouTube search failed: {e}")
            return None

        for result in results:
            url = result.get('href', '') or ''
            candidate_tokens = tokens(f"{result.get('title', '')} {result.get('body', '')}")
            if not candidate_tokens:
                continue

            overlap = len(wanted & candidate_tokens) / len(wanted)
            if overlap < 0.5:
                continue

            parsed = urllib.parse.urlparse(url)
            video_id = None
            if 'youtube.com/watch' in url:
                video_id = urllib.parse.parse_qs(parsed.query).get('v', [None])[0]
            elif 'youtu.be/' in url:
                video_id = parsed.path.lstrip('/')

            if video_id and re.match(r'^[a-zA-Z0-9_-]{11}$', video_id):
                logger.info(f"Embedding YouTube video {video_id} (title overlap {overlap:.0%})")
                return video_id

        logger.info(f"No sufficiently relevant YouTube video found for '{search_term}'; skipping embed.")
        return None

    def get_categories(self):
        """Fetch all categories from WordPress"""
        try:
            response = self._request('GET',
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

    def _prepare_post_payload(self, title, content, category_id=None, featured_image_id=None, meta_description=None, excerpt=None, focus_keyword=None, key_takeaways=None, faqs=None, author_name=None):

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

        # Re-serialize through BeautifulSoup to close broken/unbalanced tags.
        try:
            from bs4 import BeautifulSoup
            content = str(BeautifulSoup(content, 'html.parser'))
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

        # Structured data. FAQPage rich results are heavily restricted these days, so
        # its main value is as machine-readable Q&A for answer engines. BlogPosting is
        # what actually carries the authorship and freshness signals.
        graph = []

        blog_posting = {
            "@type": "BlogPosting",
            "headline": title[:110],
            "datePublished": datetime.now().astimezone().isoformat(),
            "dateModified": datetime.now().astimezone().isoformat(),
            "publisher": {"@type": "Organization", "name": self.site_name or self.url},
            "mainEntityOfPage": {"@type": "WebPage", "@id": self.url}
        }
        if author_name:
            blog_posting["author"] = {"@type": "Person", "name": author_name}
        else:
            blog_posting["author"] = {"@type": "Organization", "name": self.site_name or self.url}
        if meta_description:
            blog_posting["description"] = meta_description
        if focus_keyword:
            blog_posting["keywords"] = focus_keyword
        graph.append(blog_posting)

        if faqs and isinstance(faqs, list):
            faq_schema = {"@type": "FAQPage", "mainEntity": []}
            for faq in faqs:
                if 'question' in faq and 'answer' in faq:
                    faq_schema["mainEntity"].append({
                        "@type": "Question",
                        "name": faq["question"],
                        "acceptedAnswer": {
                            "@type": "Answer",
                            "text": faq["answer"]
                        }
                    })
            if faq_schema["mainEntity"]:
                graph.append(faq_schema)

        schema_payload = {"@context": "https://schema.org", "@graph": graph}
        content += f'\n<script type="application/ld+json">{json.dumps(schema_payload, ensure_ascii=False)}</script>\n'


        # YouTube auto-embed. Opt-in, and only when a result's title actually overlaps
        # the article topic — previously the first search hit was embedded blind, which
        # could put an unrelated or competitor video in the middle of the article.
        if self.enable_youtube_embed:
            video_id = self._find_relevant_video(focus_keyword or title)
            if video_id:
                iframe = (
                    '\n<div class="video-container" style="position: relative; padding-bottom: 56.25%; '
                    'height: 0; overflow: hidden; max-width: 100%;">'
                    '<iframe style="position: absolute; top: 0; left: 0; width: 100%; height: 100%;" '
                    f'src="https://www.youtube.com/embed/{video_id}" frameborder="0" loading="lazy" '
                    'title="Related video" '
                    'allow="accelerometer; clipboard-write; encrypted-media; gyroscope; picture-in-picture" '
                    'allowfullscreen></iframe></div>\n'
                )
                parts = re.split(r'(<h2.*?>)', content)
                if len(parts) >= 3:
                    mid_idx = len(parts) // 2
                    if mid_idx % 2 == 0:
                        mid_idx += 1
                    parts.insert(mid_idx, iframe)
                    content = "".join(parts)
                else:
                    content += iframe

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

    @staticmethod
    def _request_never_sent(exc):
        """True only when the connection was never established, so WordPress
        cannot have received (and saved) the request."""
        if isinstance(exc, requests.exceptions.ConnectTimeout):
            return True
        if not isinstance(exc, requests.exceptions.ConnectionError):
            return False
        try:
            from urllib3.exceptions import NewConnectionError
        except ImportError:  # pragma: no cover
            return False
        reason = exc.args[0] if exc.args else None
        reason = getattr(reason, 'reason', reason)
        return isinstance(reason, NewConnectionError)

    def _find_created_post(self, title, slug, not_before):
        """Look for a post this publisher just created whose response was lost.

        Matches on exact title or slug, and only posts dated after the create
        attempt began, so an older article with the same title is not mistaken
        for it. Returns the post dict or None.
        """
        import html as html_mod

        wanted_title = (title or '').strip()
        wanted_slug = re.sub(r'[\s_-]+', '-', re.sub(r'[^\w\s-]', '', (slug or '').lower())).strip('-')
        attempts = [
            {'search': wanted_title[:100], 'per_page': 10, 'orderby': 'date', 'order': 'desc',
             'context': 'edit', 'status': 'publish,future,draft,pending,private'},
            {'search': wanted_title[:100], 'per_page': 10, 'orderby': 'date', 'order': 'desc'},
        ]
        for params in attempts:
            try:
                response = self._request('GET',
                    f"{self.api_url}/posts", headers=self._get_auth(), params=params, timeout=20
                )
            except requests.exceptions.RequestException as e:
                logger.warning(f"Could not check for a post created before the timeout: {e}")
                continue
            if response.status_code != 200:
                continue
            for post in response.json() or []:
                title_obj = post.get('title') or {}
                post_title = title_obj.get('raw') or html_mod.unescape(title_obj.get('rendered') or '')
                post_slug = urllib.parse.unquote(post.get('slug') or '').lower()
                if post_title.strip() != wanted_title and (not wanted_slug or post_slug != wanted_slug):
                    continue
                try:
                    created = datetime.fromisoformat((post.get('date_gmt') or '').replace('Z', ''))
                except ValueError:
                    created = None
                if created is not None and created < not_before:
                    continue
                return post
            return None
        return None

    def create_post(self, title, content, category_id=None, featured_image_id=None, meta_description=None, excerpt=None, focus_keyword=None, key_takeaways=None, faqs=None, author_name=None):
        """Create a post. Returns (success, post_dict | error_text).

        POST /posts is not idempotent, so it is never retried once the request may
        have reached WordPress: a read timeout, a dropped connection mid-response
        or a 502/504/524 gateway timeout can all mean the post was saved anyway, and
        retrying created duplicates. In that case a matching recent post is looked
        up; if none is found the error text starts with "TIMEOUT" so the caller
        keeps the credit and does not auto-retry. Only a failure to connect at all
        (the request was provably never sent) is retried.
        """
        import time as time_mod

        headers = self._get_auth()
        headers['Content-Type'] = 'application/json'
        post_data, meta_fields = self._prepare_post_payload(title, content, category_id, featured_image_id, meta_description, excerpt, focus_keyword, key_takeaways, faqs, author_name)
        # date_gmt from WordPress has no timezone; compare in naive UTC with slack
        # for clock skew between this server and WordPress.
        not_before = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0) - timedelta(minutes=10)

        response = None
        ambiguous_error = None
        for attempt in range(3):
            try:
                response = self._request('POST',
                    f"{self.api_url}/posts",
                    headers=headers,
                    json=post_data,
                    timeout=60
                )
                break
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                if self._request_never_sent(e) and attempt < 2:
                    logger.warning(f"Could not connect to WordPress (attempt {attempt + 1}/3), retrying: {e}")
                    time_mod.sleep(2 * (attempt + 1))
                    continue
                if self._request_never_sent(e):
                    # The exception text is deliberately left out of the result: it
                    # can contain "connect timeout", which the caller would read as
                    # the TIMEOUT marker and keep the credit for a post never sent.
                    logger.error(f"Could not connect to WordPress to publish the post: {e}")
                    return False, "WordPress connection failed; the post was not sent."
                ambiguous_error = e
                break
            except Exception as e:
                logger.error(f"Error publishing post to WordPress: {e}")
                return False, str(e)

        if ambiguous_error is not None or (response is not None and response.status_code in (502, 504, 524)):
            reason = str(ambiguous_error) if ambiguous_error is not None else f"HTTP {response.status_code}"
            logger.error(
                f"WordPress did not confirm the post ({reason}); it may still have been "
                "created. Checking before giving up."
            )
            for check in range(3):
                if check:
                    time_mod.sleep(5)
                found = self._find_created_post(title, post_data.get('slug'), not_before)
                if found:
                    logger.info(f"Found post {found.get('id')} created despite the lost response.")
                    return True, found
            return False, (
                f"TIMEOUT: WordPress did not confirm the post ({reason}). It may have been "
                "published; check WordPress before retrying."
            )

        # If post created successfully, try to update Yoast meta separately
        if response.status_code == 201 and meta_fields:
            post_id = response.json().get('id')
            try:
                # Update post meta using WordPress REST API
                update_response = self._request('POST',
                    f"{self.api_url}/posts/{post_id}",
                    headers=headers,
                    json={'meta': meta_fields},
                    timeout=30
                )
                logger.info(f"Yoast meta update: {update_response.status_code}")
            except Exception as e:
                logger.warning(f"Could not update Yoast meta: {e}")

        return response.status_code == 201, response.json() if response.status_code == 201 else response.text

    def update_post_content(self, post_id, title, content, category_id=None, featured_image_id=None, meta_description=None, excerpt=None, focus_keyword=None, key_takeaways=None, faqs=None, author_name=None):
        if not self._ensure_url_ok():
            return False, f"Refusing to contact WordPress site: {self.url_error}"
        headers = self._get_auth()
        headers['Content-Type'] = 'application/json'
        post_data, meta_fields = self._prepare_post_payload(title, content, category_id, featured_image_id, meta_description, excerpt, focus_keyword, key_takeaways, faqs, author_name)
        response = self._request('POST',
            f"{self.api_url}/posts/{post_id}",
            headers=headers,
            json=post_data,
            timeout=30
        )

        # If post updated successfully, try to update Yoast meta separately
        if response.status_code == 200 and meta_fields:
            try:
                # Update post meta using WordPress REST API
                update_response = self._request('POST',
                    f"{self.api_url}/posts/{post_id}",
                    headers=headers,
                    json={'meta': meta_fields},
                    timeout=30
                )
                logger.info(f"Yoast meta update: {update_response.status_code}")
            except Exception as e:
                logger.warning(f"Could not update Yoast meta: {e}")

        return response.status_code == 200, response.json() if response.status_code == 200 else response.text


    def get_posts(self, page=1, per_page=100, search=None, context=None):
        """List posts. Pass context='edit' to get title.raw/content.raw, which is
        what must be written back; 'rendered' HTML is filter output (shortcodes
        expanded, auto-paragraphs) and saving it corrupts the stored post."""
        if not self._ensure_url_ok():
            return False, f"Refusing to contact WordPress site: {self.url_error}", 0
        headers = self._get_auth()
        params = {'page': page, 'per_page': per_page}
        if search:
            params['search'] = search
        if context:
            params['context'] = context

        response = self._request('GET',
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
        if not self._ensure_url_ok():
            return False, f"Refusing to contact WordPress site: {self.url_error}"
        headers = self._get_auth()
        headers['Content-Type'] = 'application/json'

        response = self._request('POST',
            f"{self.api_url}/posts/{post_id}",
            headers=headers,
            json=data,
            timeout=30
        )
        return response.status_code == 200, response.json() if response.status_code == 200 else response.text

