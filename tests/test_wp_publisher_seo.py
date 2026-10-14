"""WordPress payload: no AutoWP JSON-LD, visible FAQ, SEO plugin meta and short slugs."""
import unittest
from datetime import datetime, timezone
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
