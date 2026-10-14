import urllib3_compat  # noqa: F401  (must run before pytrends is imported)

try:
    from pytrends.request import TrendReq
except ImportError:
    TrendReq = None
import logging
import os
from contextlib import contextmanager
from datetime import datetime
from threading import RLock
import time
import re

logger = logging.getLogger(__name__)

# Google Trends bans IPs that burst requests. Every pytrends call in the process
# goes through one lock and waits at least this long after the previous call.
TRENDS_MIN_INTERVAL_SECONDS = max(4.0, float(os.getenv('TRENDS_MIN_INTERVAL_SECONDS', '4')))
TRENDS_RETRIES = 2
TRENDS_BACKOFF_FACTOR = 2

_trends_lock = RLock()
_trends_clients = {}
_last_trends_request = 0.0

# Web requests (/api/trending, /api/suggest-topics) wait at most this long for
# the process-wide Trends lock instead of tying up a gunicorn thread behind
# other Trends traffic; they then report Trends as unavailable.
TRENDS_WEB_LOCK_TIMEOUT_SECONDS = 20


class TrendsBusyError(RuntimeError):
    """The Trends lock could not be acquired within the caller's timeout."""


def trends_locale(language='id'):
    """(hl, tz, geo) for pytrends.

    pytrends' tz is the browser's getTimezoneOffset(): minutes *behind* UTC, so
    WIB (UTC+7) is -420 and US Central (UTC-6) is 360.
    """
    if language == 'en':
        return 'en-US', 360, 'US'
    return 'id-ID', -420, 'ID'


class _ThrottledTrends:
    """Proxy that spaces every pytrends method call by TRENDS_MIN_INTERVAL_SECONDS."""

    def __init__(self, client):
        self._client = client

    def __getattr__(self, name):
        attr = getattr(self._client, name)
        if not callable(attr):
            return attr

        def call(*args, **kwargs):
            _wait_for_trends_slot()
            try:
                return attr(*args, **kwargs)
            finally:
                _mark_trends_request()
        return call


def _wait_for_trends_slot():
    wait = TRENDS_MIN_INTERVAL_SECONDS - (time.monotonic() - _last_trends_request)
    if _last_trends_request and wait > 0:
        time.sleep(wait)


def _mark_trends_request():
    global _last_trends_request
    _last_trends_request = time.monotonic()


@contextmanager
def trends_session(language='id', client_factory=None, lock_timeout=None):
    """Yield the process-wide pytrends client for `language`, throttled.

    lock_timeout (seconds) bounds the wait for the process-wide lock; when it
    runs out TrendsBusyError is raised. None waits as long as needed (workers).

    One TrendReq per (factory, language) is reused for the life of the process;
    creating one costs a cookie request, and a fresh client per call looked like
    a new visitor every time. The lock is held for the whole session, so a
    build_payload/interest_over_time pair is never interleaved with another
    thread's payload. A failed request (404, 429, ...) does not drop the client.
    """
    factory = client_factory if client_factory is not None else TrendReq
    if factory is None:
        raise RuntimeError('pytrends provider is not installed')
    hl, tz, _geo = trends_locale(language)
    key = (factory, hl, tz)
    if lock_timeout is None:
        acquired = _trends_lock.acquire()
    else:
        acquired = _trends_lock.acquire(timeout=max(0.0, float(lock_timeout)))
    if not acquired:
        raise TrendsBusyError(f'Google Trends is busy (waited {lock_timeout}s for the lock)')
    try:
        client = _trends_clients.get(key)
        if client is None:
            _wait_for_trends_slot()
            try:
                client = factory(hl=hl, tz=tz, timeout=(10, 25),
                                 retries=TRENDS_RETRIES, backoff_factor=TRENDS_BACKOFF_FACTOR)
            finally:
                _mark_trends_request()
            _trends_clients[key] = client
        yield _ThrottledTrends(client)
    finally:
        _trends_lock.release()


