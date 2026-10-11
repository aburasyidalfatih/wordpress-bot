"""deep_research_job refund bounds, Search Console dedupe, Trends counting and
bulk year update.

seo_research/trending_research pull in pytrends/pandas, which do not import in
every environment, so they and core_extensions are stubbed.
"""
import logging
import sys
import types
import unittest
from unittest.mock import Mock, patch

if 'core_extensions' not in sys.modules:
    _stub = types.ModuleType('core_extensions')
    _stub.db = None
    _stub.logger = logging.getLogger('test_core_extensions')
    _stub.redis_conn = None
    _stub.trending = None
    for _name in ('load_config', 'send_telegram_notification', 'post_to_telegram_channel',
                  'post_to_facebook_page', 'post_to_twitter', 'post_to_threads',
                  'post_to_pinterest'):
        setattr(_stub, _name, Mock())
    sys.modules['core_extensions'] = _stub

import tasks.research_jobs as rj  # noqa: E402


class FakeSession:
    def __init__(self, site):
        self.site = site

    def query(self, _model):
        return self

    def filter_by(self, **_kwargs):
        return self

    def first(self):
        return self.site


class FakeDB:
    def __init__(self, site):
        self.site = site
        self.refunds = []
        self.saved = []

    def get_session(self):
        db = self

        class _Ctx:
            def __enter__(self_inner):
                return FakeSession(db.site)

            def __exit__(self_inner, *exc):
                return False
        return _Ctx()

    def refund_user_credits(self, user_id, amount=1):
        self.refunds.append(amount)
        return True

    def save_research_data(self, **kwargs):
        self.saved.append(kwargs['category'])

    @property
    def refunded(self):
        return sum(self.refunds)


def make_site(names):
    return types.SimpleNamespace(
        site_name='Site', telegram_enabled=False, telegram_bot_token=None,
        telegram_chat_id=None, language='id',
        selected_categories=[{'id': i, 'name': n} for i, n in enumerate(names)],
    )


class FakeSEOResearch:
    failing = set()

    def research_category(self, name, language='id'):
        if name in self.failing:
            raise RuntimeError('blocked')
        providers = {p: {'status': 'real'} for p in ('google_trends', 'google_autocomplete', 'competitors')}
        return {'quality': {'score': 60, 'real_provider_count': 3}, 'source_metadata': providers}


class DeepResearchRefundTests(unittest.TestCase):
    def run_job(self, names, failing=(), telegram=None, **kwargs):
        self.db = FakeDB(make_site(names) if names is not None else None)
        FakeSEOResearch.failing = set(failing)
        trending = Mock()
        trending.get_trending_topics.return_value = {}
        trending.build_topic_suggestions.return_value = ['t']
        seo_module = types.ModuleType('seo_research')
        seo_module.SEOResearch = FakeSEOResearch
        with patch.object(rj, 'db', self.db), patch.object(rj, 'trending', trending), \
                patch.object(rj, '_load_search_console_queries', return_value=[]), \
                patch.object(rj, 'send_telegram_notification', telegram or Mock()), \
                patch.dict(sys.modules, {'seo_research': seo_module}):
            return rj.deep_research_job(1, site_id=1, **kwargs)

    def test_duplicates_are_researched_once_and_surplus_refunded(self):
        result = self.run_job(['Keuangan', 'Keuangan', 'Parenting'], force=True, charged_credits=3)
        self.assertEqual(self.db.saved, ['Keuangan', 'Parenting'])
        self.assertEqual(self.db.refunded, 1)
        self.assertEqual(result['refunded_credits'], 1)

    def test_failed_categories_are_refunded(self):
        self.run_job(['Keuangan', 'Parenting'], failing={'Parenting'}, force=True, charged_credits=2)
        self.assertEqual(self.db.refunded, 1)

    def test_research_is_capped_to_charged_credits(self):
        self.run_job(['Keuangan', 'Parenting', 'Bisnis'], force=True, charged_credits=1)
        self.assertEqual(self.db.saved, ['Keuangan'])
        self.assertEqual(self.db.refunded, 0)

    def test_refund_never_exceeds_charge_when_failure_follows_refund(self):
        telegram = Mock(side_effect=RuntimeError('telegram down'))
        self.run_job(['Keuangan', 'Parenting'], failing={'Keuangan', 'Parenting'},
                     telegram=telegram, force=True, charged_credits=2)
        self.assertEqual(self.db.refunded, 2)

    def test_deleted_site_refunds_charge(self):
        self.run_job(None, force=True, charged_credits=2)
        self.assertEqual(self.db.refunded, 2)

    def test_category_no_longer_selected_refunds_charge(self):
        self.run_job(['Keuangan'], force=True, charged_credits=1, category='Parenting')
        self.assertEqual(self.db.refunded, 1)

    def test_scheduled_run_never_refunds(self):
        self.run_job(['Keuangan', 'Parenting'], failing={'Parenting'}, force=False)
        self.assertEqual(self.db.refunds, [])
        self.assertEqual(self.db.saved, ['Keuangan'])


