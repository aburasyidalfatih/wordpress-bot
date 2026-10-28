"""Research completeness: Claude social listening, reader questions and YouTube
videos (validation), the Google Trends head-term retry, the precise
missing-evidence notes, official sources in category research storage, and the
AI cost estimates (providers, ledger). No network."""
import sys
import types
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

try:
    import pytrends.request  # noqa: F401
except Exception:  # broken/missing pandas: stub, nothing here calls Trends
    for _name in ('pytrends', 'pytrends.request'):
        sys.modules[_name] = types.ModuleType(_name)
    sys.modules['pytrends.request'].TrendReq = object

for _module in ('trending_research', 'seo_research', 'services.claude_research'):
    if _module in sys.modules and not getattr(sys.modules[_module], '__file__', None):
        del sys.modules[_module]

import seo_research  # noqa: E402
from seo_research import SEOResearch, trend_head_term  # noqa: E402
from services import ai_costs  # noqa: E402
from services.ai_providers import AnthropicText, GeminiText, OpenAIText  # noqa: E402
from services.claude_research import ClaudeWebResearch, discussion_provider, is_discussion_url  # noqa: E402
from services.research_notes import evidence_warnings, optional_notes  # noqa: E402
from test_claude_research import (  # noqa: E402
    FakeEngine, claude_result, engine, fetch_result, message, payload, search_result, text,
)

TOPIC = 'dana darurat'
REDDIT = 'https://www.reddit.com/r/finansial/comments/abc/dana_darurat'
KASKUS = 'https://www.kaskus.co.id/thread/123/dana-darurat'
BLOG = 'https://blog.example.com/dana-darurat'
BLOG_TEXT = (
    "# Panduan Dana Darurat\n\n"
    "## Berapa besar dana darurat yang ideal?\n\n"
    "Dana darurat idealnya setara tiga sampai enam kali pengeluaran bulanan untuk keluarga kecil.\n\n"
    "## Cara Menyimpan Dana Darurat\n\n"
    "Banyak pembaca bertanya apakah dana darurat boleh disimpan di reksa dana pasar uang? Jawabannya boleh.\n"
)
VIDEO = 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'


def blocks():
    return [
        search_result('s1', (REDDIT, 'Berapa dana darurat yang cukup untuk keluarga? : r/finansial', '2 days ago'),
                      (KASKUS, 'Dana darurat habis buat bayar utang, gimana mulai lagi? | KASKUS', None),
                      ('https://news.example.com/berita-dana', 'Berita dana darurat', None),
                      (VIDEO, 'Cara Menyiapkan Dana Darurat - YouTube', None),
                      ('https://www.youtube.com/@kanal', 'Kanal Keuangan', None)),
        fetch_result('f1', BLOG, BLOG_TEXT, title='Panduan Dana Darurat'),
    ]


def run(data, topic=TOPIC, **options):
    research = engine(message(blocks() + [text(data)]))
    return research.research(topic, want_youtube=True, **options)


