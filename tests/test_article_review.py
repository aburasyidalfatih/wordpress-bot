"""AI editorial review (services.article_review): parsing, edit application,
verdict flows, reviewer failures and YMYL detection. No network calls: the
generator is a fake whose generate_text replies are scripted."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from rq.timeouts import JobTimeoutException

from services import article_review as review
from services.ai_providers import AIProviderError, TextResult
from services.article_generator import ArticleGenerator, TruncatedGenerationError
from services.article_review import (
    ArticleReviewRejected, ArticleReviewUnavailable, ProtectedLinks, ReviewParseError, apply_edits,
    build_publisher_context, build_review_evidence, extract_json_object, is_ymyl_topic, parse_review_response,
    review_article,
)


class FakeGenerator:
    """generate_text returns (or raises) the scripted replies in order."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def generate_text(self, prompt, system=None, max_tokens=8192, raise_on_truncation=False):
        self.calls.append({'prompt': prompt, 'system': system, 'max_tokens': max_tokens,
                           'raise_on_truncation': raise_on_truncation})
        reply = self.replies.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        return reply if isinstance(reply, str) else json.dumps(reply)


def make_article():
    return {
        'title': 'Rahasia Ultimate Lunas Utang dalam 7 Hari',
        'meta_description': 'Cara melunasi utang keluarga dengan langkah yang realistis dan aman untuk dicoba.',
        'focus_keyword': 'melunasi utang',
        'excerpt': 'Panduan melunasi utang keluarga.',
        'content': ('<h2>Mulai dari daftar utang</h2><p>Menurut survei kami, 87% keluarga berhasil lunas.</p>'
                    '<p>Catat semua utang.</p><p>Catat semua utang.</p>'
                    '<h2>Pilih metode</h2><p>Metode bola salju membayar saldo terkecil lebih dulu.</p>'),
        'key_takeaways': ['Catat semua utang', 'Bayar saldo terkecil dulu'],
        'faqs': [{'question': 'Berapa lama?', 'answer': 'Dijamin lunas dalam 7 hari.'}],
    }


def edit(find, replace='', critical=True, reason='alasan'):
    return {'find': find, 'replace': replace, 'reason': reason, 'critical': critical}


class ParseTests(unittest.TestCase):
    def test_plain_json(self):
        decision = parse_review_response('{"verdict": "approve", "summary": "Baik", "edits": []}')
        self.assertEqual((decision.verdict, decision.summary, decision.edits), ('approve', 'Baik', []))

    def test_code_fence_and_prose_are_tolerated(self):
        reply = ('Berikut hasil tinjauan:\n```json\n{"verdict": "Revise", "summary": "x", "edits": '
                 '[{"find": "a {b} c", "replace": "d", "reason": "r"}], "title": "  "}\n```\nSelesai.')
        decision = parse_review_response(reply)
        self.assertEqual(decision.verdict, 'revise')
        self.assertEqual(decision.edits[0]['find'], 'a {b} c')
        self.assertTrue(decision.edits[0]['critical'])  # missing flag counts as critical
        self.assertIsNone(decision.title)  # blank title means "no change"

    def test_first_object_wins_and_brace_prose_is_skipped(self):
        self.assertEqual(extract_json_object('pakai {kurung} lalu {"a": 1} dan {"b": 2}'), {'a': 1})

    def test_malformed_edits_are_dropped(self):
        decision = parse_review_response(json.dumps({'verdict': 'revise', 'edits': [
            'not a dict', {'find': ''}, {'find': 'ok', 'replace': None, 'critical': False}]}))
        self.assertEqual(decision.edits, [{'find': 'ok', 'replace': '', 'reason': '', 'critical': False}])

    def test_unusable_replies_raise(self):
        for reply in ('', 'tidak ada json', '{"verdict": "maybe"}', '[1, 2]', '{"verdict": "approve"'):
            with self.subTest(reply=reply), self.assertRaises(ReviewParseError):
                parse_review_response(reply)


