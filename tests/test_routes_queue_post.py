"""POST /api/queue/post/<id>: claim + credit reservation are atomic and recorded
on the row, so the job and the dispatcher sweep can settle it exactly once."""
import functools
import importlib
import logging
import sys
import types
import unittest
from unittest.mock import Mock, patch

from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Database
from models import Base, ContentQueue, User


def make_db():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    database = Database.__new__(Database)
    database.engine = engine
    database.session_factory = sessionmaker(bind=engine)
    return database


def load_queue_module(db, q):
    """Import routes.queue with its heavy dependencies stubbed out."""
    core = types.ModuleType('core_extensions')
    core.db = db
    core.q = q
    core.redis_conn = None
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


class QueuePostRouteTests(unittest.TestCase):
    def setUp(self):
        self.db = make_db()
        self.q = Mock()
        queue = load_queue_module(self.db, self.q)
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

    def test_success_reserves_and_records_reservation_with_job_id(self):
        self.seed(credits=2)
        resp = self.client.post('/api/queue/post/10')
        self.assertEqual(resp.status_code, 200)
        credits, status, job_id, held = self.state()
        self.assertEqual((credits, status, held), (1, 'posting', True))
        # The job is enqueued under the id recorded on the row.
        self.assertEqual(self.q.enqueue.call_args.kwargs['job_id'], job_id)
        self.assertTrue(self.q.enqueue.call_args.kwargs['credit_pre_reserved'])

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


if __name__ == '__main__':
    unittest.main()
