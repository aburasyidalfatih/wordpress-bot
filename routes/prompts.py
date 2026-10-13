import time

from flask import Blueprint, request, jsonify

import rate_limit
from core_extensions import db, logger, load_config, require_jwt
from models import User, WordPressSite
from services.ai_providers import describe_provider_error, is_retryable_provider_error, text_provider_name
from services.article_generator import ArticleGenerator

prompts_bp = Blueprint('prompts', __name__)

MAX_OPTIMIZE_PROMPT_CHARS = 12000  # default article prompt is ~5000 chars
# Free AI helpers (prompt optimizer, title generator) do not charge credits and
# may run on the admin's shared AI key, so cap how often one user can call them.
AI_HELPER_RATE_LIMIT = 20
AI_HELPER_RATE_WINDOW_SECONDS = 3600
OPTIMIZE_MAX_RETRIES = 3

DEFAULT_ARTICLE_PROMPT = """Buatkan artikel blog SEO-optimized berkualitas tinggi untuk website {target_site} tentang: {topic}
{existing_titles}{research_note}{seo_section}{category_desc_text}{internal_links_text}
TARGET AUDIENCE: {target_audience}

⚠️ PENTING - TAHUN SAAT INI: 2026
- Jika menyebutkan tahun, gunakan 2026 atau "saat ini"
- Jangan gunakan tahun 2024 atau 2025

STRUKTUR ARTIKEL (MINIMAL 2000-2500 KATA - SANGAT WAJIB!):
⚠️ TULIS DENGAN SANGAT MENDETAIL DAN PANJANG. JANGAN MERINGKAS. SETIAP SUB-HEADING HARUS TERDIRI DARI MINIMAL 4-5 PARAGRAF PANJANG DAN KOMPREHENSIF. BENTUKLAH ARTIKEL YANG SANGAT DALAM. JIKA KURANG DARI 2000 KATA, ARTIKEL INI AKAN DITOLAK.

1. HOOK PEMBUKA (100 kata):
   ⚠️ WAJIB VARIATIF - Gunakan salah satu pendekatan ini (JANGAN selalu pakai statistik):
   A. Story/Anekdot: "Pak Budi, kepala sekolah di Bandung, hampir putus asa ketika..."
   B. Problem Statement: "Bayangkan: SPP sudah naik 20%, tapi guru tetap resign..."
   C. Pertanyaan Provokatif: "Apa yang membuat 3 dari 5 sekolah swasta gagal bertahan?"
   D. Fakta Mengejutkan: "Tahun 2026, lebih banyak sekolah tutup daripada yang buka..."
   E. Kontras: "Sekolah A penuh siswa, Sekolah B sepi. Bedanya hanya satu hal..."
   ✓ Akhiri dengan promise: "Artikel ini akan memandu Anda..."
   ✗ JANGAN selalu mulai dengan "Data internal kami di KelasMaster..."

2. RINGKASAN EKSEKUTIF / TL;DR (Kotak AEO untuk Google AI Overviews):
   - WAJIB buat kotak <div class="executive-summary" style="background:#f8fafc; padding:15px; border-left:4px solid #4f46e5; margin-bottom:20px;">
   - Berisi 3 poin bullet (<ul>) yang menjawab inti topik secara langsung.
   - Ini krusial untuk fitur Answer Engine Optimization 2026.

3. CONTEXT (200 kata):
   - Situasi pendidikan Indonesia saat ini terkait topik
   - Mengapa topik ini urgent dan penting
   - Siapa yang paling membutuhkan solusi ini

4. KONTEN UTAMA (1500-1700 kata):
   H2: Konsep Dasar & Pentingnya (300 kata)
   - Definisi clear dengan bahasa praktis
   - Mengapa ini critical untuk lembaga pendidikan
   - Contoh konkret dari sekolah Indonesia

   H2: Implementasi Praktis Step-by-Step (600 kata)
   - Panduan actionable dengan numbered list
   - Timeline realistis (minggu/bulan)
   - Tools/template yang bisa digunakan
   - Checklist untuk memulai

   H2: Studi Kasus Nyata (400 kata)
   - Sekolah X di Kota Y, Indonesia (nama & lokasi realistis)
   - Challenge → Solution → Result (dengan angka spesifik)
   - WAJIB: Quote langsung dari kepala sekolah
     Format: "Quote," ujar Nama Lengkap, Kepala Sekolah X di Kota Y.

   H2: Tips & Best Practices (300 kata)
   - Analisis Perbandingan (Do's and Don'ts atau Mitos vs Fakta) dalam format HTML table
   - Common mistakes yang harus dihindari
   - Quick wins yang bisa langsung diterapkan

4. KESIMPULAN (150 kata):
   - Recap 3-5 key takeaways
   - CTA: ajakan konsultasi/download resource

5. FAQ (150 kata):
   - 3-5 pertanyaan umum dengan jawaban singkat

GAYA PENULISAN & SEO 2026 (SANGAT PENTING):
✓ Tone: Profesional tapi approachable, gunakan "Anda"
✓ Pendekatan Personal (Experience/E-E-A-T): Mulailah salah satu paragraf (misal di Context atau Kesimpulan) dengan "Berdasarkan pengalaman tim praktisi kami..." untuk mensimulasikan Kredensial Penulis (Authoritativeness).
✓ Penekanan Teks (Scannability): WAJIB gunakan teks tebal (<strong>) pada konsep inti, metrik/angka penting, atau kata kunci.
✓ Semantic SEO (Entitas): Gunakan LSI Keyword dan Entitas Semantik secara natural. Hindari pengulangan keyword utama (keyword stuffing). Sisipkan istilah teknis spesifik yang membuktikan keahlian mendalam.
✓ Kalimat (BURSTINESS & PERPLEXITY - 100% HUMAN LIKE):
  - VARIASIKAN panjang kalimat secara drastis untuk ritme natural (Burstiness).
  - Kalimat sangat pendek (2-5 kata): Untuk emphasis/kejutan emosional.
  - Kalimat panjang (25-35 kata): Untuk merangkai logika dan detail mendalam.
  - Gunakan pilihan kata yang tidak tertebak (High Perplexity) tapi tetap natural. Hindari klise.
✓ Contoh selalu dari konteks Indonesia
✓ Transisi natural: "Hasilnya?", "Yang terjadi?", "Faktanya:"
✗ Hindari: "Dengan demikian", "Oleh karena itu", "Pada akhirnya", "Kesimpulannya"
✗ Hindari: "Penting untuk dicatat bahwa...", "Perlu diingat bahwa..."
✗ JANGAN gunakan ASCII art atau Unicode box drawing
✗ Gunakan HTML table (<table>) untuk tabel, BUKAN ASCII art

SEO OPTIMIZATION:
✓ Keyword di first 100 words
✓ Keyword variations di H2 headings
✓ LSI keywords natural throughout
✓ Internal Links: WAJIB sisipkan link internal yang diberikan ke dalam paragraf secara natural (sesuai instruksi di atas).
✓ Optimasi untuk featured snippet (gunakan list/table)

FORMAT OUTPUT (Gunakan XML-Tags berikut):
<TITLE>Judul CTR tinggi dengan angka + power word + benefit (50-60 karakter)</TITLE>
<META_DESCRIPTION>Meta description 150-160 karakter dengan CTA dan keyword</META_DESCRIPTION>
<CONTENT>Konten HTML lengkap 2000-2500 kata</CONTENT>
<FOCUS_KEYWORD>keyword utama artikel</FOCUS_KEYWORD>"""

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

XML_FORMAT_MARKER = "FORMAT OUTPUT (Gunakan XML-Tags berikut):"
FORMAT_MARKER = "FORMAT OUTPUT"

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
3. Pertahankan semua peringatan tahun 2026.
4. Sesuaikan contoh-contoh di Hook Pembuka atau Studi Kasus (jika ada) dengan niche website pengguna secara kreatif.
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
            'default_article_prompt': DEFAULT_ARTICLE_PROMPT,
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
    for marker in (XML_FORMAT_MARKER, FORMAT_MARKER):
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
