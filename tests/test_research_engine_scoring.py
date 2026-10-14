"""Research engine: quality scoring, provider counting and evidence filters.

pytrends pulls in pandas, which does not import in every environment, so it is
stubbed when the real import fails. No test makes a network call.
"""
import sys
import types
import unittest
from unittest.mock import Mock, patch

try:
    import pytrends.request  # noqa: F401
except Exception:  # broken/missing pandas: stub, the tests patch TrendReq anyway
    for _name in ('pytrends', 'pytrends.request'):
        sys.modules[_name] = types.ModuleType(_name)
    sys.modules['pytrends.request'].TrendReq = object

# Other test modules replace trending_research with a bare stub when pytrends
# fails to import; this file needs the real modules.
for _module in ('trending_research', 'seo_research'):
    if _module in sys.modules and not getattr(sys.modules[_module], '__file__', None):
        del sys.modules[_module]

import seo_research  # noqa: E402
import trending_research  # noqa: E402
from seo_research import (  # noqa: E402
    SEOResearch,
    extract_youtube_video_id,
    is_boilerplate_heading,
    is_question_title,
    transcript_excerpt,
)
from trending_research import TrendingResearch  # noqa: E402

ALL_PROVIDERS = ('google_trends', 'google_autocomplete', 'related_questions',
                 'competitors', 'social', 'youtube', 'news', 'wikipedia')


def _research():
    with patch.object(seo_research, 'DDGS', None):
        return SEOResearch()


class _Series:
    def __init__(self, values):
        self._values = values

    def tolist(self):
        return list(self._values)


class _Frame:
    def __init__(self, keyword, values, partial=None):
        self._data = {keyword: values}
        if partial is not None:
            self._data['isPartial'] = partial
        self.columns = list(self._data)
        self.empty = not values

    def __getitem__(self, key):
        return _Series(self._data[key])


def _trend_client(frame, calls):
    class Client:
        def __init__(self, *args, **kwargs):
            calls.append(('init', kwargs))

        def build_payload(self, *args, **kwargs):
            calls.append(('build_payload', kwargs))

        def interest_over_time(self):
            calls.append(('interest_over_time', {}))
            return frame
    return Client


class ProviderCountingTests(unittest.TestCase):
    def test_google_suggest_counts_as_one_real_provider(self):
        result = SEOResearch.evaluate_quality({
            'google_autocomplete': {'status': 'real'},
            'related_questions': {'status': 'real'},
        })
        self.assertEqual(result['real_provider_count'], 1)
        # Point weights are unchanged: 20 + 15.
        self.assertEqual(result['score'], 35)
        self.assertEqual(result['confidence'], 'insufficient')

    def test_all_real_providers_count_seven_upstreams(self):
        providers = {name: {'status': 'real'} for name in ALL_PROVIDERS}
        result = SEOResearch.evaluate_quality(
            providers, competitor_count=3, transcript_count=2,
            suggestion_count=10, question_count=10,
        )
        self.assertEqual(result['real_provider_count'], 7)
        self.assertEqual(result['score'], 100)
        self.assertEqual(result['confidence'], 'high')

    def test_depth_bonus_ignores_fallback_and_failed_providers(self):
        status = {
            'google_autocomplete': {'status': 'fallback'},
            'related_questions': {'status': 'fallback'},
            'competitors': {'status': 'unavailable'},
            'youtube': {'status': 'partial'},
        }
        without_counts = SEOResearch.evaluate_quality(status)
        with_counts = SEOResearch.evaluate_quality(
            status, competitor_count=4, transcript_count=2,
            suggestion_count=10, question_count=10,
        )
        self.assertEqual(with_counts['score'], without_counts['score'])
        self.assertEqual(with_counts['fallback_providers'], ['google_autocomplete', 'related_questions'])

    def test_real_only_filters_fallback_lists(self):
        research = _research()
        research._mark_source('google_autocomplete', 'fallback', count=5)
        research._mark_source('related_questions', 'real', count=1)
        self.assertEqual(research._real_only('google_autocomplete', ['tips x']), [])
        self.assertEqual(research._real_only('related_questions', ['apa itu x?']), ['apa itu x?'])
        self.assertEqual(research._real_only('wikipedia', ['anything']), [])

    def test_long_tail_built_from_real_items_only(self):
        research = _research()
        fallback = ['cara memulai bisnis online', 'bisnis online untuk pemula']
        real_questions = ['bagaimana cara memulai bisnis online dari rumah']
        with patch.object(research, 'get_keyword_suggestions',
                          side_effect=lambda *a, **k: research._mark_source(
                              'google_autocomplete', 'fallback') or fallback), \
                patch.object(research, 'get_related_questions',
                             side_effect=lambda *a, **k: research._mark_source(
                                 'related_questions', 'real') or real_questions), \
                patch.object(research, 'get_trend_analysis', return_value=None), \
                patch.object(research, 'get_wikipedia_context', return_value=''), \
                patch.object(research, 'analyze_competitors', return_value=[]), \
                patch.object(research, 'get_social_insights', return_value=[]), \
                patch.object(research, 'get_youtube_insights', return_value=[]), \
                patch.object(research, 'get_latest_news', return_value=[]), \
                patch.object(seo_research, 'DDG_CALL_SPACING_SECONDS', 0), \
                patch.object(seo_research.random, 'uniform', return_value=0):
            result = research.research_category('bisnis online')
        self.assertEqual(result['evidence_suggestions'], [])
        self.assertEqual(result['evidence_questions'], real_questions)
        self.assertEqual(result['long_tail_keywords'], real_questions)
        # The raw list still carries the fallback phrases for the UI.
        self.assertEqual(result['suggestions'], fallback)


