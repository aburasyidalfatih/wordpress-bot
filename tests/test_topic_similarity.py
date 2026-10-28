"""Topic cannibalization: services.topic_similarity and its use in the article
job (queue titles, scheduled research topics, generated titles). No network."""
import json
import unittest
from datetime import datetime
from unittest.mock import Mock, patch

from rq.timeouts import JobTimeoutException

from models import ContentQueue, PostLog, ResearchData, User, WordPressSite
from services.article_review import ReviewResult
from services.ai_costs import current_stage
from services.topic_similarity import (
    BORDERLINE_THRESHOLD, CORE_MATCH_SCORE, DEFINITE_THRESHOLD, REASON_AI, REASON_AI_BUDGET, REASON_CORE,
    REASON_CORE_SUBTITLE, REASON_NO_AI, REASON_SCORE, SIMILAR_THRESHOLD, TITLE_MAX_CHARS, TITLE_TARGET_CHARS,
    SimilarMatch, category_words, clean_title, core_signature, core_topic_match, describe_match, drop_core_repeats,
    find_similar_published, propose_distinct_titles, propose_repair_title, restates_category, signatures_match,
    significant_tokens, similarity_score, title_core,
)
from test_article_quality_support import quality_stub_patches
from test_research_backend_support import load_with_stubbed_core, make_db

jobs, _core = load_with_stubbed_core('tasks.article_jobs')


def score(a, b, language):
    return similarity_score(significant_tokens(a, language), significant_tokens(b, language))


class FakeGenerator:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.prompts = []

    def generate_text(self, prompt, system=None, max_tokens=8192):
        self.prompts.append(prompt)
        self.max_tokens = max_tokens
        value = self.replies.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value


class NormalizationTests(unittest.TestCase):
    def test_generic_words_numbers_and_inflections_are_dropped(self):
        self.assertEqual(significant_tokens('Eliminate Family Debt Fast: Ultimate 2026 Household Payoff Guide', 'en'),
                         ['eliminate', 'family', 'debt', 'household', 'payoff'])
        self.assertEqual(significant_tokens('4 Practical Household Payoff Models', 'en'),
                         ['household', 'payoff', 'model'])
        self.assertEqual(significant_tokens('Family Budgeting Basics', 'en'), ['family', 'budget', 'basic'])
        self.assertEqual(significant_tokens('Contoh RAPBS Sekolah dan Cara Menyusunnya', 'id'),
                         ['rapbs', 'sekolah', 'menyusun'])
        # Indonesian words are not run through English plural rules.
        self.assertEqual(significant_tokens('Tugas Kelas', 'id'), ['tugas', 'kelas'])


class ExampleTests(unittest.TestCase):
    def assertSimilar(self, a, b, language):
        self.assertEqual(find_similar_published(a, ['Resep Nasi Goreng', b], language=language)[0], b)

    def assertDistinct(self, a, b, language):
        self.assertIsNone(find_similar_published(a, [b], language=language))

    def test_same_debt_payoff_intent_is_similar(self):
        self.assertSimilar('Eliminate Family Debt Fast: Ultimate 2026 Household Payoff Guide',
                           'Break Free From Debt: 4 Practical Household Payoff Models', 'en')

    def test_same_family_budgeting_intent_is_similar(self):
        self.assertSimilar('From Paycheck Pressure to Peace: Family Budgeting Basics',
                           'Family Budgeting Basics: Reclaim Household Cash Flow in 2026', 'en')

    def test_different_topics_are_distinct(self):
        self.assertDistinct('Emergency Fund Basics', 'Debt Payoff Methods', 'en')
        self.assertEqual(score('Emergency Fund Basics', 'Debt Payoff Methods', 'en'), 0)
        self.assertDistinct('Investasi Emas Jangka Panjang', 'Resep Nasi Goreng', 'id')

    def test_indonesian_near_duplicates_are_similar(self):
        self.assertSimilar('7 Tips Menabung!', 'tips menabung', 'id')
        self.assertSimilar('Cara Menabung untuk Pelajar SMA', 'Cara Menabung untuk Pelajar SMP', 'id')
        self.assertSimilar('Strategi Investasi Emas untuk Pemula', 'Panduan Lengkap Investasi Emas 2026', 'id')
        self.assertSimilar('Cara Mengelola Keuangan Sekolah Swasta',
                           'Manajemen Keuangan Sekolah Swasta yang Efektif', 'id')
        self.assertSimilar('Cara Menyusun RAPBS Sekolah', 'Contoh RAPBS Sekolah Dasar dan Cara Menyusunnya', 'id')

    def test_internal_audit_vs_cash_flow_control_is_distinct(self):
        # Decision: NOT similar. They share only "pengendalian" and the site's
        # niche word "sekolah" and no head phrase: internal audit / financial
        # control and cash-flow control answer different searches.
        a = 'Audit Internal dan Pengendalian Keuangan Sekolah'
        b = 'Panduan Pengendalian Arus Kas Sekolah Swasta'
        self.assertLess(score(a, b, 'id'), BORDERLINE_THRESHOLD)
        self.assertDistinct(a, b, 'id')

    def test_one_shared_word_is_never_enough(self):
        self.assertEqual(score('Best Credit Cards for Students', 'How to Improve Your Credit Score', 'en'), 0)

    def test_site_niche_words_count_less(self):
        # On an elementary-school site "sekolah dasar" is in every title, so
        # sharing it says nothing: school security is not the school canteen.
        title, existing = 'Keamanan Sekolah Dasar', 'Kantin Sekolah Dasar'
        self.assertGreaterEqual(score(title, existing, 'id'), SIMILAR_THRESHOLD)
        self.assertIsNotNone(find_similar_published(title, [existing], language='id'))
        site_titles = [f'{topic} Sekolah Dasar' for topic in
                       ('Kurikulum', 'Seragam', 'Perpustakaan', 'Ekstrakurikuler', 'Guru', 'Rapor', 'Upacara')]
        self.assertIsNone(find_similar_published(title, site_titles + [existing], language='id'))


