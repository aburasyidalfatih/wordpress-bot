"""Claude web research relevance and cost: the social and reader-question
filters (with the production examples from kelasmaster.id), tool counting at
the max_uses limit, per-iteration usage, model-aware cost estimates, the
research model setting, and the keyword ideas used when Google Suggest is
blocked. No network."""
import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

try:
    import pytrends.request  # noqa: F401
except Exception:  # broken/missing pandas: stub, nothing here uses Trends
    for _name in ('pytrends', 'pytrends.request'):
        sys.modules[_name] = types.ModuleType(_name)
    sys.modules['pytrends.request'].TrendReq = object

for _module in ('trending_research', 'seo_research', 'services.claude_research'):
    if _module in sys.modules and not getattr(sys.modules[_module], '__file__', None):
        del sys.modules[_module]

import seo_research  # noqa: E402
from seo_research import SEOResearch, claude_keyword_ideas, title_matches_topic  # noqa: E402
from services import claude_research  # noqa: E402
from services.ai_providers import make_text_provider, merge_shared_ai_config  # noqa: E402
from services.claude_research import (  # noqa: E402
    ClaudeWebResearch, from_config, is_help_page, is_news_url, is_platform_meta, is_survey_prompt, strip_numbering,
)
from test_claude_research import (  # noqa: E402
    FakeEngine, claude_result, engine, fetch_error, fetch_result, message, payload, search_result, text, tool_use,
)

CATEGORY = 'Prompt AI dan Modul Ajar Guru'

# Production: an off-topic Quora help-center page passed as social listening.
QUORA_HELP = 'https://help.quora.com/hc/en-us/articles/360000470663'
QUORA_HELP_TITLE = "What is considered 'Adult' content on Quora? - Quora Help Center"
QUORA_HELP_TEXT = "What is considered 'Adult' content on Quora?"
REDDIT = 'https://www.reddit.com/r/indonesia/comments/abc/prompt_ai_modul_ajar'
REDDIT_TITLE = 'Ada yang pakai prompt AI buat bikin modul ajar? : r/indonesia'
KASKUS = 'https://www.kaskus.co.id/thread/123/guru-honorer-chatgpt'
KASKUS_TITLE = 'Guru honorer pakai ChatGPT untuk administrasi, aman nggak? | KASKUS'
LAPTOP = 'https://www.reddit.com/r/indonesia/comments/xyz/laptop'
LAPTOP_TITLE = 'Rekomendasi laptop murah untuk kuliah? : r/indonesia'
META = 'https://id.quora.com/Bagaimana-cara-menambah-upvote-di-Quora'
META_TITLE = 'Bagaimana cara menambah upvote jawaban modul ajar di Quora? - Quora'
COMMUNITY_HELP = 'https://community.example.com/help/prompt-ai-guru'
COMMUNITY_HELP_TITLE = 'Prompt AI untuk guru dilarang di forum? - Community'

PAA = 'https://www.edukasi.example.com/prompt-modul-ajar'
PAA_TITLE = 'Bagaimana cara membuat prompt AI untuk modul ajar?'
BLOG = 'https://blog.example.com/prompt-ai-guru'
BLOG_TEXT = (
    "# Panduan Prompt AI untuk Guru\n\n"
    "## Mengapa Perlu Menggunakan Prompt Terstruktur?\n\n"
    "Prompt yang terstruktur membuat modul ajar dari AI lebih rapi dan sesuai capaian pembelajaran.\n\n"
    "## Apakah prompt AI bisa dipakai untuk semua mata pelajaran guru?\n\n"
    "## Bagaimana menguji prompt AI sebelum dipakai guru?\n\n"
    "## Kapan guru perlu menulis ulang prompt AI?\n\n"
    "## FAQ\n\n"
    "### Apa itu modul ajar berbasis AI?\n\n"
    "Modul ajar berbasis AI adalah modul yang disusun guru dengan bantuan model bahasa.\n\n"
    "### Bagaimana pengalaman Anda dalam memanfaatkan AI untuk menyusun modul ajar?\n"
)


