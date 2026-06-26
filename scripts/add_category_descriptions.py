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
    # 5 Kategori Baru 2026
    'Akreditasi dan Mutu Pendidikan': 'Panduan taktis persiapan akreditasi sekolah/madrasah sesuai standar instrumen BAN-PDM terbaru. Fokus pada pemenuhan mutu lulusan, optimalisasi kinerja guru, proses pembelajaran, serta manajemen sekolah untuk meraih akreditasi Unggul.',
    'Kesejahteraan Guru': 'Informasi regulasi profesi guru ter-update di Indonesia. Membahas skema sertifikasi (PPG), tunjangan profesi (TPG), penataan status guru PPPK/Honorer, jaminan sosial, serta strategi pengembangan karir yang adil bagi guru.',
    'Manajemen Kelas': 'Metode praktis pengelolaan kelas berbasis disiplin positif dan pembelajaran berdiferensiasi (Kurikulum Merdeka). Tips merancang iklim belajar yang inklusif, mengatasi distraksi digital siswa di kelas, dan menjaga well-being murid.',
    'Pembelajaran Abad 21': 'Strategi pengajaran inovatif yang mengintegrasikan keterampilan 4C (Critical Thinking, Collaboration, Communication, Creativity). Panduan implementasi Projek P5 serta metode asesmen otentik yang relevan dengan masa depan siswa.',
    'Teknologi Pendidikan': 'Panduan implementasi EdTech dan kecerdasan buatan (AI) untuk efisiensi administrasi serta pengajaran. Membahas manajemen infrastruktur IT sekolah, keamanan data digital, dan optimalisasi bujet investasi teknologi.',
    
    # Kategori Lainnya
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
    
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    response = requests.post(
        api_url,
        json={'description': description},
        auth=HTTPBasicAuth(username, password),
        timeout=30,
        verify=False
    )
    
    return response.status_code == 200

def get_remote_categories(wp_url, username, password):
    """Ambil daftar kategori dari WordPress API secara langsung"""
    api_url = f"{wp_url.rstrip('/')}/wp-json/wp/v2/categories"
    
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    try:
        response = requests.get(
            api_url,
            params={"per_page": 100},
            auth=HTTPBasicAuth(username, password),
            timeout=30,
            verify=False
        )
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        print(f"[ERROR] Gagal mengambil kategori dari API: {e}")
    return None

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Update deskripsi kategori WordPress")
    parser.add_argument("--url", help="WordPress URL (misal: https://kelasmaster.id)")
    parser.add_argument("--username", help="WordPress Username")
    parser.add_argument("--password", help="WordPress Application Password")
    args = parser.parse_args()
    
    wp_url = None
    username = None
    password = None
    categories = None
    
    # Cek jika kredensial dioper via CLI
    if args.url and args.username and args.password:
        wp_url = args.url
        username = args.username
        password = args.password
        
        print("[INFO] Mengambil kategori langsung dari REST API...")
        remote_cats = get_remote_categories(wp_url, username, password)
        if remote_cats:
            categories = [{'id': cat['id'], 'name': cat['name']} for cat in remote_cats]
    else:
        # Load config dari local SQLite
        db = Database('sqlite:///wordpress_bot.db')
        with db.get_session() as session:
            from database import WordPressSite
            site = session.query(WordPressSite).first()
            if site:
                wp_url = site.wordpress_url
                username = site.wordpress_username
                password = site.wordpress_password
                categories = site.categories or []
                
    if not wp_url or not username or not password:
        print("[ERROR] WordPress credentials belum diisi. Silakan isi lewat database atau oper lewat argument:")
        print("   python scripts/add_category_descriptions.py --url <URL> --username <USER> --password <APP_PASSWORD>")
        return
        
    if not categories:
        print("[ERROR] Kategori tidak ditemukan.")
        return
    
    print("="*70)
    print("MENAMBAHKAN DESKRIPSI KE SEMUA KATEGORI")
    print("="*70)
    print(f"WordPress URL: {wp_url}")
    print(f"Total kategori: {len(categories)}\n")
    
    success_count = 0
    skip_count = 0
    
    for cat in categories:
        cat_name = cat['name']
        cat_id = cat['id']
        
        if cat_name in CATEGORY_DESCRIPTIONS:
            description = CATEGORY_DESCRIPTIONS[cat_name]
            print(f"Kategori: {cat_name} (ID: {cat_id})")
            print(f"   Deskripsi: {description[:60]}...")
            
            if update_category_description(wp_url, username, password, cat_id, description):
                print(f"   [SUCCESS] Berhasil diupdate\n")
                success_count += 1
            else:
                print(f"   [ERROR] Gagal update\n")
        else:
            print(f"[SKIP] {cat_name} - Tidak ada deskripsi baru\n")
            skip_count += 1
    
    print("="*70)
    print("SUMMARY")
    print("="*70)
    print(f"Berhasil: {success_count} kategori")
    print(f"Dilewati: {skip_count} kategori")
    print(f"Total: {len(categories)} kategori")
    print("\nDeskripsi sudah ditambahkan ke WordPress!")
    print("="*70)

if __name__ == '__main__':
    main()
