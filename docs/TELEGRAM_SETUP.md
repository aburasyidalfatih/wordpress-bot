# Setup Notifikasi Telegram

## Cara Setup Bot Telegram

### 1. Buat Bot Telegram
1. Buka Telegram dan cari **@BotFather**
2. Kirim perintah `/newbot`
3. Ikuti instruksi untuk memberi nama bot
4. Copy **Bot Token** yang diberikan (format: `1234567890:ABCdefGHIjklMNOpqrsTUVwxyz`)

### 2. Dapatkan Chat ID

**Untuk Personal Chat:**
1. Cari **@userinfobot** di Telegram
2. Kirim pesan `/start`
3. Bot akan memberikan **Chat ID** Anda

**Untuk Group Chat:**
1. Tambahkan bot Anda ke grup
2. Cari **@userinfobot** dan tambahkan ke grup yang sama
3. Bot akan memberikan **Group Chat ID** (format: `-1001234567890`)
4. Hapus @userinfobot dari grup

### 3. Konfigurasi di Dashboard
1. Buka dashboard WordPress Auto Post Bot
2. Scroll ke bagian **📱 Notifikasi Telegram**
3. Centang "Aktifkan Notifikasi Telegram"
4. Masukkan **Bot Token** dan **Chat ID**
5. Klik **📲 Test Notifikasi** untuk memastikan koneksi berhasil
6. Klik **💾 Simpan Konfigurasi**

## Format Notifikasi

Bot akan mengirim notifikasi untuk:

✅ **Artikel Berhasil Dipublish**
```
✅ Artikel Berhasil Dipublish!

📝 Judul: [judul artikel]
📂 Kategori: [nama kategori]
📊 Panjang: [jumlah kata] kata
🎨 Featured Image: WebP ([ukuran] KB)
🔗 URL: [link artikel]

🎉 Status: Published
```

🤖 **Mulai Generate Artikel**
```
🤖 WordPress Auto Post Bot

📝 Mulai generate artikel...
📂 Kategori: [nama kategori]
```

❌ **Posting Gagal**
```
❌ Posting Gagal!

📝 Judul: [judul artikel]
📂 Kategori: [nama kategori]
⚠️ Error: [pesan error]
```

## Troubleshooting

**Notifikasi tidak terkirim?**
- Pastikan Bot Token dan Chat ID benar
- Pastikan bot sudah di-start (kirim `/start` ke bot)
- Untuk grup, pastikan bot sudah ditambahkan sebagai admin
- Cek koneksi internet server

**Test notifikasi gagal?**
- Periksa kembali Bot Token (tidak ada spasi)
- Periksa Chat ID (untuk grup harus ada tanda minus `-`)
- Pastikan checkbox "Aktifkan Notifikasi Telegram" sudah dicentang
