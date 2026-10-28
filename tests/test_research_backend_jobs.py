"""deep_research_job: result shape on every path, progress, reservation settlement,
lock release, category normalization and topic suggestions."""
import json
import sys
import types
import unittest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

import database
from models import PostLog, ResearchData, User, WordPressSite
from test_research_backend_support import FakeRedis, load_with_stubbed_core, make_db

rj, _core = load_with_stubbed_core('tasks.research_jobs')

RESULT_KEYS = {'successful_categories', 'failed_categories', 'refunded_credits', 'skipped', 'reason'}


class FakeJob:
    def __init__(self, job_id='research-1-abc'):
        self.id = job_id
        self.meta = {}
        self.snapshots = []

    def save_meta(self):
        self.snapshots.append(dict(self.meta))


class FakeSEO:
    failing = set()
    timeout_on = None

    def research_category(self, name, language='id'):
        if name == self.timeout_on:
            raise rj.BaseTimeoutException('deadline')
        if name in self.failing:
            raise RuntimeError('blocked')
        providers = {p: {'status': 'real'} for p in ('google_trends', 'google_autocomplete', 'competitors')}
        return {'quality': {'score': 60, 'real_provider_count': 3}, 'source_metadata': providers,
                'evidence_suggestions': ['kw'], 'evidence_questions': ['q?'],
                'long_tail_keywords': ['long tail kw']}


class FakeTrending:
    def __init__(self, topics=('topik',)):
        self.topics = list(topics)
        self.calls = []

    def get_trending_topics(self, name, limit=15, language='id'):
        return {}

    # Same signature as TrendingResearch.build_topic_suggestions.
    def build_topic_suggestions(self, category_name, trending_data, count=5,
                                suggestions=None, questions=None, long_tail=None, keywords=None):
        self.calls.append({'suggestions': suggestions, 'questions': questions,
                           'long_tail': long_tail, 'keywords': keywords})
        return [{'topic': t, 'category': category_name, 'is_trending': False} for t in self.topics]


