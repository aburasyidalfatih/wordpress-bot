"""Claude web research (services/claude_research.py) and its integration in
SEOResearch: request shape, cost controls, pause_turn handling, the hard
wall-clock cap, validation of everything the model returns against what was
really retrieved, error policy and fallback to the classic providers. No
network: the SDK client is a fake whose responses mirror the real content
block types and stream events.
"""
import json
import sys
import threading
import time
import types
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock, patch

try:
    import pytrends.request  # noqa: F401
except Exception:  # broken/missing pandas: stub, nothing here uses Trends
    for _name in ('pytrends', 'pytrends.request'):
        sys.modules[_name] = types.ModuleType(_name)
    sys.modules['pytrends.request'].TrendReq = object

# Other test modules replace seo_research with a bare stub; this file needs the real one.
for _module in ('trending_research', 'seo_research', 'services.claude_research'):
    if _module in sys.modules and not getattr(sys.modules[_module], '__file__', None):
        del sys.modules[_module]

import anthropic  # noqa: E402
import httpx2  # noqa: E402
from rq.timeouts import JobTimeoutException  # noqa: E402

import seo_research  # noqa: E402
from config import DEFAULT_ANTHROPIC_MODEL  # noqa: E402
from seo_research import SEOResearch  # noqa: E402
from services import ai_providers, claude_research  # noqa: E402
from services.ai_providers import merge_shared_ai_config  # noqa: E402
from services.claude_research import (  # noqa: E402
    ClaudeWebResearch, comparable_text, estimate_cost_usd, from_config, normalize_page_age, url_key,
)

REQUEST = httpx2.Request('POST', 'https://api.example.com/v1/messages')
TOPIC = 'lapor SPT tahunan'
TODAY = date.today()

COMP_URL = 'https://blog.example.com/spt'
COMP_TEXT = (
    "# Cara Lapor SPT Tahunan Online\n\n"
    "## Syarat Lapor SPT Tahunan\n\n"
    "SPT Tahunan adalah surat yang digunakan wajib pajak untuk melaporkan penghasilan, harta, "
    "dan kewajiban dalam satu tahun pajak. Pelaporan dilakukan secara daring melalui DJP Online.\n\n"
    "Batas Waktu\n"
    "Wajib pajak orang pribadi harus menyampaikan SPT paling lambat tanggal 31 Maret setiap tahun, "
    "sedangkan wajib pajak badan paling lambat 30 April.\n"
)
COMP_PASSAGE = ("SPT Tahunan adalah surat yang digunakan wajib pajak untuk melaporkan penghasilan, harta, "
                "dan kewajiban dalam satu tahun pajak.")
COMP_PASSAGE_2 = ("Wajib pajak orang pribadi harus menyampaikan SPT paling lambat tanggal 31 Maret setiap tahun, "
                  "sedangkan wajib pajak badan paling lambat 30 April.")
COMP2_URL = 'https://pajak.example.net/panduan'
COMP2_TEXT = ("Panduan SPT\nPelaporan SPT Tahunan bagi karyawan cukup memakai formulir 1770 S apabila penghasilan "
              "bruto setahun lebih dari enam puluh juta rupiah.\n")
COMP2_PASSAGE = ("Pelaporan SPT Tahunan bagi karyawan cukup memakai formulir 1770 S apabila penghasilan bruto "
                 "setahun lebih dari enam puluh juta rupiah.")
OFFICIAL_URL = 'https://www.pajak.go.id/id/spt-tahunan'
OFFICIAL_TEXT = (
    "SPT Tahunan PPh Orang Pribadi\n"
    "Batas waktu penyampaian SPT Tahunan PPh Orang Pribadi adalah paling lambat tiga bulan setelah "
    "akhir tahun pajak. Keterlambatan dikenai sanksi denda sebesar Rp100.000.\n"
)
OFFICIAL_PASSAGE = ("Batas waktu penyampaian SPT Tahunan PPh Orang Pribadi adalah paling lambat tiga bulan "
                    "setelah akhir tahun pajak.")
SEARCH_ONLY_URL = 'https://other.example.com/panduan-spt'
NEWS_URL = 'https://berita.example.com/2026/09/spt'
WIKI_URL = 'https://id.wikipedia.org/wiki/Surat_Pemberitahuan'
WIKI_TEXT = (
    "Surat Pemberitahuan\n"
    "Surat Pemberitahuan (SPT) adalah surat yang oleh wajib pajak digunakan untuk melaporkan "
    "penghitungan dan pembayaran pajak,[1] objek pajak dan bukan objek pajak, serta harta dan kewajiban "
    "sesuai ketentuan peraturan perundang-undangan perpajakan.[2](https://id.wikipedia.org/wiki/SPT#cite_note-2) "
    "SPT terdiri atas SPT Masa dan SPT Tahunan.[catatan 1]\n"
)
WIKI_SUMMARY = (
    "Surat Pemberitahuan (SPT) adalah surat yang oleh wajib pajak digunakan untuk melaporkan "
    "penghitungan dan pembayaran pajak, objek pajak dan bukan objek pajak, serta harta dan kewajiban "
    "sesuai ketentuan peraturan perundang-undangan perpajakan."
)


# ---------------------------------------------------------------------------
# Fake SDK objects, mirroring the real block types and stream events
# ---------------------------------------------------------------------------

def tool_use(name, tool_id, **tool_input):
    return SimpleNamespace(type='server_tool_use', id=tool_id, name=name, input=tool_input,
                           caller=SimpleNamespace(type='direct'))


def search_result(tool_id, *results):
    return SimpleNamespace(type='web_search_tool_result', tool_use_id=tool_id, caller=None, content=[
        SimpleNamespace(type='web_search_result', url=url, title=title, page_age=page_age,
                        encrypted_content='enc')
        for url, title, page_age in results
    ])


def search_error(tool_id, code='too_many_requests'):
    return SimpleNamespace(type='web_search_tool_result', tool_use_id=tool_id, caller=None,
                           content=SimpleNamespace(type='web_search_tool_result_error', error_code=code))


def fetch_result(tool_id, url, text, title=None):
    document = SimpleNamespace(type='document', title=title, citations=SimpleNamespace(enabled=True),
                               source=SimpleNamespace(type='text', media_type='text/plain', data=text))
    return SimpleNamespace(type='web_fetch_tool_result', tool_use_id=tool_id, caller=None,
                           content=SimpleNamespace(type='web_fetch_result', url=url, retrieved_at=None,
                                                   content=document))


def fetch_error(tool_id, code='url_not_accessible'):
    return SimpleNamespace(type='web_fetch_tool_result', tool_use_id=tool_id, caller=None,
                           content=SimpleNamespace(type='web_fetch_tool_result_error', error_code=code))


def text(value):
    return SimpleNamespace(type='text', text=value, citations=None)


def message(content, stop_reason='end_turn', searches=1, fetches=1, stop_details=None, input_tokens=1000,
            cache_read=0, cache_write=0):
    usage = SimpleNamespace(input_tokens=input_tokens, output_tokens=200, cache_read_input_tokens=cache_read,
                            cache_creation_input_tokens=cache_write,
                            server_tool_use=SimpleNamespace(web_search_requests=searches,
                                                            web_fetch_requests=fetches))
    return SimpleNamespace(content=content, stop_reason=stop_reason, stop_details=stop_details, usage=usage)