def social_blocks():
    return [
        search_result('s1', (QUORA_HELP, QUORA_HELP_TITLE, None), (REDDIT, REDDIT_TITLE, '3 days ago'),
                      (KASKUS, KASKUS_TITLE, None), (LAPTOP, LAPTOP_TITLE, None), (META, META_TITLE, None),
                      (COMMUNITY_HELP, COMMUNITY_HELP_TITLE, None)),
    ]


def run_social(items, topic=CATEGORY):
    research = engine(message(social_blocks() + [text(payload(social=items))]))
    return research.research(topic)['social']


class SocialRelevanceTests(unittest.TestCase):
    def test_production_quora_help_center_item_is_rejected(self):
        found = run_social([{'url': QUORA_HELP, 'text': QUORA_HELP_TEXT},
                            {'url': REDDIT, 'text': 'Ada yang pakai prompt AI buat bikin modul ajar?'}])
        self.assertEqual([item['url'] for item in found], [REDDIT])
        # Each rule rejects it on its own.
        self.assertTrue(is_help_page(QUORA_HELP, QUORA_HELP_TITLE))
        self.assertTrue(is_help_page('https://www.quora.com/q/x', QUORA_HELP_TITLE))
        self.assertTrue(is_platform_meta(QUORA_HELP_TEXT, CATEGORY))
        self.assertFalse(title_matches_topic(QUORA_HELP_TEXT, CATEGORY, 'id'))

    def test_text_needs_a_significant_topic_word(self):
        found = run_social([
            {'url': KASKUS, 'text': 'Guru honorer pakai ChatGPT untuk administrasi, aman nggak?'},  # "guru"
            {'url': LAPTOP, 'text': 'Rekomendasi laptop murah untuk kuliah?'},  # no topic word
        ])
        self.assertEqual([item['url'] for item in found], [KASKUS])

    def test_platform_meta_questions_are_rejected(self):
        found = run_social([{'url': META, 'text': 'Bagaimana cara menambah upvote jawaban modul ajar di Quora?'}])
        self.assertEqual(found, [])
        # Unless the topic is about the platform itself.
        self.assertFalse(is_platform_meta('Bagaimana cara menambah upvote di Quora?', 'Pemasaran lewat Quora upvote'))

    def test_help_paths_on_discussion_hosts_are_rejected(self):
        found = run_social([{'url': COMMUNITY_HELP, 'text': 'Prompt AI untuk guru dilarang di forum?'}])
        self.assertEqual(found, [])

    def test_help_and_policy_detection(self):
        for url, title in (
                ('https://support.google.com/x', ''), ('https://help.reddit.com/a', ''),
                ('https://x.zendesk.com/a', ''), ('https://www.quora.com/about/privacy', ''),
                ('https://www.kaskus.co.id/x', 'Pusat Bantuan Kaskus'),
                ('https://www.kaskus.co.id/x', 'Kebijakan Privasi | KASKUS'),
                ('https://www.reddit.com/x', 'Terms | Reddit'),
                ('https://www.reddit.com/x', 'Privacy Policy - Reddit'),
                ('https://www.reddit.com/x', 'Reddit User Agreement: Terms of Service')):
            self.assertTrue(is_help_page(url, title), (url, title))
        # "Kebijakan" (policy) is an ordinary topic word in Indonesian.
        self.assertFalse(is_help_page('https://www.reddit.com/r/guru/1', 'Kebijakan zonasi bikin guru bingung?'))
        self.assertFalse(is_help_page(REDDIT, REDDIT_TITLE))


def question_blocks():
    return [
        search_result('s1', (REDDIT, REDDIT_TITLE, None), (PAA, PAA_TITLE, None), (BLOG, 'Prompt AI Guru', None)),
        fetch_result('f1', BLOG, BLOG_TEXT, title='Panduan Prompt AI untuk Guru'),
    ]


def run_questions(items, topic=CATEGORY, blocks=None, news=()):
    blocks = question_blocks() if blocks is None else blocks
    research = engine(message(blocks + [text(payload(questions=items, news=list(news)))]))
    return research.research(topic)['questions']