class SearchConsoleEvidenceTests(unittest.TestCase):
    def test_rows_are_deduplicated_by_query(self):
        rows = [
            {'query': 'tips menabung', 'page': '/a', 'impressions': 10, 'clicks': 1, 'position': 8.0},
            {'query': 'Tips  Menabung', 'page': '/b', 'impressions': 5, 'clicks': 0, 'position': 4.5},
            {'query': 'menabung emas', 'page': '/c', 'impressions': 3, 'clicks': 0, 'position': 12.0},
        ]
        matches = rj._search_console_evidence(rows, 'Menabung')
        self.assertEqual(len(matches), 2)
        top = matches[0]
        self.assertEqual(top['impressions'], 15)
        self.assertEqual(top['clicks'], 1)
        self.assertEqual(top['position'], 4.5)

    def test_load_aggregates_rows(self):
        rows = [
            {'query': 'q', 'page': '/a', 'impressions': 2, 'clicks': 0, 'position': 3},
            {'query': 'q', 'page': '/b', 'impressions': 2, 'clicks': 0, 'position': 9},
        ]
        planner = types.SimpleNamespace(load_search_metrics=lambda *a: (rows, []))
        db = FakeDB(None)
        with patch.object(rj, 'db', db), \
                patch.dict(sys.modules, {'services.content_planner': planner}):
            loaded = rj._load_search_console_queries(1, 1)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]['impressions'], 4)


class GoogleTrendsCountingTests(unittest.TestCase):
    def test_related_queries_do_not_double_count_trends(self):
        self.assertEqual(rj._google_trends_top_up({'google_trends': {'status': 'real'}}, 12), (0, 0))

    def test_related_queries_stand_in_when_trends_call_failed(self):
        self.assertEqual(rj._google_trends_top_up({'google_trends': {'status': 'unavailable'}}, 3), (10, 1))
        self.assertEqual(rj._google_trends_top_up({}, 0), (0, 0))


class BulkUpdateYearTests(unittest.TestCase):
    def test_only_raw_fields_are_written_back(self):
        site = types.SimpleNamespace(wordpress_url='https://example.com', wordpress_username='a',
                                     wordpress_password='b', site_name='Site')
        bot = Mock()
        bot.get_posts.return_value = (True, [
            {'id': 1, 'title': {'raw': 'Tips 2025', 'rendered': 'Tips 2025'},
             'content': {'raw': '[gallery] 2025', 'rendered': '<div>gallery</div> 2025'}},
            {'id': 2, 'title': {'rendered': 'Rendered 2025'}, 'content': {'rendered': '<p>2025</p>'}},
        ], 1)
        bot.update_post.return_value = (True, {})
        with patch.object(rj, 'db', FakeDB(site)), \
                patch('services.wp_publisher.WordPressPublisher', return_value=bot), \
                patch.object(rj, 'send_telegram_notification', Mock()):
            rj.bulk_update_year_task(1, 1, 2025, 2026)
        self.assertEqual(bot.get_posts.call_args.kwargs['context'], 'edit')
        bot.update_post.assert_called_once_with(1, {'title': 'Tips 2026', 'content': '[gallery] 2026'})


if __name__ == '__main__':
    unittest.main()
