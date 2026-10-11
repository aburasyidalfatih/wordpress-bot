"""Dispatcher stuck-item recovery, WordPress create_post safety, Gemini retry policy
and migration bookkeeping."""
import sys
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import requests
from google import genai
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Database
from models import Base, ContentQueue, ResearchData, User

with patch('database.Database', Mock()):
    sys.modules.pop('dispatcher', None)
    import dispatcher  # noqa: E402

from services import wp_publisher  # noqa: E402
from services.wp_publisher import WordPressPublisher, is_unconfirmed_post_result  # noqa: E402
from services.article_generator import ArticleGenerator, is_retryable_genai_error  # noqa: E402


def make_db():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    database = Database.__new__(Database)
    database.engine = engine
    database.session_factory = sessionmaker(bind=engine)
    return database


class StuckQueueSweepTests(unittest.TestCase):
    def setUp(self):
        self.db = make_db()
        old = datetime.now() - timedelta(hours=3)
        with self.db.get_session() as s:
            s.add(User(id=1, email='u@example.com', credits=0))
            # job died holding a credit
            s.add(ContentQueue(id=1, user_id=1, status='posting', posting_started_at=old,
                               job_id='dead-1', credit_held=True))
            # scheduler item whose job died before reserving
            s.add(ContentQueue(id=2, user_id=1, status='posting', posting_started_at=old,
                               job_id='dead-2', credit_held=False))
            # job still running
            s.add(ContentQueue(id=3, user_id=1, status='posting', posting_started_at=old,
                               job_id='alive-3', credit_held=True))
            # web app reserved (records job id + credit_held), job never ran and is gone
            s.add(ContentQueue(id=4, user_id=1, status='posting', posting_started_at=old,
                               job_id='queue-post-4-dead', credit_held=True))
            # left 'posting' by older code: no job id, no recorded reservation
            s.add(ContentQueue(id=5, user_id=1, status='posting', posting_started_at=old))
            # legacy row whose job is still queued
            s.add(ContentQueue(id=7, user_id=1, status='posting', posting_started_at=old))
            # recently started: inside the grace period
            s.add(ContentQueue(id=6, user_id=1, status='posting', posting_started_at=datetime.now(),
                               job_id='dead-6', credit_held=True))
        patches = [
            patch.object(dispatcher, 'db', self.db),
            patch.object(dispatcher, 'StartedJobRegistry', MagicMock()),
            patch.object(dispatcher, '_job_is_alive', lambda job_id: job_id.startswith('alive')),
            patch.object(dispatcher, '_items_with_live_unclaimed_jobs', lambda: {7}),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def rows(self):
        with self.db.get_session() as s:
            return {i.id: (i.status, i.job_id, i.credit_held) for i in s.query(ContentQueue).all()}

    def test_sweep_refunds_only_unsettled_reservations(self):
        dispatcher.reset_stuck_queue_items()
        rows = self.rows()
        self.assertEqual(rows[1], ('pending', None, False))
        self.assertEqual(rows[2], ('pending', None, False))
        self.assertEqual(rows[3], ('posting', 'alive-3', True))
        self.assertEqual(rows[4], ('pending', None, False))
        self.assertEqual(rows[5], ('pending', None, False))
        self.assertEqual(rows[6][0], 'posting')
        self.assertEqual(rows[7][0], 'posting')
        with self.db.get_session() as s:
            # item 1 (job died holding) + item 4 (web-app reservation, never claimed);
            # legacy item 5 is reset without a refund.
            self.assertEqual(s.get(User, 1).credits, 2)

    def test_second_sweep_does_not_refund_again(self):
        dispatcher.reset_stuck_queue_items()
        dispatcher.reset_stuck_queue_items()
        with self.db.get_session() as s:
            self.assertEqual(s.get(User, 1).credits, 2)

    def test_job_timeout_is_25_minutes(self):
        self.assertEqual(dispatcher.GENERATE_AND_POST_JOB_TIMEOUT, '25m')


def response(status, body=None, headers=None):
    resp = Mock(status_code=status, headers=headers or {}, text=str(body), is_redirect=False)
    resp.json.return_value = body
    return resp


class CreatePostTests(unittest.TestCase):
    def setUp(self):
        p = patch.object(wp_publisher, '_validate_url', lambda url: (True, url.rstrip('/')))
        p.start()
        self.addCleanup(p.stop)
        sleep = patch('time.sleep')
        sleep.start()
        self.addCleanup(sleep.stop)
        self.publisher = WordPressPublisher('https://example.com', 'admin', 'pw')

    def posts_calls(self, mock_request):
        return [c for c in mock_request.call_args_list if c.args[0] == 'POST']

    def test_read_timeout_is_not_retried_and_finds_created_post(self):
        now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
        found = {'id': 12, 'link': 'https://example.com/p', 'slug': 'judul-artikel',
                 'title': {'raw': 'Judul Artikel'}, 'date_gmt': now}

        def fake(method, url, **kwargs):
            if method == 'POST':
                raise requests.exceptions.ReadTimeout('read timed out')
            return response(200, [found])

        with patch.object(wp_publisher.requests, 'request', side_effect=fake) as req:
            ok, result = self.publisher.create_post('Judul Artikel', '<p>x</p>')
        self.assertTrue(ok)
        self.assertEqual(result['id'], 12)
        self.assertEqual(len(self.posts_calls(req)), 1)

    def test_gateway_timeout_without_match_returns_timeout_marker(self):
        old = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=30)).isoformat()
        older_same_title = {'id': 3, 'slug': 'judul-artikel', 'title': {'raw': 'Judul Artikel'},
                            'date_gmt': old}

        def fake(method, url, **kwargs):
            if method == 'POST':
                return response(504, 'Gateway Timeout')
            return response(200, [older_same_title])

        with patch.object(wp_publisher.requests, 'request', side_effect=fake) as req:
            ok, result = self.publisher.create_post('Judul Artikel', '<p>x</p>')
        self.assertFalse(ok)
        self.assertTrue(is_unconfirmed_post_result(result))
        self.assertEqual(len(self.posts_calls(req)), 1)

    def test_connect_failure_is_retried_and_not_marked_unconfirmed(self):
        with patch.object(wp_publisher.requests, 'request',
                          side_effect=requests.exceptions.ConnectTimeout('connect timeout=60')) as req:
            ok, result = self.publisher.create_post('Judul', '<p>x</p>')
        self.assertFalse(ok)
        self.assertFalse(is_unconfirmed_post_result(result))
        self.assertEqual(len(self.posts_calls(req)), 3)

    def test_marker_check_is_case_insensitive(self):
        self.assertTrue(is_unconfirmed_post_result('timeout: unknown'))
        self.assertFalse(is_unconfirmed_post_result('rest_cannot_create'))
        self.assertFalse(is_unconfirmed_post_result({'id': 1}))

    def test_get_posts_requests_edit_context(self):
        with patch.object(wp_publisher.requests, 'request',
                          return_value=response(200, [], {'X-WP-TotalPages': '1'})) as req:
            self.publisher.get_posts(page=1, context='edit')
        self.assertEqual(req.call_args.kwargs['params']['context'], 'edit')
        self.assertFalse(req.call_args.kwargs['allow_redirects'])


