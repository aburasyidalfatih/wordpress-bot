"""POST /api/queue/post/<id>: claim + credit reservation are atomic and recorded
on the row, so the job and the dispatcher sweep can settle it exactly once."""
import functools
import importlib
import logging
import sys
import time
import types
import unittest
from unittest.mock import Mock, patch

from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Database
from models import Base, ContentQueue, PostLog, User, WordPressSite
from services import job_locks
from test_article_quality_support import LockRedis


def make_db():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    database = Database.__new__(Database)
    database.engine = engine
    database.session_factory = sessionmaker(bind=engine)
    return database


def load_queue_module(db, q, redis=None):
    """Import routes.queue with its heavy dependencies stubbed out."""
    core = types.ModuleType('core_extensions')
    core.db = db
    core.q = q
    core.redis_conn = redis
    core.logger = logging.getLogger('test-queue')
    core.load_config = lambda *a, **k: {}
    def as_user_1(f):
        @functools.wraps(f)
        def wrapper(*a, **k):
            return f(1, *a, **k)
        return wrapper
    core.require_jwt = as_user_1
    core.require_admin = core.require_jwt
    generator = types.ModuleType('services.article_generator')
    generator.ArticleGenerator = object
    stubs = {'core_extensions': core, 'services.article_generator': generator}
    with patch.dict(sys.modules, stubs):
        sys.modules.pop('routes.queue', None)
        module = importlib.import_module('routes.queue')
    sys.modules.pop('routes.queue', None)
    return module


class RouteTestCase(unittest.TestCase):
    def setUp(self):
        self.db = make_db()
        self.q = Mock()
        self.redis = LockRedis()
        queue = load_queue_module(self.db, self.q, self.redis)
        self.queue = queue
        app = Flask(__name__)
        app.register_blueprint(queue.queue_bp)
        self.client = app.test_client()

    def seed(self, credits):
        with self.db.get_session() as s:
            s.add(User(id=1, email='u@example.com', credits=credits))
            s.add(ContentQueue(id=10, user_id=1, title='T', category='C', status='pending'))

    def state(self):
        with self.db.get_session() as s:
            item = s.get(ContentQueue, 10)
            return s.get(User, 1).credits, item.status, item.job_id, item.credit_held


class QueuePostRouteTests(RouteTestCase):
    def test_success_reserves_and_records_reservation_with_job_id(self):
        self.seed(credits=2)
        resp = self.client.post('/api/queue/post/10')
        self.assertEqual(resp.status_code, 200)
        credits, status, job_id, held = self.state()
        self.assertEqual((credits, status, held), (1, 'posting', True))
        # The job is enqueued under the id recorded on the row.
        self.assertEqual(self.q.enqueue.call_args.kwargs['job_id'], job_id)
        self.assertTrue(self.q.enqueue.call_args.kwargs['credit_pre_reserved'])
        # Same timeout as the dispatcher's scheduled article jobs.
        self.assertEqual(self.q.enqueue.call_args.kwargs['job_timeout'], '45m')

    def test_second_click_is_rejected_without_charging(self):
        self.seed(credits=5)
        self.client.post('/api/queue/post/10')
        resp = self.client.post('/api/queue/post/10')
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(self.state()[0], 4)
        self.assertEqual(self.q.enqueue.call_count, 1)

    def test_insufficient_credit_leaves_item_untouched(self):
        self.seed(credits=0)
        resp = self.client.post('/api/queue/post/10')
        self.assertEqual(resp.status_code, 402)
        self.assertEqual(self.state(), (0, 'pending', None, False))
        self.q.enqueue.assert_not_called()

    def test_enqueue_failure_refunds_and_releases(self):
        self.seed(credits=1)
        self.q.enqueue.side_effect = RuntimeError('redis down')
        resp = self.client.post('/api/queue/post/10')
        self.assertEqual(resp.status_code, 500)
        self.assertEqual(self.state(), (1, 'pending', None, False))

    def test_regeneration_and_manual_post_use_the_article_job_timeout(self):
        self.seed(credits=3)
        with self.db.get_session() as s:
            s.add(PostLog(id=7, user_id=1, post_id=55, title='T', success=True, result='x'))
            s.add(WordPressSite(id=3, user_id=1, site_name='S', wordpress_url='https://example.com',
                                wordpress_username='admin'))
        resp = self.client.post('/api/queue/history/regenerate-article/7')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.q.enqueue.call_args.args[0], 'tasks.article_jobs.regenerate_article_job')
        self.assertEqual(self.q.enqueue.call_args.kwargs['job_timeout'], '45m')
        resp = self.client.post('/manual-post', json={'site_id': 3})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(self.q.enqueue.call_args.kwargs['manual'])
        self.assertEqual(self.q.enqueue.call_args.kwargs['job_timeout'], '45m')


