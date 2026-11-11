"""Gemini web research (services/gemini_research.py), the engine selection and
Claude-to-Gemini fallback (services/research_engine.py), and the engine-aware
source metadata in SEOResearch. No network: the google-genai client is a fake
whose responses mirror the SDK's candidate / grounding-metadata shapes, and
every HTTP request (grounding redirects, page fetches) goes to a fake web.

Gemini only picks pages: research is driven by the grounding chunks (the
searches it really ran); the reply text is prose and ignored. Passages,
headings, discussion texts and questions come from the pages fetched here.
"""
import sys
import threading
import types
import unittest
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

try:
    import pytrends.request  # noqa: F401
except Exception:  # broken/missing pandas: stub, nothing here uses Trends
    for _name in ('pytrends', 'pytrends.request'):
        sys.modules[_name] = types.ModuleType(_name)
    sys.modules['pytrends.request'].TrendReq = object

# Other test modules replace these with bare stubs; this file needs the real ones.
for _module in ('trending_research', 'seo_research', 'services.claude_research', 'services.gemini_research',
                'services.research_engine'):
    if _module in sys.modules and not getattr(sys.modules[_module], '__file__', None):
        del sys.modules[_module]

import anthropic  # noqa: E402
import httpx2  # noqa: E402
from google import genai  # noqa: E402
from google.genai import types as genai_types  # noqa: E402
from rq.timeouts import JobTimeoutException  # noqa: E402

import seo_research  # noqa: E402
from seo_research import SEOResearch  # noqa: E402
from services import ai_providers, claude_research, gemini_research  # noqa: E402
from services.claude_research import ClaudeWebResearch  # noqa: E402
from services.gemini_research import GeminiWebResearch, html_page_text, page_headings, page_passages  # noqa: E402
from services.research_engine import FallbackWebResearch, research_engine_from_config  # noqa: E402

TOPIC = 'lapor SPT tahunan'
PROSE = 'Berikut halaman yang saya temukan: 1. Cara Lapor SPT Tahunan Online - panduan langkah demi langkah.'
REDIRECT = 'https://vertexaisearch.cloud.google.com/grounding-api-redirect/'
R_COMP, R_OFFICIAL, R_FAKE_OFFICIAL, R_OWN, R_REDDIT, R_NEWS, R_YT = (
    REDIRECT + name for name in ('comp', 'official', 'fake-official', 'own', 'reddit', 'news', 'yt'))

COMP_URL = 'https://blog.example.com/spt'
COMP_PASSAGE = ('SPT Tahunan adalah surat yang digunakan wajib pajak untuk melaporkan penghasilan, harta, '
                'dan kewajiban dalam satu tahun pajak.')
COMP_PASSAGE_2 = ('Wajib pajak orang pribadi harus menyampaikan SPT paling lambat tanggal 31 Maret setiap tahun, '
                  'sedangkan wajib pajak badan paling lambat 30 April.')
COMP_HTML = f"""<html><head><title>Cara Lapor SPT Tahunan Online - Blog Contoh</title></head><body>
<nav>Beranda | Pajak | Kontak</nav>
<article><h1>Cara Lapor SPT Tahunan Online</h1>
<h2>Syarat Lapor <b>SPT Tahunan</b></h2>
<p>{COMP_PASSAGE} Pelaporan dilakukan secara daring melalui <a href="/djp">DJP Online</a>.</p>
<h2>Batas Waktu</h2>
<p>{COMP_PASSAGE_2}</p>
<h2>FAQ</h2><h3>Kapan batas lapor SPT tahunan?</h3><p>Paling lambat 31 Maret.</p>
</article><footer>Hak cipta Blog Contoh</footer></body></html>"""
COMP_TITLE = 'Cara Lapor SPT Tahunan Online - Blog Contoh'
COMP_LINE_1 = COMP_PASSAGE + ' Pelaporan dilakukan secara daring melalui DJP Online.'

OFFICIAL_URL = 'https://www.pajak.go.id/id/spt-tahunan'
FAKE_OFFICIAL_URL = 'https://pajak-go-id.example.com/spt'
OFFICIAL_PASSAGE = ('Batas waktu penyampaian SPT Tahunan PPh Orang Pribadi adalah paling lambat tiga bulan '
                    'setelah akhir tahun pajak.')
OFFICIAL_HTML = f"""<html><head><title>SPT Tahunan PPh Orang Pribadi | DJP</title></head><body>
<form id="aspnetForm"><div class="content"><h1>SPT Tahunan PPh Orang Pribadi</h1>
<p>{OFFICIAL_PASSAGE} Keterlambatan dikenai sanksi denda sebesar Rp100.000.</p></div></form></body></html>"""
OFFICIAL_TITLE = 'SPT Tahunan PPh Orang Pribadi | DJP'
OFFICIAL_LINE = OFFICIAL_PASSAGE + ' Keterlambatan dikenai sanksi denda sebesar Rp100.000.'

OWN_URL = 'https://www.situs.example/spt'
OWN_HTML = COMP_HTML.replace('Blog Contoh', 'Situs Sendiri')
REDDIT_URL = 'https://www.reddit.com/r/indonesia/comments/abc/lapor_spt/'
REDDIT_QUESTION = 'Bagaimana cara lapor SPT tahunan kalau lupa EFIN?'
REDDIT_TITLE = f'{REDDIT_QUESTION} : r/indonesia'
REDDIT_HTML = f"""<html><head><title>{REDDIT_TITLE}</title></head><body>
<h1>{REDDIT_QUESTION}</h1><p>Saya sudah coba reset lewat email tapi belum berhasil juga.</p></body></html>"""
HELP_URL = 'https://www.reddit.com/help/spt-tahunan'
NEWS_URL = 'https://www.kompas.com/money/read/2026/spt-tahunan'
NEWS_TITLE = 'Batas Lapor SPT Tahunan Diperpanjang - Kompas.com'
OLD_NEWS_URL = 'https://www.kompas.com/money/read/2020/spt-tahunan'
YT_URL = 'https://www.youtube.com/watch?v=abcdefghijk'
YT_HTML = '<html><head><title>Cara Lapor SPT Tahunan - YouTube</title></head><body></body></html>'


