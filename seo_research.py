"""
SEO Research Module - Advanced Enterprise Keyword & Competitor Research
Uses open source libraries to perform deep topic analysis.
"""
import urllib3_compat  # noqa: F401  (must run before pytrends is imported)

import os
import random
import re
import time
import requests
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from threading import Lock
from urllib.parse import urlsplit

from services.topic_similarity import significant_tokens
from trending_research import trends_locale, trends_session

try:
    from pytrends.request import TrendReq
except ImportError:
    TrendReq = None

# duckduckgo-search was renamed to ddgs. The old package is only a fallback for
# environments that have not reinstalled requirements yet; it does not accept
# ddgs' engine names, so `backend` is passed only to ddgs.
DDGS_PACKAGE = None
try:
    from ddgs import DDGS
    DDGS_PACKAGE = 'ddgs'
except ImportError:
    try:
        from duckduckgo_search import DDGS
        DDGS_PACKAGE = 'duckduckgo_search'
    except ImportError:
        DDGS = None

try:
    from youtube_transcript_api import YouTubeTranscriptApi
except ImportError:
    YouTubeTranscriptApi = None

try:
    from rq import get_current_job
except ImportError:
    get_current_job = None
logger = logging.getLogger(__name__)

# Google Trends seasonality lookup doubles the request rate per category. Enable
# with ENABLE_TREND_SEASONALITY=true only if your Trends quota tolerates it.
ENABLE_TREND_SEASONALITY = os.getenv('ENABLE_TREND_SEASONALITY', 'false').lower() == 'true'

# DuckDuckGo rate-limits per IP. Competitors, social, YouTube and news all go
# through it, so they are spaced out rather than fired together.
DDG_CALL_SPACING_SECONDS = float(os.getenv('DDG_CALL_SPACING_SECONDS', '3'))

# ddgs is a metasearch client; its "auto" backend puts Wikipedia/Grokipedia
# first and mixes engines. Research expects DuckDuckGo's own ranking, so the
# engine is explicit (comma-separated ddgs engine names; "auto" is allowed).
DDGS_TEXT_BACKEND = os.getenv('DDGS_TEXT_BACKEND', 'duckduckgo')
DDGS_NEWS_BACKEND = os.getenv('DDGS_NEWS_BACKEND', 'duckduckgo')

# Optional Jina Reader key: keyed requests get a far higher rate limit than the
# anonymous per-IP quota.
JINA_API_KEY = os.getenv('JINA_API_KEY', '')

# Roughly the first three minutes of a video, capped so one transcript cannot
# dominate the prompt.
TRANSCRIPT_WINDOW_SECONDS = 180
TRANSCRIPT_MAX_CHARS = 1500

# Wikipedia extracts shorter than this are stubs or bare titles, not context.
WIKIPEDIA_MIN_EXTRACT_CHARS = 200

# Only real video URLs; channel (/channel/, /c/, /@handle) and playlist pages
# have no transcript.
YOUTUBE_VIDEO_ID_RE = re.compile(
    r'(?:youtube\.com/(?:watch\?(?:[^#\s]*&)?v=|shorts/|embed/)|youtu\.be/)'
    r'([0-9A-Za-z_-]{11})(?![0-9A-Za-z_-])',
    re.IGNORECASE,
)

# Markdown links/images. Both parts are bounded and the link text may not
# contain '[', which keeps matching linear on hostile input: the unbounded
# `\[([^\]]*)\]\(` took over a minute on a 100 KB line of '['. The target allows
# one level of parentheses (Wikipedia URLs) and spaces (Jina's `(url "title")`).
_MARKDOWN_TARGET = r'\(((?:[^()\n]|\([^()\n]{0,200}\)){0,500})\)'
_MARKDOWN_IMAGE_RE = re.compile(r'!\[([^\[\]\n]{0,300})\]' + _MARKDOWN_TARGET)
_MARKDOWN_LINK_RE = re.compile(r'\[([^\[\]\n]{0,300})\]' + _MARKDOWN_TARGET)

# Fetched pages are capped before any parsing, and so are single lines: every
# regex below is then bounded no matter what a page contains.
MAX_PAGE_CONTENT_CHARS = 300_000
MAX_LINE_CHARS = 5000

# Site chrome that Jina Reader renders as headings. Compared against the heading
# lowercased with punctuation and comment counts removed. EXACT entries must be
# the whole heading (so "Search engine basics" survives); PREFIX entries are
# unambiguous enough to match the start of a heading.
_BOILERPLATE_EXACT = {
    'search', 'cari', 'pencarian', 'navigation', 'navigasi', 'menu', 'main menu',
    'comments', 'comment', 'komentar', 'categories', 'category', 'kategori',
    'tags', 'tag', 'label', 'archives', 'arsip', 'newsletter', 'subscribe',
    'berlangganan', 'footer', 'sidebar', 'about', 'tentang', 'contact', 'kontak',
    'share', 'bagikan', 'share this', 'bagikan ini', 'trending', 'populer',
    'terpopuler', 'terbaru', 'advertisement', 'iklan', 'sponsored', 'login',
    'masuk', 'daftar', 'disclaimer', 'recommended', 'rekomendasi', 'social media',
    'media sosial', 'links', 'tautan', 'quick links', 'useful links',
}
_BOILERPLATE_PREFIXES = (
    'leave a reply', 'leave a comment', 'tinggalkan balasan', 'tinggalkan komentar',
    'tulis komentar', 'related post', 'related article', 'related news',
    'artikel terkait', 'berita terkait', 'postingan terkait', 'posting terkait',
    'tulisan terkait', 'you may also like', 'you might also like', 'anda mungkin juga',
    'mungkin anda suka', 'baca juga', 'read also', 'read more', 'baca selengkapnya',
    'share this', 'share on', 'bagikan artikel', 'bagikan ke', 'bagikan di',
    'popular post', 'popular article', 'recent post', 'recent comment', 'latest post',
    'artikel terbaru', 'artikel populer', 'artikel terpopuler', 'postingan terbaru',
    'postingan populer', 'posting terbaru', 'posting populer', 'komentar terbaru',
    'subscribe to', 'sign up for our', 'join our newsletter', 'berlangganan newsletter',
    'follow us', 'ikuti kami', 'about us', 'about the author', 'tentang kami',
    'tentang penulis', 'contact us', 'hubungi kami', 'post navigation',
    'navigasi pos', 'table of contents', 'daftar isi', 'privacy policy',
    'kebijakan privasi', 'terms of service', 'terms of use', 'terms and conditions',
    'syarat dan ketentuan', 'all rights reserved', 'see also', 'lihat juga',
)
# A prefix may carry a plural/suffix ("related posts") and trailing words.
_BOILERPLATE_PREFIX_RE = re.compile(
    r'^(?:' + '|'.join(re.escape(p) for p in _BOILERPLATE_PREFIXES) + r')\w*(?:\s|$)'
)
_BOILERPLATE_COUNT_RE = re.compile(r'^\d+\s+|\s+\d+$')

# Question words, matched as whole words: 'apa' must not hit 'siapa' or
# 'apartemen', 'how' must not hit 'show'.
_QUESTION_WORDS_RE = {
    'en': re.compile(r'\b(?:how|what|why)\b', re.IGNORECASE),
    'id': re.compile(r'\b(?:bagaimana|gimana|apa|apakah|kenapa|mengapa)\b', re.IGNORECASE),
}


def strip_markdown_links(text):
    """'[text](url)' -> 'text' and '![alt](url)' -> 'alt'."""
    text = _MARKDOWN_IMAGE_RE.sub(r'\1', str(text or ''))
    return _MARKDOWN_LINK_RE.sub(r'\1', text)


def is_boilerplate_heading(heading):
    normalized = ' '.join(re.sub(r'[^\w\s]', ' ', str(heading or '').lower()).split())
    normalized = _BOILERPLATE_COUNT_RE.sub('', normalized).strip()
    if not normalized:
        return True
    return normalized in _BOILERPLATE_EXACT or bool(_BOILERPLATE_PREFIX_RE.match(normalized))


def is_question_title(title, language='id'):
    title = str(title or '')
    if '?' in title:
        return True
    pattern = _QUESTION_WORDS_RE['en' if language == 'en' else 'id']
    return bool(pattern.search(title))


def extract_youtube_video_id(url):
    match = YOUTUBE_VIDEO_ID_RE.search(str(url or ''))
    return match.group(1) if match else None


def _snippet_value(snippet, name):
    # youtube-transcript-api 1.x returns snippet objects; 0.x returned dicts.
    if isinstance(snippet, dict):
        return snippet.get(name)
    return getattr(snippet, name, None)


def transcript_excerpt(snippets, window_seconds=TRANSCRIPT_WINDOW_SECONDS, max_chars=TRANSCRIPT_MAX_CHARS):
    """Text spoken in the first `window_seconds`, whitespace-collapsed and capped."""
    parts = []
    for snippet in snippets or []:
        start = _snippet_value(snippet, 'start')
        try:
            if start is not None and float(start) > window_seconds:
                break
        except (TypeError, ValueError):
            pass
        text = ' '.join(str(_snippet_value(snippet, 'text') or '').split())
        if text:
            parts.append(text)
    excerpt = ' '.join(parts)
    if len(excerpt) > max_chars:
        excerpt = excerpt[:max_chars].rsplit(' ', 1)[0] + '...'
    return excerpt


# ---------------------------------------------------------------------------
# Key passages: what a fetched page actually says about the topic. Headings
# alone told the writer which subtopics a competitor covers but none of its
# facts, so articles came out generic. These are the few paragraphs, lists or
# table rows of a page that are most about the topic, with site chrome removed.
# ---------------------------------------------------------------------------

KEY_PASSAGE_LIMIT = 5
KEY_PASSAGE_MAX_CHARS = 600
KEY_PASSAGES_PAGE_MAX_CHARS = 2500
# Shorter blocks are captions, buttons, bylines and menu entries, not content.
KEY_PASSAGE_MIN_CHARS = 80
KEY_PASSAGE_MIN_WORDS = 10
# A partial passage shorter than this is not worth keeping under the page cap.
_MIN_PARTIAL_PASSAGE_CHARS = 200
# Blocks longer than this are article text even when they mention a word such
# as "newsletter" or "cookie"; the boilerplate patterns only apply below it.
_BOILERPLATE_BLOCK_MAX_CHARS = 400

