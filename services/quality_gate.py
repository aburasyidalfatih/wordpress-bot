"""Pre-publish quality checks for generated articles.

The prompt asks for a 2000-2500 word article, but nothing used to verify that the
model actually delivered one: the only check was "more than 50 words", so a truncated
or half-length article was published as if it were fine. These checks run after
generation and before anything is sent to WordPress.

Failures are split into two kinds:
  - errors: block publishing (the credit is refunded by the caller)
  - warnings: logged, but the article still goes out
"""

import re
import logging
from urllib.parse import urlparse

from services.article_generator import strip_html

logger = logging.getLogger(__name__)

# Minimum publishable length. Well below the 2000 the prompt requests, so that a
# slightly short but complete article is not thrown away, while an obviously
# truncated one is.
MIN_WORD_COUNT = 900
TARGET_WORD_COUNT = 2000

MIN_HEADINGS = 3
MIN_META_LENGTH = 80
MAX_META_LENGTH = 200

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
    elif len(title) > 200:
        warnings.append(f'Title is unusually long ({len(title)} chars).')

    if not content.strip():
        errors.append('Article has no content.')
        return False, errors, warnings

    if word_count < MIN_WORD_COUNT:
        errors.append(
            f'Article is too short: {word_count} words (minimum {MIN_WORD_COUNT}, '
            f'target {TARGET_WORD_COUNT}).'
        )
    elif word_count < TARGET_WORD_COUNT:
        warnings.append(f'Article is below target length: {word_count}/{TARGET_WORD_COUNT} words.')

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
        warnings.append(f'Meta description length {len(meta)} outside {MIN_META_LENGTH}-{MAX_META_LENGTH}.')

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
    """Comparable form of a link: http/https, "www." and a trailing slash do not matter."""
    url = str(url or '').strip()
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
    href = (href or '').strip()
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