def block_start(block_type):
    return SimpleNamespace(type='content_block_start', content_block=SimpleNamespace(type=block_type))


class FakeStream:
    """Stands in for the SDK's MessageStream manager: yields events, then either
    finishes (get_final_message) or raises `error` mid-stream."""

    def __init__(self, final=None, events=(), error=None, block_until_closed=False):
        self.final = final
        self.events = list(events)
        self.error = error
        self.block_until_closed = block_until_closed
        self.closed = threading.Event()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.closed.set()
        return False

    def __iter__(self):
        for event in self.events:
            yield event
        if self.block_until_closed:
            while not self.closed.wait(0.01):
                pass
            raise anthropic.APIConnectionError(request=REQUEST)
        if self.error is not None:
            raise self.error

    def close(self):
        self.closed.set()

    def get_final_message(self):
        return self.final


def fake_client(*outcomes):
    """A client whose stream() returns outcomes in order: a message, a FakeStream,
    or an exception raised when the stream is opened. One Mock backs both
    client.messages.stream and client.beta.messages.stream."""
    queue = list(outcomes)
    opened = []

    def stream(**kwargs):
        outcome = queue.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        manager = outcome if isinstance(outcome, FakeStream) else FakeStream(final=outcome)
        opened.append(manager)
        return manager

    mock = Mock(side_effect=stream)
    return SimpleNamespace(messages=SimpleNamespace(stream=mock), opened=opened,
                           beta=SimpleNamespace(messages=SimpleNamespace(stream=mock)))


def payload(competitors=(), official=(), news=(), social=(), questions=(), youtube=()):
    return json.dumps({'competitors': list(competitors), 'official': list(official), 'news': list(news),
                       'social': list(social), 'questions': list(questions), 'youtube': list(youtube)})


def research_blocks():
    """A full successful turn: searches and fetches (the final JSON is added per test)."""
    return [
        tool_use('web_search', 's1', query=TOPIC),
        search_result('s1', (COMP_URL, 'Cara Lapor SPT Tahunan Online', None),
                      (SEARCH_ONLY_URL, 'Panduan Lapor SPT Tahunan', 'September 2, 2026'),
                      ('https://situs.example/spt', 'Artikel kami tentang SPT', None),
                      ('https://pajak-go-id.example.com/spt', 'SPT Tahunan resmi?', None)),
        tool_use('web_search', 's2', query=f'{TOPIC} site:go.id'),
        search_result('s2', (OFFICIAL_URL, 'SPT Tahunan - DJP', None)),
        tool_use('web_fetch', 'f1', url=COMP_URL),
        fetch_result('f1', COMP_URL, COMP_TEXT, title='Cara Lapor SPT'),
        tool_use('web_fetch', 'f2', url=OFFICIAL_URL),
        fetch_result('f2', OFFICIAL_URL, OFFICIAL_TEXT),
        tool_use('web_fetch', 'f3', url='https://pajak-go-id.example.com/spt'),
        fetch_result('f3', 'https://pajak-go-id.example.com/spt', OFFICIAL_TEXT),
    ]


def engine(*outcomes, model='claude-opus-5-5'):
    return ClaudeWebResearch('test-key', model, client=fake_client(*outcomes))


def comp(url=COMP_URL, passages=(COMP_PASSAGE,), headings=()):
    return {'url': url, 'title': 'model title', 'headings': list(headings), 'passages': list(passages)}


class FastRetryMixin:
    def setUp(self):
        patcher = patch.object(claude_research, 'RETRY_DELAY_SECONDS', 0)
        patcher.start()
        self.addCleanup(patcher.stop)


class RequestShapeTests(unittest.TestCase):
    def run_research(self, language='id', model='claude-opus-5-5'):
        research = engine(message(research_blocks() + [text(payload())]), model=model)
        research.research(TOPIC, language, category='Pajak', exclude_hosts=['https://www.situs.example/'])
        return research.client.messages.stream.call_args.kwargs

    def test_tools_and_streaming_request(self):
        kwargs = self.run_research()
        search, fetch = kwargs['tools']
        self.assertEqual(search, {
            'type': 'web_search_20260209', 'name': 'web_search', 'max_uses': 6, 'allowed_callers': ['direct'],
            'user_location': {'type': 'approximate', 'country': 'ID', 'timezone': 'Asia/Jakarta'},
            'blocked_domains': ['situs.example'],
        })
        self.assertEqual(fetch, {
            'type': 'web_fetch_20260209', 'name': 'web_fetch', 'max_uses': 5, 'max_content_tokens': 6000,
            'citations': {'enabled': True}, 'allowed_callers': ['direct'], 'blocked_domains': ['situs.example'],
        })
        self.assertNotIn('allowed_domains', search)
        self.assertFalse(any('code_execution' in tool['type'] for tool in kwargs['tools']))
        # Automatic prompt caching for the server-side loop and continuations,
        # plus an explicit breakpoint on the static prefix (tools + system).
        self.assertEqual(kwargs['cache_control'], {'type': 'ephemeral'})
        self.assertEqual(kwargs['system'], [{'type': 'text', 'text': claude_research.SYSTEM_PROMPT,
                                             'cache_control': {'type': 'ephemeral'}}])
        # Same API surface as AnthropicText: refusal fallback beta, effort, no sampling params.
        self.assertEqual(kwargs['betas'], [ai_providers.CLAUDE_FALLBACK_BETA])
        self.assertEqual(kwargs['fallbacks'], 'default')
        self.assertEqual(kwargs['output_config'], {'effort': ai_providers.CLAUDE_EFFORT})
        self.assertNotIn('temperature', kwargs)
        self.assertNotIn('top_p', kwargs)
        self.assertNotIn('thinking', kwargs)
        self.assertEqual(kwargs['model'], 'claude-opus-5-5')
        self.assertLessEqual(kwargs['timeout'], claude_research.CLIENT_TIMEOUT_SECONDS)
        self.assertEqual(len(kwargs['messages']), 1)
        prompt = kwargs['messages'][0]['content']
        self.assertIn(TOPIC, prompt)
        self.assertIn('site:go.id', prompt)
        self.assertIn('situs.example', prompt)
        self.assertIn('never re-fetch', prompt)
        self.assertIn('never fetch the same page twice', claude_research.SYSTEM_PROMPT)
        self.assertIn('is thin: fetch another candidate', claude_research.SYSTEM_PROMPT)
        # Social listening and reader questions are part of the same call; Wikipedia is not.
        self.assertIn('Social listening', prompt)
        self.assertIn('kaskus.co.id', prompt)
        self.assertIn('Reader questions', prompt)
        self.assertNotIn('Videos:', prompt)
        self.assertNotIn('wikipedia', prompt.lower())
        self.assertNotIn('wikipedia', claude_research.SYSTEM_PROMPT.lower())
        for part in ('"social"', '"questions"', '"youtube"'):
            self.assertIn(part, claude_research.SYSTEM_PROMPT)

    def test_english_uses_us_location_and_gov(self):
        kwargs = self.run_research(language='en')
        self.assertEqual(kwargs['tools'][0]['user_location'], {'type': 'approximate', 'country': 'US'})
        self.assertIn('site:.gov', kwargs['messages'][0]['content'])
        self.assertNotIn('kaskus', kwargs['messages'][0]['content'])

    def test_model_without_fallback_uses_plain_stream(self):
        research = engine(message(research_blocks() + [text(payload())]), model='claude-haiku-4-5')
        research.research(TOPIC)
        kwargs = research.client.messages.stream.call_args.kwargs
        self.assertNotIn('betas', kwargs)
        self.assertNotIn('output_config', kwargs)

    def test_no_exclusion_means_no_blocked_domains(self):
        research = engine(message(research_blocks() + [text(payload())]))
        research.research(TOPIC, exclude_hosts=['gov'])  # a bare TLD is never sent
        tools = research.client.messages.stream.call_args.kwargs['tools']
        self.assertNotIn('blocked_domains', tools[0])
        self.assertNotIn('blocked_domains', tools[1])

    def test_unrequested_parts_are_left_out_of_the_prompt(self):
        research = engine(message(research_blocks() + [text(payload())]))
        research.research(TOPIC, want_official=False, want_news=False, want_social=False, want_questions=False)
        prompt = research.client.messages.stream.call_args.kwargs['messages'][0]['content']
        self.assertNotIn('site:go.id', prompt)
        self.assertNotIn('News:', prompt)
        self.assertNotIn('Social listening', prompt)
        self.assertNotIn('Reader questions', prompt)
        research = engine(message(research_blocks() + [text(payload())]))
        research.research(TOPIC, want_youtube=True)
        self.assertIn('2. Official sources', research.client.messages.stream.call_args.kwargs['messages'][0]['content'])
        self.assertIn('Videos: find up to 2 relevant YouTube videos',
                      research.client.messages.stream.call_args.kwargs['messages'][0]['content'])


