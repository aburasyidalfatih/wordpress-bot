# 🤖 Cara Bot Menggunakan Hasil Riset untuk Generate Artikel

## 📊 Workflow Teknis

### 1. Riset Harian (00:00 WIB)
```python
def auto_research_job():
    for category in config['selected_categories']:
        # Get trending data
        trending_data = trending.get_trending_topics(category_name)
        suggestions = trending.suggest_article_topics(category_name, count=10)
        
        # Save to database
        db.save_research_data(
            category_name,
            trending_data['trending_now'],
            trending_data['related_rising'],
            trending_data['related_top'],
            suggestions  # 5-10 topik per kategori
        )
```

**Hasil**: 50 topik tersimpan dengan status `used = FALSE`

---

### 2. Generate & Post Artikel

```python
def generate_and_post():
    # A. Pilih kategori (rotasi otomatis)
    category = config['selected_categories'][0]
    
    # B. Ambil topik dari riset (jika diaktifkan)
    custom_topic = None
    if config.get('use_research_topics'):
        custom_topic = db.get_unused_research_topic(category['name'])
        # Contoh: "Implementasi AI dalam pembelajaran"
    
    # C. Generate artikel dengan Gemini AI
    article = generator.generate_article(
        category['name'],           # "Digitalisasi Pendidikan"
        existing_titles,            # Hindari duplikasi
        custom_topic               # Topik dari riset
    )
    
    # D. Generate featured image
    image_data = generator.generate_image(
        category['name'],
        article['title'],
        article['content']
    )
    
    # E. Publish ke WordPress
    success = publisher.create_post(
        article['title'],
        article['content'],
        category['id'],
        featured_image_id
    )
    
    # F. Mark topik as used (otomatis di database)
```

---

### 3. Prompt Engineering

Ketika `custom_topic` tersedia, prompt ke Gemini AI menjadi:

```
Buatkan artikel blog SEO-optimized untuk kelasmaster.id tentang:
Implementasi AI dalam pembelajaran

🔥 TRENDING TOPIC: Implementasi AI dalam pembelajaran
Fokuskan artikel pada topik trending ini dalam konteks Digitalisasi Pendidikan.

TARGET AUDIENCE: Kepala sekolah, founder yayasan, pengelola lembaga pendidikan
RELATED KEYWORDS: transformasi digital sekolah, teknologi pendidikan, AI pembelajaran

STRUKTUR ARTIKEL (2000-2500 KATA):
1. HOOK PEMBUKA (100 kata)
   - Statistik menarik tentang AI di pendidikan
   - Problem statement yang relatable
   
2. CONTEXT (200 kata)
   - Situasi pendidikan Indonesia saat ini
   - Mengapa AI penting untuk sekolah
   
3. KONTEN UTAMA (1500-1700 kata)
   - Konsep Dasar AI dalam Pembelajaran
   - Implementasi Step-by-Step
   - Studi Kasus Sekolah Indonesia
   - Tips & Best Practices
   
4. KESIMPULAN (150 kata)
   - Key takeaways
   - Action steps
   
5. FAQ (150 kata)
   - 3-5 pertanyaan umum
```

---

## 🎯 Keunggulan Menggunakan Riset

### ✅ Relevansi Tinggi
- Topik berdasarkan data trending, bukan asumsi
- Sesuai dengan yang dicari audience
- Meningkatkan kemungkinan traffic tinggi

### ✅ SEO Boost
- Artikel tentang topik trending = search volume tinggi
- Google prioritaskan konten fresh & relevan
- Potensi ranking lebih cepat di SERP

### ✅ Engagement Lebih Baik
- Topik yang sedang hot = lebih banyak dibaca
- Rising topics = potensi viral
- Audience lebih engaged karena topik relevan

### ✅ Efisiensi
- Tidak perlu brainstorming manual
- Topik sudah ter-validasi oleh data
- Hemat waktu riset konten

---

## 📝 Contoh Output Artikel

### Input:
```
Topik: "Implementasi AI dalam pembelajaran"
Kategori: "Digitalisasi Pendidikan"
```

