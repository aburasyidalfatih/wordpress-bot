#!/usr/bin/env python3
"""
Script untuk menambahkan deskripsi ke semua kategori WordPress
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import Database
import requests
from requests.auth import HTTPBasicAuth

# Deskripsi SEO-friendly untuk setiap kategori
CATEGORY_DESCRIPTIONS = {
    'Kepemimpinan Lembaga Pendidikan': 'Panduan lengkap kepemimpinan dan manajemen lembaga pendidikan Indonesia. Tips memimpin sekolah, yayasan, dan institusi pendidikan dengan efektif.',
    
    'Digitalisasi Pendidikan': 'Transformasi digital sekolah dan lembaga pendidikan. Panduan implementasi teknologi, sistem informasi manajemen, dan platform pembelajaran online.',
    
    'Strategi Pemasaran': 'Strategi digital marketing untuk sekolah dan lembaga pendidikan. Panduan promosi, branding, recruitment siswa, dan optimasi website sekolah.',
    
    'Pengembangan Kurikulum': 'Panduan pengembangan dan implementasi kurikulum pendidikan Indonesia. Kurikulum Merdeka, pembelajaran inovatif, dan assessment methods.',
    
    'Manajemen Keuangan': 'Manajemen keuangan sekolah dan lembaga pendidikan. Panduan budgeting, akuntansi, transparansi keuangan, dan compliance ISAK 35.',
    
    'Manajemen SDM': 'Manajemen sumber daya manusia pendidikan. Panduan rekrutmen guru, training, performance management, dan pengembangan SDM sekolah.',
    
    'Pembuatan SOP': 'Panduan pembuatan standar operasional prosedur (SOP) untuk sekolah dan lembaga pendidikan. Dokumentasi proses dan quality assurance.',
    
    'Layanan Orang Tua': 'Strategi komunikasi dan engagement dengan orang tua siswa. Panduan membangun hubungan sekolah-orang tua yang efektif.',
    
    'Legalitas Dan Perizinan': 'Panduan legalitas dan perizinan lembaga pendidikan Indonesia. Izin operasional, akreditasi, dan compliance regulasi pendidikan.',
    
    'Manajemen Asrama': 'Manajemen asrama dan boarding school. Panduan pengelolaan asrama, kesejahteraan siswa, dan operasional boarding school.',
    
    'Unit Usaha Sekolah': 'Pengembangan unit usaha dan kewirausahaan sekolah. Panduan income generating activities dan bisnis unit pendidikan.',
    
    'Hotnews Pendidikan': 'Berita viral dan trending seputar dunia pendidikan Indonesia. Update terkini, isu hot, dan fenomena viral pendidikan.',
    
    'Biaya Pendidikan': 'Informasi lengkap biaya sekolah, universitas, dan pendaftaran siswa/mahasiswa baru di Indonesia. Panduan PSB dan beasiswa pendidikan.'
}

def update_category_description(wp_url, username, password, category_id, description):
    """Update deskripsi kategori di WordPress"""
    api_url = f"{wp_url.rstrip('/')}/wp-json/wp/v2/categories/{category_id}"
    
    response = requests.post(
        api_url,
        json={'description': description},
        auth=HTTPBasicAuth(username, password),
        timeout=30
    )
    
    return response.status_code == 200

def main():
    # Load config
    db = Database('sqlite:///wordpress_bot.db')
    
    with db.get_session() as session:
        from database import Config
        config = session.query(Config).first()
        
        if not config:
            print("❌ Config tidak ditemukan")
            return
        
        wp_url = config.wordpress_url
        username = config.wordpress_username
        password = config.wordpress_password
        categories = config.categories or []
    
    if not wp_url or not username or not password:
        print("❌ WordPress credentials belum diisi")
        return
    
    print("="*70)
    print("📝 MENAMBAHKAN DESKRIPSI KE SEMUA KATEGORI")
    print("="*70)
    print(f"🌐 WordPress: {wp_url}")
    print(f"📂 Total kategori: {len(categories)}\n")
    
    success_count = 0
    skip_count = 0
    
    for cat in categories:
        cat_name = cat['name']
        cat_id = cat['id']
        
        if cat_name in CATEGORY_DESCRIPTIONS:
            description = CATEGORY_DESCRIPTIONS[cat_name]
            print(f"📝 {cat_name} (ID: {cat_id})")
            print(f"   Deskripsi: {description[:60]}...")
            
            if update_category_description(wp_url, username, password, cat_id, description):
                print(f"   ✅ Berhasil diupdate\n")
                success_count += 1
            else:
                print(f"   ❌ Gagal update\n")
        else:
            print(f"⏭️  {cat_name} - Skip (tidak ada deskripsi)\n")
            skip_count += 1
    
    print("="*70)
    print("📊 SUMMARY")
    print("="*70)
    print(f"✅ Berhasil: {success_count} kategori")
    print(f"⏭️  Dilewati: {skip_count} kategori")
    print(f"📂 Total: {len(categories)} kategori")
    print("\n💡 Deskripsi sudah ditambahkan ke WordPress!")
    print("="*70)

if __name__ == '__main__':
    main()