# Jina Reader puts "Title:", "URL Source:" and "Published Time:" lines before
# this marker; the page itself follows it.
_JINA_CONTENT_MARKER = 'Markdown Content:'
_JINA_HEADER_MAX_CHARS = 3000
_JINA_TITLE_RE = re.compile(r'^Title:[ \t]*(.{1,500})$', re.MULTILINE)
_JINA_SOURCE_RE = re.compile(r'^URL Source:[ \t]*(\S{1,2000})', re.MULTILINE)
# Closing hashes ("## Title ##") are stripped separately: a lazy body followed
# by `\s*#*\s*$` backtracks quadratically on a long run of spaces.
_ATX_HEADING_RE = re.compile(r'^\s{0,3}#{1,6}\s+(.*)$')
_ATX_CLOSING_RE = re.compile(r'\s#+$')
_SETEXT_UNDERLINE_RE = re.compile(r'^\s{0,3}(?:={2,}|-{2,})\s*$')
_FENCE_RE = re.compile(r'^\s*(?:```|~~~)')
_HORIZONTAL_RULE_RE = re.compile(r'^\s*([-*_])(?:\s*\1){2,}\s*$')
_TABLE_SEPARATOR_RE = re.compile(r'^\s*\|?\s*:?-{2,}:?\s*(?:\|\s*:?-{2,}:?\s*)*\|?\s*$')
_BULLET_ITEM_RE = re.compile(r'^\s*[-*+•]\s+')
_NUMBERED_ITEM_RE = re.compile(r'^\s*\d{1,2}[.)]\s+')
_BLOCKQUOTE_RE = re.compile(r'^\s*(?:>\s?)+')
_BARE_URL_RE = re.compile(r'(?:https?://|www\.)\S+', re.IGNORECASE)
_HTML_TAG_RE = re.compile(r'<[^<>\n]{0,200}>')
_EMPHASIS_RE = re.compile(r'\*\*|__|`|\*')
_SENTENCE_END_RE = re.compile(r'[.!?]["\')\]]?(?=\s|$)')

# Whole lines that are page furniture: "Baca juga: ...", bylines, photo credits.
_BOILERPLATE_LINE_RE = re.compile(
    r'^(?:baca juga|baca selengkapnya|baca berita|simak juga|cek juga|lihat juga|read also|'
    r'read more|see also|also read|advertisement|iklan|scroll to continue|gulir untuk|'
    r'share (?:this|on)\b|share\s*:|bagikan(?:\s+(?:ini|ke|di|artikel)\b|\s*:)|'
    r'(?:tags?|label|kategori|categor(?:y|ies)|editor|penulis|reporter|pewarta|'
    r'foto|photo|image|gambar)\s*:|written by|posted by|published by|ditulis oleh|'
    r'diposting oleh|diterbitkan oleh|sumber gambar)',
    re.IGNORECASE,
)
# Short blocks containing any of these are cookie notices, comment forms,
# newsletter boxes, author bios, related-post widgets or footers.
_BOILERPLATE_BLOCK_RE = re.compile(
    r'cookies?\b|\bkuki\b|privacy policy|kebijakan privasi|terms of (?:service|use)|'
    r'syarat dan ketentuan|all rights reserved|hak cipta|copyright|©|subscribe|'
    r'berlangganan|newsletter|leave a (?:reply|comment)|tinggalkan (?:balasan|komentar)|'
    r'email address will not be published|email anda tidak akan dipublikasikan|'
    r'required fields are marked|\b\d+\s+(?:comments?|komentar)\b|no comments|'
    r'belum ada komentar|tulis komentar|kirim komentar|add a comment|post a comment|'
    r'about the author|tentang penulis|related (?:posts?|articles?|news)|artikel terkait|'
    r'berita terkait|you (?:may|might) also like|follow us|ikuti kami|'
    r'download (?:the |our )?app|unduh aplikasi|google news|whatsapp channel|saluran whatsapp',
    re.IGNORECASE,
)
# Concrete content: a definition, or a figure with a unit or currency.
_DEFINITION_RE = re.compile(
    r'\b(?:adalah|merupakan|yaitu|yakni|ialah|didefinisikan|diartikan|is (?:a|an|the)|'
    r'refers to|means|defined as)\b',
    re.IGNORECASE,
)
_FIGURE_RE = re.compile(r'\d\s*%|\bRp\.?\s*\d|\$\s*\d|\b(?:USD|IDR|persen|percent)\b', re.IGNORECASE)


def _strip_inline_markdown(line):
    """Plain text of one markdown line: no images, link targets, URLs or emphasis."""
    text = _MARKDOWN_IMAGE_RE.sub(' ', str(line or ''))
    text = _MARKDOWN_LINK_RE.sub(r'\1', text)
    text = _BARE_URL_RE.sub(' ', text)
    text = _HTML_TAG_RE.sub(' ', text)
    text = _EMPHASIS_RE.sub('', text)
    return ' '.join(text.split())


def _is_link_line(line):
    """True for navigation: a line that is only links/images, or mostly link text."""
    without_images = _MARKDOWN_IMAGE_RE.sub(' ', line)
    links = [match.group(1) for match in _MARKDOWN_LINK_RE.finditer(without_images)]
    has_media = bool(links) or without_images != line or bool(_BARE_URL_RE.search(line))
    if not has_media:
        return False
    rest = _BARE_URL_RE.sub(' ', _MARKDOWN_LINK_RE.sub(' ', without_images))
    rest_chars = len(re.sub(r'[\W_]+', '', rest))
    if rest_chars < 3:
        return True
    link_chars = sum(len(re.sub(r'[\W_]+', '', text)) for text in links)
    return len(links) >= 2 and link_chars > 2 * rest_chars


def _page_blocks(content):
    """(heading, lines) for each paragraph, list or table of a markdown page.

    Headings (ATX or setext) are not blocks themselves; each block carries the
    heading it sits under. Code blocks and horizontal rules are dropped.
    """
    text = str(content or '')[:MAX_PAGE_CONTENT_CHARS]
    marker = text.find(_JINA_CONTENT_MARKER)
    if marker != -1:
        text = text[marker + len(_JINA_CONTENT_MARKER):]
    heading, block, in_fence = '', [], False
    for raw in text.replace('\r\n', '\n').replace('\r', '\n').split('\n'):
        # Over-long lines (minified markup, PDF text without breaks) are cut,
        # which bounds the work every per-line regex can do.
        raw = raw[:MAX_LINE_CHARS]
        if _FENCE_RE.match(raw):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        line = raw.strip()
        if not line:
            if block:
                yield heading, block
                block = []
            continue
        atx = _ATX_HEADING_RE.match(line)
        if atx:
            if block:
                yield heading, block
                block = []
            heading = _strip_inline_markdown(_ATX_CLOSING_RE.sub('', atx.group(1).rstrip()))
            continue
        if _SETEXT_UNDERLINE_RE.match(line) and len(block) >= 1 and not _TABLE_SEPARATOR_RE.match(block[-1]):
            # "Heading\n-------": the previous line was a heading.
            title_line = block.pop()
            if block:
                yield heading, block
                block = []
            heading = _strip_inline_markdown(title_line)
            continue
        if _HORIZONTAL_RULE_RE.match(line):
            if block:
                yield heading, block
                block = []
            continue
        block.append(line)
    if block:
        yield heading, block


def _block_text(lines):
    """Clean a block's lines into one passage string ('' when nothing is left)."""
    parts = []
    for line in lines:
        if _TABLE_SEPARATOR_RE.match(line) or _is_link_line(line):
            continue
        line = _BLOCKQUOTE_RE.sub('', line)
        is_table_row = line.startswith('|')
        is_bullet = bool(_BULLET_ITEM_RE.match(line))
        if is_bullet:
            line = _BULLET_ITEM_RE.sub('', line)
        if is_table_row:
            line = ' | '.join(cell.strip() for cell in line.strip().strip('|').split('|') if cell.strip())
        text = _strip_inline_markdown(line)
        if not text or _BOILERPLATE_LINE_RE.match(text):
            continue
        if (is_bullet or is_table_row or _NUMBERED_ITEM_RE.match(text)) and text[-1] not in '.!?:;':
            text += ';'
        parts.append(text)
    text = ' '.join(parts).strip()
    if text.endswith(';'):
        text = text[:-1] + '.'
    return text


def _is_boilerplate_block(text, topic_tokens):
    """Short blocks with a boilerplate marker, unless the marker is the topic itself
    (an article about copyright may say "hak cipta")."""
    if len(text) > _BOILERPLATE_BLOCK_MAX_CHARS:
        return False
    for match in _BOILERPLATE_BLOCK_RE.finditer(text):
        found = match.group(0).lower()
        if not any(token in found for token in topic_tokens):
            return True
    return False


def cut_at_sentence(text, max_chars):
    """text capped at max_chars, ending on a sentence boundary when one is close.

    Falls back to a word boundary plus '...' when the last full sentence would
    keep less than 40% of the allowance.
    """
    text = ' '.join(str(text or '').split())
    if len(text) <= max_chars:
        return text
    window = text[:max_chars]
    ends = [m.end() for m in _SENTENCE_END_RE.finditer(window)]
    if ends and ends[-1] >= max_chars * .4:
        return window[:ends[-1]].strip()
    cut = text[:max(0, max_chars - 3)].rsplit(' ', 1)[0].rstrip(' ,;:')
    return cut + '...' if cut else ''


def _topic_matches(topic_tokens, text_tokens, raw_words):
    """Topic words found in a text. Affixed Indonesian forms count too:
    'pajak' matches 'perpajakan', 'wajib' matches 'kewajiban'."""
    matched = set()
    for token in topic_tokens:
        if token in text_tokens or (len(token) >= 4 and any(token in word for word in raw_words)):
            matched.add(token)
    return matched


