"""The AI review step inside the article jobs: nothing is published unreviewed,
a rejection is a content failure (refund, topic consumed), an unavailable
reviewer is not (refund, topic handed back), and review edits are re-gated."""
import json
import unittest
from datetime import datetime
from unittest.mock import Mock, patch

from models import ContentQueue, PostLog, ResearchData, User, WordPressSite
from services import article_review
from services.article_review import ArticleReviewRejected, ArticleReviewUnavailable
from test_article_quality_support import PASSING_NOTE, quality_stub_patches
from test_research_backend_support import load_with_stubbed_core, make_db

jobs, _core = load_with_stubbed_core('tasks.article_jobs')

CONTENT = '<h2>Satu</h2><p>Menurut survei kami, 87% keluarga lunas.</p><h2>Dua</h2><p>Catat utang.</p>'


PUBLISHER_PROMPT = ('Kantor kami di Bandung melayani konsultasi gratis. Tutup dengan ajakan ke '
                    'https://partner.example/konsultasi untuk topik {topic}.')


def reply(**data):
    return json.dumps(data)


class ReviewJobTestCase(unittest.TestCase):
    def setUp(self):
        self.db = make_db()
        now = datetime.now()
        with self.db.get_session() as s:
            s.add(User(id=1, email='u@example.com', credits=10))
            s.add(WordPressSite(
                id=1, user_id=1, site_name='Site', wordpress_url='https://example.com',
                wordpress_username='admin', auto_post=True, language='id',
                categories=[{'id': 7, 'name': 'Keuangan', 'description': 'Keuangan keluarga untuk pembaca umum'}],
                selected_categories=[{'id': 7, 'name': 'Keuangan'}],
                article_prompt=PUBLISHER_PROMPT,
            ))
            s.add(ResearchData(id=1, user_id=1, site_id=1, category='Keuangan', keywords=['kw kategori'],
                               suggested_topics=[{'topic': 'Investasi emas', 'is_trending': False},
                                                 {'topic': 'Dana darurat', 'is_trending': False}],
                               confidence_level='high', researched_at=now, created_at=now))
            s.add(PostLog(id=10, user_id=1, site_id=1, post_id=55, title='Judul Lama',
                          category_name='Keuangan', success=True, result='x'))
        self.generator = Mock()
        self.generator.generate_checked_article.side_effect = lambda *a, **k: {
            'title': 'Strategi Melunasi Utang Keluarga', 'content': CONTENT, 'focus_keyword': 'utang',
            'meta_description': 'Meta deskripsi yang cukup panjang untuk artikel ini dan tetap akurat.',
        }
        self.generator.generate_image.return_value = None
        self.publisher = Mock()
        self.publisher.get_recent_posts.return_value = []
        self.publisher.create_post.return_value = (True, {'id': 1, 'link': 'https://example.com/p'})
        self.publisher.update_post_content.return_value = (True, {'id': 55})
        self.gate = Mock(return_value=(True, [], []))
        patches = [
            patch.object(jobs, 'db', self.db),
            patch.object(jobs, 'load_config', Mock(return_value={})),
            patch.object(jobs, 'ArticleGenerator', Mock(**{'from_config.return_value': self.generator})),
            patch.object(jobs, 'WordPressPublisher', Mock(return_value=self.publisher)),
            patch.object(jobs, 'check_article', self.gate),
            patch.object(jobs, '_merge_topic_research', lambda seo, *a, **k: seo),
            patch.object(jobs, 'load_search_metrics', Mock(return_value=([], []))),
            patch.object(jobs, '_current_job', lambda: None),
            patch.object(article_review, 'RETRY_DELAY_SECONDS', 0),
        ]
        patches += quality_stub_patches(jobs)
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def credits(self):
        with self.db.get_session() as s:
            return s.get(User, 1).credits

    def topics_left(self):
        with self.db.get_session() as s:
            return [t['topic'] for t in s.get(ResearchData, 1).suggested_topics]

    def last_log(self):
        with self.db.get_session() as s:
            log = s.query(PostLog).order_by(PostLog.id.desc()).first()
            s.expunge(log)
            return log

    def post(self):
        jobs.generate_and_post(1, site_id=1, credit_pre_reserved=True, manual=True)


