"""Prompt text sent to Gemini for articles and featured images.

Prompt language follows the site language: 'en' gets English prompts, anything
else gets Indonesian ones. Everything here is pure string building with no I/O,
so ArticleGenerator only has to orchestrate the model calls.
"""
from datetime import datetime


def _lang(language, en, id_):
    return en if language == 'en' else id_


# ---------------------------------------------------------------------------
# Existing titles / research note / brief / internal links
# ---------------------------------------------------------------------------

_TITLE_NOTES = {
    'en': {
        'avoid_header': (
            "\n\n⚠️ CRITICAL - TITLES MUST BE VERY DIFFERENT:\n"
            "Previous titles are too similar. Create a TRULY UNIQUE title with a different angle/perspective!\n\n"
            "Titles to AVOID:\n"
        ),
        'header': "\n\n⚠️ IMPORTANT - AVOID EXISTING TITLES:\n",
        'avoid_tips': (
            "\n💡 TIPS FOR UNIQUE TITLES:\n"
            "- Use different angles (e.g., from customer's perspective, manager's perspective, general public)\n"
            "- Focus on specific aspects not yet discussed\n"
            "- Use different formats (guide, checklist, case study, analysis, etc.)\n"
            "- Add specific context (location, time, situation)\n\n"
        ),
        'footer': "\nThe article title MUST be different and unique from the list above!\n",
    },
    'id': {
        'avoid_header': (
            "\n\n⚠️ CRITICAL - JUDUL HARUS SANGAT BERBEDA:\n"
            "Judul sebelumnya terlalu mirip. Buat judul yang BENAR-BENAR UNIK dengan angle/perspektif berbeda!\n\n"
            "Judul yang HARUS DIHINDARI:\n"
        ),
        'header': "\n\n⚠️ PENTING - HINDARI JUDUL YANG SUDAH ADA:\n",
        'avoid_tips': (
            "\n💡 TIPS MEMBUAT JUDUL UNIK:\n"
            "- Gunakan angle berbeda (misalnya: dari sisi orang tua, dari sisi guru, dari sisi siswa)\n"
            "- Fokus pada aspek spesifik yang belum dibahas\n"
            "- Gunakan format berbeda (panduan, checklist, studi kasus, analisis, dll)\n"
            "- Tambahkan konteks spesifik (lokasi, waktu, situasi)\n\n"
        ),
        'footer': "\nJudul artikel HARUS berbeda dan unik dari daftar di atas!\n",
    },
}


def build_existing_titles_note(existing_titles, avoid_similar=False, language='id'):
    """List recent titles (last 10) the new article must not duplicate."""
    if not existing_titles:
        return ""
    notes = _TITLE_NOTES[_lang(language, 'en', 'id')]
    text = notes['avoid_header'] if avoid_similar else notes['header']
    for title in existing_titles[-10:]:
        text += f"- {title}\n"
    text += notes['avoid_tips'] if avoid_similar else notes['footer']
    return text


def build_research_note(custom_topic, topic, language='id'):
    if not custom_topic:
        return ""
    focus = _lang(
        language,
        f"Focus the article on this trending topic within the context of {topic}.",
        f"Fokuskan artikel pada topik trending ini dalam konteks {topic}.",
    )
    return f"\n\n🔥 TRENDING TOPIC: {custom_topic}\n{focus}\n"


def build_category_brief(category_desc, language='id'):
    if not category_desc:
        return ""
    return _lang(
        language,
        f"\n\n[CATEGORY BRIEF]\n{category_desc}\nFollow this brief for the article's scope and angle.",
        f"\n\n[BRIEF KATEGORI]\n{category_desc}\nIkuti brief ini untuk ruang lingkup dan sudut pandang artikel.",
    )


