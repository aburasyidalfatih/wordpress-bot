"""Writing brief and helpfulness assessment inside the article jobs.

Order: brief -> generate -> quality gate -> assess (-> rewrite -> gate -> assess)
-> fact-check review -> image -> publish. A quality rejection is a content
failure (refund, topic consumed); an unavailable assessor is not (refund, topic
handed back). Model calls are scripted per system prompt; no network.
"""
import json
import sys
import time
import types
import unittest
from datetime import datetime
from unittest.mock import Mock, patch

from models import ContentQueue, PostLog, ResearchData, User, WordPressSite
from services import ai_costs, article_quality, article_review, content_brief, job_locks
from services.article_quality import ArticleQualityRejected, ArticleQualityUnavailable
from rq.timeouts import JobTimeoutException

from test_article_quality_support import LockRedis
from test_research_backend_support import load_with_stubbed_core, make_db

jobs, _core = load_with_stubbed_core('tasks.article_jobs')

CONTENT = '<h2>Satu</h2><p>Catat utang.</p><h2>Dua</h2><p>Bayar yang terkecil dulu.</p>'
REWRITTEN = '<h2>Satu</h2><p>Catat utang beserta bunganya.</p><h2>Dua</h2><p>Contoh perhitungan.</p>'

BRIEF = {
    'search_intent': 'Pembaca ingin melunasi utang keluarga.',
    'reader': {'who': 'Keluarga muda', 'situation': 'Cicilan menumpuk', 'needs': ['urutan pelunasan']},
    'must_answer': ['Utang mana yang dilunasi dulu?'],
    'competitor_coverage': 'Halaman teratas membahas metode bola salju.',
    'information_gain': ['Contoh perhitungan dengan angka pembaca'],
    'angle': 'Melunasi utang tanpa mengorbankan kebutuhan pokok.',
    'format': {'type': 'how-to', 'why': 'Butuh langkah.'},
    'outline': ['Daftar utang', 'Pilih metode'],
    'key_facts': [],
    'cautions': ['Bunga berbeda-beda'],
    'avoid': ['Janji lunas cepat'],
}


def scores(default, **overrides):
    values = {criterion: default for criterion in article_quality.CRITERIA}
    values.update(overrides)
    return json.dumps({'scores': values, 'summary': 'Ringkasan penilai',
                       'revision_instructions': ['Tambahkan contoh perhitungan di bagian Dua']})


