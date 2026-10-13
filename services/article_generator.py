import html as html_mod
import logging
import re
import time
import unicodedata
from io import BytesIO

from google import genai
from google.genai import types
from PIL import Image
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception

from config import DEFAULT_GEMINI_MODEL, DEFAULT_GEMINI_IMAGE_MODEL
from services.article_prompts import build_article_prompt, build_image_prompts, build_system_instruction

try:
    import httpx  # transport used by google-genai
except ImportError:  # pragma: no cover
    httpx = None

logger = logging.getLogger(__name__)

# A 2000-2500 word HTML article plus meta, FAQs and takeaways does not fit in 8k
# tokens. Truncated output used to be published as-is with unclosed HTML tags.
MAX_OUTPUT_TOKENS = 16384


class TruncatedGenerationError(Exception):
    """Raised when the model hit the output token limit mid-article."""


# Featured images are optional (a post publishes without one), so image
# generation gets a hard time budget instead of nested retries: 5 tenacity
# attempts x up to 4 prompts with 60s backoff could burn most of the job timeout.
IMAGE_TIME_BUDGET_SECONDS = 150

# Below this much remaining budget an image attempt is not started.
IMAGE_MIN_ATTEMPT_MS = 15000


def _genai_status_code(exc):
    code = getattr(exc, 'code', None)
    if code is None:
        code = getattr(exc, 'status_code', None)
    try:
        return int(code)
    except (TypeError, ValueError):
        return None


def is_retryable_genai_error(exc):
    """Retry only failures that can succeed on a second try.

    4xx errors (invalid key 400/401, permission 403, unknown model 404, bad
    request) fail identically every time; retrying them only multiplied job time.
    429 (rate limit / quota) and 5xx are transient.
    """
    if isinstance(exc, (ConnectionError, TimeoutError, TruncatedGenerationError)):
        return True
    if isinstance(exc, genai.errors.APIError):
        code = _genai_status_code(exc)
        if code is None:
            return isinstance(exc, genai.errors.ServerError)
        return code == 429 or code >= 500
    # httpx transport errors raised by the SDK (connect/read timeouts).
    if httpx is not None and isinstance(exc, (httpx.TimeoutException, httpx.NetworkError)):
        return True
    return False


class ArticleQualityError(Exception):
    """Keep the rejected title available to the job's failure history."""

    def __init__(self, article, errors):
        self.article_title = article.get('title') or ''
        super().__init__('Artikel ditolak quality gate setelah 2 percobaan: ' + '; '.join(errors))


def sanitize_filename(name):
    name = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode('ascii')
    name = re.sub(r'[^a-zA-Z0-9._-]', '-', name)
    name = re.sub(r'-+', '-', name)
    return name.strip('-')


