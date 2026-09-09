import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from services.article_generator import ArticleGenerator, ArticleQualityError


def response(extra=''):
    body = ''.join(f'<h2>Bagian {i}</h2><p>' + 'panduan sekolah praktis ' * 320 + '</p>'
                   for i in range(3))
    return SimpleNamespace(candidates=[], text=(
        '<TITLE>Panduan Sekolah</TITLE><CONTENT>' + body + extra + '</CONTENT>'
        '<META_DESCRIPTION>' + 'Panduan sekolah yang berguna. ' * 4 + '</META_DESCRIPTION>'
    ))


class ArticleQualityRetryTests(unittest.TestCase):
    def generator(self, responses):
        generator = ArticleGenerator.__new__(ArticleGenerator)
        generator.model = 'test-model'
        generator.client = SimpleNamespace(models=SimpleNamespace(
            generate_content=Mock(side_effect=responses)))
        return generator

    def test_valid_article_needs_only_one_request(self):
        generator = self.generator([response()])
        self.assertEqual(generator.generate_checked_article('Sekolah')['title'], 'Panduan Sekolah')
        self.assertEqual(generator.client.models.generate_content.call_count, 1)

    def test_fabrication_is_corrected_with_same_research(self):
        generator = self.generator([
            response('<p>berdasarkan pengalaman tim praktisi kami</p>'), response()])
        article = generator.generate_checked_article(
            'Sekolah', custom_topic='Topik terpilih',
            custom_prompt='Tuliskan {topic}', seo_data={'keywords': ['bukti-riset-sekolah']})
        self.assertNotIn('tim praktisi kami', article['content'])
        calls = generator.client.models.generate_content.call_args_list
        self.assertEqual(len(calls), 2)
        for call in calls:
            self.assertIn('Topik terpilih', call.kwargs['contents'])
            self.assertIn('bukti-riset-sekolah', call.kwargs['contents'])
            self.assertIn('Never invent publisher experience', call.kwargs['config'].system_instruction)
        self.assertIn('manufactured-credential', calls[1].kwargs['contents'])
        self.assertIn('do not merely disguise', calls[1].kwargs['contents'])

    def test_persistent_rejection_is_bounded_and_keeps_title(self):
        generator = self.generator([response('<p>data internal kami</p>')] * 2)
        with self.assertRaises(ArticleQualityError) as caught:
            generator.generate_checked_article('Sekolah')
        self.assertEqual(caught.exception.article_title, 'Panduan Sekolah')
        self.assertIn('after 2 attempts', str(caught.exception))
        self.assertEqual(generator.client.models.generate_content.call_count, 2)

    def test_transport_failure_does_not_trigger_quality_retry(self):
        generator = self.generator([ValueError('invalid configuration')])
        with self.assertRaises(ValueError):
            generator.generate_checked_article('Sekolah')
        self.assertEqual(generator.client.models.generate_content.call_count, 1)


if __name__ == '__main__':
    unittest.main()