class WikipediaTests(unittest.TestCase):
    LONG_EXTRACT = ('Bisnis daring adalah kegiatan jual beli barang dan jasa melalui internet. ' * 4).strip()

    def _fetch(self, payload):
        research = _research()
        response = Mock(status_code=200)
        response.json.return_value = payload
        with patch.object(seo_research.requests, 'get', return_value=response) as get:
            extract = research.get_wikipedia_context('bisnis Online', 'id')
        return research, extract, get.call_args.kwargs['params']

    def test_redirects_and_case_variants_are_requested(self):
        _research_obj, _extract, params = self._fetch({'query': {'pages': {}}})
        self.assertEqual(params['redirects'], 1)
        self.assertIn('Bisnis online', params['titles'].split('|'))
        self.assertIn('bisnis Online', params['titles'].split('|'))

    def test_redirected_title_with_real_extract_is_real(self):
        research, extract, _ = self._fetch({'query': {
            'normalized': [{'from': 'bisnis Online', 'to': 'Bisnis Online'}],
            'redirects': [{'from': 'Bisnis Online', 'to': 'Bisnis daring'}],
            'pages': {
                '-1': {'title': 'Bisnis Online', 'missing': ''},
                '42': {'pageid': 42, 'title': 'Bisnis daring', 'extract': self.LONG_EXTRACT},
            },
        }})
        self.assertEqual(extract, self.LONG_EXTRACT)
        self.assertEqual(research.source_status['wikipedia']['status'], 'real')

    def test_short_extract_is_unavailable(self):
        research, extract, _ = self._fetch({'query': {'pages': {
            '7': {'pageid': 7, 'title': 'Bisnis online', 'extract': 'Bisnis online'},
        }}})
        self.assertEqual(extract, '')
        self.assertEqual(research.source_status['wikipedia']['status'], 'unavailable')

    def test_disambiguation_page_is_unavailable(self):
        research, extract, _ = self._fetch({'query': {'pages': {
            '7': {'pageid': 7, 'title': 'Bisnis online', 'extract': self.LONG_EXTRACT,
                  'pageprops': {'disambiguation': ''}},
        }}})
        self.assertEqual(extract, '')
        self.assertEqual(research.source_status['wikipedia']['status'], 'unavailable')