def _score_passage(text, heading, topic_tokens, language, is_list):
    """Relevance to the topic plus a bonus for concrete content. None = irrelevant."""
    concrete = 0.0
    if re.search(r'\d', text):
        concrete += 1.5
    if _FIGURE_RE.search(text):
        concrete += 1.0
    if is_list:
        concrete += 1.5
    if _DEFINITION_RE.search(text):
        concrete += 1.0
    if not topic_tokens:
        return concrete
    words = re.findall(r'\w+', text.lower())
    matched = _topic_matches(topic_tokens, set(significant_tokens(text, language)), words)
    heading_words = re.findall(r'\w+', heading.lower())
    heading_matched = _topic_matches(topic_tokens, set(significant_tokens(heading, language)), heading_words)
    # Under a relevant heading a block need not repeat the topic words, but it
    # must then carry something concrete (a figure, a list, a definition).
    if not matched and not (heading_matched and concrete >= 1.5):
        return None
    occurrences = sum(1 for word in words
                      if any(word == token or (len(token) >= 4 and token in word) for token in matched))
    return (10.0 * len(matched) / len(topic_tokens)
            + 0.4 * min(occurrences, 6)
            + 2.0 * len(heading_matched) / len(topic_tokens)
            + concrete)


def extract_key_passages(content, topic, language='id', limit=KEY_PASSAGE_LIMIT,
                         max_chars=KEY_PASSAGE_MAX_CHARS, page_max_chars=KEY_PASSAGES_PAGE_MAX_CHARS):
    """The page passages most relevant to topic, most relevant first.

    content is a Jina Reader markdown page. Paragraphs, lists and tables are
    cleaned of links, images and markup; navigation, cookie notices, comment
    forms, author bios, related-post widgets and sections under such headings are
    dropped, as are very short blocks. The rest is ranked by how many of the
    topic's content words it contains, with a bonus for concrete content
    (numbers, figures, steps, definitions). Each passage is cut to max_chars on a
    sentence boundary; all passages together stay within page_max_chars.
    """
    topic_tokens = list(dict.fromkeys(significant_tokens(topic, language)))
    candidates, seen = [], set()
    for position, (heading, lines) in enumerate(_page_blocks(content)):
        if heading and is_boilerplate_heading(heading):
            continue
        is_list = sum(1 for line in lines if _BULLET_ITEM_RE.match(line) or _NUMBERED_ITEM_RE.match(line)) >= 2
        text = _block_text(lines)
        if len(text) < KEY_PASSAGE_MIN_CHARS or len(text.split()) < KEY_PASSAGE_MIN_WORDS:
            continue
        if _is_boilerplate_block(text, topic_tokens):
            continue
        text = cut_at_sentence(text, max_chars)
        key = text.lower()[:100]
        if key in seen:
            continue
        seen.add(key)
        score = _score_passage(text, heading, topic_tokens, language, is_list)
        if score is not None:
            candidates.append((-score, position, text))

    passages, total = [], 0
    for _score, _position, text in sorted(candidates)[:limit]:
        remaining = page_max_chars - total
        if len(text) > remaining:
            if remaining < _MIN_PARTIAL_PASSAGE_CHARS:
                break
            text = cut_at_sentence(text, remaining)
        passages.append(text)
        total += len(text)
    return passages


def _jina_header(content):
    """The header Jina Reader puts above the page. Only the part before the
    'Markdown Content:' marker: the page body cannot forge a header line."""
    head = str(content or '')[:_JINA_HEADER_MAX_CHARS]
    marker = head.find(_JINA_CONTENT_MARKER)
    return head[:marker] if marker != -1 else ''


def page_title(content):
    """The 'Title:' line Jina Reader puts above the page, or ''."""
    match = _JINA_TITLE_RE.search(_jina_header(content))
    return ' '.join(strip_markdown_links(match.group(1)).split()) if match else ''


def page_source_url(content):
    """The 'URL Source:' Jina Reader reports (the page it actually read, after
    redirects) when it is an http(s) URL, else ''."""
    match = _JINA_SOURCE_RE.search(_jina_header(content))
    url = match.group(1) if match else ''
    return url if url.lower().startswith(('http://', 'https://')) else ''


def url_host(url):
    """Lower-case host of url without 'www.' and a trailing dot, or ''."""
    try:
        host = urlsplit(str(url or '').strip()).hostname or ''
    except ValueError:
        return ''
    return host.lower().rstrip('.').removeprefix('www.')


def title_matches_topic(title, topic, language='id'):
    """True when title shares a content word with topic (or topic has none)."""
    topic_tokens = list(dict.fromkeys(significant_tokens(topic, language)))
    if not topic_tokens:
        return True
    title = str(title or '')
    words = re.findall(r'\w+', title.lower())
    return bool(_topic_matches(topic_tokens, set(significant_tokens(title, language)), words))


# ---------------------------------------------------------------------------
# Spam / compromised pages. Hacked sites, including regional .go.id
# subdomains, host gambling and pharma SEO spam; such a page must never become
# a source, let alone an "official" one. Markers are ignored when the topic is
# itself about them (an article on the dangers of online gambling).
# "bandar" and "scatter" alone are ordinary words ("bandar udara", "Bandar
# Lampung", "scatter plot"), so only their gambling combinations count.
# ---------------------------------------------------------------------------

_SPAM_MARKER_RE = re.compile(
    r'\b(?:slot[ -]?gacor|slot[ -]?online|situs[ -]?slot|slot ?88|rtp[ -]?live|rtp[ -]?slot|maxwin|togel|'
    r'toto[ -]?macau|judi[ -]?online|judi[ -]?bola|casino[ -]?online|kasino[ -]?online|'
    r'bandar[ -]?(?:togel|judi|slot|bola|casino)|sbobet|poker[ -]?online|pola[ -]?scatter|'
    r'scatter[ -]?hitam|viagra|cialis|bokep)\b',
    re.IGNORECASE,
)
# A page body may mention gambling in a news sidebar; more than this many
# markers (or any in the title or the extracted passages) means spam.
SPAM_BODY_MARKER_LIMIT = 2


def spam_marker_count(text, topic=''):
    """Spam markers in text, not counting those the topic itself is about."""
    topic_words = set(re.findall(r'[a-z0-9]+', str(topic or '').lower()))
    count = 0
    for match in _SPAM_MARKER_RE.finditer(str(text or '')):
        words = re.findall(r'[a-z0-9]+', match.group(0).lower())
        if not any(len(word) >= 4 and word in topic_words for word in words):
            count += 1
    return count


def is_spam_page(content, title, topic, passages=(), body_limit=SPAM_BODY_MARKER_LIMIT):
    """True when a fetched page looks like gambling/adult/pharma spam.

    Any marker in the title or in the passages we would quote, or more than
    body_limit markers in the page, flags it (body_limit=0: any marker at all).
    """
    if spam_marker_count(title, topic) or spam_marker_count(page_title(content), topic):
        return True
    if any(spam_marker_count(passage, topic) for passage in passages or ()):
        return True
    return spam_marker_count(str(content or '')[:MAX_PAGE_CONTENT_CHARS], topic) > body_limit


# ---------------------------------------------------------------------------
# Host exclusion: the publisher's own site must not show up as its own
# competitor or source.
# ---------------------------------------------------------------------------

def normalize_hosts(hosts):
    """Hostnames (or URLs) as lower-case hosts without 'www.'; None/'' dropped."""
    if isinstance(hosts, str):
        hosts = [hosts]
    normalized = set()
    for value in hosts or ():
        value = str(value or '').strip().lower()
        if not value:
            continue
        if '://' in value:
            host = url_host(value)
        else:
            host = value.split('/')[0].split(':')[0].rstrip('.').removeprefix('www.')
        if host:
            normalized.add(host)
    return frozenset(normalized)


def is_excluded_url(url, excluded_hosts):
    """True when url's host is one of excluded_hosts (normalized) or a subdomain of one."""
    if not excluded_hosts:
        return False
    host = url_host(url)
    return bool(host) and any(host == h or host.endswith('.' + h) for h in excluded_hosts)


# ---------------------------------------------------------------------------
# Official / primary sources: government pages whose figures (rates, fees,
# dates, rules) outrank whatever a blog says. The host is validated, never the
# title: "go.id.evil.com" and "example.com/go.id" are not official.
# ---------------------------------------------------------------------------

OFFICIAL_DOMAIN_SUFFIXES = {
    'id': ('go.id',),
    'en': ('gov',),
}
OFFICIAL_SOURCE_LIMIT = 3
# Claude research counts as the competitor source only with at least this many
# good competitors (CLAUDE_GOOD_PASSAGES or more verified passages each); fewer
# are topped up by the classic scrape. Thin pages (fewer passages: a meta
# description, a script-rendered page) never count towards it.
CLAUDE_MIN_COMPETITORS = 2
CLAUDE_GOOD_PASSAGES = 2
# Verified reader questions Claude needs to replace Google Suggest questions.
CLAUDE_MIN_QUESTIONS = 3
# Source status key of each part Claude can supply (the rest use the part name).
CLAUDE_PART_SOURCES = {'questions': 'related_questions'}
# A category name with no Google Trends data is retried once with its first
# significant words ("Emergency Fund and Financial Safety" -> "emergency fund").
TREND_HEAD_TERM_WORDS = 2

# Google Suggest (autocomplete). The firefox client returns plain JSON
# ["query", [suggestions], ...]; the chrome client the same array with extra
# metadata, so it is the second try. ie/oe pin UTF-8 in and out (the response
# charset otherwise follows hl). A complete browser User-Agent and
# Accept-Language: the old truncated one looked like a bot.
GOOGLE_SUGGEST_URL = 'https://suggestqueries.google.com/complete/search'
GOOGLE_SUGGEST_CLIENTS = ('firefox', 'chrome')
GOOGLE_SUGGEST_RETRY_STATUSES = frozenset({429, 500, 502, 503})
GOOGLE_SUGGEST_BACKOFF_SECONDS = 2.0
SUGGEST_HEADERS = {
    'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
                   'Chrome/130.0.0.0 Safari/537.36'),
    'Accept': 'application/json, text/javascript, */*; q=0.01',
}
# Keyword ideas taken from Claude's retrieved search-result titles when Google
# Suggest is blocked: segments of 2 to 8 words that name the topic.
CLAUDE_KEYWORD_LIMIT = 10
CLAUDE_KEYWORD_MIN_WORDS = 2
CLAUDE_KEYWORD_MAX_WORDS = 8
# A title's site-name tail ("Headline - Kompas.com", "Thread | KASKUS") is
# dropped first; the head is then split into phrases on ':', '?', '!', brackets.
_SITE_TAIL_RE = re.compile(r'\s+[-|\u2013\u2014]\s+')
_TITLE_SPLIT_RE = re.compile(r'[:?!()\[\]|]')
_KEYWORD_NUMBERING_RE = re.compile(r'^\s*\d{1,3}\s*[.)]\s*')