class CostTests(unittest.TestCase):
    def test_estimate_uses_opus_prices(self):
        usage = {'input_tokens': 100_000, 'output_tokens': 10_000, 'cache_read_input_tokens': 200_000,
                 'cache_creation_input_tokens': 40_000}
        # 0.40 input + 0.20 output + 0.04 cache read + 0.20 cache write + 5 x 0.01 searches
        self.assertAlmostEqual(estimate_cost_usd(usage, 5), 0.89)

    def test_stats_and_log_report_usage_and_cost(self):
        research = engine(message(research_blocks() + [text(payload(competitors=[comp()]))], searches=2,
                                  fetches=3, input_tokens=50_000, cache_read=100_000, cache_write=20_000))
        with self.assertLogs('services.claude_research', 'INFO') as logs:
            stats = research.research(TOPIC)['stats']
        self.assertEqual((stats['searches'], stats['fetches']), (2, 3))
        self.assertEqual(stats['cache_read_input_tokens'], 100_000)
        self.assertEqual(stats['cache_creation_input_tokens'], 20_000)
        self.assertAlmostEqual(stats['estimated_cost_usd'], 0.2 + 0.004 + 0.02 + 0.1 + 0.02, places=4)
        line = logs.output[-1]
        self.assertIn('cache_read=100000', line)
        self.assertIn('cache_write=20000', line)
        self.assertIn('est_cost=$0.34', line)


class ContinuationTests(unittest.TestCase):
    def test_pause_turn_resends_user_message_and_remaining_budget(self):
        first = message(research_blocks()[:4], stop_reason='pause_turn', searches=2, fetches=0)
        second = message(research_blocks()[4:] + [text(payload(competitors=[comp()]))], searches=0, fetches=3)
        research = engine(first, second)
        result = research.research(TOPIC)
        calls = research.client.messages.stream.call_args_list
        self.assertEqual(len(calls), 2)
        first_kwargs, resumed = calls[0].kwargs, calls[1].kwargs
        self.assertEqual(resumed['messages'][0], first_kwargs['messages'][0])
        self.assertEqual(resumed['messages'][1], {'role': 'assistant', 'content': first.content})
        self.assertEqual(len(resumed['messages']), 2)  # no extra "continue" message
        # The search/fetch limits are totals: only what is left is offered.
        self.assertEqual([tool['max_uses'] for tool in resumed['tools']], [4, 5])
        self.assertEqual([tool['max_uses'] for tool in first_kwargs['tools']], [6, 5])
        self.assertEqual([c['url'] for c in result['competitors']], [COMP_URL])
        self.assertEqual(result['stats']['continuations'], 1)
        self.assertEqual((result['stats']['searches'], result['stats']['fetches']), (2, 3))

    def test_second_pause_carries_all_assistant_content(self):
        first = message(research_blocks()[:2], stop_reason='pause_turn', searches=1, fetches=0)
        second = message(research_blocks()[2:4], stop_reason='pause_turn', searches=1, fetches=0)
        third = message([text(payload())], searches=0, fetches=0)
        research = engine(first, second, third)
        self.assertIsNotNone(research.research(TOPIC))
        resumed = research.client.messages.stream.call_args_list[2].kwargs
        self.assertEqual(resumed['messages'][1]['content'], list(first.content) + list(second.content))
        self.assertEqual([tool['max_uses'] for tool in resumed['tools']], [4, 5])

    def test_spent_budget_stops_instead_of_continuing(self):
        paused = message(research_blocks()[:2], stop_reason='pause_turn', searches=6, fetches=1)
        research = engine(paused, message([text(payload())]))
        self.assertIsNone(research.research(TOPIC))
        self.assertEqual(research.client.messages.stream.call_count, 1)

    def test_budget_counted_from_result_blocks_without_usage(self):
        blocks = [search_result(f's{i}', (f'https://e{i}.example.com/', 't', None)) for i in range(6)]
        paused = message(blocks, stop_reason='pause_turn')
        paused.usage.server_tool_use = None
        research = engine(paused, message([text(payload())]))
        self.assertIsNone(research.research(TOPIC))
        self.assertEqual(research.client.messages.stream.call_count, 1)

    def test_continuations_are_capped(self):
        paused = [message([tool_use('web_search', f's{i}', query='x')], stop_reason='pause_turn',
                          searches=0, fetches=0) for i in range(5)]
        research = engine(*paused)
        self.assertIsNone(research.research(TOPIC))
        self.assertEqual(research.client.messages.stream.call_count, claude_research.MAX_CONTINUATIONS + 1)
        self.assertTrue(research.last_error)

    def test_no_continuation_with_less_than_a_minute_left(self):
        paused = message([tool_use('web_search', 's1', query='x')], stop_reason='pause_turn', searches=1, fetches=0)
        research = engine(paused, message([text(payload())]))
        clock = iter([0, 0, 0, 0] + [200] * 20)  # start, deadline, request, stream end; then 200 s later
        with patch.object(claude_research, '_now', lambda: next(clock)):
            self.assertIsNone(research.research(TOPIC))
        self.assertEqual(research.client.messages.stream.call_count, 1)