class ApplyEditsTests(unittest.TestCase):
    def test_unique_find_is_applied(self):
        article = make_article()
        result = apply_edits(article, [edit('Menurut survei kami, 87% keluarga berhasil lunas.',
                                            'Banyak keluarga berhasil lunas dengan disiplin.')])
        self.assertEqual(result, (1, 0, 1, 0))
        self.assertIn('Banyak keluarga berhasil lunas', article['content'])
        self.assertNotIn('87%', article['content'])

    def test_missing_and_duplicate_finds_are_skipped(self):
        article = make_article()
        before = article['content']
        result = apply_edits(article, [edit('teks yang tidak ada'), edit('<p>Catat semua utang.</p>', '')])
        self.assertEqual(result, (0, 2, 2, 2))
        self.assertEqual(article['content'], before)

    def test_find_counted_across_all_published_fields(self):
        article = make_article()
        # "Catat semua utang" is in the content (twice) and in a takeaway.
        self.assertEqual(apply_edits(article, [edit('Catat semua utang', 'x')])[1], 1)
        applied = apply_edits(article, [edit('Dijamin lunas dalam 7 hari.', '<b>Tergantung</b> kondisi Anda.')])
        self.assertEqual(applied[0], 1)
        self.assertEqual(article['faqs'][0]['answer'], 'Tergantung kondisi Anda.')  # no HTML outside content

    def test_unsafe_replacements_are_skipped(self):
        article = make_article()
        result = apply_edits(article, [
            edit('<p>Catat semua utang.</p><h2>', '<script>alert(1)</script><h2>'),
            edit('Metode bola salju', '<a href="https://evil.example">Metode</a> bola salju', critical=False),
        ])
        self.assertEqual(result, (0, 2, 1, 1))
        self.assertNotIn('script', article['content'])
        self.assertNotIn('evil.example', article['content'])


class ReviewFlowTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(review, 'RETRY_DELAY_SECONDS', 0)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_review(self, generator, article=None, **kwargs):
        article = article or make_article()
        options = dict(language='id', category='Keuangan', site_name='Situs')
        options.update(kwargs)
        return article, review_article(generator, article, 'EVIDENCE-TEXT', **options)

    def test_approve_without_edits_leaves_article_alone(self):
        generator = FakeGenerator({'verdict': 'approve', 'summary': 'Akurat', 'edits': []})
        article, result = self.run_review(generator, category='Hobi', site_name='Blog', ymyl=False)
        self.assertEqual(article, make_article())
        self.assertFalse(result.changed)
        self.assertEqual((result.verdict, result.rounds), ('approve', 1))
        self.assertEqual(result.note, 'Ditinjau AI: disetujui tanpa perbaikan isi.')
        self.assertEqual(len(generator.calls), 1)
        self.assertEqual(generator.calls[0]['max_tokens'], review.REVIEW_MAX_TOKENS)

    def test_prompt_frames_article_and_evidence_as_data(self):
        generator = FakeGenerator({'verdict': 'approve', 'summary': 'ok'})
        self.run_review(generator)
        prompt, system = generator.calls[0]['prompt'], generator.calls[0]['system']
        self.assertIn('untrusted data', system)
        self.assertRegex(prompt, r'<<<ARTICLE (\w+)>>>[\s\S]*Menurut survei kami[\s\S]*<<<END ARTICLE \1>>>')
        self.assertRegex(prompt, r'<<<EVIDENCE (\w+)>>>\nEVIDENCE-TEXT\n<<<END EVIDENCE \1>>>')
        self.assertIn('YMYL topic', prompt)  # Keuangan is a money topic

    def test_revise_applies_edits_title_meta_and_disclaimer(self):
        generator = FakeGenerator({
            'verdict': 'revise', 'summary': 'Statistik tanpa sumber dihapus',
            'edits': [edit('Menurut survei kami, 87% keluarga berhasil lunas.', 'Banyak keluarga bisa lunas.'),
                      edit('Dijamin lunas dalam 7 hari.', 'Lamanya tergantung jumlah utang.')],
            'title': 'Cara Realistis Melunasi Utang Keluarga',
            'meta_description': 'Langkah realistis melunasi utang keluarga: daftar utang, pilih metode, dan jaga arus kas.',
            'disclaimer': 'Informasi ini bersifat umum dan bukan nasihat keuangan.',
        })
        article, result = self.run_review(generator)
        self.assertEqual((result.applied, result.skipped, result.rounds), (2, 0, 1))
        self.assertTrue(result.title_changed and result.meta_changed and result.disclaimer_added)
        self.assertEqual(article['title'], 'Cara Realistis Melunasi Utang Keluarga')
        self.assertTrue(article['content'].endswith(
            '<p><em>Informasi ini bersifat umum dan bukan nasihat keuangan.</em></p>'))
        self.assertEqual(result.note, 'Ditinjau AI: 2 perbaikan diterapkan, judul disesuaikan, '
                                      'meta description disesuaikan, catatan disclaimer ditambahkan.')

    def test_disclaimer_only_for_ymyl_and_only_once(self):
        reply = {'verdict': 'approve', 'disclaimer': 'Ini bukan nasihat keuangan.'}
        article, result = self.run_review(FakeGenerator(reply), category='Hobi', site_name='Blog', ymyl=False)
        self.assertFalse(result.disclaimer_added)
        self.assertNotIn('nasihat', article['content'])
        existing = make_article()
        existing['content'] += '<p>Informasi umum, bukan nasihat keuangan.</p>'
        _, result = self.run_review(FakeGenerator(reply), article=existing)
        self.assertFalse(result.disclaimer_added)

    def test_unapplied_critical_edit_triggers_second_round(self):
        generator = FakeGenerator(
            {'verdict': 'revise', 'summary': 'r1', 'edits': [
                edit('Menurut survei kami, 87% keluarga berhasil lunas.', 'Banyak keluarga bisa lunas.'),
                edit('kutipan yang salah salin', 'x')]},
            {'verdict': 'approve', 'summary': 'r2', 'edits': []},
        )
        article, result = self.run_review(generator)
        self.assertEqual((result.rounds, result.applied, result.skipped, result.verdict), (2, 1, 1, 'approve'))
        self.assertIn('SECOND REVIEW', generator.calls[1]['prompt'])
        # The second round reviews the already edited text.
        self.assertIn('Banyak keluarga bisa lunas.', generator.calls[1]['prompt'])
        self.assertIn('Banyak keluarga bisa lunas.', article['content'])

    def test_unappliable_edits_after_two_rounds_reject(self):
        bad = {'verdict': 'revise', 'summary': 'klaim palsu', 'edits': [edit('tidak ada 1'), edit('tidak ada 2')]}
        generator = FakeGenerator(bad, bad)
        article = make_article()
        with self.assertRaises(ArticleReviewRejected) as caught:
            self.run_review(generator, article=article)
        self.assertIn('2 dari 2 perbaikan penting tidak dapat diterapkan', str(caught.exception))
        self.assertEqual(article, make_article())  # nothing applied on rejection
        self.assertEqual(len(generator.calls), 2)

    def test_approve_with_an_unapplied_critical_edit_is_reviewed_again(self):
        generator = FakeGenerator(
            {'verdict': 'approve', 'edits': [edit('salah salin', 'x')]},
            {'verdict': 'approve', 'edits': []},
        )
        _, result = self.run_review(generator)
        self.assertEqual(result.rounds, 2)

    def test_any_critical_edit_left_after_the_last_round_rejects(self):
        first = {'verdict': 'approve', 'edits': [edit('salah salin', 'x')]}
        # Two of three critical edits apply in round 2, one does not: still rejected.
        second = {'verdict': 'revise', 'edits': [
            edit('Menurut survei kami, 87% keluarga berhasil lunas.', 'Banyak keluarga bisa lunas.'),
            edit('Dijamin lunas dalam 7 hari.', 'Lamanya tergantung kondisi.'),
            edit('tidak ada', 'x')]}
        with self.assertRaises(ArticleReviewRejected) as caught:
            self.run_review(FakeGenerator(first, second))
        self.assertIn('1 dari 3 perbaikan penting tidak dapat diterapkan', str(caught.exception))

    def test_minor_edits_never_trigger_a_second_round(self):
        generator = FakeGenerator({'verdict': 'revise', 'edits': [edit('tidak ada', critical=False)]})
        _, result = self.run_review(generator)
        self.assertEqual((result.rounds, result.skipped), (1, 1))

    def test_reject_raises_with_indonesian_reasons(self):
        generator = FakeGenerator({'verdict': 'reject', 'summary': 'Isi sebagian besar karangan',
                                   'edits': [edit('Menurut survei kami', '', reason='Survei fiktif')]})
        article = make_article()
        with self.assertRaises(ArticleReviewRejected) as caught:
            self.run_review(generator, article=article)
        self.assertEqual(str(caught.exception),
                         'Artikel ditolak peninjau AI: Isi sebagian besar karangan; Survei fiktif')
        self.assertEqual(caught.exception.article_title, 'Rahasia Ultimate Lunas Utang dalam 7 Hari')
        self.assertEqual(article, make_article())


class ReviewerFailureTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(review, 'RETRY_DELAY_SECONDS', 0)
        patcher.start()
        self.addCleanup(patcher.stop)

    def review(self, generator):
        return review_article(generator, make_article(), '', language='id', category='Keuangan', site_name='S')

    def test_transient_failure_is_retried_once(self):
        generator = FakeGenerator(ConnectionError('reset'), {'verdict': 'approve'})
        self.assertEqual(self.review(generator).verdict, 'approve')
        self.assertEqual(len(generator.calls), 2)

    def test_persistent_transient_failure_means_no_review_and_no_publish(self):
        generator = FakeGenerator(TimeoutError('slow'), ConnectionError('reset'))
        with self.assertRaises(ArticleReviewUnavailable) as caught:
            self.review(generator)
        self.assertIn('tidak diterbitkan tanpa ditinjau', str(caught.exception))
        self.assertEqual(len(generator.calls), 2)

    def test_unparseable_reply_is_retried_then_fails_safely(self):
        generator = FakeGenerator('Artikel ini bagus!', 'masih bukan json')
        with self.assertRaises(ArticleReviewUnavailable):
            self.review(generator)
        self.assertEqual(len(generator.calls), 2)

    def test_configuration_errors_fail_immediately(self):
        for error in (AIProviderError('API key Claude belum diatur di Panel Admin.'), ValueError('bad request')):
            with self.subTest(error=error):
                generator = FakeGenerator(error)
                with self.assertRaises(ArticleReviewUnavailable):
                    self.review(generator)
                self.assertEqual(len(generator.calls), 1)

    def test_safety_refusal_rejects_the_article(self):
        generator = FakeGenerator(AIProviderError('Claude menolak membuat konten ini.'))
        with self.assertRaises(ArticleReviewRejected):
            self.review(generator)

    def test_review_budget_and_truncation(self):
        generator = FakeGenerator(TruncatedGenerationError('cut'), {'verdict': 'approve'})
        self.assertEqual(self.review(generator).verdict, 'approve')
        self.assertEqual(generator.calls[0]['max_tokens'], 16384)
        self.assertTrue(generator.calls[0]['raise_on_truncation'])

    def test_persistent_truncation_is_unavailable_with_indonesian_message(self):
        generator = FakeGenerator(TruncatedGenerationError('cut'), TruncatedGenerationError('cut'))
        with self.assertRaises(ArticleReviewUnavailable) as caught:
            self.review(generator)
        self.assertIn('jawaban peninjau AI terpotong karena mencapai batas 16384 token', str(caught.exception))
        self.assertEqual(len(generator.calls), 2)

    def test_rq_job_timeout_is_not_swallowed(self):
        with self.assertRaises(JobTimeoutException):
            self.review(FakeGenerator(JobTimeoutException('job timeout')))


class GenerateTextTruncationTests(unittest.TestCase):
    def generator(self, truncated):
        text = SimpleNamespace(generate=lambda *a, **k: TextResult('{"verdict": "app', truncated), model='m')
        return ArticleGenerator(text)

    def test_truncation_surfaces_only_when_asked(self):
        self.assertEqual(self.generator(True).generate_text('p'), '{"verdict": "app')
        with self.assertRaises(TruncatedGenerationError):
            self.generator(True).generate_text('p', raise_on_truncation=True)
        self.assertEqual(self.generator(False).generate_text('p', raise_on_truncation=True), '{"verdict": "app')


class ProtectedLinkAndContextTests(unittest.TestCase):
    CONTENT = ('<h2>A</h2><p>Lihat <a href="https://www.example.com/lama/">pos lama</a>, '
               '<a href="https://partner.example/promo?a=1&amp;b=2">promo</a> dan '
               '<a href="https://sumber.id/x">sumber</a>.</p>')

    def test_protected_hosts_and_urls(self):
        links = ProtectedLinks(['example.com', 'https://partner.example/promo?a=1&b=2', '', 'not a host'])
        self.assertTrue(links.covers('http://example.com/apa-saja'))
        self.assertTrue(links.covers('https://partner.example/promo?a=1&amp;b=2'))
        self.assertFalse(links.covers('https://sumber.id/x'))
        self.assertEqual(links.describe(), '- example.com (every page on this domain)\n'
                                           '- partner.example/promo?a=1&b=2')

    def test_edits_removing_protected_links_are_ignored_not_counted(self):
        article = {'content': self.CONTENT}
        links = ProtectedLinks(['example.com', 'https://partner.example/promo?a=1&b=2'])
        result = apply_edits(article, [
            edit('<a href="https://www.example.com/lama/">pos lama</a>', 'pos lama'),
            edit('<a href="https://partner.example/promo?a=1&amp;b=2">promo</a>', 'promo'),
            edit('<a href="https://sumber.id/x">sumber</a>', 'sumber'),
        ], links)
        self.assertEqual(result, (1, 2, 1, 0))
        self.assertIn('href="https://www.example.com/lama/"', article['content'])
        self.assertIn('href="https://partner.example/promo?a=1&amp;b=2"', article['content'])
        self.assertNotIn('sumber.id', article['content'])

    def test_prompt_carries_publisher_context_and_protected_links(self):
        generator = FakeGenerator({'verdict': 'approve'})
        context = build_publisher_context('Kami buka 08.00-17.00. ' * 400, 'Kategori untuk orang tua siswa.')
        self.assertLess(len(context), review.MAX_PUBLISHER_CONTEXT_CHARS + 200)
        review_article(generator, make_article(), '', language='id', category='Hobi', site_name='S', ymyl=False,
                       publisher_context=context, protected_links=['example.com'])
        prompt, system = generator.calls[0]['prompt'], generator.calls[0]['system']
        self.assertRegex(prompt, r'<<<PUBLISHER CONTEXT (\w+)>>>\n\[Category description\]\n'
                                 r'Kategori untuk orang tua siswa\.[\s\S]*Kami buka[\s\S]*<<<END PUBLISHER CONTEXT \1>>>')
        self.assertIn('- example.com (every page on this domain)', prompt)
        self.assertIn('NEVER remove or change links covered by\n  ALWAYS-ALLOWED LINKS', prompt)
        self.assertIn('PUBLISHER CONTEXT block is written by the site owner', system)
        self.assertEqual(build_publisher_context(None, '  '), '')


