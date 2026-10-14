import html as html_mod
import logging
import re
import time
import unicodedata
from io import BytesIO

from PIL import Image
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception

from services.ai_providers import (
    PROVIDER_LABELS, is_fatal_provider_error, is_retryable_provider_error, make_image_provider,
    make_text_provider,
)
from services.article_prompts import build_article_prompt, build_image_prompts, build_system_instruction

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


def is_retryable_genai_error(exc):
    """Retry only failures that can succeed on a second try (any provider).

    4xx errors (invalid key, permission, unknown model, bad request) fail
    identically every time; truncation, 429, 5xx and network errors are transient.
    """
    if isinstance(exc, TruncatedGenerationError):
        return True
    return is_retryable_provider_error(exc)


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


def _raise_truncated():
    """Truncated output used to be silently salvaged by the unclosed-tag fallback
    and published with broken HTML; now it fails so @retry can regenerate."""
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


def _remaining_ms(deadline):
    return int((deadline - time.monotonic()) * 1000)


class ArticleGenerator:
    """Writes articles and featured images with the configured AI providers.

    `text` / `image` are services.ai_providers instances; build them from the
    stored AI config with from_config(). The image provider is created lazily so
    a missing image key does not block text-only work (titles, prompt help).
    """

    def __init__(self, text_provider, image_provider=None, image_factory=None):
        self.text = text_provider
        self._image = image_provider
        self._image_factory = image_factory

    @classmethod
    def from_config(cls, config):
        return cls(make_text_provider(config), image_factory=lambda: make_image_provider(config))

    @property
    def image(self):
        if self._image is None and self._image_factory is not None:
            self._image = self._image_factory()
        return self._image

    @property
    def model(self):
        return self.text.model

    @property
    def image_model(self):
        return self.image.model

    def generate_text(self, prompt, system=None, max_tokens=8192, raise_on_truncation=False):
        """Plain text completion for research titles, prompt helpers and the review.

        raise_on_truncation=True raises TruncatedGenerationError when the model hit
        max_tokens, for callers that cannot use a cut-off reply (JSON).
        """
        result = self.text.generate(prompt, system=system, max_tokens=max_tokens)
        if raise_on_truncation and result.truncated:
            raise TruncatedGenerationError(
                f"Model mencapai batas {max_tokens} token output; jawaban terpotong."
            )
        return result.text

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
        result = self._request_article(prompt, evidence_policy)
        if result.truncated:
            _raise_truncated()
        article = parse_article_response(result.text, topic, language)
        article['allowed_link_urls'] = allowed_link_urls
        return article

    def _request_article(self, prompt, evidence_policy):
        return self.text.generate(
            prompt,
            system=build_system_instruction(evidence_policy),
            max_tokens=MAX_OUTPUT_TOKENS,
            # Kept low where the provider supports it (Gemini): this content
            # makes factual claims, and high temperature was compounding the
            # fabrication problem.
            temperature=0.7,
            top_p=0.9,
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
            image = self.image
            label = f"{PROVIDER_LABELS.get(image.provider, image.provider)} image"
            return self._run_image_attempts(prompts, image.attempt, label, deadline)
        except Exception as e:
            logger.error(f"Error generating featured image: {e}", exc_info=True)
            provider = getattr(self._image, 'provider', None)
            raise Exception(f"Gagal membuat gambar dengan {PROVIDER_LABELS.get(provider, 'AI')}: {str(e)}")

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
                if is_fatal_provider_error(attempt_err):
                    break

        if last_summary:
            raise Exception(
                "Model tidak menghasilkan gambar setelah mencoba semua prompt cadangan. "
                f"Respons terakhir: {last_summary}"
            )
        if last_error:
            raise last_error
        raise Exception("Model tidak menghasilkan gambar setelah mencoba semua prompt cadangan.")
