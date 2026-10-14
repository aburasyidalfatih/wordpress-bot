"""Bulk year update: validation and replacement only in visible text."""
import types
import unittest
from unittest.mock import Mock, patch

from test_research_backend_support import load_with_stubbed_core

rj, _core = load_with_stubbed_core('tasks.research_jobs')


class YearValidationTests(unittest.TestCase):
    def test_valid_years(self):
        self.assertEqual(rj.validate_year_change('2025', 2026), (2025, 2026, None))

    def test_rejects_non_years_and_same_year(self):
        for from_year, to_year in (('1', '2'), ('20', '2026'), ('2025', '2025'), ('1999', '2025'),
                                   ('2025', '2101'), ('20x5', '2026'), (True, 2026), (None, 2026),
                                   ('02025', '2026'), (2025.0, 2026)):
            with self.subTest(from_year=from_year, to_year=to_year):
                parsed_from, parsed_to, error = rj.validate_year_change(from_year, to_year)
                self.assertIsNone(parsed_from)
                self.assertTrue(error)


class YearReplacementTests(unittest.TestCase):
    def test_visible_text_is_updated(self):
        self.assertEqual(rj.replace_year_in_title('Panduan 2025', 2025, 2026), 'Panduan 2026')
        self.assertEqual(rj.replace_year_in_content('<p>Panduan 2025.</p>', 2025, 2026),
                         '<p>Panduan 2026.</p>')
        self.assertEqual(rj.replace_year_in_content('<h2>Tren (2025), lalu</h2>', 2025, 2026),
                         '<h2>Tren (2026), lalu</h2>')

    def test_upload_paths_and_attributes_are_untouched(self):
        html = (
            '<!-- wp:image {"url":"https://contoh.com/wp-content/uploads/2025/06/x.jpg"} -->'
            '<figure><img src="/wp-content/uploads/2025/06/x.jpg" alt="Panduan 2025" '
            'srcset="/wp-content/uploads/2025/06/x-300.jpg 300w"/></figure>'
            '<!-- /wp:image -->'
            '<p>Lihat <a href="https://contoh.com/promo-2025/?tahun=2025" title="2025">Panduan 2025</a> '
            'atau /wp-content/uploads/2025/06/x.jpg dan https://contoh.com/sejak+2025 '
            'serta https://contoh.com/?q=sejak%202025 sejak 2025.</p>'
        )
        result = rj.replace_year_in_content(html, 2025, 2026)
        # Every URL, path and attribute keeps 2025.
        self.assertIn('{"url":"https://contoh.com/wp-content/uploads/2025/06/x.jpg"}', result)
        self.assertIn('src="/wp-content/uploads/2025/06/x.jpg"', result)
        self.assertIn('alt="Panduan 2025"', result)
        self.assertIn('srcset="/wp-content/uploads/2025/06/x-300.jpg 300w"', result)
        self.assertIn('href="https://contoh.com/promo-2025/?tahun=2025" title="2025"', result)
        self.assertIn('atau /wp-content/uploads/2025/06/x.jpg dan', result)
        self.assertIn('https://contoh.com/sejak+2025', result)
        self.assertIn('https://contoh.com/?q=sejak%202025', result)
        # Visible text is updated.
        self.assertIn('>Panduan 2026</a>', result)
        self.assertTrue(result.endswith('sejak 2026.</p>'))

    def test_code_blocks_shortcodes_and_numbers_are_untouched(self):
        html = ('<pre>tahun = 2025</pre><code>2025</code><script>var y = 2025;</script>'
                '[gallery ids="2025"] 12025 2025-06 v2025 2025px <p>2025</p>')
        result = rj.replace_year_in_content(html, 2025, 2026)
        self.assertEqual(
            result,
            '<pre>tahun = 2025</pre><code>2025</code><script>var y = 2025;</script>'
            '[gallery ids="2025"] 12025 2025-06 v2025 2025px <p>2026</p>'
        )


class BulkUpdateTaskTests(unittest.TestCase):
    def run_task(self, posts, from_year=2025, to_year=2026):
        site = types.SimpleNamespace(wordpress_url='https://example.com', wordpress_username='a',
                                     wordpress_password='b', site_name='Site', telegram_enabled=False,
                                     telegram_bot_token=None, telegram_chat_id=None)
        session = Mock()
        session.query.return_value.filter_by.return_value.first.return_value = site
        db = Mock()
        db.get_session.return_value.__enter__ = Mock(return_value=session)
        db.get_session.return_value.__exit__ = Mock(return_value=False)
        bot = Mock()
        bot.get_posts.return_value = (True, posts, 1)
        bot.update_post.return_value = (True, {})
        with patch.object(rj, 'db', db), patch.object(rj, 'WordPressPublisher', return_value=bot), \
                patch.object(rj, 'send_telegram_notification', Mock()):
            result = rj.bulk_update_year_task(1, 1, from_year, to_year)
        return bot, result

    def test_updates_title_and_visible_content_only(self):
        bot, result = self.run_task([{
            'id': 1,
            'title': {'raw': 'Panduan 2025'},
            'content': {'raw': '<p>Panduan 2025 <img src="/wp-content/uploads/2025/06/x.jpg"></p>'},
        }])
        bot.update_post.assert_called_once_with(1, {
            'title': 'Panduan 2026',
            'content': '<p>Panduan 2026 <img src="/wp-content/uploads/2025/06/x.jpg"></p>',
        })
        self.assertEqual(result, {'updated': 1})

    def test_year_only_inside_a_title_token_does_not_update(self):
        bot, _ = self.run_task([{'id': 2, 'title': {'raw': 'Model X2025'}, 'content': {'raw': '2025'}}])
        bot.update_post.assert_not_called()

    def test_invalid_years_never_touch_wordpress(self):
        with patch.object(rj, 'WordPressPublisher') as publisher:
            result = rj.bulk_update_year_task(1, 1, '1', '2')
        publisher.assert_not_called()
        self.assertEqual(result['updated'], 0)
        self.assertTrue(result['error'])


if __name__ == '__main__':
    unittest.main()
