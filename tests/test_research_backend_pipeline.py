"""Article pipeline use of research: queue items get category research, research
topics are only spent by a published article, Search Console is filtered per topic."""
import unittest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

from models import ContentQueue, ResearchData, User, WordPressSite
from services.ai_providers import AIProviderError
from services.article_generator import ArticleQualityError
from services.article_review import ReviewResult
from test_research_backend_support import load_with_stubbed_core, make_db

jobs, _core = load_with_stubbed_core('tasks.article_jobs')


class PipelineTestCase(unittest.TestCase):
    def setUp(self):
        self.db = make_db()
        now = datetime.now()
        with self.db.get_session() as s:
            s.add(User(id=1, email='u@example.com', credits=10))
            s.add(WordPressSite(
                id=1, user_id=1, site_name='Site', wordpress_url='https://example.com',
                wordpress_username='admin', auto_post=True, language='id',
                categories=[{'id': 7, 'name': 'Keuangan'}],
                selected_categories=[{'id': 7, 'name': 'Keuangan'}],
            ))
            s.add(ResearchData(id=1, user_id=1, site_id=1, category='Keuangan', keywords=['kw kategori'],
                               long_tail_keywords=['long tail kategori'],
                               suggested_topics=[{'topic': 'Investasi emas', 'type': 'rising', 'is_trending': True},
                                                 {'topic': 'Dana darurat', 'type': 'question', 'is_trending': False}],
                               confidence_level='high', researched_at=now, created_at=now))
        self.generator = Mock()
        self.generator.generate_checked_article.return_value = {'title': 'Judul Unik Sekali', 'content': '<p>a</p>'}
        self.generator.generate_image.return_value = None
        self.publisher = Mock()
        self.publisher.get_recent_posts.return_value = []
        self.publisher.create_post.return_value = (True, {'id': 1, 'link': 'https://example.com/p'})
        self.topic_research = Mock(side_effect=lambda seo, *a, **k: seo)
        patches = [
            patch.object(jobs, 'db', self.db),
            patch.object(jobs, 'load_config', Mock(return_value={})),
            patch.object(jobs, 'ArticleGenerator', Mock(**{'from_config.return_value': self.generator})),
            patch.object(jobs, 'WordPressPublisher', Mock(return_value=self.publisher)),
            patch.object(jobs, 'check_article', Mock(return_value=(True, [], []))),
            patch.object(jobs, '_merge_topic_research', self.topic_research),
            patch.object(jobs, 'load_search_metrics', Mock(return_value=([], []))),
            patch.object(jobs, '_current_job', lambda: None),
            patch.object(jobs, 'review_article', Mock(return_value=ReviewResult('approve', 'ok'))),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def seo_data_used(self):
        return self.generator.generate_checked_article.call_args.args[3]

    def topics_left(self):
        with self.db.get_session() as s:
            return [t['topic'] for t in s.get(ResearchData, 1).suggested_topics]


class QueueItemResearchTests(PipelineTestCase):
    def test_queue_item_gets_its_category_research(self):
        with self.db.get_session() as s:
            s.add(ContentQueue(id=5, user_id=1, site_id=1, category='Keuangan', title='Cara Menabung',
                               status='posting', credit_held=True))
        jobs.generate_and_post(1, item_id=5, credit_pre_reserved=True)
        seo_data = self.seo_data_used()
        self.assertEqual(seo_data['keywords'], ['kw kategori'])
        self.assertEqual(seo_data['long_tail'], ['long tail kategori'])
        # Queue titles are not trending topics and do not take research topics.
        self.assertNotIn('topic_is_trending', seo_data)
        self.assertEqual(self.topics_left(), ['Investasi emas', 'Dana darurat'])

    def test_stale_research_is_not_used(self):
        with self.db.get_session() as s:
            s.get(ResearchData, 1).researched_at = datetime.now() - timedelta(days=8)
            s.add(ContentQueue(id=6, user_id=1, site_id=1, category='Keuangan', title='Cara Menabung',
                               status='posting', credit_held=True))
        jobs.generate_and_post(1, item_id=6, credit_pre_reserved=True)
        self.assertNotIn('kw kategori', str(self.seo_data_used()))


class ResearchTopicLifecycleTests(PipelineTestCase):
    def test_published_article_spends_the_trending_topic(self):
        jobs.generate_and_post(1, site_id=1, credit_pre_reserved=True, manual=True)
        self.assertEqual(self.generator.generate_checked_article.call_args.args[2], 'Investasi emas')
        self.assertTrue(self.seo_data_used()['topic_is_trending'])
        self.assertEqual(self.topics_left(), ['Dana darurat'])

    def test_failed_article_returns_the_topic(self):
        self.publisher.create_post.return_value = (False, 'rest_forbidden')
        jobs.generate_and_post(1, site_id=1, credit_pre_reserved=True, manual=True)
        self.assertEqual(self.topics_left(), ['Investasi emas', 'Dana darurat'])

    def test_generation_error_returns_the_topic(self):
        self.generator.generate_checked_article.side_effect = RuntimeError('quota')
        jobs.generate_and_post(1, site_id=1, credit_pre_reserved=True, manual=True)
        self.assertEqual(self.topics_left(), ['Investasi emas', 'Dana darurat'])
        with self.db.get_session() as s:
            self.assertFalse(s.get(ResearchData, 1).used)

    def test_non_trending_topic_stays_neutral(self):
        with self.db.get_session() as s:
            s.get(ResearchData, 1).suggested_topics = [{'topic': 'Dana darurat', 'is_trending': False}]
        jobs.generate_and_post(1, site_id=1, credit_pre_reserved=True, manual=True)
        self.assertNotIn('topic_is_trending', self.seo_data_used())


class TopicFailureClassificationTests(PipelineTestCase):
    def test_content_failures_consume_the_topic(self):
        for error in (ArticleQualityError({'title': 'x'}, ['too short']),
                      AIProviderError('Claude menolak membuat konten ini. Ubah topik atau gunakan provider lain.'),
                      jobs.QualityGateRejection('Artikel ditolak quality gate: too short')):
            with self.subTest(error=type(error).__name__):
                self.assertTrue(jobs._is_content_failure(error))
        self.assertFalse(jobs._is_content_failure(AIProviderError('API key Claude belum diatur di Panel Admin.')))
        self.assertFalse(jobs._is_content_failure(RuntimeError('timeout')))

    def test_quality_rejection_does_not_return_the_topic(self):
        self.generator.generate_checked_article.side_effect = ArticleQualityError({'title': 'x'}, ['too short'])
        jobs.generate_and_post(1, site_id=1, credit_pre_reserved=True, manual=True)
        self.assertEqual(self.topics_left(), ['Dana darurat'])

    def test_quality_gate_in_the_job_does_not_return_the_topic(self):
        with patch.object(jobs, 'check_article', Mock(return_value=(False, ['too short'], []))):
            jobs.generate_and_post(1, site_id=1, credit_pre_reserved=True, manual=True)
        self.assertEqual(self.topics_left(), ['Dana darurat'])

    def test_transient_failures_return_the_topic_at_most_twice(self):
        self.publisher.create_post.return_value = (False, 'HTTP 502')
        for _ in range(2):
            jobs.generate_and_post(1, site_id=1, credit_pre_reserved=True, manual=True)
            self.assertEqual(self.topics_left(), ['Investasi emas', 'Dana darurat'])
        with self.db.get_session() as s:
            self.assertEqual(s.get(ResearchData, 1).suggested_topics[0]['restore_count'], 2)
        jobs.generate_and_post(1, site_id=1, credit_pre_reserved=True, manual=True)
        self.assertEqual(self.topics_left(), ['Dana darurat'])


class LinkStrippingTests(PipelineTestCase):
    CONTENT = ('<p><a href="https://evil.example/x">evil</a> '
               '<a href="http://WWW.Example.com/old-post/">own</a> '
               '<a href="https://partner.example/promo">promo</a> '
               '<a href="https://example.com/p1">internal</a></p>')

    def setUp(self):
        super().setUp()
        with self.db.get_session() as s:
            s.get(WordPressSite, 1).article_prompt = 'Selalu tautkan https://partner.example/promo/ di artikel.'
        self.generator.generate_checked_article.return_value = {
            'title': 'Judul Unik Sekali', 'content': self.CONTENT,
            'allowed_link_urls': ['https://example.com/p1/'],
        }

    def published_content(self):
        return self.publisher.create_post.call_args.args[1]

    def test_foreign_links_unwrapped_but_own_domain_and_prompt_urls_kept(self):
        jobs.generate_and_post(1, site_id=1, credit_pre_reserved=True, manual=True)
        content = self.published_content()
        self.assertNotIn('evil.example', content)
        self.assertIn('href="http://WWW.Example.com/old-post/"', content)
        self.assertIn('href="https://partner.example/promo"', content)
        self.assertIn('href="https://example.com/p1"', content)

    def test_failed_recent_posts_fetch_leaves_links_alone(self):
        self.publisher.get_recent_posts.side_effect = RuntimeError('wp down')
        jobs.generate_and_post(1, site_id=1, credit_pre_reserved=True, manual=True)
        self.assertEqual(self.published_content(), self.CONTENT)

    def test_recent_posts_none_vs_empty(self):
        publisher = Mock(**{'get_recent_posts.return_value': []})
        self.assertEqual(jobs._recent_posts_for_links(publisher), [])
        publisher.get_recent_posts.side_effect = RuntimeError('wp down')
        self.assertIsNone(jobs._recent_posts_for_links(publisher))


class SearchEvidenceFilterTests(unittest.TestCase):
    def test_only_queries_about_the_topic_are_used(self):
        current = [
            {'query': 'investasi emas antam', 'page': '/a', 'clicks': 30, 'impressions': 900, 'ctr': .05,
             'position': 12},
            {'query': 'resep rendang padang', 'page': '/b', 'clicks': 30, 'impressions': 900, 'ctr': .05,
             'position': 12},
        ]
        with patch.object(jobs, 'db', make_db()), patch.object(jobs, 'load_search_metrics', return_value=(current, [])):
            data = jobs._attach_search_evidence({}, 1, 1, 'Keuangan', topic='Investasi emas pemula')
        self.assertEqual([q['query'] for q in data['search_queries']], ['investasi emas antam'])


if __name__ == '__main__':
    unittest.main()