class CoreTopicTests(unittest.TestCase):
    """The core topic: the framing-free title head (before ':') or whole title."""

    DIGITAL = [
        'Peta Jalan Digitalisasi Pendidikan 2026: Rencana Aksi Sekolah',
        'Panduan Digitalisasi Pendidikan 2026: Rencana Aksi Guru dan Kepala Sekolah',
        'Digitalisasi Pendidikan 2026: Strategi Taktis Kepala Sekolah',
        'Arsitektur Digitalisasi Pendidikan 2026: Blueprint Infrastruktur Sekolah',
        'Digitalisasi Pendidikan 2026 \u2013 Siasat Guru Menghadapi Kelas Hibrida',
    ]

    def test_core_is_the_framing_free_head(self):
        for title in self.DIGITAL:
            self.assertEqual(title_core(title, 'id'), {'digitalisasi', 'pendidikan'}, title)
        self.assertEqual(title_core('Family Budgeting Basics: Teaching Kids About Money', 'en'),
                         {'family', 'budget'})
        # A one-word or framing-only head is not a topic: the whole title is the core.
        self.assertEqual(title_core('Kurikulum: Cara Menyusun Modul Ajar', 'id'),
                         {'kurikulum', 'menyusun', 'modul', 'ajar'})
        self.assertEqual(title_core('Studi Kasus: Digitalisasi Perpustakaan Sekolah', 'id'),
                         {'digitalisasi', 'perpustakaan', 'sekolah'})
        self.assertIsNone(title_core('Panduan Lengkap 2026', 'id'))

    def test_same_head_with_different_framing_is_the_same_topic(self):
        for i, a in enumerate(self.DIGITAL):
            for b in self.DIGITAL[i + 1:]:
                self.assertTrue(core_topic_match(a, b, 'id'), (a, b))
        self.assertTrue(core_topic_match('Family Budgeting Basics: Meal Planning on a Shoestring',
                                         'Family Budgeting Basics: Teaching Kids About Money', 'en'))
        # A title that is only the other's head, or the other's subtitle.
        self.assertTrue(core_topic_match('Digitalisasi Pendidikan 2026', self.DIGITAL[0], 'id'))
        self.assertTrue(core_topic_match('From Paycheck Pressure to Peace: Family Budgeting Basics',
                                         'Family Budgeting Basics: Reclaim Household Cash Flow in 2026', 'en'))

    def test_core_match_beats_niche_weights_and_the_model(self):
        # On a site where every title says "Digitalisasi Pendidikan", the niche
        # weights used to let these through; the model said "different intent".
        site_titles = [f'{topic} di Sekolah Dasar' for topic in
                       ('Kurikulum', 'Seragam', 'Perpustakaan', 'Ekstrakurikuler', 'Rapor', 'Upacara', 'Kantin')]
        generator = FakeGenerator('{"same_intent": false}', '{"same_intent": false}')
        match = find_similar_published(self.DIGITAL[0], site_titles + self.DIGITAL[1:], language='id',
                                       generator=generator)
        self.assertEqual(match[0], self.DIGITAL[1])
        self.assertGreaterEqual(match[1], CORE_MATCH_SCORE)
        self.assertGreater(CORE_MATCH_SCORE, DEFINITE_THRESHOLD)
        self.assertEqual(generator.prompts, [])
        # Same head, clearly different subtitles (a series): the model decides.
        series = ('Family Budgeting Basics: Meal Planning on a Shoestring',
                  ['Family Budgeting Basics: Teaching Kids About Money'])
        self.assertIsNone(find_similar_published(series[0], series[1], language='en',
                                                 generator=FakeGenerator('{"same_intent": false}')))
        match = find_similar_published(series[0], series[1], language='en',
                                       generator=FakeGenerator('{"same_intent": true}'))
        self.assertEqual(match[0], 'Family Budgeting Basics: Teaching Kids About Money')
        # Without a model a shared core is still treated as a repeat.
        self.assertEqual(find_similar_published(series[0], series[1], language='en')[0],
                         'Family Budgeting Basics: Teaching Kids About Money')
        series_id = ('Manajemen Keuangan Sekolah: Menyusun RAPBS', ['Manajemen Keuangan Sekolah: Laporan Dana BOS'])
        self.assertIsNone(find_similar_published(series_id[0], series_id[1], language='id',
                                                 generator=FakeGenerator('{"same_intent": false}')))

    def test_different_intents_in_a_niche_still_pass(self):
        self.assertFalse(core_topic_match('Audit Internal Keuangan Sekolah',
                                          'Pengendalian Arus Kas Sekolah Swasta', 'id'))
        self.assertIsNone(find_similar_published('Audit Internal Keuangan Sekolah',
                                                 ['Pengendalian Arus Kas Sekolah Swasta'], language='id'))
        self.assertFalse(core_topic_match('Studi Kasus: Digitalisasi Perpustakaan Sekolah',
                                          'Studi Kasus: Pengelolaan BOS di Sekolah Swasta', 'id'))
        self.assertFalse(core_topic_match('Siasat Digitalisasi Pendidikan bagi Guru Honorer',
                                          'Literasi Data Guru Sekolah Negeri', 'id'))

    def test_emergency_fund_calculator_vs_where_to_keep_it(self):
        # Decision: different core topics (how much to save vs. where to hold
        # it), so the core check does not decide. The pair stays in the lexical
        # gray zone: the model's same-intent answer decides, and without a model
        # the score still matches it (conservative, as before).
        a, b = 'Emergency Fund Calculator', 'Where to Keep Your Emergency Fund'
        self.assertFalse(core_topic_match(a, b, 'en'))
        self.assertTrue(BORDERLINE_THRESHOLD <= score(a, b, 'en') < DEFINITE_THRESHOLD)
        self.assertIsNone(find_similar_published(a, [b], language='en',
                                                 generator=FakeGenerator('{"same_intent": false}')))
        self.assertIsNotNone(find_similar_published(a, [b], language='en'))

    def test_restating_the_category_head_term(self):
        self.assertTrue(restates_category('Digitalisasi Pendidikan 2026: Literasi Data Guru',
                                          'Digitalisasi Pendidikan', 'id'))
        self.assertTrue(restates_category('Debt Payoff: Snowball vs Avalanche', 'Debt Payoff Strategies', 'en'))
        self.assertFalse(restates_category('Literasi Data Guru dalam Digitalisasi Pendidikan',
                                           'Digitalisasi Pendidikan', 'id'))
        self.assertFalse(restates_category('Tips Hemat Listrik', 'Tips', 'id'))  # one-word category

    def test_drop_core_repeats(self):
        candidates = ['Digitalisasi Pendidikan 2026: Literasi Data Guru',
                      {'topic': 'digitalisasi pendidikan adalah'},
                      'Family Budgeting Basics: Meal Planning',
                      'Literasi Data Guru dalam Digitalisasi Pendidikan',
                      'Literasi Data Guru dalam Digitalisasi Pendidikan 2026',
                      'Cara Mengajar Coding di SD', '']
        kept, dropped = drop_core_repeats(candidates, ['Family Budgeting Basics: Teaching Kids'],
                                          language='id', category='Digitalisasi Pendidikan')
        self.assertEqual(kept, ['Literasi Data Guru dalam Digitalisasi Pendidikan', 'Cara Mengajar Coding di SD'])
        self.assertEqual(len(dropped), 5)


