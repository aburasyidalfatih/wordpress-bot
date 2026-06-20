#!/usr/bin/env python3
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot import WordPressPublisher, ArticleGenerator
from database import Database

db = Database('sqlite:///wordpress_bot.db')
config = db.get_config()

publisher = WordPressPublisher(
    config['wordpress_url'],
    config['wordpress_username'],
    config['wordpress_password']
)

generator = ArticleGenerator(
    config['gemini_api_key'],
    config.get('gemini_model', 'gemini-2.5-pro'),
    config.get('gemini_image_model', 'gemini-3.1-flash-image')
)

# 2 artikel terakhir yang gagal upload gambar
articles = [
    {'post_id': 8097, 'title': 'AI di Sekolah: Panduan Praktis Meningkatkan Mutu Pembelajaran'},
    {'post_id': 8095, 'title': 'Biaya Sekolah Swasta Jakarta: Strategi Menentukan Harga Juara'}
]

print("🔄 Re-uploading images for 2 articles...\n")

for article in articles:
    print(f"📝 {article['title']}")
    print(f"   Post ID: {article['post_id']}")
    
    # Generate image
    print("   📸 Generating image...")
    image_data = generator.generate_image("Pendidikan", article['title'], "")
    
    if not image_data:
        print("   ❌ Failed to generate image\n")
        continue
    
    # Upload image
    print("   ⬆️  Uploading image...")
    media_id = publisher.upload_image(image_data, article['title'])
    
    if not media_id:
        print("   ❌ Failed to upload image\n")
        continue
    
    print(f"   ✅ Image uploaded: ID {media_id}")
    
    # Update post with featured image
    print("   🔗 Setting as featured image...")
    import requests
    response = requests.post(
        f"{config['wordpress_url']}/wp-json/wp/v2/posts/{article['post_id']}",
        auth=(config['wordpress_username'], config['wordpress_password']),
        json={'featured_media': media_id},
        timeout=30
    )
    
    if response.status_code == 200:
        print(f"   ✅ Featured image set successfully!\n")
    else:
        print(f"   ❌ Failed to set featured image: {response.status_code}\n")

print("✅ Done!")
