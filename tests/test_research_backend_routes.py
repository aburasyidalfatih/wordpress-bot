"""Research routes: per-site lock (409 without charge), manual-research parameters,
active job, research_data eligibility/freshness, title generation parsing and limits."""
import json
import unittest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

from flask import Flask

import database
from models import ContentQueue, PostLog, ResearchData, User, WordPressSite
from test_research_backend_support import FakeRedis, load_with_stubbed_core, make_db

research, core = load_with_stubbed_core('routes.research')


class RouteTestCase(unittest.TestCase):
    def setUp(self):
        self.db = make_db()
        with self.db.get_session() as s:
            s.add(User(id=1, email='u@example.com', credits=5))
            s.add(User(id=2, email='o@example.com', credits=5))
            s.add(WordPressSite(id=1, user_id=1, site_name='Site', wordpress_url='https://example.com',
                                language='id',
                                selected_categories=[{'id': 1, 'name': 'Tips'}, {'id': 2, 'name': 'tips '},
                                                     {'id': 3, 'name': 'Parenting'}],
                                categories=[{'id': 1, 'name': 'Tips', 'description': 'Tips harian'}]))
            s.add(WordPressSite(id=2, user_id=2, site_name='Other', wordpress_url='https://o.example.com'))
        self.redis = FakeRedis()
        self.queue = Mock()
        self.queue.enqueue.side_effect = lambda *a, **k: Mock(id=k.get('job_id'))
        self.statuses = {}
        core.redis_conn = self.redis
        core.research_q = self.queue
        self.addCleanup(setattr, core, 'redis_conn', None)
        self.addCleanup(setattr, core, 'research_q', None)
        patches = [
            patch.object(research, 'db', self.db),
            patch.object(research, '_rq_job_status', lambda job_id: self.statuses.get(job_id, 'missing')),
            patch.object(research, '_research_workers_available', lambda: True),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        app = Flask(__name__)
        app.register_blueprint(research.research_bp)
        self.client = app.test_client()

    def credits(self, user_id=1):
        with self.db.get_session() as s:
            return s.get(User, user_id).credits


class ManualResearchTests(RouteTestCase):
    def test_success_reserves_locks_records_and_reports_remaining(self):
        res = self.client.post('/manual-research?site_id=1')
        body = res.get_json()
        self.assertEqual(res.status_code, 200, body)
        job_id = body['job_id']
        # "Tips" and "tips " are one category: 2 credits, not 3.
        self.assertEqual(body['credits_deducted'], 2)
        self.assertEqual(body['remaining_credits'], 3)
        self.assertEqual(self.credits(), 3)
        self.assertEqual(database.get_research_lock(self.redis, 1), job_id)
        record = database.read_research_charge(self.redis, job_id)
        self.assertEqual((record['user_id'], record['charged'], record['site_id']), (1, 2, 1))
        args, kwargs = self.queue.enqueue.call_args
        self.assertEqual(args, ('tasks.research_jobs.deep_research_job', 1, True, 1, None))
        self.assertEqual(kwargs['job_id'], job_id)
        self.assertTrue(kwargs['charge_recorded'])
        self.assertEqual(kwargs['charged_credits'], 2)

    def test_second_request_gets_409_without_charge(self):
        first = self.client.post('/manual-research?site_id=1').get_json()
        self.statuses[first['job_id']] = 'queued'
        res = self.client.post('/manual-research', json={'site_id': 1, 'category': 'Parenting'})
        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.get_json(), {'success': False, 'error': 'Riset untuk website ini masih berjalan.',
                                          'job_id': first['job_id']})
        self.assertEqual(self.credits(), 3)
        self.assertEqual(self.queue.enqueue.call_count, 1)

    def test_lock_of_a_finished_job_does_not_block(self):
        database.acquire_research_lock(self.redis, 1, 'old-job')
        self.statuses['old-job'] = 'finished'
        res = self.client.post('/manual-research?site_id=1&category=Parenting')
        self.assertEqual(res.status_code, 200)

    def test_enqueue_failure_refunds_and_releases(self):
        self.queue.enqueue.side_effect = RuntimeError('redis down')
        res = self.client.post('/manual-research?site_id=1')
        self.assertEqual(res.status_code, 500)
        self.assertEqual(self.credits(), 5)
        self.assertIsNone(database.get_research_lock(self.redis, 1))
        self.assertEqual(list(database.research_charge_job_ids(self.redis)), [])

    def test_category_from_query_or_body_and_normalized(self):
        res = self.client.post('/manual-research?category=TIPS', json={'site_id': 1})
        self.assertEqual(res.status_code, 200, res.get_json())
        self.assertEqual(self.queue.enqueue.call_args.args[4], 'Tips')
        self.assertEqual(res.get_json()['credits_deducted'], 1)

    def test_all_is_not_special(self):
        res = self.client.post('/manual-research', json={'site_id': 1, 'category': 'all'})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(self.credits(), 5)

    def test_empty_category_means_all(self):
        res = self.client.post('/manual-research', json={'site_id': 1, 'category': ''})
        self.assertEqual(res.get_json()['credits_deducted'], 2)

    def test_no_research_worker_is_503_without_charge(self):
        with patch.object(research, '_research_workers_available', lambda: False):
            res = self.client.post('/manual-research?site_id=1')
        self.assertEqual(res.status_code, 503)
        self.assertEqual(res.get_json()['error'], 'Layanan riset sedang tidak aktif. Hubungi admin.')
        self.assertEqual(self.credits(), 5)
        self.assertIsNone(database.get_research_lock(self.redis, 1))
        self.queue.enqueue.assert_not_called()

    def test_lock_of_a_job_being_enqueued_is_409_without_job_id(self):
        database.acquire_research_lock(self.redis, 1, 'just-taken')  # job does not exist yet
        res = self.client.post('/manual-research?site_id=1')
        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.get_json(), {'success': False, 'error': 'Riset sedang dimulai, coba lagi sebentar.'})
        self.assertEqual(self.credits(), 5)

    def test_long_queued_job_keeps_the_site_busy(self):
        # Liveness follows the job's RQ status, not the lock's age or TTL.
        database.acquire_research_lock(self.redis, 1, 'waiting-job', now=1)
        self.statuses['waiting-job'] = 'queued'
        res = self.client.post('/manual-research?site_id=1')
        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.get_json()['job_id'], 'waiting-job')
        self.assertEqual(self.credits(), 5)

    def test_missing_job_past_the_grace_period_is_stale(self):
        database.acquire_research_lock(self.redis, 1, 'vanished', now=1)
        res = self.client.post('/manual-research?site_id=1&category=Parenting')
        self.assertEqual(res.status_code, 200)

    def test_refund_failure_after_enqueue_failure_keeps_the_record(self):
        self.queue.enqueue.side_effect = RuntimeError('redis down')
        with patch.object(self.db, 'refund_user_credits', side_effect=RuntimeError('db down')):
            res = self.client.post('/manual-research?site_id=1')
        self.assertEqual(res.status_code, 500)
        (job_id,) = database.research_charge_job_ids(self.redis)
        record = database.read_research_charge(self.redis, job_id)
        self.assertTrue(record['needs_refund'])
        self.assertEqual(database.research_charge_owed(record), 2)

    def test_insufficient_credits_releases_lock(self):
        with self.db.get_session() as s:
            s.get(User, 1).credits = 1
        res = self.client.post('/manual-research?site_id=1')
        self.assertEqual(res.status_code, 400)
        self.assertIsNone(database.get_research_lock(self.redis, 1))


