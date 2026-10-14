"""Regression fixes: link allow-list normalization, research lock state, the
YouTube search backend, the bounded Google Trends lock and the research index."""
import importlib
import sys
import threading
import types
import unittest
from unittest.mock import Mock, patch

import database
from models import ResearchData
from services import wp_publisher
from services.quality_gate import normalize_link_url, strip_invalid_internal_links
from test_research_backend_support import FakeRedis


class LinkAllowListTests(unittest.TestCase):
    def test_normalization_ignores_scheme_www_and_trailing_slash(self):
        self.assertEqual(normalize_link_url('https://www.Example.com/a/'), 'example.com/a')
        self.assertEqual(normalize_link_url('http://example.com/a'), 'example.com/a')
        self.assertEqual(normalize_link_url('https://example.com/a?x=1'), 'example.com/a?x=1')

    def test_internal_links_tolerate_url_variants(self):
        content = '<a href="http://www.example.com/p1">a</a> <a href="https://example.com/p2/">b</a>'
        result = strip_invalid_internal_links(content, ['https://example.com/p1/', 'http://example.com/p2'])
        self.assertEqual(result, content)

    def test_allowed_hosts_keep_own_domain(self):
        content = '<a href="https://WWW.example.com/x">own</a> <a href="https://other.com/y">other</a>'
        result = strip_invalid_internal_links(content, [], allowed_hosts=['https://example.com/'])
        self.assertEqual(result, '<a href="https://WWW.example.com/x">own</a> other')

    def test_none_leaves_content_untouched(self):
        content = '<a href="https://other.com/y">other</a>'
        self.assertEqual(strip_invalid_internal_links(content, None, allowed_hosts=['example.com']), content)


class LockStateTests(unittest.TestCase):
    def setUp(self):
        self.redis = FakeRedis()
        self.statuses = {}
        self.status = lambda job_id: self.statuses.get(job_id, 'missing')

    def state(self, now):
        return database.research_lock_state(self.redis, 1, self.status, now=now)

    def test_states(self):
        self.assertEqual(self.state(0), (database.LOCK_FREE, None))
        database.acquire_research_lock(self.redis, 1, 'job', now=1000)
        self.assertEqual(self.redis.ttl('research_lock:1'), database.RESEARCH_LOCK_TTL_SECONDS)
        # Not enqueued yet: starting within the fixed grace window, whatever the job size.
        self.assertEqual(self.state(1000 + 119), (database.LOCK_STARTING, 'job'))
        self.statuses['job'] = 'queued'
        self.assertEqual(self.state(1000 + 20 * 3600), (database.LOCK_ACTIVE, 'job'))
        self.statuses['job'] = 'finished'
        self.assertEqual(self.state(1000 + 20 * 3600), (database.LOCK_FREE, None))
        self.assertIsNone(self.redis.get('research_lock:1'))

    def test_missing_job_past_grace_is_stale(self):
        database.acquire_research_lock(self.redis, 1, 'job', now=1000)
        self.assertEqual(self.state(1000 + 121), (database.LOCK_FREE, None))

    def test_legacy_value_without_timestamp(self):
        self.redis.set('research_lock:1', 'old-job')
        self.assertEqual(database.get_research_lock(self.redis, 1), 'old-job')
        self.assertTrue(database.release_research_lock(self.redis, 1, 'old-job'))

    def test_release_only_by_owner(self):
        database.acquire_research_lock(self.redis, 1, 'job-a')
        self.assertFalse(database.release_research_lock(self.redis, 1, 'job'))
        self.assertTrue(database.release_research_lock(self.redis, 1, 'job-a'))


class YouTubeSearchBackendTests(unittest.TestCase):
    def test_ddgs_gets_an_explicit_backend(self):
        client = Mock(**{'text.return_value': [{'href': 'x'}]})
        ddgs = types.ModuleType('ddgs')
        ddgs.DDGS = Mock(return_value=client)
        with patch.dict(sys.modules, {'ddgs': ddgs}):
            self.assertEqual(wp_publisher._ddgs_text_search('site:youtube.com kpr'), [{'href': 'x'}])
        client.text.assert_called_once_with('site:youtube.com kpr', max_results=5, backend='duckduckgo')

    def test_old_package_gets_no_backend(self):
        client = Mock(**{'text.return_value': []})
        legacy = types.ModuleType('duckduckgo_search')
        legacy.DDGS = Mock(return_value=client)
        with patch.dict(sys.modules, {'ddgs': None, 'duckduckgo_search': legacy}):
            wp_publisher._ddgs_text_search('q')
        client.text.assert_called_once_with('q', max_results=5)


def import_trending_research():
    """trending_research with pytrends stubbed (pandas/numpy are broken locally)."""
    request = types.ModuleType('pytrends.request')
    request.TrendReq = None
    pytrends = types.ModuleType('pytrends')
    pytrends.request = request
    with patch.dict(sys.modules, {'pytrends': pytrends, 'pytrends.request': request}):
        sys.modules.pop('trending_research', None)
        module = importlib.import_module('trending_research')
    sys.modules.pop('trending_research', None)
    return module


class TrendsLockTimeoutTests(unittest.TestCase):
    def test_web_requests_give_up_on_a_busy_lock(self):
        tr = import_trending_research()
        holding, release = threading.Event(), threading.Event()

        def hold():
            with tr._trends_lock:
                holding.set()
                release.wait(5)

        thread = threading.Thread(target=hold)
        thread.start()
        holding.wait(5)
        try:
            factory = Mock()
            with self.assertRaises(tr.TrendsBusyError):
                with tr.trends_session('id', client_factory=factory, lock_timeout=0.05):
                    pass
            factory.assert_not_called()
            with patch.object(tr, 'TrendReq', factory):
                result = tr.TrendingResearch().get_trending_topics('Keuangan', lock_timeout=0.05)
            self.assertEqual(result['status'], 'busy')
            self.assertEqual(result['related_top'], [])
        finally:
            release.set()
            thread.join(5)
        # The lock is released after a session, including one that raised.
        with tr.trends_session('id', client_factory=Mock(), lock_timeout=0.05):
            pass
        self.assertTrue(tr._trends_lock.acquire(timeout=0.05))
        tr._trends_lock.release()


class ResearchIndexTests(unittest.TestCase):
    def test_model_declares_the_migrated_index(self):
        index = next(i for i in ResearchData.__table__.indexes if i.name == 'idx_research_site_category_created')
        self.assertEqual([c.name for c in index.columns], ['site_id', 'category', 'created_at'])


if __name__ == '__main__':
    unittest.main()
