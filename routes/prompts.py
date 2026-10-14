import time

from flask import Blueprint, request, jsonify

import rate_limit
from core_extensions import db, logger, load_config, require_jwt
from models import User, WordPressSite
from services.ai_providers import describe_provider_error, is_retryable_provider_error, text_provider_name
from services.article_generator import ArticleGenerator
from services.default_prompts import FORMAT_MARKER_EN, FORMAT_MARKER_ID, default_article_prompt

prompts_bp = Blueprint('prompts', __name__)

MAX_OPTIMIZE_PROMPT_CHARS = 12000  # default article prompt is ~4500 chars
# Free AI helpers (prompt optimizer, title generator) do not charge credits and
# may run on the admin's shared AI key, so cap how often one user can call them.
AI_HELPER_RATE_LIMIT = 20
AI_HELPER_RATE_WINDOW_SECONDS = 3600
OPTIMIZE_MAX_RETRIES = 3

# The default article prompt shown in the UI is default_article_prompt(site
# language) from services/default_prompts.py: the same text the generator uses
# when a site has no custom prompt.

DEFAULT_IMAGE_PROMPT = """Create a professional featured image for this article about {topic}.

Article Title: "{title}"

Design Requirements:
- Modern, clean design in landscape orientation (16:9) - perfect for blog featured image
- Professional color scheme (blues, greens, education colors)
- Include the title text: "{title}"
- Add relevant visual elements, icons, or illustrations
- "{target_site}" branding subtly placed
- High quality, eye-catching design
- Suitable as blog header/featured image

Style: Modern, professional, suitable for educational blog featured image."""

XML_FORMAT_MARKER = FORMAT_MARKER_ID
FORMAT_MARKER = "FORMAT OUTPUT"
# English prompts head the section "OUTPUT FORMAT"; checked after the Indonesian markers.
FORMAT_MARKER_EN_SHORT = "OUTPUT FORMAT"

OPTIMIZER_LANG_INSTRUCTION_EN = "6. PENTING: Terjemahkan SELURUH isi teks prompt hasil revisi ke dalam Bahasa Inggris (English), termasuk semua instruksi, pedoman gaya penulisan, peringatan, dan contoh hook. KECUALI variabel placeholder seperti {topic} dll yang harus tetap sama. (Khusus Image Prompt, wajib dalam Bahasa Inggris karena model AI gambar hanya mendukung Bahasa Inggris)."
OPTIMIZER_LANG_INSTRUCTION_ID = "6. Pertahankan teks dan instruksi dalam Bahasa Indonesia."
OPTIMIZER_FORMAT_INSTRUCTION_ARTICLE = "5. PERINGATAN: Bagian 'FORMAT OUTPUT' telah dipisahkan oleh sistem. Anda HANYA bertugas merevisi isi template bagian atasnya saja. JANGAN membuat blok format (JSON/XML) atau menyebutkan FORMAT OUTPUT sama sekali dalam respon Anda."
OPTIMIZER_FORMAT_INSTRUCTION_OTHER = "5. PERINGATAN FORMAT OUTPUT: JANGAN membungkus hasil tulisan Anda ini ke dalam bentuk JSON atau XML. Output Anda harus berupa TEKS BIASA (Plain Text) yang berisi keseluruhan template prompt gambar. JANGAN MENAMBAHKAN instruksi format apapun di akhir prompt."

OPTIMIZER_SYSTEM_PROMPT = """Anda adalah ahli Prompt Engineering. Tugas Anda adalah menyesuaikan/merevisi Prompt Template yang diberikan agar spesifik dan relevan dengan niche website pengguna.

Informasi Website Pengguna:
- Nama Website: {site_name}
- URL: {site_url}
- Kategori Konten: {categories}

Instruksi Revisi (SANGAT PENTING):
1. Ganti nama website, target audience, atau konteks niche (misalnya jika ada kata 'kelasmaster.id' atau 'pendidikan' di prompt asli) menjadi sesuai dengan Informasi Website Pengguna di atas.
2. Pertahankan semua variabel placeholder seperti {{topic}}, {{existing_titles}}, {{title}}, dll persis seperti aslinya.
3. Pertahankan aturan akurasi dan sumber (tidak mengarang data, kutipan, atau studi kasus; hanya menautkan URL yang diberikan), kehati-hatian untuk topik keuangan/kesehatan/hukum, serta aturan judul dan FAQ.
4. JANGAN menambahkan target jumlah kata, kerangka heading tetap, tahun tertentu, formula judul clickbait, atau hook pembuka template. Sesuaikan contoh (jika ada) dengan niche website pengguna.
{format_instruction}
{lang_instruction}"""


