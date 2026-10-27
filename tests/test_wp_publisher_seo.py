"""WordPress payload: no AutoWP JSON-LD, visible FAQ, SEO plugin meta and short slugs."""
import unittest
from datetime import datetime, timezone
from io import BytesIO
from unittest.mock import Mock, patch

import requests

from services import wp_publisher
from services.wp_publisher import MAX_SLUG_CHARS, MAX_SLUG_WORDS, WordPressPublisher, make_post_slug


def response(status, body=None):
    resp = Mock(status_code=status, headers={}, text=str(body), is_redirect=False)
    resp.json.return_value = body
    return resp


class PublisherTestCase(unittest.TestCase):
    def setUp(self):
        p = patch.object(wp_publisher, '_validate_url', lambda url: (True, url.rstrip('/')))
        p.start()
        self.addCleanup(p.stop)
        sleep = patch('time.sleep')
        sleep.start()
        self.addCleanup(sleep.stop)
        self.publisher = WordPressPublisher('https://example.com', 'admin', 'pw', site_name='Situs')


class PayloadTests(PublisherTestCase):
    FAQS = [{'question': 'Apa itu <anggaran>?', 'answer': 'Rencana & catatan.'},
            {'question': 'Tanpa jawaban'}]

    def payload(self, **kwargs):
        args = dict(title='Family Budgeting Basics: Reclaim Household Cash Flow in 2026',
                    content='<h2>A</h2><p>Isi</p>', meta_description='Deskripsi meta.',
                    focus_keyword='family budgeting basics', key_takeaways=['Poin satu'], faqs=self.FAQS,
                    author_name='Penulis')
        args.update(kwargs)
        return self.publisher._prepare_post_payload(**args)

    def test_no_json_ld_is_injected(self):
        post_data, _ = self.payload()
        self.assertNotIn('application/ld+json', post_data['content'])
        self.assertNotIn('FAQPage', post_data['content'])
        self.assertNotIn('BlogPosting', post_data['content'])
        self.assertNotIn('<script', post_data['content'])
        self.assertFalse(hasattr(wp_publisher, '_faq_schema'))
        self.assertFalse(hasattr(WordPressPublisher, '_structured_data_script'))

    def test_seo_plugin_meta_is_still_set(self):
        post_data, meta = self.payload()
        self.assertEqual(meta, {
            '_yoast_wpseo_metadesc': 'Deskripsi meta.', 'rank_math_description': 'Deskripsi meta.',
            '_yoast_wpseo_focuskw': 'family budgeting basics',
            'rank_math_focus_keyword': 'family budgeting basics',
        })
        self.assertEqual(post_data['meta'], meta)

    def test_takeaways_box_follows_site_language_and_is_escaped(self):
        content = self.payload(key_takeaways=['Pakai <b>anggaran</b>'])[0]['content']
        self.assertIn('Poin penting', content)
        self.assertIn('Pakai &lt;b&gt;anggaran&lt;/b&gt;', content)
        self.assertNotIn('✨', content)
        self.publisher.language = 'en'
        self.assertIn('Key takeaways', self.payload()[0]['content'])
        self.assertNotIn('key-takeaways', self.payload(key_takeaways=['  '])[0]['content'])

    def test_faqs_are_visible_and_escaped(self):
        content = self.payload()[0]['content']
        self.assertIn('<h2>FAQ</h2>', content)
        self.assertIn('<h3>Apa itu &lt;anggaran&gt;?</h3>', content)
        self.assertIn('<p>Rencana &amp; catatan.</p>', content)
        self.assertNotIn('Tanpa jawaban', content)
        self.assertTrue(content.rstrip().endswith('</p>'))

    def test_no_faq_section_without_faqs(self):
        for faqs in (None, [], [{'question': 'Q?', 'answer': ''}], ['bukan dict']):
            self.assertNotIn('<h2>FAQ</h2>', self.payload(faqs=faqs)[0]['content'], repr(faqs))

    def test_new_post_gets_the_short_slug(self):
        self.assertEqual(self.payload()[0]['slug'], 'family-budgeting-basics')

    def test_update_keeps_the_existing_slug(self):
        with patch.object(wp_publisher.requests, 'request', return_value=response(200, {'id': 5})) as req:
            ok, _ = self.publisher.update_post_content(5, 'Judul Baru 2026', '<p>x</p>', focus_keyword='judul baru')
        self.assertTrue(ok)
        sent = req.call_args_list[0].kwargs['json']
        self.assertNotIn('slug', sent)
        self.assertNotIn('application/ld+json', sent['content'])


