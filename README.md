# AutoWP — WordPress Auto Post Bot

**Stack**: Python 3.12 + Flask (API) + React 19 (SPA) + PostgreSQL 15 + Redis/RQ
**Deployment**: Docker Compose (Dokploy + Traefik)

AutoWP adalah platform multi-tenant: user mendaftarkan beberapa website WordPress,
bot meng-generate artikel + featured image via Gemini AI, mem-publish ke WordPress,
lalu menyebarkannya ke berbagai platform sosial. Monetisasi lewat sistem kredit.

---

## Arsitektur

```
                  Traefik (SSL)
                        │
              Flask API (gunicorn, :5003)
                        │  serves frontend/dist sebagai SPA
        ┌───────────────┼───────────────┐
        │               │               │
   PostgreSQL 15     Redis/RQ      Gemini API
        │               │
        │      ┌────────┴────────┐
        │   worker           scheduler
        │  (RQ jobs)      (dispatcher.py)
        │
        └── WordPress REST API, Telegram, Facebook,
            Twitter/X, Threads, Pinterest
```

Tiga proses aplikasi berjalan dari image yang sama:

| Service | Command | Fungsi |
|---|---|---|
| `web` | `gunicorn ... app:app` | REST API + serve SPA |
| `worker` | `rq worker --with-scheduler` | Eksekusi job generate & post |
| `scheduler` | `python dispatcher.py` | Loop 60 detik, enqueue job terjadwal |

## Struktur Project

```
autowp/
├── app.py                  # Entry point Flask: blueprint, security headers, SPA serving
├── config.py               # Config + konstanta default model Gemini
├── core_extensions.py      # Singleton (db, queue, logger), decorator auth, helper sosmed
├── database.py             # Wrapper SQLAlchemy + migrasi (advisory-locked)
├── models.py               # Model SQLAlchemy
├── security.py             # Enkripsi Fernet + CSRF
├── dispatcher.py           # Scheduler auto-post + reaper item nyangkut
├── ml_optimizer.py         # Reorder kategori berdasarkan engagement
├── seo_research.py         # SEO research (DuckDuckGo, YouTube, scraping)
├── trending_research.py    # Google Trends (pytrends)
├── routes/                 # Blueprint API
│   ├── auth.py             # Google OAuth + login, JWT
│   ├── dashboard.py        # Statistik & riwayat
│   ├── sites.py            # CRUD website WordPress
│   ├── queue.py            # Antrean konten
│   ├── research.py         # Trending topics
│   ├── prompts.py          # Custom AI prompt
│   ├── settings.py         # Setting user
│   ├── monitor.py          # System health
│   ├── payments.py         # Tripay, PayPal, transfer manual
│   └── admin.py            # Panel admin
├── services/
│   ├── article_generator.py# Generate artikel & gambar via Gemini
│   └── wp_publisher.py     # Publish ke WordPress REST API
├── tasks/
│   ├── article_jobs.py     # Job RQ: generate_and_post, regenerate
│   └── research_jobs.py    # Job RQ: research
├── frontend/               # React 19 + Vite + Tailwind 4 + shadcn
│   └── src/
│       ├── pages/          # Dashboard, Sites, Queue, Research, Billing, Admin, ...
│       ├── components/     # Layout, ErrorBoundary, ui/
│       ├── contexts/       # SiteContext
│       └── lib/            # api.ts, types.ts, utils.ts
├── scripts/                # Utilitas CLI & shell operasional
├── docs/                   # Panduan setup per platform
├── Dockerfile              # Multi-stage: build frontend → runtime Python
└── docker-compose.yml      # web, worker, scheduler, postgres, redis
```

## Fitur

| Fitur | Deskripsi |
|---|---|
| Multi-site | Satu user, banyak website WordPress |
| Auto Post | Generate & publish terjadwal per site (timezone-aware) |
| Multi-platform | Telegram (chat & channel), Facebook, Twitter/X, Threads, Pinterest |
| Gemini AI | Model artikel & gambar dikonfigurasi terpisah |
| SEO | Meta description, focus keyword, excerpt per-artikel, internal linking tervalidasi, schema BlogPosting + FAQPage |
| Quality Gate | Menolak artikel terpotong, terlalu pendek, bocor template, atau mengandung kredensial karangan — sebelum publish |
| Research Intelligence | Google Trends, autocomplete, kompetitor, sosial, YouTube, berita; dilengkapi provenance, freshness, dan quality gate |
| Search Console Intelligence | OAuth read-only, query/page metrics, quick wins, low CTR, tren penurunan — dipakai sebagai sumber topik & bukti saat menulis |
| Content Planner | Aksi per peluang (artikel baru / rewrite meta / refresh konten), content gap vs kompetitor, deteksi search intent, volume dari impressions GSC |
| Category Rotation | Rotasi kategori otomatis tiap posting |
| AI Optimizer | Reorder kategori berdasarkan engagement |
| Custom Prompts | Override prompt artikel & gambar per site |
| Sistem Kredit | Top-up via Tripay / PayPal / transfer manual |
| Auth | Google OAuth + JWT (pendaftaran manual dinonaktifkan) |

