# 🤖 Cara Kerja Riset (Teknis)

Ringkasan untuk developer: dari mana riset dipicu, bagaimana kredit dan lock
dijaga, dan bagaimana hasilnya masuk ke judul dan artikel.

## 1. Pemicu

| Pemicu | Kode | Argumen job |
|---|---|---|
| Riset manual | `routes/research.py` → `manual_research` | `deep_research_job(user_id, True, site_id, kategori_atau_None, charged_credits=N, charge_recorded=True)` |
| Riset terjadwal | `dispatcher.py` → `_schedule_daily_research` | `deep_research_job(user_id, False, site_id, None, categories=[...])` |

Keduanya di-enqueue ke queue RQ `research` (`core_extensions.research_q`,
`dispatcher.research_q`) yang dilayani service `research-worker`
(`rq worker -u redis://redis:6379/0 research`). Queue `default` (posting artikel)
tidak pernah tertahan oleh riset.

Timeout job: `database.research_job_timeout(n)` = maks(600 detik, n × 180 detik).

### Riset terjadwal

Setiap loop dispatcher (60 detik), untuk tiap website aktif dengan `auto_post` dan
kategori terpilih:

1. Hanya pada jam 00 zona waktu website, mulai menit ke-`site_id % 50` (website
   dalam satu zona waktu tidak membebani worker bersamaan; sisa jam dipakai
   untuk mencoba ulang).
2. Key `research_sched:{site_id}:{tanggal}` membuatnya idempoten: sekali per hari.
3. Kategori dipilih jika riset usable terbarunya belum ada atau lebih tua dari
   `SCHEDULED_RESEARCH_REFRESH_DAYS` (30 hari), satu per nama ternormalisasi.
   Kategori yang topik artikelnya tinggal kurang dari `EARLY_REFRESH_MIN_TOPICS`
   (2) diperbarui lebih awal, asalkan risetnya sudah berumur minimal
   `EARLY_REFRESH_MIN_AGE_DAYS` (7 hari).
4. Jika website sedang punya riset aktif, dilewati dan dicoba lagi di loop
   berikutnya (masih dalam jam yang sama).
5. Gratis: `force=False` tidak pernah memotong maupun mengembalikan kredit.
6. Tidak mengirim Telegram saat berhasil; saat semua kategori gagal, notifikasi
   dikirim paling banyak sekali sehari per website (`research_fail_notice:*`).

## 2. Lock per Website dan Reservasi Kredit

Helper ada di `database.py` (dipakai web, job, dan dispatcher):

- `research_lock:{site_id}` = `"job_id|epoch_dibuat"`, `SET NX` dengan TTL 24 jam
  (hanya jaring pengaman). Status lock mengikuti status RQ job-nya
  (`database.research_lock_state`): sibuk selama job `queued`/`started`/
  `deferred`/`scheduled`, berapa pun lamanya antre; "sedang dimulai" selama job
  belum ada dan lock berumur < 120 detik; basi jika job selesai/gagal/dibatalkan
  atau tetap tidak ada setelah 120 detik. Diambil **sebelum** kredit dipotong;
  permintaan kedua → `409` tanpa biaya (dengan `job_id`, atau pesan "Riset sedang
  dimulai, coba lagi sebentar." tanpa `job_id`). Dilepas oleh job di `finally`
  (compare-and-delete), oleh route jika enqueue gagal, dan oleh dispatcher jika
  job-nya sudah berakhir tanpa melepasnya.
- Sebelum mengambil lock, `/manual-research` memeriksa ada worker RQ di queue
  `research` (`Worker.count`); jika tidak ada → `503` "Layanan riset sedang tidak
  aktif. Hubungi admin." tanpa memotong kredit (jika pemeriksaannya sendiri gagal,
  permintaan tetap dilanjutkan).