class WallClockTests(FastRetryMixin, unittest.TestCase):
    def test_stream_aborted_when_the_deadline_passes_between_events(self):
        stream = FakeStream(final=message([text(payload())]),
                            events=[block_start('thinking'), block_start('server_tool_use'), block_start('text')])
        research = engine(stream)
        ticks = iter([0, 0, 0, 0, 10, 250] + [250] * 20)
        with patch.object(claude_research, '_now', lambda: next(ticks)):
            self.assertIsNone(research.research(TOPIC))
        self.assertTrue(stream.closed.is_set())
        self.assertEqual(research.client.messages.stream.call_count, 1)

    def test_watchdog_closes_a_stalled_stream(self):
        stream = FakeStream(block_until_closed=True)
        research = engine(stream, message([text(payload())]))
        with patch.object(claude_research, 'RESEARCH_BUDGET_SECONDS', 0.3), \
                patch.object(claude_research, 'MIN_REQUEST_SECONDS', 0):
            started = time.monotonic()
            self.assertIsNone(research.research(TOPIC))
        self.assertLess(time.monotonic() - started, 5)
        self.assertTrue(stream.closed.is_set())
        # A budget overrun is not retried.
        self.assertEqual(research.client.messages.stream.call_count, 1)


class ValidationTests(unittest.TestCase):
    def run_payload(self, data, blocks=None, **options):
        blocks = research_blocks() if blocks is None else blocks
        research = engine(message(blocks + [text(data)]))
        return research.research(TOPIC, exclude_hosts=['situs.example'], **options)

    def test_verified_competitor_with_passages_and_headings(self):
        result = self.run_payload(payload(competitors=[comp(
            headings=['Syarat Lapor SPT Tahunan', 'Batas waktu', 'Heading yang tidak ada di halaman', 'SPT'],
            # Case and spacing differences still count as verbatim.
            passages=['  ' + COMP_PASSAGE.upper() + '  ', 'Kalimat ini tidak pernah ada di halaman itu sama sekali, '
                                                          'apa pun yang dikatakan modelnya.'],
        )]))
        [competitor] = result['competitors']
        self.assertEqual(competitor['url'], COMP_URL)
        self.assertEqual(competitor['title'], 'Cara Lapor SPT Tahunan Online')  # retrieved, never the model's
        self.assertEqual(competitor['headers'], ['Syarat Lapor SPT Tahunan', 'Batas waktu'])
        self.assertEqual(competitor['key_passages'], [COMP_PASSAGE.upper()])
        self.assertEqual(competitor['retrieved_via'], 'claude_web')
        self.assertGreater(competitor['word_count'], 20)

    def test_heading_must_be_a_heading_line_or_a_long_verbatim_match(self):
        result = self.run_payload(payload(competitors=[comp(headings=[
            'pajak untuk',                      # substring of a sentence, too short: rejected
            'Pelaporan dilakukan secara daring',  # >= 12 chars and verbatim: accepted
            'Cara Lapor SPT Tahunan Online',    # markdown heading line: accepted
        ])]))
        self.assertEqual(result['competitors'][0]['headers'],
                         ['Pelaporan dilakukan secara daring', 'Cara Lapor SPT Tahunan Online'])

    def test_short_passages_are_dropped(self):
        short = 'Pelaporan dilakukan secara daring melalui DJP Online.'  # verbatim, but < 60 chars
        self.assertLess(len(short), claude_research.MIN_PASSAGE_CHARS)
        result = self.run_payload(payload(competitors=[comp(passages=[short])]))
        self.assertEqual(result['competitors'], [])

    def test_url_not_retrieved_is_dropped(self):
        result = self.run_payload(payload(
            competitors=[comp(url='https://invented.example.com/spt')],
            official=[{'url': 'https://www.djp.go.id/karangan', 'passages': [OFFICIAL_PASSAGE]}],
            news=[{'url': 'https://news.example.com/x'}],
        ))
        self.assertEqual(result['competitors'], [])
        self.assertEqual(result['official_sources'], [])
        self.assertEqual(result['news'], [])

    def test_url_variants_match_the_retrieved_url(self):
        result = self.run_payload(payload(competitors=[
            comp(url='http://www.blog.example.com/spt/?utm_source=x&fbclid=1#bagian')]))
        self.assertEqual([c['url'] for c in result['competitors']], [COMP_URL])

    def test_non_ascii_and_percent_encoded_paths_match(self):
        url = 'https://kamus.example.com/pajak-%C3%A9lite'
        blocks = [fetch_result('f1', url, COMP_TEXT, title='Pajak')]
        result = self.run_payload(payload(competitors=[comp(url='https://kamus.example.com/pajak-élite')]),
                                  blocks=blocks)
        self.assertEqual([c['url'] for c in result['competitors']], [url])
        self.assertEqual(url_key('https://kamus.example.com/pajak-élite?utm_medium=x'), url_key(url))

    def test_search_only_and_unverified_competitors_are_dropped(self):
        result = self.run_payload(payload(competitors=[
            comp(passages=['SPT Tahunan ialah formulir untuk melaporkan pajak setahun penuh bagi semua orang.']),
            comp(url=SEARCH_ONLY_URL, passages=['Passage yang tidak bisa diverifikasi karena halaman tidak '
                                                'di-fetch sama sekali oleh model.']),
        ]))
        self.assertEqual(result['competitors'], [])

    def test_title_falls_back_to_host_never_to_model_text(self):
        url = 'https://tanpa-judul.example.com/spt'
        blocks = [fetch_result('f1', url, COMP_TEXT, title=None)]
        result = self.run_payload(payload(competitors=[comp(url=url)]), blocks=blocks)
        self.assertEqual(result['competitors'][0]['title'], 'tanpa-judul.example.com')

    def test_official_host_is_validated(self):
        result = self.run_payload(payload(official=[
            {'url': 'https://pajak-go-id.example.com/spt', 'title': 'Palsu', 'passages': [OFFICIAL_PASSAGE]},
            {'url': OFFICIAL_URL, 'title': 'DJP', 'passages': [OFFICIAL_PASSAGE]},
            {'url': COMP_URL, 'title': 'Blog', 'passages': [COMP_PASSAGE]},
        ]))
        self.assertEqual(result['official_sources'], [
            {'title': 'SPT Tahunan - DJP', 'url': OFFICIAL_URL, 'passages': [OFFICIAL_PASSAGE]}])

    def test_official_without_verified_passage_is_dropped(self):
        result = self.run_payload(payload(official=[{'url': OFFICIAL_URL, 'passages': []}]))
        self.assertEqual(result['official_sources'], [])

    def test_own_domain_is_excluded(self):
        blocks = research_blocks() + [fetch_result('f9', 'https://situs.example/spt', COMP_TEXT)]
        result = self.run_payload(payload(competitors=[comp(url='https://situs.example/spt')],
                                          news=[{'url': 'https://situs.example/spt'}]), blocks=blocks)
        self.assertEqual(result['competitors'], [])
        self.assertEqual(result['news'], [])

    def test_spam_pages_are_dropped(self):
        spam_url = 'https://spam.example.com/spt'
        spam_text = COMP_TEXT + "\nDaftar slot gacor maxwin hari ini, situs slot terpercaya.\n"
        blocks = research_blocks() + [fetch_result('f8', spam_url, spam_text, title='Lapor SPT')]
        result = self.run_payload(payload(competitors=[comp(url=spam_url)]), blocks=blocks)
        self.assertEqual(result['competitors'], [])
        # One marker is enough to reject a government page.
        gov_url = 'https://desa.example.go.id/spt'
        blocks = research_blocks() + [fetch_result('f7', gov_url, OFFICIAL_TEXT + "\nslot gacor\n")]
        result = self.run_payload(payload(official=[{'url': gov_url, 'passages': [OFFICIAL_PASSAGE]}]),
                                  blocks=blocks)
        self.assertEqual(result['official_sources'], [])

    def test_spam_marker_exempt_when_topic_is_about_it(self):
        url = 'https://edukasi.example.com/judi'
        quote = ('Judi online merusak keuangan keluarga karena kerugian yang terus berulang dan utang yang '
                 'menumpuk dari bulan ke bulan.')
        blocks = [fetch_result('f1', url, f"Bahaya judi online bagi keluarga\n{quote}\n", title='Bahaya judi online')]
        research = engine(message(blocks + [text(payload(competitors=[comp(url=url, passages=[quote])]))]))
        self.assertEqual(len(research.research('bahaya judi online')['competitors']), 1)

    def test_sizes_are_capped(self):
        sentence = 'Wajib pajak orang pribadi harus menyampaikan SPT paling lambat tanggal 31 Maret setiap tahun'
        long_passage = (sentence + ', ') * 12
        facts = [f'Fakta nomor {i} tentang lapor SPT tahunan bagi semua wajib pajak orang pribadi di Indonesia.'
                 for i in range(10)]
        page = long_passage + '\n' + '\n'.join(facts)
        blocks = [fetch_result(f'f{i}', f'https://site{i}.example.com/spt', page, title=f'Lapor SPT {i}')
                  for i in range(6)]
        competitors = [comp(url=f'https://site{i}.example.com/spt', passages=[long_passage] + facts) for i in range(6)]
        result = engine(message(blocks + [text(payload(competitors=competitors))])).research(TOPIC)
        self.assertEqual(len(result['competitors']), 4)
        for item in result['competitors']:
            self.assertLessEqual(len(item['key_passages']), 5)
            self.assertTrue(all(len(p) <= 600 for p in item['key_passages']))
            self.assertLessEqual(sum(len(p) for p in item['key_passages']), 2500)
        limited = engine(message(blocks + [text(payload(competitors=competitors))])).research(
            TOPIC, competitor_limit=3)
        self.assertEqual(len(limited['competitors']), 3)

    def test_news_comes_from_search_results_not_model_text(self):
        old = 'https://berita.example.com/lama'
        undated = 'https://berita.example.com/tanpa-tanggal'
        fetched_only = 'https://berita.example.com/fetched'
        blocks = research_blocks() + [
            search_result('s3', (NEWS_URL, 'Batas lapor SPT diperpanjang - Berita Contoh', '3 days ago'),
                          (old, 'Berita lama SPT', 'January 5, 2019'),
                          (undated, 'Berita SPT tanpa tanggal', None)),
            fetch_result('f5', fetched_only, COMP_TEXT, title='Berita yang hanya di-fetch'),
        ]
        result = self.run_payload(payload(news=[
            {'url': NEWS_URL, 'title': 'judul karangan', 'source': 'Sumber karangan', 'date': '2020-01-01'},
            {'url': old}, {'url': undated}, {'url': fetched_only},
        ]), blocks=blocks)
        self.assertEqual(result['news'], [{
            'title': 'Batas lapor SPT diperpanjang - Berita Contoh', 'source': 'Berita Contoh', 'url': NEWS_URL,
            'published_at': normalize_page_age('3 days ago'),
        }])

    def test_news_source_falls_back_to_host(self):
        blocks = [search_result('s1', (NEWS_URL, 'Batas lapor SPT diperpanjang', '2026-10-01T08:00:00Z'))]
        with patch.object(claude_research, 'NEWS_MAX_AGE_DAYS', 100000):
            result = self.run_payload(payload(news=[{'url': NEWS_URL}]), blocks=blocks)
        self.assertEqual(result['news'][0]['source'], 'berita.example.com')
        self.assertEqual(result['news'][0]['published_at'], '2026-10-01')

    def test_footnote_markers_do_not_break_the_verbatim_check(self):
        url = 'https://id.example.org/spt'
        page = ('SPT adalah surat yang oleh wajib pajak digunakan untuk melaporkan penghitungan pajak,[1] '
                'objek pajak dan harta.[2](https://id.example.org/spt#cite_note-2) Lainnya.[catatan 1]\n')
        quote = ('SPT adalah surat yang oleh wajib pajak digunakan untuk melaporkan penghitungan pajak, '
                 'objek pajak dan harta.')
        result = self.run_payload(payload(competitors=[comp(url=url, passages=[quote, quote + '[1]'])]),
                                  blocks=[fetch_result('f1', url, page, title='SPT')])
        self.assertEqual(result['competitors'][0]['key_passages'], [quote])

    def test_server_tool_errors_do_not_raise(self):
        blocks = [
            tool_use('web_search', 's1', query=TOPIC),
            search_error('s1'),
            tool_use('web_search', 's2', query=TOPIC),
            search_result('s2', (COMP_URL, 'Cara Lapor SPT Tahunan Online', None)),
            tool_use('web_fetch', 'f1', url=COMP_URL),
            fetch_error('f1'),
        ]
        result = self.run_payload(payload(competitors=[comp()]), blocks=blocks)
        # The fetch failed, so nothing can be verified and the page is not used.
        self.assertEqual(result['competitors'], [])
        self.assertEqual(result['stats']['tool_errors'], ['web_search:too_many_requests',
                                                          'web_fetch:url_not_accessible'])

    def test_same_host_redirect_keeps_the_fetched_text(self):
        requested = 'http://blog.example.com/spt-lama'
        moved_gov = 'https://www.pajak.go.id/spt-lama'
        blocks = [
            tool_use('web_fetch', 'f1', url=requested),
            fetch_result('f1', COMP_URL, COMP_TEXT, title='Lapor SPT'),
            tool_use('web_fetch', 'f2', url=moved_gov),
            fetch_result('f2', 'https://pajak-palsu.example.com/spt', OFFICIAL_TEXT),
        ]
        result = self.run_payload(payload(
            competitors=[comp(url=requested)],
            official=[{'url': moved_gov, 'passages': [OFFICIAL_PASSAGE]}],
        ), blocks=blocks)
        self.assertEqual(result['competitors'][0]['key_passages'], [COMP_PASSAGE])
        # Redirected off the government host: the text is not credited to the .go.id URL.
        self.assertEqual(result['official_sources'], [])

    def test_json_in_code_fence_after_prose(self):
        result = self.run_payload(f'Berikut hasilnya:\n```json\n{payload(competitors=[comp()])}\n```')
        self.assertEqual(len(result['competitors']), 1)