class AIConfirmationTests(unittest.TestCase):
    # "family budget basic" vs "family vacation plan budget": borderline.
    CANDIDATE = 'Family Budgeting Basics'
    PUBLISHED = ['Family Vacation Planning on a Budget']

    def test_borderline_is_confirmed_by_the_model(self):
        self.assertTrue(BORDERLINE_THRESHOLD <= score(self.CANDIDATE, self.PUBLISHED[0], 'en') < SIMILAR_THRESHOLD)
        generator = FakeGenerator('```json\n{"same_intent": true}\n```')
        match = find_similar_published(self.CANDIDATE, self.PUBLISHED, language='en', generator=generator)
        self.assertEqual(match[0], self.PUBLISHED[0])
        self.assertIn('Title A: Family Budgeting Basics', generator.prompts[0])
        # Room for Gemini's thinking tokens, which count against the output limit.
        self.assertEqual(generator.max_tokens, 4096)

    def test_failed_check_logs_the_fallback(self):
        with self.assertLogs('services.topic_similarity', level='WARNING') as logs:
            find_similar_published(self.CANDIDATE, self.PUBLISHED, language='en', generator=FakeGenerator(''))
        self.assertTrue(any('falling back to the score' in line for line in logs.output))

    def test_rq_job_timeout_is_not_swallowed(self):
        with self.assertRaises(JobTimeoutException):
            find_similar_published(self.CANDIDATE, self.PUBLISHED, language='en',
                                   generator=FakeGenerator(JobTimeoutException('job timeout')))

    def test_borderline_rejected_by_the_model_or_failing_check_is_distinct(self):
        for answer in ('{"same_intent": false}', 'no idea', ConnectionError('down')):
            with self.subTest(answer=answer):
                generator = FakeGenerator(answer)
                self.assertIsNone(find_similar_published(self.CANDIDATE, self.PUBLISHED, language='en',
                                                         generator=generator))
                self.assertEqual(len(generator.prompts), 1)
        self.assertIsNone(find_similar_published(self.CANDIDATE, self.PUBLISHED, language='en'))

    def test_model_decides_the_gray_zone_and_score_is_the_fallback(self):
        candidate = 'Eliminate Family Debt Fast: Ultimate 2026 Household Payoff Guide'
        published = ['Break Free From Debt: 4 Practical Household Payoff Models']
        self.assertTrue(SIMILAR_THRESHOLD <= score(candidate, published[0], 'en') < DEFINITE_THRESHOLD)
        self.assertIsNone(find_similar_published(candidate, published, language='en',
                                                 generator=FakeGenerator('{"same_intent": false}')))
        self.assertIsNotNone(find_similar_published(candidate, published, language='en',
                                                    generator=FakeGenerator(RuntimeError('quota'))))

    def test_model_confirmations_are_capped(self):
        published = ['Family Vacation Planning on a Budget', 'Family Budget Vacation Plans',
                     'Budget Family Vacation Planner']
        generator = FakeGenerator('{"same_intent": false}', '{"same_intent": false}')
        self.assertIsNone(find_similar_published(self.CANDIDATE, published, language='en', generator=generator))
        self.assertEqual(len(generator.prompts), 2)

    def test_clear_cases_skip_the_model(self):
        generator = FakeGenerator()
        self.assertIsNotNone(find_similar_published('Tips Menabung', ['tips menabung'], language='id',
                                                    generator=generator))
        self.assertIsNone(find_similar_published('Resep Rendang', ['Investasi Emas'], language='id',
                                                 generator=generator))
        self.assertEqual(generator.prompts, [])


