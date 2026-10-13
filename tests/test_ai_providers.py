"""Provider layer: request shapes, truncation/refusal handling, error policy and
config selection for Gemini, Claude (Anthropic) and OpenAI. No network calls."""
import base64
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import anthropic
import httpx2
import openai

from services import ai_providers
from services.ai_providers import (
    AIProviderError, AnthropicText, GeminiImage, GeminiText, OpenAIImage, OpenAIText,
    describe_provider_error, is_fatal_provider_error, is_retryable_provider_error,
    make_image_provider, make_text_provider, merge_shared_ai_config,
)
from services.article_generator import ArticleGenerator

REQUEST = httpx2.Request('POST', 'https://api.example.com/v1/x')


def status_error(sdk, code):
    response = httpx2.Response(code, request=REQUEST)
    return sdk.APIStatusError('boom', response=response, body=None)


def claude_message(text='Halo', stop_reason='end_turn', stop_details=None):
    return SimpleNamespace(
        content=[SimpleNamespace(type='thinking', thinking=''), SimpleNamespace(type='text', text=text)],
        stop_reason=stop_reason, stop_details=stop_details)


def fake_claude_client(message):
    stream = MagicMock()
    stream.__enter__.return_value.get_final_message.return_value = message
    client = SimpleNamespace(
        messages=SimpleNamespace(stream=Mock(return_value=stream)),
        beta=SimpleNamespace(messages=SimpleNamespace(stream=Mock(return_value=stream))),
    )
    return client


class AnthropicTextTests(unittest.TestCase):
    def test_current_model_streams_with_effort_and_refusal_fallback(self):
        client = fake_claude_client(claude_message('Artikel'))
        result = AnthropicText(None, 'claude-opus-5-5', client=client).generate(
            'tulis', system='sistem', max_tokens=16384, temperature=0.7, top_p=0.9)
        self.assertEqual(result.text, 'Artikel')
        self.assertFalse(result.truncated)
        kwargs = client.beta.messages.stream.call_args.kwargs
        self.assertEqual(kwargs['fallbacks'], 'default')
        self.assertEqual(kwargs['betas'], [ai_providers.CLAUDE_FALLBACK_BETA])
        self.assertEqual(kwargs['output_config'], {'effort': 'medium'})
        self.assertEqual(kwargs['system'], 'sistem')
        self.assertGreaterEqual(kwargs['max_tokens'], ai_providers.REASONING_MIN_OUTPUT_TOKENS)
        # Current Claude models reject sampling parameters.
        self.assertNotIn('temperature', kwargs)
        self.assertNotIn('top_p', kwargs)
        client.messages.stream.assert_not_called()

    def test_older_model_uses_plain_stream_without_effort(self):
        client = fake_claude_client(claude_message())
        AnthropicText(None, 'claude-haiku-4-5', client=client).generate('x')
        kwargs = client.messages.stream.call_args.kwargs
        self.assertNotIn('output_config', kwargs)
        self.assertNotIn('fallbacks', kwargs)
        client.beta.messages.stream.assert_not_called()

    def test_max_tokens_stop_is_reported_as_truncated(self):
        client = fake_claude_client(claude_message('setengah', stop_reason='max_tokens'))
        self.assertTrue(AnthropicText(None, 'claude-sonnet-5-5', client=client).generate('x').truncated)

    def test_refusal_raises_user_facing_error(self):
        message = claude_message('', stop_reason='refusal', stop_details=SimpleNamespace(category='cyber'))
        client = fake_claude_client(message)
        with self.assertRaises(AIProviderError) as caught:
            AnthropicText(None, 'claude-opus-5-5', client=client).generate('x')
        self.assertIn('cyber', str(caught.exception))


class OpenAITextTests(unittest.TestCase):
    def client(self, **response):
        defaults = {'output_text': 'Teks', 'status': 'completed', 'incomplete_details': None}
        defaults.update(response)
        return SimpleNamespace(responses=SimpleNamespace(create=Mock(return_value=SimpleNamespace(**defaults))))

    def test_responses_api_without_sampling_parameters(self):
        client = self.client()
        result = OpenAIText(None, 'gpt-5.5', client=client).generate(
            'tulis', system='sistem', temperature=0.7, top_p=0.9)
        self.assertEqual(result.text, 'Teks')
        kwargs = client.responses.create.call_args.kwargs
        self.assertEqual(kwargs['instructions'], 'sistem')
        self.assertEqual(kwargs['input'], 'tulis')
        self.assertNotIn('temperature', kwargs)

    def test_incomplete_for_max_output_tokens_is_truncated(self):
        client = self.client(status='incomplete',
                             incomplete_details=SimpleNamespace(reason='max_output_tokens'))
        self.assertTrue(OpenAIText(None, 'gpt-5.5', client=client).generate('x').truncated)


