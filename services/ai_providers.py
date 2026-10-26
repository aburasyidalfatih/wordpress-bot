"""Text and image generation behind one interface for Gemini, Anthropic and OpenAI.

ArticleGenerator and the research/prompt helpers only talk to TextProvider /
ImageProvider; everything SDK-specific (request shape, truncation and refusal
signals, error classes, image decoding) lives here.
"""
import base64
import logging
import re
from dataclasses import dataclass

import anthropic
import openai
from google import genai
from google.genai import types

from services.ai_costs import record_usage
from config import (
    DEFAULT_ANTHROPIC_MODEL, DEFAULT_GEMINI_IMAGE_MODEL, DEFAULT_GEMINI_MODEL, DEFAULT_IMAGE_PROVIDER,
    DEFAULT_OPENAI_IMAGE_MODEL, DEFAULT_OPENAI_MODEL, DEFAULT_TEXT_PROVIDER, IMAGE_PROVIDERS, TEXT_PROVIDERS,
)

try:
    import httpx  # transport used by google-genai
except ImportError:  # pragma: no cover
    httpx = None

logger = logging.getLogger(__name__)

PROVIDER_LABELS = {'gemini': 'Gemini', 'anthropic': 'Claude (Anthropic)', 'openai': 'OpenAI'}

# Claude and OpenAI reasoning models spend part of the output budget on
# thinking, so they get a larger ceiling than the visible article needs. Only
# the tokens actually generated are billed.
REASONING_MIN_OUTPUT_TOKENS = 32000

# Claude effort for article writing and research titles. Claude Opus 5.5 also
# defaults to medium; it is set explicitly so a model change keeps the level.
CLAUDE_EFFORT = 'medium'

# Models that accept output_config.effort (older ones reject it with a 400).
_CLAUDE_EFFORT_MODELS = re.compile(
    r'^claude-(fable|mythos|opus|sonnet|haiku)-5|^claude-opus-4-[678]|^claude-sonnet-4-6')
# Models that accept the server-side refusal fallback in its "default" form.
_CLAUDE_FALLBACK_MODELS = ('claude-fable-5-1', 'claude-opus-5-5', 'claude-opus-5', 'claude-sonnet-5-5')
CLAUDE_FALLBACK_BETA = 'server-side-fallback-2026-07-01'


class AIProviderError(Exception):
    """A provider failure whose (Indonesian) message is meant for the user."""


@dataclass
class TextResult:
    text: str
    truncated: bool = False
    # Token counts the SDK reported (input_tokens, output_tokens and, for
    # Claude, cache_read_input_tokens / cache_creation_input_tokens), or None.
    usage: dict | None = None
    # Estimated USD cost (services.ai_costs), None when the model is not priced.
    cost_usd: float | None = None


def _token_counts(**fields):
    """The integer token counts among fields; None when there are none."""
    counts = {name: value for name, value in fields.items() if isinstance(value, int)}
    return counts or None


# ---------------------------------------------------------------------------
# Error classification (shared by all providers)
# ---------------------------------------------------------------------------

def status_code_of(exc):
    """HTTP status of an SDK error, or None for transport errors."""
    code = getattr(exc, 'code', None)
    if code is None:
        code = getattr(exc, 'status_code', None)
    try:
        return int(code)
    except (TypeError, ValueError):
        return None


def is_retryable_provider_error(exc):
    """Retry only failures that can succeed on a second try.

    4xx errors (invalid key, permission, unknown model, bad request) fail
    identically every time; 429 (rate limit / quota), 5xx and network errors are
    transient.
    """
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return True
    # APITimeoutError is a subclass of APIConnectionError in both SDKs.
    if isinstance(exc, (anthropic.APIConnectionError, openai.APIConnectionError)):
        return True
    if isinstance(exc, (anthropic.APIStatusError, openai.APIStatusError)):
        code = status_code_of(exc)
        return code == 429 or (code is not None and code >= 500)
    if isinstance(exc, genai.errors.APIError):
        code = status_code_of(exc)
        if code is None:
            return isinstance(exc, genai.errors.ServerError)
        return code == 429 or code >= 500
    # httpx transport errors raised by google-genai (connect/read timeouts).
    if httpx is not None and isinstance(exc, (httpx.TimeoutException, httpx.NetworkError)):
        return True
    return False


def describe_provider_error(exc, provider=None):
    """Indonesian message for the user, or None when there is nothing specific to say."""
    if isinstance(exc, AIProviderError):
        return str(exc)
    label = PROVIDER_LABELS.get(provider, 'AI')
    code = status_code_of(exc)
    if code in (401, 403):
        return f'API key {label} tidak valid atau tidak memiliki izin akses.'
    if code == 404:
        return f'Model {label} tidak ditemukan. Periksa pilihan model di Panel Admin.'
    if code == 429:
        return f'Kuota atau batas permintaan {label} sedang habis. Coba lagi beberapa saat lagi.'
    if is_retryable_provider_error(exc):
        return f'Server {label} sedang sibuk atau tidak dapat dihubungi. Silakan coba lagi.'
    return None


