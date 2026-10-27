"""Pre-publish quality checks for generated articles.

These checks run after generation and before anything is sent to WordPress. The
prompt no longer sets a word count (length follows what the topic needs, without
padding), so length and structure checks are floors that catch truncated or
empty output, not targets that reward filler.

Failures are split into two kinds:
  - errors: block publishing (the credit is refunded by the caller)
  - warnings: logged, but the article still goes out
"""

import html
import re
import logging
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Comment, Declaration, Doctype, ProcessingInstruction

from services.article_generator import strip_html

logger = logging.getLogger(__name__)

# Below this the output is a stub or was cut off; it is never a complete article.
MIN_WORD_COUNT = 300
# Short but possibly complete (a focused answer): published, with a warning.
SHORT_WORD_COUNT = 600

MIN_HEADINGS = 2
MAX_TITLE_LENGTH = 70  # the prompt asks for at most 60; some slack before warning
# Search results show roughly 155-160 characters of a meta description. The
# prompts ask for 140-155; outside 120-160 the gate warns, and the publisher
# trims anything longer than PUBLISH_META_MAX_CHARS (fit_meta_description).
MIN_META_LENGTH = 120
MAX_META_LENGTH = 160
PUBLISH_META_MAX_CHARS = 158
# A cut at a sentence end is preferred while it keeps at least this much text.
MIN_SENTENCE_CUT_CHARS = 100

# Words a trimmed meta description must not end on (English and Indonesian).
_DANGLING_END_WORDS = frozenset({
    'a', 'an', 'the', 'and', 'or', 'of', 'in', 'on', 'at', 'to', 'for', 'with', 'by', 'from', 'as', 'your',
    'di', 'ke', 'dari', 'untuk', 'dan', 'yang', 'dengan', 'pada', 'atau', 'dalam', 'bagi', 'oleh', 'serta',
    'agar', 'supaya', 'tentang', 'sebagai',
})

# Phrases the old prompt actively produced. Their presence means either a stale
# custom prompt or the model ignoring the evidence policy.
FABRICATION_MARKERS = [
    r'data internal kami',
    r'berdasarkan pengalaman tim praktisi kami',
    r'our internal data shows',
    r'based on (?:our )?implementation across \d+',
    r'berdasarkan pengalaman kami menangani \d+',
]

# Structural leftovers that mean the model emitted the template instead of prose.
TEMPLATE_LEAK_MARKERS = [
    # "H2:" style labels, whether at the start of a line or just inside a tag.
    r'(?:^|>)\s*H[123]:\s',
    r'\[(?:FLOWCHART|INFOGRAPHIC|INFOGRAFIS|CHECKLIST|DIAGRAM|IMAGE|CHART|TABLE)\s*:',
    r'\{topic\}|\{title\}|\{site_name\}|\{target_site\}|\{current_year\}',
]


def _unclosed_block_tags(html):
    """Return block tags that were opened but never closed.

    Catches output cut off mid-article, which used to be published with broken markup.
    """
    tracked = ('div', 'table', 'ul', 'ol', 'section', 'blockquote')
    unclosed = []
    for tag in tracked:
        opened = len(re.findall(rf'<{tag}[\s>]', html, re.IGNORECASE))
        closed = len(re.findall(rf'</{tag}>', html, re.IGNORECASE))
        if opened > closed:
            unclosed.append(f'{tag} (x{opened - closed})')
    return unclosed