class HelperTests(unittest.TestCase):
    def test_normalize_page_age(self):
        today = date(2026, 10, 25)
        self.assertEqual(normalize_page_age('2026-09-01T10:00:00Z', today), '2026-09-01')
        self.assertEqual(normalize_page_age('3 days ago', today), '2026-10-22')
        self.assertEqual(normalize_page_age('2 weeks ago', today), '2026-10-11')
        self.assertEqual(normalize_page_age('5 hours ago', today), '2026-10-25')
        self.assertEqual(normalize_page_age('September 2, 2026', today), '2026-09-02')
        self.assertEqual(normalize_page_age('2 Sep 2026', today), '2026-09-02')
        self.assertIsNone(normalize_page_age('kemarin', today))
        self.assertIsNone(normalize_page_age(None, today))

    def test_comparable_text_drops_footnote_markers(self):
        self.assertEqual(comparable_text('Pajak[1] adalah iuran.[catatan 2] [a]'), 'pajak adalah iuran.')
        self.assertEqual(comparable_text('Pajak.[3](https://id.wikipedia.org/wiki/P#cite_note-3) Lalu'),
                         'pajak. lalu')


class ErrorPolicyTests(FastRetryMixin, unittest.TestCase):
    def ok(self):
        return message(research_blocks() + [text(payload(competitors=[comp()]))])

    def test_refusal_returns_none(self):
        research = engine(message([], stop_reason='refusal', stop_details=SimpleNamespace(category='cyber')))
        self.assertIsNone(research.research(TOPIC))
        self.assertIn('cadangan', research.last_error)

    def test_truncation_returns_none(self):
        self.assertIsNone(engine(message([text('{"competitors": [')], stop_reason='max_tokens')).research(TOPIC))

    def test_parse_failure_returns_none(self):
        self.assertIsNone(engine(message(research_blocks() + [text('Maaf, saya tidak menemukan apa pun.')]))
                          .research(TOPIC))

    def test_retryable_error_before_any_tool_is_retried_once(self):
        overloaded = anthropic.APIStatusError('overloaded', response=httpx2.Response(529, request=REQUEST), body=None)
        research = engine(FakeStream(events=[block_start('thinking')], error=overloaded), self.ok())
        result = research.research(TOPIC)
        self.assertEqual(len(result['competitors']), 1)
        self.assertEqual(research.client.messages.stream.call_count, 2)

    def test_no_retry_once_a_server_tool_ran(self):
        for started in ('server_tool_use', 'web_search_tool_result'):
            research = engine(FakeStream(events=[block_start(started)],
                                         error=anthropic.APIConnectionError(request=REQUEST)), self.ok())
            self.assertIsNone(research.research(TOPIC))
            self.assertEqual(research.client.messages.stream.call_count, 1)

    def test_second_retryable_error_gives_up(self):
        research = engine(anthropic.APIConnectionError(request=REQUEST),
                          anthropic.APIConnectionError(request=REQUEST), self.ok())
        self.assertIsNone(research.research(TOPIC))
        self.assertEqual(research.client.messages.stream.call_count, 2)

    def test_non_retryable_error_is_not_retried(self):
        bad = anthropic.APIStatusError('bad', response=httpx2.Response(400, request=REQUEST), body=None)
        research = engine(bad, self.ok())
        self.assertIsNone(research.research(TOPIC))
        self.assertEqual(research.client.messages.stream.call_count, 1)

    def test_job_timeout_propagates_when_called_on_the_main_thread(self):
        with self.assertRaises(JobTimeoutException):
            engine(JobTimeoutException('deadline')).research(TOPIC)