class SlugTests(unittest.TestCase):
    def test_focus_keyword_preferred(self):
        self.assertEqual(make_post_slug('Family Budgeting Basics: Reclaim Household Cash Flow in 2026',
                                        'family budgeting basics'), 'family-budgeting-basics')
        self.assertEqual(make_post_slug('Menghitung PPh 21 Karyawan: Panduan Praktis', 'PPh 21 karyawan'),
                         'pph-21-karyawan')

    def test_title_used_when_keyword_is_not_descriptive_or_not_in_title(self):
        title = 'Family Budgeting Basics: Reclaim Household Cash Flow in 2026'
        self.assertEqual(make_post_slug(title, 'budgeting'), 'family-budgeting-basics-reclaim-household-cash-flow')
        self.assertEqual(make_post_slug(title, None), 'family-budgeting-basics-reclaim-household-cash-flow')
        # A generic fallback keyword (the category name) must not become every post's slug.
        self.assertEqual(make_post_slug('Cara Menabung untuk Dana Darurat', 'Keuangan Keluarga'),
                         'cara-menabung-untuk-dana-darurat')

    def test_no_dangling_stopwords_or_years(self):
        cases = {
            'Family Budgeting Basics: Reclaim Household Cash Flow in 2026': '-in',
            'The Best Budget Apps for 2026': '-for',
            'Tips Hemat Belanja Bulanan di 2026': '-di',
            'Cara Menabung untuk 2026': '-untuk',
            'Panduan Investasi Reksa Dana bagi Pemula dan': '-dan',
        }
        for title, bad_end in cases.items():
            slug = make_post_slug(title)
            self.assertFalse(slug.endswith(bad_end), (title, slug))
            self.assertNotRegex(slug, r'(^|-)20\d\d(-|$)')
            self.assertNotRegex(slug, r'^(the|a|di|ke)-')
        self.assertEqual(make_post_slug('The Best Budget Apps for 2026'), 'best-budget-apps')
        self.assertEqual(make_post_slug('7 Cara Menabung 2026'), 'cara-menabung')

    def test_long_indonesian_title_is_capped_on_a_word_boundary(self):
        title = ('Panduan Lengkap Mengelola Keuangan Keluarga untuk Pemula di Tengah Kenaikan Harga '
                 'Bahan Pokok dan Biaya Pendidikan Anak Tahun 2026')
        slug = make_post_slug(title)
        self.assertLessEqual(len(slug), MAX_SLUG_CHARS)
        self.assertLessEqual(len(slug.split('-')), MAX_SLUG_WORDS)
        self.assertTrue(slug.startswith('panduan-lengkap-mengelola-keuangan-keluarga'))
        self.assertFalse(slug.endswith(('-untuk', '-di', '-dan')))
        for word in slug.split('-'):
            self.assertIn(word, title.lower())

    def test_accents_punctuation_and_empty(self):
        self.assertEqual(make_post_slug('Crème Brûlée: Don’t Burn It!', None), 'creme-brulee-dont-burn-it')
        self.assertEqual(make_post_slug('2026', '2026'), '')
        self.assertEqual(make_post_slug('', None), '')


