#!/usr/bin/env python3
"""
Script untuk menambahkan kategori baru di WordPress
"""
import sys
sys.path.insert(0, '/home/ubuntu/wordpress-bot')

from database import Database
import requests
from requests.auth import HTTPBasicAuth
import os
from dotenv import load_dotenv

load_dotenv()

def add_wordpress_category(wp_url, username, password, category_name, description=""):
    """Tambahkan kategori baru ke WordPress"""
    
    # WordPress REST API endpoint
    api_url = f"{wp_url.rstrip('/')}/wp-json/wp/v2/categories"
    
    # Data kategori
    data = {
        'name': category_name,
        'description': description,
        'slug': category_name.lower().replace(' ', '-')
    }
    
    # Request dengan authentication
    response = requests.post(
        api_url,
        json=data,
        auth=HTTPBasicAuth(username, password),
        timeout=30
    )
    
    if response.status_code == 201:
        category = response.json()
        return {
            'success': True,
            'id': category['id'],
            'name': category['name'],
            'slug': category['slug']
        }
    else:
        return {
            'success': False,
            'error': response.text
        }

def main():
    # Load config dari database
    db = Database('sqlite:///wordpress_bot.db')
    
    with db.get_session() as session:
        from database import Config
        config = session.query(Config).first()
        
        if not config:
            print("❌ Config tidak ditemukan. Silakan setup di dashboard dulu.")
            return
        
        wp_url = config.wordpress_url
        username = config.wordpress_username
        password = config.wordpress_password
    
    if not wp_url or not username or not password:
        print("❌ WordPress credentials belum diisi. Silakan setup di dashboard.")
        return
    
    print("="*60)
    print("📝 MENAMBAHKAN KATEGORI BARU KE WORDPRESS")
    print("="*60)
    
    # Data kategori baru
    category_name = "Biaya Pendidikan"
    description = "Informasi lengkap biaya sekolah, universitas, dan pendaftaran siswa/mahasiswa baru di Indonesia"
    
    print(f"\n📂 Kategori: {category_name}")
    print(f"📝 Deskripsi: {description}")
    print(f"🌐 WordPress: {wp_url}")
    print(f"\n⏳ Menambahkan kategori...")
    
    result = add_wordpress_category(wp_url, username, password, category_name, description)
    
    if result['success']:
        print(f"\n✅ BERHASIL!")
        print(f"   ID: {result['id']}")
        print(f"   Nama: {result['name']}")
        print(f"   Slug: {result['slug']}")
        print(f"\n💡 Kategori sudah ditambahkan ke WordPress!")
        print(f"   Silakan refresh halaman Settings untuk melihat kategori baru.")
    else:
        print(f"\n❌ GAGAL!")
        print(f"   Error: {result['error']}")
        print(f"\n💡 Kemungkinan penyebab:")
        print(f"   • Kategori sudah ada")
        print(f"   • WordPress credentials salah")
        print(f"   • WordPress URL tidak valid")
    
    print("\n" + "="*60)

if __name__ == '__main__':
    main()