class CategoryTests(unittest.TestCase):
    """Words of the category name are context, not evidence of a repeat."""

    CATEGORY = 'Couples and Money Management'
    CANDIDATE = 'Couples and Money Management: What to Disclose and Sign'
    PUBLISHED = 'Best Couple Money Management Apps 2026: Ditch Spreadsheets'

    def test_category_words_are_stemmed_like_titles(self):
        self.assertEqual(category_words(self.CATEGORY, 'en'), {'couple', 'money', 'management'})
        self.assertEqual(category_words(None, 'en'), frozenset())

    def test_production_pair_is_distinct_within_its_category(self):
        # Without the category the shared category words alone put the pair in
        # the gray zone (0.66): no model, so the score threshold decided.
        match = find_similar_published(self.CANDIDATE, [self.PUBLISHED], language='en')
        self.assertEqual(match, (self.PUBLISHED, 0.66))
        self.assertEqual(match.reason, REASON_NO_AI)
        self.assertFalse(core_topic_match(self.CANDIDATE, self.PUBLISHED, 'en', category=self.CATEGORY))
        tokens = (significant_tokens(self.CANDIDATE, 'en'), significant_tokens(self.PUBLISHED, 'en'))
        weighted = similarity_score(*tokens, category_words=category_words(self.CATEGORY, 'en'))
        self.assertLess(weighted, BORDERLINE_THRESHOLD)
        self.assertLess(weighted, similarity_score(*tokens))
        self.assertIsNone(find_similar_published(self.CANDIDATE, [self.PUBLISHED], language='en',
                                                 category=self.CATEGORY))
        generator = FakeGenerator('{"same_intent": false}')
        self.assertIsNone(find_similar_published(self.CANDIDATE, [self.PUBLISHED], language='en',
                                                 generator=generator, category=self.CATEGORY))
        self.assertEqual(generator.prompts, [])  # clear case now: no model call needed

    def test_model_saying_different_intent_clears_the_pair(self):
        generator = FakeGenerator('{"same_intent": false}')
        self.assertIsNone(find_similar_published(self.CANDIDATE, [self.PUBLISHED], language='en',
                                                 generator=generator))
        self.assertEqual(len(generator.prompts), 1)

    def test_true_duplicates_in_the_category_still_match(self):
        match = find_similar_published('Couple Money Management Apps: Pick the Right One', [self.PUBLISHED],
                                       language='en', category=self.CATEGORY)
        self.assertEqual(match[0], self.PUBLISHED)
        self.assertEqual(match.reason, REASON_CORE)
        # A reworded title on the same sub-question.
        match = find_similar_published('Couples and Money Management: What to Disclose Before Signing',
                                       [self.CANDIDATE], language='en', category=self.CATEGORY)
        self.assertEqual(match[0], self.CANDIDATE)

    def test_core_made_of_category_words_alone_is_not_a_core_match(self):
        # Decision: in category "Family Budgeting Basics" the shared head only
        # restates the category. Clearly different subtitles are different
        # articles of the category (no model needed); without the category the
        # shared head is still a repeat (CoreTopicTests).
        a = 'Family Budgeting Basics: Meal Planning on a Shoestring'
        b = 'Family Budgeting Basics: Teaching Kids About Money'
        category = 'Family Budgeting Basics'
        self.assertTrue(core_topic_match(a, b, 'en'))
        self.assertFalse(core_topic_match(a, b, 'en', category=category))
        words = category_words(category, 'en')
        self.assertFalse(signatures_match(core_signature(a, 'en'), core_signature(b, 'en'), words))
        self.assertTrue(signatures_match(core_signature(a, 'en'), core_signature(b, 'en')))
        generator = FakeGenerator()
        self.assertIsNone(find_similar_published(a, [b], language='en', generator=generator, category=category))
        self.assertEqual(generator.prompts, [])
        self.assertIsNotNone(find_similar_published(a, [b], language='en'))
        # The same subtitle under the category head is still a repeat.
        match = find_similar_published('Family Budgeting Basics: Teaching Your Kids About Money', [b],
                                       language='en', category=category)
        self.assertEqual(match[0], b)

    def test_repeated_category_head_is_caught_through_the_subtitle(self):
        a = 'Peta Jalan Digitalisasi Pendidikan 2026: Rencana Aksi Sekolah'
        b = 'Panduan Digitalisasi Pendidikan: Rencana Aksi Pasca Ruang GTK'
        generator = FakeGenerator()
        match = find_similar_published(a, ['Resep Nasi Goreng', b], language='id', generator=generator,
                                       category='Digitalisasi Pendidikan')
        self.assertEqual(match[0], b)
        self.assertEqual(match.reason, REASON_CORE_SUBTITLE)
        self.assertGreaterEqual(match[1], CORE_MATCH_SCORE)
        self.assertEqual(generator.prompts, [])
        self.assertTrue(core_topic_match(a, b, 'id', category='Digitalisasi Pendidikan'))

    def test_drop_core_repeats_ignores_a_core_shared_only_through_the_category(self):
        candidates = ['What to Disclose Before Marriage: Couples and Money Management']
        existing = ['Couples and Money Management: Best Budgeting Apps']
        self.assertEqual(drop_core_repeats(candidates, existing, language='en')[0], [])
        kept, dropped = drop_core_repeats(candidates, existing, language='en', category=self.CATEGORY)
        self.assertEqual((kept, dropped), (candidates, []))
        # Restating the category itself is still dropped.
        self.assertEqual(drop_core_repeats([self.CANDIDATE], [], language='en', category=self.CATEGORY)[0], [])

    def test_same_intent_prompt_judges_search_intent(self):
        generator = FakeGenerator('{"same_intent": false}')
        find_similar_published(self.CANDIDATE, [self.PUBLISHED], language='en', generator=generator)
        prompt = generator.prompts[0]
        self.assertIn('fully satisfied by the other article', prompt)
        self.assertIn('Different sub-questions within the same niche are DIFFERENT intents', prompt)
        self.assertIn('strict JSON only', prompt)
        self.assertNotIn("site's category", prompt)
        # A gray-zone pair within the category: the model is told the category
        # words are no evidence.
        generator = FakeGenerator('{"same_intent": true}')
        match = find_similar_published('Couples and Money Management: Joint Account Rules for Newlyweds',
                                       ['Joint Bank Accounts for Newlyweds: Pros and Cons'], language='en',
                                       generator=generator, category=self.CATEGORY)
        self.assertIn('category "Couples and Money Management"', generator.prompts[0])
        self.assertIn('not evidence of the same intent', generator.prompts[0])
        self.assertEqual(match.reason, REASON_AI)