def is_fatal_provider_error(exc):
    """Bad key, no permission or unknown model: the same for every prompt."""
    sdk_errors = (genai.errors.APIError, anthropic.APIStatusError, openai.APIStatusError)
    return isinstance(exc, sdk_errors) and status_code_of(exc) in (401, 403, 404)


# ---------------------------------------------------------------------------
# Text providers
# ---------------------------------------------------------------------------

class GeminiText:
    provider = 'gemini'

    def __init__(self, api_key, model=DEFAULT_GEMINI_MODEL, client=None):
        self.client = client or genai.Client(api_key=api_key)
        self.model = model

    def generate(self, prompt, system=None, max_tokens=8192, temperature=None, top_p=None):
        config = {'max_output_tokens': max_tokens}
        if system:
            config['system_instruction'] = system
        if temperature is not None:
            config['temperature'] = temperature
        if top_p is not None:
            config['top_p'] = top_p
        response = self.client.models.generate_content(
            model=self.model, contents=prompt, config=types.GenerateContentConfig(**config))
        truncated = any(
            'MAX_TOKENS' in str(getattr(candidate, 'finish_reason', '') or '').upper()
            for candidate in getattr(response, 'candidates', None) or []
        )
        meta = getattr(response, 'usage_metadata', None)
        thoughts = getattr(meta, 'thoughts_token_count', None)
        candidates = getattr(meta, 'candidates_token_count', None)
        usage = _token_counts(
            input_tokens=getattr(meta, 'prompt_token_count', None),
            # Thinking tokens are billed as output.
            output_tokens=(candidates or 0) + (thoughts or 0) if isinstance(candidates, int) else None,
        )
        cost = record_usage(self.provider, self.model, usage)
        return TextResult(response.text or '', truncated, usage, cost)


def claude_output_config(model):
    """output_config for model, or None when the model rejects effort."""
    return {'effort': CLAUDE_EFFORT} if _CLAUDE_EFFORT_MODELS.match(model or '') else None


def open_claude_stream(client, kwargs, **request_options):
    """The (not yet entered) stream manager for one Messages request.

    Models that support it get the server-side refusal fallback: if a safety
    classifier declines, the API re-runs the request on a fallback model inside
    the same call instead of just refusing. request_options are SDK per-request
    options such as timeout.
    """
    if kwargs.get('model') in _CLAUDE_FALLBACK_MODELS:
        return client.beta.messages.stream(
            betas=[CLAUDE_FALLBACK_BETA], fallbacks='default', **kwargs, **request_options)
    return client.messages.stream(**kwargs, **request_options)


def stream_claude_message(client, kwargs, **request_options):
    """Final message of one streamed Messages request (see open_claude_stream)."""
    with open_claude_stream(client, kwargs, **request_options) as active:
        return active.get_final_message()


class AnthropicText:
    """Claude via the Messages API.

    Streams (get_final_message) because the large output ceiling would otherwise
    risk HTTP timeouts. Sampling parameters are not sent: current Claude models
    reject temperature/top_p, and thinking is controlled through effort instead.
    """
    provider = 'anthropic'

    def __init__(self, api_key, model=DEFAULT_ANTHROPIC_MODEL, client=None):
        # Our callers retry transient errors themselves (tenacity), so the SDK
        # retries once instead of its default twice to keep worst-case time sane.
        self.client = client or anthropic.Anthropic(api_key=api_key, max_retries=1)
        self.model = model

    def _request_kwargs(self, prompt, system, max_tokens):
        kwargs = {
            'model': self.model,
            'max_tokens': max(max_tokens, REASONING_MIN_OUTPUT_TOKENS),
            'messages': [{'role': 'user', 'content': prompt}],
        }
        if system:
            kwargs['system'] = system
        output_config = claude_output_config(self.model)
        if output_config:
            kwargs['output_config'] = output_config
        return kwargs

    @staticmethod
    def usage_of(message):
        usage = getattr(message, 'usage', None)
        return _token_counts(
            input_tokens=getattr(usage, 'input_tokens', None),
            output_tokens=getattr(usage, 'output_tokens', None),
            cache_read_input_tokens=getattr(usage, 'cache_read_input_tokens', None),
            cache_creation_input_tokens=getattr(usage, 'cache_creation_input_tokens', None),
        )

    def generate(self, prompt, system=None, max_tokens=8192, temperature=None, top_p=None):
        message = stream_claude_message(self.client, self._request_kwargs(prompt, system, max_tokens))
        # Recorded before the refusal check: a refused request is billed too.
        usage = self.usage_of(message)
        cost = record_usage(self.provider, self.model, usage)

        if message.stop_reason == 'refusal':
            details = getattr(message, 'stop_details', None)
            category = getattr(details, 'category', None)
            raise AIProviderError(
                'Claude menolak membuat konten ini'
                + (f' (kategori: {category})' if category else '')
                + '. Ubah topik atau gunakan provider lain.'
            )
        text = ''.join(block.text for block in message.content if block.type == 'text')
        return TextResult(text, message.stop_reason == 'max_tokens', usage, cost)


