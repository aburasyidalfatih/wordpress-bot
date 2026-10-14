"""Topic cannibalization: services.topic_similarity and its use in the article
job (queue titles, scheduled research topics, generated titles). No network."""
import json
import unittest
from datetime import datetime
from unittest.mock import Mock, patch

from rq.timeouts import JobTimeoutException

from models import ContentQueue, PostLog, ResearchData, User, WordPressSite
from services.article_review import ReviewResult
from services.topic_similarity import (
    BORDERLINE_THRESHOLD, DEFINITE_THRESHOLD, SIMILAR_THRESHOLD, find_similar_published, significant_tokens,
    similarity_score,
)
from test_research_backend_support import load_with_stubbed_core, make_db

jobs, _core = load_with_stubbed_core('tasks.article_jobs')


def score(a, b, language):
    return similarity_score(significant_tokens(a, language), significant_tokens(b, language))


class FakeGenerator:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.prompts = []

    def generate_text(self, prompt, system=None, max_tokens=8192):
        self.prompts.append(prompt)
        self.max_tokens = max_tokens
        value = self.replies.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value


class NormalizationTests(unittest.TestCase):
    def test_generic_words_numbers_and_inflections_are_dropped(self):
        self.assertEqual(significant_tokens('Eliminate Family Debt Fast: Ultimate 2026 Household Payoff Guide', 'en'),
                         ['eliminate', 'family', 'debt', 'household', 'payoff'])
        self.assertEqual(significant_tokens('4 Practical Household Payoff Models', 'en'),
                         ['household', 'payoff', 'model'])
        self.assertEqual(significant_tokens('Family Budgeting Basics', 'en'), ['family', 'budget', 'basic'])
        self.assertEqual(significant_tokens('Contoh RAPBS Sekolah dan Cara Menyusunnya', 'id'),
                         ['rapbs', 'sekolah', 'menyusun'])
        # Indonesian words are not run through English plural rules.
        self.assertEqual(significant_tokens('Tugas Kelas', 'id'), ['tugas', 'kelas'])


class ExampleTests(unittest.TestCase):
    def assertSimilar(self, a, b, language):
        self.assertEqual(find_similar_published(a, ['Resep Nasi Goreng', b], language=language)[0], b)

    def assertDistinct(self, a, b, language):
        self.assertIsNone(find_similar_published(a, [b], language=language))

    def test_same_debt_payoff_intent_is_similar(self):
        self.assertSimilar('Eliminate Family Debt Fast: Ultimate 2026 Household Payoff Guide',
                           'Break Free From Debt: 4 Practical Household Payoff Models', 'en')

    def test_same_family_budgeting_intent_is_similar(self):
        self.assertSimilar('From Paycheck Pressure to Peace: Family Budgeting Basics',
                           'Family Budgeting Basics: Reclaim Household Cash Flow in 2026', 'en')

    def test_different_topics_are_distinct(self):
        self.assertDistinct('Emergency Fund Basics', 'Debt Payoff Methods', 'en')
        self.assertEqual(score('Emergency Fund Basics', 'Debt Payoff Methods', 'en'), 0)
        self.assertDistinct('Investasi Emas Jangka Panjang', 'Resep Nasi Goreng', 'id')

    def test_indonesian_near_duplicates_are_similar(self):
        self.assertSimilar('7 Tips Menabung!', 'tips menabung', 'id')
        self.assertSimilar('Cara Menabung untuk Pelajar SMA', 'Cara Menabung untuk Pelajar SMP', 'id')
        self.assertSimilar('Strategi Investasi Emas untuk Pemula', 'Panduan Lengkap Investasi Emas 2026', 'id')
        self.assertSimilar('Cara Mengelola Keuangan Sekolah Swasta',
                           'Manajemen Keuangan Sekolah Swasta yang Efektif', 'id')
        self.assertSimilar('Cara Menyusun RAPBS Sekolah', 'Contoh RAPBS Sekolah Dasar dan Cara Menyusunnya', 'id')

    def test_internal_audit_vs_cash_flow_control_is_distinct(self):
        # Decision: NOT similar. They share only "pengendalian" and the site's
        # niche word "sekolah" and no head phrase: internal audit / financial
        # control and cash-flow control answer different searches.
        a = 'Audit Internal dan Pengendalian Keuangan Sekolah'
        b = 'Panduan Pengendalian Arus Kas Sekolah Swasta'
        self.assertLess(score(a, b, 'id'), BORDERLINE_THRESHOLD)
        self.assertDistinct(a, b, 'id')

    def test_one_shared_word_is_never_enough(self):
        self.assertEqual(score('Best Credit Cards for Students', 'How to Improve Your Credit Score', 'en'), 0)

    def test_site_niche_words_count_less(self):
        # On an elementary-school site "sekolah dasar" is in every title, so
        # sharing it says nothing: school security is not the school canteen.
        title, existing = 'Keamanan Sekolah Dasar', 'Kantin Sekolah Dasar'
        self.assertGreaterEqual(score(title, existing, 'id'), SIMILAR_THRESHOLD)
        self.assertIsNotNone(find_similar_published(title, [existing], language='id'))
        site_titles = [f'{topic} Sekolah Dasar' for topic in
                       ('Kurikulum', 'Seragam', 'Perpustakaan', 'Ekstrakurikuler', 'Guru', 'Rapor', 'Upacara')]
        self.assertIsNone(find_similar_published(title, site_titles + [existing], language='id'))