class MatchReasonTests(unittest.TestCase):
    CANDIDATE = 'Couples and Money Management: What to Disclose and Sign'
    PUBLISHED = ['Best Couple Money Management Apps 2026: Ditch Spreadsheets']

    def test_match_unpacks_like_the_old_tuple(self):
        match = find_similar_published('Tips Menabung', ['tips menabung'], language='id')
        title, value = match
        self.assertEqual((title, value), ('tips menabung', 1.0))
        self.assertEqual(match, ('tips menabung', 1.0))
        self.assertEqual((match.title, match.score, match.reason), ('tips menabung', 1.0, REASON_SCORE))

    def test_reasons_are_described_in_indonesian(self):
        cases = [
            (None, 'skor 0,66; tanpa cek AI, memakai ambang skor'),
            (FakeGenerator(RuntimeError('quota')), 'skor 0,66; AI tidak tersedia, memakai ambang skor'),
            (FakeGenerator('{"same_intent": true}'), 'skor 0,66; AI menilai topiknya sama'),
        ]
        for generator, expected in cases:
            with self.subTest(expected=expected):
                match = find_similar_published(self.CANDIDATE, self.PUBLISHED, language='en', generator=generator)
                self.assertEqual(describe_match(match), expected)
        self.assertIsNone(describe_match(('x', 0.9)))
        self.assertIsNone(describe_match(None))
        self.assertEqual(SimilarMatch('x', 0.9, REASON_CORE).describe(), 'skor 0,90; inti topik judulnya sama')

    def test_spent_model_budget_is_reported(self):
        published = ['Family Budget Vacation Ideas', 'Family Budget Vacation Plans', 'Vacation Family Budget Plans']
        generator = FakeGenerator('{"same_intent": false}', '{"same_intent": false}')
        match = find_similar_published('Family Budgeting Basics', published, language='en', generator=generator)
        self.assertEqual(len(generator.prompts), 2)
        self.assertEqual(match.reason, REASON_AI_BUDGET)
        self.assertIn('batas cek AI tercapai', match.describe())

    def test_match_reason_is_logged(self):
        with self.assertLogs('services.topic_similarity', level='INFO') as logs:
            find_similar_published(self.CANDIDATE, self.PUBLISHED, language='en')
        self.assertTrue(any('reason=no_ai score=0.660' in line for line in logs.output))


class TitleProposalTests(unittest.TestCase):
    def test_clean_title(self):
        self.assertEqual(clean_title('  "Judul: **Dana Darurat** untuk Keluarga"  '), 'Dana Darurat untuk Keluarga')
        self.assertEqual(clean_title('<b>Dana Darurat</b> https://spam.example/x'), 'Dana Darurat')
        long_title = 'Dana darurat keluarga muda yang baru menikah dan tinggal di kota besar tanpa warisan'
        self.assertEqual(clean_title(long_title), '')
        trimmed = clean_title(long_title, trim=True)
        self.assertLessEqual(len(trimmed), TITLE_MAX_CHARS)
        self.assertTrue(long_title.startswith(trimmed))
        self.assertEqual(clean_title(None), '')

    def test_distinct_titles_are_parsed_cleaned_and_capped(self):
        generator = FakeGenerator(json.dumps({'titles': [
            {'title': 'Household Debt Payoff Plan', 'angle': 'same as planned'},
            {'title': '"Emergency Fund Basics: How Much to Save"', 'angle': 'Size of the fund'},
            {'title': 'Emergency Fund Basics: How Much to Save'},
            'Where to Keep an Emergency Fund',
            {'title': 'Sinking Funds for Car Repairs', 'angle': 'Saving ahead for known costs'},
        ]}))
        titles = propose_distinct_titles(generator, 'Emergency Fund Basics', 'Household Debt Payoff Plan',
                                         ['Break Free From Debt', 'Other'], language='en', category='Finance',
                                         angle='Pay off debt faster')
        self.assertEqual([t['title'] for t in titles],
                         ['Emergency Fund Basics: How Much to Save', 'Where to Keep an Emergency Fund',
                          'Sinking Funds for Car Repairs'])
        self.assertEqual(titles[0]['angle'], 'Size of the fund')
        prompt = generator.prompts[0]
        self.assertIn('3 alternative working titles', prompt)
        self.assertIn('- Break Free From Debt', prompt)
        self.assertIn('Site category: "Finance"', prompt)
        self.assertIn('PLANNED ANGLE: Pay off debt faster', prompt)
        self.assertGreaterEqual(generator.max_tokens, 4096)  # room for Gemini's thinking tokens

    def test_failed_proposal_call_gives_no_titles(self):
        for reply in ('bukan json', ConnectionError('down'), '{"titles": "x"}'):
            with self.subTest(reply=reply):
                self.assertEqual(propose_distinct_titles(FakeGenerator(reply), 't', 'x', ['y']), [])
        with self.assertRaises(JobTimeoutException):
            propose_distinct_titles(FakeGenerator(JobTimeoutException('timeout')), 't', 'x', ['y'])

    def test_repair_title_sees_headings_and_excerpt(self):
        article = {'title': 'Household Debt Payoff: Break Free Faster', 'focus_keyword': 'debt payoff',
                   'content': '<h2>How big should it be?</h2><p>x</p><h2 id="a">Where to <b>keep</b> it</h2>',
                   'excerpt': 'How much to keep in an emergency fund.'}
        generator = FakeGenerator('{"title": "Emergency Fund Size: How Much to Save", "focus_keyword": "emergency fund"}')
        proposal = propose_repair_title(generator, article, 'Break Free From Debt', language='en', category='Finance')
        self.assertEqual(proposal, {'title': 'Emergency Fund Size: How Much to Save', 'focus_keyword': 'emergency fund'})
        prompt = generator.prompts[0]
        self.assertIn('- How big should it be?', prompt)
        self.assertIn('- Where to keep it', prompt)
        self.assertIn('Excerpt: How much to keep in an emergency fund.', prompt)
        self.assertIn('PUBLISHED TITLE TO STAY DISTINCT FROM: Break Free From Debt', prompt)
        self.assertIn(f'at most {TITLE_TARGET_CHARS} characters', prompt)
        self.assertGreaterEqual(generator.max_tokens, 4096)

    def test_unusable_repair_title_is_none(self):
        article = {'title': 'Household Debt Payoff', 'content': '<h2>A</h2>'}
        too_long = 'x' * (TITLE_MAX_CHARS + 1)
        for reply in ('{"title": "Household Debt Payoff"}', json.dumps({'title': too_long}), 'no json',
                      ConnectionError('down')):
            with self.subTest(reply=reply):
                self.assertIsNone(propose_repair_title(FakeGenerator(reply), article, 'Published'))