def check_article(article, focus_keyword=None, allowed_link_urls=None):
    """Validate a generated article.

    Returns (ok: bool, errors: list[str], warnings: list[str]).
    """
    errors = []
    warnings = []

    title = (article.get('title') or '').strip()
    content = article.get('content') or ''
    plain = strip_html(content)
    word_count = len(plain.split())
    keyword = (focus_keyword or article.get('focus_keyword') or '').strip()

    if not title:
        errors.append('Article has no title.')
    elif len(title) > MAX_TITLE_LENGTH:
        warnings.append(f'Title is long ({len(title)} chars); search results truncate it.')

    if not content.strip():
        errors.append('Article has no content.')
        return False, errors, warnings

    if word_count < MIN_WORD_COUNT:
        errors.append(
            f'Article is too short: {word_count} words (minimum {MIN_WORD_COUNT}); '
            'it looks incomplete.'
        )
    elif word_count < SHORT_WORD_COUNT:
        warnings.append(f'Article is short ({word_count} words); check that it fully answers the topic.')

    unclosed = _unclosed_block_tags(content)
    if unclosed:
        errors.append(f'Unclosed HTML block tags (likely truncated output): {", ".join(unclosed)}.')

    heading_count = len(re.findall(r'<h2[\s>]', content, re.IGNORECASE))
    if heading_count < MIN_HEADINGS:
        errors.append(f'Only {heading_count} H2 heading(s); expected at least {MIN_HEADINGS}.')

    for pattern in FABRICATION_MARKERS:
        if re.search(pattern, plain, re.IGNORECASE):
            errors.append(f'Content contains a manufactured-credential phrase matching "{pattern}".')

    for pattern in TEMPLATE_LEAK_MARKERS:
        if re.search(pattern, content, re.IGNORECASE | re.MULTILINE):
            errors.append(f'Content leaked a prompt template marker matching "{pattern}".')

    # Keyword placement: a warning, not a blocker. Missing it costs some ranking
    # signal but the article can still be useful.
    if keyword:
        opening = ' '.join(plain.split()[:100]).lower()
        if keyword.lower() not in opening:
            warnings.append(f'Focus keyword "{keyword}" not found in the first 100 words.')

    meta = (article.get('meta_description') or '').strip()
    if not meta:
        warnings.append('No meta description.')
    elif not (MIN_META_LENGTH <= len(meta) <= MAX_META_LENGTH):
        warnings.append(f'Meta description length {len(meta)} outside {MIN_META_LENGTH}-{MAX_META_LENGTH} '
                        f'(trimmed to {PUBLISH_META_MAX_CHARS} on publish when longer).')

    takeaways = article.get('key_takeaways') or []
    if not takeaways:
        warnings.append('No key takeaways.')

    # Links must point at URLs we actually gave the model. An unknown internal URL
    # is hallucinated (a broken link); an unknown external URL is either invented
    # or planted by scraped research text, so it is not published either.
    if allowed_link_urls is not None:
        allowed = {normalize_link_url(u) for u in allowed_link_urls if u}
        hrefs = re.findall(r'<a[^>]+href=["\']([^"\']+)["\']', content, re.IGNORECASE)
        unknown = [h for h in hrefs if not _is_allowed_href(h, allowed)]
        invented = [h for h in unknown if h.startswith('/') or _same_site(h, allowed_link_urls)]
        external = [h for h in unknown if h not in invented]
        if invented:
            warnings.append(
                f'{len(invented)} internal link(s) not in the supplied list and will be '
                f'removed: {", ".join(invented[:3])}'
            )
        if external:
            warnings.append(
                f'{len(external)} external link(s) not in the supplied list and will be '
                f'unlinked: {", ".join(external[:3])}'
            )

    return not errors, errors, warnings


def link_host(url):
    """Lower-case host of an absolute URL without a leading "www.", or ''."""
    try:
        host = urlparse(str(url or '').strip()).hostname or ''
    except (ValueError, TypeError, AttributeError):  # malformed URL: no host
        return ''
    return host.lower().removeprefix('www.')


def _normalize_host(value):
    """A host given as a URL or as a bare domain, in link_host() form."""
    value = str(value or '').strip()
    if '//' in value:
        return link_host(value)
    return value.lower().removeprefix('www.').split('/')[0]


def normalize_link_url(url):
    """Comparable form of a link: http/https, "www." and a trailing slash do not
    matter, and neither does HTML-escaping ("&amp;" in an href is "&")."""
    url = html.unescape(str(url or '')).strip()
    host = link_host(url) if '//' in url else ''
    if not host:
        return url.rstrip('/')
    parsed = urlparse(url)
    normalized = host + (parsed.path.rstrip('/') or '')
    if parsed.query:
        normalized += '?' + parsed.query
    return normalized


def _same_site(href, allowed_urls):
    """True when href shares a host with one of the allowed URLs."""
    host = link_host(href)
    if not host:
        return False
    return any(link_host(url) == host for url in allowed_urls or [])