class SocialValidationTests(unittest.TestCase):
    def test_verbatim_discussions_from_retrieved_pages(self):
        result = run(payload(social=[
            {'url': REDDIT, 'text': 'Berapa dana darurat yang cukup untuk keluarga?'},
            {'url': KASKUS, 'text': 'Dana darurat habis buat bayar utang, gimana mulai lagi?'},
            # Paraphrased: not in the title or page.
            {'url': REDDIT, 'text': 'Berapa jumlah dana darurat yang pas untuk sebuah keluarga?'},
            # Verbatim but not a discussion page.
            {'url': 'https://news.example.com/berita-dana', 'text': 'Berita dana darurat'},
            # Never retrieved.
            {'url': 'https://www.reddit.com/r/lain/comments/zzz', 'text': 'Dana darurat untuk mahasiswa?'},
        ]))
        self.assertEqual(result['social'], [
            {'text': 'Berapa dana darurat yang cukup untuk keluarga?', 'url': REDDIT, 'provider': 'reddit'},
            {'text': 'Dana darurat habis buat bayar utang, gimana mulai lagi?', 'url': KASKUS, 'provider': 'kaskus'},
        ])

    def test_discussion_hosts(self):
        self.assertTrue(is_discussion_url('https://old.reddit.com/r/x'))
        self.assertTrue(is_discussion_url('https://forum.detik.com/t/123'))
        self.assertTrue(is_discussion_url('https://komunitas.example.id/diskusi/1'))
        self.assertFalse(is_discussion_url('https://www.kompas.com/money/read/1'))
        # Generic paths are not discussions: topic tags and Q&A articles.
        self.assertFalse(is_discussion_url('https://www.kompas.com/topic/dana-darurat'))
        self.assertFalse(is_discussion_url('https://www.investopedia.com/ask/answers/emergency-fund/'))

    def test_category_official_sources_backfill_only_when_relevant(self):
        from tasks.article_jobs import _relevant_official_sources
        sources = [
            {'title': 'Juknis Dana BOS', 'url': 'https://a.go.id/1', 'passages': ['Dana BOS dipakai untuk ...']},
            {'title': 'Akreditasi Sekolah', 'url': 'https://b.go.id/2', 'passages': ['Instrumen akreditasi ...']},
        ]
        kept = _relevant_official_sources(sources, 'Laporan penggunaan Dana BOS', 'id')
        self.assertEqual([s['url'] for s in kept], ['https://a.go.id/1'])
        self.assertEqual(discussion_provider('https://id.quora.com/q'), 'quora')
        self.assertEqual(discussion_provider('https://forum.example.com/t/1'), 'forum')


class QuestionValidationTests(unittest.TestCase):
    def questions(self, items, topic=TOPIC):
        return run(payload(questions=items), topic=topic)['questions']

    def test_questions_must_be_verbatim_question_form_and_on_topic(self):
        found = self.questions([
            {'url': REDDIT, 'text': 'Berapa dana darurat yang cukup untuk keluarga?'},  # search title
            {'url': BLOG, 'text': 'Berapa besar dana darurat yang ideal?'},  # heading
            # In the page text, with a question mark.
            {'url': BLOG, 'text': 'apakah dana darurat boleh disimpan di reksa dana pasar uang?'},
            {'url': BLOG, 'text': 'Berapa besar dana darurat yang ideal?'},  # duplicate
            {'url': BLOG, 'text': 'Apa itu dana darurat menurut perencana keuangan?'},  # not on the page
            {'url': BLOG, 'text': 'Cara Menyimpan Dana Darurat'},  # question-form heading, no '?'
            {'url': BLOG, 'text': 'Panduan Dana Darurat'},  # heading, not a question
            {'url': 'https://invented.example.com/q', 'text': 'Kapan dana darurat dipakai?'},  # not retrieved
        ])
        self.assertEqual(found, ['Berapa dana darurat yang cukup untuk keluarga?',
                                 'Berapa besar dana darurat yang ideal?',
                                 'apakah dana darurat boleh disimpan di reksa dana pasar uang?'])

    def test_off_topic_questions_are_dropped(self):
        found = self.questions([{'url': REDDIT, 'text': 'Berapa dana darurat yang cukup untuk keluarga?'}],
                               topic='resep rendang')
        self.assertEqual(found, [])

    def test_question_form_heading_without_question_mark(self):
        found = self.questions([{'url': BLOG, 'text': 'Cara Menyimpan Dana Darurat'}])
        # "Cara ..." is not a question form for is_question_title in Indonesian: dropped.
        self.assertEqual(found, [])

    def test_at_most_ten(self):
        page = '## FAQ\n' + '\n'.join(f'Apakah dana darurat nomor {i} perlu disiapkan?' for i in range(15))
        research = engine(message([fetch_result('f1', BLOG, page)] + [text(payload(questions=[
            {'url': BLOG, 'text': f'Apakah dana darurat nomor {i} perlu disiapkan?'} for i in range(15)]))]))
        self.assertEqual(len(research.research(TOPIC)['questions']), 10)