class QuestionRelevanceTests(unittest.TestCase):
    def test_forum_faq_and_search_questions_rank_before_article_headings(self):
        found = run_questions([
            {'url': BLOG, 'text': 'Mengapa Perlu Menggunakan Prompt Terstruktur?'},  # production: a heading
            {'url': PAA, 'text': PAA_TITLE},  # People-Also-Ask-like search result
            {'url': BLOG, 'text': 'Apa itu modul ajar berbasis AI?'},  # FAQ entry
            {'url': REDDIT, 'text': 'Ada yang pakai prompt AI buat bikin modul ajar?'},  # forum thread
        ])
        self.assertEqual(found, ['Ada yang pakai prompt AI buat bikin modul ajar?', 'Apa itu modul ajar berbasis AI?',
                                 PAA_TITLE, 'Mengapa Perlu Menggunakan Prompt Terstruktur?'])

    def test_article_heading_questions_are_capped(self):
        headings = ['Mengapa Perlu Menggunakan Prompt Terstruktur?',
                    'Apakah prompt AI bisa dipakai untuk semua mata pelajaran guru?',
                    'Bagaimana menguji prompt AI sebelum dipakai guru?', 'Kapan guru perlu menulis ulang prompt AI?']
        found = run_questions([{'url': BLOG, 'text': heading} for heading in headings])
        self.assertEqual(found, headings[:claude_research.MAX_ARTICLE_QUESTIONS])

    def test_survey_prompts_are_rejected(self):
        # Production: a survey question on the page's FAQ.
        found = run_questions([{'url': BLOG, 'text': 'Bagaimana pengalaman Anda dalam memanfaatkan AI untuk '
                                                    'menyusun modul ajar?'}])
        self.assertEqual(found, [])
        self.assertTrue(is_survey_prompt('In your opinion, is AI good for lesson plans?'))
        self.assertTrue(is_survey_prompt('Menurut anda, apa itu modul ajar?'))
        self.assertFalse(is_survey_prompt('Apa itu modul ajar menurut Kemendikbud?'))

    def test_numbered_quiz_items(self):
        topic = 'Pengembangan Kurikulum Sekolah'
        url = 'https://soal.example.com/kurikulum'
        page = ("Soal Pengembangan Kurikulum\n"
                "1. Menurut anda, definisi dari pengembangan kurikulum adalah?\n"
                "2) Apa tujuan pengembangan kurikulum di sekolah?\n")
        found = run_questions([
            {'url': url, 'text': '1. Menurut anda, definisi dari pengembangan kurikulum adalah?'},  # production
            {'url': url, 'text': '2) Apa tujuan pengembangan kurikulum di sekolah?'},
        ], topic=topic, blocks=[fetch_result('f1', url, page, title='Soal Kurikulum')])
        self.assertEqual(found, ['Apa tujuan pengembangan kurikulum di sekolah?'])
        self.assertEqual(strip_numbering('1. Apa itu?'), 'Apa itu?')
        self.assertEqual(strip_numbering('(3) Apa itu?'), 'Apa itu?')
        self.assertEqual(strip_numbering('2026 rules?'), '2026 rules?')

    def test_news_headlines_are_rejected(self):
        topic = 'Izin Operasional Sekolah Swasta'
        headline = 'Ratusan Izin Operasional SMK Swasta Belum Dapat Terproses, Ada Apa?'  # production
        detik = 'https://www.detik.com/edu/sekolah/d-7612345/ratusan-izin-operasional-smk-swasta'
        portal = 'https://portal.example.id/2026/10/izin-smk-swasta'
        forum = 'https://forum.example.id/t/izin-operasional-sekolah-swasta'
        blocks = [search_result('s1', (detik, headline, '2 days ago'), (portal, headline, '2 days ago'),
                                (forum, 'Berapa lama izin operasional sekolah swasta keluar?', None))]
        found = run_questions([
            {'url': detik, 'text': headline},  # news site
            {'url': portal, 'text': headline},  # listed as news in the same call
            {'url': forum, 'text': 'Berapa lama izin operasional sekolah swasta keluar?'},
        ], topic=topic, blocks=blocks, news=[{'url': portal}])
        self.assertEqual(found, ['Berapa lama izin operasional sekolah swasta keluar?'])

    def test_news_url_detection(self):
        self.assertTrue(is_news_url('https://edukasi.kompas.com/read/2026/10/01/x'))
        self.assertTrue(is_news_url('https://www.liputan6.com/news/read/123/x'))
        self.assertTrue(is_news_url('https://www.example.id/berita/izin-smk'))
        self.assertFalse(is_news_url('https://forum.detik.com/t/123'))  # a discussion, not news
        self.assertFalse(is_news_url('https://blog.example.com/prompt-ai-guru'))

    def test_question_mark_and_topic_word_are_required(self):
        self.assertEqual(run_questions([
            {'url': PAA, 'text': 'Bagaimana cara membuat prompt AI untuk modul ajar'},  # no '?'
            {'url': BLOG, 'text': 'Panduan Prompt AI untuk Guru'},  # a heading, not a question
        ]), [])
        self.assertEqual(run_questions([{'url': REDDIT, 'text': 'Ada yang pakai prompt AI buat bikin modul ajar?'}],
                                       topic='Resep Rendang Padang'), [])

    def test_prompt_asks_for_real_reader_questions_only(self):
        research = engine(message(question_blocks() + [text(payload())]))
        research.research(CATEGORY)
        prompt = research.client.messages.stream.call_args.kwargs['messages'][0]['content']
        self.assertIn('People-Also-Ask', prompt)
        self.assertIn("Never an article's own section headings, news headlines", prompt)
        self.assertIn('never help-center, support, terms or policy pages', prompt)
        self.assertIn('never questions about the platform', prompt)
        self.assertIn('never return an article', claude_research.SYSTEM_PROMPT.lower())