def _is_allowed_href(href, allowed):
    """In the supplied (normalized) list, or an in-page anchor (#section), which cannot leak anywhere."""
    href = html.unescape(href or '').strip()
    return href.startswith('#') or normalize_link_url(href) in allowed


def strip_invalid_internal_links(content, allowed_link_urls, allowed_hosts=None):
    """Unwrap <a> tags whose href is not in allowed_link_urls.

    Keeps the anchor text, drops the link. Covers internal URLs the model
    invented and external URLs, which may have been planted in the scraped
    research the prompt contains. URLs in allowed_link_urls (internal posts, or
    any evidence/source URL a caller adds to it) are kept, regardless of
    http/https, "www." or a trailing slash. Absolute links to a host in
    allowed_hosts (e.g. the site's own domain) are always kept. None means "no
    list was built" and leaves content untouched; an empty list unlinks
    everything else.
    """
    if allowed_link_urls is None:
        return content

    allowed = {normalize_link_url(u) for u in allowed_link_urls if u}
    hosts = {_normalize_host(h) for h in allowed_hosts or [] if h} - {''}

    def replace(match):
        href = match.group(1)
        inner = match.group(2)
        if _is_allowed_href(href, allowed) or (hosts and link_host(href) in hosts):
            return match.group(0)
        if href.startswith('/') or _same_site(href, allowed_link_urls):
            logger.info(f'Removing hallucinated internal link: {href}')
        else:
            logger.info(f'Unlinking external link not in the allowed list: {href}')
        return inner

    return re.sub(
        r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
        replace,
        content,
        flags=re.DOTALL | re.IGNORECASE
    )


# ---------------------------------------------------------------------------
# Allow-list HTML sanitizer for the article body. Runs on every article right
# before it is published (WordPressPublisher._clean_content), so nothing the
# model, scraped research or an AI review edit put into the HTML can carry
# script, event handlers, embeds or foreign markup onto the site. The
# publisher's own boxes (key takeaways, FAQ, YouTube embed) are added after it.
# ---------------------------------------------------------------------------

ALLOWED_TAGS = frozenset((
    'p', 'h2', 'h3', 'h4', 'ul', 'ol', 'li', 'table', 'thead', 'tbody', 'tfoot', 'tr', 'th', 'td', 'caption',
    'a', 'strong', 'em', 'b', 'i', 'u', 's', 'mark', 'small', 'sub', 'sup', 'code', 'pre', 'blockquote', 'q',
    'cite', 'abbr', 'br', 'hr', 'figure', 'figcaption', 'dl', 'dt', 'dd', 'div', 'span',
))
# Removed together with everything inside them. The pipeline never puts
# images into the article body (the featured image is uploaded separately).
DROPPED_TAGS = frozenset((
    'script', 'style', 'iframe', 'frame', 'frameset', 'object', 'embed', 'applet', 'form', 'input', 'button',
    'select', 'textarea', 'option', 'meta', 'base', 'link', 'head', 'title', 'noscript', 'template', 'svg',
    'math', 'img', 'image', 'picture', 'source', 'video', 'audio', 'track', 'canvas', 'map', 'area',
    'portal', 'dialog',
))
# Headings outside h2-h4 keep their meaning at the nearest allowed level.
RENAMED_TAGS = {'h1': 'h2', 'h5': 'h4', 'h6': 'h4'}
_ALLOWED_ATTRS = {
    'a': ('href', 'title', 'rel', 'target'),
    'th': ('colspan', 'rowspan', 'scope'),
    'td': ('colspan', 'rowspan'),
    'abbr': ('title',),
}
_ALLOWED_REL = frozenset(('nofollow', 'noopener', 'noreferrer', 'sponsored', 'ugc', 'external'))
_SAFE_CLASS_RE = re.compile(r'^[\w\s-]{1,100}$')
_URL_SCHEME_RE = re.compile(r'^([a-z][a-z0-9+.-]*):', re.IGNORECASE)


def _safe_href(href):
    """True for http(s), mailto, relative and in-page links."""
    compact = re.sub(r'[\x00-\x20\x7f]+', '', html.unescape(str(href or '')))
    if not compact:
        return False
    scheme = _URL_SCHEME_RE.match(compact)
    return scheme is None or scheme.group(1).lower() in ('http', 'https', 'mailto')


