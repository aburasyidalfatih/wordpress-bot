from datetime import datetime, timedelta, timezone

from services.article_generator import sanitize_filename
from services.quality_gate import (
    MAX_TITLE_LENGTH, fit_meta_description, link_host, normalize_link_url, plain_text, sanitize_article_html,
)
from services.url_safety import validate_public_http_url
import requests
import base64
import html as html_mod
import re
import time
import unicodedata
import urllib.parse
from io import BytesIO
import logging
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from urllib3.exceptions import NewConnectionError

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
    return validate_public_http_url(url)


def _refusal_message(error):
    """User-facing text for a WordPress URL refused by the SSRF check."""
    return f"Menolak menghubungi situs WordPress: {error}"


# Placeholder markers the model sometimes emits instead of real content.
_PLACEHOLDER_PATTERNS = [
    r'\[FLOWCHART:.*?\]',
    r'\[INFOGRAPHIC:.*?\]',
    r'\[CHECKLIST:.*?\]',
    r'\[DIAGRAM:.*?\]',
    r'\[IMAGE:.*?\]',
    r'\[CHART:.*?\]',
    r'\[TABLE:.*?\]',
]


def _clean_content(content):
    """Strip model artifacts (placeholders, ASCII art, JSON debris), then reduce the
    HTML to the article allow-list (sanitize_article_html), which also closes
    broken tags. Runs before the publisher adds its own boxes and embeds."""
    for pattern in _PLACEHOLDER_PATTERNS:
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

    # No fallback to the raw HTML: content that cannot be sanitized is not published.
    return sanitize_article_html(content)


TAKEAWAYS_HEADINGS = {'en': 'Key takeaways', 'id': 'Poin penting'}


def _key_takeaways_box(key_takeaways, language=None):
    """Summary box in the site's language, or '' when there is nothing to list."""
    items = [str(k).strip() for k in key_takeaways if str(k).strip()]
    if not items:
        return ''
    heading = TAKEAWAYS_HEADINGS['en' if language == 'en' else 'id']
    rows = ''.join(f'<li>{html_mod.escape(item, quote=False)}</li>' for item in items)
    return (f'<div class="key-takeaways" style="background:#f0f9ff; padding:20px; border-radius:8px; '
            f'border-left:5px solid #0ea5e9; margin-bottom:25px;">\n'
            f'<p style="margin-top:0; font-weight:600; color:#0369a1;">{heading}</p>\n'
            f'<ul style="margin-bottom:0;">{rows}</ul>\n</div>')


def _faq_section(faqs):
    """Visible FAQ section, or '' when no FAQ has both a question and an answer.

    No FAQPage JSON-LD: Google no longer shows FAQ rich results, and the site's
    SEO plugin owns the page's structured data.
    """
    items = []
    for faq in faqs or []:
        if not isinstance(faq, dict):
            continue
        question = str(faq.get('question') or '').strip()
        answer = str(faq.get('answer') or '').strip()
        if question and answer:
            items.append(f'<h3>{html_mod.escape(question, quote=False)}</h3>\n'
                         f'<p>{html_mod.escape(answer, quote=False)}</p>')
    if not items:
        return ''
    return '\n<h2>FAQ</h2>\n' + '\n'.join(items) + '\n'


# Slugs: short, readable, no year (a dated URL goes stale while the post is
# updated) and no dangling stopword at either end.
MAX_SLUG_CHARS = 60
MAX_SLUG_WORDS = 8
SLUG_STOPWORDS = frozenset({
    # English
    'a', 'an', 'the', 'and', 'or', 'of', 'in', 'on', 'at', 'to', 'for', 'with', 'by', 'from', 'vs',
    'into', 'about', 'as', 'your', 'our', 'via', 'per',
    # Indonesian
    'di', 'ke', 'dari', 'untuk', 'dan', 'yang', 'dengan', 'pada', 'atau', 'dalam', 'bagi', 'oleh',
    # Pure connectives only: words that carry meaning ("tanpa", "saat") stay.
    'serta', 'agar', 'supaya', 'tentang', 'sebagai', 'melalui', 'demi', 'kepada', 'terhadap',
})
# A focus-keyword slug needs at least this many words, so a bare head term
# ("digitalisasi-pendidikan") does not become the post URL.
MIN_KEYWORD_SLUG_WORDS = 3
_YEAR_RE = re.compile(r'^(?:19|20)\d{2}$')


