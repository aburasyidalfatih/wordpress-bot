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
    def generate_article(self, topic, existing_titles=None, custom_topic=None, seo_data=None, avoid_similar=False, custom_prompt=None):
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
        
        context = context_map.get(topic, topic)
        
        # Add existing titles to prompt to avoid duplicates
        existing_titles_text = ""
        if existing_titles:
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
        research_note = f"\n\n🔥 TRENDING TOPIC: {custom_topic}\nFokuskan artikel pada topik trending ini dalam konteks {topic}.\n" if custom_topic else ""
        
        # Add SEO data if available
        seo_section = ""
        if seo_data:
            keywords = seo_data.get('keywords', [])
            questions = seo_data.get('questions', [])
            
            if keywords:
                seo_section += f"\n\n🔑 RELATED KEYWORDS (gunakan natural di artikel):\n"
                for kw in keywords[:10]:
                    seo_section += f"- {kw}\n"
            
            if questions:
                seo_section += f"\n\n❓ PERTANYAAN YANG SERING DICARI (jawab di artikel):\n"
                for q in questions[:5]:
                    seo_section += f"- {q}\n"
                seo_section += "\n💡 Pastikan artikel menjawab pertanyaan-pertanyaan ini secara lengkap!\n"
        
        prompt = f"""Buatkan artikel blog SEO-optimized berkualitas tinggi untuk website kelasmaster.id tentang: {topic_focus}
{existing_titles_text}{research_note}{seo_section}
TARGET AUDIENCE: Kepala sekolah, founder yayasan, pengelola lembaga pendidikan di Indonesia
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

2. CONTEXT (200 kata):
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
✓ Kalimat: VARIASIKAN panjang untuk rhythm natural
  - Kalimat pendek (5-10 kata): Untuk emphasis dan impact
  - Kalimat sedang (15-20 kata): Untuk penjelasan standar
  - Kalimat panjang (25-35 kata): Untuk detail dan konteks
  - Contoh: "Masalahnya jelas. Sekolah butuh dana lebih. Tapi menaikkan SPP bukan solusi jangka panjang karena akan menurunkan daya saing dan membuat orang tua mencari alternatif lain."
✓ Paragraf: 3-4 kalimat maksimal, variasikan panjangnya
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
    ✓ Bikin penasaran (curiosity gap)
    
    CONTOH BAGUS:
    ✓ '7 Sekolah Jakarta Tingkatkan Nilai 40% dengan AI - Rahasianya?'
    ✓ 'Biaya Sekolah Mahal? Cara Dapat 300+ Siswa Tanpa Turunkan Harga'
    ✓ '5 Kesalahan Fatal Kepala Sekolah yang Bikin Guru Resign'
    ✓ 'Asrama Penuh 95%: Strategi dari 10 Boarding School Terbaik'
    
    CONTOH BURUK:
    ✗ 'Panduan Lengkap Digitalisasi Pendidikan' (terlalu generic)
    ✗ 'Strategi Pemasaran Sekolah 2026' (tidak ada hook)
    ✗ 'Manajemen Keuangan untuk Lembaga Pendidikan' (boring)",
    
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
- JUDUL: Fokus pada benefit/solusi, BUKAN nama kategori (contoh: "7 Strategi Meningkatkan Pendaftaran Siswa Baru" bukan "Strategi Pemasaran untuk Sekolah")

CRITICAL:
- Konten HARUS original, mendalam, dan actionable
- WAJIB ada contoh praktis dari sekolah Indonesia
- WAJIB ada angka/data untuk credibility
- WAJIB ada step-by-step guide yang bisa langsung diterapkan
- Hindari konten generic, buat spesifik untuk konteks Indonesia
- Panjang MINIMAL 2000 kata, OPTIMAL 2000-2500 kata"""

        # Use custom prompt if provided, injecting dynamic variables
        if custom_prompt:
            prompt = custom_prompt.replace('{topic}', topic_focus).replace('{category}', topic).replace('{existing_titles}', existing_titles_text).replace('{seo_section}', seo_section).replace('{research_note}', research_note)

        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt
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
            if result.get('content'):
                content = result['content']
                
                # Remove placeholder patterns
                import re
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
                
                # Remove ASCII art tables (Unicode box drawing characters)
                content = re.sub(r'<pre[^>]*>.*?[─│┼├┤┬┴┌┐└┘].*?</pre>', '', content, flags=re.DOTALL)
                content = re.sub(r'[─│┼├┤┬┴┌┐└┘╔╗╚╝║═╠╣╦╩╬]', '', content)
                
                # Remove empty paragraphs
                content = re.sub(r'<p>\s*</p>', '', content)
                content = re.sub(r'<p>\s*\\n\s*</p>', '', content)
                
                # Remove multiple newlines
                content = re.sub(r'\n\n\n+', '\n\n', content)
                
                result['content'] = content.strip()
            
            # Ensure minimum quality standards
            if not result.get('reading_time'):
                word_count = len(result.get('content', '').split())
                result['reading_time'] = f"{word_count // 200} menit"
            
            if not result.get('key_takeaways'):
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
    
    def generate_image(self, topic, title, article_content=None, custom_prompt=None):
        """Generate landscape featured image for blog"""
        try:
            if article_content:
                prompt = f"""Create a professional featured image for this article about {topic}.

Article Title: {title}

Design Requirements:
- Modern, clean design in landscape orientation (16:9) - perfect for blog featured image
- Professional color scheme (blues, greens, education colors)
- Include the title text: "{title}"
- Add relevant visual elements, icons, or illustrations
- "kelasmaster.id" branding subtly placed
- High quality, eye-catching design
- Suitable as blog header/featured image

Style: Modern, professional, suitable for educational blog featured image."""
            else:
                prompt = f"""Create a professional featured image about {topic}.

Title: "{title}"

Design: Modern, landscape (16:9), professional colors, with title text and kelasmaster.id branding.
Style: Educational blog featured image."""

            # Use custom image prompt if provided
            if custom_prompt:
                prompt = custom_prompt.replace('{topic}', topic).replace('{title}', title)

            # Use configured image model for image generation
            response = self.client.models.generate_content(
                model=self.image_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_modalities=['IMAGE'],
                    image_config=types.ImageConfig(
                        aspect_ratio='16:9',  # Landscape for featured image
                        image_size='2K'
                    )
                )
            )
            
            for part in response.parts:
                if part.inline_data is not None:
                    image_bytes = part.inline_data.data
                    
                    # Convert to WebP for better compression
                    img = Image.open(BytesIO(image_bytes))
                    
                    # Convert RGBA to RGB if needed
                    if img.mode in ('RGBA', 'LA', 'P'):
                        background = Image.new('RGB', img.size, (255, 255, 255))
                        if img.mode == 'P':
                            img = img.convert('RGBA')
                        if img.mode == 'RGBA':
                            background.paste(img, mask=img.split()[-1])
                        else:
                            background.paste(img)
                        img = background
                    
                    # Save as WebP with high quality
                    output = BytesIO()
                    img.save(output, format='WEBP', quality=85, method=6)
                    output.seek(0)
                    return output
            
            return None
        except Exception as e:
            print(f"Error generating featured image: {e}")
            return None

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
                filename = f'{title[:50].replace("/", "-").replace(":", "").replace(" ", "-")}.webp'
                mime_type = 'image/webp'
            else:
                response = requests.get(image_data, timeout=30)
                if response.status_code != 200:
                    logger.error(f"Failed to download image: {response.status_code}")
                    return None
                image_bytes = response.content
                filename = f'{title[:50].replace("/", "-").replace(":", "").replace(" ", "-")}.jpg'
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
                return [{'id': cat['id'], 'name': cat['name']} for cat in categories]
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