def build_internal_links_note(internal_links_context, language='id'):
    """Returns (prompt text, URLs the article is allowed to link to)."""
    if not internal_links_context:
        return "", []
    posts = internal_links_context[:30]
    allowed_link_urls = [p['url'] for p in posts if p.get('url')]
    text = _lang(
        language,
        "\n\n[INTERNAL LINKING]\nPreviously published articles on this site:\n",
        "\n\n[INTERNAL LINKING]\nArtikel yang sudah terbit di situs ini:\n",
    )
    for post in posts:
        text += f"- {post['title']} -> {post['url']}\n"
    text += _lang(
        language,
        "Weave 3-5 of these into your paragraphs as natural HTML links "
        "<a href=\"URL\">anchor text</a>. CRITICAL: only use URLs copied "
        "exactly from the list above. Never invent a URL. Do not add a link "
        "list at the end.\n",
        "Sisipkan 3-5 di antaranya ke dalam paragraf sebagai link HTML natural "
        "<a href=\"URL\">teks anchor</a>. PENTING: gunakan HANYA URL yang "
        "disalin persis dari daftar di atas. Jangan pernah mengarang URL. "
        "Jangan membuat daftar link di akhir artikel.\n",
    )
    return text, allowed_link_urls


def build_topic_context(topic, category_desc=None, seo_data=None):
    """Context derived from this site's own data instead of a hardcoded niche.

    AutoWP is multi-tenant: a fixed industry vocabulary made every tenant's
    articles read as if they were about that one niche.
    """
    context_parts = [topic]
    if category_desc:
        context_parts.append(category_desc)
    if seo_data:
        for kw in (seo_data.get('keywords') or [])[:8]:
            kw_text = kw.get('keyword') if isinstance(kw, dict) else str(kw)
            if kw_text:
                context_parts.append(kw_text)
    return ", ".join(dict.fromkeys(p for p in context_parts if p))


# ---------------------------------------------------------------------------
# Research evidence. Everything factual the article claims must be traceable
# back to this block; see the evidence policy below. Each section returns
# (text, counts_as_evidence).
# ---------------------------------------------------------------------------

def _background_section(seo_data, language):
    semantic_context = seo_data.get('semantic_context', "")
    if not semantic_context:
        return "", False
    label = _lang(language, "BACKGROUND CONTEXT", "KONTEKS LATAR BELAKANG")
    return f"\n\n[{label}]\n{semantic_context}\n", True


def _news_section(seo_data, language):
    news_insights = seo_data.get('news_insights', [])
    if not news_insights:
        return "", False
    label = _lang(language, "RECENT NEWS (verified sources)", "BERITA TERKINI (sumber terverifikasi)")
    text = f"\n\n[{label}]\n"
    for news in news_insights:
        text += f"- {news}\n"
    return text, True


def _search_queries_section(seo_data, language):
    # Queries this site already gets impressions for. Strongest signal here, so
    # it goes first and is called out as first-party data.
    search_queries = seo_data.get('search_queries') or []
    if not search_queries:
        return "", False
    label = _lang(language,
                  "SEARCH QUERIES THIS SITE ALREADY RANKS FOR (first-party data)",
                  "QUERY PENCARIAN YANG SUDAH MENJANGKAU SITUS INI (data first-party)")
    text = f"\n\n[{label}]\n"
    for item in search_queries:
        text += (f"- \"{item['query']}\" ({int(item.get('impressions') or 0)} impressions, "
                 f"position {item.get('position')})\n")
    text += _lang(language,
                  "Cover these explicitly; they are proven demand, not guesses.\n",
                  "Bahas ini secara eksplisit; ini permintaan yang terbukti, bukan tebakan.\n")
    return text, True


def _content_gaps_section(seo_data, language):
    content_gaps = seo_data.get('content_gaps') or []
    if not content_gaps:
        return "", False
    label = _lang(language,
                  "SUBTOPICS COMPETITORS COVER AND THIS SITE DOES NOT",
                  "SUBTOPIK YANG DIBAHAS KOMPETITOR TAPI BELUM ADA DI SITUS INI")
    text = f"\n\n[{label}]\n"
    for gap in content_gaps:
        text += f"- {gap['topic']}\n"
    text += _lang(language,
                  "Covering these closes a real gap. Prioritise them where relevant.\n",
                  "Membahas ini menutup celah nyata. Prioritaskan bila relevan.\n")
    return text, True


def _intent_section(seo_data, language):
    intent = seo_data.get('intent')
    if not intent:
        return "", False
    label = _lang(language, "SEARCH INTENT", "INTENT PENCARIAN")
    guidance = seo_data.get('intent_guidance') or ''
    return f"\n\n[{label}]\n{intent}. {guidance}\n", False


