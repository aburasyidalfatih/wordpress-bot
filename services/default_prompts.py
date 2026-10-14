"""Default article prompts: the single source for the generator and the prompt UI.

They use the same placeholders as a site's custom article prompt (see
services.article_prompts.CUSTOM_PROMPT_PLACEHOLDERS), so the text shown as the
default in the UI is exactly what runs when a site has no custom prompt, and it
keeps working when a user saves it as their custom prompt.

Written to Google's people-first guidance: structure follows search intent
instead of a fixed skeleton, no word-count targets, facts traceable to the
research data, sources linked from the publisher-checked list, no fake
freshness, and FAQs only when there are genuinely distinct questions.
"""

# Marker the prompt optimizer (routes/prompts.py) uses to keep the output format
# section out of the AI rewrite. Each default must contain its language's marker.
FORMAT_MARKER_ID = "FORMAT OUTPUT (Gunakan XML-Tags berikut):"
FORMAT_MARKER_EN = "OUTPUT FORMAT (use these XML tags):"

DEFAULT_ARTICLE_PROMPT_ID = """Tulis artikel untuk website {target_site} tentang: {topic}
{existing_titles}{research_note}{seo_section}{category_desc_text}{internal_links_text}
TARGET PEMBACA: {target_audience}
TAHUN SEKARANG: {current_year}. Sebut tahun hanya bila isinya memang bergantung pada waktu (aturan, tarif, jadwal, data terbaru). Jangan menambahkan tahun ke judul atau heading hanya agar terlihat baru.

TUJUAN
Tulis untuk manusia, bukan untuk mesin pencari. Jawab kebutuhan pembaca secara lengkap dan akurat, dan beri nilai yang tidak didapat dari sekadar merangkum hasil pencarian: penjelasan yang jernih, pertimbangan, langkah, atau perbandingan yang benar-benar membantu.

STRUKTUR MENGIKUTI INTENT PENCARIAN (tentukan dulu apa yang dicari pembaca; tidak ada kerangka baku)
- Cara/panduan: langkah bernomor berurutan, prasyarat, dan kesalahan yang perlu dihindari.
- Perbandingan/memilih: <table> HTML dengan kriteria yang jelas, lalu saran untuk tiap situasi.
- Penjelasan/konsep: definisi singkat, cara kerja, contoh, dan batasannya.
- Daftar/ide: butir yang berdiri sendiri, masing-masing dengan detail atau alasan konkret.
Heading H2/H3 harus menggambarkan isi bagiannya secara spesifik, bukan label generik ("Pendahuluan", "Studi Kasus", "Kesimpulan"). Kotak ringkasan, studi kasus, atau penutup panjang hanya dipakai bila memang membantu topik ini.

PANJANG: secukupnya untuk menjawab tuntas. Tidak ada target jumlah kata; jangan menambah paragraf pengisi atau pengulangan.

PEMBUKA: jawab inti pertanyaan pembaca dalam dua-tiga kalimat pertama, lalu lanjutkan ke detailnya. Buka setiap artikel dengan cara yang berbeda; jangan memakai hook template seperti "Bayangkan dua keluarga..." atau "Pernahkah Anda...".

AKURASI DAN SUMBER
- Angka, aturan, tarif, tanggal, dan hasil riset hanya boleh diambil dari data riset di atas. Saat memakai informasi dari daftar SUMBER YANG BOLEH DIKUTIP, tautkan sumbernya di kalimat itu dengan <a href="URL">nama sumber</a>, memakai URL persis dari daftar. Jangan menautkan URL lain.
- Jangan mengarang statistik, nama orang atau lembaga, kutipan, testimoni, atau studi kasus. Contoh ilustrasi boleh, asalkan jelas ditandai sebagai contoh hipotetis.
- Bila sebuah fakta tidak bisa dipastikan, tulis secara umum dan sarankan pembaca memeriksa sumber resmi.
- Topik keuangan, kesehatan, hukum, atau keselamatan: sajikan sebagai informasi umum, jelaskan risikonya, dan sarankan berkonsultasi dengan profesional bila keputusannya berdampak besar.

GAYA
- Bahasa Indonesia yang jelas dan alami; sapa pembaca dengan "Anda". Paragraf pendek, kalimat langsung.
- Keyword utama muncul secara alami di judul dan paragraf pembuka; pakai istilah terkait secara wajar, tanpa menumpuk keyword. Cetak tebal hanya bila benar-benar membantu.
- Link internal hanya bila relevan dengan kalimatnya, sesuai instruksi di atas.
- Tanpa emoji, placeholder ([INFOGRAFIS: ...]), ASCII art, atau label seperti "H2:". Jangan mengulang judul di dalam konten.
- <FAQS> diisi hanya bila ada pertanyaan nyata yang berbeda dan belum dijawab di isi artikel; jika tidak ada, biarkan kosong.

FORMAT OUTPUT (Gunakan XML-Tags berikut):
<TITLE>Judul akurat dan spesifik, maksimal 60 karakter. Tanpa clickbait ("Rahasia", "Ultimate", "Terlengkap", "Wajib Tahu") dan tanpa tahun kecuali isinya memang khusus tahun itu.</TITLE>
<META_DESCRIPTION>140-155 karakter, merangkum isi artikel ini dengan akurat dan memuat keyword utama secara wajar.</META_DESCRIPTION>
<FOCUS_KEYWORD>keyword utama, 2-4 kata</FOCUS_KEYWORD>
<EXCERPT>Satu-dua kalimat spesifik tentang isi artikel ini.</EXCERPT>
<KEY_TAKEAWAYS>
- Tiga poin spesifik yang benar-benar dibahas di artikel ini
</KEY_TAKEAWAYS>
<CONTENT>Artikel HTML lengkap (p, h2, h3, ul, ol, table, a, strong, em, blockquote). Mulai langsung dengan paragraf pembuka.</CONTENT>
<FAQS>
Q: Pertanyaan?
A: Jawaban langsung.
</FAQS>"""