class OpenAIText:
    """OpenAI via the Responses API.

    No temperature: OpenAI reasoning models only accept the default.
    """
    provider = 'openai'

    def __init__(self, api_key, model=DEFAULT_OPENAI_MODEL, client=None):
        self.client = client or openai.OpenAI(api_key=api_key, max_retries=1, timeout=600)
        self.model = model

    def generate(self, prompt, system=None, max_tokens=8192, temperature=None, top_p=None):
        kwargs = {
            'model': self.model,
            'input': prompt,
            'max_output_tokens': max(max_tokens, REASONING_MIN_OUTPUT_TOKENS),
        }
        if system:
            kwargs['instructions'] = system
        response = self.client.responses.create(**kwargs)
        reason = getattr(getattr(response, 'incomplete_details', None), 'reason', None)
        truncated = response.status == 'incomplete' and reason == 'max_output_tokens'
        usage = getattr(response, 'usage', None)
        usage = _token_counts(input_tokens=getattr(usage, 'input_tokens', None),
                              output_tokens=getattr(usage, 'output_tokens', None))
        cost = record_usage(self.provider, self.model, usage)
        return TextResult(response.output_text or '', truncated, usage, cost)


# ---------------------------------------------------------------------------
# Image providers: attempt(prompt, timeout_ms) -> (image bytes, None) or (None, summary)
# ---------------------------------------------------------------------------

def _iter_response_parts(response):
    try:
        direct_parts = getattr(response, 'parts', None)
    except Exception as e:
        # The SDK's .parts accessor raises on some blocked/empty responses;
        # the candidates below are still worth inspecting.
        logger.debug(f"Image response has no readable .parts: {e}")
        direct_parts = None
    if direct_parts:
        yield from direct_parts

    for candidate in getattr(response, 'candidates', None) or []:
        content = getattr(candidate, 'content', None)
        yield from getattr(content, 'parts', None) or []


def _gemini_response_summary(response):
    details = []
    prompt_feedback = getattr(response, 'prompt_feedback', None)
    if prompt_feedback:
        details.append(f"prompt_feedback={prompt_feedback}")

    for index, candidate in enumerate(getattr(response, 'candidates', None) or []):
        details.append(
            f"candidate[{index}] finish_reason={getattr(candidate, 'finish_reason', None)} "
            f"finish_message={getattr(candidate, 'finish_message', None)} "
            f"safety_ratings={getattr(candidate, 'safety_ratings', None)}"
        )

    text_parts = [
        getattr(part, 'text', '').strip()
        for part in _iter_response_parts(response)
        if getattr(part, 'text', None)
    ]
    if text_parts:
        details.append(f"text={text_parts[0][:300]}")

    return " | ".join(details) if details else "no response details"


def _inline_image_bytes(response):
    for part in _iter_response_parts(response):
        inline_data = getattr(part, 'inline_data', None)
        if inline_data is not None and getattr(inline_data, 'data', None):
            return inline_data.data
    return None


class GeminiImage:
    provider = 'gemini'

    def __init__(self, api_key, model=DEFAULT_GEMINI_IMAGE_MODEL, client=None):
        self.client = client or genai.Client(api_key=api_key)
        self.model = model

    def attempt(self, prompt, timeout_ms):
        # Image calls are counted in the job's cost ledger; their price is not tracked.
        record_usage(self.provider, self.model, None)
        if self.model.startswith('imagen-'):
            return self._imagen_attempt(prompt, timeout_ms)
        return self._gemini_image_attempt(prompt, timeout_ms)

    def _imagen_attempt(self, prompt, timeout_ms):
        response = self.client.models.generate_images(
            model=self.model,
            prompt=prompt,
            config=types.GenerateImagesConfig(
                number_of_images=1,
                aspect_ratio='16:9',
                output_mime_type='image/webp',
                http_options=types.HttpOptions(timeout=timeout_ms)
            )
        )
        for generated_image in getattr(response, 'generated_images', None) or []:
            image_bytes = getattr(getattr(generated_image, 'image', None), 'image_bytes', None)
            if image_bytes:
                return image_bytes, None
        return None, getattr(response, 'model_dump_json', lambda **_: str(response))(exclude_none=True)

    def _gemini_image_attempt(self, prompt, timeout_ms):
        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_modalities=['TEXT', 'IMAGE'],
                # person_generation is no longer supported by the Gemini API.
                image_config=types.ImageConfig(aspect_ratio='16:9'),
                http_options=types.HttpOptions(timeout=timeout_ms)
            )
        )
        image_bytes = _inline_image_bytes(response)
        if image_bytes:
            return image_bytes, None
        return None, _gemini_response_summary(response)