## Model Gemini

Default didefinisikan **satu tempat** di `config.py`:

```python
DEFAULT_GEMINI_MODEL = 'gemini-3.5-flash'
DEFAULT_GEMINI_IMAGE_MODEL = 'gemini-3.1-flash-image'
```

Semua modul mengimpor konstanta ini — jangan menulis ulang string model secara
hardcode. Pilihan yang tersedia di UI ada di `frontend/src/pages/AdminDashboard.tsx`;
kalau menambah opsi di sana, pastikan tetap konsisten dengan konstanta di atas.

## Kebijakan Konten

Prompt artikel memuat **Evidence Policy** yang berprioritas tertinggi dan mengalahkan
instruksi lain, termasuk custom prompt per site:

- Angka dan statistik hanya boleh dipakai kalau muncul di data riset yang diberikan.
- Dilarang mengarang kutipan atau mengatribusikan pernyataan ke orang/lembaga bernama.
- Dilarang mengklaim pengalaman langsung yang tidak dimiliki penerbit.
- Studi kasus tanpa dukungan data harus jelas ditulis sebagai hipotetis.

Alasannya: mengarang kredensial dan statistik adalah E-E-A-T palsu — persis yang
disasar kebijakan spam dan helpful content Google, selain membawa risiko hukum.
Keahlian ditunjukkan lewat penalaran, struktur, dan panduan yang benar-benar bisa
dipraktikkan.

`services/quality_gate.py` menegakkan ini sebelum publish. Artikel ditolak (kredit
dikembalikan) kalau terpotong, di bawah 900 kata, kurang dari 3 heading H2, bocor
label template, atau memuat frasa kredensial karangan. Link internal yang tidak ada
di daftar yang diberikan ke model akan dilepas tag `<a>`-nya.

Prompt tidak lagi terikat ke niche tertentu — konteks artikel dibangun dari nama
kategori, deskripsi kategori, dan keyword hasil riset milik site itu sendiri.

## Riset & Perencanaan Konten

Riset berjalan dua tahap. `research_category()` mengumpulkan bukti di level kategori;
saat topik spesifik sudah dipilih, `research_topic()` meriset topik itu sendiri dan
hasilnya digabung di depan bukti kategori. Semua provider dijalankan paralel.

Data Search Console tidak lagi sekadar ditampilkan — ia masuk ke pemilihan topik dan
ke prompt artikel sebagai bukti first-party. Setiap peluang dipetakan ke aksi yang
tepat di `services/content_planner.py`:

| Peluang | Aksi | Alasan |
|---|---|---|
| `quick_win` (posisi 4–20) | Artikel baru / pendukung | Permintaan terbukti, tinggal diperkuat |
| `low_ctr` (posisi ≤10, CTR <2%) | Rewrite title & meta | Sudah ranking; artikel baru justru bersaing sendiri |
| `declining` (klik turun >20%) | Refresh artikel lama | Kontennya usang, bukan kurang konten |

Tambahan lain: impressions GSC dipakai sebagai proxy volume pencarian, content gap
dihitung dari heading kompetitor vs judul yang sudah terbit, search intent
(transactional / commercial / informational / navigational) menentukan struktur
artikel, dan Google Trends kini juga mengambil jendela 12 bulan untuk mendeteksi
pola musiman.

Judul baru di-dedup terhadap seluruh antrean dan artikel terbit di situs itu —
lintas kategori — supaya dua kategori tidak menghasilkan judul yang bersaing.

Auto-post memakai gate bukti yang **sama** dengan jalur manual: riset harus
berconfidence high/medium/low dan berumur maksimal `MAX_RESEARCH_AGE_DAYS` (7 hari).
Kalau tidak ada yang memenuhi, sistem jatuh ke rotasi kategori biasa.

## Monitoring

`dispatcher.py` menulis heartbeat ke Redis (`scheduler:heartbeat`, TTL 180 detik)
di setiap awal loop. Endpoint `/api/monitor`, `/api/health-metrics`, dan `/health`
membaca key itu untuk melaporkan status scheduler yang sebenarnya — sebelumnya
nilainya di-hardcode `True`, sehingga dispatcher yang mati tetap tampil sehat.

Status `degraded` berarti web dan database sehat tapi scheduler tidak mengirim
heartbeat. Jumlah job antrean dan ukuran database juga kini dibaca sungguhan
(`pg_database_size`), bukan nilai mati.

## Jadwal Posting

Per site, field `schedule_hours` (default `0,6,12,18` = 4x sehari) dengan timezone
per site (default `Asia/Jakarta`). Dispatcher mengecek tiap 60 detik dan
meng-enqueue job dengan jitter acak 0–50 menit agar tidak semua site posting
bersamaan.

## Database

PostgreSQL 15. Aplikasi membaca `DATABASE_URL`, atau menyusunnya dari
`POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_HOST` / `POSTGRES_PORT` /
`POSTGRES_DB`. SQLite tidak didukung.

Tabel utama:

| Tabel | Isi |
|---|---|
| `users` | Akun, role, tier, kredit |
| `wordpress_sites` | Konfigurasi per website (kredensial terenkripsi) |
| `config` | API key & model Gemini per user |
| `post_logs` | Riwayat posting + metrik engagement |
| `research_data` | Hasil research per kategori |
| `content_queue` | Antrean judul/ide konten |
| `transactions` | Riwayat top-up kredit |
| `system_settings` | Setting global + penanda versi skema |

### Migrasi

Service one-shot `migrate` menjalankan `migrate.py` sebelum web, worker, dan
scheduler dimulai. Migrasi tetap dilindungi **PostgreSQL advisory lock** serta
penanda `__schema_version__` di `system_settings`. Kalau menambah langkah migrasi
baru di `_run_migrations_locked`, naikkan `SCHEMA_VERSION` di `database.py`.

Hasil research baru menyimpan status setiap provider, URL sumber yang tersedia,
umur data, quality score, confidence level, dan penanda fallback. Kategori yang
tidak mencapai bukti minimum tidak disimpan sebagai hasil sukses dan kreditnya
dikembalikan. Data lebih dari tujuh hari tidak dipakai untuk membuat judul atau
artikel otomatis.

### Backup

```bash
docker compose exec -T postgres pg_dump -U autowp autowpdb > backup_$(date +%Y%m%d).sql
```

## Keamanan

- Semua kredensial pihak ketiga (password WordPress, token sosmed, API key Gemini)
  dienkripsi Fernet di level property SQLAlchemy. `encrypt_value` menolak menyimpan
  plaintext kalau enkripsi gagal.
- Auth JWT (cookie `httponly` + header Bearer), Google token diverifikasi `aud`
  dan `email_verified`.
- Rate limiting per user (fallback IP) via Flask-Limiter + Redis.
- Security headers + CSP, container berjalan sebagai non-root user.
- Webhook Tripay diverifikasi HMAC-SHA256 dengan `compare_digest`.

**Penting**: `FERNET_KEY` tidak boleh berubah. Kalau hilang, semua kredensial
tersimpan tidak bisa didekripsi dan harus dimasukkan ulang.

## Environment Variables

Lihat `.env.example`. Yang wajib untuk production:

```env
SECRET_KEY=<random panjang>
FERNET_KEY=<python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())">
POSTGRES_PASSWORD=<password kuat>
GOOGLE_CLIENT_ID=<oauth client id>
ADMIN_EMAILS=admin@example.com
```

Kalau `SECRET_KEY` / `FERNET_KEY` kosong, keduanya dibuat otomatis dan disimpan di
volume `autowp_runtime` supaya konsisten antar service. Ini agar deploy tidak gagal,
tapi untuk production sebaiknya diisi eksplisit.

⚠️ `TRIPAY_API_URL` dan `PAYPAL_API_URL` **default ke sandbox**. Untuk transaksi
sungguhan, isi URL production. Aplikasi akan menulis warning di log saat startup
kalau mendeteksi kredensial asli dengan URL sandbox.

## Development

```bash
# Backend
pip install -r requirements.txt
python migrate.py
python app.py                    # http://localhost:5005

# Frontend
cd frontend && npm install && npm run dev
```

## Deployment

```bash
docker compose up -d --build
docker compose logs -f web
```

## Perintah Operasional

```bash
docker compose ps
docker compose restart scheduler
docker compose logs scheduler --tail=100
```

Cek posting terakhir:

```bash
docker compose exec postgres psql -U autowp -d autowpdb -c "SELECT created_at, left(title, 60), success FROM post_logs ORDER BY created_at DESC LIMIT 10;"
```

## Troubleshooting

**Bot tidak posting sesuai jadwal** — cek log scheduler. Pastikan site `auto_post`
aktif, punya `selected_categories`, dan user masih punya kredit.

**Item antrean nyangkut di status `posting`** — dispatcher otomatis mengembalikannya
ke `pending` setelah 90 menit (`STUCK_POSTING_TIMEOUT_MINUTES` di `dispatcher.py`).

**Artikel gagal generate** — cek error Gemini API:

```bash
docker compose logs worker --tail=100 | grep -i error
```

**Reset konfigurasi Gemini**:

```bash
docker compose exec postgres psql -U autowp -d autowpdb -c "DELETE FROM config;"
```

## Integrasi Platform

| Platform | Dokumentasi | Field |
|---|---|---|
| WordPress | — | URL, Username, Application Password |
| Telegram | `docs/TELEGRAM_SETUP.md` | Bot Token, Chat ID |
| Telegram Channel | `docs/TELEGRAM_CHANNEL_SETUP.md` | Channel ID |
| Facebook | `docs/FACEBOOK_SETUP.md` | Page ID, Access Token |
| Twitter/X | `docs/TWITTER_SETUP.md` | API Key, Secret, Access Token, Secret |
| Threads | `docs/THREADS_SETUP.md` | User ID, Access Token |
| Pinterest | — | Board ID, Access Token |

Dokumentasi tambahan: `docs/HOW_RESEARCH_WORKS.md`, `docs/CONTENT_QUALITY.md`,
`docs/MONITORING_GUIDE.md`.