class YoutubeValidationTests(unittest.TestCase):
    def test_videos_must_be_youtube_search_results(self):
        data = payload(youtube=[
            {'url': VIDEO},
            {'url': 'https://www.youtube.com/@kanal'},  # a channel, not a video
            {'url': 'https://youtu.be/AAAAAAAAAAA'},  # never in the results
            {'url': VIDEO + '&t=30'},  # same video
        ])
        result = run(data)
        self.assertEqual(result['youtube'], [{'video_id': 'dQw4w9WgXcQ', 'title': 'Cara Menyiapkan Dana Darurat - YouTube',
                                              'url': VIDEO}])

    def test_not_requested_means_empty(self):
        research = engine(message(blocks() + [text(payload())]))
        self.assertEqual(research.research(TOPIC)['youtube'], [])

    def test_transcripts_fetched_for_claude_videos(self):
        research = SEOResearch()
        snippets = [{'text': 'Simpan dana darurat di rekening terpisah.', 'start': 1.0}] * 3
        with patch.object(seo_research, 'YouTubeTranscriptApi', object()), \
                patch.object(research, '_fetch_transcript', return_value=snippets) as fetch:
            insights = research.youtube_insights_for([(VIDEO, 'Video')], language='id', via='claude_web')
        fetch.assert_called_once_with('dQw4w9WgXcQ', ['id', 'en'])
        self.assertTrue(insights[0]['transcript_available'])
        self.assertEqual(research.source_status['youtube']['status'], 'real')
        self.assertEqual(research.source_status['youtube']['via'], 'claude_web')

    def test_without_transcript_library_videos_stay_title_only(self):
        research = SEOResearch()
        with patch.object(seo_research, 'YouTubeTranscriptApi', None):
            insights = research.youtube_insights_for([(VIDEO, 'Video')])
        self.assertEqual(insights[0]['transcript_available'], False)
        self.assertEqual(research.source_status['youtube']['status'], 'partial')


class TopicResearchSocialQuestionsTests(unittest.TestCase):
    def test_claude_social_and_questions_replace_classic(self):
        questions = ['Kapan dana darurat dipakai?', 'Berapa dana darurat ideal?', 'Di mana menyimpan dana darurat?']
        social = [{'text': 'Dana darurat habis, gimana?', 'url': KASKUS, 'provider': 'kaskus'}]
        research = SEOResearch(claude=FakeEngine(claude_result(questions=questions, social=social)))
        mocks = {name: Mock(return_value=value) for name, value in (
            ('analyze_competitors', []), ('get_official_sources', []), ('get_social_insights', []),
            ('get_keyword_suggestions', ['saran']), ('get_related_questions', ['template?']))}
        with patch.multiple(research, **mocks), patch.object(seo_research, 'DDG_CALL_SPACING_SECONDS', 0):
            result = research.research_topic(TOPIC)
        mocks['get_related_questions'].assert_not_called()
        mocks['get_social_insights'].assert_not_called()
        self.assertEqual(result['evidence_questions'], questions)
        self.assertEqual(result['social_insights'], social)
        self.assertEqual(result['source_metadata']['related_questions']['via'], 'claude_web')


class TrendHeadTermTests(unittest.TestCase):
    def test_head_term(self):
        self.assertEqual(trend_head_term('Emergency Fund and Financial Safety', 'en'), 'emergency fund')
        self.assertEqual(trend_head_term('Couples Money Management', 'en'), 'couples money')
        self.assertEqual(trend_head_term('Tips Menabung untuk Keluarga Muda', 'id'), 'menabung keluarga')
        self.assertEqual(trend_head_term('Budgeting', 'en'), '')  # nothing shorter
        self.assertEqual(trend_head_term('Saving Money', 'en'), '')

    def trend(self, results):
        research = SEOResearch()
        calls = []

        def analysis(keyword, language='id'):
            calls.append(keyword)
            status, reason = results[len(calls) - 1]
            research._mark_source('google_trends', status, **({'reason': reason} if reason else {}))
            return {'score': 36, 'status': 'real'} if status == 'real' else {'score': None, 'status': 'unavailable'}

        with patch.object(research, 'get_trend_analysis', side_effect=analysis):
            result = research.get_category_trend('Emergency Fund and Financial Safety', 'en')
        return research, result, calls

    def test_no_data_retries_once_with_the_head_term(self):
        research, result, calls = self.trend([('unavailable', 'no_data'), ('real', None)])
        self.assertEqual(calls, ['Emergency Fund and Financial Safety', 'emergency fund'])
        self.assertEqual((result['score'], result['term']), (36, 'emergency fund'))
        self.assertEqual(research.source_status['google_trends']['trend_term'], 'emergency fund')

    def test_no_retry_after_a_block_or_success(self):
        _, _, calls = self.trend([('unavailable', 'TooManyRequestsError')])
        self.assertEqual(len(calls), 1)
        _, result, calls = self.trend([('real', None)])
        self.assertEqual(len(calls), 1)
        self.assertNotIn('term', result)

    def test_failed_retry_keeps_the_original_result(self):
        research, result, calls = self.trend([('unavailable', 'no_data'), ('unavailable', 'no_data')])
        self.assertEqual(len(calls), 2)
        self.assertEqual(result['status'], 'unavailable')
        self.assertNotIn('trend_term', research.source_status['google_trends'])


