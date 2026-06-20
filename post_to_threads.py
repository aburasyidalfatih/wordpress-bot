#!/usr/bin/env python3
"""Post last article to Threads"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import Database
from app import load_config
import requests

# Get last post
db = Database('sqlite:///wordpress_bot.db')
logs = db.get_logs(limit=1)

if not logs:
    print("❌ No posts found")
    sys.exit(1)

post = logs[0]
config = load_config()

title = post['title']
url = post['post_url']
category = post['category']

print("=" * 60)
print("📝 POSTING TO THREADS")
print("=" * 60)
print(f"\n📄 Post:")
print(f"   {title}")
print(f"   {url}")

if not config.get('threads_enabled'):
    print("\n❌ Threads not enabled in config")
    sys.exit(1)

user_id = config.get('threads_user_id')
token = config.get('threads_access_token')

if not user_id or not token:
    print("\n❌ Threads credentials not configured")
    sys.exit(1)

# Get article content to extract first paragraph
print("\n🔄 Fetching article content...")
try:
    import requests
    import re
    from bs4 import BeautifulSoup
    
    response = requests.get(url, timeout=10)
    soup = BeautifulSoup(response.text, 'html.parser')
    
    # Remove script and style elements
    for script in soup(["script", "style", "noscript"]):
        script.decompose()
    
    # Try to get first paragraph from article content
    article_content = soup.find('article') or soup.find('div', class_='entry-content')
    if article_content:
        paragraphs = article_content.find_all('p')
        first_para = ''
        for p in paragraphs:
            # Get text and clean it
            text = p.get_text(separator=' ', strip=True)
            # Remove extra whitespace
            text = re.sub(r'\s+', ' ', text).strip()
            if len(text) > 50:  # Skip short paragraphs
                first_para = text
                break
        
        # If first paragraph too long, get first 2-3 sentences
        if len(first_para) > 200:
            sentences = re.split(r'[.!?]\s+', first_para)
            first_para = '. '.join(sentences[:2])
            if not first_para.endswith('.'):
                first_para += '.'
        
        if first_para:
            caption = f"{first_para}\n\n👉 Baca selengkapnya:\n{url}\n\n#Pendidikan #KelasMaster"
        else:
            # Fallback to title
            caption = f"{title}\n\n👉 Baca selengkapnya:\n{url}\n\n#Pendidikan #KelasMaster"
    else:
        # Fallback to title
        caption = f"{title}\n\n👉 Baca selengkapnya:\n{url}\n\n#Pendidikan #KelasMaster"
        
except Exception as e:
    print(f"   ⚠️  Could not fetch content: {e}")
    # Fallback to title
    caption = f"{title}\n\n👉 Baca selengkapnya:\n{url}\n\n#Pendidikan #KelasMaster"

print(f"\n📝 Caption ({len(caption)} chars):")
print(caption)

# Step 1: Create container
print("\n🔄 Creating container...")
try:
    response = requests.post(
        f"https://graph.threads.net/v1.0/{user_id}/threads",
        params={
            'media_type': 'TEXT',
            'text': caption,
            'access_token': token
        },
        timeout=30
    )
    response.raise_for_status()
    data = response.json()
    
    if 'id' not in data:
        print(f"❌ Failed: {data}")
        sys.exit(1)
    
    container_id = data['id']
    print(f"✅ Container: {container_id}")
    
    # Step 2: Publish
    print("\n🔄 Publishing...")
    response = requests.post(
        f"https://graph.threads.net/v1.0/{user_id}/threads_publish",
        params={
            'creation_id': container_id,
            'access_token': token
        },
        timeout=30
    )
    response.raise_for_status()
    data = response.json()
    
    if 'id' in data:
        print(f"✅ Published: {data['id']}")
        print(f"\n🎉 SUCCESS! Post sent to Threads!")
    else:
        print(f"❌ Failed: {data}")
        
except Exception as e:
    print(f"❌ Error: {e}")
    if hasattr(e, 'response') and e.response:
        try:
            error_data = e.response.json()
            print(f"Error details: {error_data}")
        except:
            print(f"Response: {e.response.text}")

print("=" * 60)
