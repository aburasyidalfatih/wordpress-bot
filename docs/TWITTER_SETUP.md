# 𝕏 Auto Post ke Twitter/X

## Setup Twitter API Credentials

### 🎯 Yang Dibutuhkan:
1. **Twitter/X Account**
2. **Twitter Developer Account** (gratis)
3. **API Keys & Access Tokens**

---

## 📋 Langkah-Langkah Setup:

### **1. Apply for Developer Account**

1. Buka: https://developer.twitter.com/en/portal/dashboard
2. Klik **"Sign up"** (jika belum punya)
3. Pilih **"Hobbyist"** → **"Making a bot"**
4. Isi form aplikasi:
   - App name: `WordPress Auto Post Bot`
   - Use case: `Automated posting of blog articles`
5. Agree to terms → Submit

### **2. Create Project & App**

1. Setelah approved, klik **"Create Project"**
2. Project name: `Blog Auto Poster`
3. Use case: **"Making a bot"**
4. Project description: `Automated blog article posting`
5. Klik **"Create App"**
6. App name: `kelasmaster-bot`

### **3. Generate API Keys**

1. Di App dashboard, klik **"Keys and Tokens"**
2. Klik **"Generate"** di **API Key and Secret**
3. **SIMPAN** kedua keys:
   - ✅ API Key (Consumer Key)
   - ✅ API Secret (Consumer Secret)
4. Klik **"Generate"** di **Access Token and Secret**
5. **SIMPAN** kedua tokens:
   - ✅ Access Token
   - ✅ Access Token Secret

### **4. Set App Permissions**

1. Klik tab **"Settings"**
2. Scroll ke **"App permissions"**
3. Klik **"Edit"**
4. Pilih: **"Read and Write"**
5. Save

**PENTING:** Jika permissions diubah, regenerate Access Token & Secret!

### **5. Konfigurasi di Dashboard**

1. Buka dashboard: http://localhost:5000
2. Scroll ke **"𝕏 Auto Post ke Twitter/X"**
3. Centang **"Aktifkan Auto Post ke Twitter"**
4. Input credentials:
   - API Key (Consumer Key)
   - API Secret (Consumer Secret)
   - Access Token
   - Access Token Secret
5. Klik **"💾 Simpan Konfigurasi"**

---

## 🧪 Test Posting

```bash
cd /home/ubuntu/wordpress-bot
source venv/bin/activate
python test_twitter.py
```

---

## 📊 Format Tweet:

```
[Judul Artikel]

[Cuplikan singkat]...

[Link artikel]

#SekolahDigital #Pendidikan
```

**Dengan featured image!**

**Limit:** 280 karakter (otomatis dipotong jika terlalu panjang)

---

## 🔧 Troubleshooting

### **Error: "Forbidden: 403"**
**Solusi:**
- App permissions bukan "Read and Write"
- Regenerate Access Token setelah ubah permissions

### **Error: "Unauthorized: 401"**
**Solusi:**
- API Keys atau Access Tokens salah
- Copy ulang dengan hati-hati (no spaces)

### **Error: "Duplicate content"**
**Solusi:**
- Twitter tidak allow posting konten yang sama
- Normal untuk test, akan berbeda untuk artikel baru

### **Error: "Rate limit exceeded"**
**Solusi:**
- Terlalu banyak posting dalam waktu singkat
- Tunggu beberapa menit

---

## 📝 Checklist Setup

- [ ] Twitter Developer Account sudah approved
- [ ] Project & App sudah dibuat
- [ ] API Key & Secret sudah di-generate
- [ ] Access Token & Secret sudah di-generate
- [ ] App permissions: "Read and Write"
- [ ] Semua 4 credentials sudah disimpan
- [ ] Konfigurasi sudah diinput di dashboard
- [ ] Test posting berhasil

---

## 🎯 Tips

1. **Simpan credentials dengan aman** - jangan share
2. **Set permissions ke "Read and Write"** sebelum generate tokens
3. **Regenerate tokens** jika ubah permissions
4. **Tweet max 280 chars** - bot akan auto-shorten
5. **Gambar optional** - akan posting text jika gambar gagal

---

## 🎉 Selesai!

Sekarang setiap artikel baru akan otomatis:
- ✅ Publish ke WordPress
- ✅ Notifikasi ke Telegram
- ✅ Post ke Telegram Channel
- ✅ Post ke Facebook Fanpage
- ✅ **Post ke Twitter/X** (dengan gambar)

**5-Platform Distribution!** 🚀

---

## 📚 Referensi

- Twitter Developer Portal: https://developer.twitter.com/en/portal/dashboard
- API Documentation: https://developer.twitter.com/en/docs/twitter-api
- Tweepy Docs: https://docs.tweepy.org/
