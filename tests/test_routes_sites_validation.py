import importlib
import sys
import types
import unittest
from unittest.mock import patch


def load_sites_module():
    """Import routes.sites with its heavy dependencies stubbed out."""
    core = types.ModuleType('core_extensions')
    core.db = None
    core.logger = None
    core.require_jwt = lambda f: f
    core.send_telegram_notification = lambda *a, **k: False
    publisher = types.ModuleType('services.wp_publisher')
    publisher.WordPressPublisher = object
    stubs = {'core_extensions': core, 'services.wp_publisher': publisher}
    with patch.dict(sys.modules, stubs):
        sys.modules.pop('routes.sites', None)
        module = importlib.import_module('routes.sites')
    sys.modules.pop('routes.sites', None)
    return module


sites = load_sites_module()


class ScheduleHoursTests(unittest.TestCase):
    def test_string_and_list_are_normalized(self):
        self.assertEqual(sites._clean_schedule_hours('18, 0,6 ,6'), '0,6,18')
        self.assertEqual(sites._clean_schedule_hours([12, 3]), '3,12')

    def test_blank_falls_back_to_default_and_hh00_is_read(self):
        self.assertEqual(sites._clean_schedule_hours(''), sites.DEFAULT_SCHEDULE_HOURS)
        self.assertEqual(sites._clean_schedule_hours(' , '), sites.DEFAULT_SCHEDULE_HOURS)
        self.assertEqual(sites._clean_schedule_hours('07:00, 18'), '7,18')

    def test_invalid_values_are_rejected(self):
        for value in ('24', '-1', 'a,b', '07:30', [], [True], ['6'], {'h': 1}, 7):
            with self.assertRaises(sites._InvalidField, msg=repr(value)):
                sites._clean_schedule_hours(value)


class CategoryListTests(unittest.TestCase):
    def test_dedupes_by_id_and_drops_unknown_keys(self):
        # Same-named categories under different parents are distinct (by id).
        cleaned = sites._clean_category_list([
            {'id': 1, 'name': ' News ', 'count': 3, 'evil': 'x'},
            {'id': 2, 'name': 'News'},
            {'id': 1, 'name': 'News again'},
            {'id': 3, 'name': 'Tips', 'description': 'd'},
        ], 50, 'selected_categories')
        self.assertEqual(cleaned, [
            {'id': 1, 'name': 'News', 'description': '', 'count': 3},
            {'id': 2, 'name': 'News', 'description': '', 'count': 0},
            {'id': 3, 'name': 'Tips', 'description': 'd', 'count': 0},
        ])

    def test_malformed_entries_are_rejected(self):
        for value in ('News', [{'id': '1', 'name': 'x'}], [{'id': 1, 'name': ''}],
                      [{'id': 1}], ['News'], [{'id': True, 'name': 'x'}]):
            with self.assertRaises(sites._InvalidField, msg=repr(value)):
                sites._clean_category_list(value, 50, 'selected_categories')

    def test_length_cap(self):
        too_many = [{'id': i, 'name': f'c{i}'} for i in range(51)]
        with self.assertRaises(sites._InvalidField):
            sites._clean_category_list(too_many, 50, 'selected_categories')


class CategoryHintTests(unittest.TestCase):
    """Private per-category AI hints live in the `categories` JSON, not in WordPress."""

    def test_hints_are_kept_for_categories_only(self):
        value = [{'id': 1, 'name': 'Tips', 'ai_hint': '  Fokus guru SD.  '}, {'id': 2, 'name': 'News'}]
        self.assertEqual(sites._clean_category_list(value, 50, 'categories', keep_hints=True), [
            {'id': 1, 'name': 'Tips', 'description': '', 'count': 0, 'ai_hint': 'Fokus guru SD.'},
            {'id': 2, 'name': 'News', 'description': '', 'count': 0},
        ])
        # Selected categories never carry them.
        self.assertNotIn('ai_hint', sites._clean_category_list(value, 50, 'selected_categories')[0])
        cleaned = sites._clean_site_update({'categories': value, 'selected_categories': value})
        self.assertEqual(cleaned['categories'][0]['ai_hint'], 'Fokus guru SD.')
        self.assertNotIn('ai_hint', cleaned['selected_categories'][0])

    def test_invalid_hints_are_rejected(self):
        for hint in (5, ['x'], 'x' * (sites.MAX_CATEGORY_HINT_CHARS + 1)):
            with self.assertRaises(sites._InvalidField, msg=repr(hint)):
                sites._clean_category_list([{'id': 1, 'name': 'Tips', 'ai_hint': hint}], 50, 'categories',
                                           keep_hints=True)

    def test_stored_hints_survive_updates_without_them_and_category_refresh(self):
        stored = [{'id': 1, 'name': 'Tips', 'ai_hint': 'Fokus guru SD.'}, {'id': 2, 'name': 'News', 'ai_hint': 'x'}]
        # A client (or the WordPress category refresh) that does not send the hint keeps it.
        fresh = [{'id': 1, 'name': 'Tips & Trik', 'description': 'baru', 'count': 4}, {'id': 3, 'name': 'Baru'}]
        self.assertEqual(sites._keep_stored_hints(fresh, stored), [
            {'id': 1, 'name': 'Tips & Trik', 'description': 'baru', 'count': 4, 'ai_hint': 'Fokus guru SD.'},
            {'id': 3, 'name': 'Baru'},
        ])
        # An empty hint sent on purpose clears it.
        self.assertEqual(sites._keep_stored_hints([{'id': 1, 'name': 'Tips', 'ai_hint': ''}], stored),
                         [{'id': 1, 'name': 'Tips'}])
        self.assertEqual(sites._keep_stored_hints([{'id': 2, 'name': 'News', 'ai_hint': 'baru'}], stored),
                         [{'id': 2, 'name': 'News', 'ai_hint': 'baru'}])
        self.assertEqual(sites._keep_stored_hints(fresh[1:], None), [{'id': 3, 'name': 'Baru'}])


class ScalarFieldTests(unittest.TestCase):
    def test_clean_str(self):
        self.assertIsNone(sites._clean_str({'k': None}, 'k', 10))
        self.assertIsNone(sites._clean_str({'k': '  '}, 'k', 10))
        self.assertEqual(sites._clean_str({'k': ' a '}, 'k', 10), 'a')
        with self.assertRaises(sites._InvalidField):
            sites._clean_str({'k': 5}, 'k', 10)
        with self.assertRaises(sites._InvalidField):
            sites._clean_str({'k': 'x' * 11}, 'k', 10)
        with self.assertRaises(sites._InvalidField):
            sites._clean_str({'k': ''}, 'k', 10, allow_empty=False)

    def test_clean_bool_and_timezone(self):
        self.assertTrue(sites._clean_bool({'k': True}, 'k'))
        with self.assertRaises(sites._InvalidField):
            sites._clean_bool({'k': 'true'}, 'k')
        self.assertEqual(sites._clean_timezone('Asia/Jakarta'), 'Asia/Jakarta')
        with self.assertRaises(sites._InvalidField):
            sites._clean_timezone('Not/AZone')


if __name__ == '__main__':
    unittest.main()