class UrlSafetyTests(unittest.TestCase):
    def test_unsafe_base_url_makes_no_request(self):
        with patch.object(wp_publisher, '_validate_url', return_value=(False, 'internal')), \
                patch.object(wp_publisher.requests, 'request') as req:
            publisher = WordPressPublisher('http://redis:6379', 'a', 'b')
            self.assertEqual(publisher.create_post('t', '<p>c</p>')[0], False)
            self.assertEqual(publisher.get_posts(), (False, 'Refusing to contact WordPress site: internal', 0))
            self.assertEqual(publisher.get_recent_posts(), [])
        req.assert_not_called()

    def test_redirect_to_internal_host_is_refused(self):
        def validate(url):
            return (False, 'internal') if '169.254' in url else (True, url.rstrip('/'))

        redirect = response(301, '', {'Location': 'http://169.254.169.254/latest'})
        redirect.is_redirect = True
        with patch.object(wp_publisher, '_validate_url', side_effect=validate), \
                patch.object(wp_publisher.requests, 'request', return_value=redirect) as req:
            publisher = WordPressPublisher('https://example.com', 'a', 'b')
            self.assertEqual(publisher.get_recent_posts(), [])
        self.assertEqual(req.call_count, 1)


def client_error(code):
    return genai.errors.ClientError(code, {'error': {'message': 'x', 'status': 'X'}})