class ActiveResearchTests(RouteTestCase):
    def test_reports_live_job_only_for_owned_site(self):
        self.assertEqual(self.client.get('/api/research/active?site_id=1').get_json(),
                         {'success': True, 'job_id': None})
        database.acquire_research_lock(self.redis, 1, 'job-1')
        self.statuses['job-1'] = 'started'
        self.assertEqual(self.client.get('/api/research/active?site_id=1').get_json()['job_id'], 'job-1')
        self.assertEqual(self.client.get('/api/research/active?site_id=2').status_code, 404)
        self.statuses['job-1'] = 'failed'
        self.assertIsNone(self.client.get('/api/research/active?site_id=1').get_json()['job_id'])
        self.assertIsNone(database.get_research_lock(self.redis, 1))  # stale lock cleared


class ResearchDataTests(RouteTestCase):
    def add_run(self, run_id, category, age, confidence='high', **extra):
        stamp = datetime.now() - age
        with self.db.get_session() as s:
            s.add(ResearchData(id=run_id, user_id=1, site_id=1, category=category, keywords=['kw'],
                               confidence_level=confidence, researched_at=stamp, created_at=stamp, **extra))

    def test_latest_two_runs_per_category(self):
        for i in range(5):
            self.add_run(10 + i, 'Tips', timedelta(days=5 - i), trend_score=i)
        self.add_run(20, 'Parenting', timedelta(days=1))
        with self.db.get_session() as s:
            runs = research._latest_runs_by_category(s, 1, 1, ['Tips', 'Parenting'])
            self.assertEqual([r.id for r in runs['Tips']], [14, 13])
            self.assertEqual([r.id for r in runs['Parenting']], [20])

    def test_eligibility_and_staleness(self):
        self.add_run(1, 'Tips', timedelta(days=1))
        self.add_run(2, 'Parenting', timedelta(days=36))
        with patch.object(research, '_load_search_console_opportunities', return_value=([], [], None)):
            data = self.client.get('/api/research_data?site_id=1').get_json()['research_data']
        self.assertEqual((data['Tips']['eligible_for_titles'], data['Tips']['title_block_reason'],
                          data['Tips']['is_stale']), (True, None, False))
        # The duplicate spelling shows the same research.
        self.assertTrue(data['tips ']['eligible_for_titles'])
        self.assertEqual((data['Parenting']['eligible_for_titles'], data['Parenting']['title_block_reason'],
                          data['Parenting']['is_stale']), (False, 'Data riset sudah lebih dari 35 hari', True))

    def test_block_reasons(self):
        now = datetime.now()
        weak = ResearchData(confidence_level='insufficient', researched_at=now)
        self.assertEqual(research._title_block_reason(None), 'Belum ada riset')
        self.assertEqual(research._title_block_reason(weak), 'Bukti riset belum cukup')