class AIConfirmationTests(unittest.TestCase):
    # "family budget basic" vs "family vacation plan budget": borderline.
    CANDIDATE = 'Family Budgeting Basics'
    PUBLISHED = ['Family Vacation Planning on a Budget']

    def test_borderline_is_confirmed_by_the_model(self):
        self.assertTrue(BORDERLINE_THRESHOLD <= score(self.CANDIDATE, self.PUBLISHED[0], 'en') < SIMILAR_THRESHOLD)
        generator = FakeGenerator('```json\n{"same_intent": true}\n```')
        match = find_similar_published(self.CANDIDATE, self.PUBLISHED, language='en', generator=generator)
        self.assertEqual(match[0], self.PUBLISHED[0])
        self.assertIn('Title A: Family Budgeting Basics', generator.prompts[0])
        # Room for Gemini's thinking tokens, which count against the output limit.
        self.assertEqual(generator.max_tokens, 4096)

    def test_failed_check_logs_the_fallback(self):
        with self.assertLogs('services.topic_similarity', level='WARNING') as logs:
            find_similar_published(self.CANDIDATE, self.PUBLISHED, language='en', generator=FakeGenerator(''))
        self.assertTrue(any('falling back to the score' in line for line in logs.output))

    def test_rq_job_timeout_is_not_swallowed(self):
        with self.assertRaises(JobTimeoutException):
            find_similar_published(self.CANDIDATE, self.PUBLISHED, language='en',
                                   generator=FakeGenerator(JobTimeoutException('job timeout')))

    def test_borderline_rejected_by_the_model_or_failing_check_is_distinct(self):
        for answer in ('{"same_intent": false}', 'no idea', ConnectionError('down')):
            with self.subTest(answer=answer):
                generator = FakeGenerator(answer)
                self.assertIsNone(find_similar_published(self.CANDIDATE, self.PUBLISHED, language='en',
                                                         generator=generator))
                self.assertEqual(len(generator.prompts), 1)
        self.assertIsNone(find_similar_published(self.CANDIDATE, self.PUBLISHED, language='en'))

    def test_model_decides_the_gray_zone_and_score_is_the_fallback(self):
        candidate = 'Eliminate Family Debt Fast: Ultimate 2026 Household Payoff Guide'
        published = ['Break Free From Debt: 4 Practical Household Payoff Models']
        self.assertTrue(SIMILAR_THRESHOLD <= score(candidate, published[0], 'en') < DEFINITE_THRESHOLD)
        self.assertIsNone(find_similar_published(candidate, published, language='en',
                                                 generator=FakeGenerator('{"same_intent": false}')))
        self.assertIsNotNone(find_similar_published(candidate, published, language='en',
                                                    generator=FakeGenerator(RuntimeError('quota'))))

    def test_model_confirmations_are_capped(self):
        published = ['Family Vacation Planning on a Budget', 'Family Budget Vacation Plans',
                     'Budget Family Vacation Planner']
        generator = FakeGenerator('{"same_intent": false}', '{"same_intent": false}')
        self.assertIsNone(find_similar_published(self.CANDIDATE, published, language='en', generator=generator))
        self.assertEqual(len(generator.prompts), 2)

    def test_clear_cases_skip_the_model(self):
        generator = FakeGenerator()
        self.assertIsNotNone(find_similar_published('Tips Menabung', ['tips menabung'], language='id',
                                                    generator=generator))
        self.assertIsNone(find_similar_published('Resep Rendang', ['Investasi Emas'], language='id',
                                                 generator=generator))
        self.assertEqual(generator.prompts, [])