class GeminiRetryPolicyTests(unittest.TestCase):
    def test_retry_policy(self):
        self.assertFalse(is_retryable_genai_error(client_error(400)))
        self.assertFalse(is_retryable_genai_error(client_error(403)))
        self.assertTrue(is_retryable_genai_error(client_error(429)))
        self.assertTrue(is_retryable_genai_error(
            genai.errors.ServerError(503, {'error': {'message': 'x', 'status': 'X'}})))

    def test_invalid_key_is_not_retried(self):
        generator = ArticleGenerator.__new__(ArticleGenerator)
        generator.model = 'm'
        generator.client = SimpleNamespace(models=SimpleNamespace(
            generate_content=Mock(side_effect=client_error(401))))
        with self.assertRaises(genai.errors.ClientError):
            generator.generate_article('Sekolah')
        self.assertEqual(generator.client.models.generate_content.call_count, 1)

    def test_image_permission_error_stops_after_one_attempt(self):
        generator = ArticleGenerator.__new__(ArticleGenerator)
        generator.image_model = 'gemini-image'
        generator.client = SimpleNamespace(models=SimpleNamespace(
            generate_content=Mock(side_effect=client_error(403))))
        with self.assertRaises(Exception):
            generator.generate_image('Sekolah', 'Judul')
        self.assertEqual(generator.client.models.generate_content.call_count, 1)


class MigrationBookkeepingTests(unittest.TestCase):
    def make(self, failing=None):
        database = Database.__new__(Database)
        for name in ('migrate_plain_configs', 'migrate_add_timezone_column',
                     'migrate_add_language_column', 'migrate_add_posting_started_at_column',
                     'migrate_add_queue_job_columns', 'migrate_research_quality_columns',
                     'migrate_search_console_foundation', 'migrate_credit_system_tables',
                     'migrate_add_foreign_keys'):
            setattr(database, name, Mock(side_effect=RuntimeError('boom') if name == failing else None))
        return database

    def test_failure_is_reported_and_later_steps_still_run(self):
        database = self.make(failing='migrate_add_language_column')
        self.assertFalse(database._run_migrations_locked())
        database.migrate_add_foreign_keys.assert_called_once()

    def test_schema_version_only_recorded_on_success(self):
        for failing, recorded in ((None, True), ('migrate_add_foreign_keys', False)):
            database = self.make(failing=failing)
            conn = MagicMock()
            conn.execute.return_value.scalar.return_value = True
            database.engine = Mock(connect=Mock(return_value=conn))
            database._schema_version_matches = Mock(return_value=False)
            database._record_schema_version = Mock()
            database.run_migrations()
            self.assertEqual(database._record_schema_version.called, recorded)


class UnusedResearchTopicTests(unittest.TestCase):
    def test_empty_newest_row_does_not_hide_older_topics(self):
        database = make_db()
        now = datetime.now()
        with database.get_session() as s:
            s.add(ResearchData(id=1, user_id=1, site_id=1, category='Keuangan',
                               suggested_topics=[{'topic': 'Cara menabung'}, 'Investasi emas'],
                               confidence_level='high', researched_at=now,
                               created_at=now - timedelta(hours=2), used=False))
            s.add(ResearchData(id=2, user_id=1, site_id=1, category='Keuangan',
                               suggested_topics=[], confidence_level='high', researched_at=now,
                               created_at=now, used=False))
        self.assertEqual(database.get_unused_research_topic(1, 1, 'Keuangan'), 'Cara menabung')
        with database.get_session() as s:
            self.assertTrue(s.get(ResearchData, 2).used)
            self.assertEqual(s.get(ResearchData, 1).suggested_topics, ['Investasi emas'])
        self.assertEqual(database.get_unused_research_topic(1, 1, 'Keuangan'), 'Investasi emas')
        self.assertIsNone(database.get_unused_research_topic(1, 1, 'Keuangan'))


if __name__ == '__main__':
    unittest.main()