class CategorySlugTests(unittest.TestCase):
    """Slugs found by the SEO audit: equal to the category, or a bare head term."""

    def test_keyword_equal_to_category_falls_back_to_title(self):
        cases = [
            # (title, focus keyword, category) -> the slug must not be the category's
            ('Digitalisasi Pendidikan 2026: Rencana Aksi Sekolah Negeri', 'digitalisasi pendidikan',
             'Digitalisasi Pendidikan', 'digitalisasi-pendidikan-rencana-aksi-sekolah-negeri'),
            ('Pembelajaran Abad 21: Contoh Proyek Kolaboratif', 'Pembelajaran Abad 21', 'Pembelajaran Abad 21',
             'pembelajaran-abad-21-contoh-proyek-kolaboratif'),
            ('Debt Payoff Strategies: Snowball or Avalanche for Families', 'debt payoff strategies',
             'Debt Payoff Strategies', 'debt-payoff-strategies-snowball-or-avalanche-for-families'),
            ('Couple Money Management: Splitting Bills Fairly', 'couple money management',
             'Couple Money Management', 'couple-money-management-splitting-bills-fairly'),
        ]
        for title, keyword, category, expected in cases:
            slug = make_post_slug(title, keyword, category)
            self.assertEqual(slug, expected, title)
            self.assertNotEqual(slug, '-'.join(category.lower().split()))

    def test_keyword_contained_in_category_or_too_short_is_rejected(self):
        title = 'Asuransi Pendidikan Anak: Cara Memilih Polis yang Tepat'
        # Contained in the category name.
        self.assertEqual(make_post_slug(title, 'asuransi pendidikan anak', 'Asuransi Pendidikan Anak dan Keluarga'),
                         'asuransi-pendidikan-anak-cara-memilih-polis-yang-tepat')
        # Two words only: a bare head term, whatever the category.
        self.assertEqual(make_post_slug('Digitalisasi Pendidikan di Sekolah Dasar Negeri', 'digitalisasi pendidikan'),
                         'digitalisasi-pendidikan-di-sekolah-dasar-negeri')
        # A descriptive keyword that is not the category is still used.
        self.assertEqual(make_post_slug('Menghitung PPh 21 Karyawan: Panduan Praktis', 'PPh 21 karyawan', 'Pajak'),
                         'pph-21-karyawan')
        self.assertEqual(make_post_slug('Family Budgeting Basics: Reclaim Household Cash Flow',
                                        'family budgeting basics', ['Budgeting', 'family-finance']),
                         'family-budgeting-basics')

    def test_trailing_prepositions_are_never_left_dangling(self):
        for word in ('di', 'ke', 'dari', 'untuk', 'in', 'for', 'of', 'to', 'on', 'with', 'and', 'dan', 'yang'):
            self.assertIn(word, wp_publisher.SLUG_STOPWORDS)
        cases = {
            'Standar Pelayanan Minimal Asrama: Cara Menyusun Indikator di': '-di',
            'Saving Money Tips That Actually Work In': '-in',
            'Best Emergency Fund Accounts for': '-for',
            'Rencana Belajar Siswa yang': '-yang',
        }
        for title, bad_end in cases.items():
            slug = make_post_slug(title)
            self.assertFalse(slug.endswith(bad_end), (title, slug))
        # Meaningful words are not stopwords: "tanpa" (without) stays at the start.
        self.assertEqual(make_post_slug('Tanpa Utang Konsumtif'), 'tanpa-utang-konsumtif')


class MetaAndTitleTests(PublisherTestCase):
    LONG_META = ('Digitalisasi pendidikan 2026 menuntut sekolah menyiapkan infrastruktur, kompetensi guru, dan tata '
                 'kelola data yang rapi. Panduan ini membahas rencana aksi yang realistis untuk sekolah negeri dan '
                 'swasta, mulai dari audit perangkat sampai pelatihan guru, lengkap dengan contoh jadwal kerja.')

    def payload(self, **kwargs):
        args = dict(title='Rencana Aksi Digitalisasi Sekolah', content='<h2>A</h2><p>Isi</p>',
                    meta_description=self.LONG_META, focus_keyword='rencana aksi digitalisasi sekolah')
        args.update(kwargs)
        return self.publisher._prepare_post_payload(**args)

    def test_long_meta_is_cut_at_a_sentence_end(self):
        self.assertGreater(len(self.LONG_META), 250)
        _, meta = self.payload()
        cut = meta['_yoast_wpseo_metadesc']
        self.assertLessEqual(len(cut), 158)
        self.assertTrue(self.LONG_META.startswith(cut))
        self.assertTrue(cut.endswith('rapi.'))
        self.assertEqual(meta['rank_math_description'], cut)

    def test_meta_without_a_usable_sentence_end_is_cut_on_a_word(self):
        text = ('This guide explains how to build an emergency fund step by step with realistic monthly targets, '
                'where to keep the money, and how to rebuild it after you use it for a real family emergency')
        _, meta = self.payload(meta_description=text)
        cut = meta['_yoast_wpseo_metadesc']
        self.assertLessEqual(len(cut), 158)
        self.assertTrue(text.startswith(cut))
        self.assertEqual(text[len(cut)], ' ')  # whole words only
        self.assertFalse(cut.endswith(('...', '…', ',', ' and', ' for', ' to')))

    def test_short_meta_is_unchanged(self):
        _, meta = self.payload(meta_description='Deskripsi meta yang pas.')
        self.assertEqual(meta['_yoast_wpseo_metadesc'], 'Deskripsi meta yang pas.')

    def test_long_title_is_logged_not_cut(self):
        title = 'Rencana Aksi Digitalisasi Sekolah Negeri dan Swasta: Audit, Pelatihan Guru, dan Jadwal Kerja'
        self.assertGreater(len(title), 70)
        with self.assertLogs(wp_publisher.logger, level='WARNING') as logs:
            post_data, _ = self.payload(title=title)
        self.assertEqual(post_data['title'], title)
        self.assertTrue(any('characters' in line for line in logs.output))