def news_html(published, headline=NEWS_TITLE):
    return (f'<html><head><title>{headline}</title>'
            f'<meta property="article:published_time" content="{published}T08:00:00+07:00"></head>'
            f'<body><h1>{headline}</h1><p>Isi berita tentang SPT tahunan.</p></body></html>')


RECENT = (date.today() - timedelta(days=20)).isoformat()


class FakeResponse:
    def __init__(self, status=200, body='', content_type='text/html; charset=utf-8', location=None):
        self.status_code = status
        self.headers = {'Content-Type': content_type}
        if location:
            self.headers['Location'] = location
        self.body = body.encode('utf-8') if isinstance(body, str) else body
        self.closed = False

    def iter_content(self, chunk_size=1):
        for start in range(0, len(self.body), chunk_size):
            yield self.body[start:start + chunk_size]

    def close(self):
        self.closed = True


def redirect_to(location, status=302):
    return FakeResponse(status, '', location=location)


class FakeWeb:
    """requests.request stand-in: routes by (method, url), else by url; 404 otherwise."""

    def __init__(self, routes):
        self.routes = dict(routes)
        self.calls = []
        self.lock = threading.Lock()

    def request(self, method, url, **kwargs):
        with self.lock:
            self.calls.append((method, url, kwargs))
        route = self.routes.get((method, url), self.routes.get(url))
        if route is None:
            return FakeResponse(404, 'Not found')
        if isinstance(route, BaseException):
            raise route
        return route

    def urls(self, method=None):
        return [url for m, url, _ in self.calls if method is None or m == method]


def default_routes():
    return {
        ('HEAD', R_COMP): redirect_to(COMP_URL),
        ('HEAD', R_OFFICIAL): redirect_to(OFFICIAL_URL),
        ('HEAD', R_FAKE_OFFICIAL): redirect_to(FAKE_OFFICIAL_URL),
        ('HEAD', R_OWN): redirect_to(OWN_URL),
        ('HEAD', R_REDDIT): redirect_to(REDDIT_URL),
        ('HEAD', R_NEWS): redirect_to(NEWS_URL),
        ('HEAD', R_YT): redirect_to(YT_URL),
        ('GET', COMP_URL): FakeResponse(body=COMP_HTML),
        ('GET', OFFICIAL_URL): FakeResponse(body=OFFICIAL_HTML),
        ('GET', FAKE_OFFICIAL_URL): FakeResponse(body=OFFICIAL_HTML),
        ('GET', OWN_URL): FakeResponse(body=OWN_HTML),
        ('GET', REDDIT_URL): FakeResponse(body=REDDIT_HTML),
        ('GET', NEWS_URL): FakeResponse(body=news_html(RECENT)),
        ('GET', YT_URL): FakeResponse(body=YT_HTML),
    }


# Grounding titles are mostly bare hosts, as the Gemini API returns them.
DEFAULT_CHUNKS = ((R_COMP, 'blog.example.com'), (R_OFFICIAL, 'pajak.go.id'), (R_FAKE_OFFICIAL, 'example.com'),
                  (R_OWN, 'situs.example'), (R_REDDIT, 'reddit.com'), (R_NEWS, 'kompas.com'), (R_YT, 'youtube.com'))


def chunks(*uris):
    titles = dict(DEFAULT_CHUNKS)
    return tuple((uri, titles.get(uri, 'example.com')) for uri in uris)


def gemini_response(reply=PROSE, chunks=DEFAULT_CHUNKS, queries=(TOPIC, f'{TOPIC} site:go.id'),
                    finish=genai_types.FinishReason.STOP):
    candidate = SimpleNamespace(
        content=SimpleNamespace(parts=[SimpleNamespace(text='Merencanakan pencarian...', thought=True),
                                       SimpleNamespace(text=reply, thought=None)]),
        finish_reason=finish,
        grounding_metadata=SimpleNamespace(
            grounding_chunks=[SimpleNamespace(web=SimpleNamespace(uri=uri, title=title, domain=None))
                              for uri, title in chunks],
            web_search_queries=list(queries)))
    usage = SimpleNamespace(prompt_token_count=1200, candidates_token_count=300, thoughts_token_count=500,
                            tool_use_prompt_token_count=2000)
    return SimpleNamespace(candidates=[candidate], usage_metadata=usage, prompt_feedback=None)


def fake_genai_client(*outcomes):
    return SimpleNamespace(models=SimpleNamespace(generate_content=Mock(side_effect=list(outcomes))))


def engine(*outcomes, model='gemini-3.5-flash'):
    return GeminiWebResearch('test-key', model, client=fake_genai_client(*outcomes))


def genai_error(code):
    cls = genai.errors.ClientError if code < 500 else genai.errors.ServerError
    return cls(code, {'error': {'code': code, 'message': 'x', 'status': 'X'}})


class FakeRedis:
    """The two Redis calls the pauses use."""

    def __init__(self):
        self.data, self.ttl = {}, {}

    def set(self, key, value, ex=None, nx=False):
        if nx and key in self.data:
            return None
        self.data[key], self.ttl[key] = value, ex
        return True

    def exists(self, key):
        return int(key in self.data)