- `research_charge:{job_id}` = JSON `{user_id, site_id, charged, successful,
  created_at, timeout}`. Ditulis route setelah kredit dipotong, diperbarui job
  setiap kategori berhasil (`SET XX`, tidak pernah menghidupkan ulang record).
- Penyelesaian tepat satu kali: siapa pun yang berhasil `GETDEL` record itu (job
  di akhir run, atau dispatcher) yang mengembalikan kredit. Dispatcher
  (`reconcile_research_charges`) hanya bertindak jika umur record melewati timeout
  job dan status job `failed`/`stopped`/`canceled`/hilang — kasus worker dibunuh
  (SIGKILL/OOM) sebelum kode refund job sempat berjalan. Ia mengembalikan
  `charged - successful`.
- Job yang masih `queued` (tidak pernah dimulai) lebih dari 6 jam berarti tidak
  ada worker: dispatcher membatalkan job itu dulu (agar tidak bisa mulai belakangan),
  lalu mengembalikan kredit dan melepas lock. Ini juga berlaku untuk lock riset
  terjadwal. Dispatcher mencatat warning (maks. sekali per jam) jika queue
  `research` berisi job tetapi tidak ada worker.
- Jika refund gagal setelah record diambil (oleh job atau route), record
  dikembalikan dengan tanda `needs_refund` dan jumlah `owed`, sehingga dispatcher
  mencoba lagi — juga jika job-nya sudah `finished`.

## 3. `deep_research_job`

```
load_charge_record → _load_research_plan (di dalam try)
  → untuk setiap kategori (progress = round(selesai/total*100)):
        _research_category:
          trending.get_trending_topics       (Google Trends related queries)
          SEOResearch.research_category      (provider paralel)
          _score_research                    (+ Google Trends top-up, + Search Console)
          trending.build_topic_suggestions   (Trends, lalu pertanyaan, long-tail,
                                              autocomplete — hanya bukti nyata)
          db.save_research_data
finally: refund.settle()  +  lepas lock
→ notifikasi Telegram (tidak pernah menggagalkan job)
→ return {successful_categories, failed_categories, refunded_credits,
          skipped, reason, categories_without_topics}
```

- Kategori dinormalisasi dengan `database.category_key` (strip + lower), sama
  dengan route dan frontend: duplikat diriset sekali, dan kategori yang diminta
  dengan ejaan lain tetap ditemukan.
- Run manual tidak pernah meriset lebih banyak kategori dari yang dibayar; refund
  total = `charged - berhasil`, tidak pernah lebih.
- Timeout RQ (`JobTimeoutException`) menghentikan loop; kategori yang belum
  selesai dihitung gagal dan dikembalikan kreditnya.
- `job.meta['progress']` dan `job.meta['message']` dibaca oleh
  `GET /api/job-status/<job_id>`, yang juga mengembalikan `result` saat selesai.

### Search Console sebagai bukti

Query GSC dihitung sebagai bukti kategori hanya jika relevan
(`services.content_planner.text_matches_topic`): berbagi kata khas (≥4 huruf, bukan
kata umum di `GENERIC_TOPIC_WORDS`) atau nama kategori muncul utuh di query.
Kata seperti "tips", "cara", atau "online" tidak lagi memvalidasi kategori yang
tidak berhubungan.

## 4. Pemakaian Riset

Aturan kesegaran tunggal: `database.is_research_fresh(researched_at)` — maksimal
`MAX_RESEARCH_AGE_DAYS` (35) hari, dihitung dengan jam lokal naive yang sama dengan
saat `researched_at` ditulis. Confidence harus `high`/`medium`/`low`.

| Jalur | Kode |
|---|---|
| Gate judul AI | `routes/research.py` → `_title_block_reason` |
| `eligible_for_titles` / `is_stale` di halaman Riset | `routes/research.py` → `_research_entry` |
| Riset kategori untuk artikel | `tasks/article_jobs.py` → `_load_category_research` |
| Topik auto-post | `database.get_unused_research_topic` |

### Artikel (`generate_and_post`)