class FeaturedImageTests(PublisherTestCase):
    TITLE = 'Standar Pelayanan Minimal Asrama: Cara Menyusun Indikator dan Target di 2026'

    def upload(self, language, slug=None, image=None):
        self.publisher.language = language
        with patch.object(wp_publisher.requests, 'request',
                          side_effect=[response(201, {'id': 9}), response(200, {})]) as req:
            media_id = self.publisher.upload_image(image or BytesIO(b'img'), self.TITLE, slug=slug)
        self.assertEqual(media_id, 9)
        return req.call_args_list

    def test_filename_follows_the_slug(self):
        calls = self.upload('id', slug='standar-pelayanan-minimal-asrama')
        self.assertEqual(calls[0].kwargs['headers']['Content-Disposition'],
                         'attachment; filename="standar-pelayanan-minimal-asrama.webp"')

    def test_filename_from_title_is_cut_on_a_word_boundary(self):
        calls = self.upload('id')
        filename = calls[0].kwargs['headers']['Content-Disposition'].split('"')[1]
        stem = filename.removesuffix('.webp')
        self.assertLessEqual(len(stem), 60)
        self.assertEqual(stem, 'standar-pelayanan-minimal-asrama-cara-menyusun-indikator')
        for word in stem.split('-'):
            self.assertIn(word, self.TITLE.lower())  # no word cut in half ("in" from "indikator")
        self.assertFalse(stem.endswith(('-di', '-dan')))

    def test_media_description_follows_the_site_language(self):
        meta = self.upload('id')[1].kwargs['json']
        self.assertEqual(meta, {'title': self.TITLE, 'alt_text': self.TITLE,
                                'description': f'Ilustrasi untuk artikel: {self.TITLE}'})
        meta = self.upload('en')[1].kwargs['json']
        self.assertEqual(meta['description'], f'Illustration for the article: {self.TITLE}')
        self.assertEqual(meta['alt_text'], self.TITLE)

    def test_image_file_stem_edge_cases(self):
        long_slug = '-'.join(['kata'] * 20)
        stem = wp_publisher.image_file_stem('Judul', slug=long_slug)
        self.assertLessEqual(len(stem), 60)
        self.assertTrue(all(part == 'kata' for part in stem.split('-')))
        self.assertEqual(wp_publisher.image_file_stem('2026', slug=None), 'featured-image')


