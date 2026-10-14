"""Credit accounting and queue-item ownership in generate_and_post.

Runs against an in-memory SQLite database; core_extensions (Redis, Postgres,
Flask logging) is stubbed so the job module can be imported without services.
"""
import logging
import sys
import types
import unittest
from datetime import datetime
from unittest.mock import Mock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

if 'core_extensions' not in sys.modules:
    _stub = types.ModuleType('core_extensions')
    _stub.db = None
    _stub.logger = logging.getLogger('test_core_extensions')
    _stub.redis_conn = None
    _stub.trending = None
    for _name in ('load_config', 'send_telegram_notification', 'post_to_telegram_channel',
                  'post_to_facebook_page', 'post_to_twitter', 'post_to_threads',
                  'post_to_pinterest'):
        setattr(_stub, _name, Mock())
    sys.modules['core_extensions'] = _stub

from test_article_quality_support import quality_stub_patches  # noqa: E402
import tasks.article_jobs as jobs  # noqa: E402
from services.article_review import ReviewResult  # noqa: E402
from database import Database  # noqa: E402
from models import Base, ContentQueue, User, WordPressSite  # noqa: E402


def make_db():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    database = Database.__new__(Database)
    database.engine = engine
    database.session_factory = sessionmaker(bind=engine)
    return database


def good_article():
    return {'title': 'Panduan Lengkap', 'content': '<p>isi</p>', 'focus_keyword': 'panduan'}