def claude_keyword_ideas(claude, topic, language='id', limit=CLAUDE_KEYWORD_LIMIT):
    """Keyword ideas from a Claude research result, never invented.

    Candidates are the phrases (split on ':', '?', '!', brackets) of the
    verified reader questions and of the search-result titles the call
    retrieved, without a title's site-name tail (" - Kompas.com"). A candidate is kept only when it is a verbatim substring of a
    retrieved search-result title, has CLAUDE_KEYWORD_MIN_WORDS to
    CLAUDE_KEYWORD_MAX_WORDS words, names the topic (title_matches_topic) and
    is not just the topic itself.
    """
    if not isinstance(claude, dict):
        return []
    titles = [str(title) for title in claude.get('search_titles') or [] if isinstance(title, str) and title.strip()]
    if not titles:
        return []
    haystack = [' '.join(title.lower().split()) for title in titles]
    topic_key = ' '.join(str(topic or '').lower().split())
    sources = [q for q in claude.get('questions') or [] if isinstance(q, str)] + titles
    ideas, seen = [], set()
    for source in sources:
        for segment in _TITLE_SPLIT_RE.split(_SITE_TAIL_RE.split(source)[0]):
            phrase = ' '.join(_KEYWORD_NUMBERING_RE.sub('', segment).split()).strip(' .,;"\'')
            key = phrase.lower()
            words = len(phrase.split())
            if not (CLAUDE_KEYWORD_MIN_WORDS <= words <= CLAUDE_KEYWORD_MAX_WORDS) or key in seen or key == topic_key:
                continue
            if not any(key in title for title in haystack) or not title_matches_topic(phrase, topic, language):
                continue
            if spam_marker_count(phrase, topic):
                continue
            seen.add(key)
            ideas.append(phrase)
            if len(ideas) >= limit:
                return ideas
    return ideas


def trend_head_term(name, language='id', words=TREND_HEAD_TERM_WORDS):
    """The first `words` significant words of name, lower-cased; '' when that is not shorter."""
    raw = re.findall(r"[^\W_]+", str(name or ''))
    picked = [word.lower() for word in raw if significant_tokens(word, language)][:words]
    term = ' '.join(picked)
    return term if term and term != ' '.join(word.lower() for word in raw) else ''


# More results than sources wanted: non-official hosts are dropped.
OFFICIAL_SEARCH_RESULTS = 8
OFFICIAL_FETCH_TIMEOUT = 15
_HOST_RE = re.compile(r'^[a-z0-9-]+(?:\.[a-z0-9-]+)+$')


def official_domain_suffixes(language='id'):
    return OFFICIAL_DOMAIN_SUFFIXES['en' if language == 'en' else 'id']


def is_official_url(url, language='id'):
    """True when url is http(s) on a host under the language's official suffix."""
    try:
        parts = urlsplit(str(url or '').strip())
        host = (parts.hostname or '').lower().rstrip('.')
    except ValueError:
        return False
    if parts.scheme.lower() not in ('http', 'https') or parts.username or parts.password:
        return False
    if not _HOST_RE.match(host):
        return False
    return any(host.endswith('.' + suffix) for suffix in official_domain_suffixes(language))


