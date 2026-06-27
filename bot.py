from google import genai
from google.genai import types
import requests
import base64
import json
from io import BytesIO
from PIL import Image
import time
import logging
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

logger = logging.getLogger(__name__)

def sanitize_filename(name):
    import re
    import unicodedata
    name = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode('ascii')
    name = re.sub(r'[^a-zA-Z0-9._-]', '-', name)
    name = re.sub(r'-+', '-', name)
    return name.strip('-')

class ArticleGenerator:
    def __init__(self, api_key, model='gemini-3.5-flash', image_model='gemini-3.1-flash-image'):
        self.client = genai.Client(api_key=api_key)
        self.model = model
        self.image_model = image_model
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((requests.exceptions.RequestException, Exception))
    )
    def generate_article(self, topic, existing_titles=None, custom_topic=None, seo_data=None, avoid_similar=False, custom_prompt=None, site_name=None, **kwargs):
        # Resolve custom prompt from either parameter name
        custom_prompt = custom_prompt or kwargs.get('custom_article_prompt')
        language = kwargs.get('language') or 'id'
        target_site = site_name if site_name else "kelasmaster.id"
        
        if language == 'en':
            target_audience = f"Readers of website {target_site}"
        else:
            target_audience = "Kepala sekolah, founder yayasan, pengelola lembaga pendidikan di Indonesia" if target_site == "kelasmaster.id" else f"Pembaca website {target_site}"
        
        # Context mapping untuk setiap kategori
        context_map = {
            'Digitalisasi Pendidikan': 'transformasi digital sekolah, sistem informasi manajemen pendidikan, platform pembelajaran online, administrasi paperless, teknologi pendidikan',
            'Strategi Pemasaran': 'digital marketing sekolah, social media strategy, branding lembaga pendidikan, student recruitment, SEO website sekolah, promosi online',
            'Pengembangan Kurikulum': 'Kurikulum Merdeka, implementasi kurikulum, student-centered learning, assessment methods, pelatihan guru, IHT',
            'Manajemen Keuangan': 'manajemen keuangan sekolah, budgeting pendidikan, transparansi keuangan, software akuntansi, ISAK 35 compliance',
            'Legalitas Dan Perizinan': 'izin operasional sekolah, akreditasi, compliance regulasi pendidikan, dokumen legal lembaga',
            'Manajemen SDM': 'rekrutmen guru, performance management, teacher training, retention strategy, pengembangan SDM pendidikan',
            'Layanan Orang Tua': 'komunikasi sekolah-orang tua, parent engagement, sistem informasi orang tua, keterlibatan keluarga',
            'Pembuatan SOP': 'standar operasional prosedur sekolah, dokumentasi proses, quality assurance pendidikan',
            'Manajemen Asrama': 'pengelolaan asrama, boarding school management, kesejahteraan siswa asrama',
            'Unit Usaha Sekolah': 'kewirausahaan sekolah, income generating activities, koperasi sekolah, bisnis unit pendidikan',
            'Hotnews Pendidikan': 'berita viral pendidikan, trending education news, isu pendidikan terkini, viral education stories, hot topics pendidikan Indonesia',
            'Biaya Pendidikan': 'biaya sekolah swasta, biaya masuk universitas, PSB pendaftaran siswa baru, biaya kuliah, beasiswa pendidikan, informasi biaya pendidikan Indonesia'
        }

        context_map_en = {
            'Digitalisasi Pendidikan': 'school digital transformation, education management information system, online learning platform, paperless administration, edtech',
            'Strategi Pemasaran': 'school digital marketing, social media strategy, education branding, student recruitment, school website SEO, online promotion',
            'Pengembangan Kurikulum': 'curriculum implementation, student-centered learning, assessment methods, teacher training, professional development',
            'Manajemen Keuangan': 'school financial management, education budgeting, financial transparency, accounting software, compliance',
            'Legalitas Dan Perizinan': 'school operational permit, accreditation, educational regulation compliance, legal documents',
            'Manajemen SDM': 'teacher recruitment, performance management, teacher training, retention strategy, educational HR development',
            'Layanan Orang Tua': 'school-parent communication, parent engagement, parent information system, family involvement',
            'Pembuatan SOP': 'school standard operating procedures, process documentation, educational quality assurance',
            'Manajemen Asrama': 'dormitory management, boarding school management, student welfare',
            'Unit Usaha Sekolah': 'school entrepreneurship, income generating activities, school cooperative, education business unit',
            'Hotnews Pendidikan': 'viral education news, trending education news, current education issues, viral education stories, hot topics in education',
            'Biaya Pendidikan': 'private school fees, university admission fees, student enrollment, tuition fees, scholarships, education cost information'
        }

        context_map_en_keys = {
            'Digital Education': 'school digital transformation, education management information system, online learning platform, paperless administration, edtech',
            'Marketing Strategy': 'school digital marketing, social media strategy, education branding, student recruitment, school website SEO, online promotion',
            'Curriculum Development': 'curriculum implementation, student-centered learning, assessment methods, teacher training, professional development',
            'Financial Management': 'school financial management, education budgeting, financial transparency, accounting software, compliance',
            'Legality and Licensing': 'school operational permit, accreditation, educational regulation compliance, legal documents',
            'HR Management': 'teacher recruitment, performance management, teacher training, retention strategy, educational HR development',
            'Parent Services': 'school-parent communication, parent engagement, parent information system, family involvement',
            'SOP Creation': 'school standard operating procedures, process documentation, educational quality assurance',
            'Dormitory Management': 'dormitory management, boarding school management, student welfare',
            'School Business Unit': 'school entrepreneurship, income generating activities, school cooperative, education business unit',
            'Education Hotnews': 'viral education news, trending education news, current education issues, viral education stories, hot topics in education',
            'Education Cost': 'private school fees, university admission fees, student enrollment, tuition fees, scholarships, education cost information'
        }
        
        context = topic
        if language == 'en':
            found = False
            for k, v in context_map_en_keys.items():
                if k.lower() == topic.lower():
                    context = v
                    found = True
                    break
            if not found:
                for k, v in context_map_en.items():
                    if k.lower() == topic.lower():
                        context = v
                        break
        else:
            for k, v in context_map.items():
                if k.lower() == topic.lower():
                    context = v
                    break
        
        # Add existing titles to prompt to avoid duplicates
        existing_titles_text = ""
        if existing_titles:
            if language == 'en':
                if avoid_similar:
                    existing_titles_text = f"\n\n⚠️ CRITICAL - TITLES MUST BE VERY DIFFERENT:\n"
                    existing_titles_text += "Previous titles are too similar. Create a TRULY UNIQUE title with a different angle/perspective!\n\n"
                    existing_titles_text += "Titles to AVOID:\n"
                else:
                    existing_titles_text = f"\n\n⚠️ IMPORTANT - AVOID EXISTING TITLES:\n"
                
                for title in existing_titles[-10:]:
                    existing_titles_text += f"- {title}\n"
                
                if avoid_similar:
                    existing_titles_text += "\n💡 TIPS FOR UNIQUE TITLES:\n"
                    existing_titles_text += "- Use different angles (e.g., from customer's perspective, manager's perspective, general public)\n"
                    existing_titles_text += "- Focus on specific aspects not yet discussed\n"
                    existing_titles_text += "- Use different formats (guide, checklist, case study, analysis, etc.)\n"
                    existing_titles_text += "- Add specific context (location, time, situation)\n\n"
                else:
                    existing_titles_text += "\nThe article title MUST be different and unique from the list above!\n"
            else:
                if avoid_similar:
                    existing_titles_text = f"\n\n⚠️ CRITICAL - JUDUL HARUS SANGAT BERBEDA:\n"
                    existing_titles_text += "Judul sebelumnya terlalu mirip. Buat judul yang BENAR-BENAR UNIK dengan angle/perspektif berbeda!\n\n"
                    existing_titles_text += "Judul yang HARUS DIHINDARI:\n"
                else:
                    existing_titles_text = f"\n\n⚠️ PENTING - HINDARI JUDUL YANG SUDAH ADA:\n"
                
                for title in existing_titles[-10:]:  # Last 10 titles
                    existing_titles_text += f"- {title}\n"
                
                if avoid_similar:
                    existing_titles_text += "\n💡 TIPS MEMBUAT JUDUL UNIK:\n"
                    existing_titles_text += "- Gunakan angle berbeda (misalnya: dari sisi orang tua, dari sisi guru, dari sisi siswa)\n"
                    existing_titles_text += "- Fokus pada aspek spesifik yang belum dibahas\n"
                    existing_titles_text += "- Gunakan format berbeda (panduan, checklist, studi kasus, analisis, dll)\n"
                    existing_titles_text += "- Tambahkan konteks spesifik (lokasi, waktu, situasi)\n\n"
                else:
                    existing_titles_text += "\nJudul artikel HARUS berbeda dan unik dari daftar di atas!\n"
        
        # Add custom topic from research if available
        topic_focus = custom_topic if custom_topic else topic
        if language == 'en':
            research_note = f"\n\n🔥 TRENDING TOPIC: {custom_topic}\nFocus the article on this trending topic within the context of {topic}.\n" if custom_topic else ""
        else:
            research_note = f"\n\n🔥 TRENDING TOPIC: {custom_topic}\nFokuskan artikel pada topik trending ini dalam konteks {topic}.\n" if custom_topic else ""
        
        # Add SEO data if available
        seo_section = ""
        if seo_data:
            keywords = seo_data.get('keywords', [])
            questions = seo_data.get('questions', [])
            semantic_context = seo_data.get('semantic_context', "")
            news_insights = seo_data.get('news_insights', [])
            
            if semantic_context:
                if language == 'en':
                    seo_section += f"\n\n📚 SEMANTIC CONTEXT (Wikipedia Background):\n{semantic_context}\n"
                else:
                    seo_section += f"\n\n📚 KONTEKS SEMANTIK (Latar Belakang Wikipedia):\n{semantic_context}\n"
                    
            if news_insights:
                if language == 'en':
                    seo_section += f"\n\n📰 LATEST NEWS (Incorporate these current events as 'Angle'):\n"
                else:
                    seo_section += f"\n\n📰 BERITA TERKINI (Gunakan sebagai 'Angle' Kekinian):\n"
                for news in news_insights:
                    seo_section += f"- {news}\n"
                    
            if keywords:
                if language == 'en':
                    seo_section += f"\n\n🔑 RELATED KEYWORDS (use naturally in the article):\n"
                else:
                    seo_section += f"\n\n🔑 RELATED KEYWORDS (gunakan natural di artikel):\n"
                for kw in keywords[:10]:
                    seo_section += f"- {kw}\n"
            
            if questions:
                if language == 'en':
                    seo_section += f"\n\n❓ FREQUENTLY ASKED QUESTIONS (answer in the article):\n"
                else:
                    seo_section += f"\n\n❓ PERTANYAAN YANG SERING DICARI (jawab di artikel):\n"
                for q in questions[:5]:
                    seo_section += f"- {q}\n"
                if language == 'en':
                    seo_section += "\n💡 Ensure the article answers these questions comprehensively!\n"
                else:
                    seo_section += "\n💡 Pastikan artikel menjawab pertanyaan-pertanyaan ini secara lengkap!\n"
                    
            competitor_outlines = seo_data.get('competitor_outlines', [])
            if competitor_outlines:
                if language == 'en':
                    seo_section += f"\n\n⚔️ COMPETITOR ANALYSIS (Top Ranking Pages):\n"
                else:
                    seo_section += f"\n\n⚔️ ANALISIS KOMPETITOR (Halaman Ranking Atas):\n"
                for comp in competitor_outlines[:3]:
                    headers_str = ", ".join(comp.get('headers', [])[:5])
                    seo_section += f"- Competitor '{comp.get('title')}' covers: {headers_str}\n"
                if language == 'en':
                    seo_section += "💡 MANDATORY: Your article MUST be more comprehensive, detailed, and cover angles these competitors missed!\n"
                else:
                    seo_section += "💡 WAJIB: Artikelmu HARUS lebih komprehensif, lebih detail, dan membahas sudut pandang yang dilewatkan oleh kompetitor ini!\n"
                    
            social_insights = seo_data.get('social_insights', [])
            if social_insights:
                if language == 'en':
                    seo_section += f"\n\n🗣️ REAL AUDIENCE INSIGHTS (Quora/Reddit Discussions):\n"
                else:
                    seo_section += f"\n\n🗣️ KELUHAN AUDIENS ASLI (Diskusi Quora/Reddit):\n"
                for insight in social_insights[:5]:
                    seo_section += f"- {insight}\n"
                if language == 'en':
                    seo_section += "💡 Address these real pain points and questions directly in your content.\n"
                else:
                    seo_section += "💡 Jawab keresahan dan masalah nyata dari manusia-manusia ini ke dalam artikelmu.\n"
                    
            youtube_insights = seo_data.get('youtube_insights', [])
            if youtube_insights:
                if language == 'en':
                    seo_section += f"\n\n🎥 YOUTUBE EXPERT INSIGHTS (Transcripts from top videos):\n"
                else:
                    seo_section += f"\n\n🎥 WAWASAN PAKAR YOUTUBE (Transkrip dari video teratas):\n"
                for yt in youtube_insights[:2]:
                    seo_section += f"- Video '{yt.get('title')}': \"{yt.get('snippets')}\"\n"
                if language == 'en':
                    seo_section += "💡 Weave these expert insights naturally into the article to boost E-E-A-T signals.\n"
                else:
                    seo_section += "💡 Selipkan wawasan dari transkrip video ini agar artikelmu memiliki sudut pandang praktisi (E-E-A-T).\n"
        
        category_desc_text = ""
        category_desc = kwargs.get('category_desc')
        if category_desc:
            if language == 'en':
                category_desc_text = f"\n\n📂 CATEGORY DESCRIPTION / WRITING INSTRUCTIONS:\n{category_desc}\nFollow these category instructions and focus the article style and scope on this description."
            else:
                category_desc_text = f"\n\n📂 DESKRIPSI KATEGORI / PETUNJUK PENULISAN:\n{category_desc}\nIkuti petunjuk kategori ini dan fokuskan gaya serta ruang lingkup artikel pada deskripsi tersebut."

        if language == 'en':
            prompt = f"""Write a high-quality, SEO-optimized blog article for the website {target_site} about: {topic_focus}
{existing_titles_text}{research_note}{seo_section}{category_desc_text}
TARGET AUDIENCE: {target_audience}
RELATED KEYWORDS: {context}

⚠️ IMPORTANT - CURRENT YEAR: 2026
- If mentioning years, use 2026 or "currently"
- Do not use the year 2024 or 2025
- Example: "Complete Guide 2026" or "Latest Strategies"

ARTICLE STRUCTURE (2000-2500 WORDS):

1. INTRODUCTORY HOOK (100 words):
   ⚠️ MUST BE VARIATIVE - Use one of these approaches (DO NOT always use statistics):
   
   A. Story/Anecdote: "John, a manager in London, was almost desperate when..."
   B. Problem Statement: "Imagine: Your costs went up by 20%, but your retention is dropping..."
   C. Provocative Question: "What makes 3 out of 5 startups fail to survive?"
   D. Surprising Fact: "In 2026, more businesses are closing than opening..."
   E. Contrast: "Company A is full of customers, Company B is empty. The difference is only one thing..."
   
   ✓ End with a promise: "This article will guide you..."
   ✗ DO NOT always start with the same pattern
   ✗ DO NOT use the same opening pattern as previous articles

2. EXECUTIVE SUMMARY / TL;DR (AEO Box for Google AI Overviews):
   - MUST create a box `<div class="executive-summary" style="background:#f8fafc; padding:15px; border-left:4px solid #4f46e5; margin-bottom:20px;">`
   - Contains 3 bullet points (`<ul>`) answering the core topic directly.
   - This is crucial for Answer Engine Optimization 2026.

3. CONTEXT (200 words):
   - Current global or relevant regional situation related to the topic
   - Why this topic is urgent and important
   - Who needs this solution the most

3. MAIN CONTENT (1500-1700 words):
   
   H2: Core Concept & Importance (300 words)
   - Clear definition with practical language
   - Why this is critical for the target audience/organization
   - Concrete real-world examples
   
   H2: Step-by-Step Practical Implementation (600 words)
   - Actionable guide with a numbered list
   - Realistic timeline (weeks/months)
   - Tools/templates that can be used
   - Checklist to get started
   - Budget estimation if relevant
   
   H2: Real-World Case Study (400 words)
   - Real-world or highly realistic company/organization (realistic name & location)
   - Challenge → Solution → Result (with specific numbers)
   - Lesson learned that can be applied
   - MUST: Direct quote from a manager/expert (make it realistic & natural)
     Format: "engaging and specific quote," says Full Name, Title at Organization in City.
     Example: "Initially we were hesitant, but after 3 months of implementation, our efficiency went up by 40%," says Robert Chen, Operations Director at TechCorp in Chicago.
   
   H2: Tips & Best Practices (300 words)
   - Do's and Don'ts in an HTML table format (DO NOT use ASCII art or Unicode box drawing)
   - Common mistakes to avoid
   - Pro tips from practitioners (can add a short quote)
   - Quick wins that can be applied immediately

4. CONCLUSION (150 words):
   - Recap 3-5 key takeaways
   - Clear next action steps
   - CTA: invitation to consult/download resource

5. FAQ (150 words):
   - 3-5 common questions with short answers
   - Use Q&A format

QUALITY REQUIREMENTS:

E-E-A-T SIGNALS (MUST):
✓ Experience: "Based on implementation across 50+ organizations..."
✓ Expertise: Reference to industry standards, regulations, or research
✓ Authoritativeness: Statistical data
✓ Trustworthiness: Transparency (pros & cons), update date
✓ Current: Use the year 2026 for current context

WRITING STYLE & SEO 2026:
✓ Tone: Professional but approachable, use "you"
✓ Personal Approach (E-E-A-T): Start a paragraph with "Based on our practitioners' experience..." to simulate Authoritativeness.
✓ Text Emphasis (Scannability): MUST use bold text (<strong>) on core concepts, important metrics/numbers, or key terms.
✓ Semantic SEO (Entities): Use LSI Keywords and Semantic Entities naturally. Insert specific technical terms that prove deep expertise. DO NOT keyword stuff.
✓ Sentences (BURSTINESS & PERPLEXITY - 100% HUMAN LIKE):
  - VARY sentence length drastically for a natural rhythm (Burstiness).
  - Very short sentences (2-5 words): For emotional emphasis/surprise. "That's wrong." "The opposite is true."
  - Medium sentences (15-20 words): For standard explanations.
  - Long sentences (25-35 words): To string together deep logic and details.
  - Use unpredictable word choices (High Perplexity) but keep it natural. Avoid clichés.
✓ Paragraphs: EXTREMELY SHORT. Maximum 2-3 sentences per paragraph. Frequently use 1-sentence paragraphs. MUST use many line breaks (enter) so there is plenty of whitespace to inject ADS.
✓ Examples: Always from a realistic context with specific names
✓ Data: Include relevant statistics/numbers (but VARY the sources)
✓ Empathy: Understand the pain points of the target audience
✓ Quotes: Insert 1-2 realistic quotes from practitioners
✓ Transitions: Use natural transitions, avoid repetitive connector phrases

⚠️ AVOID REPETITIVE & AI-LIKE PHRASES:
✗ "Our internal data shows...", "Based on our experience..."
✗ "It is important to note that...", "Keep in mind that..."
✗ "In this context...", "It is crucial to..."
✗ "Let's discuss...", "In conclusion..."
✓ Use variation: recent research, case studies, real stories, questions, etc.
✓ Every article MUST have a UNIQUE and DIFFERENT opening
✓ Use conversational language, not overly formal/academic

SEO OPTIMIZATION:
✓ Keyword in first 100 words
✓ Keyword variations in H2 headings
✓ LSI keywords naturally throughout
✓ Related posts will appear automatically (no need for manual links)
✓ Optimize for featured snippets (use lists/tables)

⚠️ STRICT PROHIBITIONS:
✗ DO NOT use placeholders like [FLOWCHART: ...], [INFOGRAPHIC: ...], [CHECKLIST: ...]
✗ DO NOT use ASCII art or Unicode box drawing characters (─, │, ┼, ├, ┤, etc.)
✗ DO NOT insert JSON artifacts or metadata inside the content
✗ Use HTML table (<table>) for tables, NOT ASCII art
✗ If you want a checklist, use <ul> or <ol>, NOT placeholders

OUTPUT FORMAT (JSON):
{{
    "title": "Title with high CTR formula (50-60 characters):
    
    REQUIRED FORMULA (choose one):
    1. [Number] + [Power Word] + [Benefit] + [Proof/Location]
       Example: '7 Proven Strategies to Increase Sales 300% in London'
    
    2. [Problem] + [Number] + [Solution]
       Example: 'Low Engagement? 5 Ways to Get 95% Retention in 3 Months'
    
    3. [Social Proof] + [Benefit] + [How]
       Example: '50+ Businesses Grew 500% - Here is How They Did It'
    
    4. [Mistake/Warning] + [Solution]
       Example: '5 Fatal Marketing Mistakes (And How to Fix Them)'
    
    RULES FOR TITLE:
    ✓ MUST include a specific number (7, 5, 300%, 95%, etc.)
    ✓ MUST include a power word (Proven, Secrets, Fatal, Effective, Powerful)
    ✓ MUST include a clear benefit or problem
    ✓ Location if relevant (Chicago, London, etc.)
    ✓ Year 2026 if relevant
    ✓ DO NOT include the category name
    ✓ Focus on concrete results/solutions
    ✓ Create curiosity (curiosity gap)",
    
    "meta_description": "Meta description 150-160 characters with CTA and keyword",
    "content": "Full content of 2000-2500 words in HTML with semantic markup (h2, h3, strong, em, ul, ol, blockquote). IMPORTANT: Use HTML table tags (<table>, <tr>, <td>) for tables, DO NOT use ASCII art or Unicode box drawing characters.",
    "focus_keyword": "main keyword of the article",
    "excerpt": "Engaging summary of 2-3 sentences with a strong hook",
    "reading_time": "estimated reading time (minutes)",
    "key_takeaways": ["takeaway 1", "takeaway 2", "takeaway 3"]
}}

IMPORTANT:
- Output MUST be valid JSON without markdown code blocks
- DO NOT use ```json or ``` in output
- Return ONLY the JSON object
- Content must be cleanly formatted in HTML
"""
        else:
            prompt = f"""Buatkan artikel blog SEO-optimized berkualitas tinggi untuk website {target_site} tentang: {topic_focus}
{existing_titles_text}{research_note}{seo_section}{category_desc_text}
TARGET AUDIENCE: {target_audience}
RELATED KEYWORDS: {context}

⚠️ PENTING - TAHUN SAAT INI: 2026
- Jika menyebutkan tahun, gunakan 2026 atau "saat ini"
- Jangan gunakan tahun 2024 atau 2025
- Contoh: "Panduan Lengkap 2026" atau "Strategi Terkini"

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
   ✗ JANGAN gunakan pola yang sama dengan artikel sebelumnya

2. RINGKASAN EKSEKUTIF / TL;DR (Kotak AEO untuk Google AI Overviews):
   - WAJIB buat kotak `<div class="executive-summary" style="background:#f8fafc; padding:15px; border-left:4px solid #4f46e5; margin-bottom:20px;">`
   - Berisi 3 poin bullet (`<ul>`) yang menjawab inti topik secara langsung.
   - Ini krusial untuk fitur Answer Engine Optimization 2026.

3. CONTEXT (200 kata):
   - Situasi pendidikan Indonesia saat ini terkait topik
   - Mengapa topik ini urgent dan penting
   - Siapa yang paling membutuhkan solusi ini

3. KONTEN UTAMA (1500-1700 kata):
   
   H2: Konsep Dasar & Pentingnya (300 kata)
   - Definisi clear dengan bahasa praktis
   - Mengapa ini critical untuk lembaga pendidikan
   - Contoh konkret dari sekolah Indonesia
   
   H2: Implementasi Praktis Step-by-Step (600 kata)
   - Panduan actionable dengan numbered list
   - Timeline realistis (minggu/bulan)
   - Tools/template yang bisa digunakan
   - Checklist untuk memulai
   - Budget estimation jika relevan
   
   H2: Studi Kasus Nyata (400 kata)
   - Sekolah X di Kota Y, Indonesia (nama & lokasi realistis)
   - Challenge → Solution → Result (dengan angka spesifik)
   - Lesson learned yang bisa diterapkan
   - WAJIB: Quote langsung dari kepala sekolah (buat realistis & natural)
     Format: "Quote yang engaging dan spesifik," ujar Nama Lengkap, Kepala Sekolah X di Kota Y.
     Contoh: "Awalnya kami ragu, tapi setelah 3 bulan implementasi, SPP collection rate naik 40%," ujar Budi Santoso, Kepala SMA Harapan Bangsa di Surabaya.
   
   H2: Tips & Best Practices (300 kata)
   - Do's and Don'ts dalam format HTML table (JANGAN gunakan ASCII art atau Unicode box drawing)
   - Common mistakes yang harus dihindari
   - Pro tips dari praktisi (bisa tambahkan quote singkat)
   - Quick wins yang bisa langsung diterapkan

4. KESIMPULAN (150 kata):
   - Recap 3-5 key takeaways
   - Next action steps yang jelas
   - CTA: ajakan konsultasi/download resource

5. FAQ (150 kata):
   - 3-5 pertanyaan umum dengan jawaban singkat
   - Gunakan format Q&A

REQUIREMENTS KUALITAS:

E-E-A-T SIGNALS (WAJIB):
✓ Experience: "Berdasarkan implementasi di 50+ sekolah..."
✓ Expertise: Referensi Permendikbud/Kurikulum Merdeka/regulasi
✓ Authoritativeness: Data statistik pendidikan Indonesia
✓ Trustworthiness: Transparansi (pros & cons), update date
✓ Current: Gunakan tahun 2026 untuk konteks terkini

GAYA PENULISAN:
✓ Tone: Profesional tapi approachable, gunakan "Anda"
✓ Kalimat (BURSTINESS & PERPLEXITY - 100% HUMAN LIKE):
  - VARIASIKAN panjang kalimat secara drastis untuk ritme natural (Burstiness).
  - Kalimat sangat pendek (2-5 kata): Untuk emphasis/kejutan emosional. "Itu salah." "Faktanya sebaliknya."
  - Kalimat sedang (15-20 kata): Untuk penjelasan standar.
  - Kalimat panjang (25-35 kata): Untuk merangkai logika dan detail mendalam.
  - Gunakan pilihan kata yang tidak tertebak (High Perplexity) tapi tetap natural. Hindari klise.
✓ Semantic SEO (Entitas): Gunakan LSI Keyword dan Entitas Semantik secara natural. Sisipkan istilah teknis spesifik yang membuktikan keahlian mendalam. JANGAN keyword stuffing.
✓ Paragraf: SANGAT PENDEK. Maksimal 2-3 kalimat per paragraf. Sering-sering gunakan paragraf 1 kalimat. Wajib gunakan banyak pemisahan baris (enter) agar banyak ruang kosong untuk menyelipkan IKLAN.
✓ Contoh: Selalu dari konteks Indonesia dengan nama sekolah/kota spesifik
✓ Data: Sertakan statistik/angka yang relevan (tapi VARIASIKAN sumbernya)
✓ Empati: Pahami pain points kepala sekolah
✓ Quote: Sisipkan 1-2 quote realistis dari kepala sekolah/praktisi
  - Format: "Quote text," ujar Nama, Jabatan di Sekolah/Kota.
✓ Transisi: Gunakan transisi natural, hindari "dengan demikian", "oleh karena itu"
  - Baik: "Hasilnya?", "Yang terjadi?", "Faktanya:", "Contohnya:"
  - Buruk: "Dengan demikian", "Oleh karena itu", "Pada akhirnya"

⚠️ HINDARI FRASA REPETITIF & AI:
✗ "Data internal kami di KelasMaster per awal 2026 menunjukkan..."
✗ "Berdasarkan pengalaman kami di KelasMaster..."
✗ "Penting untuk dicatat bahwa...", "Perlu diingat bahwa..."
✗ "Dalam konteks ini...", "Sangat penting untuk..."
✗ "Mari kita bahas...", "Sebagai kesimpulan..."
✗ Pola pembuka yang sama dengan artikel sebelumnya
✓ Gunakan variasi: riset terbaru, studi kasus, cerita nyata, pertanyaan, dll
✓ Setiap artikel HARUS punya pembuka yang UNIK dan BERBEDA
✓ Gunakan bahasa conversational, bukan formal/akademis

SEO OPTIMIZATION:
✓ Keyword di first 100 words
✓ Keyword variations di H2 headings
✓ LSI keywords natural throughout
✓ Related posts akan muncul otomatis via plugin (tidak perlu manual link)
✓ Optimasi untuk featured snippet (gunakan list/table)

⚠️ LARANGAN KERAS:
✗ JANGAN gunakan placeholder seperti [FLOWCHART: ...], [INFOGRAPHIC: ...], [CHECKLIST: ...]
✗ JANGAN gunakan ASCII art atau Unicode box drawing (─, │, ┼, ├, ┤, dll)
✗ JANGAN sisipkan JSON artifacts atau metadata di dalam konten
✗ Gunakan HTML table (<table>) untuk tabel, BUKAN ASCII art
✗ Jika ingin checklist, gunakan <ul> atau <ol>, BUKAN placeholder

FORMAT OUTPUT (JSON):
{{
    "title": "Judul dengan formula CTR tinggi (50-60 karakter):
    
    FORMULA WAJIB (pilih salah satu):
    1. [Angka] + [Power Word] + [Benefit] + [Proof/Lokasi]
       Contoh: '7 Strategi Terbukti Tingkatkan PSB 300% di Jakarta'
    
    2. [Problem] + [Angka] + [Solution]
       Contoh: 'Asrama Sepi? 5 Cara Dapat Occupancy 95% dalam 3 Bulan'
    
    3. [Social Proof] + [Benefit] + [How]
       Contoh: '50+ Sekolah Dapat 500 Siswa Baru - Begini Caranya'
    
    4. [Mistake/Warning] + [Solution]
       Contoh: '5 Kesalahan Fatal Pemasaran Sekolah (Dan Cara Mengatasinya)'
    
    RULES JUDUL:
    ✓ WAJIB ada angka spesifik (7, 5, 300%, 95%, dll)
    ✓ WAJIB ada power word (Terbukti, Rahasia, Fatal, Jitu, Ampuh)
    ✓ WAJIB ada benefit/problem yang jelas
    ✓ Lokasi jika relevan (Jakarta, Indonesia)
    ✓ Tahun 2026 jika relevan
    ✓ JANGAN sertakan nama kategori
    ✓ Fokus pada hasil/solusi konkret
    ✓ Bikin penasaran (curiosity gap)",
    
    "meta_description": "Meta description 150-160 karakter dengan CTA dan keyword",
    "content": "Konten lengkap 2000-2500 kata dalam HTML dengan semantic markup (h2, h3, strong, em, ul, ol, blockquote). PENTING: Gunakan HTML table tag (<table>, <tr>, <td>) untuk tabel, JANGAN gunakan ASCII art atau Unicode box drawing characters (─, │, ┼, ├, ┤, dll)",
    "focus_keyword": "keyword utama artikel",
    "excerpt": "Ringkasan engaging 2-3 kalimat dengan hook kuat",
    "reading_time": "estimasi waktu baca (menit)",
    "key_takeaways": ["takeaway 1", "takeaway 2", "takeaway 3"]
}}

PENTING:
- Output HARUS berupa JSON valid tanpa markdown code blocks
- JANGAN gunakan ```json atau ``` di output
- Langsung return JSON object saja
- Content harus dalam format HTML yang rapi
- JUDUL: Fokus pada benefit/solusi, BUKAN nama kategori (contoh: "7 Strategi Meningkatkan Pendaftaran Siswa Baru" bukan "Strategi Pemasaran untuk Sekolah")"""

        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.85,
                top_p=0.9
            )
        )
        
        # Clean response text
        response_text = response.text.strip()
        
        # Remove markdown code blocks
        if response_text.startswith('```'):
            response_text = response_text.replace('```json', '').replace('```', '').strip()
        
        # Remove invalid control characters for JSON
        import re
        response_text = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', response_text)
        
        try:
            result = json.loads(response_text)
            
            # Clean content from placeholders and artifacts
            content = result.get('content', '')
            if content:
                # Remove any stray JSON codeblock markers AI might have embedded inside
                content = content.replace('```json', '').replace('```', '')
                result['content'] = content
            
            # Ensure minimum quality standards
            if not result.get('reading_time'):
                word_count = len(result.get('content', '').split())
                result['reading_time'] = f"{word_count // 200} menit"
            
            if not result.get('key_takeaways'):
                if language == 'en':
                    result['key_takeaways'] = [
                        f"Complete guide to {topic} for modern families",
                        "Practical tips you can apply immediately",
                        "Real-world examples and proven strategies"
                    ]
                else:
                    result['key_takeaways'] = [
                        f"Panduan lengkap {topic} untuk lembaga pendidikan",
                        "Tips praktis yang bisa langsung diterapkan",
                        "Studi kasus nyata dari sekolah Indonesia"
                    ]
            
            return result
        except json.JSONDecodeError as e:
            logger.error(f"JSON parsing failed: {e}")
            logger.error(f"Response preview: {response_text[:500]}")
            
            # Fallback if JSON parsing fails - try to extract content from malformed JSON
            content = response_text
            
            # Try to extract content field from malformed JSON
            try:
                # Look for "content": "..." pattern
                import re
                content_match = re.search(r'"content"\s*:\s*"([^"]+(?:\\.[^"]*)*)"', content, re.DOTALL)
                if content_match:
                    content = content_match.group(1)
                    # Unescape JSON string
                    content = content.replace('\\n', '\n').replace('\\"', '"').replace('\\\\', '\\')
                else:
                    # If no content field found, remove JSON structure
                    content = re.sub(r'^\s*\{.*?"content"\s*:\s*"', '', content, flags=re.DOTALL)
                    content = re.sub(r'"\s*,?\s*"[^"]+"\s*:.*\}\s*$', '', content, flags=re.DOTALL)
            except:
                pass
            
            # Remove any remaining JSON artifacts
            content = content.replace('```json', '').replace('```', '')
            content = re.sub(r'^\s*\{.*?\n', '', content)  # Remove opening JSON
            content = re.sub(r'\n.*?\}\s*$', '', content)  # Remove closing JSON
            
            if language == 'en':
                title_match = content.split('\n')[0] if '\n' in content else f"Complete Guide to {topic}"
                if title_match.startswith('#'):
                    title_match = title_match.replace('#', '').strip()
                return {
                    "title": title_match[:200] if len(title_match) < 200 else f"Complete Guide to {topic}",
                    "meta_description": f"Learn practical strategies and tips for {topic} to improve your organization. Complete guide with real-world case studies.",
                    "content": content,
                    "focus_keyword": topic,
                    "excerpt": f"Comprehensive guide to {topic} with practical tips that can be applied immediately. Complete with case studies and actionable checklist.",
                    "reading_time": "8 min read",
                    "key_takeaways": [
                        f"Step-by-step implementation of {topic}",
                        "Best practices and insights",
                        "Ready-to-use tools and templates"
                    ]
                }
            else:
                # Try to extract title if present
                title_match = content.split('\n')[0] if '\n' in content else f"Panduan Lengkap {topic} untuk Lembaga Pendidikan Indonesia"
                if title_match.startswith('#'):
                    title_match = title_match.replace('#', '').strip()
                
                return {
                    "title": title_match[:200] if len(title_match) < 200 else f"Panduan Lengkap {topic} untuk Lembaga Pendidikan Indonesia",
                    "meta_description": f"Pelajari strategi dan tips praktis {topic} untuk meningkatkan kualitas lembaga pendidikan Anda. Panduan lengkap dengan studi kasus nyata.",
                    "content": content,
                    "focus_keyword": topic,
                    "excerpt": f"Panduan komprehensif tentang {topic} dengan tips praktis yang bisa langsung diterapkan di lembaga pendidikan Anda. Dilengkapi studi kasus dan checklist actionable.",
                    "reading_time": "8 menit",
                    "key_takeaways": [
                        f"Implementasi {topic} step-by-step",
                        "Best practices dari sekolah Indonesia",
                        "Tools dan template siap pakai"
                    ]
                }
    
    def generate_image(self, topic, title, article_content=None, custom_prompt=None, site_name=None, **kwargs):
        """Generate landscape featured image for blog"""
        target_site = site_name if site_name else "kelasmaster.id"
        try:
            def to_webp(image_bytes):
                img = Image.open(BytesIO(image_bytes))
                if img.mode != 'RGB':
                    img = img.convert('RGB')

                output = BytesIO()
                img.save(output, format='WEBP', quality=85)
                output.seek(0)
                return output

            def iter_response_parts(response):
                try:
                    direct_parts = getattr(response, 'parts', None)
                except Exception:
                    direct_parts = None
                if direct_parts:
                    for part in direct_parts:
                        yield part

                for candidate in getattr(response, 'candidates', None) or []:
                    content = getattr(candidate, 'content', None)
                    for part in getattr(content, 'parts', None) or []:
                        yield part

            def response_summary(response):
                details = []
                prompt_feedback = getattr(response, 'prompt_feedback', None)
                if prompt_feedback:
                    details.append(f"prompt_feedback={prompt_feedback}")

                for index, candidate in enumerate(getattr(response, 'candidates', None) or []):
                    finish_reason = getattr(candidate, 'finish_reason', None)
                    finish_message = getattr(candidate, 'finish_message', None)
                    safety_ratings = getattr(candidate, 'safety_ratings', None)
                    details.append(
                        f"candidate[{index}] finish_reason={finish_reason} "
                        f"finish_message={finish_message} safety_ratings={safety_ratings}"
                    )

                text_parts = [
                    getattr(part, 'text', '').strip()
                    for part in iter_response_parts(response)
                    if getattr(part, 'text', None)
                ]
                if text_parts:
                    details.append(f"text={text_parts[0][:300]}")

                return " | ".join(details) if details else "no response details"

            def inline_image_bytes(response):
                for part in iter_response_parts(response):
                    inline_data = getattr(part, 'inline_data', None)
                    if inline_data is not None and getattr(inline_data, 'data', None):
                        return inline_data.data
                return None

            def safe_title(value):
                words = (value or topic or "education article").split()
                return " ".join(words[:12])

            image_prompts = []
            if custom_prompt:
                image_prompts.append((
                    "custom",
                    custom_prompt
                    .replace('{topic}', topic)
                    .replace('{title}', title)
                    .replace('{site_name}', target_site)
                ))

            image_prompts.extend([
                (
                    "safe-editorial",
                    f"""Create a professional editorial illustration for an education blog featured image.
Article theme: "{safe_title(title)}"
Category context: {topic}

Design requirements:
- Landscape 16:9 composition.
- Conceptual illustration only: documents, classroom dashboard, charts, books, soft abstract shapes.
- Professional education palette with balanced blues, greens, white, and warm accent colors.
- Do not render readable text, article headlines, government logos, official seals, real people, or realistic faces.
- Do not imply a factual announcement visually; keep it symbolic and broadly educational.
- Safe for work, non-political, non-violent, clean modern style.
- Subtle generic brand feel for {target_site}, without text-heavy typography."""
                ),
                (
                    "generic-education",
                    f"""Create a safe, generic 16:9 featured image for an education management article.
Use abstract school administration symbols: open notebook, calendar, analytics chart, notification card, and soft geometric background.
No readable words, no people, no portraits, no government insignia, no money bills, no official documents.
Modern clean vector or soft 3D illustration, high quality, professional blog thumbnail."""
                ),
                (
                    "minimal-abstract",
                    """Create a clean abstract 16:9 education blog cover image.
Use simple shapes, books, charts, and digital learning icons on a bright professional background.
No text, no faces, no logos, no sensitive or political imagery."""
                )
            ])

            image_config_kwargs = {'aspect_ratio': '16:9'}
            # person_generation is no longer supported in the new Gemini API
            # we will not pass it to ImageConfig

            # Use configured image model for image generation
            last_error = None
            last_summary = None
            if self.image_model.startswith('imagen-'):
                imagen_config_kwargs = {
                    'number_of_images': 1,
                    'aspect_ratio': '16:9',
                    'output_mime_type': 'image/webp'
                }
                # person_generation removed

                for attempt_name, prompt in image_prompts:
                    try:
                        logger.info(f"Generating featured image with {self.image_model} using {attempt_name} prompt")
                        response = self.client.models.generate_images(
                            model=self.image_model,
                            prompt=prompt,
                            config=types.GenerateImagesConfig(**imagen_config_kwargs)
                        )

                        for generated_image in getattr(response, 'generated_images', None) or []:
                            image = getattr(generated_image, 'image', None)
                            image_bytes = getattr(image, 'image_bytes', None)
                            if image_bytes:
                                return to_webp(image_bytes)

                        last_summary = getattr(response, 'model_dump_json', lambda **_: str(response))(exclude_none=True)
                        logger.warning(f"Imagen attempt '{attempt_name}' returned no image. {last_summary}")
                    except Exception as attempt_err:
                        last_error = attempt_err
                        logger.warning(f"Imagen attempt '{attempt_name}' failed: {attempt_err}", exc_info=True)
                if last_summary:
                    raise Exception(
                        "Image generation returned no image after fallback prompts. "
                        f"Last response: {last_summary}"
                    )
                if last_error:
                    raise last_error
                raise Exception("Image generation returned no image after fallback prompts.")
            else:
                for attempt_name, prompt in image_prompts:
                    try:
                        logger.info(f"Generating featured image with {self.image_model} using {attempt_name} prompt")
                        response = self.client.models.generate_content(
                            model=self.image_model,
                            contents=prompt,
                            config=types.GenerateContentConfig(
                                response_modalities=['TEXT', 'IMAGE'],
                                image_config=types.ImageConfig(**image_config_kwargs)
                            )
                        )

                        image_bytes = inline_image_bytes(response)
                        if image_bytes:
                            return to_webp(image_bytes)

                        last_summary = response_summary(response)
                        logger.warning(f"Gemini image attempt '{attempt_name}' returned no image. {last_summary}")
                    except Exception as attempt_err:
                        last_error = attempt_err
                        logger.warning(f"Gemini image attempt '{attempt_name}' failed: {attempt_err}", exc_info=True)

                if last_summary:
                    raise Exception(
                        "Image generation returned no image after fallback prompts. "
                        f"Last response: {last_summary}"
                    )
                if last_error:
                    raise last_error
                raise Exception(
                    "Image generation returned no image after fallback prompts."
                )
        except Exception as e:
            logger.error(f"Error generating featured image: {e}", exc_info=True)
            raise Exception(f"Gemini image generation API error: {str(e)}")