class GenerateAndPostReviewTests(ReviewJobTestCase):
    def test_reviewed_edits_are_published_with_a_note(self):
        self.generator.generate_text.return_value = reply(
            verdict='revise', summary='Statistik karangan dihapus',
            edits=[{'find': 'Menurut survei kami, 87% keluarga lunas.', 'replace': 'Banyak keluarga bisa lunas.',
                    'reason': 'statistik tanpa sumber', 'critical': True}])
        self.post()
        content = self.publisher.create_post.call_args.args[1]
        self.assertIn('Banyak keluarga bisa lunas.', content)
        self.assertNotIn('87%', content)
        log = self.last_log()
        self.assertTrue(log.success)
        self.assertEqual(log.result, jobs.RESULT_PUBLISHED_NO_IMAGE + f' {PASSING_NOTE} Ditinjau AI: 1 perbaikan diterapkan.')
        self.assertEqual(self.credits(), 10)  # the caller's reservation is consumed
        self.assertEqual(self.topics_left(), ['Dana darurat'])
        # The edited article went through the quality gate a second time.
        self.assertEqual(self.gate.call_count, 2)
        # The reviewer saw the research given to the writer.
        self.assertIn('kw kategori', self.generator.generate_text.call_args.args[0])

    def test_review_runs_before_image_and_publish(self):
        order = []
        self.generator.generate_text.side_effect = lambda *a, **k: order.append('review') or reply(verdict='approve')
        self.generator.generate_image.side_effect = lambda *a, **k: order.append('image')
        self.publisher.create_post.side_effect = lambda *a, **k: order.append('publish') or (False, 'x')
        self.post()
        self.assertEqual(order, ['review', 'image', 'publish'])

    def test_unavailable_reviewer_blocks_publishing_refunds_and_returns_topic(self):
        self.generator.generate_text.side_effect = ConnectionError('reset')
        self.post()
        self.publisher.create_post.assert_not_called()
        self.generator.generate_image.assert_not_called()
        self.assertEqual(self.generator.generate_text.call_count, 2)  # one retry
        self.assertEqual(self.credits(), 11)  # caller's reservation refunded
        self.assertEqual(self.topics_left(), ['Investasi emas', 'Dana darurat'])
        log = self.last_log()
        self.assertFalse(log.success)
        self.assertTrue(log.result.startswith('Sistem Berhenti Tiba-tiba: Peninjauan AI gagal'))

    def test_rejection_is_a_content_failure(self):
        self.generator.generate_text.return_value = reply(verdict='reject', summary='Isinya karangan')
        self.post()
        self.publisher.create_post.assert_not_called()
        self.assertEqual(self.credits(), 11)
        self.assertEqual(self.topics_left(), ['Dana darurat'])  # topic consumed
        log = self.last_log()
        self.assertEqual(log.title, 'GAGAL: Strategi Melunasi Utang Keluarga')
        self.assertEqual(log.result, 'Artikel tidak diterbitkan: Artikel ditolak peninjau AI: Isinya karangan')

    def test_edits_that_break_the_quality_gate_reject(self):
        self.gate.side_effect = [(True, [], []), (False, ['Only 1 H2 heading(s)'], [])]
        self.generator.generate_text.return_value = reply(verdict='revise', edits=[
            {'find': '<h2>Dua</h2>', 'replace': '', 'reason': 'x', 'critical': True}])
        self.post()
        self.publisher.create_post.assert_not_called()
        self.assertIn('hasil perbaikan tidak lolos quality gate', self.last_log().result)
        self.assertEqual(self.topics_left(), ['Dana darurat'])

    def test_queue_item_is_reviewed_and_failed_item_refunded(self):
        with self.db.get_session() as s:
            s.add(ContentQueue(id=5, user_id=1, site_id=1, category='Keuangan', title='Cara Menabung',
                               status='posting', credit_held=True))
        self.generator.generate_text.return_value = reply(verdict='reject', summary='Tidak akurat')
        jobs.generate_and_post(1, item_id=5, credit_pre_reserved=True)
        self.publisher.create_post.assert_not_called()
        with self.db.get_session() as s:
            item = s.get(ContentQueue, 5)
            self.assertEqual(item.status, 'failed')
            self.assertFalse(item.credit_held)
        self.assertEqual(self.credits(), 11)

    def test_reviewer_sees_cited_sources_but_not_internal_posts(self):
        self.publisher.get_recent_posts.return_value = [{'title': 'Pos Lama', 'url': 'https://example.com/lama'}]
        self.generator.generate_checked_article.side_effect = lambda *a, **k: {
            'title': 'Strategi Melunasi Utang Keluarga', 'content': CONTENT,
            'allowed_link_urls': ['https://example.com/lama', 'https://sumber.id/data-utang'],
        }
        self.generator.generate_text.return_value = reply(verdict='approve')
        self.post()
        prompt = self.generator.generate_text.call_args.args[0]
        sources = prompt.split('[SOURCES the writer was allowed to cite and link]')[1].split('<<<END EVIDENCE')[0]
        self.assertIn('https://sumber.id/data-utang', sources)
        self.assertNotIn('example.com/lama', sources)

    def test_category_research_carries_source_metadata(self):
        with self.db.get_session() as s:
            s.get(ResearchData, 1).source_metadata = {'wikipedia': {'title': 'Utang', 'status': 'real'}}
        seo_data = jobs._load_category_research(1, 1, 'Keuangan')
        self.assertEqual(seo_data['source_metadata'], {'wikipedia': {'title': 'Utang', 'status': 'real'}})
        with self.db.get_session() as s:
            s.get(ResearchData, 1).source_metadata = ['not', 'a', 'dict']
        self.assertEqual(jobs._load_category_research(1, 1, 'Keuangan')['source_metadata'], {})

    def test_failure_classification(self):
        self.assertTrue(jobs._is_content_failure(ArticleReviewRejected(['x'])))
        self.assertTrue(jobs._is_content_failure(jobs.TopicTooSimilar('Judul')))
        self.assertFalse(jobs._is_content_failure(ArticleReviewUnavailable('Peninjauan AI gagal')))


