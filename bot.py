from google import genai
from google.genai import types
import requests
import base64
import json
import re
import urllib.parse
from io import BytesIO
from PIL import Image
import time
import logging
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

logger = logging.getLogger(__name__)

def sanitize_filename(name):
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
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=4, max=60),
        retry=retry_if_exception_type(Exception)
    )
    def generate_article(self, topic, existing_titles=None, custom_topic=None, seo_data=None, avoid_similar=False, custom_prompt=None, site_name=None, internal_links_context=None, **kwargs):
        # Resolve custom prompt from either parameter name
        custom_prompt = custom_prompt or kwargs.get('custom_article_prompt')
        language = kwargs.get('language') or 'id'
        target_site = site_name if site_name else "website"
        
        if language == 'en':
            target_audience = f"Readers of website {target_site}"
        else:
            target_audience = f"Pembaca website {target_site}"
        
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
                    existing_titles_text = f"\n\nâš ï¸ CRITICAL - TITLES MUST BE VERY DIFFERENT:\n"
                    existing_titles_text += "Previous titles are too similar. Create a TRULY UNIQUE title with a different angle/perspective!\n\n"
                    existing_titles_text += "Titles to AVOID:\n"
                else:
                    existing_titles_text = f"\n\nâš ï¸ IMPORTANT - AVOID EXISTING TITLES:\n"
                
                for title in existing_titles[-10:]:
                    existing_titles_text += f"- {title}\n"
                
                if avoid_similar:
                    existing_titles_text += "\nðŸ’¡ TIPS FOR UNIQUE TITLES:\n"
                    existing_titles_text += "- Use different angles (e.g., from customer's perspective, manager's perspective, general public)\n"
                    existing_titles_text += "- Focus on specific aspects not yet discussed\n"
                    existing_titles_text += "- Use different formats (guide, checklist, case study, analysis, etc.)\n"
                    existing_titles_text += "- Add specific context (location, time, situation)\n\n"
                else:
                    existing_titles_text += "\nThe article title MUST be different and unique from the list above!\n"
            else:
                if avoid_similar:
                    existing_titles_text = f"\n\nâš ï¸ CRITICAL - JUDUL HARUS SANGAT BERBEDA:\n"
                    existing_titles_text += "Judul sebelumnya terlalu mirip. Buat judul yang BENAR-BENAR UNIK dengan angle/perspektif berbeda!\n\n"
                    existing_titles_text += "Judul yang HARUS DIHINDARI:\n"
                else:
                    existing_titles_text = f"\n\nâš ï¸ PENTING - HINDARI JUDUL YANG SUDAH ADA:\n"
                
                for title in existing_titles[-10:]:  # Last 10 titles
                    existing_titles_text += f"- {title}\n"
                
                if avoid_similar:
                    existing_titles_text += "\nðŸ’¡ TIPS MEMBUAT JUDUL UNIK:\n"
                    existing_titles_text += "- Gunakan angle berbeda (misalnya: dari sisi orang tua, dari sisi guru, dari sisi siswa)\n"
                    existing_titles_text += "- Fokus pada aspek spesifik yang belum dibahas\n"
                    existing_titles_text += "- Gunakan format berbeda (panduan, checklist, studi kasus, analisis, dll)\n"
                    existing_titles_text += "- Tambahkan konteks spesifik (lokasi, waktu, situasi)\n\n"
                else:
                    existing_titles_text += "\nJudul artikel HARUS berbeda dan unik dari daftar di atas!\n"
        
        # Add custom topic from research if available
        topic_focus = custom_topic if custom_topic else topic
        if language == 'en':
            research_note = f"\n\nðŸ”¥ TRENDING TOPIC: {custom_topic}\nFocus the article on this trending topic within the context of {topic}.\n" if custom_topic else ""
        else:
            research_note = f"\n\nðŸ”¥ TRENDING TOPIC: {custom_topic}\nFokuskan artikel pada topik trending ini dalam konteks {topic}.\n" if custom_topic else ""
        
        # Add SEO data if available
        seo_section = ""
        if seo_data:
            keywords = seo_data.get('keywords', [])
            questions = seo_data.get('questions', [])
            semantic_context = seo_data.get('semantic_context', "")
            news_insights = seo_data.get('news_insights', [])
            
            if semantic_context:
                if language == 'en':
                    seo_section += f"\n\nðŸ“š SEMANTIC CONTEXT (Wikipedia Background):\n{semantic_context}\n"
                else:
                    seo_section += f"\n\nðŸ“š KONTEKS SEMANTIK (Latar Belakang Wikipedia):\n{semantic_context}\n"
                    
            if news_insights:
                if language == 'en':
                    seo_section += f"\n\nðŸ“° LATEST NEWS (Incorporate these current events as 'Angle'):\n"
                else:
                    seo_section += f"\n\nðŸ“° BERITA TERKINI (Gunakan sebagai 'Angle' Kekinian):\n"
                for news in news_insights:
                    seo_section += f"- {news}\n"
                    
            if keywords:
                if language == 'en':
                    seo_section += f"\n\nðŸ”‘ RELATED KEYWORDS (use naturally in the article):\n"
                else:
                    seo_section += f"\n\nðŸ”‘ RELATED KEYWORDS (gunakan natural di artikel):\n"
                for kw in keywords[:10]:
                    seo_section += f"- {kw}\n"
            
            if questions:
                if language == 'en':
                    seo_section += f"\n\nâ“ FREQUENTLY ASKED QUESTIONS (answer in the article):\n"
                else:
                    seo_section += f"\n\nâ“ PERTANYAAN YANG SERING DICARI (jawab di artikel):\n"
                for q in questions[:5]:
                    seo_section += f"- {q}\n"
                if language == 'en':
                    seo_section += "\nðŸ’¡ Ensure the article answers these questions comprehensively!\n"
                else:
                    seo_section += "\nðŸ’¡ Pastikan artikel menjawab pertanyaan-pertanyaan ini secara lengkap!\n"
                    
            competitor_outlines = seo_data.get('competitor_outlines', [])
            if competitor_outlines:
                if language == 'en':
                    seo_section += f"\n\nâš”ï¸ COMPETITOR ANALYSIS (Top Ranking Pages):\n"
                else:
                    seo_section += f"\n\nâš”ï¸ ANALISIS KOMPETITOR (Halaman Ranking Atas):\n"
                for comp in competitor_outlines[:3]:
                    headers_str = ", ".join(comp.get('headers', [])[:5])
                    seo_section += f"- Competitor '{comp.get('title')}' covers: {headers_str}\n"
                if language == 'en':
                    seo_section += "ðŸ’¡ MANDATORY: Your article MUST be more comprehensive, detailed, and cover angles these competitors missed!\n"
                else:
                    seo_section += "ðŸ’¡ WAJIB: Artikelmu HARUS lebih komprehensif, lebih detail, dan membahas sudut pandang yang dilewatkan oleh kompetitor ini!\n"
                    
            social_insights = seo_data.get('social_insights', [])
            if social_insights:
                if language == 'en':
                    seo_section += f"\n\nðŸ—£ï¸ REAL AUDIENCE INSIGHTS (Quora/Reddit Discussions):\n"
                else:
                    seo_section += f"\n\nðŸ—£ï¸ KELUHAN AUDIENS ASLI (Diskusi Quora/Reddit):\n"
                for insight in social_insights[:5]:
                    seo_section += f"- {insight}\n"
                if language == 'en':
                    seo_section += "ðŸ’¡ Address these real pain points and questions directly in your content.\n"
                else:
                    seo_section += "ðŸ’¡ Jawab keresahan dan masalah nyata dari manusia-manusia ini ke dalam artikelmu.\n"
                    
            youtube_insights = seo_data.get('youtube_insights', [])
            if youtube_insights:
                if language == 'en':
                    seo_section += f"\n\nðŸŽ¥ YOUTUBE EXPERT INSIGHTS (Transcripts from top videos):\n"
                else:
                    seo_section += f"\n\nðŸŽ¥ WAWASAN PAKAR YOUTUBE (Transkrip dari video teratas):\n"
                for yt in youtube_insights[:2]:
                    seo_section += f"- Video '{yt.get('title')}': \"{yt.get('snippets')}\"\n"
                if language == 'en':
                    seo_section += "ðŸ’¡ Weave these expert insights naturally into the article to boost E-E-A-T signals.\n"
                else:
                    seo_section += "ðŸ’¡ Selipkan wawasan dari transkrip video ini agar artikelmu memiliki sudut pandang praktisi (E-E-A-T).\n"
        
        category_desc_text = ""
        category_desc = kwargs.get('category_desc')
        if category_desc:
            if language == 'en':
                category_desc_text = f"\n\nðŸ“‚ CATEGORY DESCRIPTION / WRITING INSTRUCTIONS:\n{category_desc}\nFollow these category instructions and focus the article style and scope on this description."
            else:
                category_desc_text = f"\n\nðŸ“‚ DESKRIPSI KATEGORI / PETUNJUK PENULISAN:\n{category_desc}\nIkuti petunjuk kategori ini dan fokuskan gaya serta ruang lingkup artikel pada deskripsi tersebut."

        internal_links_text = ""
        if internal_links_context:
            if language == 'en':
                internal_links_text = f"\n\nðŸ”— INTERNAL LINKING STRATEGY:\nHere are some of our previous articles:\n"
                for post in internal_links_context[:30]:
                    internal_links_text += f"- Title: {post['title']} (URL: {post['url']})\n"
                internal_links_text += "ðŸ’¡ IMPORTANT: Find 3-5 opportunities in your article where the topic naturally relates to the titles above. When it does, weave the title/context naturally into a sentence and make it an HTML link `<a href=\"...\">anchor text</a>`. DO NOT list them at the end; weave them inside paragraphs organically!\n"
            else:
                internal_links_text = f"\n\nðŸ”— STRATEGI INTERNAL LINKING:\nBerikut adalah artikel-artikel lama kita:\n"
                for post in internal_links_context[:30]:
                    internal_links_text += f"- Judul: {post['title']} (URL: {post['url']})\n"
                internal_links_text += "ðŸ’¡ PENTING: Sisipkan 3-5 link secara natural di dalam paragraf artikelmu. Jika kalimatmu relevan dengan salah satu judul di atas, jadikan kalimat itu sebagai anchor text menggunakan tag HTML `<a href=\"...\">teks</a>`. JANGAN membuat daftar link di akhir artikel, sisipkan secara organik di dalam teks bacaan!\n"

        if custom_prompt:
            prompt = custom_prompt
            prompt = prompt.replace('{topic}', topic_focus)
            prompt = prompt.replace('{existing_titles}', existing_titles_text)
            prompt = prompt.replace('{research_note}', research_note)
            prompt = prompt.replace('{seo_section}', seo_section)
            prompt = prompt.replace('{category_desc_text}', category_desc_text)
            prompt = prompt.replace('{internal_links_text}', internal_links_text)
            prompt = prompt.replace('{target_site}', target_site)
            prompt = prompt.replace('{target_audience}', target_audience)
        elif language == 'en':
            prompt = f"""Write a high-quality, SEO-optimized blog article for the website {target_site} about: {topic_focus}
{existing_titles_text}{research_note}{seo_section}{category_desc_text}{internal_links_text}
TARGET AUDIENCE: {target_audience}
RELATED KEYWORDS: {context}

âš ï¸ IMPORTANT - CURRENT YEAR: 2026
- If mentioning years, use 2026 or "currently"
- Do not use the year 2024 or 2025
- Example: "Complete Guide 2026" or "Latest Strategies"

ARTICLE STRUCTURE (MINIMUM 2000-2500 WORDS - STRICTLY REQUIRED!):
âš ï¸ WRITE IN EXTREME DETAIL AND LENGTH. DO NOT SUMMARIZE. EACH SUB-HEADING MUST CONSIST OF AT LEAST 4-5 LONG AND COMPREHENSIVE PARAGRAPHS. CREATE A VERY DEEP ARTICLE. IF IT IS LESS THAN 2000 WORDS, THIS ARTICLE WILL BE REJECTED.

1. INTRODUCTORY HOOK (100 words):
   âš ï¸ MUST BE VARIATIVE - Use one of these approaches (DO NOT always use statistics):
   
   A. Story/Anecdote: "John, a manager in London, was almost desperate when..."
   B. Problem Statement: "Imagine: Your costs went up by 20%, but your retention is dropping..."
   C. Provocative Question: "What makes 3 out of 5 startups fail to survive?"
   D. Surprising Fact: "In 2026, more businesses are closing than opening..."
   E. Contrast: "Company A is full of customers, Company B is empty. The difference is only one thing..."
   
   âœ“ End with a promise: "This article will guide you..."
   âœ— DO NOT always start with the same pattern
   âœ— DO NOT use the same opening pattern as previous articles

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
   - Challenge â†’ Solution â†’ Result (with specific numbers)
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
âœ“ Experience: "Based on implementation across 50+ organizations..."
âœ“ Expertise: Reference to industry standards, regulations, or research
âœ“ Authoritativeness: Statistical data
âœ“ Trustworthiness: Transparency (pros & cons), update date
âœ“ Current: Use the year 2026 for current context

WRITING STYLE & SEO 2026:
âœ“ Tone: Professional but approachable, use "you"
âœ“ Personal Approach (E-E-A-T): Start a paragraph with "Based on our practitioners' experience..." to simulate Authoritativeness.
âœ“ Text Emphasis (Scannability): MUST use bold text (<strong>) on core concepts, important metrics/numbers, or key terms.
âœ“ Semantic SEO (Entities): Use LSI Keywords and Semantic Entities naturally. Insert specific technical terms that prove deep expertise. DO NOT keyword stuff.
âœ“ Sentences (BURSTINESS & PERPLEXITY - 100% HUMAN LIKE):
  - VARY sentence length drastically for a natural rhythm (Burstiness).
  - Very short sentences (2-5 words): For emotional emphasis/surprise. "That's wrong." "The opposite is true."
  - Medium sentences (15-20 words): For standard explanations.
  - Long sentences (25-35 words): To string together deep logic and details.
  - Use unpredictable word choices (High Perplexity) but keep it natural. Avoid clichÃ©s.
âœ“ Paragraphs: EXTREMELY SHORT. Maximum 2-3 sentences per paragraph. Frequently use 1-sentence paragraphs. MUST use many line breaks (enter) so there is plenty of whitespace to inject ADS.
âœ“ Examples: Always from a realistic context with specific names
âœ“ Data: Include relevant statistics/numbers (but VARY the sources)
âœ“ Empathy: Understand the pain points of the target audience
âœ“ Quotes: Insert 1-2 realistic quotes from practitioners
âœ“ Transitions: Use natural transitions, avoid repetitive connector phrases

âš ï¸ AVOID REPETITIVE & AI-LIKE PHRASES:
âœ— "Our internal data shows...", "Based on our experience..."
âœ— "It is important to note that...", "Keep in mind that..."
âœ— "In this context...", "It is crucial to..."
âœ— "Let's discuss...", "In conclusion..."
âœ“ Use variation: recent research, case studies, real stories, questions, etc.
âœ“ Every article MUST have a UNIQUE and DIFFERENT opening
âœ“ Use conversational language, not overly formal/academic

SEO OPTIMIZATION:
âœ“ Keyword in first 100 words
âœ“ Keyword variations in H2 headings
âœ“ LSI keywords naturally throughout
âœ“ Internal Links: You MUST weave the provided internal links into the content organically (as instructed above).
âœ“ Optimize for featured snippets (use lists/tables)

âš ï¸ STRICT PROHIBITIONS:
âœ— DO NOT use placeholders like [FLOWCHART: ...], [INFOGRAPHIC: ...], [CHECKLIST: ...]
âœ— DO NOT use ASCII art or Unicode box drawing characters (â”€, â”‚, â”¼, â”œ, â”¤, etc.)
âœ— DO NOT insert JSON artifacts or metadata inside the content
âœ— Use HTML table (<table>) for tables, NOT ASCII art
âœ— If you want a checklist, use <ul> or <ol>, NOT placeholders

OUTPUT FORMAT (JSON):
{{
    "title": "Title with high CTR formula (50-60 characters) - REQUIRED: ONLY the title text. DO NOT add word count notes like (approx 450 words) or any brackets.",
    "meta_description": "Meta description 150-160 characters with CTA and keyword",
    "content": "Full content of AT LEAST 2000-2500 words in HTML. MANDATORY: You must generate a very long and comprehensive article. Write at least 20 paragraphs. Use semantic markup (h2, h3, strong, em, ul, ol, blockquote). IMPORTANT: Use HTML table tags (<table>, <tr>, <td>) for tables, DO NOT use ASCII art or Unicode box drawing characters. DO NOT put the title inside the content.",
    "focus_keyword": "main keyword of the article",
    "excerpt": "Engaging summary of 2-3 sentences with a strong hook",
    "reading_time": "estimated reading time (minutes)",
    "key_takeaways": ["takeaway 1", "takeaway 2", "takeaway 3"],
    "faqs": [
        {{"question": "Question 1", "answer": "Answer 1"}},
        {{"question": "Question 2", "answer": "Answer 2"}}
    ]
}}

IMPORTANT:
- Output MUST be valid JSON without markdown code blocks
- DO NOT use ```json or ``` in output
- Return ONLY the JSON object
- Content must be cleanly formatted in HTML
"""
        else:
            prompt = f"""Buatkan artikel blog SEO-optimized berkualitas tinggi untuk website {target_site} tentang: {topic_focus}
{existing_titles_text}{research_note}{seo_section}{category_desc_text}{internal_links_text}
TARGET AUDIENCE: {target_audience}
RELATED KEYWORDS: {context}

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

FORMAT OUTPUT (Gunakan XML-Tags berikut, BUKAN JSON):

<TITLE>Judul CTR tinggi dengan angka + power word + benefit (50-60 karakter). WAJIB: HANYA berisi judul murni.</TITLE>
<META_DESCRIPTION>Meta description 150-160 karakter dengan CTA dan keyword</META_DESCRIPTION>
<FOCUS_KEYWORD>keyword utama artikel</FOCUS_KEYWORD>
<CONTENT>
Konten HTML lengkap 2000-2500 kata. WAJIB: Langsung mulai dengan tag HTML paragraf pembuka, JANGAN ulangi judul di dalam konten. Bebas berkreasi tanpa batasan string JSON!
</CONTENT>
<FAQS>
Q: Pertanyaan 1?
A: Jawaban 1

Q: Pertanyaan 2?
A: Jawaban 2
</FAQS>

PENTING:
- Output HARUS menggunakan TAG XML di atas. Jangan gunakan format JSON.
- Content harus dalam format HTML yang rapi
- JUDUL: Fokus pada benefit/solusi, BUKAN nama kategori (contoh: "7 Strategi Meningkatkan Pendaftaran Siswa Baru" bukan "Strategi Pemasaran untuk Sekolah")"""
        # Force strict system rules regardless of custom prompt
        system_rules = """
⚠️ SYSTEM OVERRIDE - STRICT INSTRUCTIONS ⚠️
1. DO NOT write literal template labels (e.g., "H1:", "H2:", "1. HOOK PEMBUKA:", "Checklist 1:") in the final HTML content. Output ONLY the natural text and HTML tags.
2. DO NOT use ANY emojis (like ✨, 🚀, 👍, etc.) in the content. It must look professional and academic.
3. Your output MUST use XML Tags (e.g. <CONTENT>...</CONTENT>). DO NOT output JSON.
4. CRITICAL: You MUST write AT LEAST 2000-2500 words inside the <CONTENT> tag. Expand heavily on each section! Write at least 20 paragraphs.
"""
        prompt = prompt + "\n\n" + system_rules

        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.85,
                top_p=0.9,
                max_output_tokens=8192
            )
        )
        
        # Clean response text
        response_text = response.text.strip()
        
        # Remove markdown code blocks
        if response_text.startswith('```'):
            response_text = response_text.replace('```json', '').replace('```', '').strip()
        
        # Remove invalid control characters for JSON
        # Remove invalid control characters for JSON, EXCEPT newlines and tabs
        response_text = re.sub(r'[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f-\x9f]', '', response_text)
        
        # Extract fields using XML tags
        def extract_tag(tag, text, default=""):
            match = re.search(f'<{tag}>(.*?)</{tag}>', text, re.DOTALL | re.IGNORECASE)
            return match.group(1).strip() if match else default
            
        title = extract_tag('TITLE', response_text)
        meta_desc = extract_tag('META_DESCRIPTION', response_text)
        content = extract_tag('CONTENT', response_text)
        focus_keyword = extract_tag('FOCUS_KEYWORD', response_text, default=topic)
        
        # If XML parsing fails (e.g. model didn't use tags), fallback to full text
        if not content:
            content = response_text
            
        # Clean content artifacts
        content = content.replace('```html', '').replace('```', '').strip()
            
        if not title:
            fallback_title = f"Complete Guide to {topic}" if language == 'en' else f"Panduan Lengkap {topic}"
            title_match = content.split('\n')[0] if '\n' in content else fallback_title
            if title_match.startswith('#'):
                title_match = title_match.replace('#', '').strip()
            title = title_match[:200] if len(title_match) < 200 else fallback_title
            
        # Parse FAQs from text
        faqs_text = extract_tag('FAQS', response_text)
        faqs = []
        if faqs_text:
            # simple parse Q: ... A: ...
            q_matches = re.finditer(r'Q:\s*(.*?)\n', faqs_text)
            a_matches = re.finditer(r'A:\s*(.*?)(?=\nQ:|$)', faqs_text, re.DOTALL)
            questions = [m.group(1).strip() for m in q_matches]
            answers = [m.group(1).strip() for m in a_matches]
            for q, a in zip(questions, answers):
                faqs.append({"question": q, "answer": a})
                
        word_count = len(content.split())
        reading_time = f"{max(1, word_count // 200)} menit" if language != 'en' else f"{max(1, word_count // 200)} min read"
        
        if language == 'en':
            key_takeaways = [
                f"Complete guide to {topic}",
                "Practical tips you can apply immediately",
                "Real-world examples and proven strategies"
            ]
            excerpt = f"Comprehensive guide to {topic} with practical tips that can be applied immediately. Complete with case studies and actionable checklist."
            if not meta_desc:
                meta_desc = f"Learn practical strategies and tips for {topic}. Complete guide with real-world case studies."
        else:
            key_takeaways = [
                f"Panduan lengkap {topic}",
                "Tips praktis yang bisa langsung diterapkan",
                "Studi kasus nyata dan implementasinya"
            ]
            excerpt = f"Panduan komprehensif {topic} dengan tips praktis yang bisa langsung diterapkan. Dilengkapi studi kasus nyata dan checklist yang dapat ditindaklanjuti."
            if not meta_desc:
                meta_desc = f"Pelajari strategi dan tips praktis {topic} untuk kemajuan Anda. Panduan lengkap dengan studi kasus nyata."
        
        return {
            "title": title,
            "meta_description": meta_desc,
            "content": content,
            "focus_keyword": focus_keyword,
            "excerpt": excerpt,
            "reading_time": reading_time,
            "key_takeaways": key_takeaways,
            "faqs": faqs
        }
    
    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=4, max=60),
        retry=retry_if_exception_type(Exception)
    )
    def generate_image(self, topic, title, article_content=None, custom_prompt=None, site_name=None, **kwargs):
        """Generate landscape featured image for blog"""
        target_site = site_name if site_name else "website"
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
                    .replace('{target_site}', target_site)
                ))

            image_prompts.extend([
                (
                    "safe-editorial",
                    f"""Create a professional editorial illustration for a blog featured image.
Article theme: "{safe_title(title)}"
Category context: {topic}

Design requirements:
- Landscape 16:9 composition.
- Include a bold, highly aesthetic typographic overlay (about 3 to 6 words). This text should be a catchy, descriptive hook that perfectly summarizes the article's core value (e.g. "Ultimate Guide to {topic}", "Mastering {topic} in 2026", "Key Strategies You Need to Know").
- DO NOT just write 1 or 2 generic words. The text must accurately represent the article's content while remaining click-worthy.
- DO NOT render the full lengthy article title. Keep it punchy and readable.
- Beautiful, modern typography perfectly integrated into the design.
- Conceptual illustration with soft abstract shapes, charts, or modern digital elements.
- Professional palette with vibrant, eye-catching colors.
- Safe for work, non-political, clean modern style."""
                ),
                (
                    "generic-education",
                    f"""Create a high-quality 16:9 featured image for an article about {topic}.
Include a descriptive, click-worthy typographic hook of 3 to 6 words in the center (e.g. "Essential Tips for {topic}"). 
Do NOT write the full lengthy title, but make sure the text clearly describes the content.
Use abstract modern symbols and a soft geometric background.
Modern clean vector or soft 3D illustration, professional blog thumbnail."""
                ),
                (
                    "minimal-abstract",
                    f"""Create a clean abstract 16:9 blog cover image for {topic}.
Include a bold, catchy 3-to-6 word phrase in aesthetic typography that summarizes the topic.
Use simple shapes and digital icons on a bright professional background."""
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
            logger.error(f"Error getting post stats: {e}")
            return None

    def get_recent_posts(self, limit=30):
        """Get recent posts for internal linking"""
        try:
            response = requests.get(
                f"{self.api_url}/posts",
                params={'per_page': limit, '_fields': 'id,title,link'},
                headers=self._get_auth(),
                timeout=10
            )
            if response.status_code == 200:
                posts = []
                import html as html_mod
                for p in response.json():
                    title_rendered = p.get('title', {}).get('rendered', '')
                    title_rendered = html_mod.unescape(title_rendered)
                    posts.append({
                        'title': title_rendered,
                        'url': p.get('link', '')
                    })
                return posts
            return []
        except Exception as e:
            logger.error(f"Error getting recent posts: {e}")
            return []
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((requests.exceptions.ConnectionError, requests.exceptions.Timeout))
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
        retry=retry_if_exception_type((requests.exceptions.ConnectionError, requests.exceptions.Timeout))
    )

    def _prepare_post_payload(self, title, content, category_id=None, featured_image_id=None, meta_description=None, excerpt=None, focus_keyword=None, key_takeaways=None, faqs=None):
        import urllib.parse
        import json
        
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
        content = re.sub(r'<pre[^>]*>.*?[\u2500-\u257F].*?</pre>', '', content, flags=re.DOTALL)
        content = re.sub(r'[\u2500-\u257F]', '', content)
        
        # Remove empty paragraphs
        content = re.sub(r'<p>\s*</p>', '', content)
        content = re.sub(r'<p>\s*\\n\s*</p>', '', content)
        
        # Remove JSON artifacts at the beginning
        content = re.sub(r'^\s*\{\s*"[^"]*"\s*:', '', content)
        content = re.sub(r'"\s*\}\s*$', '', content)
        
        content = content.strip()
        
        # HTML Sanitizer (Fix broken tags)
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(content, 'html.parser')
            for a in soup.find_all('a'):
                if not a.get('href') or a.get('href').startswith('http') == False:
                    pass
            content = str(soup)
        except Exception as e:
            from core_extensions import logger
            logger.warning(f"Failed to sanitize HTML: {e}")
            
        # Inject Key Takeaways Box
        if key_takeaways and isinstance(key_takeaways, list):
            box = f"""<div class="key-takeaways" style="background:#f0f9ff; padding:20px; border-radius:8px; border-left:5px solid #0ea5e9; margin-bottom:25px;">
    <h3 style="margin-top:0; color:#0369a1;">✨ Key Takeaways</h3>
    <ul style="margin-bottom:0;">
        {''.join([f'<li>{k}</li>' for k in key_takeaways])}
    </ul>
</div>"""
            content = box + "\n" + content
            
        # Inject FAQ Schema (JSON-LD)
        if faqs and isinstance(faqs, list):
            schema = {
                "@context": "https://schema.org",
                "@type": "FAQPage",
                "mainEntity": []
            }
            for faq in faqs:
                if 'question' in faq and 'answer' in faq:
                    schema["mainEntity"].append({
                        "@type": "Question",
                        "name": faq["question"],
                        "acceptedAnswer": {
                            "@type": "Answer",
                            "text": faq["answer"]
                        }
                    })
            if schema["mainEntity"]:
                schema_html = f'\n<script type="application/ld+json">{json.dumps(schema)}</script>\n'
                content += schema_html
                
        # YouTube Auto-Embed
        try:
            from duckduckgo_search import DDGS
            search_term = focus_keyword if focus_keyword else title
            ddgs = DDGS()
            results = ddgs.text(f"site:youtube.com {search_term}", max_results=1)
            if results:
                url = results[0].get('href', '')
                parsed = urllib.parse.urlparse(url)
                video_id = None
                if 'youtube.com/watch' in url:
                    qs = urllib.parse.parse_qs(parsed.query)
                    video_id = qs.get('v', [None])[0]
                elif 'youtu.be/' in url:
                    video_id = parsed.path.lstrip('/')
                
                if video_id and re.match(r'^[a-zA-Z0-9_-]{11}$', video_id):
                    iframe = f'\n<div class="video-container" style="position: relative; padding-bottom: 56.25%; height: 0; overflow: hidden; max-width: 100%;"><iframe style="position: absolute; top: 0; left: 0; width: 100%; height: 100%;" src="https://www.youtube.com/embed/{video_id}" frameborder="0" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" allowfullscreen></iframe></div>\n'
                    parts = re.split(r'(<h2.*?>)', content)
                    if len(parts) >= 3:
                        mid_idx = len(parts) // 2
                        if mid_idx % 2 == 0:
                            mid_idx += 1
                        parts.insert(mid_idx, iframe)
                        content = "".join(parts)
                    else:
                        content += iframe
        except Exception as e:
            from core_extensions import logger
            logger.warning(f"Failed to embed YouTube video: {e}")
        
        clean_slug = re.sub(r'\b20[2-9][0-9]\b', '', title).strip()
        
        post_data = {
            'title': title,
            'content': content,
            'status': 'publish',
            'slug': clean_slug
        }
        
        if category_id:
            post_data['categories'] = [category_id]
        if featured_image_id:
            post_data['featured_media'] = featured_image_id
        if excerpt:
            post_data['excerpt'] = excerpt
            
        meta_fields = {}
        if meta_description:
            meta_fields['_yoast_wpseo_metadesc'] = meta_description
            meta_fields['rank_math_description'] = meta_description
        if focus_keyword:
            meta_fields['_yoast_wpseo_focuskw'] = focus_keyword
            meta_fields['rank_math_focus_keyword'] = focus_keyword
            
        if meta_fields:
            post_data['meta'] = meta_fields
            
        return post_data, meta_fields

    def create_post(self, title, content, category_id=None, featured_image_id=None, meta_description=None, excerpt=None, focus_keyword=None, key_takeaways=None, faqs=None):
        headers = self._get_auth()
        headers['Content-Type'] = 'application/json'
        post_data, meta_fields = self._prepare_post_payload(title, content, category_id, featured_image_id, meta_description, excerpt, focus_keyword, key_takeaways, faqs)
        try:
            response = requests.post(
                f"{self.api_url}/posts",
                headers=headers,
                json=post_data,
                timeout=30
            )
        except requests.exceptions.Timeout:
            # WordPress might have saved it, but took too long to respond.
            # We return False but signal a timeout so the caller knows it might exist.
            logger.error("Timeout while waiting for WordPress to publish the post.")
            return False, "TIMEOUT: Post may have been created on WordPress but response timed out."
        except Exception as e:
            logger.error(f"Error publishing post to WordPress: {e}")
            return False, str(e)
            
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
        
    def update_post_content(self, post_id, title, content, category_id=None, featured_image_id=None, meta_description=None, excerpt=None, focus_keyword=None, key_takeaways=None, faqs=None):
        headers = self._get_auth()
        headers['Content-Type'] = 'application/json'
        post_data, meta_fields = self._prepare_post_payload(title, content, category_id, featured_image_id, meta_description, excerpt, focus_keyword, key_takeaways, faqs)
        response = requests.post(
            f"{self.api_url}/posts/{post_id}",
            headers=headers,
            json=post_data,
            timeout=30
        )
        
        # If post updated successfully, try to update Yoast meta separately
        if response.status_code == 200 and meta_fields:
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
        
        return response.status_code == 200, response.json() if response.status_code == 200 else response.text
        

    def get_posts(self, page=1, per_page=100, search=None):
        headers = self._get_auth()
        params = {'page': page, 'per_page': per_page}
        if search:
            params['search'] = search
        
        response = requests.get(
            f"{self.api_url}/posts",
            headers=headers,
            params=params,
            timeout=30
        )
        if response.status_code == 200:
            total_pages = int(response.headers.get('X-WP-TotalPages', 1))
            return True, response.json(), total_pages
        return False, response.text, 0
        
    def update_post(self, post_id, data):
        headers = self._get_auth()
        headers['Content-Type'] = 'application/json'
        
        response = requests.post(
            f"{self.api_url}/posts/{post_id}",
            headers=headers,
            json=data,
            timeout=30
        )
        return response.status_code == 200, response.json() if response.status_code == 200 else response.text