DEFAULT_ARTICLE_PROMPT_EN = """Write an article for the website {target_site} about: {topic}
{existing_titles}{research_note}{seo_section}{category_desc_text}{internal_links_text}
TARGET AUDIENCE: {target_audience}
CURRENT YEAR: {current_year}. Mention a year only when the content genuinely depends on it (rules, rates, deadlines, recent data). Never add a year to the title or headings just to look fresh.

GOAL
Write for people, not for search engines. Answer the reader's need completely and accurately, and add value they would not get from a summary of the search results: clear explanation, trade-offs, steps or comparisons that actually help.

STRUCTURE FOLLOWS SEARCH INTENT (decide what the reader is looking for first; there is no fixed outline)
- How-to: ordered, numbered steps, prerequisites, and mistakes to avoid.
- Comparison/choosing: an HTML <table> with clear criteria, then advice for each situation.
- Explainer: a short definition, how it works, examples, and limitations.
- List/ideas: self-contained items, each with concrete detail or reasoning.
H2/H3 headings must describe their section specifically, not generic labels ("Introduction", "Case Study", "Conclusion"). Use summary boxes, case studies or long wrap-ups only when they genuinely help this topic.

LENGTH: as long as needed to answer fully. There is no word-count target; never add filler or repetition.

OPENING: answer the reader's core question within the first two or three sentences, then move into the detail. Open each article differently; no template hooks such as "Imagine two families..." or "Have you ever...".

ACCURACY AND SOURCES
- Take figures, rules, rates, dates and research findings only from the research data above. When you use information from the SOURCES YOU MAY CITE list, link the source in that sentence with <a href="URL">source name</a>, copying the URL exactly from the list. Do not link any other URL.
- Never invent statistics, names of people or organisations, quotes, testimonials or case studies. Illustrative examples are fine if clearly labelled as hypothetical.
- If a fact cannot be confirmed, write in general terms and suggest checking the official source.
- Finance, health, legal or safety topics: present general information, explain the risks, and suggest consulting a qualified professional when the decision has real consequences.

STYLE
- Clear, natural English; address the reader as "you". Short paragraphs, direct sentences.
- Use the focus keyword naturally in the title and the opening paragraph; use related terms naturally, never keyword-stuff. Bold only where it genuinely helps.
- Internal links only where relevant to the sentence, as instructed above.
- No emoji, placeholders ([INFOGRAPHIC: ...]), ASCII art, or labels such as "H2:". Do not repeat the title in the content.
- Fill <FAQS> only with real, distinct questions the body has not already answered; otherwise leave it empty.

OUTPUT FORMAT (use these XML tags):
<TITLE>Accurate, specific title, at most 60 characters. No clickbait ("Ultimate", "Secret", "Everything You Need to Know") and no year unless the content is specific to that year.</TITLE>
<META_DESCRIPTION>140-155 characters accurately summarising this article, including the focus keyword naturally.</META_DESCRIPTION>
<FOCUS_KEYWORD>focus keyword, 2-4 words</FOCUS_KEYWORD>
<EXCERPT>One or two specific sentences about what this article covers.</EXCERPT>
<KEY_TAKEAWAYS>
- Three specific points this article actually covers
</KEY_TAKEAWAYS>
<CONTENT>Full HTML article (p, h2, h3, ul, ol, table, a, strong, em, blockquote). Start directly with the opening paragraph.</CONTENT>
<FAQS>
Q: Question?
A: Direct answer.
</FAQS>"""

DEFAULT_ARTICLE_PROMPTS = {
    'id': DEFAULT_ARTICLE_PROMPT_ID,
    'en': DEFAULT_ARTICLE_PROMPT_EN,
}


def default_article_prompt(language='id'):
    """English for 'en' sites, Indonesian for everything else (as elsewhere)."""
    return DEFAULT_ARTICLE_PROMPTS['en' if language == 'en' else 'id']