def _slug_words(text):
    """Lower-case ASCII words: accents transliterated, apostrophes dropped, years removed."""
    text = unicodedata.normalize('NFKD', str(text or '')).encode('ascii', 'ignore').decode('ascii').lower()
    text = text.replace("'", '')
    return [w for w in re.findall(r'[a-z0-9]+', text) if not _YEAR_RE.match(w)]


def _trim_slug_words(words):
    """Drop stopwords and bare numbers (list counts, leftovers like "in 2026") from
    both ends, cap the length on a word boundary, then trim the new end again."""
    def trim(ws):
        start, end = 0, len(ws)
        while start < end and (ws[start] in SLUG_STOPWORDS or ws[start].isdigit()):
            start += 1
        while end > start and (ws[end - 1] in SLUG_STOPWORDS or ws[end - 1].isdigit()):
            end -= 1
        return ws[start:end]

    capped = []
    for word in trim(words):
        if len(capped) >= MAX_SLUG_WORDS or len('-'.join(capped + [word])) > MAX_SLUG_CHARS:
            break
        capped.append(word)
    return trim(capped)


def _contains_run(words, run):
    """True when run occurs as consecutive words in words."""
    n = len(run)
    return n > 0 and any(words[i:i + n] == run for i in range(len(words) - n + 1))


def _restates_category(keyword_words, category):
    """True when the keyword slug equals, or is contained in, a category name or slug."""
    names = [category] if isinstance(category, str) else list(category or [])
    for name in names:
        category_words = _slug_words(name)
        if category_words and _contains_run(category_words, keyword_words):
            return True
    return False


def make_post_slug(title, focus_keyword=None, category=None):
    """Short slug for a new post, or '' to let WordPress derive one.

    The focus keyword is used when it is descriptive: at least
    MIN_KEYWORD_SLUG_WORDS words with two or more content words, at least half
    of which appear in the title, and not equal to (or contained in) the
    category name or slug (category: a name/slug or a list of them). A slug
    like /digitalisasi-pendidikan/digitalisasi-pendidikan/, or a post slug
    equal to /category/debt-payoff-strategies/, says nothing about the post and
    collides with the next one on the same head term. Otherwise the title is
    used. Numbers inside the slug are kept ("pph-21-karyawan").
    """
    title_words = _slug_words(title)
    keyword_words = _trim_slug_words(_slug_words(focus_keyword))
    content_words = [w for w in keyword_words if w not in SLUG_STOPWORDS and not w.isdigit()]
    if (len(keyword_words) >= MIN_KEYWORD_SLUG_WORDS and len(content_words) >= 2
            and 2 * sum(w in title_words for w in content_words) >= len(content_words)
            and not _restates_category(keyword_words, category)):
        return '-'.join(keyword_words)
    return '-'.join(_trim_slug_words(title_words))


# Featured image file names follow the post slug: whole words, at most this long.
MAX_IMAGE_FILENAME_CHARS = 60

MEDIA_DESCRIPTIONS = {'en': 'Illustration for the article: {title}', 'id': 'Ilustrasi untuk artikel: {title}'}


def image_file_stem(title, slug=None):
    """File name (without extension) for a featured image: the post slug when
    given, else the title cut on a word boundary (at most
    MAX_IMAGE_FILENAME_CHARS, no year and no dangling stopword)."""
    stem = sanitize_filename(str(slug or '').strip().lower())
    if len(stem) > MAX_IMAGE_FILENAME_CHARS:
        stem = stem[:MAX_IMAGE_FILENAME_CHARS + 1].rsplit('-', 1)[0]
    stem = stem.strip('-._')
    if not stem:
        stem = '-'.join(_trim_slug_words(_slug_words(title)))
    return stem or 'featured-image'


# ---------------------------------------------------------------------------
# Sources section: built in code from the research sources the final content
# actually links to, never written by the model.
# ---------------------------------------------------------------------------

SOURCES_HEADINGS = {'en': 'Sources', 'id': 'Sumber'}
MAX_SOURCES_LISTED = 8
SOURCES_SECTION_CLASS = 'article-sources'
_SOURCES_SECTION_RE = re.compile(
    r'\s*<div class="' + SOURCES_SECTION_CLASS + r'">.*?</div>', re.DOTALL | re.IGNORECASE)
