import unittest
from unittest.mock import patch

import seo_research
from seo_research import SEOResearch
from trending_research import TrendingResearch


class FakeSeries:
    def __init__(self, values):
        self._values = values

    def tolist(self):
        return self._values


class FakeTrendFrame:
    empty = False
    columns = ['bisnis online']

    def __getitem__(self, key):
        if key != 'bisnis online':
            raise KeyError(key)
        return FakeSeries([20, 25, 30, 35, 45, 55, 65, 75])


class FakeTrendClient:
    def __init__(self, *args, **kwargs):
        pass

    def build_payload(self, *args, **kwargs):
        return None

    def interest_over_time(self):
        return FakeTrendFrame()


class ResearchQualityTests(unittest.TestCase):
    def setUp(self):
        with patch.object(seo_research, 'DDGS', None):
            self.research = SEOResearch()

    def test_quality_requires_multiple_real_providers(self):
        result = self.research.evaluate_quality({
            'google_trends': {'status': 'real'},
            'google_autocomplete': {'status': 'fallback'},
        }, suggestion_count=10)
        self.assertEqual(result['confidence'], 'insufficient')
        self.assertFalse(result['passes_minimum'])

    def test_quality_high_for_diverse_real_evidence(self):
        providers = {
            name: {'status': 'real'} for name in (
                'google_trends', 'google_autocomplete', 'related_questions',
                'competitors', 'social', 'youtube', 'news', 'wikipedia'
            )
        }
        result = self.research.evaluate_quality(
            providers, competitor_count=3, transcript_count=2,
            suggestion_count=10, question_count=8,
        )
        self.assertEqual(result['score'], 100)
        self.assertEqual(result['confidence'], 'high')
        self.assertTrue(result['passes_minimum'])

    def test_long_tail_keywords_are_deduplicated(self):
        result = self.research.build_long_tail_keywords(
            'bisnis',
            ['cara memulai bisnis online', 'Cara   memulai bisnis online'],
            ['bagaimana cara memilih produk bisnis online'],
        )
        self.assertEqual(result, [
            'cara memulai bisnis online',
            'bagaimana cara memilih produk bisnis online',
        ])

    def test_social_fallback_never_fabricates_evidence(self):
        self.assertEqual(self.research._get_fallback_social('bisnis online', 'id'), [])

    def test_trend_score_is_measured_not_default_fifty(self):
        with patch.object(seo_research, 'TrendReq', FakeTrendClient):
            analysis = self.research.get_trend_analysis('bisnis online', 'id')
        self.assertEqual(analysis['status'], 'real')
        self.assertGreater(analysis['score'], 50)
        self.assertIsNotNone(analysis['growth'])


class TrendingResearchTests(unittest.TestCase):
    def test_country_trend_relevance_filter(self):
        self.assertTrue(TrendingResearch.is_relevant('Bisnis online terbaru', 'Bisnis Online'))
        self.assertFalse(TrendingResearch.is_relevant('Skor pertandingan sepak bola', 'Bisnis Online'))

    def test_suggestions_are_deduplicated_and_prioritized(self):
        result = TrendingResearch.build_topic_suggestions('Teknologi', {
            'related_rising': ['AI Indonesia', 'AI Indonesia'],
            'related_top': ['Laptop terbaik'],
            'trending_now': ['Teknologi hijau'],
        }, count=3)
        self.assertEqual([item['topic'] for item in result], [
            'AI Indonesia', 'Laptop terbaik', 'Teknologi hijau'
        ])
        self.assertEqual(result[0]['type'], 'rising')


if __name__ == '__main__':
    unittest.main()