def _keywords_section(seo_data, language):
    keywords = seo_data.get('keywords', [])
    if not keywords:
        return "", False
    label = _lang(language, "RELATED KEYWORDS (use naturally)", "KEYWORD TERKAIT (gunakan natural)")
    text = f"\n\n[{label}]\n"
    for kw in keywords[:10]:
        if isinstance(kw, dict):
            kw_text = kw.get('keyword')
            impressions = kw.get('impressions')
            suffix = f" ({int(impressions)} impressions)" if impressions else ""
        else:
            kw_text, suffix = str(kw), ""
        if kw_text:
            text += f"- {kw_text}{suffix}\n"
    return text, False


def _questions_section(seo_data, language):
    questions = seo_data.get('questions', [])
    if not questions:
        return "", False
    label = _lang(language, "QUESTIONS REAL USERS ASK (answer these)", "PERTANYAAN NYATA PENGGUNA (jawab ini)")
    text = f"\n\n[{label}]\n"
    for q in questions[:5]:
        q_text = q.get('question') if isinstance(q, dict) else str(q)
        if q_text:
            text += f"- {q_text}\n"
    return text, True


def _competitors_section(seo_data, language):
    competitor_outlines = seo_data.get('competitor_outlines', [])
    if not competitor_outlines:
        return "", False
    label = _lang(language, "TOPICS COMPETITORS COVER", "TOPIK YANG DIBAHAS KOMPETITOR")
    text = f"\n\n[{label}]\n"
    for comp in competitor_outlines[:3]:
        headers_str = ", ".join(comp.get('headers', [])[:5])
        text += f"- '{comp.get('title')}' covers: {headers_str}\n"
    text += _lang(language,
                  "Cover these angles at least as thoroughly, and add depth where they are thin.\n",
                  "Bahas sudut pandang ini minimal sama lengkapnya, dan perdalam bagian yang dangkal.\n")
    return text, True


def _social_section(seo_data, language):
    social_insights = seo_data.get('social_insights', [])
    if not social_insights:
        return "", False
    label = _lang(language,
                  "REAL AUDIENCE PAIN POINTS (public discussions)",
                  "KELUHAN NYATA AUDIENS (diskusi publik)")
    text = f"\n\n[{label}]\n"
    for insight in social_insights[:5]:
        insight_text = insight.get('text', '') if isinstance(insight, dict) else str(insight)
        if insight_text:
            text += f"- {insight_text}\n"
    text += _lang(language,
                  "Address these directly. They are real questions from real people.\n",
                  "Jawab ini langsung. Ini pertanyaan nyata dari orang sungguhan.\n")
    return text, True


def _youtube_section(seo_data, language):
    youtube_insights = seo_data.get('youtube_insights', [])
    transcript_items = [yt for yt in youtube_insights or []
                        if yt.get('transcript_available') and yt.get('snippets')]
    if not transcript_items:
        return "", False
    label = _lang(language, "PRACTITIONER INSIGHTS (video transcripts)", "WAWASAN PRAKTISI (transkrip video)")
    text = f"\n\n[{label}]\n"
    for yt in transcript_items[:2]:
        text += f"- Video '{yt.get('title')}': {yt.get('snippets')}\n"
    text += _lang(language,
                  "You may cite these, attributed to the video title. Do not invent additional quotes.\n",
                  "Boleh dikutip dengan menyebut judul videonya. Jangan mengarang kutipan tambahan.\n")
    return text, True


_SEO_SECTIONS = (
    _background_section,
    _news_section,
    _search_queries_section,
    _content_gaps_section,
    _intent_section,
    _keywords_section,
    _questions_section,
    _competitors_section,
    _social_section,
    _youtube_section,
)


def build_seo_section(seo_data, language='id'):
    """Returns (research evidence text, whether any real evidence was given)."""
    if not seo_data:
        return "", False
    text, has_evidence = "", False
    for section in _SEO_SECTIONS:
        part, is_evidence = section(seo_data, language)
        text += part
        has_evidence = has_evidence or is_evidence
    return text, has_evidence