class ResearchNotesTests(unittest.TestCase):
    def test_template_questions_are_named_not_generic(self):
        meta = {'competitors': {'status': 'real'}, 'related_questions': {'status': 'fallback'},
                'google_autocomplete': {'status': 'real'}, 'social': {'status': 'unavailable'},
                'youtube': {'status': 'partial'}, 'news': {'status': 'real'}}
        self.assertEqual(evidence_warnings(meta), [
            'Pertanyaan pembaca memakai template cadangan; template itu tidak dipakai untuk artikel.'])
        self.assertEqual(optional_notes(meta), ['Diskusi sosial tidak tersedia', 'Transkrip video tidak tersedia'])

    def test_optional_sources_never_warn(self):
        meta = {'competitors': {'status': 'real'}, 'related_questions': {'status': 'real'},
                'google_autocomplete': {'status': 'real'}, 'social': {'status': 'unavailable'},
                'youtube': {'status': 'unavailable'}, 'google_trends': {'status': 'unavailable'}}
        self.assertEqual(evidence_warnings(meta), [])
        self.assertEqual(len(optional_notes(meta)), 3)

    def test_missing_and_thin_competitors(self):
        self.assertEqual(evidence_warnings({'competitors': {'status': 'unavailable'}}),
                         ['Data kompetitor tidak tersedia.'])
        self.assertIn('tipis', evidence_warnings({'competitors': {'status': 'partial'}})[0])
        self.assertEqual(evidence_warnings({}), [])


class AICostTests(unittest.TestCase):
    def test_price_table(self):
        usage = {'input_tokens': 1_000_000, 'output_tokens': 100_000, 'cache_read_input_tokens': 1_000_000,
                 'cache_creation_input_tokens': 100_000}
        self.assertAlmostEqual(ai_costs.token_cost_usd('claude-opus-5-5', usage), 4 + 2 + 0.2 + 0.5)
        self.assertAlmostEqual(ai_costs.token_cost_usd('claude-sonnet-5-5', usage), 2 + 1 + 0.2 + 0.25)
        self.assertAlmostEqual(ai_costs.token_cost_usd('claude-haiku-5-5', {'input_tokens': 1_000_000,
                                                                            'output_tokens': 1_000_000}), 0.6)
        self.assertIsNone(ai_costs.token_cost_usd('gemini-3-pro', usage))

    def test_ledger_stages_and_summary(self):
        with ai_costs.track_costs() as ledger:
            ai_costs.add_cost('riset', 0.62)
            with ai_costs.cost_stage('tulis'):
                ai_costs.record_usage('anthropic', 'claude-opus-5-5', {'input_tokens': 50_000, 'output_tokens': 3_500})
                ai_costs.record_usage('gemini', 'gemini-x', {'input_tokens': 10})
                with ai_costs.cost_stage('revisi'):
                    ai_costs.record_usage('anthropic', 'claude-opus-5-5', {'output_tokens': 5_000})
        self.assertIsNone(ai_costs._ledger.get())
        line = ledger.summary('42')
        self.assertTrue(line.startswith('Biaya AI artikel 42: riset $0.62, brief $0.00, tulis $0.27'))
        self.assertIn('revisi $0.10', line)
        self.assertIn('total $0.99', line)
        self.assertIn('+1 panggilan tanpa tarif', line)

    def test_no_ledger_no_error(self):
        self.assertAlmostEqual(ai_costs.record_usage('anthropic', 'claude-opus-5-5', {'input_tokens': 250_000}), 1.0)