# A link list the model put under its own "Sources"/"Referensi" heading at the
# very end of the content: replaced by the code-built section.
_MODEL_SOURCES_TAIL_RE = re.compile(
    r'\s*<h[23][^>]*>\s*(?:sumber(?: referensi| rujukan)?|referensi|rujukan|daftar pustaka|sources?|references?'
    r'|further reading)\s*:?\s*</h[23]>\s*<(ul|ol)\b[^>]*>(?:(?!</?(?:ul|ol)\b|<h[1-6]\b).)*</\1>\s*$',
    re.DOTALL | re.IGNORECASE)
_HREF_RE = re.compile(r'<a\b[^>]*?\bhref=["\']([^"\']+)["\']', re.IGNORECASE)


def cited_sources(content, citable, own_hosts=()):
    """Citable sources the content links to, in order of first use.

    citable: dicts with 'url' and 'title' (services.article_prompts
    .citable_sources). Links match the way the link allow-list does
    (http/https, "www." and a trailing slash do not matter). Links to own_hosts
    are internal, not sources. De-duplicated, at most MAX_SOURCES_LISTED.
    """
    by_key = {}
    for source in citable or []:
        if isinstance(source, dict) and source.get('url'):
            by_key.setdefault(normalize_link_url(source['url']), source)
    own = {str(h).lower().removeprefix('www.') for h in own_hosts or () if h}
    used, seen = [], set()
    for href in _HREF_RE.findall(content or ''):
        key = normalize_link_url(href)
        source = by_key.get(key)
        if source is None or key in seen or link_host(href) in own:
            continue
        seen.add(key)
        used.append(source)
        if len(used) >= MAX_SOURCES_LISTED:
            break
    return used


def _source_label(source):
    title = plain_text(source.get('title'))
    host = link_host(source.get('url'))
    if title and host and host not in title.lower():
        return f"{title} ({host})"
    return title or host or str(source.get('url'))


def sources_section(sources, language=None):
    """The visible "Sumber"/"Sources" section, or '' when nothing was cited.

    Wrapped in <div class="article-sources"> (which sanitize_article_html
    keeps) so a later run recognises and replaces it instead of adding another.
    """
    items = []
    for source in sources or []:
        url = str(source.get('url') or '')
        if not url.lower().startswith(('http://', 'https://')):
            continue
        # Attributes in the order sanitize_article_html writes them, so the
        # section passes through it unchanged.
        items.append(f'<li><a href="{html_mod.escape(url, quote=True)}" rel="noopener" target="_blank">'
                     f'{html_mod.escape(_source_label(source), quote=False)}</a></li>')
    if not items:
        return ''
    heading = SOURCES_HEADINGS['en' if language == 'en' else 'id']
    return (f'\n<div class="{SOURCES_SECTION_CLASS}">\n<h2>{heading}</h2>\n<ul>\n'
            + '\n'.join(items) + '\n</ul>\n</div>\n')


def strip_sources_section(content):
    """Content without a code-built sources section or a model-written one at the very end."""
    content = _SOURCES_SECTION_RE.sub('', content or '')
    return _MODEL_SOURCES_TAIL_RE.sub('', content)


def _youtube_iframe(video_id):
    return (
        '\n<div class="video-container" style="position: relative; padding-bottom: 56.25%; '
        'height: 0; overflow: hidden; max-width: 100%;">'
        '<iframe style="position: absolute; top: 0; left: 0; width: 100%; height: 100%;" '
        f'src="https://www.youtube.com/embed/{video_id}" frameborder="0" loading="lazy" '
        'title="Related video" '
        'allow="accelerometer; clipboard-write; encrypted-media; gyroscope; picture-in-picture" '
        'allowfullscreen></iframe></div>\n'
    )


# ddgs is a metasearch client whose "auto" backend mixes in Wikipedia-style
# results; the YouTube embed search wants plain DuckDuckGo results.
YOUTUBE_SEARCH_BACKEND = 'duckduckgo'


def _ddgs_text_search(query, max_results=5):
    """Text search through ddgs (explicit backend), or the old duckduckgo_search
    package, which does not know ddgs' backend names."""
    # Local import: only needed by the opt-in YouTube embed.
    try:
        from ddgs import DDGS
    except ImportError:
        from duckduckgo_search import DDGS as LegacyDDGS
        return list(LegacyDDGS().text(query, max_results=max_results) or [])
    return list(DDGS().text(query, max_results=max_results, backend=YOUTUBE_SEARCH_BACKEND) or [])


