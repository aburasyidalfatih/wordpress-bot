# WordPress Auto Post Bot — Dokumentasi

**URL**: https://bot.kelasmaster.id  
**Stack**: Python 3 + Flask + PostgreSQL 15 + Redis/RQ  
**Server**: VPS 43.157.223.102, port 5003  
**Process Manager**: Supervisor  
**Last Updated**: 2026-03-22

---

## Arsitektur

```
https://bot.kelasmaster.id
        │
    Nginx (SSL)
        │
    Flask app (port 5003)
        ├── Redis/RQ      ──→ Background jobs
        ├── Dispatcher    ──→ Auto post terjadwal
        ├── Gemini AI    ──→ Generate artikel & gambar
        ├── WordPress API──→ Publish artikel
        ├── Telegram API ──→ Notifikasi & channel post
        ├── Facebook API ──→ Auto post ke fanpage
        ├── Twitter API  ──→ Auto post ke X
        └── Threads API  ──→ Auto post ke Threads
```

## File Struktur

```
wordpress-bot/
├── app.py              # Entry point Flask, semua routes
├── bot.py              # ArticleGenerator, WordPressPublisher
├── database.py         # Database wrapper (SQLAlchemy: PostgreSQL production, SQLite fallback)
├── config.py           # Konstanta konfigurasi
├── ml_optimizer.py     # AI category optimizer
├── seo_research.py     # SEO research helper
├── trending_research.py# Google Trends wrapper
├── post_to_threads.py  # Threads posting helper
├── templates/
│   ├── base.html       # Layout utama (sidebar + topbar)
│   ├── index.html      # Dashboard
│   ├── settings.html   # Konfigurasi
│   ├── prompts.html    # Custom AI prompts
│   ├── research.html   # Trending topics
│   ├── monitor.html    # System health
│   └── login.html      # PIN login
├── static/
│   ├── app.css         # Design system (dark theme)
│   ├── app.js          # JS utilities (toast, modal, dll)
│   ├── favicon.svg     # Favicon
│   └── lucide.min.js   # Icon library
├── scripts/
│   ├── add_category.py           # Tambah kategori via CLI
│   ├── add_category_descriptions.py
│   ├── reupload_images.py        # Re-upload gambar ke WP
│   ├── run_research.py           # Jalankan research manual
│   ├── check_scheduler.sh        # Cek status scheduler
│   ├── cleanup.sh                # Bersihkan log lama
│   └── monitor.sh                # Monitor bot
├── docs/               # Dokumentasi setup per platform
├── logs/               # Log files (rotasi otomatis)
├── docker-compose.yml  # Web, worker, scheduler, PostgreSQL 15, Redis
├── wordpress_bot.db    # SQLite fallback/local legacy database
├── .env                # Environment variables (tidak di-commit)
└── venv/               # Python virtual environment
```

## Fitur

| Fitur | Deskripsi |
|---|---|
| Auto Post | Generate & publish artikel ke WordPress terjadwal |
| Multi-platform | Post ke Telegram, Facebook, Twitter/X, Threads |
| Gemini AI | Generate konten artikel (model terpisah dari gambar) |
| Featured Image | Generate gambar landscape 16:9 via Gemini image model |
| SEO Optimized | Artikel dengan meta description, focus keyword, excerpt |
| Research | Trending topics via Google Trends per kategori |
| Category Rotation | Rotasi kategori otomatis setiap posting |
| AI Optimizer | Reorder kategori berdasarkan engagement performance |
| Sync Engagement | Sinkronisasi views/comments dari WordPress |
| Custom Prompts | Override prompt artikel & gambar via dashboard |
| PIN Auth | Proteksi dashboard dengan 6-digit PIN |

## Konfigurasi Model Gemini

Dua model terpisah bisa dikonfigurasi di `/settings`:

| Setting | Default | Fungsi |
|---|---|---|
| Model Artikel | `gemini-2.5-pro` | Generate konten artikel |
| Model Gambar | `gemini-3.1-flash-image-preview` | Generate featured image |

**Pilihan Model Artikel:**
- `gemini-2.5-pro` — Best quality
- `gemini-2.5-flash` — Fast & cheap
- `gemini-2.5-flash-lite` — Fastest
- `gemini-3.1-pro-preview` — Most advanced
- `gemini-3-flash-preview` — Frontier

**Pilihan Model Gambar:**
- `gemini-3.1-flash-image-preview` — Nano Banana 2, fast
- `gemini-3-pro-image-preview` — Nano Banana Pro, best quality
- `gemini-2.5-flash-image` — Nano Banana, stable

## Jadwal Posting

Default: `0,6,12,18` (4x per hari — jam 00:00, 06:00, 12:00, 18:00)  
Bisa diubah di Settings → Schedule Hours.

Auto Research: setiap hari jam 00:00 (jika diaktifkan).

## Database

Production Docker memakai **PostgreSQL 15** (`postgres:15-alpine`) melalui `DATABASE_URL`. Jika `DATABASE_URL` tidak diset, aplikasi fallback ke `sqlite:///wordpress_bot.db` untuk mode lokal/legacy.