def _clean_attrs(tag):
    allowed = _ALLOWED_ATTRS.get(tag.name, ())
    attrs = {}
    for name, value in tag.attrs.items():
        name = name.lower()
        value = ' '.join(value) if isinstance(value, list) else str(value)
        if name == 'class':
            if _SAFE_CLASS_RE.match(value):
                attrs['class'] = value
            continue
        if name not in allowed:
            continue
        if name in ('colspan', 'rowspan') and not value.strip().isdigit():
            continue
        if name == 'target':
            if value.strip().lower() != '_blank':
                continue
            value = '_blank'
        if name == 'rel':
            value = ' '.join(r for r in value.lower().split() if r in _ALLOWED_REL)
            if not value:
                continue
        attrs[name] = value
    if tag.name == 'a' and attrs.get('target') == '_blank':
        attrs['rel'] = ' '.join(sorted(set((attrs.get('rel') or '').split()) | {'noopener'}))
    tag.attrs = attrs


def _is_markup_debris(node):
    return isinstance(node, (Comment, Declaration, Doctype, ProcessingInstruction))


def sanitize_article_html(content):
    """Article HTML reduced to an allow-list of tags and attributes.

    Dangerous elements (script, style, iframe, forms, embeds, images, SVG,
    meta/base/link ...) are removed with their content; other unknown tags are
    unwrapped (their text is kept); attributes are limited per tag (links keep
    href/title/rel/target, table cells their spans, any tag a plain class);
    links with a scheme other than http(s)/mailto lose the link but keep the
    text. Broken markup comes back balanced.
    """
    if not content:
        return content or ''
    soup = BeautifulSoup(content, 'html.parser')
    for node in soup.find_all(string=_is_markup_debris):
        node.extract()
    for tag in soup.find_all(True):
        if tag.decomposed:
            continue
        name = (tag.name or '').lower()
        if name in DROPPED_TAGS:
            tag.decompose()
            continue
        name = RENAMED_TAGS.get(name, name)
        if name not in ALLOWED_TAGS:
            tag.unwrap()
            continue
        tag.name = name
        _clean_attrs(tag)
        if name == 'a' and not _safe_href(tag.get('href')):
            tag.unwrap()
    return str(soup)


def plain_text(value):
    """Text for fields WordPress shows as they are (title, excerpt, meta).

    Entities are decoded first and tags removed after, then any remaining angle
    bracket, so an encoded "&lt;script&gt;" cannot turn into live markup.
    """
    text = html.unescape(str(value or ''))
    text = re.sub(r'<[^>]*>', ' ', text)
    text = text.replace('<', '').replace('>', '')
    return ' '.join(text.split())


_SENTENCE_END_RE = re.compile(r'[.!?](?=\s|$)')


def fit_meta_description(text, max_chars=PUBLISH_META_MAX_CHARS):
    """Meta description of at most max_chars characters.

    Plain text is expected (see plain_text). A longer text is cut at the last
    sentence end inside the limit when that keeps at least
    MIN_SENTENCE_CUT_CHARS; otherwise at the last word boundary, dropping
    trailing punctuation and dangling joining words ("dan", "for"). No ellipsis
    is added. Shorter text is returned unchanged (whitespace collapsed).
    """
    text = ' '.join(str(text or '').split())
    if len(text) <= max_chars:
        return text
    window = text[:max_chars + 1]
    sentence_ends = [m.end() for m in _SENTENCE_END_RE.finditer(window) if m.end() <= max_chars]
    if sentence_ends and sentence_ends[-1] >= min(MIN_SENTENCE_CUT_CHARS, max_chars):
        return window[:sentence_ends[-1]].strip()
    # Word boundary: the character after the cut must be a space (or the end).
    cut = window[:max_chars]
    if not window[max_chars:max_chars + 1].isspace():
        cut = cut.rsplit(' ', 1)[0] if ' ' in cut else cut
    words = cut.split()
    while len(words) > 1 and words[-1].lower().strip(',;:-–—') in _DANGLING_END_WORDS:
        words.pop()
    return ' '.join(words).rstrip(' ,;:-–—(')