class ResearchJobTestCase(unittest.TestCase):
    def setUp(self):
        self.db = make_db()
        with self.db.get_session() as s:
            s.add(User(id=1, email='u@example.com', credits=0))
        self.redis = FakeRedis()
        self.telegram = Mock()
        self.trending = FakeTrending()
        self.job = FakeJob()
        FakeSEO.failing, FakeSEO.timeout_on = set(), None
        seo_module = types.ModuleType('seo_research')
        seo_module.SEOResearch = FakeSEO
        patches = [
            patch.object(rj, 'db', self.db),
            patch.object(rj, 'trending', self.trending),
            patch.object(rj, '_redis', lambda: self.redis),
            patch.object(rj, '_current_job', lambda: self.job),
            patch.object(rj, '_load_search_console_queries', return_value=[]),
            patch.object(rj, 'send_telegram_notification', self.telegram),
            patch.dict(sys.modules, {'seo_research': seo_module}),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def add_site(self, names, telegram=True):
        with self.db.get_session() as s:
            s.add(WordPressSite(id=1, user_id=1, site_name='Site', wordpress_url='https://example.com',
                                language='id', telegram_enabled=telegram,
                                selected_categories=[{'id': i, 'name': n} for i, n in enumerate(names)]))

    def credits(self):
        with self.db.get_session() as s:
            return s.get(User, 1).credits

    def saved_categories(self):
        with self.db.get_session() as s:
            return [r.category for r in s.query(ResearchData).order_by(ResearchData.id)]


class ResultShapeTests(ResearchJobTestCase):
    def assert_shape(self, result):
        self.assertTrue(RESULT_KEYS <= set(result))
        json.dumps(result)

    def test_success(self):
        self.add_site(['Keuangan', 'Parenting'])
        result = rj.deep_research_job(1, True, 1, None, charged_credits=2)
        self.assert_shape(result)
        self.assertEqual((result['successful_categories'], result['failed_categories'],
                          result['refunded_credits'], result['skipped'], result['reason']),
                         (2, 0, 0, False, None))

    def test_all_failed(self):
        self.add_site(['Keuangan', 'Parenting'])
        FakeSEO.failing = {'Keuangan', 'Parenting'}
        result = rj.deep_research_job(1, True, 1, None, charged_credits=2)
        self.assert_shape(result)
        self.assertEqual(result['failed_categories'], 2)
        self.assertEqual(result['refunded_credits'], 2)
        self.assertFalse(result['skipped'])
        self.assertTrue(result['reason'])
        self.assertEqual(self.credits(), 2)

    def test_nothing_to_research(self):
        self.add_site([])
        result = rj.deep_research_job(1, False, 1, None)
        self.assert_shape(result)
        self.assertTrue(result['skipped'])
        self.assertTrue(result['reason'])
        self.telegram.assert_not_called()

    def test_missing_site_and_missing_site_id(self):
        for site_id in (None, 99):
            with self.subTest(site_id=site_id):
                result = rj.deep_research_job(1, True, site_id, None, charged_credits=1)
                self.assert_shape(result)
                self.assertTrue(result['skipped'])
                self.assertEqual(result['refunded_credits'], 1)

    def test_timeout_refunds_unfinished_categories(self):
        self.add_site(['Keuangan', 'Parenting', 'Bisnis'])
        FakeSEO.timeout_on = 'Parenting'
        result = rj.deep_research_job(1, True, 1, None, charged_credits=3)
        self.assert_shape(result)
        self.assertEqual((result['successful_categories'], result['failed_categories'],
                          result['refunded_credits']), (1, 2, 2))
        self.assertIn('batas waktu', result['reason'])

    def test_unexpected_error_still_returns_result(self):
        self.add_site(['Keuangan'])
        with patch.object(rj, '_research_categories', side_effect=RuntimeError('boom')):
            result = rj.deep_research_job(1, True, 1, None, charged_credits=1)
        self.assert_shape(result)
        self.assertEqual(result['refunded_credits'], 1)
        self.assertEqual(result['failed_categories'], 1)

    def test_plan_failure_refunds(self):
        with patch.object(rj, '_load_research_plan', side_effect=RuntimeError('db down')):
            result = rj.deep_research_job(1, True, 1, None, charged_credits=2)
        self.assertEqual(result['refunded_credits'], 2)
        self.assertEqual(self.credits(), 2)

    def test_telegram_failure_does_not_fail_a_successful_run(self):
        self.add_site(['Keuangan'])
        self.telegram.side_effect = RuntimeError('telegram down')
        result = rj.deep_research_job(1, True, 1, None, charged_credits=1)
        self.assertEqual((result['successful_categories'], result['refunded_credits'], result['reason']),
                         (1, 0, None))


class ProgressTests(ResearchJobTestCase):
    def test_progress_and_message_before_each_category(self):
        self.add_site(['Keuangan', 'Parenting'])
        rj.deep_research_job(1, False, 1, None)
        messages = [(s['progress'], s['message']) for s in self.job.snapshots]
        self.assertIn((0, "Meriset kategori 'Keuangan' (1/2)..."), messages)
        self.assertIn((50, "Meriset kategori 'Parenting' (2/2)..."), messages)
        self.assertEqual(self.job.snapshots[-1]['progress'], 100)


class SavedEvidenceTests(ResearchJobTestCase):
    def run_with(self, extra_metadata, **extra):
        original = FakeSEO.research_category

        def research_category(seo, name, language='id'):
            data = original(seo, name, language)
            data['source_metadata'].update(extra_metadata)
            data.update(extra)
            return data

        self.add_site(['Keuangan'])
        with patch.object(FakeSEO, 'research_category', research_category):
            rj.deep_research_job(1, False, 1, None)
        with self.db.get_session() as s:
            row = s.query(ResearchData).first()
            return row.is_fallback, row.official_sources

    def test_optional_sources_missing_is_not_fallback(self):
        official = [{'title': 'OJK', 'url': 'https://www.ojk.go.id/x', 'passages': ['p']}]
        is_fallback, saved = self.run_with({'social': {'status': 'unavailable'}, 'youtube': {'status': 'unavailable'},
                                            'related_questions': {'status': 'real'}}, official_sources=official)
        self.assertFalse(is_fallback)
        self.assertEqual(saved, official)

    def test_template_questions_are_flagged(self):
        is_fallback, saved = self.run_with({'related_questions': {'status': 'fallback'}})
        self.assertTrue(is_fallback)
        self.assertEqual(saved, [])


class ClaudeEngineTests(ResearchJobTestCase):
    def run_with(self, from_config):
        created = []
        original_init = getattr(FakeSEO, '__init__')

        def init(seo):
            original_init(seo)
            created.append(seo)

        factory = types.ModuleType('services.claude_research')
        factory.from_config = from_config
        self.add_site(['Keuangan'])
        config = {'ai_text_provider': 'gemini', 'anthropic_api_key': 'shared-admin-key'}
        with patch.object(FakeSEO, '__init__', init), \
                patch.object(rj.core_extensions, 'load_config', Mock(return_value=config)) as load, \
                patch.dict(sys.modules, {'services.claude_research': factory}):
            result = rj.deep_research_job(1, False, 1, None)
        return result, created, load

    def test_engine_from_the_users_effective_config(self):
        engine = object()
        from_config = Mock(return_value=engine)
        result, created, load = self.run_with(from_config)
        load.assert_called_once_with(1)
        from_config.assert_called_once_with(load.return_value)
        self.assertIs(created[0].claude, engine)
        self.assertEqual(result['successful_categories'], 1)

    def test_factory_failure_keeps_classic_research(self):
        result, created, _ = self.run_with(Mock(side_effect=RuntimeError('broken')))
        self.assertFalse(hasattr(created[0], 'claude'))
        self.assertEqual(result['successful_categories'], 1)


class TopicTests(ResearchJobTestCase):
    def test_observed_evidence_is_passed_to_supported_parameters(self):
        self.add_site(['Keuangan'])
        rj.deep_research_job(1, False, 1, None)
        self.assertEqual(self.trending.calls, [{'suggestions': ['kw'], 'questions': ['q?'],
                                                'long_tail': ['long tail kw'], 'keywords': None}])

    def test_topics_repeating_a_published_core_or_the_category_are_dropped(self):
        self.add_site(['Digitalisasi Pendidikan'])
        with self.db.get_session() as s:
            s.add(PostLog(user_id=1, site_id=1, category_name='Digitalisasi Pendidikan', success=True,
                          title='Asesmen Digital Sekolah: Rencana Aksi 2026', result='ok'))
        self.trending.topics = (['digitalisasi pendidikan adalah', 'panduan asesmen digital sekolah',
                                 'literasi data guru', 'literasi data guru 2026']
                                + [f'topik khusus {word}' for word in ('rapor', 'kantin', 'seragam', 'upacara', 'koperasi', 'perpustakaan',
                                                                    'ekskul', 'pramuka', 'lab', 'uks', 'osis', 'bos')])
        rj.deep_research_job(1, False, 1, None)
        with self.db.get_session() as s:
            topics = [t['topic'] for t in s.query(ResearchData).one().suggested_topics]
        self.assertEqual(topics[0], 'literasi data guru')
        self.assertNotIn('digitalisasi pendidikan adalah', topics)
        self.assertNotIn('panduan asesmen digital sekolah', topics)
        self.assertNotIn('literasi data guru 2026', topics)
        self.assertEqual(len(topics), rj.TOPIC_SUGGESTION_COUNT)

    def test_real_engine_signature_is_wired(self):
        # trending_research imports pandas/pytrends, so read its signature from source.
        import ast
        from pathlib import Path
        tree = ast.parse(Path(__file__).resolve().parent.parent.joinpath('trending_research.py')
                         .read_text(encoding='utf-8'))
        func = next(node for node in ast.walk(tree)
                    if isinstance(node, ast.FunctionDef) and node.name == 'build_topic_suggestions')
        params = {arg.arg for arg in func.args.args + func.args.kwonlyargs}
        self.assertTrue({'suggestions', 'questions', 'long_tail'} <= params)

    def test_research_without_topics_is_saved_and_reported(self):
        self.add_site(['Keuangan'])
        self.trending.topics = []
        result = rj.deep_research_job(1, True, 1, None, charged_credits=1)
        self.assertEqual(self.saved_categories(), ['Keuangan'])
        self.assertEqual(result['categories_without_topics'], ['Keuangan'])
        self.assertIn('tidak ditemukan topik', result['reason'])
        self.assertIn('Tidak ditemukan topik', self.telegram.call_args.args[1])
        # The topic picker skips the row without consuming it.
        self.assertIsNone(self.db.get_unused_research_topic(1, 1, 'Keuangan'))
        with self.db.get_session() as s:
            self.assertFalse(s.query(ResearchData).one().used)


class CategoryNormalizationTests(ResearchJobTestCase):
    def test_requested_spelling_variant_is_researched_once(self):
        self.add_site(['Tips', 'tips ', 'Parenting'])
        result = rj.deep_research_job(1, True, 1, 'tips ', charged_credits=1)
        self.assertEqual(self.saved_categories(), ['Tips'])
        self.assertEqual(result['refunded_credits'], 0)

    def test_duplicates_charged_once_by_the_route_are_researched_once(self):
        self.add_site(['Tips', 'TIPS', 'Parenting'])
        result = rj.deep_research_job(1, True, 1, None, charged_credits=2)
        self.assertEqual(self.saved_categories(), ['Tips', 'Parenting'])
        self.assertEqual(result['refunded_credits'], 0)

    def test_scheduled_run_limited_to_requested_categories(self):
        self.add_site(['Keuangan', 'Parenting'])
        result = rj.deep_research_job(1, False, 1, None, categories=['parenting'])
        self.assertEqual(self.saved_categories(), ['Parenting'])
        self.assertEqual(result['refunded_credits'], 0)
        self.assertEqual(self.credits(), 0)


class ReservationAndLockTests(ResearchJobTestCase):
    def start(self, charged):
        database.acquire_research_lock(self.redis, 1, self.job.id, 4000)
        database.record_research_charge(self.redis, self.job.id, 1, 1, charged, 600, now=self.redis.now)

    def test_job_takes_its_record_and_releases_the_lock(self):
        self.add_site(['Keuangan', 'Parenting'])
        FakeSEO.failing = {'Parenting'}
        self.start(2)
        result = rj.deep_research_job(1, True, 1, None, charged_credits=2, charge_recorded=True)
        self.assertEqual(result['refunded_credits'], 1)
        self.assertEqual(self.credits(), 1)
        self.assertIsNone(database.read_research_charge(self.redis, self.job.id))
        self.assertIsNone(database.get_research_lock(self.redis, 1))

    def test_progress_is_recorded_for_reconciliation(self):
        self.add_site(['Keuangan', 'Parenting'])
        self.start(2)
        seen = []
        original = rj._research_category

        def spy(*args):
            seen.append(database.read_research_charge(self.redis, self.job.id)['successful'])
            return original(*args)

        with patch.object(rj, '_research_category', spy):
            rj.deep_research_job(1, True, 1, None, charged_credits=2, charge_recorded=True)
        self.assertEqual(seen, [0, 1])

    def test_record_already_reconciled_means_no_second_refund(self):
        self.add_site(['Keuangan'])
        FakeSEO.failing = {'Keuangan'}
        self.start(1)
        database.take_research_charge(self.redis, self.job.id)  # the dispatcher settled it
        result = rj.deep_research_job(1, True, 1, None, charged_credits=1, charge_recorded=True)
        self.assertEqual(result['refunded_credits'], 0)
        self.assertEqual(self.credits(), 0)

    def test_lock_of_another_job_is_left_alone(self):
        self.add_site(['Keuangan'])
        database.acquire_research_lock(self.redis, 1, 'other-job', 4000)
        rj.deep_research_job(1, False, 1, None)
        self.assertEqual(database.get_research_lock(self.redis, 1), 'other-job')


class ScheduledNotificationTests(ResearchJobTestCase):
    def test_scheduled_success_is_silent(self):
        self.add_site(['Keuangan'])
        rj.deep_research_job(1, False, 1, None)
        self.telegram.assert_not_called()

    def test_scheduled_partial_failure_is_silent(self):
        self.add_site(['Keuangan', 'Parenting'])
        FakeSEO.failing = {'Parenting'}
        rj.deep_research_job(1, False, 1, None)
        self.telegram.assert_not_called()

    def test_scheduled_total_failure_notifies_once_a_day(self):
        self.add_site(['Keuangan'])
        FakeSEO.failing = {'Keuangan'}
        rj.deep_research_job(1, False, 1, None)
        rj.deep_research_job(1, False, 1, None)
        self.assertEqual(self.telegram.call_count, 1)
        self.assertIn('Riset Gagal', self.telegram.call_args.args[1])

    def test_manual_runs_always_notify(self):
        self.add_site(['Keuangan'])
        rj.deep_research_job(1, True, 1, None, charged_credits=1)
        rj.deep_research_job(1, True, 1, None, charged_credits=1)
        self.assertEqual(self.telegram.call_count, 2)


class RefundFailureHandBackTests(ResearchJobTestCase):
    def test_failed_refund_puts_the_record_back_for_reconciliation(self):
        self.add_site(['Keuangan', 'Parenting'])
        FakeSEO.failing = {'Parenting'}
        database.record_research_charge(self.redis, self.job.id, 1, 1, 2, 600, now=self.redis.now)
        with patch.object(self.db, 'refund_user_credits', side_effect=RuntimeError('db down')):
            result = rj.deep_research_job(1, True, 1, None, charged_credits=2, charge_recorded=True)
        self.assertEqual(result['refunded_credits'], 0)
        record = database.read_research_charge(self.redis, self.job.id)
        self.assertTrue(record['needs_refund'])
        self.assertEqual(database.research_charge_owed(record), 1)


class FreshnessTests(unittest.TestCase):
    def test_single_boundary(self):
        now = datetime(2026, 10, 14, 12, 0)
        self.assertTrue(database.is_research_fresh(now - timedelta(days=35), now))
        self.assertFalse(database.is_research_fresh(now - timedelta(days=35, seconds=1), now))
        self.assertFalse(database.is_research_fresh(None, now))
        self.assertEqual(database.research_fresh_cutoff(now), now - timedelta(days=35))
        # Monthly refresh, days before expiry.
        self.assertEqual(database.SCHEDULED_RESEARCH_REFRESH_DAYS, 30)
        self.assertLess(database.SCHEDULED_RESEARCH_REFRESH_DAYS, database.MAX_RESEARCH_AGE_DAYS)
        self.assertLess(database.EARLY_REFRESH_MIN_AGE_DAYS, database.SCHEDULED_RESEARCH_REFRESH_DAYS)

    def test_uses_local_naive_clock(self):
        # researched_at is written with datetime.now(); a just-written row is fresh.
        self.assertTrue(database.is_research_fresh(datetime.now()))


if __name__ == '__main__':
    unittest.main()
