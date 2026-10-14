"""Search Console relevance filtering per category/topic and opportunity classification."""
import unittest

from services.content_planner import (
    ACTION_NEW_ARTICLE, ACTION_REFRESH_CONTENT, ACTION_REWRITE_META,
    filter_opportunities_for_topic, plan_from_opportunities, text_matches_topic,
    topic_candidates_from_opportunities,
)
from services.search_console import build_search_opportunities
from test_research_backend_support import load_with_stubbed_core

rj, _core = load_with_stubbed_core('tasks.research_jobs')


def row(query, position, ctr, clicks=10, impressions=500, page='https://example.com/a'):
    return {'query': query, 'page': page, 'clicks': clicks, 'impressions': impressions,
            'ctr': ctr, 'position': position}


class TopicFilterTests(unittest.TestCase):
    def test_generic_words_do_not_make_a_query_relevant(self):
        self.assertFalse(text_matches_topic('tips diet sehat', 'Tips Bisnis'))
        self.assertFalse(text_matches_topic('cara online terbaik', 'Cara Investasi Online'))
        self.assertFalse(text_matches_topic('best guide how to', 'Best Guide'))

    def test_shared_meaningful_token_matches(self):
        self.assertTrue(text_matches_topic('cara investasi emas untuk pemula', 'Investasi'))
        self.assertTrue(text_matches_topic('saving for beginners', 'Savings'))
        self.assertTrue(text_matches_topic('resep rendang', 'Kuliner', 'Resep Rendang Padang'))

    def test_short_specific_phrase_matches(self):
        self.assertTrue(text_matches_topic('simulasi kpr bca 2025', 'KPR'))
        self.assertFalse(text_matches_topic('kprs', 'KPR'))

    def test_filter_opportunities(self):
        opportunities = [{'query': 'harga emas hari ini'}, {'query': 'tips diet'}, {'query': None}]
        self.assertEqual(filter_opportunities_for_topic(opportunities, 'Investasi Emas'),
                         [{'query': 'harga emas hari ini'}])
        self.assertEqual(filter_opportunities_for_topic(opportunities, None, ''), [])

    def test_research_evidence_ignores_generic_overlap(self):
        rows = [{'query': 'tips diet sehat', 'impressions': 50, 'clicks': 1, 'position': 5},
                {'query': 'tips bisnis kuliner', 'impressions': 10, 'clicks': 0, 'position': 9}]
        matches = rj._search_console_evidence(rows, 'Tips Bisnis')
        self.assertEqual([m['query'] for m in matches], ['tips bisnis kuliner'])


class ClassificationOrderTests(unittest.TestCase):
    def classify(self, current, previous=()):
        return {o['query']: o['type'] for o in build_search_opportunities(current, list(previous))}

    def test_page_one_low_ctr_is_not_a_quick_win(self):
        self.assertEqual(self.classify([row('kpr syariah', 6, .01)]), {'kpr syariah': 'low_ctr'})

    def test_falling_clicks_beat_quick_win_and_low_ctr(self):
        current = [row('kpr syariah', 6, .01, clicks=5)]
        previous = [row('kpr syariah', 5, .03, clicks=20)]
        self.assertEqual(self.classify(current, previous), {'kpr syariah': 'declining'})

    def test_quick_win_needs_healthy_ctr_or_page_two(self):
        types = self.classify([row('kpr syariah', 6, .05), row('kpr bank', 14, .005)])
        self.assertEqual(types, {'kpr syariah': 'quick_win', 'kpr bank': 'quick_win'})

    def test_actions_follow_the_type(self):
        current = [row('a query', 6, .01), row('b query', 12, .05), row('c query', 3, .05, clicks=2)]
        previous = [row('c query', 3, .05, clicks=20)]
        planned = {o['query']: o['action'] for o in
                   plan_from_opportunities(build_search_opportunities(current, previous))}
        self.assertEqual(planned, {'a query': ACTION_REWRITE_META, 'b query': ACTION_NEW_ARTICLE,
                                   'c query': ACTION_REFRESH_CONTENT})
        # Only quick wins become new article topics.
        candidates = topic_candidates_from_opportunities(build_search_opportunities(current, previous))
        self.assertEqual([c['query'] for c in candidates], ['b query'])


if __name__ == '__main__':
    unittest.main()
