# Content Quality Improvements

## Perubahan yang Dilakukan (2026-03-08)

### Update 1: Auto-Cleaning Content (08:33)
Bot sekarang otomatis membersihkan konten dari:
- ✅ Placeholder text seperti `[FLOWCHART: ...]`, `[INFOGRAPHIC: ...]`, `[CHECKLIST: ...]`
- ✅ ASCII art dan Unicode box drawing characters (─, │, ┼, dll)
- ✅ JSON artifacts yang muncul di awal/akhir konten
- ✅ Paragraf kosong yang tidak perlu
- ✅ Multiple newlines berlebihan

### Update 2: Variasi Pembuka Artikel (08:40)
Bot sekarang menggunakan 5 variasi pembuka artikel untuk menghindari repetisi:
- ✅ Story/Anekdot: "Pak Budi, kepala sekolah di Bandung..."
- ✅ Problem Statement: "Bayangkan: SPP naik 20%, guru resign..."
- ✅ Pertanyaan Provokatif: "Apa yang membuat 3 dari 5 sekolah..."
- ✅ Fakta Mengejutkan: "Tahun 2026, lebih banyak sekolah tutup..."
- ✅ Kontras: "Sekolah A penuh, Sekolah B sepi..."

**Larangan Eksplisit:**
- ✗ JANGAN selalu mulai dengan "Data internal kami di KelasMaster..."
- ✗ JANGAN gunakan pola yang sama dengan artikel sebelumnya
- ✓ Setiap artikel HARUS punya pembuka UNIK

### Update 3: SEO & Naturalness Optimization (08:45)
Bot sekarang menghasilkan artikel yang lebih natural dan SEO-friendly:

**Variasi Kalimat:**
- ✅ Mix panjang kalimat: 5-10, 15-20, 25-35 kata
- ✅ Variance >50 untuk lolos AI detection
- ✅ Rhythm natural seperti tulisan manusia

**Quote/Testimonial:**
- ✅ WAJIB 1-2 quote per artikel
- ✅ Format: "Quote," ujar Nama, Jabatan di Kota.
- ✅ Menambah kredibilitas & human touch

**Transisi Natural:**
- ✅ Gunakan: "Hasilnya?", "Faktanya:", "Contohnya:"
- ✗ Hindari: "Dengan demikian", "Oleh karena itu"

**Hindari Frasa AI:**
- ✗ "Penting untuk dicatat bahwa..."
- ✗ "Perlu diingat bahwa..."
- ✗ "Dalam konteks ini..."
- ✗ "Mari kita bahas..."

**Prediksi Skor:**
- Sebelum: 11/15 (73%) - GOOD
- Setelah: ~14/15 (93%) - EXCELLENT

### 2. Updated Prompt
Prompt AI diperbaharui dengan:
- ⚠️ **LARANGAN KERAS** untuk tidak menggunakan placeholder
- ✓ Instruksi jelas untuk menggunakan HTML table, bukan ASCII art
- ✓ Panduan lebih spesifik untuk format konten yang bersih

### 3. Double-Layer Cleaning
Cleaning dilakukan di 2 tempat:
1. **Saat generate artikel** (`generate_article()`) - cleaning hasil dari AI
2. **Saat posting** (`create_post()`) - final check sebelum publish

## Hasil yang Diharapkan

Artikel yang dihasilkan akan:
- ✅ Lebih bersih dan profesional
- ✅ Tidak ada placeholder text
- ✅ Tidak ada karakter aneh (ASCII art)
- ✅ Tidak ada JSON artifacts
- ✅ Format HTML yang proper

## Testing

Untuk test artikel baru:
1. Generate artikel dari dashboard
2. Cek preview sebelum publish
3. Pastikan tidak ada:
   - `[FLOWCHART: ...]` atau placeholder sejenis
   - Karakter box drawing (─, │, ┼)
   - JSON artifacts di awal artikel

## Troubleshooting

Jika masih ada masalah:
1. Cek log: `tail -f ~/wordpress-bot/dashboard.log`
2. Restart bot: `pkill -f "python.*app.py" && cd ~/wordpress-bot && nohup python3 app.py > dashboard.log 2>&1 &`
3. Untuk artikel lama yang sudah publish, gunakan script manual untuk clean

## Manual Cleaning Script

Jika perlu clean artikel yang sudah ada:

```bash
cd /home/ubuntu/wordpress-bot
source venv/bin/activate
python3 << 'EOF'
import requests
from requests.auth import HTTPBasicAuth
import re

WP_URL = "https://kelasmaster.id"
WP_USER = "andriko"
WP_PASS = "Sbyd JGoX limQ fHC3 VJsC VDar"
POST_ID = 8136  # Ganti dengan ID post yang mau dibersihkan

response = requests.get(
    f"{WP_URL}/wp-json/wp/v2/posts/{POST_ID}?context=edit",
    auth=HTTPBasicAuth(WP_USER, WP_PASS)
)

content = response.json()['content']['raw']

# Clean placeholders
patterns = [
    r'\[FLOWCHART:.*?\]',
    r'\[INFOGRAPHIC:.*?\]',
    r'\[CHECKLIST:.*?\]',
    r'\[DIAGRAM:.*?\]',
]
for pattern in patterns:
    content = re.sub(pattern, '', content, flags=re.IGNORECASE)

# Clean ASCII art
content = re.sub(r'[─│┼├┤┬┴┌┐└┘╔╗╚╝║═╠╣╦╩╬]', '', content)

# Update
response = requests.post(
    f"{WP_URL}/wp-json/wp/v2/posts/{POST_ID}",
    auth=HTTPBasicAuth(WP_USER, WP_PASS),
    json={'content': content}
)

print(f"Status: {response.status_code}")
EOF
```

---

**Last Updated**: 2026-03-08
**Status**: ✅ Implemented & Active