class JobSimilarityTestCase(unittest.TestCase):
    TOPICS = ['Eliminate Family Debt Fast: Ultimate 2026 Household Payoff Guide', 'Emergency Fund Basics']
    PUBLISHED = 'Break Free From Debt: 4 Practical Household Payoff Models'

    def setUp(self):
        self.db = make_db()
        now = datetime.now()
        with self.db.get_session() as s:
            s.add(User(id=1, email='u@example.com', credits=10))
            s.add(WordPressSite(
                id=1, user_id=1, site_name='Site', wordpress_url='https://example.com',
                wordpress_username='admin', auto_post=True, language='en',
                categories=[{'id': 7, 'name': 'Finance'}],
                selected_categories=[{'id': 7, 'name': 'Finance'}],
            ))
            s.add(ResearchData(id=1, user_id=1, site_id=1, category='Finance',
                               suggested_topics=[{'topic': t} for t in self.TOPICS],
                               confidence_level='high', researched_at=now, created_at=now))
            s.add(PostLog(user_id=1, site_id=1, category_name='Finance', title=self.PUBLISHED,
                          success=True, result='ok', created_at=now))
        self.generator = Mock()
        # Gray-zone title pairs are confirmed by the model (scripted: same intent).
        self.generator.generate_text.side_effect = lambda *a, **k: json.dumps({'same_intent': True})
        self.generator.generate_checked_article.side_effect = lambda *a, **k: {
            'title': 'Emergency Fund Basics: How Much to Save', 'content': '<p>x</p>'}
        self.generator.generate_image.return_value = None
        self.publisher = Mock()
        self.publisher.get_recent_posts.return_value = []
        self.publisher.create_post.return_value = (True, {'id': 1, 'link': 'https://example.com/p'})
        patches = [
            patch.object(jobs, 'db', self.db),
            patch.object(jobs, 'load_config', Mock(return_value={})),
            patch.object(jobs, 'ArticleGenerator', Mock(**{'from_config.return_value': self.generator})),
            patch.object(jobs, 'WordPressPublisher', Mock(return_value=self.publisher)),
            patch.object(jobs, 'check_article', Mock(return_value=(True, [], []))),
            patch.object(jobs, '_merge_topic_research', lambda seo, *a, **k: seo),
            patch.object(jobs, 'load_search_metrics', Mock(return_value=([], []))),
            patch.object(jobs, '_current_job', lambda: None),
            patch.object(jobs, 'review_article', Mock(return_value=ReviewResult('approve', 'ok'))),
        ]
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

    def generation_call(self, index=0):
        return self.generator.generate_checked_article.call_args_list[index]


