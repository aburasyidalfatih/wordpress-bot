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

_MARKDOWN_IMAGE_RE = re.compile(r'!\[([^\]]*)\]\([^)]*\)')
_MARKDOWN_LINK_RE = re.compile(r'\[([^\]]*)\]\([^)]*\)')

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


class SEOResearch:
    """Advanced Research using DDGS, Pytrends, and YouTube Transcripts"""

    def __init__(self):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        self.ddgs_available = DDGS is not None
        self.source_status = {}
        self._status_lock = Lock()

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

    def get_keyword_suggestions(self, keyword, limit=10, language='id'):
        """Get keyword suggestions from Google Autocomplete"""
        suggestions = []
        try:
            url = "https://suggestqueries.google.com/complete/search"
            hl = 'en' if language == 'en' else 'id'
            params = {'client': 'firefox', 'q': keyword, 'hl': hl}
            response = requests.get(url, params=params, headers=self.headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if len(data) > 1:
                    suggestions = data[1][:limit]
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
            self._mark_source('google_autocomplete', 'fallback', count=len(suggestions))
        return suggestions[:limit]

    def get_related_questions(self, keyword, limit=10, language='id'):
        """Generate related questions dynamically via Google Autocomplete using question modifiers"""
        questions = []
        if language == 'en':
            modifiers = ["how to", "what is", "why does", "can you"]
        else:
            modifiers = ["bagaimana cara", "apa itu", "kenapa", "apakah"]

        try:
            url = "https://suggestqueries.google.com/complete/search"
            hl = 'en' if language == 'en' else 'id'
            for mod in modifiers:
                query = f"{mod} * {keyword}"
                params = {'client': 'firefox', 'q': query, 'hl': hl}
                response = requests.get(url, params=params, headers=self.headers, timeout=5)
                if response.status_code == 200:
                    data = response.json()
                    if len(data) > 1:
                        # Add valid questions that aren't too short
                        questions.extend([q for q in data[1] if len(q.split()) > 3])

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
        for line in str(content or '').split('\n'):
            line = line.strip()
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

    def _scrape_competitor(self, url, title):
        """Fetch one competitor page and extract its structure.

        Captures word count, full heading outline and any visible date, so callers
        can judge how thorough and how current the competing page is.
        """
        request_headers = {'Authorization': f'Bearer {JINA_API_KEY}'} if JINA_API_KEY else None
        try:
            page_resp = requests.get(f"https://r.jina.ai/{url}", headers=request_headers, timeout=20)
        except Exception as ex:
            logger.warning(f"Failed to fetch competitor {url}: {ex}")
            return None

        if page_resp.status_code == 429:
            logger.warning(f"Jina Reader rate-limited while fetching {url}; skipping.")
            return None
        if page_resp.status_code != 200:
            logger.warning(f"Competitor fetch for {url} returned {page_resp.status_code}")
            return None

        content = page_resp.text
        headers = self.extract_outline(content)
        title = ' '.join(strip_markdown_links(title).split())

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
            'retrieved_via': 'duckduckgo+jina',
        }

    def analyze_competitors(self, keyword, language='id', limit=4):
        """Scrape the top competitors via DuckDuckGo and extract their structure.

        Pages are fetched concurrently: previously this ran serially with a 2 second
        sleep between each, which dominated the runtime of a whole research pass.
        Results keep the search ranking order, not the order the fetches finished.
        """
        ddgs = self._new_ddgs()
        if not ddgs:
            self._mark_source('competitors', 'unavailable', count=0)
            return []

        try:
            results = list(ddgs.text(keyword, **self._ddg_kwargs(language, limit)) or [])
        except Exception as e:
            logger.error(f"DDGS competitor search error: {e}")
            self._mark_source('competitors', 'unavailable', count=0, reason=type(e).__name__)
            return []

        targets = [(r.get('href'), r.get('title')) for r in results if r.get('href')]
        scraped = [None] * len(targets)
        if targets:
            with ThreadPoolExecutor(max_workers=min(4, len(targets))) as pool:
                futures = {pool.submit(self._scrape_competitor, url, title): rank
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
        insights = []
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

        langs = ['en', 'id'] if language == 'en' else ['id', 'en']
        seen_ids = set()
        for res in results:
            url = res.get('href', '')
            video_id = extract_youtube_video_id(url)
            if not video_id or video_id in seen_ids:
                continue
            seen_ids.add(video_id)
            snippets = ''
            try:
                snippets = transcript_excerpt(self._fetch_transcript(video_id, langs))
            except Exception as ex:
                # NoTranscriptFound, TranscriptsDisabled, IpBlocked, ... all
                # subclass CouldNotRetrieveTranscript; network errors land here too.
                logger.warning(f"No transcript for video {video_id}: {type(ex).__name__}: {ex}")
            insights.append({
                'video_id': video_id,
                'title': res.get('title'),
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
        self._mark_source('youtube', status, count=len(insights), transcripts=transcript_count)
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

    def research_topic(self, topic, category_name=None, language='id'):
        """Focused research for one specific article topic.

        research_category() researches a broad category name, which produces generic
        evidence for a specific article. This runs the same providers against the
        actual title/topic, so the article is written against evidence for what it
        is really about. Cheaper than a full category pass: no Trends, no news.
        """
        logger.info(f"Topic-level research: '{topic}' (category={category_name})")
        self.source_status = {}

        collected = self._run_providers(
            independent={
                'suggestions': lambda: self.get_keyword_suggestions(topic, limit=10, language=language),
                'questions': lambda: self.get_related_questions(topic, limit=8, language=language),
            },
            duckduckgo={
                'competitors': lambda: self.analyze_competitors(topic, language=language, limit=3),
                'social': lambda: self.get_social_insights(topic, language=language),
            },
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
            'social_insights': collected.get('social') or [],
            'long_tail_keywords': self.build_long_tail_keywords(topic, evidence_suggestions, evidence_questions),
            'source_metadata': self.source_status,
            'timestamp': datetime.now(timezone.utc).isoformat(),
        }

    def research_category(self, category_name, language='id'):
        """Deep Research a category including competitors, social, and youtube"""
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
        collected = self._run_providers(
            independent={
                'suggestions': lambda: self.get_keyword_suggestions(category_name, limit=10, language=language),
                'trend_analysis': lambda: self.get_trend_analysis(category_name, language=language),
                'questions': lambda: self.get_related_questions(category_name, limit=10, language=language),
                'wikipedia': lambda: self.get_wikipedia_context(category_name, language=language),
            },
            duckduckgo={
                'competitors': lambda: self.analyze_competitors(category_name, language=language),
                'social': lambda: self.get_social_insights(category_name, language=language),
                'youtube': lambda: self.get_youtube_insights(category_name, language=language),
                'news': lambda: self.get_latest_news(category_name, limit=3, language=language),
            },
            label=f" for {category_name}",
        )
        update_progress(90, f'Menilai bukti untuk {category_name}...')

        suggestions = collected.get('suggestions') or []
        trend_analysis = collected.get('trend_analysis') or {'score': None, 'status': 'unavailable'}
        trend_score = trend_analysis.get('score') or 0
        competitor_outlines = collected.get('competitors') or []
        social_insights = collected.get('social') or []
        youtube_insights = collected.get('youtube') or []
        questions = collected.get('questions') or []
        semantic_context = collected.get('wikipedia') or ''
        news_insights = collected.get('news') or []

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