class GenerateAndPostCreditTests(unittest.TestCase):
    def setUp(self):
        self.db = make_db()
        with self.db.get_session() as s:
            s.add(User(id=1, email='u@example.com', credits=10))
            s.add(WordPressSite(
                id=1, user_id=1, site_name='Site', wordpress_url='https://example.com',
                wordpress_username='admin', auto_post=True, language='id',
                categories=[{'id': 7, 'name': 'Keuangan'}, {'id': 8, 'name': 'Parenting'}],
                selected_categories=[{'id': 7, 'name': 'Keuangan'}, {'id': 8, 'name': 'Parenting'}],
            ))
            s.add(ContentQueue(id=5, user_id=1, site_id=1, category='Keuangan',
                               title='Cara menabung', status='posting',
                               posting_started_at=datetime.now()))

        self.generator = Mock()
        self.generator.generate_checked_article.return_value = good_article()
        self.generator.generate_image.return_value = None
        self.publisher = Mock()
        self.publisher.get_recent_posts.return_value = []
        self.publisher.create_post.return_value = (True, {'id': 99, 'link': 'https://example.com/p'})

        self.job = Mock(id='job-A', connection=None)
        patches = [
            patch.object(jobs, 'db', self.db),
            patch.object(jobs, 'load_config', Mock(return_value={'gemini_api_key': 'k'})),
            patch.object(jobs, 'ArticleGenerator', Mock(**{'from_config.return_value': self.generator})),
            patch.object(jobs, 'WordPressPublisher', Mock(return_value=self.publisher)),
            patch.object(jobs, 'check_article', Mock(return_value=(True, [], []))),
            patch.object(jobs, '_merge_topic_research', lambda seo, *a, **k: seo),
            patch.object(jobs, '_attach_search_evidence', lambda seo, *a, **k: seo),
            patch.object(jobs, '_current_job', lambda: self.job),
            patch.object(jobs, '_rq_job_is_alive', Mock(return_value=False)),
            patch.object(jobs, 'review_article', Mock(return_value=ReviewResult('approve', 'ok'))),
        ]
        patches += quality_stub_patches(jobs)
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        # Reservation done by the web app before enqueueing.
        self.assertTrue(self.db.reserve_user_credits(1, 1))

    def credits(self):
        with self.db.get_session() as s:
            return s.get(User, 1).credits

    def item(self):
        with self.db.get_session() as s:
            item = s.get(ContentQueue, 5)
            s.expunge(item)
            return item

    def test_success_consumes_credit_and_marks_posted(self):
        jobs.generate_and_post(1, item_id=5, credit_pre_reserved=True)
        self.assertEqual(self.credits(), 9)
        item = self.item()
        self.assertEqual(item.status, 'posted')
        self.assertEqual(item.post_url, 'https://example.com/p')
        self.assertFalse(item.credit_held)
        self.assertIsNone(item.job_id)

    def test_config_failure_before_main_work_refunds_and_fails_item(self):
        jobs.load_config.side_effect = ValueError('cannot decrypt')
        jobs.generate_and_post(1, item_id=5, credit_pre_reserved=True)
        self.assertEqual(self.credits(), 10)
        self.assertEqual(self.item().status, 'failed')
        self.assertFalse(self.item().credit_held)

    def test_generation_failure_refunds_exactly_once(self):
        self.generator.generate_checked_article.side_effect = RuntimeError('quota')
        jobs.generate_and_post(1, item_id=5, credit_pre_reserved=True)
        self.assertEqual(self.credits(), 10)
        self.assertEqual(self.item().status, 'failed')

    def test_failure_after_publish_does_not_refund(self):
        with patch.object(jobs.db, 'add_log', Mock(side_effect=RuntimeError('log down'))):
            jobs.generate_and_post(1, item_id=5, credit_pre_reserved=True)
        self.assertEqual(self.credits(), 9)
        self.assertEqual(self.item().status, 'posted')

    def test_wordpress_timeout_keeps_credit_and_does_not_retry_item(self):
        self.publisher.create_post.return_value = (False, 'TIMEOUT: WordPress did not confirm')
        jobs.generate_and_post(1, item_id=5, credit_pre_reserved=True)
        self.assertEqual(self.credits(), 9)
        self.assertEqual(self.item().status, 'failed')
        self.assertFalse(self.item().credit_held)

    def test_wordpress_rejection_refunds(self):
        self.publisher.create_post.return_value = (False, '{"code":"rest_cannot_create"}')
        jobs.generate_and_post(1, item_id=5, credit_pre_reserved=True)
        self.assertEqual(self.credits(), 10)
        self.assertEqual(self.item().status, 'failed')

    def test_missing_item_refunds_pre_reserved_credit(self):
        jobs.generate_and_post(1, item_id=404, credit_pre_reserved=True)
        self.assertEqual(self.credits(), 10)
        self.generator.generate_checked_article.assert_not_called()

    def test_already_posted_item_refunds_and_is_untouched(self):
        with self.db.get_session() as s:
            s.get(ContentQueue, 5).status = 'posted'
        jobs.generate_and_post(1, item_id=5, credit_pre_reserved=True)
        self.assertEqual(self.credits(), 10)
        self.assertEqual(self.item().status, 'posted')

    def test_duplicate_job_backs_off_when_owner_is_alive(self):
        with self.db.get_session() as s:
            item = s.get(ContentQueue, 5)
            item.job_id = 'job-OTHER'
            item.credit_held = True
        jobs._rq_job_is_alive.return_value = True
        jobs.generate_and_post(1, item_id=5, credit_pre_reserved=True)
        # This job's own reservation is refunded; the owner's is untouched.
        self.assertEqual(self.credits(), 10)
        item = self.item()
        self.assertEqual(item.job_id, 'job-OTHER')
        self.assertTrue(item.credit_held)
        self.generator.generate_checked_article.assert_not_called()

    def test_takeover_from_dead_job_refunds_its_unsettled_credit(self):
        with self.db.get_session() as s:
            item = s.get(ContentQueue, 5)
            item.job_id = 'job-DEAD'
            item.credit_held = True
        jobs.generate_and_post(1, item_id=5, credit_pre_reserved=True)
        # Dead attempt refunded (+1), this attempt consumed: net 10.
        self.assertEqual(self.credits(), 10)
        self.assertEqual(self.item().status, 'posted')

    def test_scheduler_item_with_no_credit_goes_back_to_pending(self):
        with self.db.get_session() as s:
            s.get(User, 1).credits = 0
            s.get(ContentQueue, 5).job_id = 'job-A'
        jobs.generate_and_post(1, item_id=5, site_id=1)
        self.assertEqual(self.credits(), 0)
        item = self.item()
        self.assertEqual(item.status, 'pending')
        self.assertIsNone(item.job_id)
        self.generator.generate_checked_article.assert_not_called()

    def test_scheduler_item_reserves_and_consumes_once(self):
        self.db.refund_user_credits(1, 1)  # undo the web-app reservation from setUp
        jobs.generate_and_post(1, item_id=5, site_id=1)
        self.assertEqual(self.credits(), 9)
        self.assertEqual(self.item().status, 'posted')

    def test_manual_post_bypasses_auto_post_switch(self):
        with self.db.get_session() as s:
            s.get(WordPressSite, 1).auto_post = False
        jobs.generate_and_post(1, site_id=1, credit_pre_reserved=True, manual=True)
        self.assertEqual(self.credits(), 9)
        self.publisher.create_post.assert_called_once()

    def test_scheduled_post_with_auto_post_off_refunds(self):
        with self.db.get_session() as s:
            s.get(WordPressSite, 1).auto_post = False
        jobs.generate_and_post(1, site_id=1, credit_pre_reserved=True)
        self.assertEqual(self.credits(), 10)
        self.publisher.create_post.assert_not_called()

    def test_manual_post_still_requires_categories(self):
        with self.db.get_session() as s:
            s.get(WordPressSite, 1).selected_categories = []
        jobs.generate_and_post(1, site_id=1, credit_pre_reserved=True, manual=True)
        self.assertEqual(self.credits(), 10)
        self.publisher.create_post.assert_not_called()

    def test_category_post_rotates_under_lock(self):
        jobs.generate_and_post(1, site_id=1, credit_pre_reserved=True, manual=True)
        with self.db.get_session() as s:
            names = [c['name'] for c in s.get(WordPressSite, 1).selected_categories]
        self.assertEqual(names, ['Parenting', 'Keuangan'])
        self.assertEqual(self.publisher.create_post.call_args.args[2], 7)


