# 🧵 Auto Post ke Threads

## Setup Threads API

### 🎯 Yang Dibutuhkan:
1. **Instagram Professional Account** (Business/Creator)
2. **Facebook Developer Account**
3. **Threads Access Token**

---

## 📋 Langkah-Langkah Setup:

### **1. Convert Instagram ke Professional Account**

1. Buka Instagram app
2. Settings → Account → Switch to Professional Account
3. Pilih **Creator** atau **Business**
4. Complete setup

### **2. Buat/Gunakan Facebook App**

1. Buka: https://developers.facebook.com
2. Gunakan App yang sudah ada (untuk Facebook posting)
3. ATAU buat App baru:
   - Create App → Business
   - App Name: `WordPress Auto Post Bot`

### **3. Add Threads API Product**

1. Di App dashboard, klik **"Add Product"**
2. Cari **"Threads API"**
3. Klik **"Set Up"**
4. Follow instruksi setup

### **4. Generate Access Token**

1. Tools → **Graph API Explorer**
2. Select App: pilih app Anda
3. Select User: pilih Instagram account Anda
4. Add Permissions:
   - ✅ `threads_basic`
   - ✅ `threads_content_publish`
5. Klik **"Generate Access Token"**
6. Login dengan Instagram account
7. **Copy token** yang muncul

### **5. Extend Token (Long-lived)**

**Via Graph API Explorer:**
1. Endpoint: `/oauth/access_token`
2. Parameters:
   ```
   grant_type: ig_exchange_token
   client_secret: [Your App Secret]
   access_token: [Short-lived token]
   ```
3. Submit → Copy long-lived token (60 hari)

**Via Access Token Debugger:**
1. https://developers.facebook.com/tools/debug/accesstoken/
2. Paste token
3. Klik **"Extend Access Token"**
4. Copy new token

### **6. Get User ID**

**Via Graph API Explorer:**
1. Endpoint: `/me?fields=id,username`
2. Submit
3. Copy **`id`** (numeric)

### **7. Konfigurasi di Dashboard**

1. Buka dashboard: http://localhost:5000
2. Scroll ke **"🧵 Auto Post ke Threads"**
3. Centang **"Aktifkan Auto Post ke Threads"**
4. Input **User ID**: `123456789012345`
5. Input **Access Token**: `IGQxxxxxxxxxx...`
6. Klik **"💾 Simpan Konfigurasi"**

---

## 🧪 Test Posting

```bash
cd /home/ubuntu/wordpress-bot
source venv/bin/activate
python test_threads.py
```

---

## 📊 Format Post di Threads:

```
[Judul Artikel]

[Cuplikan artikel - 400 karakter]...

[Link artikel]

#SekolahDigital #Pendidikan
```

**Max 500 karakter**

---

## 🔧 Troubleshooting

### **Error: "Invalid OAuth access token"**
**Solusi:**
- Token expired (max 60 hari)
- Generate token baru
- Extend token menjadi long-lived

### **Error: "Permissions error"**
**Solusi:**
- Permission `threads_content_publish` belum ada
- Re-generate token dengan permission yang benar

### **Error: "User not eligible"**
**Solusi:**
- Instagram account bukan Professional Account
- Convert ke Business/Creator account

### **Error: "Rate limit exceeded"**
**Solusi:**
- Terlalu banyak posting dalam waktu singkat
- Tunggu beberapa menit

---

## 📝 Checklist Setup

- [ ] Instagram sudah Professional Account (Business/Creator)
- [ ] Facebook App sudah dibuat
- [ ] Threads API product sudah ditambahkan
- [ ] Access Token sudah di-generate
- [ ] Token sudah di-extend (long-lived)
- [ ] Permission `threads_content_publish` sudah ada
- [ ] User ID sudah didapat
- [ ] Konfigurasi sudah disimpan di dashboard
- [ ] Test posting berhasil

---

## 🎯 Tips

1. **Gunakan Professional Account** - wajib untuk API access
2. **Extend token** agar tidak expire cepat (60 hari)
3. **Refresh token** sebelum expire
4. **Max 500 chars** - bot akan auto-shorten
5. **Image support** terbatas - text posting lebih reliable

---

## ⚠️ Limitations

- Access token expire setiap 60 hari (perlu refresh)
- Rate limit: max posting per hari
- Image posting butuh public URL (belum fully supported)
- Text-only posting lebih stable

---

## 🎉 Selesai!

Sekarang setiap artikel baru akan otomatis:
- ✅ Publish ke WordPress
- ✅ Notifikasi ke Telegram
- ✅ Post ke Telegram Channel
- ✅ Post ke Facebook Fanpage
- ✅ Post ke Twitter/X
- ✅ **Post ke Threads** (text)

**6-Platform Distribution!** 🚀

---

## 📚 Referensi

- Threads API Docs: https://developers.facebook.com/docs/threads
- Facebook Developers: https://developers.facebook.com
- Graph API Explorer: https://developers.facebook.com/tools/explorer/
- Access Token Debugger: https://developers.facebook.com/tools/debug/accesstoken/
