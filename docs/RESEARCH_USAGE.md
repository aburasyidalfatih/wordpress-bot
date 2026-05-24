# Cara Bot Menggunakan Hasil Riset

## 📊 Overview

Bot melakukan riset SEO otomatis setiap hari jam 00:00 untuk semua kategori, lalu menggunakan data riset tersebut saat generate artikel.

## 🔄 Alur Penggunaan Riset

### 1. Auto Research (Daily 00:00)
```
Cron Job → auto_research_job()
  ↓
Untuk setiap kategori:
  - Riset Google Trends
  - Riset Keywords (Google Suggest)
  - Riset Questions (People Also Ask)
  - Riset Long-tail Keywords
  ↓
Simpan ke database (research_data table)
```

### 2. Generate Article (Setiap Posting)
```
generate_and_post()
  ↓
Cek: use_research_topics = True?
  ↓
Ambil data riset terbaru untuk kategori
  ↓
Kirim ke Gemini AI:
  - Custom topic (dari trending)
  - Keywords (untuk SEO)
  - Questions (untuk struktur artikel)
  - Long-tail keywords (untuk konten)
  ↓
Generate artikel SEO-optimized
```

## 📦 Data Riset yang Digunakan

### 1. **Trending Topics**
- Topik yang sedang trending di Google
- Digunakan sebagai **custom topic** untuk artikel
- Bot pilih 1 topik yang belum digunakan

### 2. **Keywords**
- Keyword utama dari Google Suggest
- Digunakan untuk **SEO optimization**
- Contoh: "manajemen sdm", "manajemen sdm adalah"

### 3. **Questions**
- Pertanyaan dari "People Also Ask"
- Digunakan untuk **struktur artikel** (H2/H3)
- Contoh: "Apa itu Manajemen SDM?"

### 4. **Long-tail Keywords**
- Keyword panjang dan spesifik
- Digunakan untuk **konten detail**
- Contoh: "strategi manajemen sdm dalam menghadapi era vuca"

## 💡 Contoh Penggunaan

### Kategori: Manajemen SDM

**Data Riset:**
```json
{
  "keywords": [
    "manajemen sdm",
    "manajemen sdm adalah",
    "manajemen sdm kerja apa"
  ],
  "questions": [
    "Apa itu Manajemen SDM?",
    "Bagaimana cara Manajemen SDM?",
    "Apa manfaat Manajemen SDM?"
  ],
  "long_tail": [
    "strategi manajemen sdm dalam menghadapi era vuca",
    "strategi manajemen sdm"
  ]
}
```

**Artikel yang Dihasilkan:**
- **Judul**: Menggunakan keyword utama + long-tail
- **H2/H3**: Menggunakan questions
- **Konten**: Menjawab questions + menggunakan long-tail keywords
- **Meta**: Focus keyword dari riset

## 🎯 Keuntungan

✅ **SEO-Optimized**: Artikel menggunakan keyword yang dicari orang
✅ **Trending**: Topik sesuai dengan yang sedang trending
✅ **Relevant**: Menjawab pertanyaan yang sering ditanyakan
✅ **Automatic**: Riset dan penggunaan otomatis tanpa manual

## 📅 Schedule

- **Riset**: Setiap hari jam **00:00 WIB**
- **Posting**: Jam **0, 6, 12, 18** (menggunakan riset terbaru)

## 🔧 Konfigurasi

Di dashboard Settings:
- ✅ **Auto Research**: Enabled
- ✅ **Use Research Topics**: Enabled

## 📊 Monitoring

Cek data riset:
```sql
SELECT category, created_at, used 
FROM research_data 
ORDER BY created_at DESC;
```

Cek artikel yang menggunakan riset:
```bash
tail -f bot.log | grep "Using research topic"
tail -f bot.log | grep "Using SEO data"
```

## 🎓 Best Practice

1. **Riset berjalan otomatis** - tidak perlu manual
2. **Data selalu fresh** - update setiap hari
3. **Topik tidak duplikat** - bot track topik yang sudah digunakan
4. **SEO-friendly** - semua artikel optimized untuk search engine

---

**Last Updated**: 2026-03-07
**Status**: ✅ Active & Working
