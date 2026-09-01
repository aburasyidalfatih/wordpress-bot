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
import json
import time
import logging
from datetime import datetime, timezone

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
        self.source_status = {}

    def _mark_source(self, provider, status, **details):
        self.source_status[provider] = {
            'status': status,
            'checked_at': datetime.now(timezone.utc).isoformat(),
            **details,
        }

    @staticmethod
    def _deduplicate(values, key=None):
        seen = set()
        output = []
        for value in values or []:
            raw = key(value) if key else value
            normalized = ' '.join(str(raw or '').lower().split())
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            output.append(value)
        return output
    
    def get_keyword_suggestions(self, keyword, limit=10, language='id'):
        """Get keyword suggestions from Google Autocomplete"""
        suggestions = []
        try:
            url = "https://suggestqueries.google.com/complete/search"
            hl = 'en' if language == 'en' else 'id'
            params = {'client': 'firefox', 'q': keyword, 'hl': hl}
            response = requests.get(url, params=params, headers=self.headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if len(data) > 1:
                    suggestions = data[1][:limit]
                    self._mark_source('google_autocomplete', 'real', count=len(suggestions))
        except Exception as e:
            logger.error(f"Error getting keyword suggestions: {e}")
            
        if not suggestions:
            # Fallback if Google Autocomplete fails or yields nothing
            if language == 'en':
                suggestions = [
                    f"best {keyword}", f"{keyword} tips", f"{keyword} tutorial", 
                    f"how to start with {keyword}", f"{keyword} for beginners"
                ]
            else:
                suggestions = [
                    f"tips {keyword}", f"panduan {keyword}", f"belajar {keyword}",
                    f"cara memulai {keyword}", f"{keyword} untuk pemula"
                ]
            self._mark_source('google_autocomplete', 'fallback', count=len(suggestions))
        return suggestions[:limit]

    def get_related_questions(self, keyword, limit=10, language='id'):
        """Generate related questions dynamically via Google Autocomplete using question modifiers"""
        questions = []
        if language == 'en':
            modifiers = ["how to", "what is", "why does", "can you"]
        else:
            modifiers = ["bagaimana cara", "apa itu", "kenapa", "apakah"]
            
        try:
            url = "https://suggestqueries.google.com/complete/search"
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
                self._mark_source('related_questions', 'real', count=len(unique_questions[:limit]))
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
        self._mark_source('related_questions', 'fallback', count=len(patterns[:limit]))
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
                        self._mark_source('wikipedia', 'real', count=1)
                        return page_data['extract']
        except Exception as e:
            logger.error(f"Error getting Wikipedia context: {e}")
        self._mark_source('wikipedia', 'unavailable', count=0)
        return ""

    def get_latest_news(self, keyword, limit=3):
        """Get latest news headlines using DuckDuckGo News"""
        news_headlines = []
        if self.ddgs:
            try:
                results = self.ddgs.news(keyword, max_results=limit)
                for res in results:
                    news_headlines.append({
                        'title': res.get('title', ''),
                        'source': res.get('source', ''),
                        'url': res.get('url') or res.get('href', ''),
                        'published_at': res.get('date'),
                    })
            except Exception as e:
                logger.error(f"Error getting DDG News: {e}")
        self._mark_source('news', 'real' if news_headlines else 'unavailable', count=len(news_headlines))
        return news_headlines

    def get_trend_analysis(self, keyword, language='id'):
        """Return an auditable score based on level, momentum, and stability."""
        if not TrendReq:
            self._mark_source('google_trends', 'unavailable', reason='pytrends_not_installed')
            return {'score': None, 'current': None, 'average': None, 'growth': None,
                    'volatility': None, 'status': 'unavailable'}
            
        try:
            hl = 'en-US' if language == 'en' else 'id-ID'
            geo = 'US' if language == 'en' else 'ID'
            pytrends = TrendReq(hl=hl, tz=360 if language == 'en' else 420, retries=2, backoff_factor=0.5)
            # Use a slightly broader timeframe and just one keyword
            pytrends.build_payload([keyword], cat=0, timeframe='now 7-d', geo=geo)
            data = pytrends.interest_over_time()
            if not data.empty and keyword in data.columns:
                values = [float(v) for v in data[keyword].tolist()]
                recent = values[-min(24, len(values)):]
                current = sum(recent[-min(4, len(recent)):]) / min(4, len(recent))
                average = sum(recent) / len(recent)
                midpoint = max(1, len(recent) // 2)
                previous = sum(recent[:midpoint]) / midpoint
                latest = sum(recent[midpoint:]) / max(1, len(recent) - midpoint)
                growth = ((latest - previous) / max(previous, 1.0)) * 100
                variance = sum((v - average) ** 2 for v in recent) / len(recent)
                volatility = variance ** 0.5
                momentum = max(0.0, min(100.0, 50.0 + growth))
                stability = max(0.0, 100.0 - volatility)
                score = round((current * .45) + (average * .25) +
                              (momentum * .20) + (stability * .10))
                self._mark_source('google_trends', 'real', samples=len(recent))
                return {
                    'score': max(0, min(100, score)),
                    'current': round(current, 1),
                    'average': round(average, 1),
                    'growth': round(growth, 1),
                    'volatility': round(volatility, 1),
                    'status': 'real',
                }
        except Exception as e:
            logger.error(f"Pytrends error for {keyword}: {e}")
            self._mark_source('google_trends', 'unavailable', reason=type(e).__name__)
        return {'score': None, 'current': None, 'average': None, 'growth': None,
                'volatility': None, 'status': 'unavailable'}

    def get_trend_score(self, keyword, language='id'):
        """Backward-compatible score accessor; zero means unavailable, never fake average."""
        return self.get_trend_analysis(keyword, language).get('score') or 0

    def analyze_competitors(self, keyword, language='id'):
        """Scrape top 3 competitors via DuckDuckGo and extract their headers"""
        competitors = []
        if not self.ddgs:
            self._mark_source('competitors', 'unavailable', count=0)
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
                            'headers': headers if headers else [title],
                            'retrieved_via': 'duckduckgo+jina',
                        })
                except Exception as ex:
                    logger.warning(f"Failed to scrape competitor {url} via Jina: {ex}")
                    continue
        except Exception as e:
            logger.error(f"DDGS competitor search error: {e}")
            self._mark_source('competitors', 'unavailable', count=0, reason=type(e).__name__)
            return []

        competitors = self._deduplicate(competitors, key=lambda item: item.get('url'))
        self._mark_source('competitors', 'real' if competitors else 'unavailable', count=len(competitors))
        return competitors

    def get_social_insights(self, keyword, language='id'):
        """Search Quora & Reddit for real human questions"""
        insights = []
        if not self.ddgs:
            self._mark_source('social', 'unavailable', count=0)
            return []

        try:
            query = f"site:quora.com OR site:reddit.com {keyword}"
            region = 'us-en' if language == 'en' else 'id-id'
            results = list(self.ddgs.text(query, region=region, max_results=5))
            for res in results:
                title = res.get('title', '')
                if language == 'en':
                    if '?' in title or 'how' in title.lower() or 'what' in title.lower() or 'why' in title.lower():
                        insights.append({'text': title, 'url': res.get('href', ''), 'provider': 'quora_or_reddit'})
                else:
                    if '?' in title or 'bagaimana' in title.lower() or 'apa' in title.lower():
                        insights.append({'text': title, 'url': res.get('href', ''), 'provider': 'quora_or_reddit'})
        except Exception as e:
            logger.error(f"DDGS social insights error: {e}")
            self._mark_source('social', 'unavailable', count=0, reason=type(e).__name__)
            return []
            
        insights = self._deduplicate(insights, key=lambda item: item.get('text'))[:5]
        self._mark_source('social', 'real' if insights else 'unavailable', count=len(insights))
        return insights

    def _get_fallback_social(self, keyword, language='id'):
        """Kept for compatibility; fabricated social evidence is intentionally disabled."""
        return []

    def get_youtube_insights(self, keyword, language='id'):
        """Find top YouTube video and get transcript summary"""
        insights = []
        if not self.ddgs or not YouTubeTranscriptApi:
            self._mark_source('youtube', 'unavailable', count=0)
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
                            'url': url,
                            'snippets': " ".join(text_snippets[:5]) + "...",
                            'transcript_available': True,
                        })
                    except Exception as ex:
                        logger.warning(f"No transcript for video {video_id}: {ex}")
                        insights.append({
                            'video_id': video_id,
                            'title': res.get('title'),
                            'url': url,
                            'snippets': '',
                            'transcript_available': False,
                        })
        except Exception as e:
            logger.error(f"Youtube insights error: {e}")
            self._mark_source('youtube', 'unavailable', count=0, reason=type(e).__name__)
            return []

        insights = self._deduplicate(insights, key=lambda item: item.get('video_id'))
        transcript_count = sum(1 for item in insights if item.get('transcript_available'))
        self._mark_source('youtube', 'real' if transcript_count else 'partial',
                          count=len(insights), transcripts=transcript_count)
        return insights

    @staticmethod
    def build_long_tail_keywords(category_name, suggestions, questions, limit=15):
        candidates = list(suggestions or []) + list(questions or [])
        long_tail = []
        seen = set()
        for candidate in candidates:
            text = ' '.join(str(candidate).split()).strip()
            normalized = text.lower()
            if len(text.split()) < 4 or normalized in seen:
                continue
            seen.add(normalized)
            long_tail.append(text)
            if len(long_tail) >= limit:
                break
        return long_tail

    @staticmethod
    def evaluate_quality(source_status, competitor_count=0, transcript_count=0,
                         suggestion_count=0, question_count=0):
        """Score evidence quality, not popularity. Returns 0..100 and a label."""
        weights = {
            'google_trends': 25,
            'google_autocomplete': 15,
            'related_questions': 10,
            'competitors': 20,
            'social': 10,
            'youtube': 10,
            'news': 5,
            'wikipedia': 5,
        }
        score = 0.0
        real_providers = 0
        fallback_providers = []
        for provider, weight in weights.items():
            status = (source_status.get(provider) or {}).get('status', 'unavailable')
            if status == 'real':
                score += weight
                real_providers += 1
            elif status == 'partial':
                score += weight * .5
            elif status == 'fallback':
                score += weight * .15
                fallback_providers.append(provider)

        # Reward useful depth but cap each bonus so quantity cannot mask bad sources.
        score += min(5, competitor_count * 2)
        score += min(3, transcript_count * 1.5)
        score += min(4, suggestion_count * .4)
        score += min(3, question_count * .3)
        score = max(0, min(100, round(score)))

        if score >= 75 and real_providers >= 5:
            confidence = 'high'
        elif score >= 50 and real_providers >= 3:
            confidence = 'medium'
        elif score >= 35 and real_providers >= 2:
            confidence = 'low'
        else:
            confidence = 'insufficient'
        return {
            'score': score,
            'confidence': confidence,
            'real_provider_count': real_providers,
            'fallback_providers': fallback_providers,
            'passes_minimum': confidence != 'insufficient',
        }

    def research_category(self, category_name, language='id'):
        """Deep Research a category including competitors, social, and youtube"""
        logger.info(f"Advanced Researching category: {category_name} with language={language}")
        self.source_status = {}
        
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
        trend_analysis = self.get_trend_analysis(category_name, language=language)
        trend_score = trend_analysis.get('score') or 0
        
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
        long_tail_keywords = self.build_long_tail_keywords(category_name, suggestions, questions)
        transcript_count = sum(1 for item in youtube_insights if item.get('transcript_available'))
        quality = self.evaluate_quality(
            self.source_status,
            competitor_count=len(competitor_outlines),
            transcript_count=transcript_count,
            suggestion_count=len(suggestions),
            question_count=len(questions),
        )
        
        result = {
            'category': category_name,
            'suggestions': suggestions,
            'trend_score': trend_score,
            'trend_analysis': trend_analysis,
            'competitor_outlines': competitor_outlines,
            'social_insights': social_insights,
            'youtube_insights': youtube_insights,
            'questions': questions,
            'long_tail_keywords': long_tail_keywords,
            'semantic_context': semantic_context,
            'news_insights': news_insights,
            'source_metadata': self.source_status,
            'quality': quality,
            'timestamp': datetime.now(timezone.utc).isoformat(),
        }
        
        logger.info(f"Category research complete: Trend={trend_score}, Competitors={len(competitor_outlines)}")
        
        return result

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    seo = SEOResearch()
    print("Testing advanced research...")
    res = seo.research_category("bisnis online")
    print(json.dumps(res, indent=2))