class QueueItemSettlementTests(unittest.TestCase):
    def setUp(self):
        self.db = make_db()
        with self.db.get_session() as s:
            s.add(User(id=1, email='u@example.com', credits=0))
            s.add(ContentQueue(id=5, user_id=1, status='posting', job_id='job-A', credit_held=True))
        p = patch.object(jobs, 'db', self.db)
        p.start()
        self.addCleanup(p.stop)

    def credits(self):
        with self.db.get_session() as s:
            return s.get(User, 1).credits

    def test_refund_happens_once(self):
        self.assertTrue(jobs._settle_queue_item(1, 5, 'job-A', status='failed', refund=True))
        self.assertFalse(jobs._settle_queue_item(1, 5, 'job-A', status='failed', refund=True))
        self.assertEqual(self.credits(), 1)

    def test_item_taken_over_is_left_alone(self):
        with self.db.get_session() as s:
            item = s.get(ContentQueue, 5)
            item.job_id = None          # reset by the dispatcher sweep, which refunded
            item.credit_held = False
            item.status = 'pending'
        self.assertFalse(jobs._settle_queue_item(1, 5, 'job-A', status='failed', refund=True))
        self.assertEqual(self.credits(), 0)
        with self.db.get_session() as s:
            self.assertEqual(s.get(ContentQueue, 5).status, 'pending')


class IntentTests(unittest.TestCase):
    def test_category_names_default_to_informational(self):
        from services.content_planner import classify_intent, intent_guidance
        self.assertEqual(classify_intent('Keuangan'), 'informational')
        self.assertEqual(classify_intent('Parenting Anak'), 'informational')
        self.assertEqual(classify_intent('bca mobile', allow_navigational=True), 'navigational')
        self.assertNotIn('bertele-tele', intent_guidance('navigational', 'id'))
        self.assertTrue(intent_guidance('informational', 'en').startswith('The reader'))

    def test_attach_search_evidence_uses_topic_and_language(self):
        database = make_db()
        with patch.object(jobs, 'db', database):
            data = jobs._attach_search_evidence({}, 1, 1, 'Finance', topic=None, language='en')
            self.assertEqual(data['intent'], 'informational')
            self.assertTrue(data['intent_guidance'].startswith('The reader'))
            data = jobs._attach_search_evidence({}, 1, 1, 'Finance',
                                                topic='best savings account', language='en')
            self.assertEqual(data['intent'], 'commercial')


if __name__ == '__main__':
    unittest.main()