```
_gather_seo_data:
  - auto-post kategori: ambil topik riset (return_claim=True) → (id, teks, saran)
  - SEMUA artikel (termasuk item Antrean): riset kategori segar sebagai latar
  - ada topik (topik riset atau judul item Antrean): riset topik, digabung di depan
  - Search Console: hanya peluang yang relevan dengan kategori/topik
  - topic_is_trending=True hanya jika saran berasal dari Google Trends
```

Topik riset diambil dengan row lock (tidak dipakai dua job sekaligus) dan dianggap
terpakai saat artikel terbit. Jika artikel gagal karena kontennya (quality gate,
`ArticleQualityError`, provider menolak topik), topik dianggap terpakai karena
akan gagal lagi. Kegagalan lain (WordPress/jaringan/publish, timeout, error
provider sementara) mengembalikan topik ke depan daftar
(`db.restore_research_topic`), paling banyak 2 kali (`restore_count` di topik);
setelah itu topik dianggap terpakai. Riset tanpa topik dilewati tanpa ditandai
`used`.

Link di artikel: link yang tidak ada di daftar artikel internal dilepas
(teks anchor tetap), kecuali link ke domain website sendiri dan URL yang ditulis
di prompt artikel kustom. Perbandingan URL mengabaikan http/https, `www.`, dan
garis miring di akhir. Jika daftar artikel terbaru gagal diambil dari WordPress,
link dibiarkan apa adanya.

### Judul AI (`POST /api/generate-titles/<path:category>`)

- Konteks: keyword, pertanyaan, deskripsi kategori, content gap, dan quick win
  Search Console yang relevan dengan kategori.
- Output model diparse dengan mencari array JSON pertama (toleran terhadap code
  fence dan teks tambahan); maksimal 40 judul diproses. Jika gagal diparse →
  `502` dan kuota `ai_titles` pengguna dikembalikan.
- Dedup terhadap 300 judul antrean terbaru (kecuali `failed`) dan 300 artikel
  terbit. Respons berisi `queued` (jumlah yang benar-benar masuk antrean).

## 5. Klasifikasi Peluang Search Console

`services/search_console.build_search_opportunities`, urutan dicek:

1. `declining` — klik turun >20% dari periode sebelumnya → perbarui artikel lama.
2. `low_ctr` — posisi ≤10 dan CTR <2% → tulis ulang title & meta.
3. `quick_win` — posisi 4–20 → artikel baru/pendukung.

Hanya `quick_win` yang menjadi kandidat topik atau judul baru
(`topic_candidates_from_opportunities`).

## 6. Pemeliharaan oleh Dispatcher

Setiap 10 loop (`run_research_maintenance`):

- `reconcile_research_charges` — refund reservasi job yang mati (lihat bagian 2).
- `release_stale_research_locks` — lepas lock yang job-nya sudah berakhir, dan
  batalkan job yang antre > 6 jam.
- `warn_if_research_worker_missing` — warning per jam jika tidak ada research worker.
- `cleanup_old_research_daily` — sekali sehari, hapus riset > 90 hari kecuali dua
  riset terakhir per website + kategori.

## 7. Tabel `research_data` (kolom utama)

| Kolom | Isi |
|---|---|
| `category` | Nama kategori (ejaan pertama di website) |
| `suggested_topics` | Saran topik `{topic, type, category, is_trending}`; diambil satu per artikel |
| `keywords`, `questions`, `long_tail_keywords` | Bukti nyata (bukan fallback) |
| `competitor_outlines`, `youtube_insights`, `social_insights`, `news_insights` | Bukti pendukung |
| `source_metadata` | Status tiap provider, termasuk query Search Console yang cocok |
| `quality_score`, `confidence_level`, `is_fallback` | Hasil penilaian kualitas |
| `researched_at` | Waktu riset (jam lokal), dasar aturan kesegaran |
| `used` | `TRUE` jika semua topiknya sudah terpakai |