def _insert_mid_article(content, snippet):
    """Insert snippet before the middle H2, or append it when there are fewer than one."""
    parts = re.split(r'(<h2.*?>)', content)
    if len(parts) < 3:
        return content + snippet
    mid_idx = len(parts) // 2
    if mid_idx % 2 == 0:
        mid_idx += 1
    parts.insert(mid_idx, snippet)
    return "".join(parts)


def _seo_meta_fields(meta_description, focus_keyword):
    """Yoast and Rank Math meta, so either SEO plugin picks it up."""
    meta_fields = {}
    if meta_description:
        meta_fields['_yoast_wpseo_metadesc'] = meta_description
        meta_fields['rank_math_description'] = meta_description
    if focus_keyword:
        meta_fields['_yoast_wpseo_focuskw'] = focus_keyword
        meta_fields['rank_math_focus_keyword'] = focus_keyword
    return meta_fields


class WordPressPublisher:
    def __init__(self, url, username, password, site_name=None, enable_youtube_embed=False, language=None):
        self.url = url.rstrip('/')
        self.language = language
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
            raise UnsafeURLError(_refusal_message(self.url_error))
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
                raise UnsafeURLError(f"Menolak redirect ke URL non-publik: {error}")
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
    def upload_image(self, image_data, title, slug=None):
        """Upload image via WordPress REST API.

        The file is named after the post slug, or the title cut on a word
        boundary (image_file_stem). Alt text and title are the post title; the
        media description is in the site's language.

        Transient network errors (ConnectionError, Timeout) propagate to trigger retry.
        Non-transient errors (bad status, data issues) are caught and return None immediately."""
        title = plain_text(title)
        file_stem = image_file_stem(title, slug)
        if isinstance(image_data, BytesIO):
            image_bytes = image_data.getvalue()
            filename = f'{file_stem}.webp'
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
            filename = f'{file_stem}.jpg'
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
                    'description': MEDIA_DESCRIPTIONS['en' if self.language == 'en' else 'id'].format(title=title),
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
            results = _ddgs_text_search(f"site:youtube.com {search_term}", max_results=5)
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

    def _prepare_post_payload(self, title, content, category_id=None, featured_image_id=None, meta_description=None,
                              excerpt=None, focus_keyword=None, key_takeaways=None, faqs=None, author_name=None,
                              set_slug=True, category_name=None, citable_sources=None):
        """Build the REST payload. Returns (post_data, SEO meta fields).

        No JSON-LD is added: the site's SEO plugin (Rank Math/Yoast) already
        outputs the Article/BlogPosting schema, and AutoWP's own copy duplicated
        it. The plugin gets the focus keyword and meta description through the
        meta fields. author_name is still accepted from callers but unused.

        Layout: key takeaways box, content, sources section, FAQ.
        citable_sources: the research sources the writer was allowed to cite
        (dicts with 'url' and 'title', see article_prompts.citable_sources); the
        ones the final content links to are listed under "Sumber"/"Sources".
        The meta description is cut to PUBLISH_META_MAX_CHARS. category_name
        keeps the slug from repeating the category.

        set_slug=False leaves the slug alone, so an updated post keeps its URL.
        """
        content = _clean_content(content)
        # Before the old section is removed: links in a sources list the model
        # wrote itself still count as used.
        cited = cited_sources(content, citable_sources, own_hosts=[link_host(self.url)])
        # A sources section from an earlier run (or the model's own) is replaced, never duplicated.
        content = strip_sources_section(content)
        # WordPress shows these as they are: plain text only.
        title = plain_text(title)
        if len(title) > MAX_TITLE_LENGTH:
            # Not cut: a mechanically shortened title can change its meaning.
            logger.warning(f"Post title is {len(title)} characters (target at most 60); search results "
                           f"will truncate it: {title!r}")
        excerpt = plain_text(excerpt) if excerpt else excerpt
        if meta_description:
            plain_meta = plain_text(meta_description)
            meta_description = fit_meta_description(plain_meta)
            if meta_description != plain_meta:
                logger.info(f"Meta description trimmed from {len(plain_meta)} to {len(meta_description)} characters.")
        if key_takeaways and isinstance(key_takeaways, list):
            content = _key_takeaways_box(key_takeaways, self.language) + "\n" + content

        # YouTube auto-embed. Opt-in, and only when a result's title actually overlaps
        # the article topic — previously the first search hit was embedded blind, which
        # could put an unrelated or competitor video in the middle of the article.
        # Embedded before the Sources and FAQ sections are added, so it always
        # lands in the article body (their H2s would otherwise count as sections).
        if self.enable_youtube_embed:
            video_id = self._find_relevant_video(focus_keyword or title)
            if video_id:
                content = _insert_mid_article(content, _youtube_iframe(video_id))

        content += sources_section(cited, self.language)
        if faqs and isinstance(faqs, list):
            content += _faq_section(faqs)

        post_data = {
            'title': title,
            'content': content,
            'status': 'publish',
        }
        slug = make_post_slug(title, focus_keyword, category_name) if set_slug else ''
        if slug:
            post_data['slug'] = slug
        if category_id:
            post_data['categories'] = [category_id]
        if featured_image_id:
            post_data['featured_media'] = featured_image_id
        if excerpt:
            post_data['excerpt'] = excerpt

        meta_fields = _seo_meta_fields(meta_description, focus_keyword)
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
        reason = exc.args[0] if exc.args else None
        reason = getattr(reason, 'reason', reason)
        return isinstance(reason, NewConnectionError)

    def _find_created_post(self, title, slug, not_before):
        """Look for a post this publisher just created whose response was lost.

        Matches on exact title or slug, and only posts dated after the create
        attempt began, so an older article with the same title is not mistaken
        for it. Returns the post dict or None.
        """
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

    def create_post(self, title, content, category_id=None, featured_image_id=None, meta_description=None, excerpt=None,
                    focus_keyword=None, key_takeaways=None, faqs=None, author_name=None, category_name=None,
                    citable_sources=None):
        """Create a post. Returns (success, post_dict | error_text).

        POST /posts is not idempotent, so it is never retried once the request may
        have reached WordPress: a read timeout, a dropped connection mid-response
        or a 502/504/524 gateway timeout can all mean the post was saved anyway, and
        retrying created duplicates. In that case a matching recent post is looked
        up; if none is found the error text starts with "TIMEOUT" so the caller
        keeps the credit and does not auto-retry. Only a failure to connect at all
        (the request was provably never sent) is retried.
        """
        headers = self._get_auth()
        headers['Content-Type'] = 'application/json'
        post_data, meta_fields = self._prepare_post_payload(
            title, content, category_id, featured_image_id, meta_description, excerpt, focus_keyword, key_takeaways,
            faqs, author_name, category_name=category_name, citable_sources=citable_sources)
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
                    time.sleep(2 * (attempt + 1))
                    continue
                if self._request_never_sent(e):
                    # The exception text is deliberately left out of the result: it
                    # can contain "connect timeout", which the caller would read as
                    # the TIMEOUT marker and keep the credit for a post never sent.
                    logger.error(f"Could not connect to WordPress to publish the post: {e}")
                    return False, "Gagal terhubung ke WordPress; postingan tidak terkirim."
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
                    time.sleep(5)
                found = self._find_created_post(post_data['title'], post_data.get('slug'), not_before)
                if found:
                    logger.info(f"Found post {found.get('id')} created despite the lost response.")
                    return True, found
            # Starts with UNCONFIRMED_POST_MARKER, which is_unconfirmed_post_result checks.
            return False, (
                f"{UNCONFIRMED_POST_MARKER}: WordPress tidak mengonfirmasi postingan ({reason}). "
                "Postingan mungkin sudah terbit; cek WordPress sebelum mencoba lagi."
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

    def update_post_content(self, post_id, title, content, category_id=None, featured_image_id=None,
                            meta_description=None, excerpt=None, focus_keyword=None, key_takeaways=None, faqs=None,
                            author_name=None, citable_sources=None):
        if not self._ensure_url_ok():
            return False, _refusal_message(self.url_error)
        headers = self._get_auth()
        headers['Content-Type'] = 'application/json'
        # An existing post keeps its slug: changing it would move a live URL.
        post_data, meta_fields = self._prepare_post_payload(
            title, content, category_id, featured_image_id, meta_description, excerpt, focus_keyword,
            key_takeaways, faqs, author_name, set_slug=False, citable_sources=citable_sources)
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
            return False, _refusal_message(self.url_error), 0
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
            return False, _refusal_message(self.url_error)
        headers = self._get_auth()
        headers['Content-Type'] = 'application/json'

        response = self._request('POST',
            f"{self.api_url}/posts/{post_id}",
            headers=headers,
            json=data,
            timeout=30
        )
        return response.status_code == 200, response.json() if response.status_code == 200 else response.text