class TrendingResearch:
    def get_trending_topics(self, category_name, limit=10, language='id', lock_timeout=None):
        """Get trending topics related to category.

        lock_timeout bounds the wait for the Trends lock (web requests); when it
        runs out the result is empty with status 'busy'.
        """
        try:
            results = {
                'category': category_name,
                # Kept for stored-data compatibility. pytrends' trending_searches
                # (the hottrends endpoint) is gone and only ever returned 404.
                'trending_now': [],
                'related_rising': [],
                'related_top': [],
                'timestamp': datetime.now().isoformat()
            }

            _hl, _tz, geo = trends_locale(language)

            # Get related queries for category
            try:
                with trends_session(language, lock_timeout=lock_timeout) as pytrends:
                    pytrends.build_payload([category_name], timeframe='now 7-d', geo=geo)
                    related = pytrends.related_queries()

                if category_name in related:
                    if related[category_name]['rising'] is not None and not related[category_name]['rising'].empty:
                        results['related_rising'] = related[category_name]['rising'].head(limit)['query'].tolist()
                    if related[category_name]['top'] is not None and not related[category_name]['top'].empty:
                        results['related_top'] = related[category_name]['top'].head(limit)['query'].tolist()
            except TrendsBusyError as e:
                logger.warning(f"Skipped related queries: {e}")
                results['status'] = 'busy'
            except Exception as e:
                logger.warning(f"Could not get related queries: {e}")

            return results
        except Exception as e:
            logger.error(f"Trending research error: {e}")
            return None

    @staticmethod
    def _tokens(value):
        stopwords = {'dan', 'atau', 'yang', 'untuk', 'dengan', 'the', 'and', 'for', 'with'}
        return {
            token for token in re.findall(r'[a-z0-9]+', str(value).lower())
            if len(token) > 2 and token not in stopwords
        }

    @classmethod
    def is_relevant(cls, topic, category):
        category_tokens = cls._tokens(category)
        return bool(category_tokens and category_tokens.intersection(cls._tokens(topic)))

    # Topic types that came from Google Trends data, i.e. genuinely trending.
    TREND_TOPIC_TYPES = ('rising', 'popular', 'trending')

    @staticmethod
    def build_topic_suggestions(category_name, trending_data, count=5,
                                suggestions=None, questions=None, long_tail=None, keywords=None):
        """Build deterministic, deduplicated suggestions.

        Trend data (rising, then top related queries) comes first. Google Trends
        often has nothing for a niche category, so observed search demand backs it
        up: related questions, long-tail keywords, then autocomplete suggestions.
        Pass only REAL (non-fallback) suggestions/questions/long-tail here, i.e.
        SEOResearch's evidence_suggestions / evidence_questions / long_tail_keywords;
        the offline fallback phrases are invented and must never become topics.
        `keywords` is an alias for `suggestions`.
        """
        suggestions = list(suggestions or []) + list(keywords or [])
        output = []
        seen = {' '.join(str(category_name or '').lower().split())}
        groups = (
            ('rising', (trending_data or {}).get('related_rising', [])),
            ('popular', (trending_data or {}).get('related_top', [])),
            ('trending', (trending_data or {}).get('trending_now', [])),
            ('question', questions or []),
            ('long_tail', long_tail or []),
            ('autocomplete', suggestions or []),
        )
        for topic_type, topics in groups:
            for topic in topics:
                if isinstance(topic, dict):
                    topic = topic.get('keyword') or topic.get('question') or topic.get('topic') or ''
                text = ' '.join(str(topic).split())
                normalized = text.lower()
                if not normalized or normalized in seen:
                    continue
                seen.add(normalized)
                output.append({
                    'topic': text,
                    'type': topic_type,
                    'category': category_name,
                    'is_trending': topic_type in TrendingResearch.TREND_TOPIC_TYPES,
                })
                if len(output) >= count:
                    return output
        return output

    def suggest_article_topics(self, category_name, count=5, language='id', lock_timeout=None):
        """Suggest article topics based on trending data"""
        try:
            trending_data = self.get_trending_topics(category_name, limit=20, language=language,
                                                     lock_timeout=lock_timeout)

            if not trending_data:
                # Fallback: generate generic topics based on category
                return []

            return self.build_topic_suggestions(category_name, trending_data, count)
        except Exception as e:
            logger.error(f"Suggest topics error: {e}")
            return []
