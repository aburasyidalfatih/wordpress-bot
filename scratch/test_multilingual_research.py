import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trending_research import TrendingResearch
from seo_research import SEOResearch
import json

print("=== Testing TrendingResearch ===")
trending = TrendingResearch()
print("1. Indonesian Trends (fallback):")
tr_id = trending._generate_fallback_topics("Digitalisasi Pendidikan", count=2, language='id')
print(json.dumps(tr_id, indent=2))

print("\n2. English Trends (fallback):")
tr_en = trending._generate_fallback_topics("Digital Education", count=2, language='en')
print(json.dumps(tr_en, indent=2))

print("\n=== Testing SEOResearch ===")
seo = SEOResearch()
print("1. Indonesian Related Questions:")
q_id = seo.get_related_questions("Teknologi", limit=3, language='id')
print(q_id)

print("\n2. English Related Questions:")
q_en = seo.get_related_questions("Technology", limit=3, language='en')
print(q_en)

print("\n3. English Keyword Suggestions:")
s_en = seo.get_keyword_suggestions("Technology", limit=3, language='en')
print(s_en)

print("\n4. English Fallback Competitors:")
c_en = seo._get_fallback_competitors("Technology", language='en')
print(json.dumps(c_en, indent=2))

print("\n=== Done ===")