Tabel utama:
- `users` — akun, role, tier, kredit
- `wordpress_sites` — konfigurasi multi-website per user
- `config` — konfigurasi Gemini global/admin
- `post_logs` — riwayat semua posting (title, url, success, engagement)
- `research_data` — hasil research trending topics per kategori
- `content_queue` — antrean judul/content idea
- `transactions` — riwayat top-up kredit

Contoh backup PostgreSQL via cron setiap hari jam 02:00:
```bash
0 2 * * * docker compose exec -T postgres pg_dump -U autowp autowpdb > /home/ubuntu/backups/autowp_$(date +\%Y\%m\%d).sql
```

## Deployment Docker/Dokploy

`docker-compose.yml` menjalankan `web`, `worker`, `scheduler`, **PostgreSQL 15**, dan Redis. Untuk production, sebaiknya isi env berikut di Dokploy:

```env
SECRET_KEY=<random secret panjang>
FERNET_KEY=<hasil python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())">
```

Jika kedua env itu belum diisi, aplikasi tetap bisa start: `SECRET_KEY` dan `FERNET_KEY` akan dibuat otomatis di volume bersama `autowp_runtime` pada boot pertama. Ini mencegah deploy gagal saat Dokploy menjalankan `docker compose` tanpa `.env`, sekaligus menjaga secret tetap sama untuk `web`, `worker`, dan `scheduler`.

## Perintah Penting

```bash
# Status
sudo supervisorctl status wordpress-bot

# Restart
sudo supervisorctl restart wordpress-bot

# Log realtime
tail -f /home/ubuntu/wordpress-bot/logs/bot.log

# Log supervisor
tail -f /home/ubuntu/wordpress-bot/supervisor.out.log

# Jika port conflict (zombie process)
sudo supervisorctl stop wordpress-bot
sudo fuser -k 5003/tcp
sudo supervisorctl start wordpress-bot

# Cek database production
docker compose exec postgres psql -U autowp -d autowpdb \
  -c "SELECT created_at, left(title, 60), success FROM post_logs ORDER BY created_at DESC LIMIT 10;"

# Manual post via CLI
cd /home/ubuntu/wordpress-bot
source venv/bin/activate
python -c "from app import generate_and_post; generate_and_post(USER_ID, site_id=SITE_ID)"
```

## Supervisor Config

```ini
[program:wordpress-bot]
command=/home/ubuntu/wordpress-bot/venv/bin/python app.py
directory=/home/ubuntu/wordpress-bot
user=ubuntu
autostart=true
autorestart=true
stderr_logfile=/home/ubuntu/wordpress-bot/supervisor.err.log
stdout_logfile=/home/ubuntu/wordpress-bot/supervisor.out.log
```

## Nginx Config

```nginx
server {
    server_name bot.kelasmaster.id;
    location / {
        proxy_pass http://127.0.0.1:5003;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
    listen 443 ssl; # managed by Certbot
}
```

## Troubleshooting

### Port 5003 already in use
```bash
sudo supervisorctl stop wordpress-bot
sudo fuser -k 5003/tcp
sleep 2
sudo supervisorctl start wordpress-bot
```

### Bot tidak posting sesuai jadwal
```bash
# Cek scheduler/dispatcher log
docker compose logs scheduler --tail=100
# Restart scheduler
docker compose restart scheduler
```

### Artikel gagal generate
Cek log untuk error Gemini API:
```bash
grep "ERROR\|error" /home/ubuntu/wordpress-bot/logs/bot.log | tail -20
```

### Reset konfigurasi
```bash
docker compose exec postgres psql -U autowp -d autowpdb -c "DELETE FROM config;"
# Lalu isi ulang via Admin Settings
```

## Integrasi Platform

| Platform | Setup Docs | Field di Settings |
|---|---|---|
| WordPress | — | URL, Username, App Password |
| Telegram | `docs/TELEGRAM_SETUP.md` | Bot Token, Chat ID |
| Telegram Channel | `docs/TELEGRAM_CHANNEL_SETUP.md` | Channel ID |
| Facebook | `docs/FACEBOOK_SETUP.md` | Page ID, Access Token |
| Twitter/X | `docs/TWITTER_SETUP.md` | API Key, Secret, Token |
| Threads | `docs/THREADS_SETUP.md` | User ID, Access Token |

## Changelog Terakhir (2026-03-22)

- **Model Gemini terpisah** — Model artikel dan gambar bisa dikonfigurasi secara independen
- **Model terbaru** — Ditambahkan Gemini 3.1 Pro, 3 Flash, Nano Banana 2, Nano Banana Pro
- **Quick Actions di topbar** — Tombol Post Now, Research, Sync, Optimize dipindah ke topbar
- **Favicon** — Icon "W" ungu di browser tab
- **Responsive fix** — Grid monitor & research responsive di mobile
- **CSS cleanup** — Inline style dipindah ke app.css
