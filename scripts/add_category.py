#!/usr/bin/env python3
"""
Script untuk menambahkan kategori baru di WordPress
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
    
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    # Request dengan authentication
    response = requests.post(
        api_url,
        json=data,
        auth=HTTPBasicAuth(username, password),
        timeout=30,
        verify=False
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
    import argparse
    parser = argparse.ArgumentParser(description="Tambahkan kategori baru ke WordPress")
    parser.add_argument("--url", help="WordPress URL")
    parser.add_argument("--username", help="WordPress Username")
    parser.add_argument("--password", help="WordPress Application Password")
    parser.add_argument("--name", required=True, help="Nama Kategori Baru")
    parser.add_argument("--description", default="", help="Deskripsi Kategori Baru")
    args = parser.parse_args()
    
    wp_url = None
    username = None
    password = None
    
    if args.url and args.username and args.password:
        wp_url = args.url
        username = args.username
        password = args.password
    else:
        # Load config dari database
        db = Database('sqlite:///wordpress_bot.db')
        with db.get_session() as session:
            from database import WordPressSite
            site = session.query(WordPressSite).first()
            if site:
                wp_url = site.wordpress_url
                username = site.wordpress_username
                password = site.wordpress_password
    
    if not wp_url or not username or not password:
        print("[ERROR] WordPress credentials belum diisi. Silakan isi lewat database atau oper lewat argument:")
        print("   python scripts/add_category.py --url <URL> --username <USER> --password <APP_PASSWORD> --name <NAME> --description <DESC>")
        return
    
    print("="*60)
    print("MENAMBAHKAN KATEGORI BARU KE WORDPRESS")
    print("="*60)
    print(f"Kategori: {args.name}")
    print(f"Deskripsi: {args.description}")
    print(f"WordPress: {wp_url}")
    print("\n[INFO] Menambahkan kategori...")
    
    result = add_wordpress_category(wp_url, username, password, args.name, args.description)
    
    if result['success']:
        print(f"\n[SUCCESS] BERHASIL!")
        print(f"   ID: {result['id']}")
        print(f"   Nama: {result['name']}")
        print(f"   Slug: {result['slug']}")
    else:
        print(f"\n[ERROR] GAGAL!")
        print(f"   Error: {result['error']}")
    
    print("\n" + "="*60)

if __name__ == '__main__':
    main()