class SEOResearch:
    """Advanced Research using DDGS, Pytrends, and YouTube Transcripts.

    With a Claude engine (services.claude_research.ClaudeWebResearch, set when
    the AI config has an Anthropic key) competitors, official sources, news and
    the Wikipedia background come from Claude's web_search/web_fetch tools; the
    DuckDuckGo + Jina Reader providers for those parts only run as a fallback,
    for each part Claude did not return. Without one, research is unchanged.
    """

    def __init__(self, exclude_hosts=None, claude=None):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        self.ddgs_available = DDGS is not None
        self.source_status = {}
        self._status_lock = Lock()
        # Default for every exclude_hosts parameter below (see normalize_hosts).
        self.exclude_hosts = exclude_hosts
        # Optional ClaudeWebResearch; None keeps every provider classic.
        self.claude = claude

    def _excluded(self, exclude_hosts=None):
        """Normalized hosts to exclude: the argument, else the instance default."""
        return normalize_hosts(exclude_hosts if exclude_hosts is not None else self.exclude_hosts)

    def _new_ddgs(self):
        """Create a fresh DDGS client for a single call.

        The client is not thread-safe and latches into a failed state: once one
        call errors, every later call on the same instance raises "Exception
        occurred in previous call". A single shared instance was fine while the
        providers ran sequentially, but they now run concurrently, so one failure
        took out competitors, social, YouTube and news together — 45 of the 100
        quality points, which is enough to drop every category.
        """
        if not DDGS:
            return None
        try:
            return DDGS()
        except Exception as e:
            logger.error(f"Failed to initialize DDGS: {e}")
            return None

    @staticmethod
    def _ddg_kwargs(language, max_results, kind='text'):
        """Search kwargs shared by every DDGS call: site region and result count."""
        kwargs = {
            'region': 'us-en' if language == 'en' else 'id-id',
            'max_results': max_results,
        }
        if DDGS_PACKAGE == 'ddgs':
            kwargs['backend'] = DDGS_NEWS_BACKEND if kind == 'news' else DDGS_TEXT_BACKEND
        return kwargs

    def _run_providers(self, independent, duckduckgo, label=''):
        """Run providers grouped by the upstream they hit.

        `independent` targets distinct hosts (Google autocomplete, Wikipedia,
        Trends) and can safely run at once. `duckduckgo` all share one host that
        rate-limits per IP, so firing them concurrently looks like a burst and gets
        the whole server blocked; they run one at a time with a gap between them.
        The two groups still overlap with each other.
        """
        collected = {}

        def run_duckduckgo_group():
            for index, (name, fn) in enumerate(duckduckgo.items()):
                if index:
                    # Jitter so the gap is not a fixed, bot-like cadence.
                    time.sleep(DDG_CALL_SPACING_SECONDS + random.uniform(0, 1))
                try:
                    collected[name] = fn()
                except Exception as exc:
                    logger.error(f"Research provider '{name}' failed{label}: {exc}")
                    collected[name] = None

        with ThreadPoolExecutor(max_workers=len(independent) + 1) as pool:
            futures = {pool.submit(fn): name for name, fn in independent.items()}
            ddg_future = pool.submit(run_duckduckgo_group) if duckduckgo else None

            for future in as_completed(list(futures)):
                name = futures[future]
                try:
                    collected[name] = future.result()
                except Exception as exc:
                    logger.error(f"Research provider '{name}' failed{label}: {exc}")
                    collected[name] = None

            if ddg_future:
                try:
                    ddg_future.result()
                except Exception as exc:
                    logger.error(f"DuckDuckGo provider group failed{label}: {exc}")

        return collected

    def _claude_research(self, topic, language, excluded, **options):
        """Claude's validated web research parts, or None (failed / nothing usable).

        Records a 'claude_web' source entry either way and never raises. It runs
        on a worker thread (see _run_with_claude), where RQ's job timeout never
        fires: RQ signals the job's main thread, which is waiting in
        claude_future.result() or in a classic provider and propagates it there.
        """
        try:
            result = self.claude.research(topic, language, exclude_hosts=excluded, **options)
        except Exception as e:  # the engine should not raise; never let it fail research
            logger.error(f"Claude web research raised for '{topic}': {type(e).__name__}: {e}")
            result = None

        model = getattr(self.claude, 'model', None)
        if not isinstance(result, dict):
            reason = getattr(self.claude, 'last_error', None) or 'Riset web Claude gagal; memakai sumber cadangan.'
            self._mark_source('claude_web', 'unavailable', count=0, model=model, reason=reason)
            return None
        stats = result.get('stats') or {}
        good, thin = self._split_claude_competitors(result)
        counts = {
            'competitors': len(good) + len(thin),
            'thin_competitors': len(thin),
            'official_sources': len(result.get('official_sources') or []),
            'news': len(result.get('news') or []),
            'social': len(result.get('social') or []),
            'questions': len(result.get('questions') or []),
            'youtube': len(result.get('youtube') or []),
        }
        total = sum(n for part, n in counts.items() if part != 'thin_competitors')
        details = {'count': total, 'model': stats.get('model', model), 'searches': stats.get('searches'),
                   'fetches': stats.get('fetches'), 'estimated_cost_usd': stats.get('estimated_cost_usd'),
                   **{f'{part}_count': n for part, n in counts.items()}}
        if not total:
            details['reason'] = 'Tidak ada sumber dari Claude yang lolos validasi; memakai sumber cadangan.'
        self._mark_source('claude_web', 'real' if total else 'unavailable', **details)
        return result

    @staticmethod
    def _split_claude_competitors(claude):
        """(good, thin) Claude competitors: good ones have CLAUDE_GOOD_PASSAGES or
        more verified passages, thin ones fewer (but at least one)."""
        good, thin = [], []
        for item in (claude or {}).get('competitors') or []:
            if not isinstance(item, dict) or not item.get('key_passages'):
                continue
            (good if len(item['key_passages']) >= CLAUDE_GOOD_PASSAGES else thin).append(item)
        return good, thin

    def _claude_part(self, claude, name, language='id'):
        """The classic-provider value for provider `name` from Claude's result, or None.

        name is a provider key of the research methods ('competitors',
        'official_sources', 'news', 'social', 'questions', 'youtube'); its
        source status is marked the same way the classic provider would. None
        means the classic provider runs instead:
          - competitors: fewer than CLAUDE_MIN_COMPETITORS good pages (thin pages
            never count; _run_with_claude tops them up);
          - questions: fewer than CLAUDE_MIN_QUESTIONS verified questions;
          - youtube: no video; the videos' transcripts are fetched here.
        """
        if not claude:
            return None
        if name == 'competitors':
            items = self._split_claude_competitors(claude)[0]
            if len(items) < CLAUDE_MIN_COMPETITORS:
                return None
        elif name == 'questions':
            items = [q for q in claude.get('questions') or [] if isinstance(q, str) and q]
            if len(items) < CLAUDE_MIN_QUESTIONS:
                return None
        elif name == 'youtube':
            videos = [v for v in claude.get('youtube') or [] if isinstance(v, dict) and v.get('url')]
            if not videos:
                return None
            return self.youtube_insights_for([(v['url'], v.get('title')) for v in videos], language=language,
                                             via='claude_web')
        else:
            items = list(claude.get(name) or [])
            if not items:
                return None
        self._mark_source(CLAUDE_PART_SOURCES.get(name, name), 'real', count=len(items), via='claude_web')
        return items

    def _top_up_competitors(self, good, classic_items, thin, limit):
        """Good Claude competitors, then classic ones, then thin Claude ones; by URL, up to limit."""
        merged = self._deduplicate(list(good) + list(classic_items or []) + list(thin),
                                   key=lambda item: item.get('url') if isinstance(item, dict) else item)[:limit]
        # Only thin pages (one verified passage each) are partial evidence.
        status = 'real' if (good or classic_items) else 'partial'
        self._mark_source('competitors', status, count=len(merged), via='claude_web+duckduckgo',
                          claude_count=len(good), thin_count=len(thin))
        return merged

    def _run_with_claude(self, topic, language, excluded, independent, duckduckgo, replaceable, claude_options,
                         label='', competitor_limit=4):
        """Run the research providers, letting Claude replace the web-reading ones.

        replaceable names the providers (keys of independent/duckduckgo) that
        Claude's result can supply. Without a Claude engine this is exactly
        _run_providers. With one, Claude runs alongside the classic-only
        providers (so its latency overlaps theirs); then the classic provider
        runs for each replaceable part Claude did not return. When Claude has
        fewer than CLAUDE_MIN_COMPETITORS good competitors, the classic scrape
        tops them up (up to competitor_limit), with thin Claude pages last.
        """
        if not self.claude:
            return self._run_providers(independent, duckduckgo, label=label)

        def only(group, names):
            return {name: fn for name, fn in group.items() if name in names}

        classic_only = (set(independent) | set(duckduckgo)) - set(replaceable)
        pool = ThreadPoolExecutor(max_workers=1)
        try:
            claude_future = pool.submit(self._claude_research, topic, language, excluded, **claude_options)
            collected = self._run_providers(only(independent, classic_only), only(duckduckgo, classic_only),
                                            label=label)
            # RQ's job timeout is raised here, in the main thread, while waiting.
            claude = claude_future.result()
        finally:
            # Never block on the Claude thread, e.g. when the job timeout fired above.
            pool.shutdown(wait=False)

        missing = set()
        for name in replaceable:
            value = self._claude_part(claude, name, language)
            if value is None:
                missing.add(name)
            else:
                collected[name] = value
        if missing:
            fallback_ddg = only(duckduckgo, missing)
            if fallback_ddg and only(duckduckgo, classic_only):
                # Keep the DuckDuckGo spacing across the two groups.
                time.sleep(DDG_CALL_SPACING_SECONDS + random.uniform(0, 1))
            collected.update(self._run_providers(only(independent, missing), fallback_ddg,
                                                 label=f"{label} (Claude fallback)"))
        good, thin = self._split_claude_competitors(claude)
        if 'competitors' in missing and (good or thin):
            collected['competitors'] = self._top_up_competitors(good, collected.get('competitors'), thin,
                                                                competitor_limit)
        self._claude_keyword_fallback(claude, topic, language, collected)
        return collected

    def _claude_keyword_fallback(self, claude, topic, language, collected):
        """Keyword ideas from Claude's retrieved titles when Google Suggest failed.

        Only when 'suggestions' was collected without real data (blocked:
        template fallback). The ideas are verbatim parts of search-result titles
        this call retrieved (claude_keyword_ideas), so they count as observed.
        """
        status = (self.source_status.get('google_autocomplete') or {}).get('status')
        if 'suggestions' not in collected or status == 'real':
            return
        ideas = claude_keyword_ideas(claude, topic, language)
        if not ideas:
            return
        previous = self.source_status.get('google_autocomplete') or {}
        details = {'via': 'claude_web', 'derived_from': 'search_titles'}
        if previous.get('reason'):
            details['google_error'] = previous['reason']
        collected['suggestions'] = ideas
        self._mark_source('google_autocomplete', 'real', count=len(ideas), **details)

    def _mark_source(self, provider, status, **details):
        # Called concurrently by the parallel providers.
        with self._status_lock:
            self.source_status[provider] = {
                'status': status,
                'checked_at': datetime.now(timezone.utc).isoformat(),
                **details,
            }

    @staticmethod
    def _deduplicate(values, key=None):
        seen = set()
        output = []
        for value in values or []:
            raw = key(value) if key else value
            normalized = ' '.join(str(raw or '').lower().split())
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            output.append(value)
        return output

    def _google_suggest(self, query, language='id', timeout=10):
        """(suggestions, error) from Google Suggest; suggestions is None when
        Google gave nothing usable (blocked, rate-limited, not JSON).

        Tries each GOOGLE_SUGGEST_CLIENTS in turn; a rate limit or server error
        waits GOOGLE_SUGGEST_BACKOFF_SECONDS (plus jitter) first. Any other
        HTTP error (403: the IP is blocked) stops at once, more requests would
        only prolong the block.
        """
        english = language == 'en'
        error = None
        for attempt, client in enumerate(GOOGLE_SUGGEST_CLIENTS):
            if attempt:
                time.sleep(GOOGLE_SUGGEST_BACKOFF_SECONDS + random.uniform(0, 1))
            params = {'client': client, 'q': query, 'hl': 'en' if english else 'id', 'gl': 'us' if english else 'id',
                      'ie': 'utf-8', 'oe': 'utf-8'}
            headers = dict(SUGGEST_HEADERS, **{'Accept-Language': 'en-US,en;q=0.9' if english else 'id-ID,id;q=0.9'})
            try:
                response = requests.get(GOOGLE_SUGGEST_URL, params=params, headers=headers, timeout=timeout)
            except requests.RequestException as e:
                error = type(e).__name__
                continue
            if response.status_code != 200:
                error = f'HTTP {response.status_code}'
                if response.status_code in GOOGLE_SUGGEST_RETRY_STATUSES:
                    continue
                break
            try:
                data = json.loads(response.content.decode('utf-8', errors='replace'))
            except ValueError:
                error = 'bukan JSON'
                continue
            if isinstance(data, list) and len(data) > 1 and isinstance(data[1], list):
                return [' '.join(item.split()) for item in data[1] if isinstance(item, str) and item.strip()], None
            error = 'format tidak dikenal'
            break
        logger.warning(f"Google Suggest gave nothing for '{query}': {error}")
        return None, error

    def get_keyword_suggestions(self, keyword, limit=10, language='id'):
        """Get keyword suggestions from Google Autocomplete"""
        suggestions = []
        error = None
        try:
            found, error = self._google_suggest(keyword, language=language, timeout=10)
            if found:
                suggestions = found[:limit]
                self._mark_source('google_autocomplete', 'real', count=len(suggestions))
        except Exception as e:
            logger.error(f"Error getting keyword suggestions: {e}")

        if not suggestions:
            # Fallback if Google Autocomplete fails or yields nothing
            if language == 'en':
                suggestions = [
                    f"best {keyword}", f"{keyword} tips", f"{keyword} tutorial",
                    f"how to start with {keyword}", f"{keyword} for beginners"
                ]
            else:
                suggestions = [
                    f"tips {keyword}", f"panduan {keyword}", f"belajar {keyword}",
                    f"cara memulai {keyword}", f"{keyword} untuk pemula"
                ]
            details = {'reason': error} if error else {}
            self._mark_source('google_autocomplete', 'fallback', count=len(suggestions), **details)
        return suggestions[:limit]

    def get_related_questions(self, keyword, limit=10, language='id'):
        """Generate related questions dynamically via Google Autocomplete using question modifiers"""
        questions = []
        if language == 'en':
            modifiers = ["how to", "what is", "why does", "can you"]
        else:
            modifiers = ["bagaimana cara", "apa itu", "kenapa", "apakah"]

        try:
            for mod in modifiers:
                found, _error = self._google_suggest(f"{mod} * {keyword}", language=language, timeout=5)
                if found is None:
                    break  # blocked or rate-limited: more modifiers would only prolong it
                # Add valid questions that aren't too short
                questions.extend([q for q in found if len(q.split()) > 3])

            # Remove duplicates while preserving order
            seen = set()
            unique_questions = []
            for q in questions:
                if q not in seen:
                    seen.add(q)
                    unique_questions.append(q)

            if unique_questions:
                self._mark_source('related_questions', 'real', count=len(unique_questions[:limit]))
                return unique_questions[:limit]
        except Exception as e:
            logger.error(f"Error getting dynamic related questions: {e}")

        # Fallback to standard hardcoded patterns if API fails or returns nothing
        if language == 'en':
            patterns = [
                f"What is {keyword}?",
                f"How to {keyword}?",
                f"What are the benefits of {keyword}?"
            ]
        else:
            patterns = [
                f"Apa itu {keyword}?",
                f"Bagaimana cara {keyword}?",
                f"Apa manfaat {keyword}?"
            ]
        self._mark_source('related_questions', 'fallback', count=len(patterns[:limit]))
        return patterns[:limit]

    @staticmethod
    def _wikipedia_title_candidates(keyword):
        """Case variants to try, since only the first letter of a title is case-insensitive."""
        base = ' '.join(str(keyword or '').split())
        candidates = []
        for title in (base, base[:1].upper() + base[1:].lower(), base.title(), base.lower()):
            if title and title not in candidates:
                candidates.append(title)
        return candidates

    @classmethod
    def _pick_wikipedia_extract(cls, data, candidates):
        """Return (title, extract) for the first candidate resolving to a real article."""
        query = (data or {}).get('query') or {}
        pages = query.get('pages') or {}
        by_title = {}
        for page in pages.values():
            if 'missing' in page or 'invalid' in page:
                continue
            by_title.setdefault(str(page.get('title') or '').lower(), page)

        def resolve(title):
            # Normalisation runs before redirects in the API response too.
            for step in ('normalized', 'redirects'):
                for mapping in query.get(step) or []:
                    if mapping.get('from') == title:
                        title = mapping.get('to') or title
            return title

        for candidate in candidates:
            page = by_title.get(resolve(candidate).lower())
            if not page or 'disambiguation' in (page.get('pageprops') or {}):
                continue
            extract = ' '.join(str(page.get('extract') or '').split())
            title = str(page.get('title') or '')
            if len(extract) < WIKIPEDIA_MIN_EXTRACT_CHARS or extract.lower().strip(' .') == title.lower():
                continue
            return title, extract
        return None, ''

    def get_wikipedia_context(self, keyword, language='id'):
        """Extract semantic entities and context from Wikipedia API"""
        try:
            wiki_lang = 'en' if language == 'en' else 'id'
            url = f"https://{wiki_lang}.wikipedia.org/w/api.php"
            candidates = self._wikipedia_title_candidates(keyword)
            params = {
                'action': 'query',
                'format': 'json',
                'prop': 'extracts|pageprops',
                'ppprop': 'disambiguation',
                'exintro': True,
                'explaintext': True,
                'exsentences': 3,
                'redirects': 1,
                'titles': '|'.join(candidates),
            }
            response = requests.get(url, params=params, headers=self.headers, timeout=5)
            if response.status_code == 200:
                title, extract = self._pick_wikipedia_extract(response.json(), candidates)
                if extract:
                    self._mark_source('wikipedia', 'real', count=1, title=title)
                    return extract
        except Exception as e:
            logger.error(f"Error getting Wikipedia context: {e}")
        self._mark_source('wikipedia', 'unavailable', count=0)
        return ""

    def get_latest_news(self, keyword, limit=3, language='id'):
        """Get latest news headlines using DuckDuckGo News"""
        news_headlines = []
        ddgs = self._new_ddgs()
        if ddgs:
            try:
                results = ddgs.news(keyword, **self._ddg_kwargs(language, limit, kind='news')) or []
                for res in results:
                    if not res.get('title'):
                        continue
                    news_headlines.append({
                        'title': res.get('title', ''),
                        'source': res.get('source', ''),
                        'url': res.get('url') or res.get('href', ''),
                        'published_at': res.get('date'),
                    })
            except Exception as e:
                logger.error(f"Error getting DDG News: {e}")
        self._mark_source('news', 'real' if news_headlines else 'unavailable', count=len(news_headlines))
        return news_headlines

    # Daily points on each side of the growth comparison: last week vs the week before.
    TREND_COMPARE_DAYS = 7
    # Daily resolution; long enough that `average` is a real baseline for `current`.
    TREND_TIMEFRAME = 'today 3-m'

    @classmethod
    def score_trend_series(cls, values):
        """Score a daily interest series. Returns None when there is no real signal.

        `current` is the mean of the last 7 days, `growth` compares it with the
        7 days before, `average`/`volatility` describe the whole window. An all-zero
        series is Google's "not enough data", not a measurement of zero interest.
        """
        values = [float(v) for v in values or []]
        if len(values) < 2 or max(values) <= 0:
            return None
        window = max(1, min(cls.TREND_COMPARE_DAYS, len(values) // 2))
        latest = values[-window:]
        previous = values[-2 * window:-window]
        current = sum(latest) / len(latest)
        previous_level = sum(previous) / len(previous)
        average = sum(values) / len(values)
        growth = ((current - previous_level) / max(previous_level, 1.0)) * 100
        variance = sum((v - average) ** 2 for v in values) / len(values)
        volatility = variance ** 0.5
        momentum = max(0.0, min(100.0, 50.0 + growth))
        stability = max(0.0, 100.0 - volatility)
        score = round((current * .45) + (average * .25) +
                      (momentum * .20) + (stability * .10))
        return {
            'score': max(0, min(100, score)),
            'current': round(current, 1),
            'average': round(average, 1),
            'growth': round(growth, 1),
            'volatility': round(volatility, 1),
            'samples': len(values),
        }

    @staticmethod
    def _complete_values(data, keyword):
        """Interest values without the trailing partial (still-collecting) day."""
        values = data[keyword].tolist()
        if 'isPartial' in getattr(data, 'columns', []):
            partial = data['isPartial'].tolist()
            values = [v for v, is_partial in zip(values, partial) if not is_partial]
        return values

    def get_trend_analysis(self, keyword, language='id'):
        """Return an auditable score based on level, momentum, and stability."""
        unavailable = {'score': None, 'current': None, 'average': None, 'growth': None,
                       'volatility': None, 'status': 'unavailable'}
        if not TrendReq:
            self._mark_source('google_trends', 'unavailable', reason='pytrends_not_installed')
            return unavailable

        try:
            _hl, _tz, geo = trends_locale(language)
            # Shared, throttled client; see trending_research.trends_session.
            with trends_session(language, client_factory=TrendReq) as pytrends:
                pytrends.build_payload([keyword], cat=0, timeframe=self.TREND_TIMEFRAME, geo=geo)
                data = pytrends.interest_over_time()

                # A 12-month pass detects seasonality, but it doubles the number of
                # Google Trends requests. Trends throttles aggressively, and a 429
                # costs the category its Trends points, which can push it below the
                # evidence threshold. Off unless explicitly enabled.
                seasonality = None
                if ENABLE_TREND_SEASONALITY:
                    seasonality = self._get_seasonality(pytrends, keyword, geo)

            if data.empty or keyword not in data.columns:
                self._mark_source('google_trends', 'unavailable', reason='no_data')
                return unavailable
            measured = self.score_trend_series(self._complete_values(data, keyword))
            if not measured:
                self._mark_source('google_trends', 'unavailable', reason='no_interest')
                return unavailable
            self._mark_source('google_trends', 'real', samples=measured.pop('samples'))
            return {**measured, 'status': 'real', 'seasonality': seasonality}
        except Exception as e:
            logger.error(f"Pytrends error for {keyword}: {e}")
            self._mark_source('google_trends', 'unavailable', reason=type(e).__name__)
        return unavailable

    def get_category_trend(self, category_name, language='id'):
        """get_trend_analysis for category_name, retried once with its head term.

        Long category names ("Emergency Fund and Financial Safety") often have no
        Trends data; the shorter head term ("emergency fund") usually does. The
        term actually scored is recorded as trend_term (source metadata and the
        analysis), so the UI can say which term the score is for.
        """
        analysis = self.get_trend_analysis(category_name, language=language)
        reason = (self.source_status.get('google_trends') or {}).get('reason')
        head = trend_head_term(category_name, language)
        if analysis.get('status') == 'real' or reason not in ('no_data', 'no_interest') or not head:
            return analysis
        logger.info(f"No Google Trends data for '{category_name}'; retrying with head term '{head}'.")
        retried = self.get_trend_analysis(head, language=language)
        if retried.get('status') == 'real':
            with self._status_lock:
                self.source_status['google_trends']['trend_term'] = head
            return {**retried, 'term': head}
        return analysis

    @staticmethod
    def _get_seasonality(pytrends, keyword, geo):
        """Detect recurring demand from a 12-month interest curve.

        Returns the peak months and whether the topic looks seasonal, so a topic
        can be scheduled when demand actually rises rather than at random.
        """
        try:
            pytrends.build_payload([keyword], cat=0, timeframe='today 12-m', geo=geo)
            yearly = pytrends.interest_over_time()
            if yearly.empty or keyword not in yearly.columns:
                return None

            by_month = {}
            for timestamp, value in yearly[keyword].items():
                by_month.setdefault(timestamp.month, []).append(float(value))
            monthly_avg = {m: sum(v) / len(v) for m, v in by_month.items() if v}
            if len(monthly_avg) < 6:
                return None

            overall = sum(monthly_avg.values()) / len(monthly_avg)
            if overall <= 0:
                return None
            peak_months = sorted(
                (m for m, v in monthly_avg.items() if v >= overall * 1.3),
                key=lambda m: monthly_avg[m], reverse=True
            )[:3]
            spread = max(monthly_avg.values()) - min(monthly_avg.values())
            return {
                'is_seasonal': bool(peak_months) and spread >= overall * .5,
                'peak_months': peak_months,
                'monthly_average': {str(m): round(v, 1) for m, v in sorted(monthly_avg.items())},
            }
        except Exception as e:
            logger.warning(f"Seasonality lookup failed for '{keyword}': {e}")
            return None

    @staticmethod
    def extract_outline(content, limit=15):
        """Content headings from a Jina Reader markdown page, minus site chrome."""
        headers = []
        seen = set()
        for line in str(content or '')[:MAX_PAGE_CONTENT_CHARS].split('\n'):
            line = line.strip()
            if len(line) > 500:
                # Not a real heading; also keeps the regexes below bounded.
                continue
            if line.startswith('## ') or line.startswith('### '):
                header_text = re.sub(r'^#+\s*', '', line)
                header_text = ' '.join(strip_markdown_links(header_text).split()).strip(' *_#')
                if not (10 < len(header_text) < 120) or is_boilerplate_heading(header_text):
                    continue
                if header_text.lower() in seen:
                    continue
                seen.add(header_text.lower())
                headers.append(header_text)
            if len(headers) >= limit:
                break
        return headers

    @staticmethod
    def _fetch_page_markdown(url, timeout=20, kind='competitor'):
        """A page as markdown through Jina Reader, or None (error, 429, non-200)."""
        request_headers = {'Authorization': f'Bearer {JINA_API_KEY}'} if JINA_API_KEY else None
        try:
            page_resp = requests.get(f"https://r.jina.ai/{url}", headers=request_headers, timeout=timeout)
        except Exception as ex:
            logger.warning(f"Failed to fetch {kind} {url}: {ex}")
            return None

        if page_resp.status_code == 429:
            logger.warning(f"Jina Reader rate-limited while fetching {url}; skipping.")
            return None
        if page_resp.status_code != 200:
            logger.warning(f"{kind.capitalize()} fetch for {url} returned {page_resp.status_code}")
            return None
        return (page_resp.text or '')[:MAX_PAGE_CONTENT_CHARS]

    def _scrape_competitor(self, url, title, keyword=None, language='id', exclude_hosts=None):
        """Fetch one competitor page and extract its structure and key passages.

        Captures word count, full heading outline and any visible date, so callers
        can judge how thorough and how current the competing page is, plus the
        passages most relevant to keyword (see extract_key_passages), so the
        writer sees what the page says and not only how it is organised.

        Returns None for pages that failed to load, that redirected to an
        excluded host, that look like spam, or that are off-topic (no relevant
        passage and a title unrelated to keyword). When Jina reports that the
        page was read from a different host (a redirect), that final URL is the
        one recorded and cited.
        """
        content = self._fetch_page_markdown(url)
        if content is None:
            return None

        final_url = page_source_url(content)
        if final_url and url_host(final_url) and url_host(final_url) != url_host(url):
            logger.info(f"Competitor {url} redirected to {final_url}")
            url = final_url
        if is_excluded_url(url, normalize_hosts(exclude_hosts)):
            return None

        topic = keyword or title
        title = ' '.join(strip_markdown_links(title).split()) or page_title(content)
        passages = extract_key_passages(content, topic, language)
        if is_spam_page(content, title, topic, passages):
            logger.warning(f"Competitor {url} looks like spam; skipped.")
            return None
        if not passages and not title_matches_topic(title, topic, language):
            logger.info(f"Competitor {url} is off-topic for '{topic}'; skipped.")
            return None

        headers = self.extract_outline(content)

        word_count = len(re.findall(r'\w+', content))
        published = None
        date_match = re.search(
            r'\b(20\d{2}-\d{2}-\d{2})\b|\b(\d{1,2}\s+\w+\s+20\d{2})\b', content[:4000]
        )
        if date_match:
            published = date_match.group(0)

        return {
            'url': url,
            'title': title,
            'headers': headers if headers else [title],
            'heading_count': len(headers),
            'word_count': word_count,
            'published_hint': published,
            'key_passages': passages,
            'retrieved_via': 'duckduckgo+jina',
        }

    def analyze_competitors(self, keyword, language='id', limit=4, exclude_hosts=None):
        """Scrape the top competitors via DuckDuckGo and extract their structure.

        Pages are fetched concurrently: previously this ran serially with a 2 second
        sleep between each, which dominated the runtime of a whole research pass.
        Results keep the search ranking order, not the order the fetches finished.
        Pages on exclude_hosts (the publisher's own site) are skipped.
        """
        excluded = self._excluded(exclude_hosts)
        ddgs = self._new_ddgs()
        if not ddgs:
            self._mark_source('competitors', 'unavailable', count=0)
            return []

        # A couple of spare results so an excluded own-site hit does not cost a competitor.
        max_results = limit + 2 if excluded else limit
        try:
            results = list(ddgs.text(keyword, **self._ddg_kwargs(language, max_results)) or [])
        except Exception as e:
            logger.error(f"DDGS competitor search error: {e}")
            self._mark_source('competitors', 'unavailable', count=0, reason=type(e).__name__)
            return []

        targets = [(r.get('href'), r.get('title')) for r in results
                   if r.get('href') and not is_excluded_url(r.get('href'), excluded)][:limit]
        scraped = [None] * len(targets)
        if targets:
            with ThreadPoolExecutor(max_workers=min(4, len(targets))) as pool:
                futures = {pool.submit(self._scrape_competitor, url, title, keyword, language, excluded): rank
                           for rank, (url, title) in enumerate(targets)}
                for future in as_completed(futures):
                    rank = futures[future]
                    try:
                        scraped[rank] = future.result()
                    except Exception as ex:
                        logger.warning(f"Competitor scrape failed for {targets[rank][0]}: {ex}")

        competitors = [item for item in scraped if item]
        competitors = self._deduplicate(competitors, key=lambda item: item.get('url'))
        self._mark_source('competitors', 'real' if competitors else 'unavailable', count=len(competitors))
        return competitors

    def get_official_sources(self, topic, language='id', limit=OFFICIAL_SOURCE_LIMIT, exclude_hosts=None):
        """Government pages about topic with their key passages.

        Searches DuckDuckGo restricted to the language's official domain (go.id
        for Indonesian, .gov for English), keeps the top results whose host
        really is under that domain, fetches them through Jina Reader and returns
        [{'title', 'url', 'passages'}] for pages that had relevant passages.
        A page is dropped when Jina read it from a non-official URL (a redirect
        off the government domain) or when it shows any spam marker: hacked
        regional .go.id sites hosting gambling spam are common.
        Never raises: any failure means no official sources.
        """
        try:
            return self._collect_official_sources(topic, language, limit, self._excluded(exclude_hosts))
        except Exception as e:
            logger.error(f"Official source lookup failed for '{topic}': {e}")
            self._mark_source('official_sources', 'unavailable', count=0, reason=type(e).__name__)
            return []

    def _collect_official_sources(self, topic, language, limit, excluded=frozenset()):
        ddgs = self._new_ddgs()
        if not ddgs:
            self._mark_source('official_sources', 'unavailable', count=0)
            return []

        sites = ' OR '.join(f'site:{suffix}' for suffix in official_domain_suffixes(language))
        try:
            results = list(ddgs.text(f'{topic} {sites}', **self._ddg_kwargs(language, OFFICIAL_SEARCH_RESULTS)) or [])
        except Exception as e:
            logger.error(f"DDGS official source search error: {e}")
            self._mark_source('official_sources', 'unavailable', count=0, reason=type(e).__name__)
            return []

        targets, seen = [], set()
        for result in results:
            url = str(result.get('href') or '').strip()
            if not is_official_url(url, language) or is_excluded_url(url, excluded) or url.lower() in seen:
                continue
            seen.add(url.lower())
            targets.append((url, result.get('title')))
            if len(targets) >= limit:
                break

        def fetch(url, title):
            content = self._fetch_page_markdown(url, timeout=OFFICIAL_FETCH_TIMEOUT, kind='official source')
            if content is None:
                return None
            final_url = page_source_url(content)
            if final_url:
                if not is_official_url(final_url, language) or is_excluded_url(final_url, excluded):
                    logger.warning(f"Official source {url} was read from {final_url}; skipped.")
                    return None
                url = final_url
            passages = extract_key_passages(content, topic, language)
            if not passages:
                return None
            title = ' '.join(strip_markdown_links(title).split()) or page_title(content) or urlsplit(url).hostname
            # Strict: any spam marker at all on a government page means it was compromised.
            if is_spam_page(content, title, topic, passages, body_limit=0):
                logger.warning(f"Official source {url} carries spam markers; skipped.")
                return None
            return {'title': title, 'url': url, 'passages': passages}

        fetched = [None] * len(targets)
        if targets:
            with ThreadPoolExecutor(max_workers=len(targets)) as pool:
                futures = {pool.submit(fetch, url, title): rank for rank, (url, title) in enumerate(targets)}
                for future in as_completed(futures):
                    rank = futures[future]
                    try:
                        fetched[rank] = future.result()
                    except Exception as ex:
                        logger.warning(f"Official source fetch failed for {targets[rank][0]}: {ex}")

        sources = [item for item in fetched if item]
        self._mark_source('official_sources', 'real' if sources else 'unavailable',
                          count=len(sources), candidates=len(targets))
        return sources

    def get_social_insights(self, keyword, language='id'):
        """Search Quora & Reddit for real human questions"""
        insights = []
        ddgs = self._new_ddgs()
        if not ddgs:
            self._mark_source('social', 'unavailable', count=0)
            return []

        try:
            query = f"site:quora.com OR site:reddit.com {keyword}"
            results = list(ddgs.text(query, **self._ddg_kwargs(language, 5)) or [])
            for res in results:
                title = res.get('title', '')
                if is_question_title(title, language):
                    insights.append({'text': title, 'url': res.get('href', ''), 'provider': 'quora_or_reddit'})
        except Exception as e:
            logger.error(f"DDGS social insights error: {e}")
            self._mark_source('social', 'unavailable', count=0, reason=type(e).__name__)
            return []

        insights = self._deduplicate(insights, key=lambda item: item.get('text'))[:5]
        self._mark_source('social', 'real' if insights else 'unavailable', count=len(insights))
        return insights

    @staticmethod
    def _fetch_transcript(video_id, languages):
        """Transcript snippets via youtube-transcript-api 1.x (0.x as a fallback)."""
        if hasattr(YouTubeTranscriptApi, 'fetch'):
            return YouTubeTranscriptApi().fetch(video_id, languages=languages)
        return YouTubeTranscriptApi.get_transcript(video_id, languages=languages)

    def get_youtube_insights(self, keyword, language='id', max_videos=2):
        """Find top YouTube videos and get a transcript excerpt for each"""
        ddgs = self._new_ddgs()
        if not ddgs or not YouTubeTranscriptApi:
            self._mark_source('youtube', 'unavailable', count=0)
            return []

        try:
            query = f"site:youtube.com {keyword}"
            # More results than videos wanted: channel and playlist pages are skipped.
            results = list(ddgs.text(query, **self._ddg_kwargs(language, 5)) or [])
        except Exception as e:
            logger.error(f"Youtube insights error: {e}")
            self._mark_source('youtube', 'unavailable', count=0, reason=type(e).__name__)
            return []

        return self.youtube_insights_for([(res.get('href', ''), res.get('title')) for res in results],
                                         language=language, max_videos=max_videos)

    def youtube_insights_for(self, videos, language='id', max_videos=2, **status_details):
        """Transcript excerpts for (url, title) video candidates, in order.

        A video whose transcript cannot be fetched (none published, disabled,
        or YouTube blocking this server's IP) is kept title-only with
        transcript_available False; nothing is invented. Marks the 'youtube'
        source: real with a transcript, partial with videos only.
        """
        insights = []
        langs = ['en', 'id'] if language == 'en' else ['id', 'en']
        seen_ids = set()
        for url, title in videos:
            video_id = extract_youtube_video_id(url)
            if not video_id or video_id in seen_ids:
                continue
            seen_ids.add(video_id)
            snippets = ''
            if YouTubeTranscriptApi:
                try:
                    snippets = transcript_excerpt(self._fetch_transcript(video_id, langs))
                except Exception as ex:
                    # NoTranscriptFound, TranscriptsDisabled, IpBlocked, ... all
                    # subclass CouldNotRetrieveTranscript; network errors land here too.
                    logger.warning(f"No transcript for video {video_id}: {type(ex).__name__}: {ex}")
            insights.append({
                'video_id': video_id,
                'title': title,
                'url': url,
                'snippets': snippets,
                'transcript_available': bool(snippets),
            })
            if len(insights) >= max_videos:
                break

        transcript_count = sum(1 for item in insights if item.get('transcript_available'))
        if not insights:
            status = 'unavailable'
        else:
            status = 'real' if transcript_count else 'partial'
        self._mark_source('youtube', status, count=len(insights), transcripts=transcript_count, **status_details)
        return insights

    def _real_only(self, provider, items):
        """`items` if `provider` returned observed data, else [] (fallback or failure)."""
        status = (self.source_status.get(provider) or {}).get('status')
        return list(items or []) if status == 'real' else []

    @staticmethod
    def build_long_tail_keywords(category_name, suggestions, questions, limit=15):
        candidates = list(suggestions or []) + list(questions or [])
        long_tail = []
        seen = set()
        for candidate in candidates:
            text = ' '.join(str(candidate).split()).strip()
            normalized = text.lower()
            if len(text.split()) < 4 or normalized in seen:
                continue
            seen.add(normalized)
            long_tail.append(text)
            if len(long_tail) >= limit:
                break
        return long_tail

    @staticmethod
    def evaluate_quality(source_status, competitor_count=0, transcript_count=0,
                         suggestion_count=0, question_count=0):
        """Score evidence quality, not popularity. Returns 0..100 and a label."""
        # Weighted by how much each source actually contributes to writing the
        # article, not merely by whether it responded.
        #
        # Google Trends previously carried 25 — the largest share — but it returns a
        # popularity score, not material you can write from. Autocomplete and related
        # questions return the actual phrasing people search and the questions they
        # ask, which become keywords and section headings, so they now carry more.
        #
        # These total 85. The remaining 15 is Search Console, added by the caller,
        # because it is first-party evidence the research module cannot see.
        weights = {
            'google_autocomplete': 20,
            'competitors': 20,
            'related_questions': 15,
            'google_trends': 10,
            'social': 8,
            'youtube': 5,
            'news': 4,
            'wikipedia': 3,
        }
        # Autocomplete and related questions are both Google Suggest (the same
        # endpoint queried with and without question modifiers). They keep their
        # separate point weights, because they feed different prompt sections
        # (keywords vs. questions to answer), but they are one independent source,
        # so together they count once towards the provider-diversity thresholds.
        upstream = {'google_autocomplete': 'google_suggest', 'related_questions': 'google_suggest'}

        def status_of(provider):
            return (source_status.get(provider) or {}).get('status', 'unavailable')

        score = 0.0
        real_upstreams = set()
        fallback_providers = []
        for provider, weight in weights.items():
            status = status_of(provider)
            if status == 'real':
                score += weight
                real_upstreams.add(upstream.get(provider, provider))
            elif status == 'partial':
                score += weight * .5
            elif status == 'fallback':
                score += weight * .15
                fallback_providers.append(provider)
        real_providers = len(real_upstreams)

        # Reward useful depth but cap each bonus so quantity cannot mask bad sources.
        # Depth only counts observed evidence: counts from a provider that fell
        # back to invented items (or failed) are ignored, whatever the caller passed.
        if status_of('competitors') == 'real':
            score += min(5, competitor_count * 2)
        if status_of('youtube') == 'real':
            score += min(3, transcript_count * 1.5)
        if status_of('google_autocomplete') == 'real':
            score += min(4, suggestion_count * .4)
        if status_of('related_questions') == 'real':
            score += min(3, question_count * .3)
        score = max(0, min(100, round(score)))

        if score >= 75 and real_providers >= 5:
            confidence = 'high'
        elif score >= 50 and real_providers >= 3:
            confidence = 'medium'
        elif score >= 35 and real_providers >= 2:
            confidence = 'low'
        else:
            confidence = 'insufficient'
        return {
            'score': score,
            'confidence': confidence,
            'real_provider_count': real_providers,
            'fallback_providers': fallback_providers,
            'passes_minimum': confidence != 'insufficient',
        }

    def research_topic(self, topic, category_name=None, language='id', exclude_hosts=None):
        """Focused research for one specific article topic.

        research_category() researches a broad category name, which produces generic
        evidence for a specific article. This runs the same providers against the
        actual title/topic, so the article is written against evidence for what it
        is really about. Cheaper than a full category pass: no Trends, no news.

        Only here, not per category, official (government) pages are looked up:
        their figures and rules are specific to the article's topic.

        exclude_hosts: hostnames (e.g. the publisher's own site) whose pages must
        not appear as competitors or sources; subdomains are excluded too.
        """
        excluded = self._excluded(exclude_hosts)
        logger.info(f"Topic-level research: '{topic}' (category={category_name})")
        self.source_status = {}

        collected = self._run_with_claude(
            topic, language, excluded,
            independent={
                'suggestions': lambda: self.get_keyword_suggestions(topic, limit=10, language=language),
                'questions': lambda: self.get_related_questions(topic, limit=8, language=language),
            },
            duckduckgo={
                'competitors': lambda: self.analyze_competitors(topic, language=language, limit=3,
                                                                exclude_hosts=excluded),
                'official_sources': lambda: self.get_official_sources(topic, language=language,
                                                                      exclude_hosts=excluded),
                'social': lambda: self.get_social_insights(topic, language=language),
            },
            replaceable=('competitors', 'official_sources', 'social', 'questions'),
            claude_options={'category': category_name, 'want_news': False, 'want_youtube': False,
                            'competitor_limit': 3, 'question_limit': 8},
            competitor_limit=3,
            label=f" for '{topic}'",
        )

        evidence_suggestions = self._real_only('google_autocomplete', collected.get('suggestions'))
        evidence_questions = self._real_only('related_questions', collected.get('questions'))

        return {
            'topic': topic,
            'category': category_name,
            'keywords': evidence_suggestions,
            'questions': evidence_questions,
            'evidence_suggestions': evidence_suggestions,
            'evidence_questions': evidence_questions,
            'competitor_outlines': collected.get('competitors') or [],
            'official_sources': collected.get('official_sources') or [],
            'social_insights': collected.get('social') or [],
            'long_tail_keywords': self.build_long_tail_keywords(topic, evidence_suggestions, evidence_questions),
            'source_metadata': self.source_status,
            'timestamp': datetime.now(timezone.utc).isoformat(),
        }

    def research_category(self, category_name, language='id', exclude_hosts=None):
        """Deep Research a category including competitors, social, and youtube.

        exclude_hosts: hostnames (e.g. the publisher's own site) whose pages must
        not appear as competitors or news sources; subdomains are excluded too.
        """
        excluded = self._excluded(exclude_hosts)
        logger.info(f"Advanced Researching category: {category_name} with language={language}")
        self.source_status = {}

        job = get_current_job() if get_current_job else None

        def update_progress(prog, msg):
            if job:
                job.meta['progress'] = prog
                job.meta['message'] = msg
                job.save_meta()

        # Shown to the user by the research job status endpoint.
        update_progress(30, f'Mengumpulkan bukti untuk {category_name}...')
        duckduckgo = {
            'competitors': lambda: self.analyze_competitors(category_name, language=language,
                                                            exclude_hosts=excluded),
            'social': lambda: self.get_social_insights(category_name, language=language),
            'youtube': lambda: self.get_youtube_insights(category_name, language=language),
            'news': lambda: self.get_latest_news(category_name, limit=3, language=language),
        }
        if self.claude:
            # Official pages per category come with Claude research; the classic
            # lookup only runs as its fallback (classic research is unchanged).
            duckduckgo['official_sources'] = lambda: self.get_official_sources(
                category_name, language=language, exclude_hosts=excluded)
        collected = self._run_with_claude(
            category_name, language, excluded,
            independent={
                'suggestions': lambda: self.get_keyword_suggestions(category_name, limit=10, language=language),
                'trend_analysis': lambda: self.get_category_trend(category_name, language=language),
                'questions': lambda: self.get_related_questions(category_name, limit=10, language=language),
                # Always the free Wikipedia API (no DuckDuckGo, no Claude fetch).
                'wikipedia': lambda: self.get_wikipedia_context(category_name, language=language),
            },
            duckduckgo=duckduckgo,
            replaceable=('competitors', 'official_sources', 'news', 'social', 'questions', 'youtube'),
            claude_options={'want_youtube': True, 'question_limit': 10},
            label=f" for {category_name}",
        )
        update_progress(90, f'Menilai bukti untuk {category_name}...')

        suggestions = collected.get('suggestions') or []
        trend_analysis = collected.get('trend_analysis') or {'score': None, 'status': 'unavailable'}
        trend_score = trend_analysis.get('score') or 0
        competitor_outlines = collected.get('competitors') or []
        official_sources = collected.get('official_sources') or []
        social_insights = collected.get('social') or []
        youtube_insights = collected.get('youtube') or []
        questions = collected.get('questions') or []
        semantic_context = collected.get('wikipedia') or ''
        news_insights = [item for item in collected.get('news') or []
                         if not (isinstance(item, dict) and is_excluded_url(item.get('url'), excluded))]

        update_progress(95, f'Menilai bukti untuk {category_name}...')

        # Keywords produced by the offline fallback are invented, not observed. They
        # are fine as UI hints but must not reach the article generator, which is now
        # under an evidence policy, nor long-tail keywords, topics or the score.
        evidence_suggestions = self._real_only('google_autocomplete', suggestions)
        evidence_questions = self._real_only('related_questions', questions)
        long_tail_keywords = self.build_long_tail_keywords(category_name, evidence_suggestions, evidence_questions)
        transcript_count = sum(1 for item in youtube_insights if item.get('transcript_available'))
        quality = self.evaluate_quality(
            self.source_status,
            competitor_count=len(competitor_outlines),
            transcript_count=transcript_count,
            suggestion_count=len(evidence_suggestions),
            question_count=len(evidence_questions),
        )

        result = {
            'category': category_name,
            # May contain offline fallback phrases; UI hints only.
            'suggestions': suggestions,
            # Only observed evidence is passed to the generator; see above.
            'evidence_suggestions': evidence_suggestions,
            'evidence_questions': evidence_questions,
            'trend_score': trend_score,
            'trend_analysis': trend_analysis,
            'competitor_outlines': competitor_outlines,
            'official_sources': official_sources,
            'social_insights': social_insights,
            'youtube_insights': youtube_insights,
            # May contain offline fallback phrases; UI hints only.
            'questions': questions,
            # Built from evidence_suggestions/evidence_questions only.
            'long_tail_keywords': long_tail_keywords,
            'semantic_context': semantic_context,
            'news_insights': news_insights,
            'source_metadata': self.source_status,
            'quality': quality,
            'timestamp': datetime.now(timezone.utc).isoformat(),
        }

        logger.info(f"Category research complete: Trend={trend_score}, Competitors={len(competitor_outlines)}")

        return result

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    seo = SEOResearch()
    logger.info("Testing advanced research...")
    res = seo.research_category("bisnis online")
    logger.info(json.dumps(res, indent=2))