class QualityJobTestCase(unittest.TestCase):
    def setUp(self):
        self.db = make_db()
        now = datetime.now()
        with self.db.get_session() as s:
            s.add(User(id=1, email='u@example.com', credits=10))
            s.add(WordPressSite(
                id=1, user_id=1, site_name='Site', wordpress_url='https://example.com',
                wordpress_username='admin', auto_post=True, language='id',
                categories=[{'id': 7, 'name': 'Keuangan', 'description': 'Keuangan keluarga'}],
                selected_categories=[{'id': 7, 'name': 'Keuangan'}],
            ))
            s.add(ResearchData(id=1, user_id=1, site_id=1, category='Keuangan', keywords=['kw kategori'],
                               suggested_topics=[{'topic': 'Investasi emas', 'is_trending': False},
                                                 {'topic': 'Dana darurat', 'is_trending': False}],
                               confidence_level='high', researched_at=now, created_at=now))
            s.add(PostLog(id=10, user_id=1, site_id=1, post_id=55, title='Judul Lama',
                          category_name='Keuangan', success=True, result='x'))
        self.order = []
        # Scripted replies per kind of call.
        self.replies = {'brief': [json.dumps(BRIEF)], 'assess': [scores(5)],
                        'review': [json.dumps({'verdict': 'approve'})]}
        self.generator = Mock()
        self.generator.generate_text.side_effect = self.model_reply
        self.generator.generate_checked_article.side_effect = self.write
        self.generator.generate_article.side_effect = self.rewrite
        self.generator.generate_image.side_effect = lambda *a, **k: self.order.append('image')
        self.publisher = Mock()
        self.publisher.get_recent_posts.return_value = []
        self.publisher.create_post.side_effect = lambda *a, **k: (
            self.order.append('publish') or (True, {'id': 1, 'link': 'https://example.com/p'}))
        self.publisher.update_post_content.side_effect = lambda *a, **k: (
            self.order.append('update') or (True, {'id': 55}))
        self.gate = Mock(side_effect=lambda *a, **k: self.order.append('gate') or (True, [], []))
        self.notify = Mock()
        patches = [
            patch.object(jobs, 'db', self.db),
            patch.object(jobs, 'load_config', Mock(return_value={})),
            patch.object(jobs, 'ArticleGenerator', Mock(**{'from_config.return_value': self.generator})),
            patch.object(jobs, 'WordPressPublisher', Mock(return_value=self.publisher)),
            patch.object(jobs, 'check_article', self.gate),
            patch.object(jobs, '_merge_topic_research', lambda seo, *a, **k: seo),
            patch.object(jobs, 'load_search_metrics', Mock(return_value=([], []))),
            patch.object(jobs, '_current_job', lambda: None),
            patch.object(jobs, 'send_telegram_notification', self.notify),
            patch.object(article_review, 'RETRY_DELAY_SECONDS', 0),
            patch.object(article_quality, 'RETRY_DELAY_SECONDS', 0),
            patch.object(content_brief, 'RETRY_DELAY_SECONDS', 0),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def model_reply(self, prompt, system=None, **kwargs):
        kind = {content_brief.SYSTEM_PROMPT: 'brief', article_quality.SYSTEM_PROMPT: 'assess',
                article_review.SYSTEM_PROMPT: 'review'}.get(system)
        if kind is None:
            return json.dumps({'same_intent': False})  # topic similarity confirmation
        self.order.append(kind)
        queue = self.replies[kind]
        reply = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(reply, BaseException):
            raise reply
        return reply

    def write(self, *args, **kwargs):
        self.order.append('generate')
        return {'title': 'Strategi Melunasi Utang Keluarga', 'content': CONTENT, 'focus_keyword': 'utang',
                'meta_description': 'Meta deskripsi yang cukup panjang untuk artikel ini dan tetap akurat.'}

    def rewrite(self, *args, **kwargs):
        self.order.append('rewrite')
        return {'title': 'Strategi Melunasi Utang Keluarga dengan Contoh', 'content': REWRITTEN,
                'focus_keyword': 'utang', 'meta_description': 'Meta deskripsi revisi yang cukup panjang dan akurat.'}

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

    def log10(self):
        with self.db.get_session() as s:
            log = s.get(PostLog, 10)
            s.expunge(log)
            return log

    def post(self):
        jobs.generate_and_post(1, site_id=1, credit_pre_reserved=True, manual=True)


class GenerateAndPostQualityTests(QualityJobTestCase):
    def test_passing_article_order_brief_and_note(self):
        self.post()
        self.assertEqual(self.order, ['brief', 'generate', 'gate', 'assess', 'review', 'image', 'publish'])
        brief = self.generator.generate_checked_article.call_args.kwargs['content_brief']
        self.assertIn('[BRIEF PENULISAN]', brief)
        self.assertIn('Utang mana yang dilunasi dulu?', brief)
        # The brief saw the research and the publisher's category description.
        brief_prompt = self.generator.generate_text.call_args_list[0].args[0]
        self.assertIn('kw kategori', brief_prompt)
        self.assertIn('Keuangan keluarga', brief_prompt)
        # The assessor saw the brief.
        assess_prompt = next(c.args[0] for c in self.generator.generate_text.call_args_list
                             if c.kwargs.get('system') == article_quality.SYSTEM_PROMPT)
        self.assertIn('Utang mana yang dilunasi dulu?', assess_prompt.split('<<<END BRIEF')[0])
        log = self.last_log()
        self.assertTrue(log.success)
        self.assertEqual(log.result, jobs.RESULT_PUBLISHED_NO_IMAGE + ' Kualitas AI: 5,0/5 (tanpa revisi). '
                                     'Ditinjau AI: disetujui tanpa perbaikan isi.')
        self.generator.generate_article.assert_not_called()

    def test_rewrite_flow_publishes_the_better_draft(self):
        self.replies['assess'] = [scores(4, information_gain=2), scores(4, reader_fit=5, trust=5, completeness=5)]
        self.post()
        self.assertEqual(self.order, ['brief', 'generate', 'gate', 'assess', 'rewrite', 'gate', 'assess',
                                      'review', 'image', 'publish'])
        # The rewrite repeats the original generation call plus the revision request.
        first_call = self.generator.generate_checked_article.call_args
        rewrite_call = self.generator.generate_article.call_args
        self.assertEqual(rewrite_call.args, first_call.args)
        self.assertEqual(rewrite_call.kwargs['content_brief'], first_call.kwargs['content_brief'])
        revision = rewrite_call.kwargs['revision_request']
        self.assertIn('Tambahkan contoh perhitungan di bagian Dua', revision)
        self.assertIn('<p>Catat utang.</p>', revision.split('<<<PREVIOUS DRAFT')[1])
        args = self.publisher.create_post.call_args.args
        self.assertEqual(args[:2], ('Strategi Melunasi Utang Keluarga dengan Contoh', REWRITTEN))
        # The reviewer fact-checked the rewrite.
        review_prompt = self.generator.generate_text.call_args.args[0]
        self.assertIn('Contoh perhitungan.', review_prompt)
        self.assertEqual(self.last_log().result,
                         jobs.RESULT_PUBLISHED_NO_IMAGE + ' Kualitas AI: 4,4/5 (1 revisi). '
                         'Ditinjau AI: disetujui tanpa perbaikan isi.')
        success_message = self.notify.call_args.args[1]
        self.assertIn('⭐ <b>Kualitas AI:</b> 4,4/5 (1 revisi)', success_message)
        self.assertEqual(self.topics_left(), ['Dana darurat'])
        self.assertEqual(self.credits(), 10)

    def test_rejection_after_rewrite_is_a_content_failure(self):
        self.replies['assess'] = [scores(3, trust=2), scores(3, information_gain=2)]
        self.post()
        self.assertNotIn('review', self.order)
        self.publisher.create_post.assert_not_called()
        self.assertEqual(self.credits(), 11)  # refunded
        self.assertEqual(self.topics_left(), ['Dana darurat'])  # topic consumed
        log = self.last_log()
        self.assertEqual(log.title, 'GAGAL: Strategi Melunasi Utang Keluarga dengan Contoh')
        self.assertTrue(log.result.startswith('Artikel tidak diterbitkan: Artikel ditolak penilai kualitas AI: '
                                              'skor 2,9/5'))

    def test_rewrite_failing_the_gate_keeps_the_first_draft(self):
        self.replies['assess'] = [scores(4, information_gain=3)]
        self.gate.side_effect = [(True, [], []), (False, ['Only 1 H2 heading(s)'], []), (True, [], [])]
        self.post()
        self.assertEqual(self.publisher.create_post.call_args.args[1], CONTENT)
        self.assertIn('Kualitas AI: 3,9/5 (1 revisi, draf awal dipertahankan).', self.last_log().result)

    def test_unavailable_assessor_refunds_and_returns_the_topic(self):
        self.replies['assess'] = [ConnectionError('reset'), ConnectionError('reset')]
        self.post()
        self.publisher.create_post.assert_not_called()
        self.assertEqual(self.order.count('assess'), 2)  # one retry
        self.assertNotIn('review', self.order)
        self.assertEqual(self.credits(), 11)
        self.assertEqual(self.topics_left(), ['Investasi emas', 'Dana darurat'])
        self.assertTrue(self.last_log().result.startswith('Sistem Berhenti Tiba-tiba: Penilaian kualitas AI gagal'))

    def test_brief_failure_writes_without_a_brief(self):
        self.replies['brief'] = ['bukan json', 'bukan json juga']
        self.post()
        self.assertEqual(self.order.count('brief'), 2)
        self.assertIsNone(self.generator.generate_checked_article.call_args.kwargs['content_brief'])
        log = self.last_log()
        self.assertTrue(log.success)
        self.assertIn('Kualitas AI: 5,0/5 (tanpa revisi, tanpa brief penulisan).', log.result)

    def test_rewritten_title_repeating_a_published_article_is_dropped(self):
        with self.db.get_session() as s:
            s.add(PostLog(user_id=1, site_id=1, category_name='Keuangan',
                          title='Strategi Melunasi Utang Keluarga dengan Contoh Nyata', success=True, result='ok'))
        self.replies['assess'] = [scores(4, information_gain=2), scores(5)]
        with patch.object(jobs, 'find_similar_published',
                          lambda title, *a, **k: ('Strategi Melunasi Utang Keluarga dengan Contoh Nyata', 0.9)
                          if 'Contoh' in title else None):
            self.post()
        args = self.publisher.create_post.call_args.args
        self.assertEqual(args[:2], ('Strategi Melunasi Utang Keluarga', REWRITTEN))

    def test_queue_item_rejection_fails_and_refunds_the_item(self):
        with self.db.get_session() as s:
            s.add(ContentQueue(id=5, user_id=1, site_id=1, category='Keuangan', title='Cara Melunasi Utang',
                               status='posting', credit_held=True))
        self.replies['assess'] = [scores(2), scores(2)]
        jobs.generate_and_post(1, item_id=5, credit_pre_reserved=True)
        with self.db.get_session() as s:
            item = s.get(ContentQueue, 5)
            self.assertEqual(item.status, 'failed')
            self.assertFalse(item.credit_held)
        self.assertEqual(self.credits(), 11)

    def test_failure_classification(self):
        self.assertTrue(jobs._is_content_failure(ArticleQualityRejected(['x'])))
        self.assertFalse(jobs._is_content_failure(ArticleQualityUnavailable('x')))
        self.assertIn(ArticleQualityRejected, jobs.EDITORIAL_FAILURES)


class RegenerationQualityTests(QualityJobTestCase):
    def test_regeneration_gets_research_brief_assessment_and_rewrite(self):
        self.replies['assess'] = [scores(4, completeness=3), scores(5)]
        with self.db.get_session() as s:
            s.get(User, 1).credits = 4  # after the route's reservation
        jobs.regenerate_article_job(1, 10)
        self.assertEqual(self.order, ['brief', 'generate', 'gate', 'assess', 'rewrite', 'gate', 'assess',
                                      'review', 'update'])
        write_call = self.generator.generate_checked_article.call_args
        self.assertEqual(write_call.args[2], 'Judul Lama')
        self.assertEqual(write_call.args[3]['keywords'], ['kw kategori'])  # the writer gets the research
        self.assertEqual(write_call.kwargs['category_desc'], 'Keuangan keluarga')
        self.assertIn('[BRIEF PENULISAN]', write_call.kwargs['content_brief'])
        self.assertEqual(self.publisher.update_post_content.call_args.args[2], REWRITTEN)
        self.assertEqual(self.log10().result, jobs.RESULT_REGENERATED + ' Kualitas AI: 5,0/5 (1 revisi). '
                                                                        'Ditinjau AI: disetujui tanpa perbaikan isi.')
        self.assertEqual(self.credits(), 4)

    def test_regeneration_rejected_on_quality_refunds_and_keeps_the_post(self):
        self.replies['assess'] = [scores(2), scores(2)]
        with self.db.get_session() as s:
            s.get(User, 1).credits = 4
        jobs.regenerate_article_job(1, 10)
        self.publisher.update_post_content.assert_not_called()
        self.assertEqual(self.credits(), 5)
        self.assertTrue(self.log10().result.startswith(
            'Regenerasi artikel gagal: Artikel ditolak penilai kualitas AI: skor 2,0/5'))


class AICostSummaryTests(QualityJobTestCase):
    """One log line per article job with the estimated AI cost of each step."""

    COSTS = {'brief': 25_000, 'generate': 50_000, 'assess': 10_000, 'rewrite': 30_000, 'review': 40_000,
             'similar': 5_000}

    def setUp(self):
        super().setUp()
        reply, write, rewrite = self.model_reply, self.write, self.rewrite

        def billed(kind, result):
            # 1M Opus input tokens cost $4, so 25_000 tokens are $0.10.
            ai_costs.record_usage('anthropic', 'claude-opus-5-5', {'input_tokens': self.COSTS[kind]})
            return result

        def model_reply(prompt, system=None, **kwargs):
            result = reply(prompt, system=system, **kwargs)
            return billed(self.order[-1] if self.order and self.order[-1] in self.COSTS else 'similar', result)

        self.generator.generate_text.side_effect = model_reply
        self.generator.generate_checked_article.side_effect = lambda *a, **k: billed('generate', write(*a, **k))
        self.generator.generate_article.side_effect = lambda *a, **k: billed('rewrite', rewrite(*a, **k))

    def summary(self, logs):
        lines = [line for line in logs.output if 'Biaya AI artikel' in line]
        self.assertEqual(len(lines), 1)
        return lines[0]

    def test_published_article_cost_per_step(self):
        with self.assertLogs(jobs.logger, 'INFO') as logs:
            self.post()
        line = self.summary(logs)
        log_id = self.last_log().id
        self.assertIn(f"Biaya AI artikel {log_id} 'Strategi Melunasi Utang Keluarga'", line)
        for part in ('riset $0.00', 'brief $0.10', 'tulis $0.20', 'nilai $0.04', 'revisi $0.00', 'cek fakta $0.16'):
            self.assertIn(part, line)
        self.assertIn('total $0.50', line)

    def test_rewrite_and_research_costs_are_attributed(self):
        self.replies['assess'] = [scores(2), scores(5)]
        with self.assertLogs(jobs.logger, 'INFO') as logs:
            with patch.object(jobs, '_merge_topic_research',
                              lambda seo, *a, **k: ai_costs.add_cost('riset', 0.62) or seo):
                self.post()
        line = self.summary(logs)
        self.assertIn('nilai $0.08', line)  # two assessments
        self.assertIn('revisi $0.12', line)

    def test_failed_job_still_logs_its_cost(self):
        self.replies['review'] = [json.dumps({'verdict': 'reject', 'reasons': ['Klaim tanpa sumber']})]
        with self.assertLogs(jobs.logger, 'INFO') as logs:
            self.post()
        line = self.summary(logs)
        self.assertIn('cek fakta $0.16', line)
        self.assertIn(f"Biaya AI artikel {self.last_log().id} ", line)


class TopicResearchMergeTests(unittest.TestCase):
    def test_official_sources_reach_seo_data(self):
        official = [{'title': f'Sumber {i}', 'url': f'https://ojk.go.id/{i}', 'passages': [f'Kutipan {i}']}
                    for i in range(5)]
        official.insert(1, dict(official[0]))  # duplicate URL
        seo = types.ModuleType('seo_research')
        seo.SEOResearch = lambda: Mock(research_topic=Mock(return_value={'official_sources': official}))
        with patch.dict(sys.modules, {'seo_research': seo}):
            merged = jobs._merge_topic_research({'keywords': ['kw']}, 'Dana darurat', 'Keuangan')
        self.assertEqual([s['url'] for s in merged['official_sources']],
                         ['https://ojk.go.id/0', 'https://ojk.go.id/1', 'https://ojk.go.id/2'])
        self.assertEqual(merged['official_sources'][0]['passages'], ['Kutipan 0'])

    def test_site_host_is_excluded_from_topic_research(self):
        research = Mock(return_value={})
        seo = types.ModuleType('seo_research')
        seo.SEOResearch = lambda: Mock(research_topic=research)
        with patch.dict(sys.modules, {'seo_research': seo}):
            jobs._merge_topic_research({}, 'Dana darurat', 'Keuangan', exclude_hosts=['example.com'])
        self.assertEqual(research.call_args.kwargs['exclude_hosts'], ['example.com'])

    def test_claude_engine_comes_from_the_effective_ai_config(self):
        instances = []

        def make_research():
            instance = Mock(research_topic=Mock(return_value={}), claude=None)
            instances.append(instance)
            return instance

        seo = types.ModuleType('seo_research')
        seo.SEOResearch = make_research
        engine = object()
        factory = types.ModuleType('services.claude_research')
        factory.from_config = Mock(side_effect=lambda config: engine if config.get('anthropic_api_key') else None)
        config = {'ai_text_provider': 'gemini', 'anthropic_api_key': 'shared-admin-key'}
        with patch.dict(sys.modules, {'seo_research': seo, 'services.claude_research': factory}):
            jobs._merge_topic_research({}, 'Dana darurat', 'Keuangan', ai_config=config)
            jobs._merge_topic_research({}, 'Dana darurat', 'Keuangan', ai_config={'gemini_api_key': 'g'})
            jobs._merge_topic_research({}, 'Dana darurat', 'Keuangan')
        self.assertIs(instances[0].claude, engine)
        self.assertIsNone(instances[1].claude)
        self.assertIsNone(instances[2].claude)
        factory.from_config.assert_any_call(config)
        self.assertEqual(factory.from_config.call_count, 1)  # no Anthropic key: not even asked

    def test_rq_job_timeout_is_not_swallowed(self):
        seo = types.ModuleType('seo_research')
        seo.SEOResearch = lambda: Mock(research_topic=Mock(side_effect=JobTimeoutException('timeout')))
        with patch.dict(sys.modules, {'seo_research': seo}):
            with self.assertRaises(JobTimeoutException):
                jobs._merge_topic_research({}, 'Dana darurat', 'Keuangan')
        publisher = Mock(**{'get_recent_posts.side_effect': JobTimeoutException('timeout')})
        with self.assertRaises(JobTimeoutException):
            jobs._recent_posts_for_links(publisher)
        generator = Mock(**{'generate_image.side_effect': JobTimeoutException('timeout')})
        with self.assertRaises(JobTimeoutException):
            jobs._generate_featured_image(generator, Mock(), 'Keuangan', {'title': 'T'}, None, 'Site')
        with patch.object(jobs, 'load_search_metrics', Mock(side_effect=JobTimeoutException('timeout'))),                 patch.object(jobs, 'db', make_db()):
            with self.assertRaises(JobTimeoutException):
                jobs._attach_search_evidence({}, 1, 1, 'Keuangan')

    def test_own_pages_are_dropped_from_research(self):
        seo = {'competitor_outlines': [{'url': 'https://www.example.com/a', 'title': 'Milik sendiri'},
                                       {'url': 'https://blog.example.com/b', 'title': 'Subdomain'},
                                       {'url': 'https://pesaing.id/c', 'title': 'Pesaing'}],
               'news_insights': [{'link': 'https://example.com/berita'}, {'url': 'https://berita.id/x'}],
               'keywords': ['kw']}
        filtered = jobs._without_own_pages(seo, jobs._site_hosts('https://example.com'))
        self.assertEqual([c['title'] for c in filtered['competitor_outlines']], ['Pesaing'])
        self.assertEqual(filtered['news_insights'], [{'url': 'https://berita.id/x'}])
        self.assertEqual(len(seo['competitor_outlines']), 3)  # the input is not modified
        self.assertIs(jobs._without_own_pages(seo, []), seo)


class OwnSiteEvidenceJobTests(QualityJobTestCase):
    def test_own_site_competitor_never_reaches_brief_writer_assessor_or_reviewer(self):
        own = {'title': 'Artikel Kami Sendiri', 'url': 'https://example.com/lama', 'headers': ['Bagian kami']}
        other = {'title': 'Panduan Pesaing', 'url': 'https://pesaing.id/utang', 'headers': ['Bagian pesaing']}
        merge = Mock(side_effect=lambda seo, *a, **k: dict(seo or {}, competitor_outlines=[own, other]))
        with patch.object(jobs, '_merge_topic_research', merge):
            self.post()
        self.assertEqual(merge.call_args.kwargs['exclude_hosts'], ['example.com'])
        writer_seo = self.generator.generate_checked_article.call_args.args[3]
        self.assertEqual(writer_seo['competitor_outlines'], [other])
        for call in self.generator.generate_text.call_args_list:
            self.assertNotIn('Artikel Kami Sendiri', call.args[0])
        self.assertTrue(any('Panduan Pesaing' in c.args[0] for c in self.generator.generate_text.call_args_list))


class RegenerationLockJobTests(QualityJobTestCase):
    KEY = 'regenerate_article_lock:10'

    def run_job(self, holder='job-1', alive=False):
        self.redis = LockRedis()
        if holder:
            self.redis.set(self.KEY, holder, ex=6 * 3600)
        job = Mock(id='job-1', connection=self.redis)
        seen = {}
        original = jobs._regenerate_article

        def body(*args):
            seen['ttl'] = self.redis.ttl(self.KEY)
            return original(*args)
        with patch.object(jobs, '_current_job', lambda: job), patch.object(jobs, '_regenerate_article', body),                 patch.object(jobs, '_rq_job_is_alive', Mock(return_value=alive)):
            jobs.regenerate_article_job(1, 10)
        return seen

    def test_lock_is_shortened_while_running_and_released_after_success(self):
        seen = self.run_job(holder=job_locks.lock_value('job-1'))
        self.assertLessEqual(seen['ttl'], jobs.REGENERATION_LOCK_RUNNING_TTL_SECONDS)
        self.assertGreater(seen['ttl'], 45 * 60)
        self.assertIsNone(self.redis.get(self.KEY))
        self.assertEqual(self.redis.scripts, ['expire', 'delete'])  # atomic compare-and-expire/-delete
        self.assertTrue(self.log10().result.startswith(jobs.RESULT_REGENERATED))

    def test_lock_is_released_after_failure(self):
        self.replies['assess'] = [scores(2), scores(2)]
        self.run_job(holder=job_locks.lock_value('job-1'))
        self.assertIsNone(self.redis.get(self.KEY))
        self.assertTrue(self.log10().result.startswith('Regenerasi artikel gagal'))

    def test_lock_expired_while_queued_is_taken_again(self):
        seen = self.run_job(holder=None)
        self.assertGreater(seen['ttl'], 45 * 60)
        self.assertIsNone(self.redis.get(self.KEY))

    def test_another_running_regeneration_skips_this_job_and_refunds(self):
        with self.db.get_session() as s:
            s.get(User, 1).credits = 4  # after the route's reservation
        self.run_job(holder=job_locks.lock_value('job-2'), alive=True)
        self.generator.generate_checked_article.assert_not_called()
        self.assertEqual(self.credits(), 5)
        self.assertTrue(self.redis.get(self.KEY).startswith(b'job-2|'))

    def test_a_dead_holder_past_the_grace_period_is_taken_over(self):
        self.run_job(holder=job_locks.lock_value('job-2', now=time.time() - 3600), alive=False)
        self.assertTrue(self.log10().result.startswith(jobs.RESULT_REGENERATED))
        self.assertIsNone(self.redis.get(self.KEY))


class SitePublishLockTests(QualityJobTestCase):
    KEY = 'article_publish_lock:1'

    def setUp(self):
        super().setUp()
        self.redis = LockRedis()
        job = Mock(id='job-1', connection=self.redis)
        patcher = patch.object(jobs, '_current_job', lambda: job)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_publishing_waits_for_another_job_of_the_site_and_releases_the_lock(self):
        self.redis.set(self.KEY, 'other-job', ex=600)
        waits = []

        def sleep(seconds):
            waits.append(seconds)
            self.redis.delete(self.KEY)  # the other job finished publishing
        with patch.object(jobs.time, 'sleep', sleep):
            self.post()
        self.assertEqual(waits, [jobs.SITE_PUBLISH_LOCK_POLL_SECONDS])
        self.publisher.create_post.assert_called_once()
        self.assertIsNone(self.redis.get(self.KEY))
        self.assertTrue(self.last_log().success)

    def test_article_published_meanwhile_by_another_job_is_not_repeated(self):
        def publish_elsewhere(*args, **kwargs):
            # Another worker publishes a near-identical article while this one is written.
            with self.db.get_session() as s:
                s.add(PostLog(user_id=1, site_id=1, category_name='Keuangan', title='Strategi Melunasi Utang Keluarga',
                              success=True, result='ok'))
            return None
        self.generator.generate_image.side_effect = publish_elsewhere
        self.post()
        self.publisher.create_post.assert_not_called()
        self.assertEqual(self.credits(), 11)  # refunded
        log = self.last_log()
        self.assertFalse(log.success)
        self.assertIn('Topik terlalu mirip', log.result)
        self.assertIsNone(self.redis.get(self.KEY))

    def test_lock_is_released_once_the_post_is_recorded_before_sharing(self):
        held_while_sharing = []
        with patch.object(jobs, '_share_published_post',
                          lambda *a, **k: held_while_sharing.append(self.redis.get(self.KEY))):
            self.post()
        self.assertEqual(held_while_sharing, [None])
        self.assertEqual(self.redis.scripts, ['delete'])  # atomic compare-and-delete
        self.assertTrue(self.last_log().success)

    def test_duplicate_published_before_the_image_skips_the_image(self):
        def publish_elsewhere(*args, **kwargs):
            # Another worker publishes a near-identical article during the fact-check.
            with self.db.get_session() as s:
                s.add(PostLog(user_id=1, site_id=1, category_name='Keuangan', title='Strategi Melunasi Utang Keluarga',
                              success=True, result='ok'))
            return json.dumps({'verdict': 'approve'})
        original = self.model_reply
        self.generator.generate_text.side_effect = lambda prompt, system=None, **k: (
            publish_elsewhere() if system == article_review.SYSTEM_PROMPT else original(prompt, system=system, **k))
        self.post()
        self.generator.generate_image.assert_not_called()
        self.publisher.create_post.assert_not_called()
        self.assertIn('Topik terlalu mirip', self.last_log().result)

    def test_meanwhile_check_weighs_niche_words_with_the_whole_history(self):
        captured = {}

        def fake_find(title, published, **kwargs):
            captured.update(published=list(published), corpus=kwargs.get('corpus'))
            return None
        job = jobs._ArticlePostJob(1, None, 1, True, True)
        job.site_config, job.article = {'language': 'id'}, {'title': 'Judul Baru'}
        job.published_titles = [f'Judul lama {i}' for i in range(10)]
        self.db.get_existing_titles = Mock(return_value=job.published_titles + ['Judul terbit barusan'])
        with patch.object(jobs, 'find_similar_published', fake_find):
            job._check_not_published_meanwhile(self.generator)
        self.assertEqual(captured['published'], ['Judul terbit barusan'])
        self.assertEqual(len(captured['corpus']), 11)


class CorpusWeightTests(unittest.TestCase):
    def test_corpus_weights_apply_when_matching_a_few_new_titles(self):
        from services.topic_similarity import find_similar_published
        history = [f'Cara mengatur keuangan keluarga bagian {i}' for i in range(12)]
        candidate = 'Cara mengatur keuangan keluarga untuk pemula'
        new = ['Cara mengatur keuangan keluarga saat pensiun']
        without = find_similar_published(candidate, new, language='id')
        with_corpus = find_similar_published(candidate, new, language='id', corpus=history + new)
        # Words common across the history weigh less, so the same pair scores lower.
        self.assertEqual(without[1], 1.0)
        self.assertLess(with_corpus[1], without[1])


if __name__ == '__main__':
    unittest.main()