class RegenerationLockTests(RouteTestCase):
    URL = '/api/queue/history/regenerate-article/7'
    KEY = 'regenerate_article_lock:7'

    def setUp(self):
        super().setUp()
        self.seed(credits=3)
        with self.db.get_session() as s:
            s.add(PostLog(id=7, user_id=1, post_id=55, title='T', success=True, result='x'))
        self.status = 'started'

        def fetch(job_id, connection=None):
            if self.status == 'missing':
                raise self.queue.NoSuchJobError(job_id)
            return Mock(**{'get_status.return_value': self.status})
        patcher = patch.object(self.queue, 'Job', Mock(fetch=Mock(side_effect=fetch)))
        patcher.start()
        self.addCleanup(patcher.stop)

    def credits(self):
        with self.db.get_session() as s:
            return s.get(User, 1).credits

    def holder(self):
        return job_locks.parse_lock_value(self.redis.get(self.KEY))

    def age_lock(self, seconds):
        owner, created = self.holder()
        self.redis.set(self.KEY, job_locks.lock_value(owner, now=created - seconds), ex=3600)

    def test_second_regeneration_while_one_runs_is_refused_without_charge(self):
        first = self.client.post(self.URL)
        self.assertEqual(first.status_code, 200)
        job_id = first.get_json()['job_id']
        self.assertEqual(self.q.enqueue.call_args.kwargs['job_id'], job_id)
        owner, created = self.holder()
        self.assertEqual(owner, job_id)
        self.assertAlmostEqual(created, time.time(), delta=5)
        self.assertGreater(self.redis.ttl(self.KEY), 45 * 60)
        self.age_lock(3600)  # long past the grace period: liveness decides
        second = self.client.post(self.URL)
        self.assertEqual(second.status_code, 409)
        self.assertEqual(second.get_json()['error'], 'Artikel ini sedang dibuat ulang. Tunggu hingga prosesnya selesai.')
        self.assertEqual(self.credits(), 2)  # charged once
        self.assertEqual(self.q.enqueue.call_count, 1)

    def test_fresh_lock_whose_job_is_not_in_rq_yet_counts_as_busy(self):
        # The first request has taken the lock but not enqueued its job yet.
        self.redis.set(self.KEY, job_locks.lock_value('regenerate-7-pending'), ex=3600)
        self.status = 'missing'
        resp = self.client.post(self.URL)
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(self.holder()[0], 'regenerate-7-pending')
        self.assertEqual(self.credits(), 3)
        self.q.enqueue.assert_not_called()

    def test_stale_lock_of_a_finished_or_vanished_job_is_taken_over_by_compare_and_set(self):
        with self.db.get_session() as s:
            s.get(User, 1).credits = 10
        for status in ('failed', 'missing'):
            self.client.post(self.URL)
            self.age_lock(job_locks.LOCK_GRACE_SECONDS + 1)
            self.status = status
            resp = self.client.post(self.URL)
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(self.holder()[0], resp.get_json()['job_id'])
            self.assertIn('cas', self.redis.scripts)
            self.status = 'started'
            self.redis.delete(self.KEY)

    def test_compare_and_set_loses_when_the_lock_changed_in_between(self):
        self.redis.set(self.KEY, job_locks.lock_value('old', now=time.time() - 3600), ex=3600)
        self.status = 'missing'
        real_get = self.redis.get

        def get_then_race(key):
            value = real_get(key)
            # Another request takes the stale lock right after this one read it.
            self.redis.data[key] = job_locks.lock_value('winner').encode()
            return value
        with patch.object(self.redis, 'get', get_then_race):
            resp = self.client.post(self.URL)
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(self.holder()[0], 'winner')

    def test_failed_reservation_or_enqueue_releases_the_lock(self):
        self.q.enqueue.side_effect = RuntimeError('redis down')
        self.assertEqual(self.client.post(self.URL).status_code, 500)
        self.assertIsNone(self.redis.get(self.KEY))
        self.assertEqual(self.credits(), 3)
        self.q.enqueue.side_effect = None
        with self.db.get_session() as s:
            s.get(User, 1).credits = 0
        self.assertEqual(self.client.post(self.URL).status_code, 402)
        self.assertIsNone(self.redis.get(self.KEY))

    def test_image_regeneration_is_not_locked(self):
        self.client.post('/api/queue/history/regenerate-image/7')
        self.client.post('/api/queue/history/regenerate-image/7')
        self.assertEqual(self.q.enqueue.call_count, 2)
        self.assertEqual(self.redis.data, {})

if __name__ == '__main__':
    unittest.main()