def iteration(input_tokens, cache_write, cache_read, output_tokens, kind='message', model=None):
    return SimpleNamespace(type=kind, model=model, input_tokens=input_tokens, output_tokens=output_tokens,
                           cache_creation_input_tokens=cache_write, cache_read_input_tokens=cache_read)


def fetch_blocks(count, rejected=0):
    blocks = [search_result('s1', *[(f'https://site{i}.example.com/a', f'Prompt AI guru {i}', None)
                                    for i in range(max(count, 1))])]
    for i in range(count):
        blocks += [tool_use('web_fetch', f'f{i}', url=f'https://site{i}.example.com/a'),
                   fetch_result(f'f{i}', f'https://site{i}.example.com/a', 'Prompt AI untuk guru.')]
    for i in range(rejected):
        blocks += [tool_use('web_fetch', f'r{i}', url='https://extra.example.com/'),
                   fetch_error(f'r{i}', 'max_uses_exceeded')]
    return blocks


class ToolCountTests(unittest.TestCase):
    def test_limits(self):
        self.assertEqual((claude_research.WEB_SEARCH_MAX_USES, claude_research.WEB_FETCH_MAX_USES), (6, 5))
        self.assertEqual(claude_research.WEB_FETCH_MAX_CONTENT_TOKENS, 6000)
        tools = ClaudeWebResearch('k', client=Mock()).build_tools('id', set())
        self.assertEqual([tool['max_uses'] for tool in tools], [6, 5])

    def test_attempt_refused_at_max_uses_is_not_a_fetch(self):
        # Production logged fetches=7 with max_uses 6: the refused attempt was counted.
        research = engine(message(fetch_blocks(5, rejected=1) + [text(payload())], searches=1, fetches=6))
        with self.assertLogs('services.claude_research', 'INFO') as logs:
            stats = research.research(CATEGORY)['stats']
        self.assertEqual((stats['fetches'], stats['fetches_reported'], stats['limit_rejections']), (5, 6, 1))
        self.assertIn('fetches=5 (reported 6, refused at limit 1)', logs.output[-1])
        self.assertFalse(any('more tools than max_uses' in line for line in logs.output))

    def test_more_fetches_than_the_limit_are_logged(self):
        research = engine(message(fetch_blocks(6) + [text(payload())], searches=1, fetches=6))
        with self.assertLogs('services.claude_research', 'WARNING') as logs:
            research.research(CATEGORY)
        self.assertIn('fetches=6/5', logs.output[0])

    def test_continuation_budget_counts_executed_or_reported_uses(self):
        paused = message(fetch_blocks(2, rejected=1), stop_reason='pause_turn', searches=1, fetches=3)
        research = engine(paused, message([text(payload())], searches=0, fetches=0))
        research.research(CATEGORY)
        resumed = research.client.messages.stream.call_args_list[1].kwargs
        # The larger of executed (2) and reported (3) is spent: 5 - 3 left.
        self.assertEqual([tool['max_uses'] for tool in resumed['tools']], [5, 2])