class WebTestCase(unittest.TestCase):
    """Patches the network: requests.request goes to FakeWeb, every host is
    public, Jina Reader returns nothing and retries do not sleep."""

    def setUp(self):
        self.web = FakeWeb(default_routes())
        self.reader = Mock(return_value=None)
        for patcher in (
                patch.object(gemini_research.requests, 'request', self.web.request),
                patch.object(gemini_research, '_is_public_host', return_value=True),
                patch.object(GeminiWebResearch, '_fetch_via_reader', staticmethod(self.reader)),
                patch.object(gemini_research, 'RETRY_DELAY_SECONDS', 0)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def add_page(self, name, url, html=None, response=None):
        """A search result: the grounding redirect REDIRECT+name to url, serving html."""
        uri = REDIRECT + name
        self.web.routes[('HEAD', uri)] = redirect_to(url)
        if response is not None or html is not None:
            self.web.routes[('GET', url)] = response or FakeResponse(body=html)
        return uri

    def run_research(self, chunks=DEFAULT_CHUNKS, language='id', exclude_hosts=('https://www.situs.example/',),
                     topic=TOPIC, finish=genai_types.FinishReason.STOP, model='gemini-3.5-flash', **options):
        research = engine(gemini_response(chunks=chunks, finish=finish), model=model)
        options.setdefault('want_youtube', True)
        result = research.research(topic, language, category='Pajak', exclude_hosts=list(exclude_hosts),
                                   **options)
        return research, result


class RequestShapeTests(WebTestCase):
    def test_one_grounded_plain_language_request(self):
        research, _ = self.run_research()
        call = research.client.models.generate_content
        self.assertEqual(call.call_count, 1)
        kwargs = call.call_args.kwargs
        self.assertEqual(kwargs['model'], 'gemini-3.5-flash')
        config = kwargs['config']
        self.assertEqual(len(config.tools), 1)
        self.assertIsNotNone(config.tools[0].google_search)
        self.assertIsNone(config.response_schema)
        self.assertIsNone(config.response_mime_type)
        # Gemini blocks replies that recite web text, and skips searching when
        # asked for JSON: the request asks for pages in plain language.
        self.assertNotIn('JSON', config.system_instruction)
        self.assertIn('Never quote or copy page text', config.system_instruction)
        self.assertEqual(config.thinking_config.thinking_level, genai_types.ThinkingLevel.LOW)
        self.assertLessEqual(config.http_options.timeout, gemini_research.REQUEST_TIMEOUT_SECONDS * 1000)
        prompt = kwargs['contents']
        self.assertNotIn('JSON', prompt)
        self.assertIn(f'Search Google for pages about "{TOPIC}" (category: "Pajak")', prompt)
        self.assertIn('readers in Indonesia', prompt)
        self.assertIn('site:go.id', prompt)
        self.assertIn('only hosts ending in .go.id', prompt)
        self.assertIn('situs.example', prompt)
        self.assertIn('Kaskus', prompt)

    def test_older_models_get_no_thinking_level(self):
        research, _ = self.run_research(model='gemini-2.5-flash')
        self.assertIsNone(research.client.models.generate_content.call_args.kwargs['config'].thinking_config)

    def test_english_asks_for_gov_hosts(self):
        research, _ = self.run_research(language='en')
        prompt = research.client.models.generate_content.call_args.kwargs['contents']
        self.assertIn('site:.gov', prompt)
        self.assertIn('only hosts ending in .gov', prompt)
        self.assertIn('United States', prompt)

    def test_unrequested_parts_are_left_out(self):
        research, result = self.run_research(want_news=False, want_youtube=False, want_social=False)
        prompt = research.client.models.generate_content.call_args.kwargs['contents']
        self.assertNotIn('news articles', prompt)
        self.assertNotIn('YouTube', prompt)
        self.assertNotIn('discussions', prompt)
        # The search found news, a video and a thread; they are not returned.
        self.assertEqual((result['news'], result['youtube'], result['social']), ([], [], []))


class RedirectTests(WebTestCase):
    def test_grounding_redirects_are_resolved_to_the_real_urls(self):
        _, result = self.run_research()
        # The .go.id look-alike is an ordinary competitor, never an official source.
        self.assertEqual([c['url'] for c in result['competitors']], [COMP_URL, FAKE_OFFICIAL_URL])
        heads = [(url, kwargs['allow_redirects']) for method, url, kwargs in self.web.calls if method == 'HEAD']
        self.assertIn((R_COMP, False), heads)
        # Only the redirect host is asked for a Location; pages are fetched once, by GET.
        self.assertEqual({url for url, _ in heads}, {uri for uri, _ in DEFAULT_CHUNKS})
        self.assertEqual(self.web.urls('GET').count(COMP_URL), 1)
        self.assertFalse(any(url.startswith(REDIRECT) for url in self.web.urls('GET')))

    def test_each_redirect_is_resolved_once_per_call(self):
        research = engine(gemini_response(chunks=chunks(R_COMP, R_COMP, R_OFFICIAL)),
                          gemini_response(chunks=chunks(R_COMP)))
        research.research(TOPIC)
        self.assertEqual(self.web.urls('HEAD').count(R_COMP), 1)
        self.assertEqual(self.web.urls('HEAD').count(R_OFFICIAL), 1)
        # A new call resolves again: the memo only lives for one call.
        research.research(TOPIC)
        self.assertEqual(self.web.urls('HEAD').count(R_COMP), 2)

    def test_head_not_allowed_falls_back_to_get(self):
        self.web.routes[('HEAD', R_COMP)] = FakeResponse(405, '')
        self.web.routes[('GET', R_COMP)] = redirect_to(COMP_URL)
        _, result = self.run_research(chunks(R_COMP))
        self.assertEqual([c['url'] for c in result['competitors']], [COMP_URL])

    def test_redirect_hops_stay_on_the_redirect_host(self):
        second = REDIRECT + 'comp-2'
        self.web.routes[('HEAD', R_COMP)] = redirect_to(second)
        self.web.routes[('HEAD', second)] = redirect_to(COMP_URL)
        research = engine()
        self.assertEqual(research._resolve_redirect(R_COMP, gemini_research._now() + 30), COMP_URL)
        self.assertNotIn(('HEAD', COMP_URL), [(m, u) for m, u, _ in self.web.calls])

    def test_unresolvable_redirect_is_dropped(self):
        self.web.routes[('HEAD', R_COMP)] = FakeResponse(404, '')
        self.web.routes[('GET', R_COMP)] = FakeResponse(404, '')
        _, result = self.run_research()
        self.assertEqual([c['url'] for c in result['competitors']], [FAKE_OFFICIAL_URL])
        self.assertNotIn(COMP_URL, self.web.urls('GET'))
        self.assertEqual(result['stats']['redirects_resolved'], len(DEFAULT_CHUNKS) - 1)

    def test_page_redirects_to_a_private_host_are_not_followed(self):
        internal = 'https://intranet.example.com/spt'
        self.web.routes[('GET', COMP_URL)] = redirect_to(internal)
        self.web.routes[('GET', internal)] = FakeResponse(body=COMP_HTML)
        with patch.object(gemini_research, '_is_public_host', side_effect=lambda host: 'intranet' not in host):
            _, result = self.run_research(chunks(R_COMP))
        self.assertNotIn(internal, self.web.urls('GET'))
        self.assertEqual(result['competitors'], [])


class ClassificationTests(unittest.TestCase):
    KASKUS_URL = 'https://www.kaskus.co.id/thread/123/lapor-spt'
    GOV_URL = 'https://www.irs.gov/filing'

    def test_searched_pages_are_sorted_into_parts_by_url(self):
        data = GeminiWebResearch._data_from_search(
            [COMP_URL, OFFICIAL_URL, FAKE_OFFICIAL_URL, REDDIT_URL, self.KASKUS_URL, NEWS_URL, YT_URL, OWN_URL,
             None, COMP_URL + '/'],
            'id', frozenset({'situs.example'}))
        urls = {part: [item['url'] for item in items] for part, items in data.items()}
        self.assertEqual(urls, {
            'competitors': [COMP_URL, FAKE_OFFICIAL_URL],  # duplicate and own-site URLs dropped
            'official': [OFFICIAL_URL],
            'social': [REDDIT_URL, self.KASKUS_URL],
            'news': [NEWS_URL],
            'youtube': [YT_URL],
            'questions': [],
        })

    def test_official_hosts_follow_the_language(self):
        data = GeminiWebResearch._data_from_search([OFFICIAL_URL, self.GOV_URL], 'en', frozenset())
        self.assertEqual([item['url'] for item in data['official']], [self.GOV_URL])
        self.assertEqual([item['url'] for item in data['competitors']], [OFFICIAL_URL])


JINA_TITLE = 'Title: Cara lapor SPT tahunan online lengkap untuk karyawan dan wajib pajak orang pribadi 2026'


class PageExtractionTests(WebTestCase):
    """Gemini only picks pages: passages, headings and questions come from the fetched page."""

    def test_page_passages(self):
        figures = 'Denda telat lapor SPT tahunan orang pribadi adalah Rp100.000 dan untuk badan Rp1.000.000 per SPT.'
        plain = 'Cara lapor SPT tahunan secara online bisa dilakukan sendiri dari rumah tanpa datang ke kantor pajak.'
        text = '\n'.join([
            JINA_TITLE,
            'URL Source: https://blog.example.com/spt',
            'Markdown Content:',
            '## Cara lapor SPT tahunan online lengkap untuk karyawan dan wajib pajak orang pribadi',
            plain,
            'Lapor SPT tahunan.',  # too short
            'Baca juga: cara lapor SPT tahunan untuk pekerja lepas dan pemilik usaha kecil di seluruh Indonesia',
            '[Panduan lapor SPT tahunan online untuk karyawan swasta dan aparatur sipil negara](https://x.example)',
            '- [Lapor SPT tahunan lewat aplikasi DJP Online untuk karyawan swasta](https://y.example/a)',
            'Resep nasi goreng kampung yang gurih dan mudah dibuat di rumah untuk keluarga tercinta setiap hari.',
            figures,
        ])
        self.assertEqual(page_passages(text, TOPIC), [plain, figures])
        # Lines with figures rank higher; the result stays in page order.
        self.assertEqual(page_passages(text, TOPIC, limit=1), [figures])
        self.assertEqual(page_passages('', TOPIC), [])

    def test_page_headings(self):
        text = '# Judul\n## Syarat\nisi\n### Langkah\n#### Detail\n## Syarat\n## Batas Waktu'
        self.assertEqual(page_headings(text), ['Syarat', 'Langkah', 'Batas Waktu'])
        self.assertEqual(page_headings(text, limit=2), ['Syarat', 'Langkah'])

    def test_passages_and_headings_come_from_the_fetched_page(self):
        _, result = self.run_research(chunks(R_COMP))
        [competitor] = result['competitors']
        self.assertEqual(competitor['key_passages'], [COMP_LINE_1, COMP_PASSAGE_2])
        self.assertEqual(competitor['headers'], ['Syarat Lapor SPT Tahunan', 'Batas Waktu', 'FAQ',
                                                 'Kapan batas lapor SPT tahunan?'])
        self.assertEqual(competitor['title'], COMP_TITLE)
        self.assertEqual(competitor['retrieved_via'], 'gemini_web')

    def test_reply_text_is_ignored(self):
        research = engine(gemini_response(reply=f'"{COMP_PASSAGE_2} Denda Rp5 juta." {COMP_URL}', chunks=()))
        self.assertIsNone(research.research(TOPIC))
        self.assertEqual(self.web.calls, [])

    def test_page_without_on_topic_text_gives_no_competitor(self):
        self.web.routes[('GET', COMP_URL)] = FakeResponse(
            body='<html><head><title>Resep Nasi Goreng</title></head><body><p>Resep nasi goreng kampung yang '
                 'gurih dan mudah dibuat di rumah untuk keluarga tercinta setiap hari.</p></body></html>')
        _, result = self.run_research(chunks(R_COMP))
        self.assertEqual(result['competitors'], [])

    def test_jina_reader_text_without_its_header_lines(self):
        self.web.routes[('GET', COMP_URL)] = FakeResponse(body='<html><body><div id="app"></div></body></html>')
        self.reader.return_value = (f'{JINA_TITLE}\nURL Source: {COMP_URL}\nPublished Time: {RECENT}T08:00:00Z\n'
                                    f'Markdown Content:\n# Cara Lapor SPT\n\n{COMP_PASSAGE}\n')
        _, result = self.run_research(chunks(R_COMP))
        [competitor] = result['competitors']
        self.assertEqual(competitor['key_passages'], [COMP_PASSAGE])
        self.assertEqual(competitor['title'], JINA_TITLE.removeprefix('Title: '))
        self.assertEqual(competitor['published_hint'], RECENT)

    def test_soft_404_page_is_dropped(self):
        self.web.routes[('GET', COMP_URL)] = FakeResponse(
            body=COMP_HTML.replace(COMP_TITLE, 'Halaman Tidak Ditemukan - Blog Contoh'))
        _, result = self.run_research(chunks(R_COMP))
        self.assertEqual(result['competitors'], [])
        self.assertEqual(result['search_titles'], [])

    def test_page_that_cannot_be_fetched_gives_no_competitor(self):
        self.web.routes[('GET', COMP_URL)] = FakeResponse(403, 'Forbidden')
        _, result = self.run_research(chunks(R_COMP))
        self.assertEqual(result['competitors'], [])
        self.reader.assert_called()  # Jina Reader was tried for the blocked page

    def test_pdf_is_not_read(self):
        self.web.routes[('GET', COMP_URL)] = FakeResponse(body=b'%PDF-1.7', content_type='application/pdf')
        _, result = self.run_research(chunks(R_COMP))
        self.assertEqual(result['competitors'], [])


class OfficialAndOwnHostTests(WebTestCase):
    def test_only_official_hosts_count(self):
        _, result = self.run_research()
        self.assertEqual(result['official_sources'], [
            {'title': OFFICIAL_TITLE, 'url': OFFICIAL_URL, 'passages': [OFFICIAL_LINE]}])

    def test_official_redirect_to_another_host_is_judged_by_the_host_that_served_it(self):
        self.web.routes[('GET', OFFICIAL_URL)] = redirect_to(FAKE_OFFICIAL_URL)
        _, result = self.run_research(chunks(R_OFFICIAL))
        self.assertEqual(result['official_sources'], [])

    def test_english_official_needs_gov(self):
        gov = 'https://www.irs.gov/filing'
        passage = 'Most people must file their federal income tax return by April 15 of each calendar year.'
        uri = self.add_page('irs', gov, f'<html><head><title>Filing | IRS</title></head><body><p>{passage}</p>'
                                        '</body></html>')
        _, result = self.run_research(chunks(uri, R_OFFICIAL), language='en', topic='federal income tax return')
        self.assertEqual(result['official_sources'], [{'title': 'Filing | IRS', 'url': gov, 'passages': [passage]}])

    def test_own_hosts_are_never_fetched_or_used(self):
        _, result = self.run_research()
        self.assertNotIn(OWN_URL, self.web.urls('GET'))
        found = [c['url'] for c in result['competitors']] + [s['url'] for s in result['official_sources']]
        self.assertFalse(any('situs.example' in url for url in found))
        self.assertNotIn('Cara Lapor SPT Tahunan Online - Situs Sendiri', result['search_titles'])

    def test_redirect_onto_an_own_host_is_rejected(self):
        self.web.routes[('GET', COMP_URL)] = redirect_to(OWN_URL)
        _, result = self.run_research(chunks(R_COMP))
        self.assertEqual(result['competitors'], [])
        self.assertEqual(result['questions'], [])

    def test_spam_on_a_government_page_is_rejected(self):
        spam = OFFICIAL_HTML.replace('</p>', ' Daftar slot gacor maxwin hari ini.</p>')
        self.web.routes[('GET', OFFICIAL_URL)] = FakeResponse(body=spam)
        _, result = self.run_research(chunks(R_OFFICIAL))
        self.assertEqual(result['official_sources'], [])


FAQ_URL = 'https://panduan.example.com/spt'
FAQ_HTML = """<html><head><title>Panduan SPT Tahunan Karyawan</title></head><body>
<p>Panduan lapor SPT tahunan ini membahas formulir 1770 S dan 1770 SS untuk karyawan dengan satu pemberi kerja.</p>
<h2>Pertanyaan yang Sering Diajukan</h2>
<h3>1. Apakah SPT tahunan wajib dilaporkan setiap tahun?</h3><p>Ya.</p>
<h3>Bagaimana pengalaman Anda lapor SPT tahunan?</h3><p>Survei.</p>
<h3>Berapa harga laptop terbaik tahun ini?</h3><p>Lain topik.</p>
</body></html>"""


class OtherPartsTests(WebTestCase):
    def test_social_text_is_the_on_topic_thread_title(self):
        off_topic = self.add_page('reddit-laptop', 'https://www.reddit.com/r/indonesia/comments/def/laptop/',
                                  '<html><head><title>Rekomendasi laptop murah untuk kuliah : r/indonesia</title>'
                                  '</head><body><p>Budget lima juta.</p></body></html>')
        help_page = self.add_page('reddit-help', HELP_URL, REDDIT_HTML)
        _, result = self.run_research(chunks(R_REDDIT, off_topic, help_page, R_COMP))
        self.assertEqual(result['social'], [{'text': REDDIT_TITLE, 'url': REDDIT_URL, 'provider': 'reddit'}])

    def test_questions_come_from_page_headings_ranked_and_filtered(self):
        faq = self.add_page('faq', FAQ_URL, FAQ_HTML)
        _, result = self.run_research(chunks(R_COMP, faq, R_REDDIT))
        # The forum question first, then FAQ entries (numbering stripped); the
        # survey prompt and the off-topic question are dropped.
        self.assertEqual(result['questions'], [REDDIT_QUESTION, 'Kapan batas lapor SPT tahunan?',
                                               'Apakah SPT tahunan wajib dilaporkan setiap tahun?'])

    def test_news_needs_a_recent_date_from_the_page(self):
        old = self.add_page('news-old', OLD_NEWS_URL, news_html('2020-03-01', 'SPT Tahunan 2020 - Kompas.com'))
        undated = self.add_page('news-undated', 'https://www.kompas.com/money/read/undated',
                                '<html><head><title>SPT - Kompas.com</title></head><body><p>Tanpa tanggal.</p>'
                                '</body></html>')
        _, result = self.run_research(chunks(R_NEWS, old, undated))
        self.assertEqual(result['news'], [{'title': NEWS_TITLE, 'source': 'Kompas.com', 'url': NEWS_URL,
                                           'published_at': RECENT}])

    def test_youtube_videos(self):
        channel = self.add_page('yt-channel', 'https://www.youtube.com/@pajakkita', YT_HTML)
        _, result = self.run_research(chunks(channel, R_YT, R_COMP))
        self.assertEqual(result['youtube'], [{'video_id': 'abcdefghijk', 'title': 'Cara Lapor SPT Tahunan',
                                              'url': YT_URL}])

    def test_search_titles_come_from_grounded_pages(self):
        # A grounded page that could not be fetched still has its grounding title.
        unfetched = self.add_page('unfetched', 'https://lain.example.com/spt')
        _, result = self.run_research(DEFAULT_CHUNKS + ((unfetched, 'Panduan Lapor SPT Tahunan Lengkap'),))
        self.assertEqual(result['search_titles'], [COMP_TITLE, OFFICIAL_TITLE, REDDIT_TITLE, NEWS_TITLE,
                                                   'Cara Lapor SPT Tahunan - YouTube',
                                                   'Panduan Lapor SPT Tahunan Lengkap'])

    def test_stats_report_tokens_and_an_unknown_cost(self):
        _, result = self.run_research()
        stats = result['stats']
        self.assertEqual(stats['model'], 'gemini-3.5-flash')
        self.assertEqual(stats['searches'], 2)
        self.assertEqual(stats['grounding_chunks'], len(DEFAULT_CHUNKS))
        self.assertEqual(stats['redirects_resolved'], len(DEFAULT_CHUNKS))
        self.assertEqual(stats['fetches'], len(DEFAULT_CHUNKS) - 1)  # never the own site
        self.assertEqual((stats['input_tokens'], stats['output_tokens']), (3200, 800))
        self.assertIsNone(stats['estimated_cost_usd'])


class FailureTests(WebTestCase):
    def test_no_grounding_chunks_returns_none(self):
        research = engine(gemini_response(chunks=()))
        self.assertIsNone(research.research(TOPIC))
        self.assertEqual(research.last_error, gemini_research.FAILURE_REASON)
        self.assertEqual(self.web.calls, [])

    def test_invalid_key_returns_none_with_an_indonesian_reason(self):
        research = engine(genai_error(401))
        self.assertIsNone(research.research(TOPIC))
        self.assertIn('API key Gemini tidak valid', research.last_error)
        self.assertIn('cadangan', research.last_error)
        self.assertEqual(research.client.models.generate_content.call_count, 1)  # not retried

    def test_client_error_is_not_retried(self):
        research = engine(genai_error(400), gemini_response())
        self.assertIsNone(research.research(TOPIC))
        self.assertEqual(research.client.models.generate_content.call_count, 1)

    def test_server_error_is_retried_once(self):
        research = engine(genai_error(503), gemini_response(chunks=chunks(R_COMP)))
        self.assertEqual(len(research.research(TOPIC)['competitors']), 1)
        research = engine(genai_error(503), genai_error(503))
        self.assertIsNone(research.research(TOPIC))
        self.assertEqual(research.client.models.generate_content.call_count, 2)
        self.assertIn('Gemini', research.last_error)

    def test_blocked_or_truncated_replies_return_none(self):
        for response in (gemini_response(finish=genai_types.FinishReason.RECITATION),
                         gemini_response(finish=genai_types.FinishReason.SAFETY),
                         gemini_response(finish=genai_types.FinishReason.MAX_TOKENS),
                         SimpleNamespace(candidates=[], usage_metadata=None, prompt_feedback='BLOCKED')):
            research = engine(response)
            self.assertIsNone(research.research(TOPIC))
            self.assertEqual(research.last_error, gemini_research.FAILURE_REASON)
        self.assertEqual(self.web.calls, [])  # nothing resolved or fetched

    def test_network_errors_while_fetching_do_not_raise(self):
        self.web.routes[('HEAD', R_REDDIT)] = gemini_research.requests.ConnectionError('down')
        self.web.routes[('GET', COMP_URL)] = gemini_research.requests.Timeout('slow')
        _, result = self.run_research()
        self.assertEqual([c['url'] for c in result['competitors']], [FAKE_OFFICIAL_URL])
        self.assertEqual(result['social'], [])
        self.assertEqual(len(result['official_sources']), 1)

    def test_no_time_left_means_no_request(self):
        research = engine(gemini_response())
        times = iter([0, 1000, 1000, 1000])
        with patch.object(gemini_research, '_now', side_effect=lambda: next(times, 1000)):
            self.assertIsNone(research.research(TOPIC))
        research.client.models.generate_content.assert_not_called()
        self.assertEqual(research.last_error, gemini_research.FAILURE_REASON)

    def test_work_stops_at_the_deadline(self):
        release = threading.Event()

        def slow(method, url, **kwargs):
            release.wait(2)
            return self.web.request(method, url, **kwargs)

        research = engine(gemini_response())
        with patch.object(gemini_research.requests, 'request', side_effect=slow), \
                patch.object(gemini_research, 'wait', side_effect=lambda futures, timeout: (set(), set(futures))):
            result = research.research(TOPIC)
        release.set()
        # Nothing finished in time: nothing resolved, fetched or verified.
        self.assertEqual((result['competitors'], result['official_sources'], result['search_titles']), ([], [], []))

    def test_job_timeout_propagates(self):
        with self.assertRaises(JobTimeoutException):
            engine(JobTimeoutException('deadline')).research(TOPIC)


class HtmlTextTests(unittest.TestCase):
    def test_blocks_become_lines_and_headings_markdown(self):
        text, title, published = html_page_text(COMP_HTML.encode('utf-8'))
        self.assertEqual(title, COMP_TITLE)
        self.assertIsNone(published)
        self.assertIn('# Cara Lapor SPT Tahunan Online\n## Syarat Lapor SPT Tahunan\n', text)
        self.assertIn(COMP_LINE_1, text)
        self.assertNotIn('Beranda', text)  # navigation
        self.assertNotIn('Hak cipta', text)  # footer

    def test_published_date_from_meta_json_ld_or_time(self):
        self.assertEqual(html_page_text(news_html('2026-09-20'))[2], '2026-09-20')
        ld = ('<html><head><script type="application/ld+json">{"@type": "NewsArticle", '
              '"datePublished": "2026-08-01T09:00:00Z"}</script></head><body><p>x</p></body></html>')
        self.assertEqual(html_page_text(ld)[2], '2026-08-01')
        self.assertEqual(html_page_text('<p><time datetime="2026-07-02">2 Juli</time></p>')[2], '2026-07-02')


class FactoryTests(unittest.TestCase):
    def test_key_and_model_from_config(self):
        research = gemini_research.from_config({'gemini_api_key': 'g', 'gemini_model': 'gemini-3.5-pro'})
        self.assertIsInstance(research, GeminiWebResearch)
        self.assertEqual(research.model, 'gemini-3.5-pro')
        self.assertEqual(gemini_research.from_config({'gemini_api_key': 'g'}).model, 'gemini-3.5-flash')

    def test_no_key_or_kill_switch_means_none(self):
        self.assertIsNone(gemini_research.from_config({'anthropic_api_key': 'a'}))
        self.assertIsNone(gemini_research.from_config(None))
        with patch.object(gemini_research, 'GEMINI_WEB_RESEARCH_ENABLED', False):
            self.assertIsNone(gemini_research.from_config({'gemini_api_key': 'g'}))


# ---------------------------------------------------------------------------
# Engine selection and the Claude -> Gemini fallback
# ---------------------------------------------------------------------------

REQUEST = httpx2.Request('POST', 'https://api.example.com/v1/messages')
BOTH = {'anthropic_api_key': 'bad-anthropic-key', 'gemini_api_key': 'g', 'gemini_model': 'gemini-3.5-flash'}


def claude_auth_error():
    return anthropic.AuthenticationError(
        'invalid x-api-key', response=httpx2.Response(401, request=REQUEST),
        body={'type': 'error', 'error': {'type': 'authentication_error', 'message': 'invalid x-api-key'}})


def failing_claude(error):
    stream = Mock(side_effect=error)
    client = SimpleNamespace(messages=SimpleNamespace(stream=stream), beta=SimpleNamespace(
        messages=SimpleNamespace(stream=stream)))
    return ClaudeWebResearch('bad-anthropic-key', 'claude-opus-5-5', client=client)


class EngineSelectionTests(WebTestCase):
    def setUp(self):
        super().setUp()
        self.redis = FakeRedis()
        patcher = patch.object(ai_providers, '_pause_store', return_value=self.redis)
        patcher.start()
        self.addCleanup(patcher.stop)
        for patcher in (patch.object(claude_research, 'RETRY_DELAY_SECONDS', 0),
                        # Building a real google-genai client is slow and not under test here.
                        patch.object(gemini_research.genai, 'Client')):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_engine_per_configured_keys(self):
        self.assertIsInstance(research_engine_from_config({'anthropic_api_key': 'a'}), ClaudeWebResearch)
        self.assertIsInstance(research_engine_from_config({'gemini_api_key': 'g'}), GeminiWebResearch)
        both = research_engine_from_config(BOTH)
        self.assertIsInstance(both, FallbackWebResearch)
        self.assertIsInstance(both.primary, ClaudeWebResearch)
        self.assertIsInstance(both.fallback, GeminiWebResearch)
        self.assertIsNone(research_engine_from_config({'openai_api_key': 'o'}))
        self.assertIsNone(research_engine_from_config(None))

    def test_claude_disabled_or_paused_means_gemini(self):
        with patch.object(claude_research, 'CLAUDE_WEB_RESEARCH_ENABLED', False):
            self.assertIsInstance(research_engine_from_config(BOTH), GeminiWebResearch)
        ai_providers.pause_claude_usage()
        self.assertIsInstance(research_engine_from_config(BOTH), GeminiWebResearch)
        self.assertIsNone(research_engine_from_config({'anthropic_api_key': 'a'}))

    def test_gemini_kill_switch(self):
        with patch.object(gemini_research, 'GEMINI_WEB_RESEARCH_ENABLED', False):
            self.assertIsInstance(research_engine_from_config(BOTH), ClaudeWebResearch)
            self.assertIsNone(research_engine_from_config({'gemini_api_key': 'g'}))

    def test_claude_401_falls_back_to_gemini_and_pauses_that_key(self):
        claude = failing_claude(claude_auth_error())
        gemini = engine(gemini_response(chunks=chunks(R_OFFICIAL)))
        wrapper = FallbackWebResearch(claude, gemini)
        result = wrapper.research(TOPIC, 'id', exclude_hosts=['situs.example'])
        self.assertEqual([s['url'] for s in result['official_sources']], [OFFICIAL_URL])
        self.assertEqual(claude.client.messages.stream.call_count, 1)  # not retried
        self.assertEqual(claude.last_failure, claude_research.FAILURE_AUTH)
        self.assertIn('API key Anthropic ditolak', claude.last_error)
        self.assertEqual((wrapper.source_key, wrapper.label, wrapper.model), ('gemini_web', 'Gemini', gemini.model))
        self.assertIsNone(wrapper.last_error)
        # The rejected key is paused: the next research goes straight to Gemini.
        self.assertTrue(ai_providers.claude_auth_paused('bad-anthropic-key'))
        self.assertEqual(list(self.redis.ttl.values()), [ai_providers.CLAUDE_AUTH_PAUSE_SECONDS])
        self.assertIsInstance(research_engine_from_config(BOTH), GeminiWebResearch)
        # A new key is not paused.
        self.assertIsInstance(research_engine_from_config(dict(BOTH, anthropic_api_key='new-key')),
                              FallbackWebResearch)
        # The same engine, called again, skips Claude without a request.
        gemini.client.models.generate_content.side_effect = [gemini_response(chunks=chunks(R_COMP))]
        self.assertIsNotNone(wrapper.research(TOPIC))
        self.assertEqual(claude.client.messages.stream.call_count, 1)

    def test_claude_usage_limit_also_falls_back(self):
        limit = anthropic.RateLimitError('usage limits', response=httpx2.Response(429, request=REQUEST), body={
            'type': 'error', 'error': {'type': 'rate_limit_error',
                                       'message': 'You have reached your specified API usage limits.'}})
        wrapper = FallbackWebResearch(failing_claude(limit), engine(gemini_response(chunks=chunks(R_COMP))))
        self.assertIsNotNone(wrapper.research(TOPIC))
        self.assertEqual(wrapper.source_key, 'gemini_web')

    def test_other_claude_failures_do_not_run_gemini(self):
        bad = anthropic.APIStatusError('bad', response=httpx2.Response(400, request=REQUEST), body=None)
        gemini = engine(gemini_response())
        wrapper = FallbackWebResearch(failing_claude(bad), gemini)
        self.assertIsNone(wrapper.research(TOPIC))
        gemini.client.models.generate_content.assert_not_called()
        self.assertEqual(wrapper.source_key, 'claude_web')
        self.assertEqual(wrapper.last_error, claude_research.FAILURE_REASON)

    def test_both_failing_reports_the_gemini_reason(self):
        wrapper = FallbackWebResearch(failing_claude(claude_auth_error()), engine(genai_error(403)))
        self.assertIsNone(wrapper.research(TOPIC))
        self.assertIn('API key Gemini', wrapper.last_error)

    def test_text_provider_401_pauses_claude_research_too(self):
        stream = Mock(side_effect=claude_auth_error())
        client = SimpleNamespace(messages=SimpleNamespace(stream=stream),
                                 beta=SimpleNamespace(messages=SimpleNamespace(stream=stream)))
        provider = ai_providers.AnthropicText('bad-anthropic-key', 'claude-opus-5-5', client=client)
        with self.assertRaises(anthropic.AuthenticationError):
            provider.generate('Tulis artikel')
        self.assertTrue(ai_providers.claude_auth_paused('bad-anthropic-key'))


# ---------------------------------------------------------------------------
# SEOResearch labels its entries with the engine that ran
# ---------------------------------------------------------------------------

class SEOResearchEngineLabelTests(WebTestCase):
    PROVIDERS = {'analyze_competitors': [], 'get_official_sources': [], 'get_social_insights': [],
                 'get_keyword_suggestions': ['saran'], 'get_related_questions': ['apa itu spt?']}

    def run_topic(self, claude):
        research = SEOResearch(claude=claude)
        patches = [patch.object(research, name, Mock(return_value=value)) for name, value in self.PROVIDERS.items()]
        patches += [patch.object(seo_research, 'DDG_CALL_SPACING_SECONDS', 0),
                    patch.object(seo_research.random, 'uniform', return_value=0)]
        for p in patches:
            p.start()
        try:
            return research.research_topic(TOPIC, 'Pajak', exclude_hosts=['situs.example'])
        finally:
            for p in patches:
                p.stop()

    def test_gemini_results_are_recorded_as_gemini_web(self):
        result = self.run_topic(engine(gemini_response(chunks=chunks(R_OFFICIAL))))
        meta = result['source_metadata']
        self.assertNotIn('claude_web', meta)
        self.assertEqual(meta['gemini_web']['status'], 'real')
        self.assertEqual(meta['gemini_web']['model'], 'gemini-3.5-flash')
        self.assertEqual(meta['gemini_web']['tokens'], 4000)
        self.assertIsNone(meta['gemini_web']['estimated_cost_usd'])
        self.assertEqual(meta['official_sources']['via'], 'gemini_web')
        self.assertEqual([s['url'] for s in result['official_sources']], [OFFICIAL_URL])

    def test_failed_gemini_reason_names_gemini(self):
        result = self.run_topic(engine(gemini_response(chunks=())))
        meta = result['source_metadata']['gemini_web']
        self.assertEqual(meta['status'], 'unavailable')
        self.assertEqual(meta['reason'], gemini_research.FAILURE_REASON)

    def test_nothing_verified_names_gemini(self):
        # The search only found the publisher's own page.
        result = self.run_topic(engine(gemini_response(chunks=chunks(R_OWN))))
        self.assertIn('dari Gemini', result['source_metadata']['gemini_web']['reason'])

    def test_fallback_wrapper_reports_the_engine_that_ran(self):
        wrapper = FallbackWebResearch(failing_claude(claude_auth_error()),
                                      engine(gemini_response(chunks=chunks(R_OFFICIAL))))
        with patch.object(ai_providers, '_pause_store', return_value=FakeRedis()):
            meta = self.run_topic(wrapper)['source_metadata']
        self.assertEqual(meta['gemini_web']['status'], 'real')
        self.assertNotIn('claude_web', meta)


if __name__ == '__main__':
    unittest.main()
