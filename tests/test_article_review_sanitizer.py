"""Final HTML hardening around the AI review: the allow-list sanitizer on the
published body, plain-text title/excerpt/meta, the publisher's own boxes and
embeds surviving it, and HTML-escaped source URLs matching the link allow-list."""
import unittest
from unittest.mock import patch

from services import wp_publisher
from services.quality_gate import check_article, plain_text, sanitize_article_html, strip_invalid_internal_links
from services.wp_publisher import WordPressPublisher


class SanitizerTests(unittest.TestCase):
    def test_dangerous_markup_is_removed(self):
        dirty = (
            '<p onclick="x()">Halo <a href="javascript:alert(1)">tautan</a></p>'
            '<svg/onload=alert(1)></svg><script>bad()</script><style>p{}</style>'
            '<iframe src="https://evil.example"></iframe><img src=x onerror=alert(1)>'
            '<meta http-equiv="refresh" content="0;url=https://evil.example"><base href="https://evil.example">'
            '<link rel="stylesheet" href="x"><frame src="x"><object data="x"></object><embed src="x">'
            '<form action="x"><input name="q"></form><!-- komentar -->'
            '<a href=" java&#09;script:alert(1)">tab</a><a href="data:text/html,x">data</a>'
        )
        clean = sanitize_article_html(dirty)
        for marker in ('onclick', 'onload', 'onerror', '<script', 'bad()', '<style', '<iframe', '<img', '<meta',
                       '<base', '<link', '<frame', '<object', '<embed', '<form', '<input', 'komentar',
                       'javascript', 'data:text', 'evil.example', '<svg'):
            with self.subTest(marker=marker):
                self.assertNotIn(marker, clean)
        self.assertIn('<p>Halo tautan</p>', clean)  # unsafe link unwrapped, text kept
        self.assertIn('tab', clean)

    def test_article_structure_survives(self):
        html = (
            '<h1>Judul</h1><h2 id="a" style="color:red">Bagian</h2><p class="lead">Teks <strong>tebal</strong> '
            '<em>miring</em><br>baris</p><ul><li>satu</li></ul><ol><li>dua</li></ol>'
            '<table><thead><tr><th colspan="2" scope="col">H</th></tr></thead>'
            '<tbody><tr><td rowspan="x">1</td><td>2</td></tr></tbody></table>'
            '<blockquote>kutip</blockquote><div class="cta" style="x"><span>CTA</span></div>'
            '<a href="https://sumber.id/a?x=1&amp;y=2" target="_blank" rel="nofollow evil" title="t">sumber</a>'
            '<a href="/internal">internal</a><a href="#bagian">lompat</a><a href="mailto:a@b.id">surel</a>'
            '<custom-tag>isi kustom</custom-tag>'
        )
        clean = sanitize_article_html(html)
        self.assertIn('<h2>Judul</h2>', clean)
        self.assertIn('<h2>Bagian</h2>', clean)
        self.assertIn('<p class="lead">Teks <strong>tebal</strong> <em>miring</em><br/>baris</p>', clean)
        self.assertIn('<th colspan="2" scope="col">H</th>', clean)
        self.assertIn('<td>1</td>', clean)
        self.assertIn('<div class="cta"><span>CTA</span></div>', clean)
        self.assertIn('<a href="https://sumber.id/a?x=1&amp;y=2" rel="nofollow noopener" target="_blank" '
                      'title="t">sumber</a>', clean)
        for kept in ('<a href="/internal">', '<a href="#bagian">', '<a href="mailto:a@b.id">', 'isi kustom',
                     '<blockquote>kutip</blockquote>', '<ul><li>satu</li></ul>'):
            self.assertIn(kept, clean)
        self.assertNotIn('custom-tag', clean)

    def test_text_entities_stay_escaped(self):
        self.assertEqual(sanitize_article_html('<p>A &amp; B &lt;script&gt;</p>'), '<p>A &amp; B &lt;script&gt;</p>')

    def test_plain_text_decodes_before_stripping(self):
        self.assertEqual(plain_text('&lt;script&gt;alert(1)&lt;/script&gt; Tom &amp; Jerry <b>x</b>'),
                         'alert(1) Tom & Jerry x')
        self.assertEqual(plain_text('Return > inflasi <i>2026</i>'), 'Return inflasi 2026')
        self.assertEqual(plain_text(None), '')


class PublisherPayloadTests(unittest.TestCase):
    def setUp(self):
        p = patch.object(wp_publisher, '_validate_url', lambda url: (True, url.rstrip('/')))
        p.start()
        self.addCleanup(p.stop)
        self.publisher = WordPressPublisher('https://example.com', 'admin', 'pw', site_name='Situs',
                                            enable_youtube_embed=True)

    def test_body_is_sanitized_before_boxes_and_embed_are_added(self):
        with patch.object(self.publisher, '_find_relevant_video', return_value='abc123XYZ_-'):
            post_data, _ = self.publisher._prepare_post_payload(
                title='<b>Judul</b> &amp; &lt;script&gt;x&lt;/script&gt;',
                content='<h2>A</h2><p onclick="x">Isi</p><script>bad()</script><h2>B</h2><p>Dua</p>',
                meta_description='Meta &lt;img src=x onerror=1&gt; deskripsi',
                excerpt='<em>Ringkas</em> &lt;script&gt;',
                key_takeaways=['Poin satu'], faqs=[{'question': 'Apa?', 'answer': 'Itu.'}],
            )
        content = post_data['content']
        self.assertNotIn('onclick', content)
        self.assertNotIn('bad()', content)
        # The publisher's own markup is added after sanitizing and keeps its styling.
        self.assertIn('<div class="key-takeaways" style="background:#f0f9ff;', content)
        self.assertIn('<h2>FAQ</h2>', content)
        self.assertIn('<iframe style="position: absolute;', content)
        self.assertIn('src="https://www.youtube.com/embed/abc123XYZ_-"', content)
        self.assertEqual(post_data['title'], 'Judul & x')
        self.assertEqual(post_data['excerpt'], 'Ringkas')
        self.assertEqual(post_data['meta']['rank_math_description'], 'Meta deskripsi')


class EscapedHrefTests(unittest.TestCase):
    URL = 'https://sumber.id/data?a=1&b=2'
    CONTENT = '<p>Lihat <a href="https://sumber.id/data?a=1&amp;b=2">data</a>.</p>'

    def test_escaped_query_matches_the_allow_list(self):
        self.assertEqual(strip_invalid_internal_links(self.CONTENT, [self.URL]), self.CONTENT)
        _, _, warnings = check_article({'title': 'T', 'content': self.CONTENT}, allowed_link_urls=[self.URL])
        self.assertFalse([w for w in warnings if 'link' in w])

    def test_other_links_are_still_unwrapped(self):
        self.assertEqual(strip_invalid_internal_links(self.CONTENT, ['https://sumber.id/lain']),
                         '<p>Lihat data.</p>')


if __name__ == '__main__':
    unittest.main()