class TrendScoreTests(unittest.TestCase):
    def setUp(self):
        trending_research._trends_clients.clear()
        patcher = patch.object(trending_research, 'TRENDS_MIN_INTERVAL_SECONDS', 0)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(trending_research._trends_clients.clear)

    def _analyze(self, values, partial=None, language='id'):
        calls = []
        research = _research()
        client = _trend_client(_Frame('bisnis online', values, partial), calls)
        with patch.object(seo_research, 'TrendReq', client):
            analysis = research.get_trend_analysis('bisnis online', language)
        return research, analysis, calls

    def test_all_zero_series_is_not_real(self):
        research, analysis, _ = self._analyze([0] * 90)
        self.assertEqual(analysis['status'], 'unavailable')
        self.assertIsNone(analysis['score'])
        self.assertEqual(research.source_status['google_trends']['status'], 'unavailable')
        score = SEOResearch.evaluate_quality(research.source_status)['score']
        self.assertEqual(score, 0)

    def test_empty_series_is_unavailable(self):
        research, analysis, _ = self._analyze([])
        self.assertEqual(analysis['status'], 'unavailable')
        self.assertEqual(research.source_status['google_trends']['status'], 'unavailable')

    def test_growth_compares_last_week_with_previous_week(self):
        values = [10] * 76 + [20] * 7 + [30] * 7
        _research_obj, analysis, calls = self._analyze(values)
        self.assertEqual(analysis['status'], 'real')
        self.assertEqual(analysis['current'], 30.0)
        self.assertEqual(analysis['growth'], 50.0)
        payload = next(kwargs for name, kwargs in calls if name == 'build_payload')
        self.assertEqual(payload['timeframe'], 'today 3-m')

    def test_partial_last_day_is_ignored(self):
        values = [10] * 14 + [100]
        partial = [False] * 14 + [True]
        _research_obj, analysis, _ = self._analyze(values, partial)
        self.assertEqual(analysis['current'], 10.0)
        self.assertEqual(analysis['growth'], 0.0)

    def test_wib_timezone_and_backoff(self):
        _research_obj, _analysis, calls = self._analyze([5] * 30)
        init = next(kwargs for name, kwargs in calls if name == 'init')
        self.assertEqual(init['tz'], -420)
        self.assertEqual(init['hl'], 'id-ID')
        self.assertEqual(init['retries'], 2)
        self.assertGreaterEqual(init['backoff_factor'], 2)
        self.assertEqual(trending_research.trends_locale('en')[1], 360)

    def test_client_is_reused_across_calls(self):
        calls = []
        client = _trend_client(_Frame('bisnis online', [5] * 30), calls)
        with patch.object(seo_research, 'TrendReq', client):
            _research().get_trend_analysis('bisnis online', 'id')
            _research().get_trend_analysis('bisnis online', 'id')
        self.assertEqual(sum(1 for name, _ in calls if name == 'init'), 1)

    def test_requests_are_spaced(self):
        calls = []
        client = _trend_client(_Frame('bisnis online', [5] * 30), calls)
        sleeps = []
        with patch.object(trending_research, 'TRENDS_MIN_INTERVAL_SECONDS', 4), \
                patch.object(trending_research, '_last_trends_request', 0.0), \
                patch.object(trending_research.time, 'sleep', side_effect=sleeps.append), \
                patch.object(seo_research, 'TrendReq', client):
            _research().get_trend_analysis('bisnis online', 'id')
        # Client creation, build_payload and interest_over_time: two waits.
        self.assertEqual(len(sleeps), 2)
        self.assertTrue(all(0 < s <= 4 for s in sleeps))

    def test_trends_error_marks_provider_unavailable_and_keeps_client(self):
        calls = []

        class Failing:
            def __init__(self, *args, **kwargs):
                calls.append('init')

            def build_payload(self, *args, **kwargs):
                raise RuntimeError('The request failed: Google returned a response with code 429')

        with patch.object(seo_research, 'TrendReq', Failing):
            research = _research()
            analysis = research.get_trend_analysis('bisnis online', 'id')
            research.get_trend_analysis('bisnis online', 'id')
        self.assertEqual(analysis['status'], 'unavailable')
        self.assertEqual(research.source_status['google_trends']['status'], 'unavailable')
        self.assertEqual(calls, ['init'])


