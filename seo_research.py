"""
SEO Research Module - Keyword & Question Research
Provides keyword suggestions and related questions for better SEO
"""

import requests
from bs4 import BeautifulSoup
import json
import time
from urllib.parse import quote_plus
import logging

logger = logging.getLogger(__name__)


class SEOResearch:
    """Research keywords and questions for SEO optimization"""
    
    def __init__(self):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
    
    def get_keyword_suggestions(self, keyword, limit=10):
        """Get keyword suggestions from Google Autocomplete"""
        suggestions = []
        
        try:
            # Google Autocomplete API
            url = f"http://suggestqueries.google.com/complete/search"
            params = {
                'client': 'firefox',
                'q': keyword,
                'hl': 'id'  # Indonesian
            }
            
            response = requests.get(url, params=params, headers=self.headers, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                if len(data) > 1:
                    suggestions = data[1][:limit]
                    logger.info(f"Found {len(suggestions)} keyword suggestions for: {keyword}")
            
        except Exception as e:
            logger.error(f"Error getting keyword suggestions: {e}")
        
        return suggestions
    
    def get_related_questions(self, keyword, limit=10):
        """Scrape 'People Also Ask' questions from Google"""
        questions = []
        
        try:
            # Search Google
            search_url = f"https://www.google.com/search?q={quote_plus(keyword)}&hl=id"
            response = requests.get(search_url, headers=self.headers, timeout=10)
            
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # Find PAA questions (multiple selectors for reliability)
                paa_divs = soup.find_all('div', {'class': lambda x: x and 'related-question' in x.lower()})
                
                if not paa_divs:
                    # Alternative selector
                    paa_divs = soup.find_all('div', {'jsname': True})
                
                for div in paa_divs[:limit]:
                    question_text = div.get_text(strip=True)
                    if question_text and '?' in question_text and len(question_text) > 10:
                        questions.append(question_text)
                
                # Fallback: Generate common questions
                if len(questions) < 3:
                    questions.extend(self._generate_common_questions(keyword))
                
                logger.info(f"Found {len(questions)} questions for: {keyword}")
            
        except Exception as e:
            logger.error(f"Error scraping questions: {e}")
            # Fallback to generated questions
            questions = self._generate_common_questions(keyword)
        
        return questions[:limit]
    
    def _generate_common_questions(self, keyword):
        """Generate common question patterns"""
        patterns = [
            f"Apa itu {keyword}?",
            f"Bagaimana cara {keyword}?",
            f"Apa manfaat {keyword}?",
            f"Apa saja jenis {keyword}?",
            f"Berapa biaya {keyword}?",
            f"Apa kelebihan dan kekurangan {keyword}?",
            f"Bagaimana tips {keyword}?",
            f"Apa tantangan {keyword}?",
            f"Bagaimana strategi {keyword}?",
            f"Apa contoh {keyword}?"
        ]
        return patterns[:5]
    
    def get_long_tail_keywords(self, base_keyword):
        """Get long-tail keyword variations"""
        modifiers = [
            "cara", "tips", "panduan", "strategi", "contoh",
            "terbaik", "efektif", "mudah", "lengkap", "gratis",
            "2026", "terbaru", "modern", "praktis", "sukses"
        ]
        
        long_tails = []
        
        # Get suggestions with modifiers
        for modifier in modifiers[:5]:
            query = f"{modifier} {base_keyword}"
            suggestions = self.get_keyword_suggestions(query, limit=3)
            long_tails.extend(suggestions)
            time.sleep(0.5)  # Rate limiting
        
        # Remove duplicates
        long_tails = list(set(long_tails))
        
        return long_tails[:15]
    
    def analyze_keyword(self, keyword):
        """Complete keyword analysis"""
        logger.info(f"Analyzing keyword: {keyword}")
        
        result = {
            'keyword': keyword,
            'suggestions': [],
            'long_tail': [],
            'questions': [],
            'related_topics': []
        }
        
        try:
            # 1. Get autocomplete suggestions
            result['suggestions'] = self.get_keyword_suggestions(keyword, limit=10)
            time.sleep(1)
            
            # 2. Get long-tail keywords
            result['long_tail'] = self.get_long_tail_keywords(keyword)
            time.sleep(1)
            
            # 3. Get related questions
            result['questions'] = self.get_related_questions(keyword, limit=10)
            
            # 4. Extract related topics from suggestions
            result['related_topics'] = self._extract_topics(result['suggestions'])
            
            logger.info(f"Analysis complete: {len(result['suggestions'])} suggestions, "
                       f"{len(result['questions'])} questions")
            
        except Exception as e:
            logger.error(f"Error in keyword analysis: {e}")
        
        return result
    
    def _extract_topics(self, suggestions):
        """Extract unique topics from suggestions"""
        topics = set()
        
        for suggestion in suggestions:
            # Split and extract meaningful words
            words = suggestion.lower().split()
            for word in words:
                if len(word) > 4 and word not in ['untuk', 'dengan', 'adalah', 'yang']:
                    topics.add(word)
        
        return list(topics)[:10]
    
    def research_category(self, category_name):
        """Research a category for article generation"""
        logger.info(f"Researching category: {category_name}")
        
        # Analyze main keyword
        main_analysis = self.analyze_keyword(category_name)
        
        # Get top suggestions for deeper analysis
        deep_keywords = []
        for suggestion in main_analysis['suggestions'][:3]:
            time.sleep(1)
            deep_analysis = self.analyze_keyword(suggestion)
            deep_keywords.append(deep_analysis)
        
        result = {
            'category': category_name,
            'main_keyword': main_analysis,
            'deep_keywords': deep_keywords,
            'all_questions': main_analysis['questions'],
            'all_suggestions': main_analysis['suggestions'],
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        
        # Aggregate all questions
        for deep in deep_keywords:
            result['all_questions'].extend(deep['questions'])
        
        # Remove duplicates
        result['all_questions'] = list(set(result['all_questions']))[:20]
        
        logger.info(f"Category research complete: {len(result['all_questions'])} total questions")
        
        return result


if __name__ == "__main__":
    # Test
    logging.basicConfig(level=logging.INFO)
    
    seo = SEOResearch()
    
    # Test keyword suggestions
    print("\n=== Testing Keyword Suggestions ===")
    suggestions = seo.get_keyword_suggestions("manajemen keuangan sekolah")
    for s in suggestions:
        print(f"  - {s}")
    
    # Test questions
    print("\n=== Testing Questions ===")
    questions = seo.get_related_questions("digitalisasi pendidikan")
    for q in questions:
        print(f"  - {q}")
    
    # Test full analysis
    print("\n=== Testing Full Analysis ===")
    result = seo.analyze_keyword("biaya pendidikan")
    print(f"Suggestions: {len(result['suggestions'])}")
    print(f"Questions: {len(result['questions'])}")
    print(f"Long-tail: {len(result['long_tail'])}")