class UsageAndCostTests(unittest.TestCase):
    def test_per_iteration_usage_is_logged(self):
        reply = message(fetch_blocks(1) + [text(payload())], input_tokens=150_014, cache_read=3_000,
                        cache_write=3_000)
        reply.usage.iterations = [iteration(14, 3_000, 0, 100), iteration(150_000, 0, 3_000, 100)]
        research = engine(reply)
        with self.assertLogs('services.claude_research', 'INFO') as logs:
            stats = research.research(CATEGORY)['stats']
        line = next(line for line in logs.output if 'iterations:' in line)
        self.assertIn('#1 message in=14 cache_write=3000 cache_read=0 out=100', line)
        self.assertIn('#2 message in=150000 cache_write=0 cache_read=3000 out=100', line)
        self.assertEqual(stats['iterations'], 2)
        self.assertEqual(stats['input_tokens'], 150_014)

    def test_fallback_hop_is_counted_at_its_own_price(self):
        # Top-level usage covers only the attempt that produced the message.
        reply = message(fetch_blocks(1) + [text(payload())], input_tokens=100_000, searches=0)
        reply.usage.output_tokens = 0
        reply.usage.iterations = [iteration(1_000_000, 0, 0, 0),
                                  iteration(100_000, 0, 0, 0, kind='fallback_message', model='claude-sonnet-5-5')]
        stats = engine(reply).research(CATEGORY)['stats']
        self.assertEqual(stats['input_tokens'], 1_100_000)
        # 1M at Opus 5.5 ($4) plus 100k at Sonnet 5.5 ($0.20).
        self.assertAlmostEqual(stats['estimated_cost_usd'], 4.2, places=4)

    def test_cost_uses_the_research_model_prices(self):
        usage = dict(input_tokens=100_000, cache_read=200_000, cache_write=40_000, searches=6)
        costs = {}
        for model in ('claude-opus-5-5', 'claude-sonnet-5-5'):
            reply = message(fetch_blocks(1) + [text(payload())], **usage)
            costs[model] = engine(reply, model=model).research(CATEGORY)['stats']['estimated_cost_usd']
        # Opus: 0.40 input + 0.004 output + 0.04 read + 0.20 write + 0.06 searches.
        self.assertAlmostEqual(costs['claude-opus-5-5'], 0.704, places=4)
        # Sonnet: 0.20 input + 0.002 output + 0.04 read + 0.10 write + 0.06 searches.
        self.assertAlmostEqual(costs['claude-sonnet-5-5'], 0.402, places=4)
        self.assertAlmostEqual(claude_research.estimate_cost_usd(
            {'input_tokens': 1_000_000}, 0, 'claude-sonnet-4-6'), 3.0)

    def test_unpriced_model_is_estimated_at_opus_prices_and_says_so(self):
        reply = message(fetch_blocks(1) + [text(payload())], input_tokens=1_000_000, searches=0)
        reply.usage.output_tokens = 0
        research = engine(reply, model='claude-future-9')
        with self.assertLogs('services.claude_research', 'INFO') as logs:
            stats = research.research(CATEGORY)['stats']
        self.assertEqual(stats['priced_as'], 'claude-opus-5-5')
        self.assertAlmostEqual(stats['estimated_cost_usd'], 4.0)
        self.assertIn('model=claude-future-9 (priced as claude-opus-5-5)', logs.output[-1])

    def test_source_metadata_carries_the_model_and_cost(self):
        reply = message(fetch_blocks(1) + [text(payload())], input_tokens=100_000, searches=2)
        research = SEOResearch(claude=engine(reply, model='claude-sonnet-5-5'))
        research._claude_research(CATEGORY, 'id', frozenset())
        meta = research.source_status['claude_web']
        self.assertEqual(meta['model'], 'claude-sonnet-5-5')
        # 100k input at $2/M, 200 output at $10/M, two searches.
        self.assertAlmostEqual(meta['estimated_cost_usd'], 0.2 + 0.002 + 0.02, places=4)