class OpenAIImage:
    provider = 'openai'

    def __init__(self, api_key, model=DEFAULT_OPENAI_IMAGE_MODEL, client=None):
        self.client = client or openai.OpenAI(api_key=api_key, max_retries=1)
        self.model = model

    def attempt(self, prompt, timeout_ms):
        # Image calls are counted in the job's cost ledger; their price is not tracked.
        record_usage(self.provider, self.model, None)
        kwargs = {'model': self.model, 'prompt': prompt, 'n': 1, 'timeout': timeout_ms / 1000}
        if self.model.startswith('dall-e'):
            # DALL-E returns URLs unless asked for base64; 1792x1024 is its 16:9-ish size.
            kwargs.update(size='1792x1024', response_format='b64_json')
        else:
            # GPT Image models always return base64; 1536x1024 is the landscape size.
            kwargs['size'] = '1536x1024'
        response = self.client.images.generate(**kwargs)
        for item in getattr(response, 'data', None) or []:
            if getattr(item, 'b64_json', None):
                return base64.b64decode(item.b64_json), None
        return None, f"no image data in response (created={getattr(response, 'created', None)})"


# ---------------------------------------------------------------------------
# Construction from the stored AI config
# ---------------------------------------------------------------------------

def text_provider_name(config):
    name = (config or {}).get('ai_text_provider') or DEFAULT_TEXT_PROVIDER
    return name if name in TEXT_PROVIDERS else DEFAULT_TEXT_PROVIDER


def image_provider_name(config):
    name = (config or {}).get('ai_image_provider') or DEFAULT_IMAGE_PROVIDER
    return name if name in IMAGE_PROVIDERS else DEFAULT_IMAGE_PROVIDER


def _require_key(config, provider):
    key = (config or {}).get(f'{provider}_api_key') or ''
    if not key:
        raise AIProviderError(f'API key {PROVIDER_LABELS[provider]} belum diatur di Panel Admin.')
    return key


def make_text_provider(config):
    name = text_provider_name(config)
    key = _require_key(config, name)
    if name == 'anthropic':
        return AnthropicText(key, config.get('anthropic_model') or DEFAULT_ANTHROPIC_MODEL)
    if name == 'openai':
        return OpenAIText(key, config.get('openai_model') or DEFAULT_OPENAI_MODEL)
    return GeminiText(key, config.get('gemini_model') or DEFAULT_GEMINI_MODEL)


def make_image_provider(config):
    name = image_provider_name(config)
    key = _require_key(config, name)
    if name == 'openai':
        return OpenAIImage(key, config.get('openai_image_model') or DEFAULT_OPENAI_IMAGE_MODEL)
    return GeminiImage(key, config.get('gemini_image_model') or DEFAULT_GEMINI_IMAGE_MODEL)


AI_KEY_FIELDS = ('gemini_api_key', 'anthropic_api_key', 'openai_api_key')


def merge_shared_ai_config(user_config, admin_config):
    """AI providers, models and keys are set once in the admin panel and shared.

    A user's own stored key (legacy per-user setting) still overrides the shared
    key for that provider; `own_ai_key` records whether the active text provider
    runs on the user's own key, which exempts them from the free-helper quota.
    """
    config = dict(admin_config)
    for field in AI_KEY_FIELDS:
        if user_config.get(field):
            config[field] = user_config[field]
    config['own_ai_key'] = bool(user_config.get(f'{text_provider_name(config)}_api_key'))
    return config


def has_text_credentials(config):
    """True when the configured text provider has an API key."""
    return bool((config or {}).get(f'{text_provider_name(config)}_api_key'))


def list_models(provider, api_key):
    """Model ids the key can use, for the admin model picker. Newest first where known."""
    if provider == 'anthropic':
        client = anthropic.Anthropic(api_key=api_key, max_retries=1, timeout=20)
        return [model.id for model in client.models.list()]
    if provider == 'openai':
        client = openai.OpenAI(api_key=api_key, max_retries=1, timeout=20)
        models = sorted(client.models.list(), key=lambda m: getattr(m, 'created', 0) or 0, reverse=True)
        return [model.id for model in models]
    if provider == 'gemini':
        client = genai.Client(api_key=api_key)
        return [(model.name or '').removeprefix('models/') for model in client.models.list() if model.name]
    raise AIProviderError('Provider tidak dikenal.')
