"""
SEO Research Module - Advanced Enterprise Keyword & Competitor Research
Uses open source libraries to perform deep topic analysis.
"""
import urllib3
import urllib3.util.retry

# Monkey-patch urllib3 Retry to support old method_whitelist parameter used by pytrends
original_init = urllib3.util.retry.Retry.__init__
def patched_init(self, *args, **kwargs):
    if 'method_whitelist' in kwargs:
        kwargs['allowed_methods'] = kwargs.pop('method_whitelist')
    original_init(self, *args, **kwargs)
urllib3.util.retry.Retry.__init__ = patched_init

import requests
from bs4 import BeautifulSoup
import json
import time
from urllib.parse import quote_plus
import logging

try:
    from pytrends.request import TrendReq
except ImportError:
    TrendReq = None

try:
    from ddgs import DDGS
except ImportError:
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        DDGS = None

try:
    from youtube_transcript_api import YouTubeTranscriptApi
except ImportError:
    YouTubeTranscriptApi = None

logger = logging.getLogger(__name__)

class SEOResearch:
    """Advanced Research using DDGS, Pytrends, and YouTube Transcripts"""
    
    def __init__(self):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        if DDGS:
            try:
                # Try simple initialization (v6.x compatibility)
                self.ddgs = DDGS()
            except Exception as e:
                logger.warning(f"Failed to initialize DDGS with default arguments: {e}. Trying verify=False fallback.")
                try:
                    # Fallback for older versions if needed
                    self.ddgs = DDGS(verify=True)
                except Exception as ex:
                    logger.error(f"Failed to initialize DDGS: {ex}")
                    self.ddgs = None
        else:
            self.ddgs = None
    
    def get_keyword_suggestions(self, keyword, limit=10, language='id'):
        """Get keyword suggestions from Google Autocomplete"""
        suggestions = []
        try:
            url = f"http://suggestqueries.google.com/complete/search"
            hl = 'en' if language == 'en' else 'id'
            params = {'client': 'firefox', 'q': keyword, 'hl': hl}
            response = requests.get(url, params=params, headers=self.headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if len(data) > 1:
                    suggestions = data[1][:limit]
        except Exception as e:
            logger.error(f"Error getting keyword suggestions: {e}")
        return suggestions

    def get_related_questions(self, keyword, limit=10, language='id'):
        """Generate related questions dynamically via Google Autocomplete using question modifiers"""
        questions = []
        if language == 'en':
            modifiers = ["how to", "what is", "why does", "can you"]
        else:
            modifiers = ["bagaimana cara", "apa itu", "kenapa", "apakah"]
            
        try:
            url = "http://suggestqueries.google.com/complete/search"
            hl = 'en' if language == 'en' else 'id'
            for mod in modifiers:
                query = f"{mod} * {keyword}"
                params = {'client': 'firefox', 'q': query, 'hl': hl}
                response = requests.get(url, params=params, headers=self.headers, timeout=5)
                if response.status_code == 200:
                    data = response.json()
                    if len(data) > 1:
                        # Add valid questions that aren't too short
                        questions.extend([q for q in data[1] if len(q.split()) > 3])
            
            # Remove duplicates while preserving order
            seen = set()
            unique_questions = []
            for q in questions:
                if q not in seen:
                    seen.add(q)
                    unique_questions.append(q)
                    
            if unique_questions:
                return unique_questions[:limit]
        except Exception as e:
            logger.error(f"Error getting dynamic related questions: {e}")
            
        # Fallback to standard hardcoded patterns if API fails or returns nothing
        if language == 'en':
            patterns = [
                f"What is {keyword}?",
                f"How to {keyword}?",
                f"What are the benefits of {keyword}?"
            ]
        else:
            patterns = [
                f"Apa itu {keyword}?",
                f"Bagaimana cara {keyword}?",
                f"Apa manfaat {keyword}?"
            ]
        return patterns[:limit]

    def get_wikipedia_context(self, keyword, language='id'):
        """Extract semantic entities and context from Wikipedia API"""
        try:
            wiki_lang = 'en' if language == 'en' else 'id'
            url = f"https://{wiki_lang}.wikipedia.org/w/api.php"
            params = {
                'action': 'query',
                'format': 'json',
                'prop': 'extracts',
                'exintro': True,
                'explaintext': True,
                'exsentences': 3,
                'titles': keyword
            }
            response = requests.get(url, params=params, headers=self.headers, timeout=5)
            if response.status_code == 200:
                data = response.json()
                pages = data.get('query', {}).get('pages', {})
                for page_id, page_data in pages.items():
                    if page_id != "-1" and 'extract' in page_data:
                        return page_data['extract']
        except Exception as e:
            logger.error(f"Error getting Wikipedia context: {e}")
        return ""

    def get_latest_news(self, keyword, limit=3):
        """Get latest news headlines using DuckDuckGo News"""
        news_headlines = []
        if self.ddgs:
            try:
                results = self.ddgs.news(keyword, max_results=limit)
                for res in results:
                    news_headlines.append(f"{res.get('title', '')} - {res.get('source', '')}")
            except Exception as e:
                logger.error(f"Error getting DDG News: {e}")
        return news_headlines

    def get_trend_score(self, keyword, language='id'):
        """Get interest score from Google Trends using pytrends"""
        score = 50  # Default fallback score
        if not TrendReq:
            return score
            
        try:
            hl = 'en-US' if language == 'en' else 'id-ID'
            geo = 'US' if language == 'en' else 'ID'
            pytrends = TrendReq(hl=hl, tz=360 if language == 'en' else 420, retries=2, backoff_factor=0.5)
            # Use a slightly broader timeframe and just one keyword
            pytrends.build_payload([keyword], cat=0, timeframe='now 7-d', geo=geo)
            data = pytrends.interest_over_time()
            if not data.empty and keyword in data.columns:
                score = int(data[keyword].iloc[-1])
        except Exception as e:
            logger.error(f"Pytrends error for {keyword}: {e}")
            score = 0  # Return 0 when real data is unavailable
            
        return score

    def analyze_competitors(self, keyword, language='id'):
        """Scrape top 3 competitors via DuckDuckGo and extract their headers"""
        competitors = []
        if not self.ddgs:
            return []

        try:
            region = 'us-en' if language == 'en' else 'id-id'
            results = list(self.ddgs.text(keyword, region=region, max_results=3))
            for res in results:
                url = res.get('href')
                title = res.get('title')
                
                # Fetch page content via Jina Reader to bypass Cloudflare
                try:
                    jina_url = f"https://r.jina.ai/{url}"
                    page_resp = requests.get(jina_url, timeout=15)
                    time.sleep(2) # Prevent Jina AI rate limiting
                    if page_resp.status_code == 200:
                        content = page_resp.text
                        import re
                        headers = []
                        for line in content.split('\n'):
                            line = line.strip()
                            # Match Markdown headers ## or ###
                            if line.startswith('## ') or line.startswith('### '):
                                header_text = re.sub(r'^#+\s*', '', line)
                                if 10 < len(header_text) < 100:
                                    headers.append(header_text)
                                    if len(headers) >= 5:
                                        break
                        
                        competitors.append({
                            'url': url,
                            'title': title,
                            'headers': headers if headers else [title]
                        })
                except Exception as ex:
                    logger.warning(f"Failed to scrape competitor {url} via Jina: {ex}")
                    continue
        except Exception as e:
            logger.error(f"DDGS competitor search error: {e}")
            return []

        return competitors

    def get_social_insights(self, keyword, language='id'):
        """Search Quora & Reddit for real human questions"""
        insights = []
        if not self.ddgs:
            return []

        try:
            query = f"site:quora.com OR site:reddit.com {keyword}"
            region = 'us-en' if language == 'en' else 'id-id'
            results = list(self.ddgs.text(query, region=region, max_results=5))
            for res in results:
                title = res.get('title', '')
                if language == 'en':
                    if '?' in title or 'how' in title.lower() or 'what' in title.lower() or 'why' in title.lower():
                        insights.append(title)
                else:
                    if '?' in title or 'bagaimana' in title.lower() or 'apa' in title.lower():
                        insights.append(title)
        except Exception as e:
            logger.error(f"DDGS social insights error: {e}")
            return []
            
        return list(set(insights))[:5] if insights else self._get_fallback_social(keyword, language)

    def get_youtube_insights(self, keyword, language='id'):
        """Find top YouTube video and get transcript summary"""
        insights = []
        if not self.ddgs or not YouTubeTranscriptApi:
            return []

        try:
            query = f"site:youtube.com {keyword}"
            region = 'us-en' if language == 'en' else 'id-id'
            results = list(self.ddgs.text(query, region=region, max_results=2))
            
            for res in results:
                url = res.get('href', '')
                import re
                match = re.search(r'(?:v=|\/)([0-9A-Za-z_-]{11}).*', url)
                if match:
                    video_id = match.group(1)
                    try:
                        langs = ['en', 'id'] if language == 'en' else ['id', 'en']
                        transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=langs)
                        # Take just snippets from first 3 minutes
                        text_snippets = [t['text'] for t in transcript[:20]]
                        insights.append({
                            'video_id': video_id,
                            'title': res.get('title'),
                            'snippets': " ".join(text_snippets[:5]) + "..."
                        })
                    except Exception as ex:
                        logger.warning(f"No transcript for video {video_id}: {ex}")
                        snippets_text = f"Video tutorial about {keyword}. Please watch the video for a complete visual explanation..." if language == 'en' else f"Video tutorial seputar {keyword}. Silakan tonton video untuk penjelasan visual secara lengkap..."
                        insights.append({
                            'video_id': video_id,
                            'title': res.get('title'),
                            'snippets': snippets_text
                        })
        except Exception as e:
            logger.error(f"Youtube insights error: {e}")
            return []

        return insights

    def research_category(self, category_name, language='id'):
        """Deep Research a category including competitors, social, and youtube"""
        logger.info(f"Advanced Researching category: {category_name} with language={language}")
        
        try:
            from rq import get_current_job
            job = get_current_job()
        except ImportError:
            job = None
            
        def update_progress(prog, msg):
            if job:
                job.meta['progress'] = prog
                job.meta['message'] = msg
                job.save_meta()
                
        update_progress(20, f'Fetching keyword suggestions for {category_name}...')
        # 1. Basic Keyword Suggestions
        suggestions = self.get_keyword_suggestions(category_name, limit=10, language=language)
        
        update_progress(35, f'Analyzing Google Trends for {category_name}...')
        # 2. Trend Score
        trend_score = self.get_trend_score(category_name, language=language)
        
        update_progress(50, f'Scraping top competitors for {category_name}...')
        # 3. Competitor Analysis
        competitor_outlines = self.analyze_competitors(category_name, language=language)
        
        update_progress(65, f'Listening to social forums for {category_name}...')
        # 4. Social Listening
        social_insights = self.get_social_insights(category_name, language=language)
        
        update_progress(80, f'Extracting YouTube insights for {category_name}...')
        # 5. YouTube Insights
        youtube_insights = self.get_youtube_insights(category_name, language=language)
        
        update_progress(90, f'Finding related questions for {category_name}...')
        # 6. Questions
        questions = self.get_related_questions(category_name, limit=10, language=language)
        
        update_progress(95, f'Extracting Semantic Entities and News for {category_name}...')
        # 7. Wikipedia & News
        semantic_context = self.get_wikipedia_context(category_name, language=language)
        news_insights = self.get_latest_news(category_name, limit=3)
        
        result = {
            'category': category_name,
            'suggestions': suggestions,
            'trend_score': trend_score,
            'competitor_outlines': competitor_outlines,
            'social_insights': social_insights,
            'youtube_insights': youtube_insights,
            'questions': questions,
            'semantic_context': semantic_context,
            'news_insights': news_insights,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        
        logger.info(f"Category research complete: Trend={trend_score}, Competitors={len(competitor_outlines)}")
        
        return result

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    seo = SEOResearch()
    print("Testing advanced research...")
    res = seo.research_category("bisnis online")
    print(json.dumps(res, indent=2))