class CompetitorOutlineTests(unittest.TestCase):
    def test_boilerplate_headings_are_detected(self):
        for heading in ('Leave a Reply', 'Leave a Reply Cancel reply', 'Tinggalkan Balasan',
                        'Related Posts', 'Artikel Terkait', 'You May Also Like', '3 Comments',
                        'Komentar', 'Share this:', 'Bagikan', 'Popular Posts', 'Recent Posts',
                        'Categories', 'Kategori', 'Newsletter', 'Subscribe to our newsletter',
                        'Search', 'Navigation', 'Menu', 'About Us', 'Hubungi Kami', 'Baca Juga'):
            self.assertTrue(is_boilerplate_heading(heading), heading)

    def test_content_headings_survive(self):
        for heading in ('Search engine optimization basics', 'Cara memilih kategori produk',
                        'Komentar pelanggan sebagai sumber ide', 'Menu makanan sehat untuk anak'):
            self.assertFalse(is_boilerplate_heading(heading), heading)

    def test_outline_strips_links_and_boilerplate(self):
        content = '\n'.join([
            '## [Cara Memulai Bisnis Online](https://example.com/a)',
            '## Leave a Reply',
            '### Modal awal yang realistis',
            '## Related Posts',
            '## Artikel Terkait',
        ])
        self.assertEqual(SEOResearch.extract_outline(content), [
            'Cara Memulai Bisnis Online', 'Modal awal yang realistis',
        ])

    def test_competitors_keep_search_rank_order(self):
        research = _research()
        ddgs = Mock()
        ddgs.text.return_value = [
            {'href': 'https://a.test/1', 'title': 'First'},
            {'href': 'https://b.test/2', 'title': 'Second'},
            {'href': 'https://c.test/3', 'title': 'Third'},
        ]

        def scrape(url, title, *_args):
            # The top result finishes last.
            import time as _time
            _time.sleep({'First': .2, 'Second': .1, 'Third': 0}[title])
            return {'url': url, 'title': title, 'headers': [title]}

        with patch.object(research, '_new_ddgs', return_value=ddgs), \
                patch.object(research, '_scrape_competitor', side_effect=scrape):
            result = research.analyze_competitors('bisnis online', 'id')
        self.assertEqual([item['title'] for item in result], ['First', 'Second', 'Third'])

    def test_ddgs_calls_pass_region(self):
        research = _research()
        ddgs = Mock()
        ddgs.news.return_value = [{'title': 'Judul', 'source': 'Kompas', 'url': 'https://k.test',
                                   'date': '2026-10-01T00:00:00+00:00'}]
        with patch.object(research, '_new_ddgs', return_value=ddgs):
            news = research.get_latest_news('bisnis online', limit=3, language='id')
        self.assertEqual(ddgs.news.call_args.kwargs['region'], 'id-id')
        self.assertEqual(ddgs.news.call_args.kwargs['max_results'], 3)
        self.assertEqual(news[0]['published_at'], '2026-10-01T00:00:00+00:00')


class SocialQuestionFilterTests(unittest.TestCase):
    def test_word_boundaries(self):
        self.assertFalse(is_question_title('Siapa pemilik toko ini', 'id'))
        self.assertFalse(is_question_title('Sewa apartemen murah Jakarta', 'id'))
        self.assertTrue(is_question_title('Apa modal awal bisnis online', 'id'))
        self.assertTrue(is_question_title('Bagaimana memulai dropship', 'id'))
        self.assertFalse(is_question_title('Show HN: my side project', 'en'))
        self.assertTrue(is_question_title('How do I start freelancing', 'en'))
        self.assertTrue(is_question_title('Worth it to start a blog in 2026?', 'en'))