class JobSimilarityTestCase(unittest.TestCase):
    TOPICS = ['Eliminate Family Debt Fast: Ultimate 2026 Household Payoff Guide', 'Emergency Fund Basics']
    PUBLISHED = 'Break Free From Debt: 4 Practical Household Payoff Models'

    def setUp(self):
        self.db = make_db()
        now = datetime.now()
        with self.db.get_session() as s:
            s.add(User(id=1, email='u@example.com', credits=10))
            s.add(WordPressSite(
                id=1, user_id=1, site_name='Site', wordpress_url='https://example.com',
                wordpress_username='admin', auto_post=True, language='en',
                categories=[{'id': 7, 'name': 'Finance'}],
                selected_categories=[{'id': 7, 'name': 'Finance'}],
            ))
            s.add(ResearchData(id=1, user_id=1, site_id=1, category='Finance',
                               suggested_topics=[{'topic': t} for t in self.TOPICS],
                               confidence_level='high', researched_at=now, created_at=now))
            s.add(PostLog(user_id=1, site_id=1, category_name='Finance', title=self.PUBLISHED,
                          success=True, result='ok', created_at=now))
        self.generator = Mock()
        # Small model calls, routed by prompt. Scripted replies per kind; by
        # default gray-zone title pairs are confirmed (same intent) and the
        # title proposals are unusable.
        self.replies = {}
        self.prompts = []  # (kind, prompt)
        self.stages = []  # (kind, cost stage the call was made in)

        def generate_text(prompt, *args, **kwargs):
            kind = ('alternatives' if 'alternative working titles' in prompt
                    else 'repair' if 'Propose a new title' in prompt else 'same_intent')
            self.prompts.append((kind, prompt))
            self.stages.append((kind, current_stage()))
            if self.replies.get(kind):
                return self.replies[kind].pop(0)
            return json.dumps({'same_intent': True}) if kind == 'same_intent' else 'no json'
        self.generator.generate_text.side_effect = generate_text
        self.generator.generate_checked_article.side_effect = lambda *a, **k: {
            'title': 'Emergency Fund Basics: How Much to Save', 'content': '<p>x</p>'}
        self.generator.generate_image.return_value = None
        self.publisher = Mock()
        self.publisher.get_recent_posts.return_value = []
        self.publisher.create_post.return_value = (True, {'id': 1, 'link': 'https://example.com/p'})
        patches = [
            patch.object(jobs, 'db', self.db),
            patch.object(jobs, 'load_config', Mock(return_value={})),
            patch.object(jobs, 'ArticleGenerator', Mock(**{'from_config.return_value': self.generator})),
            patch.object(jobs, 'WordPressPublisher', Mock(return_value=self.publisher)),
            patch.object(jobs, 'check_article', Mock(return_value=(True, [], []))),
            patch.object(jobs, '_merge_topic_research', lambda seo, *a, **k: seo),
            patch.object(jobs, 'load_search_metrics', Mock(return_value=([], []))),
            patch.object(jobs, '_current_job', lambda: None),
            patch.object(jobs, 'review_article', Mock(return_value=ReviewResult('approve', 'ok'))),
        ]
        patches += quality_stub_patches(jobs)
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def credits(self):
        with self.db.get_session() as s:
            return s.get(User, 1).credits

    def topics_left(self):
        with self.db.get_session() as s:
            return [t['topic'] for t in s.get(ResearchData, 1).suggested_topics]

    def last_log(self):
        with self.db.get_session() as s:
            log = s.query(PostLog).order_by(PostLog.id.desc()).first()
            s.expunge(log)
            return log

    def post(self):
        jobs.generate_and_post(1, site_id=1, credit_pre_reserved=True, manual=True)

    def generation_call(self, index=0):
        return self.generator.generate_checked_article.call_args_list[index]

    def calls(self):
        """Kinds of the small model calls made so far."""
        return [kind for kind, _ in self.prompts]


