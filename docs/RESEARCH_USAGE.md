# Cara Bot Menggunakan Hasil Riset

## 📊 Overview

Riset dijalankan per kategori website. Hasilnya (keyword, pertanyaan, long-tail,
kompetitor, data Search Console, dan saran topik) disimpan di tabel `research_data`
dan dipakai untuk membuat judul AI, artikel auto-post, dan artikel dari Antrean.

Riset bisa berjalan dengan dua cara:

| | Riset manual | Riset terjadwal |
|---|---|---|
| Pemicu | Tombol di halaman Riset (`POST /manual-research`) | Dispatcher, sekali sehari |
| Waktu | Kapan saja | 00:00–00:59 zona waktu website (tiap website pada menitnya sendiri) |
| Kategori | Satu kategori, atau semua kategori terpilih | Hanya kategori yang riset terakhirnya belum ada atau > 30 hari (atau topiknya hampir habis) |
| Syarat | Kredit cukup | Website aktif, auto-post aktif, ada kategori terpilih |
| Biaya | 1 kredit per kategori unik | Gratis |

Riset terjadwal memperbarui kategori sebulan sekali (30 hari), beberapa hari sebelum
datanya kedaluwarsa (35 hari), sehingga auto-post tidak diam-diam kehilangan risetnya.
Kategori yang topik artikelnya tinggal kurang dari 2 diperbarui lebih awal (paling
cepat 7 hari setelah riset terakhir).

## 🔄 Alur Riset

```
POST /manual-research  ─┐
dispatcher (00:00)     ─┴→ lock per website (research_lock:{site_id})
                            ↓
                   queue RQ "research" (service research-worker)
                            ↓
              deep_research_job, untuk setiap kategori:
                - Google Trends (related queries) + SEOResearch
                  (autocomplete, pertanyaan, kompetitor, YouTube, sosial, berita)
                - query Search Console yang relevan dengan kategori
                - skor kualitas + confidence (high / medium / low)
                - saran topik dari Trends, pertanyaan, long-tail, autocomplete
                ↓
              simpan ke research_data
```

- Hanya satu riset per website pada satu waktu, selama job-nya masih antre atau
  berjalan. Permintaan riset manual kedua dijawab `409` dengan `job_id` riset yang
  sedang berjalan (atau "Riset sedang dimulai, coba lagi sebentar." jika job baru
  sedang dimasukkan ke antrean), tanpa memotong kredit.
- Jika tidak ada research worker yang aktif, riset manual ditolak dengan `503`
  "Layanan riset sedang tidak aktif. Hubungi admin." tanpa memotong kredit. Job
  yang tetap antre lebih dari 6 jam dibatalkan dan kreditnya dikembalikan.
- Riset terjadwal tidak mengirim Telegram saat berhasil; jika semua kategori gagal,
  notifikasi dikirim paling banyak sekali sehari.
- Queue `research` terpisah dari queue `default`, jadi riset yang lama tidak pernah
  menunda posting artikel.
- Kategori dengan bukti tidak cukup (confidence `insufficient`) tidak disimpan dan
  kreditnya dikembalikan.
- Riset yang buktinya cukup tetapi tidak menemukan topik artikel tetap disimpan;
  hasil job dan notifikasi Telegram menyebutkan kategori tanpa topik.

## 💳 Kredit Riset Manual

- 1 kredit per kategori unik. Nama kategori dibandingkan tanpa spasi di tepi dan
  tanpa membedakan huruf besar/kecil, jadi "Tips" dan "tips " dihitung satu.
- Kredit untuk kategori yang gagal, tidak sempat diriset (batas waktu), atau sudah
  tidak dipilih dikembalikan otomatis.
- Jika worker mati mendadak, dispatcher mengembalikan kredit kategori yang belum
  diriset (tepat satu kali) berdasarkan catatan `research_charge:{job_id}`.

## 📡 Memantau Progres

`GET /api/job-status/<job_id>` mengembalikan `progress` (0–100) dan `message`
sungguhan, misalnya `Meriset kategori 'Keuangan' (2/5)...`. Setelah selesai,
`result` berisi:

```json
{
  "successful_categories": 2,
  "failed_categories": 1,
  "refunded_credits": 1,
  "skipped": false,
  "reason": null,
  "categories_without_topics": []
}
```

`GET /api/research/active?site_id=<id>` mengembalikan `job_id` riset yang sedang
antre/berjalan untuk website itu (atau `null`), sehingga halaman Riset bisa
melanjutkan pemantauan setelah dimuat ulang.

## 📦 Cara Data Riset Dipakai

Riset dipakai hanya jika **segar** (maksimal 35 hari, `database.is_research_fresh`)
dan confidence-nya `high`, `medium`, atau `low`. Aturan ini sama untuk semua jalur:

1. **Generate judul AI** (`POST /api/generate-titles/<kategori>`): keyword,
   pertanyaan, content gap, dan query Search Console yang relevan dengan kategori.
   Halaman Riset menampilkan `eligible_for_titles` dan `title_block_reason`
   ("Belum ada riset", "Bukti riset belum cukup", "Data riset sudah lebih dari 7
   hari") dengan aturan yang sama.
2. **Auto-post per kategori**: mengambil satu topik riset yang belum dipakai.
   Topik baru benar-benar terpakai saat artikelnya terbit. Jika artikel gagal
   karena kontennya (ditolak quality gate atau ditolak model AI), topik dianggap
   terpakai; kegagalan lain (WordPress, jaringan, timeout) mengembalikan topik,
   paling banyak 2 kali. Riset tanpa topik dilewati tanpa ditandai terpakai.
3. **Item Antrean**: judul item diriset sebagai topik dan diletakkan di depan,
   dengan riset kategori sebagai latar belakang.

Search Console bersifat site-wide, jadi hanya query yang relevan dengan kategori
atau topik artikel yang dipakai: harus ada kata khas yang sama (≥4 huruf, bukan
kata umum seperti "tips", "cara", "online", "terbaik") atau nama kategori muncul
utuh di query.

## 🗑️ Retensi

Setiap hari dispatcher menghapus riset yang lebih tua dari 90 hari, kecuali dua
riset terakhir per website + kategori (dipakai untuk perbandingan di halaman
Riset).

## 📊 Monitoring

Cek data riset:
```sql
SELECT category, researched_at, confidence_level, quality_score, used,
       json_array_length(suggested_topics) AS topik
FROM research_data
ORDER BY created_at DESC
LIMIT 20;
```

Cek worker dan log:
```bash
docker compose logs research-worker --tail=100
docker compose logs scheduler --tail=100 | grep -i research
```

---

**Last Updated**: 2026-10-14
