"""Pipeline steps extracted from generate_and_post, the regeneration jobs and
the dispatcher's auto-post scheduling.

Runs against an in-memory SQLite database; core_extensions (Redis, Postgres,
Flask logging) is stubbed so the job modules import without services.
"""
import logging
import sys
import types
import unittest
from datetime import datetime
from io import BytesIO
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

from test_article_quality_support import PASSING_NOTE, quality_stub_patches  # noqa: E402
import tasks.article_jobs as jobs
from services.article_review import ReviewResult
from database import Database
from models import Base, ContentQueue, PostLog, User, WordPressSite

with patch('database.Database', Mock()):
    sys.modules.pop('dispatcher', None)
    import dispatcher


def make_db():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    database = Database.__new__(Database)
    database.engine = engine
    database.session_factory = sessionmaker(bind=engine)
    return database


class CategoryLookupTests(unittest.TestCase):
    CONFIG = {'categories': [{'id': 7, 'name': 'Keuangan', 'description': 'Uang'},
                             {'id': 9, 'name': 'Tips &amp; Trik'},
                             {'id': 11, 'name': 'Kepemimpinan'}]}

    def test_item_category_is_resolved_by_name(self):
        self.assertEqual(jobs._category_for_item(self.CONFIG, 'Keuangan'), {'name': 'Keuangan', 'id': 7})
        # Case, spacing and HTML entities do not matter.
        self.assertEqual(jobs._category_for_item(self.CONFIG, ' keuangan ')['id'], 7)
        self.assertEqual(jobs._category_for_item(self.CONFIG, 'Tips & Trik')['id'], 9)
        # A clearly closest name (a typo) still matches; the item keeps its own name.
        self.assertEqual(jobs._category_for_item(self.CONFIG, 'Kepemimpinann'), {'name': 'Kepemimpinann', 'id': 11})
        # Selected categories count too.
        config = {'categories': [], 'selected_categories': [{'id': 4, 'name': 'Berita'}]}
        self.assertEqual(jobs._category_for_item(config, 'Berita')['id'], 4)

    def test_unknown_category_fails_instead_of_wordpress_default(self):
        # Used to fall back to WordPress category 1 (the site default), which
        # filed off-topic posts under an unrelated category.
        for config in (self.CONFIG, {'categories': None}):
            with self.assertRaises(jobs.CategoryNotFound) as ctx:
                jobs._category_for_item(config, 'Digitalisasi Pendidikan')
            self.assertIn("Kategori 'Digitalisasi Pendidikan' tidak ditemukan", str(ctx.exception))
        # A neighbouring name is not "close enough".
        with self.assertRaises(jobs.CategoryNotFound):
            jobs._category_for_item({'categories': [{'id': 3, 'name': 'Keuangan Sekolah'}]}, 'Keuangan Keluarga')

    def test_live_wordpress_categories_are_checked_when_stored_ones_miss(self):
        publisher = Mock()
        publisher.get_categories.return_value = [{'id': 21, 'name': 'Digitalisasi Pendidikan'}]
        self.assertEqual(jobs._category_for_item(self.CONFIG, 'Digitalisasi Pendidikan', publisher)['id'], 21)
        publisher.get_categories.side_effect = RuntimeError('down')
        with self.assertRaises(jobs.CategoryNotFound):
            jobs._category_for_item(self.CONFIG, 'Digitalisasi Pendidikan', publisher)
        # Not fetched when the stored list already has it.
        publisher.get_categories.reset_mock()
        jobs._category_for_item(self.CONFIG, 'Keuangan', publisher)
        publisher.get_categories.assert_not_called()

    def test_category_description(self):
        config = {'categories': [{'id': 7, 'name': 'Keuangan', 'description': 'Uang'}]}
        self.assertEqual(jobs._category_description(config, 'Keuangan'), 'Uang')
        self.assertEqual(jobs._category_description(config, 'Lain'), '')
        self.assertEqual(jobs._category_description({'categories': None}, 'Lain'), '')

    def test_public_description_drops_writing_notes_and_hint_is_private(self):
        config = {'categories': [{
            'id': 7, 'name': 'Digitalisasi Pendidikan',
            'description': ('Artikel seputar transformasi digital sekolah. (Fokus Tambahan: Gunakan frasa eksak '
                            '"digitalisasi pendidikan" / Selalu gunakan angka tahun 2026 (wajib) di judul)'),
            'ai_hint': 'Sasar kepala sekolah SMA swasta.',
        }]}
        self.assertEqual(jobs._category_description(config, 'Digitalisasi Pendidikan'),
                         'Artikel seputar transformasi digital sekolah.')
        self.assertEqual(jobs._category_hint(config, 'Digitalisasi Pendidikan'), 'Sasar kepala sekolah SMA swasta.')
        # By id when the name changed in WordPress since.
        self.assertEqual(jobs._category_hint(config, 'Nama Lama', 7), 'Sasar kepala sekolah SMA swasta.')
        self.assertEqual(jobs._category_hint(config, 'Lain'), '')


