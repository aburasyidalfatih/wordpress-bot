from google import genai
from google.genai import types
import re
from datetime import datetime
from io import BytesIO
from PIL import Image
import logging
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from config import DEFAULT_GEMINI_MODEL, DEFAULT_GEMINI_IMAGE_MODEL

logger = logging.getLogger(__name__)

# A 2000-2500 word HTML article plus meta, FAQs and takeaways does not fit in 8k
# tokens. Truncated output used to be published as-is with unclosed HTML tags.
MAX_OUTPUT_TOKENS = 16384


class TruncatedGenerationError(Exception):
    """Raised when the model hit the output token limit mid-article."""


def sanitize_filename(name):
    import unicodedata
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
    import html as html_mod
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

class ArticleGenerator:
    def __init__(self, api_key, model=DEFAULT_GEMINI_MODEL, image_model=DEFAULT_GEMINI_IMAGE_MODEL):
        self.client = genai.Client(api_key=api_key)
        self.model = model
        self.image_model = image_model
    
    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=4, max=60),
        retry=retry_if_exception_type((
            genai.errors.ServerError, genai.errors.APIError,
            ConnectionError, TimeoutError, TruncatedGenerationError
        ))
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
        
        # Context for the article is derived from this site's own data (category name,
        # the admin-written category description, and researched keywords) instead of a
        # hardcoded industry vocabulary. AutoWP is multi-tenant: a fixed niche map made
        # every tenant's articles read as if they were about that one niche.
        current_year = datetime.now().year
        category_desc = kwargs.get('category_desc')

        context_parts = [topic]
        if category_desc:
            context_parts.append(category_desc)
        if seo_data:
            for kw in (seo_data.get('keywords') or [])[:8]:
                kw_text = kw.get('keyword') if isinstance(kw, dict) else str(kw)
                if kw_text:
                    context_parts.append(kw_text)
        context = ", ".join(dict.fromkeys(p for p in context_parts if p))

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
        
        # Research evidence handed to the model. Everything factual the article claims
        # must be traceable back to this block; see the EVIDENCE POLICY in the prompt.
        seo_section = ""
        has_evidence = False
        if seo_data:
            keywords = seo_data.get('keywords', [])
            questions = seo_data.get('questions', [])
            semantic_context = seo_data.get('semantic_context', "")
            news_insights = seo_data.get('news_insights', [])

            if semantic_context:
                label = "BACKGROUND CONTEXT" if language == 'en' else "KONTEKS LATAR BELAKANG"
                seo_section += f"\n\n[{label}]\n{semantic_context}\n"
                has_evidence = True

            if news_insights:
                label = "RECENT NEWS (verified sources)" if language == 'en' else "BERITA TERKINI (sumber terverifikasi)"
                seo_section += f"\n\n[{label}]\n"
                for news in news_insights:
                    seo_section += f"- {news}\n"
                has_evidence = True

            # Queries this site already gets impressions for. Strongest signal here,
            # so it goes first and is called out as first-party data.
            search_queries = seo_data.get('search_queries') or []
            if search_queries:
                label = ("SEARCH QUERIES THIS SITE ALREADY RANKS FOR (first-party data)"
                         if language == 'en' else
                         "QUERY PENCARIAN YANG SUDAH MENJANGKAU SITUS INI (data first-party)")
                seo_section += f"\n\n[{label}]\n"
                for item in search_queries:
                    seo_section += (f"- \"{item['query']}\" ({int(item.get('impressions') or 0)} impressions, "
                                    f"position {item.get('position')})\n")
                if language == 'en':
                    seo_section += "Cover these explicitly; they are proven demand, not guesses.\n"
                else:
                    seo_section += "Bahas ini secara eksplisit; ini permintaan yang terbukti, bukan tebakan.\n"
                has_evidence = True

            content_gaps = seo_data.get('content_gaps') or []
            if content_gaps:
                label = ("SUBTOPICS COMPETITORS COVER AND THIS SITE DOES NOT"
                         if language == 'en' else
                         "SUBTOPIK YANG DIBAHAS KOMPETITOR TAPI BELUM ADA DI SITUS INI")
                seo_section += f"\n\n[{label}]\n"
                for gap in content_gaps:
                    seo_section += f"- {gap['topic']}\n"
                if language == 'en':
                    seo_section += "Covering these closes a real gap. Prioritise them where relevant.\n"
                else:
                    seo_section += "Membahas ini menutup celah nyata. Prioritaskan bila relevan.\n"
                has_evidence = True

            intent = seo_data.get('intent')
            if intent:
                label = "SEARCH INTENT" if language == 'en' else "INTENT PENCARIAN"
                guidance = seo_data.get('intent_guidance') or ''
                seo_section += f"\n\n[{label}]\n{intent}. {guidance}\n"

            if keywords:
                label = "RELATED KEYWORDS (use naturally)" if language == 'en' else "KEYWORD TERKAIT (gunakan natural)"
                seo_section += f"\n\n[{label}]\n"
                for kw in keywords[:10]:
                    if isinstance(kw, dict):
                        kw_text = kw.get('keyword')
                        impressions = kw.get('impressions')
                        suffix = f" ({int(impressions)} impressions)" if impressions else ""
                    else:
                        kw_text, suffix = str(kw), ""
                    if kw_text:
                        seo_section += f"- {kw_text}{suffix}\n"

            if questions:
                label = "QUESTIONS REAL USERS ASK (answer these)" if language == 'en' else "PERTANYAAN NYATA PENGGUNA (jawab ini)"
                seo_section += f"\n\n[{label}]\n"
                for q in questions[:5]:
                    q_text = q.get('question') if isinstance(q, dict) else str(q)
                    if q_text:
                        seo_section += f"- {q_text}\n"
                has_evidence = True

            competitor_outlines = seo_data.get('competitor_outlines', [])
            if competitor_outlines:
                label = "TOPICS COMPETITORS COVER" if language == 'en' else "TOPIK YANG DIBAHAS KOMPETITOR"
                seo_section += f"\n\n[{label}]\n"
                for comp in competitor_outlines[:3]:
                    headers_str = ", ".join(comp.get('headers', [])[:5])
                    seo_section += f"- '{comp.get('title')}' covers: {headers_str}\n"
                if language == 'en':
                    seo_section += "Cover these angles at least as thoroughly, and add depth where they are thin.\n"
                else:
                    seo_section += "Bahas sudut pandang ini minimal sama lengkapnya, dan perdalam bagian yang dangkal.\n"
                has_evidence = True

            social_insights = seo_data.get('social_insights', [])
            if social_insights:
                label = "REAL AUDIENCE PAIN POINTS (public discussions)" if language == 'en' else "KELUHAN NYATA AUDIENS (diskusi publik)"
                seo_section += f"\n\n[{label}]\n"
                for insight in social_insights[:5]:
                    insight_text = insight.get('text', '') if isinstance(insight, dict) else str(insight)
                    if insight_text:
                        seo_section += f"- {insight_text}\n"
                if language == 'en':
                    seo_section += "Address these directly. They are real questions from real people.\n"
                else:
                    seo_section += "Jawab ini langsung. Ini pertanyaan nyata dari orang sungguhan.\n"
                has_evidence = True

            youtube_insights = seo_data.get('youtube_insights', [])
            if youtube_insights:
                transcript_items = [yt for yt in youtube_insights if yt.get('transcript_available') and yt.get('snippets')]
                if transcript_items:
                    label = "PRACTITIONER INSIGHTS (video transcripts)" if language == 'en' else "WAWASAN PRAKTISI (transkrip video)"
                    seo_section += f"\n\n[{label}]\n"
                    for yt in transcript_items[:2]:
                        seo_section += f"- Video '{yt.get('title')}': {yt.get('snippets')}\n"
                    if language == 'en':
                        seo_section += "You may cite these, attributed to the video title. Do not invent additional quotes.\n"
                    else:
                        seo_section += "Boleh dikutip dengan menyebut judul videonya. Jangan mengarang kutipan tambahan.\n"
                    has_evidence = True

        # The single most important rule in this prompt. The previous version asked the
        # model to invent "realistic" case studies, named people and statistics. That is
        # fabricated E-E-A-T and is precisely what Google's spam and helpful-content
        # policies target.
        if language == 'en':
            evidence_state = ("You have been given researched evidence above."
                              if has_evidence else
                              "You have NOT been given researched evidence for this topic.")
            evidence_policy = f"""

=== EVIDENCE POLICY (HIGHEST PRIORITY - OVERRIDES EVERYTHING ELSE) ===
{evidence_state}

ABSOLUTE RULES:
1. NEVER invent statistics, percentages, survey results, or numeric claims. Use a
   number ONLY if it appears in the evidence above. Otherwise describe the effect
   qualitatively ("costs typically fall", not "costs fall 40%").
2. NEVER invent quotes. Do not attribute statements to named people, companies, or
   institutions that were not given to you above. No made-up experts, no made-up
   customers, no "realistic" placeholder names.
3. NEVER claim first-hand experience the publisher does not have. Do not write
   "based on our experience with 50+ clients", "our internal data shows", or any
   similar manufactured credential.
4. Case studies must be clearly generic and hypothetical when not evidence-backed.
   Write "consider an organisation that..." - NOT "Acme Corp in Chicago grew 40%".
5. If you cannot support a claim, make a weaker but honest claim. An accurate article
   that is less impressive beats a confident article that is fabricated.
6. Demonstrate expertise through clear reasoning, useful structure, correct
   terminology and genuinely practical guidance - not through invented authority.

Violating any rule above makes the article unusable.
=== END EVIDENCE POLICY ===
"""
        else:
            evidence_state = ("Kamu sudah diberi data riset di atas."
                              if has_evidence else
                              "Kamu TIDAK diberi data riset untuk topik ini.")
            evidence_policy = f"""

=== KEBIJAKAN BUKTI (PRIORITAS TERTINGGI - MENGALAHKAN SEMUA ATURAN LAIN) ===
{evidence_state}

ATURAN MUTLAK:
1. JANGAN PERNAH mengarang statistik, persentase, hasil survei, atau klaim angka.
   Gunakan angka HANYA jika muncul di data riset di atas. Kalau tidak ada, jelaskan
   secara kualitatif ("biaya biasanya turun", bukan "biaya turun 40%").
2. JANGAN PERNAH mengarang kutipan. Jangan mengatribusikan pernyataan kepada orang,
   perusahaan, atau lembaga bernama yang tidak diberikan di atas. Tidak ada pakar
   karangan, tidak ada narasumber karangan, tidak ada nama "yang realistis".
3. JANGAN mengklaim pengalaman langsung yang tidak dimiliki penerbit. Jangan menulis
   "berdasarkan pengalaman kami menangani 50+ klien", "data internal kami menunjukkan",
   atau kredensial buatan sejenis.
4. Studi kasus harus jelas bersifat umum dan hipotetis kalau tidak didukung data.
   Tulis "bayangkan sebuah organisasi yang..." - BUKAN "SMA Harapan di Bandung naik 40%".
5. Kalau sebuah klaim tidak bisa didukung, tulis klaim yang lebih lemah tapi jujur.
   Artikel akurat yang terdengar biasa lebih baik daripada artikel meyakinkan yang palsu.
6. Tunjukkan keahlian lewat penalaran jernih, struktur rapi, istilah yang tepat, dan
   panduan yang benar-benar bisa dipraktikkan - bukan lewat otoritas karangan.

Melanggar salah satu aturan di atas membuat artikel tidak bisa dipakai.
=== AKHIR KEBIJAKAN BUKTI ===
"""

        category_desc_text = ""
        if category_desc:
            if language == 'en':
                category_desc_text = f"\n\n[CATEGORY BRIEF]\n{category_desc}\nFollow this brief for the article's scope and angle."
            else:
                category_desc_text = f"\n\n[BRIEF KATEGORI]\n{category_desc}\nIkuti brief ini untuk ruang lingkup dan sudut pandang artikel."

        internal_links_text = ""
        allowed_link_urls = []
        if internal_links_context:
            allowed_link_urls = [p['url'] for p in internal_links_context[:30] if p.get('url')]
            if language == 'en':
                internal_links_text = "\n\n[INTERNAL LINKING]\nPreviously published articles on this site:\n"
                for post in internal_links_context[:30]:
                    internal_links_text += f"- {post['title']} -> {post['url']}\n"
                internal_links_text += (
                    "Weave 3-5 of these into your paragraphs as natural HTML links "
                    "<a href=\"URL\">anchor text</a>. CRITICAL: only use URLs copied "
                    "exactly from the list above. Never invent a URL. Do not add a link "
                    "list at the end.\n"
                )
            else:
                internal_links_text = "\n\n[INTERNAL LINKING]\nArtikel yang sudah terbit di situs ini:\n"
                for post in internal_links_context[:30]:
                    internal_links_text += f"- {post['title']} -> {post['url']}\n"
                internal_links_text += (
                    "Sisipkan 3-5 di antaranya ke dalam paragraf sebagai link HTML natural "
                    "<a href=\"URL\">teks anchor</a>. PENTING: gunakan HANYA URL yang "
                    "disalin persis dari daftar di atas. Jangan pernah mengarang URL. "
                    "Jangan membuat daftar link di akhir artikel.\n"
                )

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
            prompt = prompt.replace('{current_year}', str(current_year))
        elif language == 'en':
            prompt = f"""Write an in-depth, genuinely useful article for the website {target_site} about: {topic_focus}
{existing_titles_text}{research_note}{seo_section}{category_desc_text}{internal_links_text}
TARGET AUDIENCE: {target_audience}
TOPIC CONTEXT: {context}
CURRENT YEAR: {current_year} (use this year when a year is relevant)

LENGTH: 2000-2500 words. Depth comes from genuinely covering the subject, not from
padding. Every section must add information a reader could act on.

STRUCTURE:

1. OPENING (about 100 words)
   Vary the approach between articles - a concrete scenario, a sharp problem
   statement, a question, or a counter-intuitive observation. End by telling the
   reader what they will be able to do after reading.

2. KEY POINTS BOX (for Answer Engine Optimization / AI Overviews)
   <div class="executive-summary" style="background:#f8fafc; padding:15px; border-left:4px solid #4f46e5; margin-bottom:20px;">
   containing a <ul> of 3 bullets that answer the core question directly and
   specifically. These must be real answers, not teasers.

3. CONTEXT (about 200 words)
   Why this matters now, and who it matters most to.

4. MAIN BODY (1500-1700 words)
   H2: Core concept and why it matters (~300 words)
       Clear definition in plain language. Concrete, checkable examples.
   H2: Step-by-step implementation (~600 words)
       Numbered, actionable steps. Realistic timeframes. Tools or templates that
       genuinely exist. A starting checklist.
   H2: Worked example (~400 words)
       A clearly hypothetical scenario ("consider a mid-sized team that...").
       Walk through challenge, approach, and outcome. Keep outcomes qualitative
       unless the evidence section gave you real figures.
   H2: Practical tips and common mistakes (~300 words)
       A do/don't comparison as an HTML <table>. Real mistakes people make.

5. CONCLUSION (about 150 words)
   Recap the 3-5 things that matter most, then a clear next step.

6. FAQ (about 150 words)
   3-5 questions people genuinely ask, with direct answers.

WRITING QUALITY:
- Tone: professional but direct. Address the reader as "you".
- Use <strong> on key terms, metrics and concepts so the page is scannable.
- Use related terminology naturally. Never keyword-stuff.
- Vary sentence length deliberately. Short sentences for emphasis. Longer ones to
  develop an argument fully. Avoid a uniform rhythm.
- Short paragraphs: 2-3 sentences, often one.
- Avoid filler openers: "It is important to note that", "In this context",
  "Let's discuss", "In conclusion".
- Every article must open differently from the ones listed above.

SEO:
- Focus keyword within the first 100 words.
- Keyword variations in H2 headings.
- Structure list and table content so it can be lifted as a featured snippet.
- Use the internal links exactly as instructed above.

FORMATTING RULES:
- No emoji anywhere in the content.
- No placeholder markers like [INFOGRAPHIC: ...] or [CHECKLIST: ...].
- No ASCII art or box-drawing characters. Tables must be real HTML <table>.
- Do not repeat the title inside the content.
- Do not write literal section labels such as "H2:" or "1. OPENING" in the output.

OUTPUT FORMAT - use these XML tags exactly, no JSON, no markdown fences:
<TITLE>Compelling, accurate title, 50-60 characters. Title text only.</TITLE>
<META_DESCRIPTION>150-160 characters, specific to THIS article, includes the keyword.</META_DESCRIPTION>
<FOCUS_KEYWORD>primary keyword</FOCUS_KEYWORD>
<EXCERPT>One or two sentences summarising what THIS specific article covers, 140-160 characters. Must not be generic.</EXCERPT>
<KEY_TAKEAWAYS>
- First specific takeaway drawn from this article's actual content
- Second specific takeaway
- Third specific takeaway
</KEY_TAKEAWAYS>
<CONTENT>
Full HTML article, 2000-2500 words. Start with the opening paragraph. Use h2, h3,
strong, em, ul, ol, table, blockquote.
</CONTENT>
<FAQS>
Q: Question 1?
A: Answer 1

Q: Question 2?
A: Answer 2
</FAQS>
"""
        else:
            prompt = f"""Tulis artikel mendalam yang benar-benar berguna untuk website {target_site} tentang: {topic_focus}
{existing_titles_text}{research_note}{seo_section}{category_desc_text}{internal_links_text}
TARGET PEMBACA: {target_audience}
KONTEKS TOPIK: {context}
TAHUN SEKARANG: {current_year} (pakai tahun ini kalau perlu menyebut tahun)

PANJANG: 2000-2500 kata. Kedalaman datang dari benar-benar membahas topiknya, bukan
dari mengulang-ulang. Setiap bagian harus menambah informasi yang bisa ditindaklanjuti.

STRUKTUR:

1. PEMBUKA (sekitar 100 kata)
   Variasikan pendekatan antar artikel - skenario konkret, pernyataan masalah yang
   tajam, pertanyaan, atau pengamatan yang berlawanan dengan dugaan umum. Akhiri
   dengan menjelaskan apa yang bisa pembaca lakukan setelah membaca.

2. KOTAK POIN UTAMA (untuk Answer Engine Optimization / AI Overviews)
   <div class="executive-summary" style="background:#f8fafc; padding:15px; border-left:4px solid #4f46e5; margin-bottom:20px;">
   berisi <ul> dengan 3 poin yang menjawab inti pertanyaan secara langsung dan
   spesifik. Ini harus jawaban sungguhan, bukan pancingan.

3. KONTEKS (sekitar 200 kata)
   Kenapa ini penting sekarang, dan siapa yang paling membutuhkannya.

4. ISI UTAMA (1500-1700 kata)
   H2: Konsep inti dan kenapa penting (~300 kata)
       Definisi jelas dengan bahasa sederhana. Contoh konkret yang bisa dicek.
   H2: Implementasi langkah demi langkah (~600 kata)
       Langkah bernomor yang bisa dikerjakan. Perkiraan waktu yang realistis.
       Tools atau template yang benar-benar ada. Checklist untuk memulai.
   H2: Contoh penerapan (~400 kata)
       Skenario yang jelas hipotetis ("bayangkan sebuah tim berukuran menengah
       yang..."). Bahas tantangan, pendekatan, dan hasilnya. Jaga hasil tetap
       kualitatif kecuali bagian data riset memberimu angka nyata.
   H2: Tips praktis dan kesalahan umum (~300 kata)
       Perbandingan lakukan/hindari dalam bentuk <table> HTML. Kesalahan nyata
       yang sering terjadi.

5. KESIMPULAN (sekitar 150 kata)
   Rangkum 3-5 hal terpenting, lalu langkah lanjutan yang jelas.

6. FAQ (sekitar 150 kata)
   3-5 pertanyaan yang benar-benar sering ditanyakan, dengan jawaban langsung.

KUALITAS PENULISAN:
- Nada: profesional tapi lugas. Sapa pembaca dengan "Anda".
- Gunakan <strong> pada istilah kunci, metrik, dan konsep penting agar mudah dipindai.
- Gunakan istilah terkait secara natural. Jangan menumpuk keyword.
- Variasikan panjang kalimat dengan sengaja. Kalimat pendek untuk penegasan. Kalimat
  panjang untuk mengembangkan argumen. Hindari ritme yang seragam.
- Paragraf pendek: 2-3 kalimat, sering cukup satu.
- Hindari pembuka kosong: "Penting untuk dicatat bahwa", "Dalam konteks ini",
  "Mari kita bahas", "Kesimpulannya".
- Setiap artikel harus dibuka berbeda dari judul-judul yang terdaftar di atas.

SEO:
- Focus keyword muncul di 100 kata pertama.
- Variasi keyword di heading H2.
- Susun isi list dan tabel supaya bisa diangkat jadi featured snippet.
- Gunakan link internal persis seperti instruksi di atas.

ATURAN FORMAT:
- Tidak ada emoji di dalam konten.
- Tidak ada penanda placeholder seperti [INFOGRAFIS: ...] atau [CHECKLIST: ...].
- Tidak ada ASCII art atau karakter box-drawing. Tabel harus <table> HTML asli.
- Jangan mengulang judul di dalam konten.
- Jangan menulis label struktur seperti "H2:" atau "1. PEMBUKA" di output.

FORMAT OUTPUT - gunakan tag XML berikut persis, tanpa JSON, tanpa pagar markdown:
<TITLE>Judul menarik dan akurat, 50-60 karakter. Hanya teks judul.</TITLE>
<META_DESCRIPTION>150-160 karakter, spesifik untuk artikel INI, mengandung keyword.</META_DESCRIPTION>
<FOCUS_KEYWORD>keyword utama</FOCUS_KEYWORD>
<EXCERPT>Satu atau dua kalimat yang merangkum isi spesifik artikel INI, 140-160 karakter. Tidak boleh generik.</EXCERPT>
<KEY_TAKEAWAYS>
- Poin spesifik pertama yang diambil dari isi artikel ini
- Poin spesifik kedua
- Poin spesifik ketiga
</KEY_TAKEAWAYS>
<CONTENT>
Artikel HTML lengkap 2000-2500 kata. Mulai langsung dengan paragraf pembuka. Gunakan
h2, h3, strong, em, ul, ol, table, blockquote.
</CONTENT>
<FAQS>
Q: Pertanyaan 1?
A: Jawaban 1

Q: Pertanyaan 2?
A: Jawaban 2
</FAQS>
"""

        # The evidence policy is appended last so it is the most recent instruction the
        # model sees, and it explicitly outranks anything above it.
        system_rules = f"""

=== OUTPUT CONTRACT ===
1. Do NOT write literal template labels (e.g. "H2:", "1. OPENING") in the HTML.
2. Do NOT use emoji in the content.
3. Output MUST use the XML tags specified. Never output JSON.
4. Write the full 2000-2500 words inside <CONTENT>. Close every HTML tag you open.
5. <EXCERPT> and <KEY_TAKEAWAYS> must describe THIS article specifically. Generic
   filler such as "practical tips you can apply immediately" is rejected.
{evidence_policy}"""
        prompt = prompt + "\n\n" + system_rules

        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                # Lower than before: this content makes factual claims, and high
                # temperature was compounding the fabrication problem.
                temperature=0.7,
                top_p=0.9,
                max_output_tokens=MAX_OUTPUT_TOKENS
            )
        )

        # Detect a hard stop at the token ceiling. Previously truncated output was
        # silently salvaged by the unclosed-tag fallback below and published with
        # broken HTML; now it fails so @retry can regenerate.
        for candidate in getattr(response, 'candidates', None) or []:
            finish_reason = str(getattr(candidate, 'finish_reason', '') or '')
            if 'MAX_TOKENS' in finish_reason.upper():
                raise TruncatedGenerationError(
                    f"Model hit the {MAX_OUTPUT_TOKENS} output token limit; "
                    "article was cut off mid-generation."
                )

        response_text = (response.text or '').strip()

        if response_text.startswith('```'):
            response_text = response_text.replace('```json', '').replace('```', '').strip()

        # Strip control characters, keeping newlines and tabs.
        response_text = re.sub(r'[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f-\x9f]', '', response_text)

        def extract_tag(tag, text, default=""):
            match = re.search(f'<{tag}>(.*?)</{tag}>', text, re.DOTALL | re.IGNORECASE)
            if match:
                return match.group(1).strip()
            # Unclosed tag: the model stopped early. Salvage what is there; the
            # quality gate downstream decides whether it is publishable.
            match_open = re.search(f'<{tag}>(.*)', text, re.DOTALL | re.IGNORECASE)
            if match_open:
                logger.warning(f"Tag <{tag}> was not closed in model output; salvaging partial value.")
                return match_open.group(1).strip()
            return default

        title = extract_tag('TITLE', response_text)
        meta_desc = extract_tag('META_DESCRIPTION', response_text)
        content = extract_tag('CONTENT', response_text)
        focus_keyword = extract_tag('FOCUS_KEYWORD', response_text, default=topic)
        excerpt = extract_tag('EXCERPT', response_text)

        if not content:
            content = response_text

        for tag in ['TITLE', 'META_DESCRIPTION', 'CONTENT', 'FOCUS_KEYWORD',
                    'FAQS', 'EXCERPT', 'KEY_TAKEAWAYS']:
            content = re.sub(f'</?{tag}>', '', content, flags=re.IGNORECASE)

        content = content.replace('```html', '').replace('```', '').strip()

        if not title:
            first_heading = re.search(r'<h[12][^>]*>(.*?)</h[12]>', content, re.DOTALL | re.IGNORECASE)
            if first_heading:
                title = strip_html(first_heading.group(1))[:200]
            else:
                title = strip_html(content)[:120].rsplit(' ', 1)[0]

        # Parse FAQs. Tolerates a missing trailing newline on the last pair, which the
        # previous newline-anchored regex silently dropped.
        faqs_text = extract_tag('FAQS', response_text)
        faqs = []
        if faqs_text:
            pairs = re.findall(
                r'Q:\s*(.+?)\s*\n\s*A:\s*(.*?)(?=\n\s*Q:|$)',
                faqs_text,
                re.DOTALL
            )
            for question, answer in pairs:
                question = question.strip()
                answer = strip_html(answer).strip()
                if question and answer:
                    faqs.append({"question": question, "answer": answer})

        # Key takeaways come from the model, describing this article. Only if that is
        # missing do we fall back to the article's own H2 headings. Neither path uses a
        # fixed template, so the box is no longer identical across every post.
        takeaways_text = extract_tag('KEY_TAKEAWAYS', response_text)
        key_takeaways = []
        if takeaways_text:
            for line in takeaways_text.split('\n'):
                line = re.sub(r'^\s*[-*\u2022]\s*', '', line).strip()
                line = strip_html(line)
                if len(line) > 8:
                    key_takeaways.append(line)
        if not key_takeaways:
            key_takeaways = derive_takeaways(content)

        if not excerpt:
            excerpt = derive_excerpt(content)
        if not meta_desc:
            meta_desc = excerpt or derive_excerpt(content)

        plain_text = strip_html(content)
        word_count = len(plain_text.split())
        reading_time = (f"{max(1, word_count // 200)} min read" if language == 'en'
                        else f"{max(1, word_count // 200)} menit")

        return {
            "title": title,
            "meta_description": meta_desc,
            "content": content,
            "focus_keyword": focus_keyword,
            "excerpt": excerpt,
            "reading_time": reading_time,
            "key_takeaways": key_takeaways,
            "faqs": faqs,
            "word_count": word_count,
            "allowed_link_urls": allowed_link_urls
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


