"""Job locks (services.job_locks) and the per-site Search Console sync lock.

A lock value is "owner|epoch". A fresh lock counts as busy even when its job is
not in RQ yet; a stale one is taken over with an atomic compare-and-set.
"""
import time
import unittest
from unittest.mock import Mock, patch

from flask import Flask

from models import User, WordPressSite
from services import job_locks
from test_article_quality_support import LockRedis
from test_research_backend_support import load_with_stubbed_core, make_db

gsc_jobs, _gsc_core = load_with_stubbed_core('tasks.gsc_jobs')
gsc_routes, _route_core = load_with_stubbed_core('routes.search_console')


class ClaimLockTests(unittest.TestCase):
    def setUp(self):
        self.redis = LockRedis()
        self.alive = Mock(return_value=False)

    def claim(self, owner, now=None):
        return job_locks.claim_lock(self.redis, 'k', owner, 600, is_alive=self.alive, now=now)

    def test_free_lock_is_taken_with_owner_and_time(self):
        self.assertTrue(self.claim('a', now=1000))
        self.assertEqual(job_locks.parse_lock_value(self.redis.get('k')), ('a', 1000.0))

    def test_own_lock_is_refreshed_atomically(self):
        self.claim('a', now=1000)
        self.redis.expire('k', 5)
        self.assertTrue(self.claim('a', now=1010))
        self.assertEqual(self.redis.scripts, ['expire'])
        self.assertGreater(self.redis.ttl('k'), 500)

    def test_young_lock_is_busy_even_when_its_job_is_missing(self):
        self.claim('a', now=1000)
        self.assertFalse(self.claim('b', now=1000 + job_locks.LOCK_GRACE_SECONDS - 1))
        self.alive.assert_not_called()

    def test_old_lock_of_a_live_job_is_busy_and_of_a_dead_job_is_taken_over(self):
        self.claim('a', now=1000)
        self.alive.return_value = True
        self.assertFalse(self.claim('b', now=5000))
        self.alive.return_value = False
        self.assertTrue(self.claim('b', now=5000))
        self.assertEqual(job_locks.parse_lock_value(self.redis.get('k'))[0], 'b')
        self.assertIn('cas', self.redis.scripts)
        self.assertGreater(self.redis.ttl('k'), 500)  # set together with the value

    def test_release_only_by_the_owner(self):
        self.claim('a', now=1000)
        self.assertFalse(job_locks.release_lock(self.redis, 'k', 'b'))
        self.assertFalse(job_locks.release_lock(self.redis, 'k', 'a|'))
        self.assertTrue(job_locks.release_lock(self.redis, 'k', 'a'))
        self.assertIsNone(self.redis.get('k'))


class GscSyncJobLockTests(unittest.TestCase):
    KEY = 'gsc_sync_lock:2'

    def setUp(self):
        self.redis = LockRedis()
        self.sync = Mock(return_value={'rows_saved': 3})
        job = Mock(id='job-1', connection=self.redis)
        for p in (patch.object(gsc_jobs, '_current_job', lambda: job),
                  patch.object(gsc_jobs, '_sync_search_console', self.sync),
                  patch.object(gsc_jobs, 'rq_job_may_run', Mock(return_value=True))):
            p.start()
            self.addCleanup(p.stop)

    def test_sync_runs_under_the_lock_and_releases_it(self):
        self.assertEqual(gsc_jobs.sync_search_console_job(1, 2), {'rows_saved': 3})
        self.sync.assert_called_once_with(1, 2)
        self.assertIsNone(self.redis.get(self.KEY))

    def test_manual_sync_holds_the_lock_taken_by_the_route(self):
        self.redis.set(self.KEY, job_locks.lock_value('job-1'), ex=6 * 3600)
        seen = {}
        self.sync.side_effect = lambda *a: seen.update(ttl=self.redis.ttl(self.KEY)) or {}
        gsc_jobs.sync_search_console_job(1, 2)
        self.assertLessEqual(seen['ttl'], gsc_jobs.GSC_SYNC_LOCK_RUNNING_TTL_SECONDS)
        self.assertIsNone(self.redis.get(self.KEY))

    def test_overlapping_sync_is_skipped_quietly(self):
        self.redis.set(self.KEY, job_locks.lock_value('other-job'), ex=600)
        result = gsc_jobs.sync_search_console_job(1, 2)
        self.assertTrue(result['skipped'])
        self.sync.assert_not_called()
        self.assertTrue(self.redis.get(self.KEY).startswith(b'other-job|'))

    def test_lock_is_released_when_the_sync_fails(self):
        self.sync.side_effect = RuntimeError('google down')
        with self.assertRaises(RuntimeError):
            gsc_jobs.sync_search_console_job(1, 2)
        self.assertIsNone(self.redis.get(self.KEY))


class GscSyncRouteLockTests(unittest.TestCase):
    URL = '/api/search-console/sites/2/sync'
    KEY = 'gsc_sync_lock:2'

    def setUp(self):
        self.db = make_db()
        with self.db.get_session() as s:
            s.add(User(id=1, email='u@example.com', credits=1))
            s.add(WordPressSite(id=2, user_id=1, site_name='S', wordpress_url='https://example.com',
                                wordpress_username='admin', gsc_refresh_token='t',
                                gsc_property_url='sc-domain:example.com'))
        self.redis = LockRedis()
        self.q = Mock(**{'enqueue.side_effect': lambda *a, **k: Mock(id=k['job_id'])})
        self.alive = Mock(return_value=True)
        for p in (patch.object(gsc_routes, 'db', self.db), patch.object(gsc_routes, 'q', self.q),
                  patch.object(gsc_routes, 'redis_conn', self.redis),
                  patch.object(gsc_routes, 'rq_job_may_run', lambda conn, job_id: self.alive(job_id))):
            p.start()
            self.addCleanup(p.stop)
        app = Flask(__name__)
        app.register_blueprint(gsc_routes.search_console_bp)
        self.client = app.test_client()

    def test_second_manual_sync_is_refused_with_409(self):
        first = self.client.post(self.URL)
        self.assertEqual(first.status_code, 200)
        job_id = first.get_json()['job_id']
        self.assertEqual(job_locks.parse_lock_value(self.redis.get(self.KEY))[0], job_id)
        second = self.client.post(self.URL)
        self.assertEqual(second.status_code, 409)
        self.assertIn('sedang berjalan', second.get_json()['error'])
        self.assertEqual(self.q.enqueue.call_count, 1)

    def test_stale_lock_is_taken_over(self):
        self.redis.set(self.KEY, job_locks.lock_value('dead', now=time.time() - 3600), ex=600)
        self.alive.return_value = False
        self.assertEqual(self.client.post(self.URL).status_code, 200)

    def test_enqueue_failure_releases_the_lock(self):
        self.q.enqueue.side_effect = RuntimeError('redis down')
        self.assertEqual(self.client.post(self.URL).status_code, 500)
        self.assertIsNone(self.redis.get(self.KEY))


if __name__ == '__main__':
    unittest.main()
