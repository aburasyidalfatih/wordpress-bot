#!/usr/bin/env python3
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import trending, db, load_config
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def run_manual_research():
    config = load_config()
    
    if not config.get('selected_categories'):
        print("❌ No categories selected")
        return
    
    print(f"🔍 Starting research for {len(config['selected_categories'])} categories...\n")
    
    results = []
    for category in config['selected_categories']:
        category_name = category['name']
        print(f"📊 Researching: {category_name}")
        
        try:
            # Get trending data
            trending_data = trending.get_trending_topics(category_name, limit=15)
            if not trending_data:
                print(f"   ⚠️  No data found")
                continue
            
            # Get suggestions
            suggestions = trending.suggest_article_topics(category_name, count=10)
            
            # Save to database
            db.save_research_data(
                category_name,
                trending_data.get('trending_now', []),
                trending_data.get('related_rising', []),
                trending_data.get('related_top', []),
                suggestions
            )
            
            results.append({
                'category': category_name,
                'trending_count': len(trending_data.get('trending_now', [])),
                'rising_count': len(trending_data.get('related_rising', [])),
                'top_count': len(trending_data.get('related_top', [])),
                'suggestions_count': len(suggestions)
            })
            
            print(f"   ✅ Found {len(suggestions)} suggested topics")
            
        except Exception as e:
            print(f"   ❌ Error: {e}")
            continue
    
    print(f"\n{'='*60}")
    print("📊 RESEARCH SUMMARY")
    print(f"{'='*60}")
    for r in results:
        print(f"\n📂 {r['category']}")
        print(f"   🔥 Trending Now: {r['trending_count']} topics")
        print(f"   📈 Rising: {r['rising_count']} topics")
        print(f"   ⭐ Popular: {r['top_count']} topics")
        print(f"   💡 Suggestions: {r['suggestions_count']} topics")
    
    print(f"\n✅ Research completed! Visit http://localhost:5000/research to view details")

if __name__ == '__main__':
    run_manual_research()