def check_ai_helper_quota(user_id, bucket='ai_helper', limit=None):
    """Gate uncharged AI helper calls.

    Returns None when the call may proceed, otherwise a (response, status)
    tuple to return from the route. Users whose active text provider runs on
    their own key pay for the calls themselves and are not limited.
    """
    try:
        own_key = (load_config(user_id) or {}).get('own_ai_key')
    except Exception as exc:
        logger.error(f'Could not load config for AI helper quota (user {user_id}): {exc}')
        own_key = None
    if own_key:
        return None

    # Without their own key the call is paid by the admin key; only users
    # with credits may use it.
    with db.get_session() as session:
        user = session.query(User).filter_by(id=user_id).first()
        credits = (user.credits or 0) if user else 0
    if credits <= 0:
        return jsonify({
            'success': False,
            'error': 'Kredit tidak mencukupi. Silakan isi kredit terlebih dahulu.'
        }), 402

    allowed, retry_sec = rate_limit.hit(
        f'ratelimit:{bucket}:{user_id}', limit or AI_HELPER_RATE_LIMIT, AI_HELPER_RATE_WINDOW_SECONDS
    )
    if not allowed:
        return jsonify({
            'success': False,
            'error': f'Terlalu banyak permintaan AI. Coba lagi dalam {retry_sec // 60 + 1} menit.'
        }), 429
    return None


@prompts_bp.route('/api/prompts')
@require_jwt
def api_prompts(user_id):
    site_id = request.args.get('site_id', type=int)

    if not site_id:
        return jsonify({'success': False, 'error': 'site_id wajib diisi.'}), 400

    with db.get_session() as session:
        site = session.query(WordPressSite).filter_by(id=site_id, user_id=user_id).first()
        if not site:
            return jsonify({'success': False, 'error': 'Website tidak ditemukan.'}), 404

        return jsonify({
            'success': True,
            'config': {
                'article_prompt': site.article_prompt,
                'image_prompt': site.image_prompt
            },
            'default_article_prompt': default_article_prompt(site.language or 'id'),
            'default_image_prompt': DEFAULT_IMAGE_PROMPT,
        })


@prompts_bp.route('/api/save-prompts', methods=['POST'])
@require_jwt
def save_prompts(user_id):
    site_id = request.form.get('site_id', type=int)

    if not site_id:
        return jsonify({'success': False, 'error': 'site_id wajib diisi.'}), 400

    article_prompt = request.form.get('article_prompt')
    image_prompt = request.form.get('image_prompt')

    with db.get_session() as session:
        site = session.query(WordPressSite).filter_by(id=site_id, user_id=user_id).first()
        if not site:
            return jsonify({'success': False, 'error': 'Website tidak ditemukan.'}), 404

        site.article_prompt = article_prompt
        site.image_prompt = image_prompt
        session.commit()

    return jsonify({'success': True, 'message': 'Prompt berhasil disimpan!'})


def _split_output_format(prompt, prompt_type):
    """Separate the OUTPUT FORMAT section so the AI cannot rewrite it.

    Returns (prompt_without_format, format_section_to_reattach). Image prompts
    drop the section entirely.
    """
    for marker in (XML_FORMAT_MARKER, FORMAT_MARKER_EN, FORMAT_MARKER, FORMAT_MARKER_EN_SHORT):
        if marker in prompt:
            parts = prompt.split(marker)
            format_part = "\n\n" + marker + parts[1] if prompt_type != 'image' else ""
            return parts[0].strip(), format_part
    return prompt, ""