class ResearchModelTests(unittest.TestCase):
    def test_research_model_is_used_when_set(self):
        config = {'anthropic_api_key': 'k', 'anthropic_model': 'claude-opus-5-5',
                  'anthropic_research_model': 'claude-sonnet-5-5'}
        self.assertEqual(from_config(config).model, 'claude-sonnet-5-5')
        # Articles keep the text model.
        self.assertEqual(make_text_provider(dict(config, ai_text_provider='anthropic')).model, 'claude-opus-5-5')

    def test_empty_research_model_follows_the_text_model(self):
        for value in ('', '  ', None):
            config = {'anthropic_api_key': 'k', 'anthropic_model': 'claude-opus-4-8', 'anthropic_research_model': value}
            self.assertEqual(from_config(config).model, 'claude-opus-4-8')

    def test_shared_admin_research_model_reaches_users(self):
        admin = {'ai_text_provider': 'anthropic', 'anthropic_api_key': 'admin-a', 'anthropic_model': 'claude-opus-5-5',
                 'anthropic_research_model': 'claude-sonnet-5-5'}
        user = {'anthropic_api_key': '', 'anthropic_research_model': 'claude-opus-5-5'}
        research = from_config(merge_shared_ai_config(user, admin))
        self.assertEqual((research.model, research.client.api_key), ('claude-sonnet-5-5', 'admin-a'))

    def test_request_uses_the_research_model(self):
        research = engine(message(question_blocks() + [text(payload())]), model='claude-sonnet-5-5')
        research.research(CATEGORY)
        self.assertEqual(research.client.messages.stream.call_args.kwargs['model'], 'claude-sonnet-5-5')


class KeywordIdeaTests(unittest.TestCase):
    TITLES = ['Cara Membuat Modul Ajar dengan AI - Guru Inovatif', REDDIT_TITLE, 'Berita Hari Ini - Kompas.com',
              'Kumpulan Prompt ChatGPT untuk Guru: Modul Ajar dan RPP | Blog Guru']

    def test_ideas_are_verbatim_parts_of_retrieved_titles(self):
        ideas = claude_keyword_ideas({'search_titles': self.TITLES, 'questions': [
            'Apa itu modul ajar berbasis AI?',  # not in a retrieved title: never a keyword
            'Ada yang pakai prompt AI buat bikin modul ajar?',  # 9 words: too long for a keyword
            'Cara Membuat Modul Ajar dengan AI?']}, CATEGORY)
        # Site-name tails ("Guru Inovatif", "Blog Guru") and off-topic titles are not keywords.
        self.assertEqual(ideas, ['Cara Membuat Modul Ajar dengan AI', 'Kumpulan Prompt ChatGPT untuk Guru',
                                 'Modul Ajar dan RPP'])
        haystack = ' '.join(self.TITLES).lower()
        self.assertTrue(all(idea.lower() in haystack for idea in ideas))

    def test_no_titles_no_ideas(self):
        self.assertEqual(claude_keyword_ideas({'questions': ['Apa itu modul ajar?']}, CATEGORY), [])
        self.assertEqual(claude_keyword_ideas(None, CATEGORY), [])

    def run_category(self, claude_parts, suggestions):
        research = SEOResearch(claude=FakeEngine(claude_result(**claude_parts)))

        def keyword_suggestions(*args, **kwargs):
            status, reason = suggestions
            details = {'reason': reason} if reason else {}
            research._mark_source('google_autocomplete', status, count=1, **details)
            return ['tips ' + CATEGORY] if status != 'real' else ['modul ajar ai']

        mocks = {name: Mock(return_value=value) for name, value in (
            ('analyze_competitors', []), ('get_official_sources', []), ('get_social_insights', []),
            ('get_related_questions', []), ('get_latest_news', []), ('get_wikipedia_context', ''),
            ('get_youtube_insights', []), ('get_category_trend', {'score': None, 'status': 'unavailable'}))}
        mocks['get_keyword_suggestions'] = Mock(side_effect=keyword_suggestions)
        with patch.multiple(research, **mocks), patch.object(seo_research, 'DDG_CALL_SPACING_SECONDS', 0):
            return research.research_category(CATEGORY)

    def test_blocked_google_suggest_falls_back_to_claude_titles(self):
        result = self.run_category({'search_titles': self.TITLES}, ('fallback', 'HTTP 429'))
        self.assertEqual(result['evidence_suggestions'][0], 'Cara Membuat Modul Ajar dengan AI')
        meta = result['source_metadata']['google_autocomplete']
        self.assertEqual((meta['status'], meta['via'], meta['google_error']), ('real', 'claude_web', 'HTTP 429'))

    def test_real_google_suggestions_are_kept(self):
        result = self.run_category({'search_titles': self.TITLES}, ('real', None))
        self.assertEqual(result['evidence_suggestions'], ['modul ajar ai'])
        self.assertNotIn('via', result['source_metadata']['google_autocomplete'])

    def test_without_titles_the_template_stays_a_fallback(self):
        result = self.run_category({}, ('fallback', 'HTTP 403'))
        self.assertEqual(result['evidence_suggestions'], [])
        self.assertEqual(result['source_metadata']['google_autocomplete']['status'], 'fallback')

    def test_search_titles_come_from_retrieved_results(self):
        blocks = [search_result('s1', (REDDIT, REDDIT_TITLE, None), ('https://situs.example/a', 'Milik sendiri', None),
                                ('https://spam.example.com/x', 'Slot gacor maxwin', None))]
        result = engine(message(blocks + [text(payload())])).research(CATEGORY, exclude_hosts=['situs.example'])
        self.assertEqual(result['search_titles'], [REDDIT_TITLE])