class ScheduledTopicTests(JobSimilarityTestCase):
    def test_similar_research_topic_is_consumed_and_the_next_one_used(self):
        self.post()
        self.assertEqual(self.generation_call().args[2], 'Emergency Fund Basics')
        self.assertEqual(self.topics_left(), [])  # skipped topic consumed, used topic spent
        self.assertTrue(self.last_log().success)
        # A distinct topic is written normally, not as an "avoid similar" rewrite.
        self.assertNotIn('avoid_similar', self.generation_call().kwargs)

    def test_all_topics_similar_falls_back_to_category_avoiding_them(self):
        with self.db.get_session() as s:
            s.get(ResearchData, 1).suggested_topics = [
                {'topic': 'Eliminate Family Debt Fast: Household Payoff Guide'},
                {'topic': 'Household Debt Payoff Plan'},
                {'topic': 'Debt Payoff for the Household'},
                {'topic': 'Emergency Fund Basics'},
            ]
        self.post()
        call = self.generation_call()
        self.assertIsNone(call.args[2])  # category article, no topic
        self.assertTrue(call.kwargs['avoid_similar'])
        self.assertEqual(call.args[1][-1], self.PUBLISHED)  # most important title listed last
        self.assertEqual(self.topics_left(), ['Emergency Fund Basics'])  # only MAX_TOPIC_CLAIMS tried

    def test_failure_after_skipping_still_returns_the_used_topic(self):
        self.publisher.create_post.return_value = (False, 'HTTP 502')
        self.post()
        self.assertEqual(self.topics_left(), ['Emergency Fund Basics'])

    def test_similar_generated_title_is_regenerated_then_fails(self):
        with self.db.get_session() as s:
            s.get(ResearchData, 1).suggested_topics = [{'topic': 'Emergency Fund Basics'}]
        self.generator.generate_checked_article.side_effect = lambda *a, **k: {
            'title': 'Household Debt Payoff: Break Free Faster', 'content': '<p>x</p>'}
        self.post()
        # The title repair came first (its reply is unusable here), then the
        # full regeneration.
        self.assertEqual(self.calls().count('repair'), 1)
        self.assertIn(('repair', 'cek kemiripan'), self.stages)
        calls = self.generator.generate_checked_article.call_args_list
        self.assertEqual(len(calls), 2)
        self.assertTrue(calls[1].kwargs['avoid_similar'])
        self.assertEqual(calls[1].args[1][-1], self.PUBLISHED)
        self.publisher.create_post.assert_not_called()
        self.assertEqual(self.credits(), 11)
        self.assertEqual(self.last_log().result,
                         f"Artikel tidak diterbitkan: Topik terlalu mirip dengan artikel yang sudah terbit: "
                         f"'{self.PUBLISHED}' (skor 1,00; kata-kata judulnya hampir sama)")
        self.assertEqual(self.topics_left(), [])  # content failure: topic consumed


class QueueItemSimilarityTests(JobSimilarityTestCase):
    def add_item(self, title):
        with self.db.get_session() as s:
            s.add(ContentQueue(id=5, user_id=1, site_id=1, category='Finance', title=title,
                               status='posting', credit_held=True))

    def item(self):
        with self.db.get_session() as s:
            item = s.get(ContentQueue, 5)
            s.expunge(item)
            return item

    def test_queue_title_repeating_a_published_article_fails_with_refund(self):
        self.add_item('Eliminate Family Debt Fast: Ultimate 2026 Household Payoff Guide')
        jobs.generate_and_post(1, item_id=5, credit_pre_reserved=True)
        self.generator.generate_checked_article.assert_not_called()
        self.assertEqual(self.item().status, 'failed')
        self.assertFalse(self.item().credit_held)
        self.assertEqual(self.credits(), 11)
        log = self.last_log()
        self.assertFalse(log.success)
        self.assertEqual(log.title, 'GAGAL: Eliminate Family Debt Fast: Ultimate 2026 Household Payoff Guide')
        self.assertEqual(log.result, "Artikel tidak diterbitkan: Topik terlalu mirip dengan artikel yang sudah "
                                     f"terbit: '{self.PUBLISHED}' (skor 0,68; AI menilai topiknya sama)")

    def test_recent_wordpress_posts_count_as_published(self):
        self.publisher.get_recent_posts.return_value = [
            {'title': 'Emergency Fund Basics &amp; Beyond', 'url': 'https://example.com/ef'}]
        self.add_item('Emergency Fund Basics')
        jobs.generate_and_post(1, item_id=5, credit_pre_reserved=True)
        self.assertEqual(self.item().status, 'failed')

    def test_distinct_queue_title_is_published(self):
        self.add_item('Emergency Fund Basics')
        jobs.generate_and_post(1, item_id=5, credit_pre_reserved=True)
        self.assertEqual(self.item().status, 'posted')
        self.assertEqual(self.generation_call().args[2], 'Emergency Fund Basics')


class PreWritingTitleTests(JobSimilarityTestCase):
    """The brief's working title is checked before any article is written."""

    SIMILAR = 'Household Debt Payoff: Break Free Faster'
    DISTINCT = 'Emergency Fund Basics: How Much to Save'

    def setUp(self):
        super().setUp()
        with self.db.get_session() as s:
            s.get(ResearchData, 1).suggested_topics = [{'topic': 'Emergency Fund Basics'}]

    def post_with_working_title(self, working_title):
        brief = {'working_title': working_title, 'search_intent': 'Know how much to save.',
                 'must_answer': ['How much is enough?'], 'angle': 'Planned angle', 'avoid': ['Filler']}
        with patch.object(jobs, 'build_content_brief', Mock(return_value=brief)):
            self.post()

    def brief_text(self):
        return self.generation_call().kwargs['content_brief']

    def test_distinct_working_title_reaches_the_writer(self):
        self.post_with_working_title(self.DISTINCT)
        self.assertEqual(self.generator.generate_checked_article.call_count, 1)
        self.assertIn(f'- Working title: {self.DISTINCT} (keep the article and its final title on this angle',
                      self.brief_text())
        self.assertNotIn('alternatives', self.calls())
        self.assertTrue(self.last_log().success)

    def test_similar_working_title_moves_to_a_distinct_angle(self):
        self.replies['alternatives'] = [json.dumps({'titles': [
            {'title': 'Household Debt Payoff Models Compared', 'angle': 'Still about debt payoff'},
            {'title': self.DISTINCT, 'angle': 'How big the emergency fund should be'},
            {'title': 'Never used', 'angle': 'x'},
        ]})]
        self.post_with_working_title(self.SIMILAR)
        self.assertEqual(self.generator.generate_checked_article.call_count, 1)
        self.assertNotIn('avoid_similar', self.generation_call().kwargs)
        text = self.brief_text()
        self.assertIn(f'- Working title: {self.DISTINCT}', text)
        self.assertNotIn(self.SIMILAR, text)
        self.assertIn('- Angle: How big the emergency fund should be', text)
        self.assertIn(f"Repeating the intent of the published article '{self.PUBLISHED}'", text)
        # One small call for the alternatives, accounted to the similarity stage.
        self.assertEqual(self.calls().count('alternatives'), 1)
        self.assertIn(('alternatives', 'cek kemiripan'), self.stages)
        alternatives_prompt = next(p for kind, p in self.prompts if kind == 'alternatives')
        self.assertIn(f'PLANNED TITLE (too similar): {self.SIMILAR}', alternatives_prompt)
        self.assertIn(f'PUBLISHED TITLES TO STAY DISTINCT FROM (most important first):\n- {self.PUBLISHED}',
                      alternatives_prompt)
        self.assertTrue(self.last_log().success)

    def test_no_distinct_angle_fails_before_writing(self):
        for reply in (json.dumps({'titles': [{'title': 'Household Debt Payoff Models Compared'},
                                             {'title': 'Debt Payoff for the Household'}]}), 'no json'):
            with self.subTest(reply=reply):
                self.replies['alternatives'] = [reply]
                credits = self.credits()
                self.post_with_working_title(self.SIMILAR)
                self.generator.generate_checked_article.assert_not_called()
                self.generator.generate_image.assert_not_called()
                self.publisher.create_post.assert_not_called()
                self.assertEqual(self.credits(), credits + 1)  # the pre-reserved credit is refunded
                log = self.last_log()
                self.assertFalse(log.success)
                self.assertEqual(log.title, f'GAGAL: {self.SIMILAR}')
                self.assertEqual(log.result, "Artikel tidak diterbitkan: Topik terlalu mirip dengan artikel yang "
                                             f"sudah terbit: '{self.PUBLISHED}' (skor 1,00; kata-kata judulnya "
                                             "hampir sama)")

    def test_every_similarity_check_gets_the_category(self):
        seen = []
        real = jobs.find_similar_published

        def spy(*args, **kwargs):
            seen.append(kwargs.get('category'))
            return real(*args, **kwargs)
        with patch.object(jobs, 'find_similar_published', spy):
            self.post_with_working_title(self.DISTINCT)
        self.assertGreaterEqual(len(seen), 3)  # research topic, working title, generated title
        self.assertEqual(set(seen), {'Finance'})