def strip_html(text):
    """Plain text from HTML, for deriving excerpts and counting words."""
    if not text:
        return ""
    text = re.sub(r'<script[^>]*>.*?</script>', ' ', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<style[^>]*>.*?</style>', ' ', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = html_mod.unescape(text)
    return re.sub(r'\s+', ' ', text).strip()


def derive_excerpt(content, limit=160):
    """Build an excerpt from the article's own opening prose.

    Never returns a canned template — a per-article excerpt is what makes the
    meta description unique across the site.
    """
    plain = strip_html(content)
    if not plain:
        return ""
    sentences = re.split(r'(?<=[.!?])\s+', plain)
    excerpt = ""
    for sentence in sentences:
        candidate = (excerpt + " " + sentence).strip() if excerpt else sentence
        if len(candidate) > limit:
            break
        excerpt = candidate
    if not excerpt:
        excerpt = plain[:limit].rsplit(' ', 1)[0]
    return excerpt.strip()


def derive_takeaways(content, limit=4):
    """Fall back to the article's own H2 headings rather than a fixed template."""
    headings = re.findall(r'<h2[^>]*>(.*?)</h2>', content or '', flags=re.DOTALL | re.IGNORECASE)
    takeaways = []
    for heading in headings:
        text = strip_html(heading)
        if text and len(text) > 3:
            takeaways.append(text)
        if len(takeaways) >= limit:
            break
    return takeaways


# ---------------------------------------------------------------------------
# Parsing the model's XML-tagged article output
# ---------------------------------------------------------------------------

_OUTPUT_TAGS = ('TITLE', 'META_DESCRIPTION', 'CONTENT', 'FOCUS_KEYWORD', 'FAQS', 'EXCERPT', 'KEY_TAKEAWAYS')


def _raise_if_truncated(response):
    """Detect a hard stop at the token ceiling.

    Truncated output used to be silently salvaged by the unclosed-tag fallback
    and published with broken HTML; now it fails so @retry can regenerate.
    """
    for candidate in getattr(response, 'candidates', None) or []:
        finish_reason = str(getattr(candidate, 'finish_reason', '') or '')
        if 'MAX_TOKENS' in finish_reason.upper():
            raise TruncatedGenerationError(
                f"Model mencapai batas {MAX_OUTPUT_TOKENS} token output; "
                "artikel terpotong di tengah pembuatan."
            )


def _clean_response_text(text):
    text = (text or '').strip()
    if text.startswith('```'):
        text = text.replace('```json', '').replace('```', '').strip()
    # Strip control characters, keeping newlines and tabs.
    return re.sub(r'[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f-\x9f]', '', text)


def _extract_tag(tag, text, default=""):
    match = re.search(f'<{tag}>(.*?)</{tag}>', text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    # Unclosed tag: the model stopped early. Salvage what is there; the quality
    # gate downstream decides whether it is publishable.
    match_open = re.search(f'<{tag}>(.*)', text, re.DOTALL | re.IGNORECASE)
    if match_open:
        logger.warning(f"Tag <{tag}> was not closed in model output; salvaging partial value.")
        return match_open.group(1).strip()
    return default


def _extract_content(response_text):
    content = _extract_tag('CONTENT', response_text) or response_text
    for tag in _OUTPUT_TAGS:
        content = re.sub(f'</?{tag}>', '', content, flags=re.IGNORECASE)
    return content.replace('```html', '').replace('```', '').strip()


def _fallback_title(content):
    first_heading = re.search(r'<h[12][^>]*>(.*?)</h[12]>', content, re.DOTALL | re.IGNORECASE)
    if first_heading:
        return strip_html(first_heading.group(1))[:200]
    return strip_html(content)[:120].rsplit(' ', 1)[0]


def _parse_faqs(faqs_text):
    """Q:/A: pairs. Tolerates a missing trailing newline on the last pair."""
    faqs = []
    if not faqs_text:
        return faqs
    pairs = re.findall(r'Q:\s*(.+?)\s*\n\s*A:\s*(.*?)(?=\n\s*Q:|$)', faqs_text, re.DOTALL)
    for question, answer in pairs:
        question = question.strip()
        answer = strip_html(answer).strip()
        if question and answer:
            faqs.append({"question": question, "answer": answer})
    return faqs


def _parse_takeaways(takeaways_text, content):
    """Takeaways from the model, describing this article; else its own H2 headings.

    Neither path uses a fixed template, so the box differs across posts.
    """
    key_takeaways = []
    for line in (takeaways_text or '').split('\n'):
        line = re.sub(r'^\s*[-*\u2022]\s*', '', line).strip()
        line = strip_html(line)
        if len(line) > 8:
            key_takeaways.append(line)
    return key_takeaways or derive_takeaways(content)


def parse_article_response(response_text, topic, language='id'):
    """Turn the model's tagged output into the article dict (without link URLs)."""
    response_text = _clean_response_text(response_text)
    content = _extract_content(response_text)
    title = _extract_tag('TITLE', response_text) or _fallback_title(content)
    excerpt = _extract_tag('EXCERPT', response_text) or derive_excerpt(content)
    meta_desc = _extract_tag('META_DESCRIPTION', response_text) or excerpt or derive_excerpt(content)

    word_count = len(strip_html(content).split())
    minutes = max(1, word_count // 200)
    reading_time = f"{minutes} min read" if language == 'en' else f"{minutes} menit"

    return {
        "title": title,
        "meta_description": meta_desc,
        "content": content,
        "focus_keyword": _extract_tag('FOCUS_KEYWORD', response_text, default=topic),
        "excerpt": excerpt,
        "reading_time": reading_time,
        "key_takeaways": _parse_takeaways(_extract_tag('KEY_TAKEAWAYS', response_text), content),
        "faqs": _parse_faqs(_extract_tag('FAQS', response_text)),
        "word_count": word_count,
    }


# ---------------------------------------------------------------------------
# Image response helpers
# ---------------------------------------------------------------------------

def _to_webp(image_bytes):
    img = Image.open(BytesIO(image_bytes))
    if img.mode != 'RGB':
        img = img.convert('RGB')
    output = BytesIO()
    img.save(output, format='WEBP', quality=85)
    output.seek(0)
    return output


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


def _response_summary(response):
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


def _is_fatal_image_error(err):
    # Bad key, no permission or unknown model fails the same for every prompt,
    # so do not spend the remaining attempts on it.
    return isinstance(err, genai.errors.APIError) and _genai_status_code(err) in (401, 403, 404)


def _remaining_ms(deadline):
    return int((deadline - time.monotonic()) * 1000)


class ArticleGenerator:
    def __init__(self, api_key, model=DEFAULT_GEMINI_MODEL, image_model=DEFAULT_GEMINI_IMAGE_MODEL):
        self.client = genai.Client(api_key=api_key)
        self.model = model
        self.image_model = image_model

    def generate_checked_article(self, *args, **kwargs):
        """Allow one evidence-preserving correction, never publish rejected output."""
        # Local import: quality_gate imports strip_html from this module.
        from services.quality_gate import check_article

        options = dict(kwargs)
        for attempt in range(2):
            article = self.generate_article(*args, **options)
            ok, errors, _ = check_article(
                article, allowed_link_urls=article.get('allowed_link_urls'))
            if ok:
                return article
            logger.warning('Article quality attempt %s rejected: %s', attempt + 1, '; '.join(errors))
            options['quality_feedback'] = errors
        raise ArticleQualityError(article, errors)

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=4, max=60),
        retry=retry_if_exception(is_retryable_genai_error),
        reraise=True
    )
    def generate_article(self, topic, existing_titles=None, custom_topic=None, seo_data=None, avoid_similar=False,
                         custom_prompt=None, site_name=None, internal_links_context=None, **kwargs):
        language = kwargs.get('language') or 'id'
        prompt, evidence_policy, allowed_link_urls = build_article_prompt(
            topic,
            existing_titles=existing_titles,
            custom_topic=custom_topic,
            seo_data=seo_data,
            avoid_similar=avoid_similar,
            # Accept the prompt under either parameter name.
            custom_prompt=custom_prompt or kwargs.get('custom_article_prompt'),
            site_name=site_name,
            internal_links_context=internal_links_context,
            language=language,
            category_desc=kwargs.get('category_desc'),
            quality_feedback=kwargs.get('quality_feedback'),
        )
        response = self._request_article(prompt, evidence_policy)
        _raise_if_truncated(response)
        article = parse_article_response(response.text, topic, language)
        article['allowed_link_urls'] = allowed_link_urls
        return article

    def _request_article(self, prompt, evidence_policy):
        return self.client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=build_system_instruction(evidence_policy),
                # Kept low: this content makes factual claims, and high
                # temperature was compounding the fabrication problem.
                temperature=0.7,
                top_p=0.9,
                max_output_tokens=MAX_OUTPUT_TOKENS
            )
        )

    def generate_image(self, topic, title, article_content=None, custom_prompt=None, site_name=None, **kwargs):
        """Generate landscape featured image for blog.

        One pass over the fallback prompts, bounded by IMAGE_TIME_BUDGET_SECONDS.
        There is no outer retry: the image is optional, and a wrapper retry around
        the prompt loop multiplied attempts and backoff into many minutes.
        """
        deadline = time.monotonic() + IMAGE_TIME_BUDGET_SECONDS
        try:
            prompts = build_image_prompts(topic, title, custom_prompt, site_name if site_name else "website")
            if self.image_model.startswith('imagen-'):
                attempt, label = self._imagen_attempt, 'Imagen'
            else:
                attempt, label = self._gemini_image_attempt, 'Gemini image'
            return self._run_image_attempts(prompts, attempt, label, deadline)
        except Exception as e:
            logger.error(f"Error generating featured image: {e}", exc_info=True)
            raise Exception(f"Gagal membuat gambar dengan Gemini: {str(e)}")

    def _run_image_attempts(self, prompts, attempt, label, deadline):
        """Try each prompt until one yields an image. Raises when none does."""
        last_error = None
        last_summary = None
        for attempt_name, prompt in prompts:
            if _remaining_ms(deadline) < IMAGE_MIN_ATTEMPT_MS:
                logger.warning(
                    f"Image generation time budget ({IMAGE_TIME_BUDGET_SECONDS}s) exhausted; "
                    f"skipping '{attempt_name}' and remaining prompts."
                )
                break
            try:
                logger.info(f"Generating featured image with {self.image_model} using {attempt_name} prompt")
                image_bytes, summary = attempt(prompt, _remaining_ms(deadline))
                if image_bytes:
                    return _to_webp(image_bytes)
                last_summary = summary
                logger.warning(f"{label} attempt '{attempt_name}' returned no image. {summary}")
            except Exception as attempt_err:
                last_error = attempt_err
                logger.warning(f"{label} attempt '{attempt_name}' failed: {attempt_err}", exc_info=True)
                if _is_fatal_image_error(attempt_err):
                    break

        if last_summary:
            raise Exception(
                "Model tidak menghasilkan gambar setelah mencoba semua prompt cadangan. "
                f"Respons terakhir: {last_summary}"
            )
        if last_error:
            raise last_error
        raise Exception("Model tidak menghasilkan gambar setelah mencoba semua prompt cadangan.")

    def _imagen_attempt(self, prompt, timeout_ms):
        """One Imagen call. Returns (image bytes, None) or (None, response summary)."""
        response = self.client.models.generate_images(
            model=self.image_model,
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
        """One Gemini image call. Returns (image bytes, None) or (None, response summary)."""
        response = self.client.models.generate_content(
            model=self.image_model,
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
        return None, _response_summary(response)