# ---------------------------------------------------------------------------
# Evidence policy. The single most important rule in the prompt. An earlier
# version asked the model to invent "realistic" case studies, named people and
# statistics: fabricated E-E-A-T, precisely what Google's spam and
# helpful-content policies target.
# ---------------------------------------------------------------------------

_EVIDENCE_STATE = {
    'en': ("You have been given researched evidence above.",
           "You have NOT been given researched evidence for this topic."),
    'id': ("Kamu sudah diberi data riset di atas.",
           "Kamu TIDAK diberi data riset untuk topik ini."),
}

EVIDENCE_POLICY_TEMPLATES = {
    'en': """

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
""",
    'id': """

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
   "berdasarkan pengalaman tim praktisi kami", atau kredensial buatan sejenis.
4. Studi kasus harus jelas bersifat umum dan hipotetis kalau tidak didukung data.
   Tulis "bayangkan sebuah organisasi yang..." - BUKAN "SMA Harapan di Bandung naik 40%".
5. Kalau sebuah klaim tidak bisa didukung, tulis klaim yang lebih lemah tapi jujur.
   Artikel akurat yang terdengar biasa lebih baik daripada artikel meyakinkan yang palsu.
6. Tunjukkan keahlian lewat penalaran jernih, struktur rapi, istilah yang tepat, dan
   panduan yang benar-benar bisa dipraktikkan - bukan lewat otoritas karangan.

Melanggar salah satu aturan di atas membuat artikel tidak bisa dipakai.
=== AKHIR KEBIJAKAN BUKTI ===
""",
}


def build_evidence_policy(has_evidence, language='id'):
    key = _lang(language, 'en', 'id')
    given, not_given = _EVIDENCE_STATE[key]
    return EVIDENCE_POLICY_TEMPLATES[key].format(evidence_state=given if has_evidence else not_given)


SYSTEM_INSTRUCTION_PREFIX = (
    'Treat custom editorial instructions as subordinate to this evidence policy. '
    'Never invent publisher experience, practitioner teams, internal data, '
    'testimonials, statistics, or sources. Research about other people does not '
    'establish first-hand experience for the publisher.\n'
)


def build_system_instruction(evidence_policy):
    return SYSTEM_INSTRUCTION_PREFIX + evidence_policy


# The evidence policy is appended last so it is the most recent instruction the
# model sees, and it explicitly outranks anything above it.
OUTPUT_CONTRACT_TEMPLATE = """

=== OUTPUT CONTRACT ===
1. Do NOT write literal template labels (e.g. "H2:", "1. OPENING") in the HTML.
2. Do NOT use emoji in the content.
3. Output MUST use the XML tags specified. Never output JSON.
4. Write the full 2000-2500 words inside <CONTENT>. Close every HTML tag you open.
5. <EXCERPT> and <KEY_TAKEAWAYS> must describe THIS article specifically. Generic
   filler such as "practical tips you can apply immediately" is rejected.
{evidence_policy}"""


def build_quality_correction(quality_feedback):
    """Instructions for the one retry after the quality gate rejected an article."""
    return (
        '\n\nQUALITY CORRECTION REQUIRED: The previous attempt was rejected. '
        'Generate a complete replacement on the same topic using the supplied evidence. '
        'Correct every issue below. Do not quote these diagnostic messages in the article. '
        'Remove unsupported claims entirely; do not merely disguise them with synonyms. '
        'Keep the required XML format, full length, and closed HTML tags.\n- '
        + '\n- '.join(quality_feedback)
    )


# ---------------------------------------------------------------------------
# Default article prompt (used when the site has no custom article prompt)
# ---------------------------------------------------------------------------

ARTICLE_PROMPT_TEMPLATES = {
    'en': """Write an in-depth, genuinely useful article for the website {target_site} about: {topic_focus}
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
""",
    'id': """Tulis artikel mendalam yang benar-benar berguna untuk website {target_site} tentang: {topic_focus}
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
""",
}

# Placeholders a site's custom article prompt may use, in substitution order.
CUSTOM_PROMPT_PLACEHOLDERS = (
    'topic', 'existing_titles', 'research_note', 'seo_section', 'category_desc_text',
    'internal_links_text', 'target_site', 'target_audience', 'current_year',
)