class WordPressPublisher:
    def __init__(self, url, username, password):
        self.url = url.rstrip('/')
        self.username = username
        self.password = password
        self.api_url = f"{self.url}/wp-json/wp/v2"
    
    def _get_auth(self):
        credentials = f"{self.username}:{self.password}"
        token = base64.b64encode(credentials.encode()).decode()
        return {'Authorization': f'Basic {token}'}
    
    def get_post_stats(self, post_id):
        """Get post statistics from WordPress"""
        try:
            response = requests.get(
                f"{self.api_url}/posts/{post_id}",
                headers=self._get_auth(),
                timeout=10
            )
            
            if response.status_code == 200:
                post = response.json()
                
                # Get comments count
                comments_response = requests.get(
                    f"{self.api_url}/comments",
                    params={'post': post_id},
                    timeout=10
                )
                comments_count = len(comments_response.json()) if comments_response.status_code == 200 else 0
                
                return {
                    'views': post.get('meta', {}).get('views', 0),  # Requires view counter plugin
                    'comments': comments_count,
                    'likes': post.get('meta', {}).get('likes', 0),  # Requires like plugin
                    'shares': post.get('meta', {}).get('shares', 0)  # Requires share counter
                }
            return None
        except Exception as e:
            print(f"Error getting post stats: {e}")
            return None
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((requests.exceptions.RequestException, Exception))
    )
    def upload_image(self, image_data, title):
        """Upload image via WordPress REST API"""
        try:
            if isinstance(image_data, BytesIO):
                image_bytes = image_data.getvalue()
                sanitized_title = sanitize_filename(title[:50])
                filename = f'{sanitized_title}.webp'
                mime_type = 'image/webp'
            else:
                response = requests.get(image_data, timeout=30)
                if response.status_code != 200:
                    logger.error(f"Failed to download image: {response.status_code}")
                    return None
                image_bytes = response.content
                sanitized_title = sanitize_filename(title[:50])
                filename = f'{sanitized_title}.jpg'
                mime_type = 'image/jpeg'
            
            # Upload via WordPress REST API
            headers = self._get_auth()
            headers['Content-Disposition'] = f'attachment; filename="{filename}"'
            headers['Content-Type'] = mime_type
            
            response = requests.post(
                f"{self.api_url}/media",
                headers=headers,
                data=image_bytes,
                timeout=60
            )
            
            if response.status_code == 201:
                media_data = response.json()
                media_id = media_data['id']
                logger.info(f"Image uploaded successfully via REST API: {media_id}")
                
                # Update SEO metadata (Alt Text, Description, Title)
                try:
                    update_headers = self._get_auth()
                    update_headers['Content-Type'] = 'application/json'
                    metadata_payload = {
                        'title': title,
                        'alt_text': title,
                        'description': f"Illustration for article about: {title}"
                    }
                    requests.post(
                        f"{self.api_url}/media/{media_id}",
                        headers=update_headers,
                        json=metadata_payload,
                        timeout=30
                    )
                    logger.info(f"Image SEO metadata updated for media ID: {media_id}")
                except Exception as meta_e:
                    logger.error(f"Failed to update image metadata: {meta_e}")
                    
                return media_id
            else:
                logger.error(f"Failed to upload image: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            logger.error(f"Error uploading image: {e}")
            return None
    
    def get_categories(self):
        """Fetch all categories from WordPress"""
        try:
            response = requests.get(
                f"{self.api_url}/categories",
                headers=self._get_auth(),
                params={'per_page': 100},
                timeout=30
            )
            
            if response.status_code == 200:
                categories = response.json()
                return [{'id': cat['id'], 'name': cat['name'], 'description': cat.get('description', ''), 'count': cat.get('count', 0)} for cat in categories]
            else:
                logger.error(f"Failed to fetch categories: {response.status_code}")
                return []
        except Exception as e:
            logger.error(f"Error fetching categories: {e}")
            return []
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((requests.exceptions.RequestException, Exception))
    )
    def create_post(self, title, content, category_id=None, featured_image_id=None, meta_description=None, excerpt=None, focus_keyword=None):
        headers = self._get_auth()
        headers['Content-Type'] = 'application/json'
        
        # Clean content before posting
        import re
        
        # Remove placeholder patterns
        placeholders = [
            r'\[FLOWCHART:.*?\]',
            r'\[INFOGRAPHIC:.*?\]',
            r'\[CHECKLIST:.*?\]',
            r'\[DIAGRAM:.*?\]',
            r'\[IMAGE:.*?\]',
            r'\[CHART:.*?\]',
            r'\[TABLE:.*?\]',
        ]
        for pattern in placeholders:
            content = re.sub(pattern, '', content, flags=re.IGNORECASE)
        
        # Remove ASCII art tables
        content = re.sub(r'<pre[^>]*>.*?[─│┼├┤┬┴┌┐└┘].*?</pre>', '', content, flags=re.DOTALL)
        content = re.sub(r'[─│┼├┤┬┴┌┐└┘╔╗╚╝║═╠╣╦╩╬]', '', content)
        
        # Remove empty paragraphs
        content = re.sub(r'<p>\s*</p>', '', content)
        content = re.sub(r'<p>\s*\\n\s*</p>', '', content)
        
        # Remove JSON artifacts at the beginning
        content = re.sub(r'^\s*\{\s*"[^"]*"\s*:', '', content)
        content = re.sub(r'"\s*\}\s*$', '', content)
        
        content = content.strip()
        
        post_data = {
            'title': title,
            'content': content,
            'status': 'publish'
        }
        
        if category_id:
            post_data['categories'] = [category_id]
        
        if featured_image_id:
            post_data['featured_media'] = featured_image_id
        
        if excerpt:
            post_data['excerpt'] = excerpt
        
        # Add Yoast SEO meta if available
        meta_fields = {}
        if meta_description:
            meta_fields['_yoast_wpseo_metadesc'] = meta_description
        if focus_keyword:
            meta_fields['_yoast_wpseo_focuskw'] = focus_keyword
        
        if meta_fields:
            post_data['meta'] = meta_fields
        
        response = requests.post(
            f"{self.api_url}/posts",
            headers=headers,
            json=post_data,
            timeout=30
        )
        
        # If post created successfully, try to update Yoast meta separately
        if response.status_code == 201 and meta_fields:
            post_id = response.json().get('id')
            try:
                # Update post meta using WordPress REST API
                update_response = requests.post(
                    f"{self.api_url}/posts/{post_id}",
                    headers=headers,
                    json={'meta': meta_fields},
                    timeout=30
                )
                logger.info(f"Yoast meta update: {update_response.status_code}")
            except Exception as e:
                logger.warning(f"Could not update Yoast meta: {e}")
        
        return response.status_code == 201, response.json() if response.status_code == 201 else response.text