class ReviewContextJobTests(ReviewJobTestCase):
    LINKED = ('<h2>Satu</h2><p>Baca <a href="https://example.com/lama">panduan lama</a> dan '
              '<a href="https://partner.example/konsultasi">konsultasi gratis</a>.</p><h2>Dua</h2><p>Catat.</p>')

    def setUp(self):
        super().setUp()
        self.publisher.get_recent_posts.return_value = [{'title': 'Pos Lama', 'url': 'https://example.com/lama'}]
        self.generator.generate_checked_article.side_effect = lambda *a, **k: {
            'title': 'Strategi Melunasi Utang Keluarga', 'content': self.LINKED,
            'allowed_link_urls': ['https://example.com/lama'],
        }

    def test_reviewer_gets_publisher_context_and_protected_links(self):
        self.generator.generate_text.return_value = reply(verdict='approve')
        self.post()
        prompt = self.generator.generate_text.call_args.args[0]
        protected = prompt.split('ALWAYS-ALLOWED LINKS')[-1].split('<<<PUBLISHER CONTEXT')[0]
        self.assertIn('- example.com (every page on this domain)', protected)
        self.assertIn('example.com/lama', protected)
        self.assertIn('partner.example/konsultasi', protected)
        context = prompt.split('<<<PUBLISHER CONTEXT')[1].split('<<<END PUBLISHER CONTEXT')[0]
        self.assertIn('Kantor kami di Bandung melayani konsultasi gratis', context)
        self.assertIn('Keuangan keluarga untuk pembaca umum', context)

    def test_edits_removing_site_or_cta_links_are_ignored(self):
        self.generator.generate_text.return_value = reply(verdict='revise', edits=[
            {'find': '<a href="https://partner.example/konsultasi">konsultasi gratis</a>',
             'replace': 'konsultasi gratis', 'reason': 'tautan tidak ada di SOURCES', 'critical': True},
            {'find': '<a href="https://example.com/lama">panduan lama</a>', 'replace': 'panduan lama',
             'reason': 'x', 'critical': True}])
        self.post()
        content = self.publisher.create_post.call_args.args[1]
        self.assertIn('href="https://partner.example/konsultasi"', content)
        self.assertIn('href="https://example.com/lama"', content)
        self.assertTrue(self.last_log().success)
        self.assertEqual(self.generator.generate_text.call_count, 1)  # ignored edits do not force round 2

    def test_reviewer_title_repeating_a_published_article_is_dropped(self):
        with self.db.get_session() as s:
            s.add(PostLog(user_id=1, site_id=1, category_name='Keuangan', title='Tips Menabung Keluarga Muda',
                          success=True, result='ok'))
        self.generator.generate_text.side_effect = [
            reply(verdict='approve', title='Cara Menabung untuk Keluarga Muda'),
            json.dumps({'same_intent': True}),
        ]
        self.post()
        self.assertEqual(self.publisher.create_post.call_args.args[0], 'Strategi Melunasi Utang Keluarga')
        self.assertEqual(self.last_log().result,
                         jobs.RESULT_PUBLISHED_NO_IMAGE + f' {PASSING_NOTE} Ditinjau AI: disetujui tanpa perbaikan isi.')

    def test_truncated_review_fails_safely_with_a_clear_message(self):
        from services.article_generator import TruncatedGenerationError
        self.generator.generate_text.side_effect = TruncatedGenerationError('cut')
        self.post()
        self.publisher.create_post.assert_not_called()
        self.assertEqual(self.generator.generate_text.call_count, 2)
        self.assertTrue(self.generator.generate_text.call_args.kwargs['raise_on_truncation'])
        self.assertEqual(self.generator.generate_text.call_args.kwargs['max_tokens'], 16384)
        self.assertIn('terpotong karena mencapai batas 16384 token', self.last_log().result)
        self.assertEqual(self.topics_left(), ['Investasi emas', 'Dana darurat'])  # not a content failure
        self.assertEqual(self.credits(), 11)

    def test_telegram_error_text_is_html_escaped(self):
        notify = Mock()
        self.generator.generate_text.return_value = reply(verdict='reject', summary='Klaim A & B <palsu>')
        with patch.object(jobs, 'send_telegram_notification', notify):
            self.post()
        message = notify.call_args.args[1]
        self.assertIn('Gagal Generate &amp; Post', message)
        self.assertIn('Klaim A &amp; B palsu', message)  # angle brackets dropped, & escaped
        start = jobs._start_message({'site_name': 'A & B'}, {'name': 'K<1>'}, 'Judul & "x"')
        self.assertIn('A &amp; B', start)
        self.assertIn('K&lt;1&gt;', start)
        self.assertIn('Judul &amp; "x"', start)