class FactoryTests(unittest.TestCase):
    def test_own_key_and_model(self):
        research = from_config({'anthropic_api_key': 'own-key', 'anthropic_model': 'claude-sonnet-5-5'})
        self.assertIsInstance(research, ClaudeWebResearch)
        self.assertEqual(research.model, 'claude-sonnet-5-5')
        self.assertEqual(research.client.api_key, 'own-key')
        self.assertEqual(research.client.max_retries, 0)

    def test_default_model_when_unset(self):
        self.assertEqual(from_config({'anthropic_api_key': 'k', 'anthropic_model': ''}).model,
                         DEFAULT_ANTHROPIC_MODEL)

    def test_no_key_means_classic(self):
        self.assertIsNone(from_config({'gemini_api_key': 'g', 'anthropic_api_key': ''}))
        self.assertIsNone(from_config({}))
        self.assertIsNone(from_config(None))
        self.assertIsNone(from_config(Mock()))

    def test_shared_admin_key_reaches_users(self):
        admin = {'ai_text_provider': 'gemini', 'gemini_api_key': 'admin-g', 'anthropic_api_key': 'admin-a',
                 'anthropic_model': 'claude-opus-5-5'}
        research = from_config(merge_shared_ai_config({'gemini_api_key': ''}, admin))
        self.assertEqual(research.client.api_key, 'admin-a')
        self.assertEqual(research.model, 'claude-opus-5-5')
        own = from_config(merge_shared_ai_config({'anthropic_api_key': 'user-a'}, admin))
        self.assertEqual(own.client.api_key, 'user-a')

    def test_kill_switch(self):
        with patch.object(claude_research, 'CLAUDE_WEB_RESEARCH_ENABLED', False):
            self.assertIsNone(from_config({'anthropic_api_key': 'k'}))


# ---------------------------------------------------------------------------
# SEOResearch integration
# ---------------------------------------------------------------------------

def claude_competitor(url=COMP_URL, passages=(COMP_PASSAGE, COMP_PASSAGE_2)):
    return {'url': url, 'title': 'Cara Lapor', 'headers': ['Syarat'], 'heading_count': 1, 'word_count': 50,
            'published_hint': None, 'key_passages': list(passages), 'retrieved_via': 'claude_web'}


CLAUDE_COMPETITORS = [claude_competitor(), claude_competitor(COMP2_URL, (COMP2_PASSAGE, COMP_PASSAGE))]
THIN_COMPETITOR = claude_competitor('https://thin.example.com/x', (COMP_PASSAGE,))
CLAUDE_OFFICIAL = {'title': 'DJP', 'url': OFFICIAL_URL, 'passages': [OFFICIAL_PASSAGE]}
CLAUDE_NEWS = {'title': 'Berita SPT', 'source': 'Contoh', 'url': NEWS_URL, 'published_at': '2026-09-20'}
CLAUDE_SOCIAL = [{'text': 'Bagaimana cara lapor SPT kalau lupa EFIN?', 'url': 'https://www.reddit.com/r/x/1',
                  'provider': 'reddit'}]
CLAUDE_QUESTIONS = ['Kapan batas lapor SPT tahunan?', 'Bagaimana cara lapor SPT tahunan online?',
                    'Apa sanksi telat lapor SPT tahunan?']
CLAUDE_VIDEOS = [{'video_id': 'abcdefghijk', 'title': 'Cara lapor SPT', 'url': 'https://www.youtube.com/watch?v=abcdefghijk'}]
CLASSIC_COMPETITORS = [{'url': COMP_URL, 'title': 'DDG duplikat', 'headers': []},
                       {'url': 'https://ddg.example.com/a', 'title': 'DDG A', 'headers': []},
                       {'url': 'https://ddg.example.com/b', 'title': 'DDG B', 'headers': []},
                       {'url': 'https://ddg.example.com/c', 'title': 'DDG C', 'headers': []}]