class YouTubeTests(unittest.TestCase):
    def test_video_id_only_from_video_urls(self):
        self.assertEqual(extract_youtube_video_id('https://www.youtube.com/watch?v=dQw4w9WgXcQ'), 'dQw4w9WgXcQ')
        self.assertEqual(extract_youtube_video_id('https://www.youtube.com/watch?feature=share&v=dQw4w9WgXcQ'),
                         'dQw4w9WgXcQ')
        self.assertEqual(extract_youtube_video_id('https://youtu.be/dQw4w9WgXcQ?t=10'), 'dQw4w9WgXcQ')
        self.assertEqual(extract_youtube_video_id('https://youtube.com/shorts/dQw4w9WgXcQ'), 'dQw4w9WgXcQ')
        self.assertEqual(extract_youtube_video_id('https://www.youtube.com/embed/dQw4w9WgXcQ'), 'dQw4w9WgXcQ')
        self.assertIsNone(extract_youtube_video_id('https://www.youtube.com/channel/UCabcdefghijklmnopqrstuv'))
        self.assertIsNone(extract_youtube_video_id('https://www.youtube.com/c/SomeChannelName'))
        self.assertIsNone(extract_youtube_video_id('https://www.youtube.com/@handle12345'))
        self.assertIsNone(extract_youtube_video_id('https://www.youtube.com/playlist?list=PL1234567890'))

    def test_transcript_excerpt_covers_first_three_minutes(self):
        snippets = [types.SimpleNamespace(text=f'kalimat {i}', start=i * 10.0, duration=10.0)
                    for i in range(40)]
        excerpt = transcript_excerpt(snippets)
        self.assertIn('kalimat 18', excerpt)   # 180 s
        self.assertNotIn('kalimat 19', excerpt)
        self.assertLessEqual(len(transcript_excerpt(snippets, max_chars=50)), 53)

    def test_transcript_errors_are_handled(self):
        research = _research()
        ddgs = Mock()
        ddgs.text.return_value = [
            {'href': 'https://www.youtube.com/channel/UCabcdefghijklmnopqrstuv', 'title': 'Channel'},
            {'href': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ', 'title': 'Video'},
        ]

        class FakeApi:
            def fetch(self, video_id, languages=()):
                raise RuntimeError('Subtitles are disabled for this video')

        with patch.object(research, '_new_ddgs', return_value=ddgs), \
                patch.object(seo_research, 'YouTubeTranscriptApi', FakeApi):
            insights = research.get_youtube_insights('bisnis online', 'id')
        self.assertEqual([item['video_id'] for item in insights], ['dQw4w9WgXcQ'])
        self.assertFalse(insights[0]['transcript_available'])
        self.assertEqual(research.source_status['youtube']['status'], 'partial')

    def test_transcript_uses_v1_fetch_api(self):
        research = _research()
        ddgs = Mock()
        ddgs.text.return_value = [{'href': 'https://youtu.be/dQw4w9WgXcQ', 'title': 'Video'}]
        seen = {}

        class FakeApi:
            def fetch(self, video_id, languages=()):
                seen['args'] = (video_id, list(languages))
                return [types.SimpleNamespace(text='halo semua', start=0.0, duration=2.0)]

        with patch.object(research, '_new_ddgs', return_value=ddgs), \
                patch.object(seo_research, 'YouTubeTranscriptApi', FakeApi):
            insights = research.get_youtube_insights('bisnis online', 'id')
        self.assertEqual(seen['args'], ('dQw4w9WgXcQ', ['id', 'en']))
        self.assertEqual(insights[0]['snippets'], 'halo semua')
        self.assertEqual(research.source_status['youtube']['status'], 'real')


class TopicSuggestionTests(unittest.TestCase):
    def test_trending_searches_endpoint_is_not_called(self):
        client = Mock()
        client.related_queries.return_value = {}
        with patch.object(trending_research, 'TRENDS_MIN_INTERVAL_SECONDS', 0), \
                patch.object(trending_research, 'TrendReq', Mock(return_value=client)):
            trending_research._trends_clients.clear()
            data = TrendingResearch().get_trending_topics('bisnis online', language='id')
            trending_research._trends_clients.clear()
        client.trending_searches.assert_not_called()
        self.assertEqual(data['trending_now'], [])

    def test_topics_from_real_evidence_when_trends_is_empty(self):
        result = TrendingResearch.build_topic_suggestions(
            'Bisnis Online', {'related_rising': [], 'related_top': []}, count=5,
            suggestions=['bisnis online', 'bisnis online modal kecil'],
            questions=['bagaimana cara memulai bisnis online?'],
            long_tail=['bisnis online modal kecil untuk mahasiswa'],
        )
        self.assertEqual([(item['topic'], item['type']) for item in result], [
            ('bagaimana cara memulai bisnis online?', 'question'),
            ('bisnis online modal kecil untuk mahasiswa', 'long_tail'),
            ('bisnis online modal kecil', 'autocomplete'),
        ])
        self.assertFalse(any(item['is_trending'] for item in result))

    def test_trend_topics_come_first_and_are_flagged(self):
        result = TrendingResearch.build_topic_suggestions(
            'Teknologi', {'related_rising': ['AI Indonesia']}, count=2,
            keywords=['teknologi terbaru 2026'],
        )
        self.assertEqual([item['topic'] for item in result], ['AI Indonesia', 'teknologi terbaru 2026'])
        self.assertTrue(result[0]['is_trending'])
        self.assertFalse(result[1]['is_trending'])


if __name__ == '__main__':
    unittest.main()