class RegenerationReviewTests(ReviewJobTestCase):
    def log10(self):
        with self.db.get_session() as s:
            log = s.get(PostLog, 10)
            s.expunge(log)
            return log

    def test_regeneration_is_reviewed(self):
        self.generator.generate_text.return_value = reply(verdict='approve', title='Judul Lebih Jujur')
        with self.db.get_session() as s:
            s.get(User, 1).credits = 4  # after the route's reservation
        jobs.regenerate_article_job(1, 10)
        args = self.publisher.update_post_content.call_args.args
        self.assertEqual(args[1], 'Judul Lebih Jujur')
        self.assertEqual(self.log10().result, jobs.RESULT_REGENERATED + f' {PASSING_NOTE} Ditinjau AI: disetujui tanpa perbaikan '
                                                                         'isi, judul disesuaikan.')
        prompt = self.generator.generate_text.call_args.args[0]
        # The category's research and the publisher's own context reach the reviewer.
        self.assertIn('kw kategori', prompt)
        self.assertIn('Kantor kami di Bandung', prompt)
        self.assertIn('Keuangan keluarga untuk pembaca umum', prompt)
        self.assertEqual(self.credits(), 4)

    def test_regeneration_without_research_says_so(self):
        with self.db.get_session() as s:
            s.get(ResearchData, 1).confidence_level = 'unknown'
        self.generator.generate_text.return_value = reply(verdict='approve')
        jobs.regenerate_article_job(1, 10)
        self.assertIn('No research evidence', self.generator.generate_text.call_args.args[0])

    def test_rejected_regeneration_refunds_and_keeps_the_post(self):
        self.generator.generate_text.return_value = reply(verdict='reject', summary='Klaim hukum keliru')
        with self.db.get_session() as s:
            s.get(User, 1).credits = 4
        jobs.regenerate_article_job(1, 10)
        self.publisher.update_post_content.assert_not_called()
        self.assertEqual(self.credits(), 5)
        self.assertEqual(self.log10().result,
                         'Regenerasi artikel gagal: Artikel ditolak peninjau AI: Klaim hukum keliru')


if __name__ == '__main__':
    unittest.main()