class ScheduledTopicTests(JobSimilarityTestCase):
    def test_similar_research_topic_is_consumed_and_the_next_one_used(self):
        self.post()
        self.assertEqual(self.generation_call().args[2], 'Emergency Fund Basics')
        self.assertEqual(self.topics_left(), [])  # skipped topic consumed, used topic spent
        self.assertTrue(self.last_log().success)
        # A distinct topic is written normally, not as an "avoid similar" rewrite.
        self.assertNotIn('avoid_similar', self.generation_call().kwargs)

    def test_all_topics_similar_falls_back_to_category_avoiding_them(self):
        with self.db.get_session() as s:
            s.get(ResearchData, 1).suggested_topics = [
                {'topic': 'Eliminate Family Debt Fast: Household Payoff Guide'},
                {'topic': 'Household Debt Payoff Plan'},
                {'topic': 'Debt Payoff for the Household'},
                {'topic': 'Emergency Fund Basics'},
            ]
        self.post()
        call = self.generation_call()
        self.assertIsNone(call.args[2])  # category article, no topic
        self.assertTrue(call.kwargs['avoid_similar'])
        self.assertEqual(call.args[1][-1], self.PUBLISHED)  # most important title listed last
        self.assertEqual(self.topics_left(), ['Emergency Fund Basics'])  # only MAX_TOPIC_CLAIMS tried

    def test_failure_after_skipping_still_returns_the_used_topic(self):
        self.publisher.create_post.return_value = (False, 'HTTP 502')
        self.post()
        self.assertEqual(self.topics_left(), ['Emergency Fund Basics'])

    def test_similar_generated_title_is_regenerated_then_fails(self):
        with self.db.get_session() as s:
            s.get(ResearchData, 1).suggested_topics = [{'topic': 'Emergency Fund Basics'}]
        self.generator.generate_checked_article.side_effect = lambda *a, **k: {
            'title': 'Household Debt Payoff: Break Free Faster', 'content': '<p>x</p>'}
        self.post()
        calls = self.generator.generate_checked_article.call_args_list
        self.assertEqual(len(calls), 2)
        self.assertTrue(calls[1].kwargs['avoid_similar'])
        self.assertEqual(calls[1].args[1][-1], self.PUBLISHED)
        self.publisher.create_post.assert_not_called()
        self.assertEqual(self.credits(), 11)
        self.assertEqual(self.last_log().result,
                         f"Artikel tidak diterbitkan: Topik terlalu mirip dengan artikel yang sudah terbit: "
                         f"'{self.PUBLISHED}'")
        self.assertEqual(self.topics_left(), [])  # content failure: topic consumed


class QueueItemSimilarityTests(JobSimilarityTestCase):
    def add_item(self, title):
        with self.db.get_session() as s:
            s.add(ContentQueue(id=5, user_id=1, site_id=1, category='Finance', title=title,
                               status='posting', credit_held=True))

    def item(self):
        with self.db.get_session() as s:
            item = s.get(ContentQueue, 5)
            s.expunge(item)
            return item

    def test_queue_title_repeating_a_published_article_fails_with_refund(self):
        self.add_item('Eliminate Family Debt Fast: Ultimate 2026 Household Payoff Guide')
        jobs.generate_and_post(1, item_id=5, credit_pre_reserved=True)
        self.generator.generate_checked_article.assert_not_called()
        self.assertEqual(self.item().status, 'failed')
        self.assertFalse(self.item().credit_held)
        self.assertEqual(self.credits(), 11)
        log = self.last_log()
        self.assertFalse(log.success)
        self.assertEqual(log.title, 'GAGAL: Eliminate Family Debt Fast: Ultimate 2026 Household Payoff Guide')
        self.assertEqual(log.result, "Artikel tidak diterbitkan: Topik terlalu mirip dengan artikel yang sudah "
                                     f"terbit: '{self.PUBLISHED}'")

    def test_recent_wordpress_posts_count_as_published(self):
        self.publisher.get_recent_posts.return_value = [
            {'title': 'Emergency Fund Basics &amp; Beyond', 'url': 'https://example.com/ef'}]
        self.add_item('Emergency Fund Basics')
        jobs.generate_and_post(1, item_id=5, credit_pre_reserved=True)
        self.assertEqual(self.item().status, 'failed')

    def test_distinct_queue_title_is_published(self):
        self.add_item('Emergency Fund Basics')
        jobs.generate_and_post(1, item_id=5, credit_pre_reserved=True)
        self.assertEqual(self.item().status, 'posted')
        self.assertEqual(self.generation_call().args[2], 'Emergency Fund Basics')


if __name__ == '__main__':
    unittest.main()