### Output:
```
JUDUL:
"Implementasi AI dalam Pembelajaran: Panduan Lengkap untuk 
Sekolah Indonesia di Era Digital 2026"

META DESCRIPTION:
"Panduan praktis implementasi AI dalam pembelajaran untuk sekolah 
Indonesia. Lengkap dengan studi kasus, tools, dan strategi efektif."

KONTEN (2000-2500 kata):

[HOOK]
Tahukah Anda bahwa 78% sekolah di Indonesia masih menggunakan 
metode pembelajaran konvensional? Padahal, teknologi AI telah 
terbukti meningkatkan engagement siswa hingga 45%...

[CONTEXT]
Di era digital 2026, transformasi pendidikan bukan lagi pilihan, 
melainkan kebutuhan. Artificial Intelligence (AI) menawarkan 
solusi untuk personalisasi pembelajaran...

[KONSEP DASAR]
AI dalam pembelajaran adalah penggunaan teknologi kecerdasan 
buatan untuk:
1. Personalisasi materi belajar
2. Analisis performa siswa
3. Automasi tugas administratif
...

[IMPLEMENTASI STEP-BY-STEP]
Langkah 1: Assessment Kebutuhan Sekolah
- Identifikasi pain points
- Survey guru dan siswa
- Budget planning

Langkah 2: Pilih Platform AI yang Tepat
- Google Classroom + AI extensions
- Khan Academy
- Duolingo for Schools
...

[STUDI KASUS]
SMA Negeri 5 Jakarta berhasil implementasi AI:
- Before: Nilai rata-rata 75
- After: Nilai rata-rata 85 (+13%)
- Engagement siswa naik 40%
- Waktu guru untuk admin turun 60%
...

[TIPS & BEST PRACTICES]
DO's:
✅ Mulai dari pilot project kecil
✅ Training guru secara berkala
✅ Monitor progress dengan KPI

DON'Ts:
❌ Implementasi sekaligus tanpa persiapan
❌ Abaikan feedback guru dan siswa
...

[KESIMPULAN]
Key Takeaways:
1. AI bukan pengganti guru, tapi tools untuk enhance
2. Implementasi bertahap lebih efektif
3. Training adalah kunci sukses

Next Steps:
→ Download checklist implementasi AI
→ Konsultasi dengan tim kelasmaster.id
...

[FAQ]
Q: Berapa budget minimal untuk implementasi AI?
A: Mulai dari 5 juta/bulan untuk sekolah kecil...

Q: Apakah guru perlu skill programming?
A: Tidak. Platform modern user-friendly...
```

---

## 🔄 Siklus Berkelanjutan

```
Day 1:
00:00 → Riset 50 topik baru
06:00 → Post "Implementasi AI dalam pembelajaran"
12:00 → Post "Platform LMS terbaik untuk sekolah"
18:00 → Post "Digitalisasi administrasi sekolah"

Day 2:
00:00 → Riset 50 topik baru (refresh)
06:00 → Post "E-learning untuk pendidikan Indonesia"
12:00 → Post "Teknologi pendidikan terkini"
18:00 → Post "Digital marketing untuk sekolah"
...

Topik tidak akan repeat karena auto-marked as used
```

---

## ⚙️ Cara Mengaktifkan

### 1. Buka Settings
```
http://localhost:5000/settings
```

### 2. Aktifkan Fitur
- ☑️ **Enable Daily Auto Research** - Riset otomatis jam 00:00
- ☑️ **Use Research Topics for Articles** - Gunakan topik riset

### 3. Save Settings

### 4. Bot Akan Otomatis:
- ✅ Riset trending topics setiap hari
- ✅ Gunakan topik riset saat generate artikel
- ✅ Mark topik as used setelah dipakai
- ✅ Fallback ke generate normal jika topik habis

---

## 💡 Tips & Best Practices

### Monitoring
- Cek halaman `/research` untuk lihat topik tersedia
- Monitor log untuk lihat topik yang digunakan
- Track engagement artikel dari topik riset vs normal

### Optimization
- Jika topik habis sebelum riset berikutnya, bot akan generate normal
- Research bisa di-trigger manual kapan saja via dashboard
- Adjust interval posting sesuai jumlah topik tersedia

### Quality Control
- Review artikel yang di-generate dari topik riset
- Bandingkan engagement dengan artikel normal
- Adjust fallback topics jika perlu

---

## 📊 Database Schema

```sql
-- Tabel research_data
CREATE TABLE research_data (
    id INTEGER PRIMARY KEY,
    category VARCHAR(200),
    trending_topics JSON,      -- Topik trending umum
    rising_topics JSON,        -- Topik yang sedang naik
    top_topics JSON,           -- Topik paling populer
    suggested_topics JSON,     -- 5-10 saran artikel
    used BOOLEAN DEFAULT 0,    -- Status penggunaan
    created_at DATETIME
);

-- Query untuk ambil topik
SELECT * FROM research_data 
WHERE category = 'Digitalisasi Pendidikan' 
  AND used = FALSE 
ORDER BY created_at DESC 
LIMIT 1;

-- Auto-mark as used setelah dipakai
UPDATE research_data 
SET used = TRUE 
WHERE id = ?;
```

---

## 🚀 Kesimpulan

Bot menggunakan hasil riset untuk:
1. **Identifikasi topik trending** yang relevan dengan kategori
2. **Generate artikel berkualitas** dengan Gemini AI
3. **Optimasi SEO** dengan topik yang sedang dicari
4. **Meningkatkan engagement** dengan konten yang relevan
5. **Automasi penuh** dari riset hingga publish

Hasilnya: **Artikel berkualitas tinggi yang data-driven dan SEO-optimized!**
