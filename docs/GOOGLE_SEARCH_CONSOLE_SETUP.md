# Google Search Console Integration

Integrasi ini menggunakan OAuth web-server dengan akses **read-only**. AutoWP
tidak dapat menambah atau menghapus property Search Console.

## Google Cloud Console

1. Buka project Google Cloud yang digunakan AutoWP.
2. Enable **Google Search Console API**.
3. Konfigurasikan OAuth consent screen.
4. Buat OAuth Client bertipe **Web application**, atau gunakan client Google
   Login yang sudah ada.
5. Tambahkan Authorized redirect URI berikut:

   ```text
   https://DOMAIN-AUTOWP/api/search-console/callback
   ```

6. Pastikan akun yang menghubungkan integrasi memang memiliki akses ke property
   Search Console website tersebut.

## Konfigurasi di AutoWP

Tidak diperlukan perubahan `.env` untuk Search Console. Buka **New Website**
atau **Edit Website → Search Console**, lalu isi Google OAuth Client ID dan
Client Secret. Client Secret disimpan terenkripsi dan field-nya dikosongkan
kembali setelah tersimpan.

UI akan menampilkan Authorized redirect URI berdasarkan domain AutoWP yang
sedang dibuka. Salin URI tersebut ke OAuth Client di Google Cloud.

## Penggunaan

1. Isi Client ID dan Client Secret di **Websites → Configure → Search Console**.
2. Simpan website.
3. Klik **Hubungkan Google Search Console** dan berikan izin read-only.
4. AutoWP mencoba memilih property yang domainnya sama dengan WordPress URL.
5. Bila belum terpilih, klik **Ambil Property** lalu pilih property secara manual.
6. Klik **Sinkronkan 56 Hari**.
7. Opportunity akan muncul di **Intelligence Hub** setelah background job selesai.

AutoWP menyimpan refresh token dalam keadaan terenkripsi menggunakan Fernet.
Snapshot hanya menyimpan query/page metrics untuk periode 28 hari saat ini dan
28 hari sebelumnya. Search Console API dapat mengembalikan top rows, bukan
jaminan seluruh row yang tersedia.