class TitleRepairTests(JobSimilarityTestCase):
    """A written article whose title repeats a published one gets a new title first."""

    REPEATING = 'Household Debt Payoff: Break Free Faster'
    REPAIRED = 'Emergency Fund Basics: How Much to Save'

    def setUp(self):
        super().setUp()
        with self.db.get_session() as s:
            s.get(ResearchData, 1).suggested_topics = [{'topic': 'Emergency Fund Basics'}]
        self.articles = [self.article(self.REPEATING)]
        self.generator.generate_checked_article.side_effect = lambda *a, **k: dict(self.articles.pop(0))

    def article(self, title):
        return {'title': title, 'focus_keyword': 'debt payoff',
                'meta_description': f'{title}: a plan for the money you need for surprises.',
                'excerpt': 'How much to keep in an emergency fund.',
                'content': '<p>An emergency fund covers surprises.</p><h2>How much is enough?</h2><p>x</p>'
                           '<h2>Where to keep it</h2><p>y</p>'}

    def test_repaired_title_is_published_without_regenerating(self):
        self.replies['repair'] = [json.dumps({'title': self.REPAIRED, 'focus_keyword': 'emergency fund'})]
        self.post()
        self.assertEqual(self.generator.generate_checked_article.call_count, 1)
        args = self.publisher.create_post.call_args.args
        self.assertEqual(args[0], self.REPAIRED)
        self.assertEqual(args[4], f'{self.REPAIRED}: a plan for the money you need for surprises.')
        self.assertEqual(args[6], 'emergency fund')  # old keyword not in the new title; new one is in the text
        self.assertEqual(self.calls().count('repair'), 1)
        self.assertIn(('repair', 'cek kemiripan'), self.stages)
        repair_prompt = next(p for kind, p in self.prompts if kind == 'repair')
        self.assertIn('- How much is enough?', repair_prompt)
        self.assertIn('Excerpt: How much to keep in an emergency fund.', repair_prompt)
        self.assertIn(f'PUBLISHED TITLE TO STAY DISTINCT FROM: {self.PUBLISHED}', repair_prompt)
        self.assertTrue(self.last_log().success)
        self.assertEqual(self.last_log().title, self.REPAIRED)

    def test_repair_still_similar_falls_back_to_regeneration(self):
        self.replies['repair'] = [json.dumps({'title': 'Household Debt Payoff Models Compared'})]
        self.articles.append(self.article(self.REPAIRED))
        self.post()
        calls = self.generator.generate_checked_article.call_args_list
        self.assertEqual(len(calls), 2)
        self.assertTrue(calls[1].kwargs['avoid_similar'])
        self.assertEqual(self.publisher.create_post.call_args.args[0], self.REPAIRED)
        self.assertEqual(self.calls().count('repair'), 1)  # no second repair after the regeneration


class TopicTooSimilarMessageTests(unittest.TestCase):
    def test_reason_in_the_history_message(self):
        error = jobs.TopicTooSimilar('Judul Lama', reason='skor 0,66; AI tidak tersedia, memakai ambang skor')
        self.assertEqual(str(error), "Topik terlalu mirip dengan artikel yang sudah terbit: 'Judul Lama' "
                                     "(skor 0,66; AI tidak tersedia, memakai ambang skor)")
        match = find_similar_published('Couples and Money Management: What to Disclose and Sign',
                                       ['Best Couple Money Management Apps 2026: Ditch Spreadsheets'], language='en',
                                       generator=FakeGenerator('{"same_intent": true}'))
        self.assertEqual(str(jobs.TopicTooSimilar.from_match(match)),
                         "Topik terlalu mirip dengan artikel yang sudah terbit: 'Best Couple Money Management Apps "
                         "2026: Ditch Spreadsheets' (skor 0,66; AI menilai topiknya sama)")
        # A plain (title, score) tuple (patched in tests) has no reason.
        self.assertEqual(str(jobs.TopicTooSimilar.from_match(('Judul', 0.9))),
                         "Topik terlalu mirip dengan artikel yang sudah terbit: 'Judul'")


if __name__ == '__main__':
    unittest.main()