class WorkerCheckTests(unittest.TestCase):
    def test_counts_workers_on_the_research_queue(self):
        with patch('rq.Worker.count', return_value=0) as count:
            self.assertFalse(research._research_workers_available())
        self.assertIs(count.call_args.kwargs['queue'], core.research_q)
        with patch('rq.Worker.count', return_value=1):
            self.assertTrue(research._research_workers_available())

    def test_introspection_failure_does_not_block(self):
        with patch('rq.Worker.count', side_effect=RuntimeError('redis hiccup')):
            self.assertTrue(research._research_workers_available())


class TitleParsingTests(unittest.TestCase):
    def test_extracts_first_array_from_fences_and_prose(self):
        text = 'Berikut judulnya:\n```json\n["Judul A", "Judul B", "Judul A"]\n```\nSemoga [membantu].'
        self.assertEqual(research._parse_title_response(text), ['Judul A', 'Judul B'])
        self.assertEqual(research._parse_title_response('[{"title": "Satu"}, 2, "  Dua  "]'), ['Satu', 'Dua'])
        self.assertEqual(research._parse_title_response('Catatan [1] lalu ["X"]'), ['X'])

    def test_unparseable_output_raises(self):
        for text in ('maaf, tidak bisa', '["a", ', '[]', '{"titles": 1}'):
            with self.subTest(text=text):
                with self.assertRaises(research._TitleParseError):
                    research._parse_title_response(text)

    def test_number_of_titles_is_capped(self):
        titles = json.dumps([f'Judul {i}' for i in range(500)])
        self.assertEqual(len(research._parse_title_response(titles)), research.MAX_AI_TITLES_PROCESSED)