class GeminiTextTests(unittest.TestCase):
    def test_sampling_and_truncation(self):
        response = SimpleNamespace(text='ok', candidates=[SimpleNamespace(finish_reason='MAX_TOKENS')])
        client = SimpleNamespace(models=SimpleNamespace(generate_content=Mock(return_value=response)))
        result = GeminiText(None, 'gemini-x', client=client).generate('x', system='s', temperature=0.7)
        self.assertTrue(result.truncated)
        config = client.models.generate_content.call_args.kwargs['config']
        self.assertEqual(config.temperature, 0.7)
        self.assertEqual(config.system_instruction, 's')


class ImageProviderTests(unittest.TestCase):
    PNG = base64.b64encode(b'\x89PNG fake').decode()

    def client(self):
        response = SimpleNamespace(data=[SimpleNamespace(b64_json=self.PNG)], created=1)
        return SimpleNamespace(images=SimpleNamespace(generate=Mock(return_value=response)))

    def test_gpt_image_uses_landscape_size_and_decodes_base64(self):
        client = self.client()
        image_bytes, summary = OpenAIImage(None, 'gpt-image-2', client=client).attempt('gambar', 30000)
        self.assertEqual(image_bytes, b'\x89PNG fake')
        self.assertIsNone(summary)
        kwargs = client.images.generate.call_args.kwargs
        self.assertEqual(kwargs['size'], '1536x1024')
        self.assertNotIn('response_format', kwargs)

    def test_dall_e_asks_for_base64(self):
        client = self.client()
        OpenAIImage(None, 'dall-e-3', client=client).attempt('gambar', 30000)
        kwargs = client.images.generate.call_args.kwargs
        self.assertEqual(kwargs['response_format'], 'b64_json')
        self.assertEqual(kwargs['size'], '1792x1024')

    def test_generator_falls_back_across_prompts_then_reports_provider(self):
        client = SimpleNamespace(images=SimpleNamespace(
            generate=Mock(side_effect=status_error(openai, 401))))
        generator = ArticleGenerator(None, image_provider=OpenAIImage(None, 'gpt-image-2', client=client))
        with self.assertRaises(Exception) as caught:
            generator.generate_image('Sekolah', 'Judul')
        # A bad key fails the same for every prompt: stop after one attempt.
        self.assertEqual(client.images.generate.call_count, 1)
        self.assertIn('OpenAI', str(caught.exception))


class ErrorPolicyTests(unittest.TestCase):
    def test_retry_and_fatal_classification(self):
        for sdk in (anthropic, openai):
            self.assertTrue(is_retryable_provider_error(status_error(sdk, 429)))
            self.assertTrue(is_retryable_provider_error(status_error(sdk, 529)))
            self.assertFalse(is_retryable_provider_error(status_error(sdk, 400)))
            self.assertTrue(is_fatal_provider_error(status_error(sdk, 401)))
            self.assertTrue(is_retryable_provider_error(sdk.APIConnectionError(request=REQUEST)))

    def test_user_messages(self):
        self.assertIn('Claude', describe_provider_error(status_error(anthropic, 401), 'anthropic'))
        self.assertIn('Kuota', describe_provider_error(status_error(openai, 429), 'openai'))
        self.assertIsNone(describe_provider_error(ValueError('x'), 'openai'))


class ConfigSelectionTests(unittest.TestCase):
    BASE = {
        'ai_text_provider': 'anthropic', 'ai_image_provider': 'openai',
        'gemini_api_key': 'g', 'anthropic_api_key': 'a', 'openai_api_key': 'o',
        'anthropic_model': 'claude-sonnet-5-5', 'openai_image_model': 'gpt-image-1',
    }

    def test_selected_providers_and_models(self):
        text = make_text_provider(self.BASE)
        image = make_image_provider(self.BASE)
        self.assertIsInstance(text, AnthropicText)
        self.assertEqual(text.model, 'claude-sonnet-5-5')
        self.assertIsInstance(image, OpenAIImage)
        self.assertEqual(image.model, 'gpt-image-1')

    def test_unknown_provider_falls_back_to_gemini(self):
        config = dict(self.BASE, ai_text_provider='nope', ai_image_provider='nope')
        self.assertIsInstance(make_text_provider(config), GeminiText)
        self.assertIsInstance(make_image_provider(config), GeminiImage)

    def test_missing_key_is_a_user_facing_error(self):
        with self.assertRaises(AIProviderError) as caught:
            make_text_provider(dict(self.BASE, anthropic_api_key=''))
        self.assertIn('Claude', str(caught.exception))

    def test_text_only_work_does_not_need_an_image_key(self):
        generator = ArticleGenerator.from_config(dict(self.BASE, openai_api_key=''))
        self.assertIsInstance(generator.text, AnthropicText)

    def test_shared_config_and_own_key(self):
        admin = dict(self.BASE)
        merged = merge_shared_ai_config({'gemini_api_key': 'mine'}, admin)
        self.assertEqual(merged['gemini_api_key'], 'mine')
        self.assertEqual(merged['anthropic_api_key'], 'a')
        # The active text provider is Anthropic, which runs on the shared key.
        self.assertFalse(merged['own_ai_key'])
        merged = merge_shared_ai_config({'anthropic_api_key': 'mine'}, admin)
        self.assertTrue(merged['own_ai_key'])


if __name__ == '__main__':
    unittest.main()
