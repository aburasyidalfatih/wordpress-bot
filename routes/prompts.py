from flask import Blueprint, request, jsonify
from core_extensions import db, load_config, require_jwt

prompts_bp = Blueprint('prompts', __name__)

@prompts_bp.route('/api/prompts')
@require_jwt
def api_prompts(user_id):
    site_id = request.args.get('site_id', type=int)
    
    if not site_id:
        return jsonify({'success': False, 'error': 'site_id is required'}), 400
        
    with db.get_session() as session:
        from database import WordPressSite
        site = session.query(WordPressSite).filter_by(id=site_id, user_id=user_id).first()
        if not site:
            return jsonify({'success': False, 'error': 'Site not found'}), 404
            
        return jsonify({
            'success': True,
            'config': {
                'article_prompt': site.article_prompt,
                'image_prompt': site.image_prompt
            },
            'default_article_prompt': """Buatkan artikel blog SEO-optimized berkualitas tinggi untuk website kelasmaster.id tentang: {topic}
{existing_titles}{research_note}{seo_section}
TARGET AUDIENCE: Kepala sekolah, founder yayasan, pengelola lembaga pendidikan di Indonesia

⚠️ PENTING - TAHUN SAAT INI: 2026
- Jika menyebutkan tahun, gunakan 2026 atau "saat ini"
- Jangan gunakan tahun 2024 atau 2025

STRUKTUR ARTIKEL (2000-2500 KATA):

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

FORMAT OUTPUT (JSON valid, tanpa markdown code blocks):
{
    "title": "Judul CTR tinggi dengan angka + power word + benefit (50-60 karakter)",
    "meta_description": "Meta description 150-160 karakter dengan CTA dan keyword",
    "content": "Konten HTML lengkap 2000-2500 kata",
    "focus_keyword": "keyword utama artikel",
    "excerpt": "Ringkasan engaging 2-3 kalimat",
    "reading_time": "estimasi menit",
    "key_takeaways": ["takeaway 1", "takeaway 2", "takeaway 3"]
}""",
            'default_image_prompt': """Create a professional featured image for this article about {topic}.

Article Title: "{title}"

Design Requirements:
- Modern, clean design in landscape orientation (16:9) - perfect for blog featured image
- Professional color scheme (blues, greens, education colors)
- Include the title text: "{title}"
- Add relevant visual elements, icons, or illustrations
- "kelasmaster.id" branding subtly placed
- High quality, eye-catching design
- Suitable as blog header/featured image

Style: Modern, professional, suitable for educational blog featured image."""
        })

@prompts_bp.route('/save-prompts', methods=['POST'])
@require_jwt
def save_prompts(user_id):
    site_id = request.form.get('site_id', type=int)
    
    if not site_id:
        return jsonify({'success': False, 'error': 'site_id is required'}), 400
        
    article_prompt = request.form.get('article_prompt')
    image_prompt = request.form.get('image_prompt')
    
    with db.get_session() as session:
        from database import WordPressSite
        site = session.query(WordPressSite).filter_by(id=site_id, user_id=user_id).first()
        if not site:
            return jsonify({'success': False, 'error': 'Site not found'}), 404
            
        site.article_prompt = article_prompt
        site.image_prompt = image_prompt
        session.commit()
        
    return jsonify({'success': True, 'message': 'Prompts saved!'})

@prompts_bp.route('/api/optimize-prompt', methods=['POST'])
@require_jwt
def api_optimize_prompt(user_id):
    data = request.json or {}
    site_id = data.get('site_id')
    prompt_type = data.get('prompt_type', 'article')
    current_prompt = data.get('current_prompt')
    
    if not site_id or not current_prompt:
        return jsonify({'success': False, 'error': 'site_id and current_prompt are required'}), 400
        
    config = load_config(user_id) or {}
    try:
        with db.get_session() as session:
            from database import WordPressSite
            site = session.query(WordPressSite).filter_by(id=site_id, user_id=user_id).first()
            if not site:
                return jsonify({'success': False, 'error': 'Site not found'}), 404
                
            site_name = site.site_name or ''
            site_url = getattr(site, 'wordpress_url', '') or ''
            
            cats = site.categories or []
            categories = ", ".join([c.get('name', '') if isinstance(c, dict) else str(c) for c in cats])
            
            from bot import ArticleGenerator
            
            api_key = config.get('gemini_api_key')
            if not api_key:
                return jsonify({'success': False, 'error': 'API Key Gemini belum diatur di menu Settings.'}), 400
                
            generator = ArticleGenerator(
                api_key, 
                config.get('gemini_model', 'gemini-2.5-pro'),
                config.get('gemini_image_model', 'gemini-3.1-flash-image')
            )
            
            language = site.language or 'id'
            if language == 'en':
                lang_instruction = "6. PENTING: Terjemahkan SELURUH isi teks prompt hasil revisi ke dalam Bahasa Inggris (English), termasuk semua instruksi, pedoman gaya penulisan, peringatan, contoh hook, dan field JSON. KECUALI variabel placeholder seperti {topic} dll yang harus tetap sama."
            else:
                lang_instruction = "6. Pertahankan teks dan instruksi dalam Bahasa Indonesia."

            sys_prompt = f"""Anda adalah ahli Prompt Engineering. Tugas Anda adalah menyesuaikan/merevisi Prompt Template yang diberikan agar spesifik dan relevan dengan niche website pengguna.

Informasi Website Pengguna:
- Nama Website: {site_name}
- URL: {site_url}
- Kategori Konten: {categories}

Instruksi Revisi (SANGAT PENTING):
1. Ganti nama website, target audience, atau konteks niche (misalnya jika ada kata 'kelasmaster.id' atau 'pendidikan' di prompt asli) menjadi sesuai dengan Informasi Website Pengguna di atas.
2. Pertahankan semua variabel placeholder seperti {{topic}}, {{existing_titles}}, {{title}}, dll persis seperti aslinya.
3. Pertahankan semua peringatan tahun 2026.
4. Sesuaikan contoh-contoh di Hook Pembuka atau Studi Kasus (jika ada) dengan niche website pengguna secara kreatif.
5. PERINGATAN FORMAT OUTPUT: Prompt asli memiliki teks instruksi "FORMAT OUTPUT (JSON valid...)" di bagian akhirnya. Anda HARUS mempertahankan teks instruksi tersebut apa adanya di bagian akhir prompt Anda. JANGAN membungkus hasil tulisan Anda ini ke dalam bentuk JSON. Output Anda harus berupa TEKS BIASA (Plain Text) yang berisi keseluruhan template prompt.
{lang_instruction}"""

            response = generator.client.models.generate_content(
                model=generator.model,
                contents=[
                    sys_prompt,
                    f"PROMPT ASLI YANG HARUS DIREVISI:\n{current_prompt}"
                ]
            )
            
            if not response or not hasattr(response, 'text') or not response.text:
                return jsonify({'success': False, 'error': 'Tidak ada respon valid dari Gemini AI.'}), 400
                
            optimized_prompt = response.text.strip()
            # Clean markdown codeblocks if any
            if optimized_prompt.startswith('```'):
                lines = optimized_prompt.split('\n')
                if len(lines) > 2:
                    optimized_prompt = '\n'.join(lines[1:-1])
            
            return jsonify({'success': True, 'optimized_prompt': optimized_prompt})
    except Exception as e:
        from core_extensions import logger
        logger.error(f"Optimize prompt error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 400