class GenerateTitlesTests(RouteTestCase):
    def setUp(self):
        super().setUp()
        with self.db.get_session() as s:
            now = datetime.now()
            s.add(ResearchData(user_id=1, site_id=1, category='Tips', keywords=['kw'], questions=[],
                               confidence_level='high', researched_at=now, created_at=now))
        self.generator = Mock()
        patches = [
            patch.object(research, 'check_ai_helper_quota', Mock(return_value=None)),
            patch.object(research, 'load_config', Mock(return_value={})),
            patch.object(research, 'ArticleGenerator', Mock(**{'from_config.return_value': self.generator})),
            patch.object(research, '_title_evidence', Mock(return_value=([], []))),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_success_reports_queued_count(self):
        self.generator.generate_text.return_value = '```json\n["Cara Hemat Listrik", "Resep Kue Lebaran"]\n```'
        res = self.client.post('/api/generate-titles/tips%20?site_id=1', json={'count': 5})
        body = res.get_json()
        self.assertEqual(res.status_code, 200, body)
        self.assertEqual(body['queued'], 2)
        with self.db.get_session() as s:
            self.assertEqual({q.category for q in s.query(ContentQueue)}, {'Tips'})

    def test_category_with_slash_is_routed(self):
        res = self.client.post('/api/generate-titles/Hukum/Perdata?site_id=1', json={})
        self.assertEqual(res.status_code, 400)  # reached the view: no research for it
        self.assertIn('riset', res.get_json()['error'])

    def test_parse_failure_is_502_and_refunds_quota(self):
        self.redis.set('ratelimit:ai_titles:1', 3)
        self.generator.generate_text.return_value = 'Maaf, saya tidak bisa.'
        res = self.client.post('/api/generate-titles/Tips?site_id=1', json={})
        self.assertEqual(res.status_code, 502)
        self.assertEqual(int(self.redis.get('ratelimit:ai_titles:1')), 2)
        with self.db.get_session() as s:
            self.assertEqual(s.query(ContentQueue).count(), 0)

    def test_prompt_asks_for_distinct_intents_and_core_repeats_are_dropped(self):
        now = datetime.now()
        with self.db.get_session() as s:
            s.add(ResearchData(user_id=1, site_id=1, category='Digitalisasi Pendidikan', keywords=['kw'],
                               questions=[], confidence_level='high', researched_at=now, created_at=now))
            s.add(PostLog(user_id=1, site_id=1, category_name='Digitalisasi Pendidikan', success=True,
                          title='Peta Jalan Asesmen Digital 2026: Rencana Aksi Sekolah', result='ok',
                          created_at=now))
        self.generator.generate_text.return_value = json.dumps([
            'Digitalisasi Pendidikan 2026: Literasi Data Guru',          # restates the category
            'Panduan Asesmen Digital 2026: Bank Soal Daring',            # repeats a published head
            'Literasi Data Guru untuk Membaca Rapor Pendidikan',
            'Siasat Literasi Data Guru untuk Membaca Rapor Pendidikan',  # repeats the title above
            'Cara Sekolah Swasta Memilih LMS yang Hemat',
        ])
        res = self.client.post('/api/generate-titles/Digitalisasi%20Pendidikan?site_id=1', json={'count': 5})
        self.assertEqual(res.status_code, 200, res.get_json())
        prompt = self.generator.generate_text.call_args.args[0]
        self.assertIn('MAKSUD PENCARIAN BERBEDA', prompt)
        self.assertIn('nama kategori "Digitalisasi Pendidikan"', prompt)
        self.assertIn('- Peta Jalan Asesmen Digital 2026: Rencana Aksi Sekolah', prompt)
        with self.db.get_session() as s:
            queued = [q.title for q in s.query(ContentQueue).order_by(ContentQueue.id)]
        self.assertEqual(queued, ['Literasi Data Guru untuk Membaca Rapor Pendidikan',
                                  'Cara Sekolah Swasta Memilih LMS yang Hemat'])

    def test_english_prompt_rules(self):
        block = research._distinct_intent_block('Debt Payoff Strategies', 'en', ['A', 'a', 'B'])
        self.assertIn('DISTINCT SEARCH INTENTS', block)
        self.assertIn('category name "Debt Payoff Strategies"', block)
        self.assertEqual(block.count('\n- A\n'), 1)
        self.assertNotIn('JUDUL', block)

    def test_dedupe_ignores_failed_and_old_queue_items(self):
        with self.db.get_session() as s:
            s.add(ContentQueue(user_id=1, site_id=1, title='Cara Hemat Listrik', status='failed'))
        self.generator.generate_text.return_value = '["Cara Hemat Listrik"]'
        res = self.client.post('/api/generate-titles/Tips?site_id=1', json={})
        self.assertEqual(res.get_json()['queued'], 1)


class MiscRouteTests(RouteTestCase):
    def test_clear_research_validates_site_id(self):
        self.assertEqual(self.client.post('/api/clear-research', data='nope').status_code, 400)
        self.assertEqual(self.client.post('/api/clear-research', json={'site_id': 'x'}).status_code, 400)
        self.assertEqual(self.client.post('/api/clear-research', json={'site_id': 1}).status_code, 200)

    def test_trend_lookups_are_rate_limited(self):
        trending = Mock()
        trending.get_trending_topics.return_value = {'related_top': []}
        with patch.object(research, 'trending', trending):
            codes = [self.client.get('/api/trending/Tips').status_code for _ in range(11)]
        self.assertEqual(codes[:10], [200] * 10)
        self.assertEqual(codes[10], 429)
        self.assertEqual(self.client.get('/api/trending/' + 'x' * 201).status_code, 400)


if __name__ == '__main__':
    unittest.main()