class EditSanitizationTests(unittest.TestCase):
    def test_event_handler_and_dangerous_tag_variants_are_refused(self):
        for replace in ('<svg/onload=alert(1)>', '<a href=x/onclick=alert(1)>x</a>', '<meta http-equiv=refresh>',
                        '<base href="https://evil">', '<link rel=stylesheet href=x>', '<frame src=x>',
                        '<image href=x>', '<object data=x>', '<embed src=x>', '<form action=x>', '<style>',
                        '<p style="x" onmouseover="y">t</p>', '<a href="java\tscript:alert(1)">x</a>'):
            with self.subTest(replace=replace):
                article = make_article()
                applied = apply_edits(article, [edit('Metode bola salju', replace)])
                self.assertEqual(applied[0], 0)

    def test_plain_text_fields_cannot_receive_live_markup(self):
        article = make_article()
        apply_edits(article, [edit('Panduan melunasi utang keluarga.', '&lt;script&gt;alert(1)&lt;/script&gt;Aman')])
        self.assertNotIn('<', article['excerpt'])
        self.assertNotIn('script>', article['excerpt'])
        article = make_article()
        generator = FakeGenerator({'verdict': 'approve', 'title': '&lt;b&gt;Judul&lt;/b&gt; Baru'})
        review_article(generator, article, '', language='id', category='Hobi', site_name='S', ymyl=False)
        self.assertEqual(article['title'], 'Judul Baru')


class YmylAndEvidenceTests(unittest.TestCase):
    def test_ymyl_detection(self):
        for texts in (('Keuangan',), ('Blog', 'Family Budgeting Basics'), ('Kesehatan Anak',),
                      ('Tips', 'Situs Hukum Kita'), ('Investing for beginners',), ('Pajak UMKM',),
                      ('Debt payoff',), ('Asuransi mobil',)):
            with self.subTest(texts=texts):
                self.assertTrue(is_ymyl_topic(*texts))
        for texts in (('Resep Masakan', 'Dapur Kita'), ('Sekolah', 'Kegiatan Siswa'), ('Lawn care',),
                      ('Taxonomy of birds',), (None, '')):
            with self.subTest(texts=texts):
                self.assertFalse(is_ymyl_topic(*texts))

    def test_evidence_is_the_writer_research_plus_source_urls(self):
        seo_data = {
            'keywords': ['dana darurat keluarga'],
            'semantic_context': 'Dana darurat adalah tabungan untuk kebutuhan mendesak.',
            'competitor_outlines': [{'title': 'Panduan Dana Darurat', 'url': 'https://contoh.id/dana',
                                     'headers': ['Berapa idealnya']}],
            'news_insights': [{'title': 'Berita', 'url': 'javascript:alert(1)'}],
        }
        evidence = build_review_evidence(seo_data, 'id')
        self.assertIn('dana darurat keluarga', evidence)
        self.assertIn('tabungan untuk kebutuhan mendesak', evidence)
        self.assertIn('- https://contoh.id/dana', evidence)
        self.assertNotIn('javascript:', evidence)
        self.assertEqual(build_review_evidence(None), '')

    def test_missing_evidence_tightens_the_prompt(self):
        generator = FakeGenerator({'verdict': 'approve'})
        review_article(generator, make_article(), {}, language='en', category='Hobby', site_name='S', ymyl=False)
        prompt = generator.calls[0]['prompt']
        self.assertIn('No research evidence was given to the writer', prompt)
        self.assertIn('must be written in English', prompt)
        self.assertNotIn('YMYL topic', prompt)


if __name__ == '__main__':
    unittest.main()
