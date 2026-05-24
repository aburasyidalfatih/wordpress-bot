# 📘 Auto Post ke Facebook Fanpage

## Setup Facebook Page Access Token

### 🎯 Yang Dibutuhkan:
1. **Facebook Page** (Fanpage)
2. **Facebook Developer Account**
3. **Page Access Token** (never expires)

---

## 📋 Langkah-Langkah Setup:

### **1. Buat Facebook App**

1. Buka: https://developers.facebook.com
2. Klik **"My Apps"** → **"Create App"**
3. Pilih **"Business"** → **"Next"**
4. App Name: `WordPress Auto Post Bot`
5. App Contact Email: email Anda
6. Klik **"Create App"**

### **2. Add Facebook Login Product**

1. Di dashboard app, klik **"Add Product"**
2. Cari **"Facebook Login"** → Klik **"Set Up"**
3. Pilih **"Web"** platform
4. Site URL: `https://kelasmaster.id` (atau domain Anda)
5. Save

### **3. Generate Page Access Token**

1. Di sidebar, klik **"Tools"** → **"Graph API Explorer"**
2. Di dropdown **"User or Page"**, pilih **"Get Page Access Token"**
3. Pilih **Page** Anda dari list
4. Centang permissions:
   - ✅ `pages_manage_posts`
   - ✅ `pages_read_engagement`
   - ✅ `pages_show_list`
5. Klik **"Generate Access Token"**
6. **Copy token** yang muncul

### **4. Extend Token (Never Expires)**

**Opsi A: Via Graph API Explorer**
1. Masih di Graph API Explorer
2. Ganti endpoint menjadi: `/me/accounts`
3. Klik **"Submit"**
4. Cari page Anda di response
5. Copy **`access_token`** dari page tersebut (ini sudah long-lived)

**Opsi B: Via Access Token Debugger**
1. Buka: https://developers.facebook.com/tools/debug/accesstoken/
2. Paste token yang sudah di-generate
3. Klik **"Extend Access Token"**
4. Copy token baru (expires: Never)

### **5. Dapatkan Page ID**

**Cara 1: Via Page Settings**
1. Buka fanpage Anda
2. Settings → Page Info
3. Copy **Page ID**

**Cara 2: Via Graph API Explorer**
1. Endpoint: `/me/accounts`
2. Submit
3. Copy **`id`** dari page Anda

### **6. Konfigurasi di Dashboard**

1. Buka dashboard: http://localhost:5000
2. Scroll ke **"📘 Auto Post ke Facebook Fanpage"**
3. Centang **"Aktifkan Auto Post ke Facebook"**
4. Input **Page ID**: `123456789012345`
5. Input **Access Token**: `EAAxxxxxxxxxx...`
6. Klik **"💾 Simpan Konfigurasi"**

---

## 🧪 Test Posting

```bash
cd /home/ubuntu/wordpress-bot
source venv/bin/activate
python test_facebook.py
```

---

## 📊 Format Posting ke Facebook:

```
[Judul Artikel]

[Cuplikan artikel - 500 karakter]...

Baca artikel lengkap: [link]

#SekolahDigital #Pendidikan #KelasMaster
```

**Dengan featured image!**

---

## 🔧 Troubleshooting

### **Error: "Invalid OAuth access token"**
**Solusi:**
- Token expired atau salah
- Generate token baru
- Pastikan token adalah **Page Access Token**, bukan User Access Token

### **Error: "Permissions error"**
**Solusi:**
- Pastikan permission `pages_manage_posts` sudah dicentang
- Re-generate token dengan permission yang benar

### **Error: "Page ID not found"**
**Solusi:**
- Periksa Page ID sudah benar (numeric)
- Pastikan Anda admin/owner dari page tersebut

### **Posting berhasil tapi tidak ada gambar**
**Solusi:**
- Normal, Facebook kadang reject gambar tertentu
- Artikel tetap terposting dengan text + link

---

## 📝 Checklist Setup

- [ ] Facebook App sudah dibuat
- [ ] Facebook Login product sudah ditambahkan
- [ ] Page Access Token sudah di-generate
- [ ] Token sudah di-extend (never expires)
- [ ] Permission `pages_manage_posts` sudah ada
- [ ] Page ID sudah benar
- [ ] Konfigurasi sudah disimpan di dashboard
- [ ] Test posting berhasil

---

## 🎯 Tips

1. **Simpan token dengan aman** - jangan share ke orang lain
2. **Gunakan Page Access Token**, bukan User Access Token
3. **Extend token** agar tidak expire
4. **Test dulu** sebelum aktifkan auto post
5. **Monitor** posting pertama untuk memastikan format OK

---

## 🎉 Selesai!

Sekarang setiap artikel baru akan otomatis:
- ✅ Publish ke WordPress
- ✅ Notifikasi ke Telegram (personal/grup)
- ✅ Post ke Telegram Channel
- ✅ **Post ke Facebook Fanpage** (dengan gambar)

Quadruple distribution! 🚀

---

## 📚 Referensi

- Facebook Developers: https://developers.facebook.com
- Graph API Explorer: https://developers.facebook.com/tools/explorer/
- Access Token Debugger: https://developers.facebook.com/tools/debug/accesstoken/
- Page Permissions: https://developers.facebook.com/docs/pages/overview