class ProviderUsageTests(unittest.TestCase):
    def test_anthropic_usage_and_cost(self):
        msg = SimpleNamespace(content=[SimpleNamespace(type='text', text='ok')], stop_reason='end_turn',
                              usage=SimpleNamespace(input_tokens=100_000, output_tokens=10_000,
                                                    cache_read_input_tokens=0, cache_creation_input_tokens=None))
        stream = MagicMock()
        stream.__enter__.return_value.get_final_message.return_value = msg
        client = SimpleNamespace(messages=SimpleNamespace(stream=Mock(return_value=stream)),
                                 beta=SimpleNamespace(messages=SimpleNamespace(stream=Mock(return_value=stream))))
        with ai_costs.track_costs() as ledger, ai_costs.cost_stage('tulis'):
            result = AnthropicText(None, 'claude-opus-5-5', client=client).generate('x')
        self.assertEqual(result.usage, {'input_tokens': 100_000, 'output_tokens': 10_000, 'cache_read_input_tokens': 0})
        self.assertAlmostEqual(result.cost_usd, 0.6)
        self.assertAlmostEqual(ledger.stages['tulis']['usd'], 0.6)

    def test_openai_and_gemini_usage_without_price(self):
        response = SimpleNamespace(output_text='ok', status='completed', incomplete_details=None,
                                   usage=SimpleNamespace(input_tokens=10, output_tokens=20))
        client = SimpleNamespace(responses=SimpleNamespace(create=Mock(return_value=response)))
        result = OpenAIText(None, 'gpt-5.5', client=client).generate('x')
        self.assertEqual(result.usage, {'input_tokens': 10, 'output_tokens': 20})
        self.assertIsNone(result.cost_usd)
        gemini = SimpleNamespace(text='ok', candidates=[], usage_metadata=SimpleNamespace(
            prompt_token_count=5, candidates_token_count=7, thoughts_token_count=3))
        client = SimpleNamespace(models=SimpleNamespace(generate_content=Mock(return_value=gemini)))
        result = GeminiText(None, 'gemini-x', client=client).generate('x')
        self.assertEqual(result.usage, {'input_tokens': 5, 'output_tokens': 10})
        self.assertIsNone(result.cost_usd)

    def test_missing_usage_is_tolerated(self):
        response = SimpleNamespace(text='ok', candidates=[])
        client = SimpleNamespace(models=SimpleNamespace(generate_content=Mock(return_value=response)))
        self.assertIsNone(GeminiText(None, 'gemini-x', client=client).generate('x').usage)


class EngineStatsTests(unittest.TestCase):
    def test_thin_count_and_price_for_the_configured_model(self):
        data = payload(competitors=[{'url': BLOG, 'passages': [
            'Dana darurat idealnya setara tiga sampai enam kali pengeluaran bulanan untuk keluarga kecil.']}])
        research = ClaudeWebResearch('k', 'claude-sonnet-5-5', client=engine(
            message(blocks() + [text(data)], input_tokens=1_000_000, searches=2)).client)
        stats = research.research(TOPIC)['stats']
        self.assertEqual(stats['thin_competitors'], 1)
        # Sonnet 5.5 input price ($2/M) plus two searches.
        self.assertAlmostEqual(stats['estimated_cost_usd'], 2.0 + 200 * 10 / 1_000_000 + 0.02, places=4)


class StorageTests(unittest.TestCase):
    def test_official_sources_and_notes_are_saved_and_served(self):
        from test_research_backend_support import load_with_stubbed_core, make_db
        from models import ResearchData
        db = make_db()
        official = [{'title': 'OJK', 'url': 'https://www.ojk.go.id/x', 'passages': ['p']}]
        db.save_research_data(1, 1, 'Keuangan', [], [], [], [], official_sources=official,
                              source_metadata={'related_questions': {'status': 'fallback'}})
        with db.get_session() as session:
            row = session.query(ResearchData).first()
            self.assertEqual(row.official_sources, official)
            research_routes, _ = load_with_stubbed_core('routes.research')
            entry = research_routes._research_entry(row, None, datetime.now())
        self.assertEqual(entry['official_sources'], official)
        self.assertTrue(entry['is_fallback'])
        self.assertEqual(entry['fallback_warnings'],
                         ['Pertanyaan pembaca memakai template cadangan; template itu tidak dipakai untuk artikel.'])


if __name__ == '__main__':
    unittest.main()