class QueueItemCategoryFailureTests(unittest.TestCase):
    """A queue item whose category is unknown fails before any generation, refunded."""

    def setUp(self):
        self.db = make_db()
        with self.db.get_session() as s:
            s.add(User(id=1, email='u@example.com', credits=10))
            s.add(WordPressSite(id=1, user_id=1, site_name='Site', wordpress_url='https://example.com',
                                wordpress_username='admin', language='id',
                                categories=[{'id': 7, 'name': 'Keuangan'}]))
            s.add(ContentQueue(id=5, user_id=1, site_id=1, title='Cara menabung', category='Hilang',
                               status='posting', credit_held=True, created_at=datetime.now()))
        self.generator = Mock()
        self.publisher = Mock()
        self.publisher.get_recent_posts.return_value = []
        self.publisher.get_categories.return_value = [{'id': 7, 'name': 'Keuangan'}]
        patches = [
            patch.object(jobs, 'db', self.db),
            patch.object(jobs, 'load_config', Mock(return_value={'gemini_api_key': 'k'})),
            patch.object(jobs, 'ArticleGenerator', Mock(**{'from_config.return_value': self.generator})),
            patch.object(jobs, 'WordPressPublisher', Mock(return_value=self.publisher)),
            patch.object(jobs, '_current_job', lambda: None),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_unknown_category_fails_the_item_and_refunds(self):
        jobs.generate_and_post(1, item_id=5, site_id=1, credit_pre_reserved=True)
        self.generator.generate_checked_article.assert_not_called()
        self.publisher.create_post.assert_not_called()
        with self.db.get_session() as s:
            item = s.get(ContentQueue, 5)
            self.assertEqual(item.status, 'failed')
            self.assertFalse(item.credit_held)
            self.assertEqual(s.get(User, 1).credits, 11)  # the held credit came back
            log = s.query(PostLog).one()
            self.assertFalse(log.success)
            self.assertTrue(log.result.startswith("Artikel tidak diterbitkan: Kategori 'Hilang' tidak ditemukan"))


class GenerateAndPostTitleRetryTests(unittest.TestCase):
    def setUp(self):
        self.db = make_db()
        with self.db.get_session() as s:
            s.add(User(id=1, email='u@example.com', credits=10))
            s.add(WordPressSite(
                id=1, user_id=1, site_name='Site', wordpress_url='https://example.com',
                wordpress_username='admin', auto_post=True, language='id',
                categories=[{'id': 7, 'name': 'Keuangan'}],
                selected_categories=[{'id': 7, 'name': 'Keuangan'}],
            ))
        self.generator = Mock()
        self.generator.generate_checked_article.side_effect = [
            {'title': 'Tips Menabung', 'content': '<p>a</p>'},
            {'title': 'Strategi Investasi Emas', 'content': '<p>b</p>'},
        ]
        self.generator.generate_image.return_value = None
        self.publisher = Mock()
        self.publisher.get_recent_posts.return_value = []
        self.publisher.create_post.return_value = (True, {'id': 1, 'link': 'https://example.com/p'})
        patches = [
            patch.object(jobs, 'db', self.db),
            patch.object(jobs, 'load_config', Mock(return_value={'gemini_api_key': 'k'})),
            patch.object(jobs, 'ArticleGenerator', Mock(**{'from_config.return_value': self.generator})),
            patch.object(jobs, 'WordPressPublisher', Mock(return_value=self.publisher)),
            patch.object(jobs, 'check_article', Mock(return_value=(True, [], []))),
            patch.object(jobs, '_merge_topic_research', lambda seo, *a, **k: seo),
            patch.object(jobs, '_attach_search_evidence', lambda seo, *a, **k: seo),
            patch.object(jobs, '_current_job', lambda: None),
            patch.object(jobs, 'review_article', Mock(return_value=ReviewResult('approve', 'ok'))),
        ]
        patches += quality_stub_patches(jobs)
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.db.get_existing_titles = Mock(return_value=['Tips Menabung'])
        self.db.get_unused_research_topic = Mock(return_value=None)

    def test_duplicate_title_is_regenerated_with_avoid_similar(self):
        jobs.generate_and_post(1, site_id=1, credit_pre_reserved=True, manual=True)
        calls = self.generator.generate_checked_article.call_args_list
        self.assertEqual(len(calls), 2)
        self.assertNotIn('avoid_similar', calls[0].kwargs)
        self.assertTrue(calls[1].kwargs['avoid_similar'])
        self.assertEqual(self.publisher.create_post.call_args.args[0], 'Strategi Investasi Emas')
        with self.db.get_session() as s:
            log = s.query(PostLog).one()
            self.assertTrue(log.success)
            self.assertEqual(log.result, jobs.RESULT_PUBLISHED_NO_IMAGE + f' {PASSING_NOTE} Ditinjau AI: disetujui tanpa perbaikan isi.')
            self.assertEqual(s.get(User, 1).credits, 10)  # pre-reserved by the caller, consumed

    def test_failure_history_is_in_indonesian(self):
        self.generator.generate_checked_article.side_effect = RuntimeError('quota')
        jobs.generate_and_post(1, site_id=1, credit_pre_reserved=True, manual=True)
        with self.db.get_session() as s:
            log = s.query(PostLog).one()
            self.assertFalse(log.success)
            self.assertTrue(log.title.startswith('GAGAL: '))
            self.assertEqual(log.result, 'Sistem Berhenti Tiba-tiba: quota')
            self.assertEqual(s.get(User, 1).credits, 11)  # refunded the caller's reservation


class PublishWiringTests(unittest.TestCase):
    """What the job hands the writer, the brief, the reviewer and the publisher."""

    SEO = {'official_sources': [{'title': 'Emergency savings', 'url': 'https://www.consumerfinance.gov/es/',
                                 'passages': ['Save a little each payday.']}],
           'competitor_outlines': [{'title': 'Blog', 'url': 'https://blog.other.org/fund'}]}

    def setUp(self):
        self.db = make_db()
        with self.db.get_session() as s:
            s.add(User(id=1, email='u@example.com', credits=10))
            s.add(WordPressSite(
                id=1, user_id=1, site_name='Site', wordpress_url='https://example.com',
                wordpress_username='admin', auto_post=True, language='en',
                categories=[{'id': 7, 'name': 'Emergency Fund',
                             'description': 'Saving for surprises. (Fokus Tambahan: always write 2026)',
                             'ai_hint': 'Readers are dual-income parents.'}],
                selected_categories=[{'id': 7, 'name': 'Emergency Fund'}],
            ))
        self.generator = Mock()
        self.generator.generate_checked_article.return_value = {
            'title': 'Where to Keep an Emergency Fund Safely', 'content': '<p>a</p>',
            'focus_keyword': 'emergency fund'}
        self.generator.generate_image.return_value = BytesIO(b'img')
        self.publisher = Mock()
        self.publisher.get_recent_posts.return_value = []
        self.publisher.upload_image.return_value = 31
        self.publisher.create_post.return_value = (True, {'id': 1, 'link': 'https://example.com/p'})
        self.review = Mock(return_value=ReviewResult('approve', 'ok'))
        patches = [
            patch.object(jobs, 'db', self.db),
            patch.object(jobs, 'load_config', Mock(return_value={'gemini_api_key': 'k'})),
            patch.object(jobs, 'ArticleGenerator', Mock(**{'from_config.return_value': self.generator})),
            patch.object(jobs, 'WordPressPublisher', Mock(return_value=self.publisher)),
            patch.object(jobs, 'check_article', Mock(return_value=(True, [], []))),
            patch.object(jobs, '_load_category_research', Mock(return_value=dict(self.SEO))),
            patch.object(jobs, '_merge_topic_research', lambda seo, *a, **k: seo),
            patch.object(jobs, '_attach_search_evidence', lambda seo, *a, **k: seo),
            patch.object(jobs, '_current_job', lambda: None),
            patch.object(jobs, 'review_article', self.review),
        ]
        patches += quality_stub_patches(jobs)
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.db.get_existing_titles = Mock(return_value=[])
        self.db.get_unused_research_topic = Mock(return_value=None)

    def test_publish_gets_category_sources_and_slugged_image(self):
        jobs.generate_and_post(1, site_id=1, credit_pre_reserved=True, manual=True)
        kwargs = self.publisher.create_post.call_args.kwargs
        self.assertEqual(kwargs['category_name'], 'Emergency Fund')
        self.assertEqual([s['url'] for s in kwargs['citable_sources']],
                         ['https://www.consumerfinance.gov/es/', 'https://blog.other.org/fund'])
        self.assertEqual(self.publisher.create_post.call_args.args[2], 7)
        # The image file is named after the slug the post will get.
        self.assertEqual(self.publisher.upload_image.call_args.kwargs['slug'],
                         jobs.make_post_slug('Where to Keep an Emergency Fund Safely', 'emergency fund',
                                             'Emergency Fund'))

    def test_private_hint_reaches_writer_brief_and_reviewer_but_public_notes_do_not(self):
        jobs.generate_and_post(1, site_id=1, credit_pre_reserved=True, manual=True)
        writer = self.generator.generate_checked_article.call_args.kwargs
        self.assertEqual(writer['category_desc'], 'Saving for surprises.')
        self.assertEqual(writer['category_hint'], 'Readers are dual-income parents.')
        brief = jobs.build_content_brief.call_args.kwargs
        self.assertEqual(brief['category_description'], 'Saving for surprises.')
        self.assertEqual(brief['category_hint'], 'Readers are dual-income parents.')
        context = self.review.call_args.kwargs['publisher_context']
        self.assertIn('Readers are dual-income parents.', context)
        self.assertNotIn('Fokus Tambahan', context)


class RegenerationJobTests(unittest.TestCase):
    def setUp(self):
        self.db = make_db()
        with self.db.get_session() as s:
            s.add(User(id=1, email='u@example.com', credits=4))
            s.add(WordPressSite(id=1, user_id=1, site_name='Site', wordpress_url='https://example.com',
                                wordpress_username='admin', language='id', is_active=True))
            s.add(PostLog(id=10, user_id=1, site_id=1, post_id=55, title='Judul Lama',
                          category_name='Keuangan', success=True, result='x', image_failed=True))
        self.generator = Mock()
        self.generator.generate_checked_article.return_value = {
            'title': 'Judul Baru', 'content': '<p>isi</p>', 'focus_keyword': 'judul'}
        self.generator.generate_image.return_value = Mock()
        self.publisher = Mock()
        self.publisher.get_recent_posts.return_value = []
        self.publisher.update_post_content.return_value = (True, {'id': 55})
        self.publisher.upload_image.return_value = 77
        self.publisher._get_auth.return_value = {}
        self.publisher.api_url = 'https://example.com/wp-json/wp/v2'
        self.publisher._request.return_value = Mock(status_code=200)
        patches = [
            patch.object(jobs, 'db', self.db),
            patch.object(jobs, 'load_config', Mock(return_value={'gemini_api_key': 'k'})),
            patch.object(jobs, 'ArticleGenerator', Mock(**{'from_config.return_value': self.generator})),
            patch.object(jobs, 'WordPressPublisher', Mock(return_value=self.publisher)),
            patch.object(jobs, 'check_article', Mock(return_value=(True, [], []))),
            patch.object(jobs, 'review_article', Mock(return_value=ReviewResult('approve', 'ok', applied=2))),
            # Regeneration researches the post's title; tests must not hit the network.
            patch.object(jobs, '_merge_topic_research', lambda seo, *a, **k: seo),
        ]
        patches += quality_stub_patches(jobs)
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def log(self):
        with self.db.get_session() as s:
            log = s.get(PostLog, 10)
            s.expunge(log)
            return log

    def credits(self):
        with self.db.get_session() as s:
            return s.get(User, 1).credits

    def test_article_regeneration_success_consumes_credit(self):
        jobs.regenerate_article_job(1, 10)
        self.assertEqual(self.log().result, jobs.RESULT_REGENERATED + f' {PASSING_NOTE} Ditinjau AI: 2 perbaikan diterapkan.')
        self.assertEqual(self.credits(), 4)
        args = self.publisher.update_post_content.call_args.args
        self.assertEqual(args[:3], (55, 'Judul Baru', '<p>isi</p>'))

    def test_article_regeneration_failure_refunds_once(self):
        self.publisher.update_post_content.return_value = (False, 'rest_forbidden')
        jobs.regenerate_article_job(1, 10)
        self.assertEqual(self.credits(), 5)
        self.assertEqual(self.log().result,
                         'Regenerasi artikel gagal: Update postingan WordPress gagal: rest_forbidden')

    def test_quality_rejection_refunds(self):
        jobs.check_article.return_value = (False, ['too short'], [])
        jobs.regenerate_article_job(1, 10)
        self.assertEqual(self.credits(), 5)
        self.assertIn('ditolak quality gate', self.log().result)
        self.publisher.update_post_content.assert_not_called()

    def test_missing_log_refunds(self):
        jobs.regenerate_article_job(1, 999)
        self.assertEqual(self.credits(), 5)
        self.generator.generate_checked_article.assert_not_called()

    def test_log_without_post_id_refunds(self):
        with self.db.get_session() as s:
            s.get(PostLog, 10).post_id = None
        jobs.regenerate_image_job(1, 10)
        self.assertEqual(self.credits(), 5)
        self.generator.generate_image.assert_not_called()

    def test_image_regeneration_attaches_media(self):
        jobs.regenerate_image_job(1, 10)
        self.assertEqual(self.credits(), 4)
        log = self.log()
        self.assertFalse(log.image_failed)
        self.assertEqual(log.result, jobs.RESULT_PUBLISHED)
        self.assertEqual(self.publisher._request.call_args.kwargs['json'], {'featured_media': 77})

    def test_image_upload_failure_refunds(self):
        self.publisher.upload_image.return_value = None
        jobs.regenerate_image_job(1, 10)
        self.assertEqual(self.credits(), 5)
        self.assertTrue(self.log().result.startswith('Regenerasi gambar gagal: Upload gambar'))
        self.assertTrue(self.log().image_failed)


class FakeRedis:
    def __init__(self):
        self.store = {}

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.store:
            return False
        self.store[key] = value
        return True

    def get(self, key):
        return self.store.get(key)

    def setex(self, key, ttl, value):
        self.store[key] = value

    def delete(self, key):
        self.store.pop(key, None)


class DispatchJobsTests(unittest.TestCase):
    def setUp(self):
        self.db = make_db()
        with self.db.get_session() as s:
            s.add(User(id=1, email='u@example.com', credits=3))
            s.add(WordPressSite(
                id=1, user_id=1, site_name='Site', wordpress_url='https://example.com',
                is_active=True, auto_post=True, timezone='Asia/Jakarta',
                schedule_hours=','.join(str(h) for h in range(24)),
                selected_categories=[{'id': 7, 'name': 'Keuangan'}],
            ))
            s.add(ContentQueue(id=5, user_id=1, site_id=1, title='Cara menabung', category='Keuangan',
                               status='pending', created_at=datetime.now()))
        self.redis = FakeRedis()
        self.queue = Mock()
        patches = [
            patch.object(dispatcher, 'db', self.db),
            patch.object(dispatcher, 'redis_conn', self.redis),
            patch.object(dispatcher, 'q', self.queue),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def item(self):
        with self.db.get_session() as s:
            item = s.get(ContentQueue, 5)
            s.expunge(item)
            return item

    def test_due_site_enqueues_oldest_pending_item_once_per_hour(self):
        dispatcher.dispatch_jobs()
        dispatcher.dispatch_jobs()
        self.queue.enqueue_in.assert_called_once()
        call = self.queue.enqueue_in.call_args
        self.assertEqual(call.args[1:], ('tasks.article_jobs.generate_and_post', 1, 5, 1))
        item = self.item()
        self.assertEqual(item.status, 'posting')
        self.assertEqual(item.job_id, call.kwargs['job_id'])
        self.assertFalse(item.credit_held)

    def test_enqueue_failure_reverts_item_and_lock(self):
        self.queue.enqueue_in.side_effect = RuntimeError('redis down')
        dispatcher.dispatch_jobs()
        item = self.item()
        self.assertEqual(item.status, 'pending')
        self.assertIsNone(item.job_id)
        self.assertFalse(any(k.startswith('scheduler:last_run_post:') for k in self.redis.store))

    def test_user_without_credits_is_skipped(self):
        with self.db.get_session() as s:
            s.get(User, 1).credits = 0
        dispatcher.dispatch_jobs()
        self.queue.enqueue_in.assert_not_called()
        self.assertIn('scheduler:log_credit_warning:1', self.redis.store)
        self.assertEqual(self.item().status, 'pending')

    def test_search_console_sync_is_scheduled_even_without_credits(self):
        with self.db.get_session() as s:
            s.get(User, 1).credits = 0
            site = s.get(WordPressSite, 1)
            site.gsc_refresh_token = 'token'
            site.gsc_property_url = 'sc-domain:example.com'
        dispatcher.dispatch_jobs()
        self.queue.enqueue.assert_called_once_with(
            'tasks.gsc_jobs.sync_search_console_job', 1, 1, job_timeout='10m')


if __name__ == '__main__':
    unittest.main()