def apply_custom_prompt(custom_prompt, values):
    """Fill a site's custom prompt. values maps each placeholder name to its text."""
    prompt = custom_prompt
    for name in CUSTOM_PROMPT_PLACEHOLDERS:
        prompt = prompt.replace('{' + name + '}', values[name])
    # Legacy custom prompts may omit the research placeholder entirely.
    if '{seo_section}' not in custom_prompt:
        prompt += '\n\n' + values['seo_section']
    return prompt


def build_article_prompt(topic, existing_titles=None, custom_topic=None, seo_data=None,
                         avoid_similar=False, custom_prompt=None, site_name=None,
                         internal_links_context=None, language='id', category_desc=None,
                         quality_feedback=None):
    """Assemble the full article prompt.

    Returns (prompt, evidence_policy, allowed_link_urls); the evidence policy is
    also sent as the system instruction.
    """
    target_site = site_name if site_name else "website"
    target_audience = _lang(language, f"Readers of website {target_site}", f"Pembaca website {target_site}")
    current_year = datetime.now().year
    topic_focus = custom_topic if custom_topic else topic

    existing_titles_text = build_existing_titles_note(existing_titles, avoid_similar, language)
    research_note = build_research_note(custom_topic, topic, language)
    seo_section, has_evidence = build_seo_section(seo_data, language)
    evidence_policy = build_evidence_policy(has_evidence, language)
    category_desc_text = build_category_brief(category_desc, language)
    internal_links_text, allowed_link_urls = build_internal_links_note(internal_links_context, language)

    if custom_prompt:
        prompt = apply_custom_prompt(custom_prompt, {
            'topic': topic_focus,
            'existing_titles': existing_titles_text,
            'research_note': research_note,
            'seo_section': seo_section,
            'category_desc_text': category_desc_text,
            'internal_links_text': internal_links_text,
            'target_site': target_site,
            'target_audience': target_audience,
            'current_year': str(current_year),
        })
    else:
        prompt = ARTICLE_PROMPT_TEMPLATES[_lang(language, 'en', 'id')].format(
            target_site=target_site,
            topic_focus=topic_focus,
            existing_titles_text=existing_titles_text,
            research_note=research_note,
            seo_section=seo_section,
            category_desc_text=category_desc_text,
            internal_links_text=internal_links_text,
            target_audience=target_audience,
            context=build_topic_context(topic, category_desc, seo_data),
            current_year=current_year,
        )

    prompt = prompt + "\n\n" + OUTPUT_CONTRACT_TEMPLATE.format(evidence_policy=evidence_policy)
    if quality_feedback:
        prompt += build_quality_correction(quality_feedback)
    return prompt, evidence_policy, allowed_link_urls


# ---------------------------------------------------------------------------
# Featured image prompts, tried in order until one returns an image.
# ---------------------------------------------------------------------------

IMAGE_PROMPT_TEMPLATES = (
    (
        "safe-editorial",
        """Create a professional editorial illustration for a blog featured image.
Article theme: "{safe_title}"
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
        """Create a high-quality 16:9 featured image for an article about {topic}.
Include a descriptive, click-worthy typographic hook of 3 to 6 words in the center (e.g. "Essential Tips for {topic}").
Do NOT write the full lengthy title, but make sure the text clearly describes the content.
Use abstract modern symbols and a soft geometric background.
Modern clean vector or soft 3D illustration, professional blog thumbnail."""
    ),
    (
        "minimal-abstract",
        """Create a clean abstract 16:9 blog cover image for {topic}.
Include a bold, catchy 3-to-6 word phrase in aesthetic typography that summarizes the topic.
Use simple shapes and digital icons on a bright professional background."""
    ),
)


def build_image_prompts(topic, title, custom_prompt=None, target_site="website"):
    """(attempt name, prompt) pairs: the site's custom prompt first, then fallbacks."""
    prompts = []
    if custom_prompt:
        prompts.append((
            "custom",
            custom_prompt
            .replace('{topic}', topic)
            .replace('{title}', title)
            .replace('{site_name}', target_site)
            .replace('{target_site}', target_site)
        ))
    safe_title = " ".join((title or topic or "education article").split()[:12])
    for name, template in IMAGE_PROMPT_TEMPLATES:
        prompts.append((name, template.format(topic=topic, safe_title=safe_title)))
    return prompts