class FakeEngine:
    model = 'claude-opus-5-5'

    def __init__(self, result=None, error=None, wait=None):
        self.result = result
        self.error = error
        self.wait = wait
        self.last_error = None if result else 'Riset web Claude gagal; memakai DuckDuckGo/Jina sebagai cadangan.'
        self.calls = []

    def research(self, topic, language='id', **options):
        self.calls.append((topic, language, options))
        if self.wait is not None:
            self.wait.wait(5)
        if self.error:
            raise self.error
        return self.result


def claude_result(**parts):
    result = {'competitors': [], 'official_sources': [], 'news': [], 'wikipedia': None,
              'stats': {'model': 'claude-opus-5-5', 'searches': 4, 'fetches': 3, 'estimated_cost_usd': 0.61}}
    result.update(parts)
    return result


class SEOResearchIntegrationTests(unittest.TestCase):
    PROVIDERS = ('analyze_competitors', 'get_official_sources', 'get_social_insights', 'get_keyword_suggestions',
                 'get_related_questions', 'get_latest_news', 'get_wikipedia_context', 'get_youtube_insights',
                 'get_trend_analysis')

    def run_topic(self, claude, **returns):
        research = SEOResearch(claude=claude)
        return self._run(research, lambda: research.research_topic(TOPIC, 'Pajak', exclude_hosts=['situs.example']),
                         returns)

    def _run(self, research, call, returns):
        defaults = {'analyze_competitors': [{'url': 'https://ddg.example.com/a', 'title': 'DDG', 'headers': []}],
                    'get_official_sources': [{'title': 'Jina', 'url': 'https://www.ojk.go.id/x', 'passages': ['p']}],
                    'get_social_insights': [], 'get_keyword_suggestions': ['saran'],
                    'get_related_questions': ['apa itu spt?'], 'get_latest_news': [{'title': 'DDG news'}],
                    'get_wikipedia_context': 'Konteks klasik', 'get_youtube_insights': [],
                    'get_trend_analysis': {'score': 10, 'status': 'real'}}
        defaults.update(returns)
        mocks = {name: Mock(return_value=defaults[name]) for name in self.PROVIDERS}
        patches = [patch.object(research, name, mock) for name, mock in mocks.items()]
        patches += [patch.object(seo_research, 'DDG_CALL_SPACING_SECONDS', 0),
                    patch.object(seo_research.random, 'uniform', return_value=0)]
        for p in patches:
            p.start()
        try:
            return call(), mocks
        finally:
            for p in patches:
                p.stop()

    def test_claude_parts_replace_classic_providers(self):
        claude = FakeEngine(claude_result(competitors=CLAUDE_COMPETITORS, official_sources=[CLAUDE_OFFICIAL]))
        result, mocks = self.run_topic(claude)
        mocks['analyze_competitors'].assert_not_called()
        mocks['get_official_sources'].assert_not_called()
        mocks['get_social_insights'].assert_called_once()
        mocks['get_keyword_suggestions'].assert_called_once()
        mocks['get_related_questions'].assert_called_once()
        self.assertEqual(result['competitor_outlines'], CLAUDE_COMPETITORS)
        self.assertEqual(result['official_sources'], [CLAUDE_OFFICIAL])
        meta = result['source_metadata']
        self.assertEqual(meta['claude_web']['status'], 'real')
        self.assertEqual(meta['claude_web']['searches'], 4)
        self.assertEqual(meta['claude_web']['estimated_cost_usd'], 0.61)
        self.assertEqual(meta['competitors']['status'], 'real')
        self.assertEqual(meta['competitors']['via'], 'claude_web')
        self.assertEqual(meta['official_sources']['count'], 1)
        topic, language, options = claude.calls[0]
        self.assertEqual((topic, language), (TOPIC, 'id'))
        self.assertEqual(options['exclude_hosts'], frozenset({'situs.example'}))
        self.assertEqual(options['competitor_limit'], 3)
        self.assertFalse(options['want_news'])
        self.assertFalse(options['want_youtube'])
        self.assertEqual(options['question_limit'], 8)
        self.assertNotIn('want_wikipedia', options)

    def test_one_good_competitor_is_topped_up_by_the_classic_scrape(self):
        claude = FakeEngine(claude_result(competitors=[claude_competitor(), THIN_COMPETITOR,
                                                       claude_competitor(SEARCH_ONLY_URL, ())],
                                          official_sources=[CLAUDE_OFFICIAL]))
        result, mocks = self.run_topic(claude, analyze_competitors=CLASSIC_COMPETITORS)
        mocks['analyze_competitors'].assert_called_once()
        mocks['get_official_sources'].assert_not_called()
        # Good Claude page, then classic ones (the duplicate URL dropped); the thin page did not fit.
        self.assertEqual([c['url'] for c in result['competitor_outlines']],
                         [COMP_URL, 'https://ddg.example.com/a', 'https://ddg.example.com/b'])
        self.assertEqual(result['competitor_outlines'][0]['retrieved_via'], 'claude_web')
        meta = result['source_metadata']['competitors']
        self.assertEqual((meta['status'], meta['count'], meta['via'], meta['claude_count'], meta['thin_count']),
                         ('real', 3, 'claude_web+duckduckgo', 1, 1))
        self.assertEqual(result['source_metadata']['claude_web']['competitors_count'], 2)
        self.assertEqual(result['source_metadata']['claude_web']['thin_competitors_count'], 1)

    def test_thin_pages_never_count_but_are_kept_when_nothing_better_exists(self):
        # Two thin pages are not enough to replace the classic scrape...
        claude = FakeEngine(claude_result(competitors=[THIN_COMPETITOR, claude_competitor(COMP2_URL, (COMP2_PASSAGE,))]))
        result, mocks = self.run_topic(claude, analyze_competitors=[])
        mocks['analyze_competitors'].assert_called_once()
        # ...but with DuckDuckGo blocked they are kept, as partial evidence.
        self.assertEqual(len(result['competitor_outlines']), 2)
        self.assertEqual(result['source_metadata']['competitors']['status'], 'partial')
        # Two good pages replace the scrape and the thin one is dropped.
        claude = FakeEngine(claude_result(competitors=CLAUDE_COMPETITORS + [THIN_COMPETITOR]))
        result, mocks = self.run_topic(claude)
        mocks['analyze_competitors'].assert_not_called()
        self.assertEqual(result['competitor_outlines'], CLAUDE_COMPETITORS)

    def test_missing_part_falls_back_to_classic(self):
        claude = FakeEngine(claude_result(competitors=CLAUDE_COMPETITORS))
        result, mocks = self.run_topic(claude)
        mocks['analyze_competitors'].assert_not_called()
        mocks['get_official_sources'].assert_called_once()
        self.assertEqual(mocks['get_official_sources'].call_args.kwargs['exclude_hosts'], frozenset({'situs.example'}))
        self.assertEqual(result['official_sources'][0]['title'], 'Jina')

    def test_failed_claude_falls_back_to_all_classic(self):
        for claude in (FakeEngine(None), FakeEngine(error=RuntimeError('boom'))):
            result, mocks = self.run_topic(claude)
            mocks['analyze_competitors'].assert_called_once()
            mocks['get_official_sources'].assert_called_once()
            self.assertEqual(result['competitor_outlines'][0]['title'], 'DDG')
            meta = result['source_metadata']['claude_web']
            self.assertEqual(meta['status'], 'unavailable')
            self.assertTrue(meta['reason'])

    def test_no_engine_is_classic_only(self):
        result, mocks = self.run_topic(None)
        mocks['analyze_competitors'].assert_called_once()
        mocks['get_official_sources'].assert_called_once()
        self.assertNotIn('claude_web', result['source_metadata'])

    def test_job_timeout_on_the_main_thread_propagates_without_waiting_for_claude(self):
        # RQ raises its timeout in the job's main thread, here while the classic
        # providers run; the Claude worker thread is still busy and is not waited for.
        release = threading.Event()
        self.addCleanup(release.set)
        claude = FakeEngine(claude_result(competitors=CLAUDE_COMPETITORS), wait=release)
        research = SEOResearch(claude=claude)
        started = time.monotonic()
        with patch.object(research, '_run_providers', Mock(side_effect=JobTimeoutException('deadline'))):
            with self.assertRaises(JobTimeoutException):
                research.research_topic(TOPIC)
        self.assertLess(time.monotonic() - started, 2)

    def test_exception_inside_the_claude_thread_means_fallback(self):
        # RQ never raises its timeout inside the worker thread; anything raised
        # there is just a failed Claude call.
        result, mocks = self.run_topic(FakeEngine(error=JobTimeoutException('not from RQ')))
        mocks['analyze_competitors'].assert_called_once()
        self.assertEqual(result['source_metadata']['claude_web']['status'], 'unavailable')

    def test_category_research_with_claude(self):
        claude = FakeEngine(claude_result(competitors=CLAUDE_COMPETITORS, news=[CLAUDE_NEWS],
                                          official_sources=[CLAUDE_OFFICIAL], social=CLAUDE_SOCIAL,
                                          questions=CLAUDE_QUESTIONS, youtube=CLAUDE_VIDEOS))
        research = SEOResearch(claude=claude)
        research.exclude_hosts = ['situs.example']
        with patch.object(research, '_fetch_transcript', side_effect=RuntimeError('IpBlocked')), \
                patch.object(seo_research, 'YouTubeTranscriptApi', object()):
            result, mocks = self._run(research, lambda: research.research_category('Pajak'), {})
        for name in ('analyze_competitors', 'get_latest_news', 'get_official_sources', 'get_social_insights',
                     'get_related_questions', 'get_youtube_insights'):
            mocks[name].assert_not_called()
        for name in ('get_keyword_suggestions', 'get_trend_analysis', 'get_wikipedia_context'):
            mocks[name].assert_called_once()
        self.assertEqual(result['competitor_outlines'], CLAUDE_COMPETITORS)
        self.assertEqual(result['news_insights'], [CLAUDE_NEWS])
        self.assertEqual(result['official_sources'], [CLAUDE_OFFICIAL])
        self.assertEqual(result['social_insights'], CLAUDE_SOCIAL)
        self.assertEqual(result['questions'], CLAUDE_QUESTIONS)
        self.assertEqual(result['evidence_questions'], CLAUDE_QUESTIONS)
        # Wikipedia always comes from the free Wikipedia API.
        self.assertEqual(result['semantic_context'], 'Konteks klasik')
        # The transcript was blocked: the video stays, title-only.
        self.assertEqual(result['youtube_insights'], [{
            'video_id': 'abcdefghijk', 'title': 'Cara lapor SPT', 'url': CLAUDE_VIDEOS[0]['url'],
            'snippets': '', 'transcript_available': False}])
        meta = result['source_metadata']
        self.assertEqual((meta['youtube']['status'], meta['youtube']['via']), ('partial', 'claude_web'))
        self.assertEqual((meta['social']['status'], meta['social']['via']), ('real', 'claude_web'))
        self.assertEqual((meta['related_questions']['status'], meta['related_questions']['via']), ('real', 'claude_web'))
        self.assertEqual(meta['news']['status'], 'real')
        self.assertEqual(meta['claude_web']['status'], 'real')
        options = claude.calls[0][2]
        self.assertTrue(options.get('want_official', True))
        self.assertTrue(options['want_youtube'])
        self.assertNotIn('want_wikipedia', options)
        # Claude-supplied parts score like the classic providers.
        self.assertEqual(result['quality'], SEOResearch.evaluate_quality(
            meta, competitor_count=2, suggestion_count=0, question_count=3))
        self.assertGreaterEqual(result['quality']['score'], 20 + 15 + 8 + 4 + 3)

    def test_category_falls_back_for_parts_claude_missed(self):
        claude = FakeEngine(claude_result(competitors=CLAUDE_COMPETITORS, questions=CLAUDE_QUESTIONS[:2]))
        research = SEOResearch(claude=claude)
        result, mocks = self._run(research, lambda: research.research_category('Pajak'), {})
        mocks['analyze_competitors'].assert_not_called()
        for name in ('get_latest_news', 'get_wikipedia_context', 'get_official_sources', 'get_social_insights',
                     'get_youtube_insights', 'get_related_questions'):
            mocks[name].assert_called_once()
        # Two verified questions are not enough to replace Google Suggest.
        self.assertEqual(result['questions'], ['apa itu spt?'])

    def test_classic_category_research_has_no_official_lookup(self):
        research = SEOResearch()
        result, mocks = self._run(research, lambda: research.research_category('Pajak'), {})
        mocks['get_official_sources'].assert_not_called()
        self.assertEqual(result['official_sources'], [])

    def test_category_top_up_respects_the_category_limit(self):
        claude = FakeEngine(claude_result(competitors=[claude_competitor(), THIN_COMPETITOR]))
        research = SEOResearch(claude=claude)
        result, _ = self._run(research, lambda: research.research_category('Pajak'),
                              {'analyze_competitors': CLASSIC_COMPETITORS})
        self.assertEqual(len(result['competitor_outlines']), 4)
        self.assertEqual(result['competitor_outlines'][0]['retrieved_via'], 'claude_web')

    def test_end_to_end_with_real_engine(self):
        page2 = COMP2_TEXT + COMP_PASSAGE + '\n'
        blocks = research_blocks() + [fetch_result('f9', COMP2_URL, page2, title='Panduan SPT karyawan')]
        data = payload(competitors=[comp(passages=[COMP_PASSAGE, COMP_PASSAGE_2]),
                                    comp(url=COMP2_URL, passages=[COMP2_PASSAGE, COMP_PASSAGE])],
                       official=[{'url': OFFICIAL_URL, 'passages': [OFFICIAL_PASSAGE]}])
        claude = engine(message(blocks + [text(data)]))
        result, mocks = self.run_topic(claude)
        mocks['analyze_competitors'].assert_not_called()
        mocks['get_official_sources'].assert_not_called()
        self.assertEqual([c['url'] for c in result['competitor_outlines']], [COMP_URL, COMP2_URL])
        self.assertEqual(result['official_sources'][0]['passages'], [OFFICIAL_PASSAGE])
        self.assertEqual(result['source_metadata']['claude_web']['model'], 'claude-opus-5-5')
        # The excluded host is passed on to Claude's tools.
        tools = claude.client.messages.stream.call_args.kwargs['tools']
        self.assertEqual(tools[0]['blocked_domains'], ['situs.example'])


if __name__ == '__main__':
    unittest.main()
