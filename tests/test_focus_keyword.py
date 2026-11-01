"""The focus keyword of a topic article is never just the category name."""
import unittest

from services.article_generator import choose_focus_keyword

CATEGORY = 'Couples and Money Management'
TITLE = 'The Weekly Budget Meeting for Couples: A 15-Minute Format'


class ChooseFocusKeywordTest(unittest.TestCase):
    def test_keeps_a_specific_keyword(self):
        article = {'title': TITLE, 'focus_keyword': 'weekly budget meeting'}
        self.assertEqual(choose_focus_keyword(article, CATEGORY), 'weekly budget meeting')

    def test_keeps_the_category_when_the_title_targets_it(self):
        article = {'title': 'Couples and Money Management: A Repair Guide', 'focus_keyword': CATEGORY}
        self.assertEqual(choose_focus_keyword(article, CATEGORY), CATEGORY)

    def test_prefers_a_researched_keyword_in_the_title(self):
        article = {'title': TITLE, 'focus_keyword': 'couples and money management'}
        seo = {'keywords': [{'keyword': CATEGORY}, {'keyword': 'budget meeting for couples'}],
               'long_tail_keywords': ['weekly money date']}
        self.assertEqual(choose_focus_keyword(article, CATEGORY, seo), 'budget meeting for couples')

    def test_falls_back_to_the_title_lead_phrase(self):
        article = {'title': TITLE, 'focus_keyword': CATEGORY}
        self.assertEqual(choose_focus_keyword(article, CATEGORY, {'keywords': [CATEGORY]}),
                         'weekly budget meeting for couples')

    def test_leading_number_is_dropped(self):
        article = {'title': '5 Budgeting Mistakes New Parents Make and How to Fix Them', 'focus_keyword': ''}
        # Lead phrase is too long: nothing better than the category.
        self.assertEqual(choose_focus_keyword(article, 'Family Budgeting Basics'), 'Family Budgeting Basics')
        article = {'title': '5 Budgeting Mistakes: A Guide', 'focus_keyword': 'family budgeting basics'}
        self.assertEqual(choose_focus_keyword(article, 'Family Budgeting Basics'), 'budgeting mistakes')


if __name__ == '__main__':
    unittest.main()