class Response:
    def __init__(self, status, body=b''):
        self.status_code = status
        self.content = body


class GoogleSuggestTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(seo_research.time, 'sleep')
        self.sleep = patcher.start()
        self.addCleanup(patcher.stop)

    def test_rate_limit_retries_with_backoff_and_the_chrome_client(self):
        body = '["modul ajar", ["modul ajar ai", "modul ajar kurikulum merdeka"], [], {}]'.encode('utf-8')
        with patch.object(seo_research.requests, 'get', side_effect=[Response(429), Response(200, body)]) as get:
            research = SEOResearch()
            found = research.get_keyword_suggestions('modul ajar')
        self.assertEqual(found, ['modul ajar ai', 'modul ajar kurikulum merdeka'])
        self.assertEqual(research.source_status['google_autocomplete']['status'], 'real')
        first, second = get.call_args_list
        self.assertEqual(first.kwargs['params']['client'], 'firefox')
        self.assertEqual(second.kwargs['params']['client'], 'chrome')
        self.assertEqual((first.kwargs['params']['ie'], first.kwargs['params']['oe']), ('utf-8', 'utf-8'))
        self.assertEqual(first.kwargs['params']['gl'], 'id')
        self.assertIn('Chrome/', first.kwargs['headers']['User-Agent'])
        self.assertTrue(first.kwargs['headers']['Accept-Language'].startswith('id-ID'))
        self.sleep.assert_called_once()

    def test_blocked_ip_is_not_hammered(self):
        with patch.object(seo_research.requests, 'get', return_value=Response(403)) as get:
            research = SEOResearch()
            found = research.get_keyword_suggestions('modul ajar')
            self.assertEqual(get.call_count, 1)
            questions = research.get_related_questions('modul ajar')
            self.assertEqual(get.call_count, 2)  # stops after the first blocked modifier
        self.assertEqual(found[0], 'tips modul ajar')  # template, never evidence
        meta = research.source_status['google_autocomplete']
        self.assertEqual((meta['status'], meta['reason']), ('fallback', 'HTTP 403'))
        self.assertTrue(questions)
        self.assertEqual(research.source_status['related_questions']['status'], 'fallback')

    def test_non_json_reply_tries_the_next_client(self):
        responses = [Response(200, b'<html>sorry</html>'), Response(200, b'["q", ["satu dua"]]')]
        with patch.object(seo_research.requests, 'get', side_effect=responses):
            self.assertEqual(SEOResearch().get_keyword_suggestions('q'), ['satu dua'])


if __name__ == '__main__':
    unittest.main()