def _optimizer_system_prompt(site, prompt_type):
    categories = ", ".join(
        c.get('name', '') if isinstance(c, dict) else str(c) for c in (site.categories or [])
    )
    language = site.language or 'id'
    if language == 'en' or prompt_type == 'image':
        lang_instruction = OPTIMIZER_LANG_INSTRUCTION_EN
    else:
        lang_instruction = OPTIMIZER_LANG_INSTRUCTION_ID
    if prompt_type == 'article':
        format_instruction = OPTIMIZER_FORMAT_INSTRUCTION_ARTICLE
    else:
        format_instruction = OPTIMIZER_FORMAT_INSTRUCTION_OTHER
    return OPTIMIZER_SYSTEM_PROMPT.format(
        site_name=site.site_name or '',
        site_url=getattr(site, 'wordpress_url', '') or '',
        categories=categories,
        format_instruction=format_instruction,
        lang_instruction=lang_instruction,
    )


def _generate_with_retry(generator, prompt, system):
    """Call the text provider, retrying transient errors with a growing pause."""
    for attempt in range(OPTIMIZE_MAX_RETRIES):
        try:
            return generator.generate_text(prompt, system=system)
        except Exception as e:
            if is_retryable_provider_error(e) and attempt < OPTIMIZE_MAX_RETRIES - 1:
                time.sleep(2 * (attempt + 1))
                continue
            raise
    return None


def _strip_code_fence(text):
    if text.startswith('```'):
        lines = text.split('\n')
        if len(lines) > 2:
            return '\n'.join(lines[1:-1]).strip()
    return text


def _optimize_error_message(error, provider):
    return describe_provider_error(error, provider) or "Gagal mengoptimasi prompt. Silakan coba lagi."


@prompts_bp.route('/api/optimize-prompt', methods=['POST'])
@require_jwt
def api_optimize_prompt(user_id):
    data = request.get_json(silent=True) or {}
    site_id = data.get('site_id')
    prompt_type = data.get('prompt_type', 'article')
    current_prompt = data.get('current_prompt')

    if not site_id or not current_prompt or not isinstance(current_prompt, str):
        return jsonify({'success': False, 'error': 'site_id dan current_prompt wajib diisi.'}), 400
    if len(current_prompt) > MAX_OPTIMIZE_PROMPT_CHARS:
        return jsonify({'success': False, 'error': f'Prompt terlalu panjang (maksimal {MAX_OPTIMIZE_PROMPT_CHARS} karakter).'}), 400

    with db.get_session() as session:
        if not session.query(WordPressSite.id).filter_by(id=site_id, user_id=user_id).first():
            return jsonify({'success': False, 'error': 'Website tidak ditemukan.'}), 404

    quota_error = check_ai_helper_quota(user_id)
    if quota_error:
        return quota_error

    current_prompt, xml_format_part = _split_output_format(current_prompt, prompt_type)

    config = load_config(user_id) or {}
    try:
        with db.get_session() as session:
            site = session.query(WordPressSite).filter_by(id=site_id, user_id=user_id).first()
            if not site:
                return jsonify({'success': False, 'error': 'Website tidak ditemukan.'}), 404

            sys_prompt = _optimizer_system_prompt(site, prompt_type)

        generator = ArticleGenerator.from_config(config)
        response_text = _generate_with_retry(
            generator, f"PROMPT ASLI YANG HARUS DIREVISI:\n{current_prompt}", sys_prompt
        )
        if not response_text:
            return jsonify({'success': False, 'error': 'Tidak ada respons yang valid dari AI.'}), 400

        # Re-attach the exact OUTPUT FORMAT section the user wrote.
        optimized_prompt = _strip_code_fence(response_text.strip()) + xml_format_part
        return jsonify({'success': True, 'optimized_prompt': optimized_prompt})
    except Exception as e:
        logger.error(f"Optimize prompt error: {e}")
        return jsonify({'success': False, 'error': _optimize_error_message(e, text_provider_name(config))}), 400