class SourcesSectionTests(PublisherTestCase):
    CITABLE = [
        {'url': 'https://www.consumerfinance.gov/emergency-savings/', 'title': 'Emergency savings & <b>basics</b>'},
        {'url': 'https://www.fdic.gov/deposit-insurance', 'title': 'Deposit insurance'},
        {'url': 'https://blog.example.org/fund', 'title': ''},
        {'url': 'https://unused.example.net/x', 'title': 'Unused'},
    ]
    CONTENT = ('<h2>Why</h2><p>Keep three months, says the '
               '<a href="https://consumerfinance.gov/emergency-savings">CFPB</a>.</p>'
               '<h2>Where</h2><p>Accounts are insured up to the limit '
               '(<a href="https://www.fdic.gov/deposit-insurance/">FDIC</a>), see also '
               '<a href="https://blog.example.org/fund">this</a> and again '
               '<a href="https://www.consumerfinance.gov/emergency-savings/">CFPB</a> and '
               '<a href="https://example.com/own-post">our post</a>.</p>')

    def payload(self, content=None, language='en', **kwargs):
        self.publisher.language = language
        args = dict(title='Emergency Fund Basics for Families', content=content or self.CONTENT,
                    key_takeaways=['Point'], faqs=[{'question': 'Q?', 'answer': 'A.'}],
                    citable_sources=self.CITABLE + [{'url': 'https://example.com/own-post', 'title': 'Own'}])
        args.update(kwargs)
        return self.publisher._prepare_post_payload(**args)[0]['content']

    def test_section_lists_cited_sources_between_content_and_faq(self):
        content = self.payload()
        self.assertEqual(content.count('<h2>Sources</h2>'), 1)
        self.assertLess(content.index('key-takeaways'), content.index('<h2>Why</h2>'))
        self.assertLess(content.index('our post'), content.index('<h2>Sources</h2>'))
        self.assertLess(content.index('<h2>Sources</h2>'), content.index('<h2>FAQ</h2>'))
        section = content[content.index('<div class="article-sources">'):content.index('<h2>FAQ</h2>')]
        # De-duplicated, in order of first use, escaped; unused and own-site links are not sources.
        self.assertEqual(section.count('<li>'), 3)
        self.assertIn('Emergency savings &amp; basics (consumerfinance.gov)', section)
        self.assertIn('Deposit insurance (fdic.gov)', section)
        self.assertIn('>blog.example.org</a>', section)
        self.assertNotIn('Unused', section)
        self.assertNotIn('example.com/own-post', section)
        self.assertLess(section.index('consumerfinance'), section.index('fdic'))

    def test_heading_follows_language_and_section_survives_the_sanitizer(self):
        content = self.payload(language='id')
        self.assertIn('<h2>Sumber</h2>', content)
        section = wp_publisher.sources_section(wp_publisher.cited_sources(self.CONTENT, self.CITABLE), 'id')
        self.assertEqual(wp_publisher.sanitize_article_html(section), section)

    def test_no_section_without_external_citations(self):
        for citable in (None, [], [{'url': 'https://elsewhere.org/', 'title': 'x'}]):
            content = self.payload(citable_sources=citable)
            self.assertNotIn('article-sources', content)
            self.assertNotIn('<h2>Sources</h2>', content)

    def test_at_most_eight_sources(self):
        citable = [{'url': f'https://src{i}.gov/page', 'title': f'Source {i}'} for i in range(12)]
        content = '<h2>A</h2><p>' + ' '.join(f'<a href="https://src{i}.gov/page">s{i}</a>' for i in range(12)) + '</p>'
        out = self.payload(content=content, citable_sources=citable)
        self.assertEqual(out.count('<li><a href="https://src'), 8)

    def test_not_added_twice_on_regeneration(self):
        first = self.payload(key_takeaways=None, faqs=None)
        # The published content comes back (e.g. a regeneration or an update of it).
        again = self.payload(content=first, key_takeaways=None, faqs=None)
        self.assertEqual(again.count('article-sources'), 1)
        self.assertEqual(again.count('<h2>Sources</h2>'), 1)
        with patch.object(wp_publisher.requests, 'request', return_value=response(200, {'id': 5})) as req:
            self.publisher.update_post_content(5, 'T', first, citable_sources=self.CITABLE)
        self.assertEqual(req.call_args_list[0].kwargs['json']['content'].count('<h2>Sources</h2>'), 1)

    def test_model_written_sources_list_is_replaced(self):
        content = self.CONTENT + ('<h2>References</h2><ul><li><a href="https://www.fdic.gov/deposit-insurance">'
                                  'FDIC</a></li></ul>')
        out = self.payload(content=content, faqs=None)
        self.assertNotIn('References', out)
        self.assertEqual(out.count('<h2>Sources</h2>'), 1)

    def test_only_a_trailing_link_list_is_treated_as_model_sources(self):
        # A "Referensi" list followed by more content is article content, not a sources tail.
        content = (self.CONTENT + '<h2>Referensi</h2><ul><li>Satu</li></ul><p>Paragraf penting</p>'
                   '<ul><li>Dua</li></ul>')
        out = self.payload(content=content, faqs=None)
        for kept in ('Referensi', 'Paragraf penting', 'Dua'):
            self.assertIn(kept, out)

    def test_youtube_embed_lands_in_the_body_not_in_the_sources_box(self):
        self.publisher.enable_youtube_embed = True
        with patch.object(self.publisher, '_find_relevant_video', return_value='abcdefghijk'):
            out = self.payload()
        section = out[out.index('<div class="article-sources">'):]
        self.assertIn('abcdefghijk', out)
        self.assertNotIn('abcdefghijk', section)
        self.assertLess(out.index('abcdefghijk'), out.index('<div class="article-sources">'))


class TimeoutRecoveryTests(PublisherTestCase):
    def test_lost_response_is_recovered_by_the_new_slug(self):
        now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
        # WordPress may render the title differently (texturized quotes), so the slug must match.
        found = {'id': 21, 'slug': 'family-budgeting-basics', 'date_gmt': now,
                 'title': {'rendered': 'Family Budgeting Basics &#8211; Reclaim Household Cash Flow'}}
        sent = []

        def fake(method, url, **kwargs):
            if method == 'POST':
                sent.append(kwargs['json'])
                raise requests.exceptions.ReadTimeout('read timed out')
            return response(200, [found])

        with patch.object(wp_publisher.requests, 'request', side_effect=fake):
            ok, result = self.publisher.create_post(
                'Family Budgeting Basics: Reclaim Household Cash Flow in 2026', '<p>x</p>',
                focus_keyword='family budgeting basics')
        self.assertTrue(ok)
        self.assertEqual(result['id'], 21)
        self.assertEqual(sent[0]['slug'], 'family-budgeting-basics')


if __name__ == '__main__':
    unittest.main()
