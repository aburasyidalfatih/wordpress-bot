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

import os
import re
import time
import requests
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from threading import Lock

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

# Google Trends seasonality lookup doubles the request rate per category. Enable
# with ENABLE_TREND_SEASONALITY=true only if your Trends quota tolerates it.
ENABLE_TREND_SEASONALITY = os.getenv('ENABLE_TREND_SEASONALITY', 'false').lower() == 'true'

# DuckDuckGo rate-limits per IP. Competitors, social, YouTube and news all go
# through it, so they are spaced out rather than fired together.
DDG_CALL_SPACING_SECONDS = float(os.getenv('DDG_CALL_SPACING_SECONDS', '3'))


class SEOResearch:
    """Advanced Research using DDGS, Pytrends, and YouTube Transcripts"""
    
    def __init__(self):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        self.ddgs_available = DDGS is not None
        self.source_status = {}
        self._status_lock = Lock()

    def _new_ddgs(self):
        """Create a fresh DDGS client for a single call.

        The client is not thread-safe and latches into a failed state: once one
        call errors, every later call on the same instance raises "Exception
        occurred in previous call". A single shared instance was fine while the
        providers ran sequentially, but they now run concurrently, so one failure
        took out competitors, social, YouTube and news together — 45 of the 100
        quality points, which is enough to drop every category.
        """
        if not DDGS:
            return None
        try:
            return DDGS()
        except Exception as e:
            logger.error(f"Failed to initialize DDGS: {e}")
            return None

    def _run_providers(self, independent, duckduckgo, label=''):
        """Run providers grouped by the upstream they hit.

        `independent` targets distinct hosts (Google autocomplete, Wikipedia,
        Trends) and can safely run at once. `duckduckgo` all share one host that
        rate-limits per IP, so firing them concurrently looks like a burst and gets
        the whole server blocked; they run one at a time with a gap between them.
        The two groups still overlap with each other.
        """
        collected = {}

        def run_duckduckgo_group():
            for index, (name, fn) in enumerate(duckduckgo.items()):
                if index:
                    time.sleep(DDG_CALL_SPACING_SECONDS)
                try:
                    collected[name] = fn()
                except Exception as exc:
                    logger.error(f"Research provider '{name}' failed{label}: {exc}")
                    collected[name] = None

        with ThreadPoolExecutor(max_workers=len(independent) + 1) as pool:
            futures = {pool.submit(fn): name for name, fn in independent.items()}
            ddg_future = pool.submit(run_duckduckgo_group) if duckduckgo else None

            for future in as_completed(list(futures)):
                name = futures[future]
                try:
                    collected[name] = future.result()
                except Exception as exc:
                    logger.error(f"Research provider '{name}' failed{label}: {exc}")
                    collected[name] = None

            if ddg_future:
                try:
                    ddg_future.result()
                except Exception as exc:
                    logger.error(f"DuckDuckGo provider group failed{label}: {exc}")

        return collected

    def _mark_source(self, provider, status, **details):
        # Called concurrently by the parallel providers.
        with self._status_lock:
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
        ddgs = self._new_ddgs()
        if ddgs:
            try:
                results = ddgs.news(keyword, max_results=limit)
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
            # Short window drives the momentum score.
            pytrends.build_payload([keyword], cat=0, timeframe='now 7-d', geo=geo)
            data = pytrends.interest_over_time()

            # A 12-month pass detects seasonality, but it doubles the number of
            # Google Trends requests. Trends throttles aggressively, and a 429 costs
            # the category 25 quality points, which is enough to push it below the
            # evidence threshold and drop it entirely. Off unless explicitly enabled.
            seasonality = None
            if ENABLE_TREND_SEASONALITY:
                seasonality = self._get_seasonality(pytrends, keyword, geo)
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
                    'seasonality': seasonality,
                }
        except Exception as e:
            logger.error(f"Pytrends error for {keyword}: {e}")
            self._mark_source('google_trends', 'unavailable', reason=type(e).__name__)
        return {'score': None, 'current': None, 'average': None, 'growth': None,
                'volatility': None, 'status': 'unavailable'}

    @staticmethod
    def _get_seasonality(pytrends, keyword, geo):
        """Detect recurring demand from a 12-month interest curve.

        Returns the peak months and whether the topic looks seasonal, so a topic
        can be scheduled when demand actually rises rather than at random.
        """
        try:
            pytrends.build_payload([keyword], cat=0, timeframe='today 12-m', geo=geo)
            yearly = pytrends.interest_over_time()
            if yearly.empty or keyword not in yearly.columns:
                return None

            by_month = {}
            for timestamp, value in yearly[keyword].items():
                by_month.setdefault(timestamp.month, []).append(float(value))
            monthly_avg = {m: sum(v) / len(v) for m, v in by_month.items() if v}
            if len(monthly_avg) < 6:
                return None

            overall = sum(monthly_avg.values()) / len(monthly_avg)
            if overall <= 0:
                return None
            peak_months = sorted(
                (m for m, v in monthly_avg.items() if v >= overall * 1.3),
                key=lambda m: monthly_avg[m], reverse=True
            )[:3]
            spread = max(monthly_avg.values()) - min(monthly_avg.values())
            return {
                'is_seasonal': bool(peak_months) and spread >= overall * .5,
                'peak_months': peak_months,
                'monthly_average': {str(m): round(v, 1) for m, v in sorted(monthly_avg.items())},
            }
        except Exception as e:
            logger.warning(f"Seasonality lookup failed for '{keyword}': {e}")
            return None

    def get_trend_score(self, keyword, language='id'):
        """Backward-compatible score accessor; zero means unavailable, never fake average."""
        return self.get_trend_analysis(keyword, language).get('score') or 0

    def _scrape_competitor(self, url, title):
        """Fetch one competitor page and extract its structure.

        Captures word count, full heading outline and any visible date, so callers
        can judge how thorough and how current the competing page is.
        """
        try:
            page_resp = requests.get(f"https://r.jina.ai/{url}", timeout=20)
        except Exception as ex:
            logger.warning(f"Failed to fetch competitor {url}: {ex}")
            return None

        if page_resp.status_code == 429:
            logger.warning(f"Jina Reader rate-limited while fetching {url}; skipping.")
            return None
        if page_resp.status_code != 200:
            logger.warning(f"Competitor fetch for {url} returned {page_resp.status_code}")
            return None

        content = page_resp.text
        headers = []
        for line in content.split('\n'):
            line = line.strip()
            if line.startswith('## ') or line.startswith('### '):
                header_text = re.sub(r'^#+\s*', '', line).strip()
                if 10 < len(header_text) < 120:
                    headers.append(header_text)
            if len(headers) >= 15:
                break

        word_count = len(re.findall(r'\w+', content))
        published = None
        date_match = re.search(
            r'\b(20\d{2}-\d{2}-\d{2})\b|\b(\d{1,2}\s+\w+\s+20\d{2})\b', content[:4000]
        )
        if date_match:
            published = date_match.group(0)

        return {
            'url': url,
            'title': title,
            'headers': headers if headers else [title],
            'heading_count': len(headers),
            'word_count': word_count,
            'published_hint': published,
            'retrieved_via': 'duckduckgo+jina',
        }

    def analyze_competitors(self, keyword, language='id', limit=4):
        """Scrape the top competitors via DuckDuckGo and extract their structure.

        Pages are fetched concurrently: previously this ran serially with a 2 second
        sleep between each, which dominated the runtime of a whole research pass.
        """
        competitors = []
        ddgs = self._new_ddgs()
        if not ddgs:
            self._mark_source('competitors', 'unavailable', count=0)
            return []

        try:
            region = 'us-en' if language == 'en' else 'id-id'
            results = list(ddgs.text(keyword, region=region, max_results=limit))
        except Exception as e:
            logger.error(f"DDGS competitor search error: {e}")
            self._mark_source('competitors', 'unavailable', count=0, reason=type(e).__name__)
            return []

        targets = [(r.get('href'), r.get('title')) for r in results if r.get('href')]
        if targets:
            with ThreadPoolExecutor(max_workers=min(4, len(targets))) as pool:
                futures = {pool.submit(self._scrape_competitor, url, title): url
                           for url, title in targets}
                for future in as_completed(futures):
                    try:
                        result = future.result()
                    except Exception as ex:
                        logger.warning(f"Competitor scrape failed for {futures[future]}: {ex}")
                        continue
                    if result:
                        competitors.append(result)

        competitors = self._deduplicate(competitors, key=lambda item: item.get('url'))
        self._mark_source('competitors', 'real' if competitors else 'unavailable', count=len(competitors))
        return competitors

    def get_social_insights(self, keyword, language='id'):
        """Search Quora & Reddit for real human questions"""
        insights = []
        ddgs = self._new_ddgs()
        if not ddgs:
            self._mark_source('social', 'unavailable', count=0)
            return []

        try:
            query = f"site:quora.com OR site:reddit.com {keyword}"
            region = 'us-en' if language == 'en' else 'id-id'
            results = list(ddgs.text(query, region=region, max_results=5))
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
        ddgs = self._new_ddgs()
        if not ddgs or not YouTubeTranscriptApi:
            self._mark_source('youtube', 'unavailable', count=0)
            return []

        try:
            query = f"site:youtube.com {keyword}"
            region = 'us-en' if language == 'en' else 'id-id'
            results = list(ddgs.text(query, region=region, max_results=2))
            
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
        # Weighted by how much each source actually contributes to writing the
        # article, not merely by whether it responded.
        #
        # Google Trends previously carried 25 — the largest share — but it returns a
        # popularity score, not material you can write from. Autocomplete and related
        # questions return the actual phrasing people search and the questions they
        # ask, which become keywords and section headings, so they now carry more.
        #
        # These total 85. The remaining 15 is Search Console, added by the caller,
        # because it is first-party evidence the research module cannot see.
        weights = {
            'google_autocomplete': 20,
            'competitors': 20,
            'related_questions': 15,
            'google_trends': 10,
            'social': 8,
            'youtube': 5,
            'news': 4,
            'wikipedia': 3,
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

    def research_topic(self, topic, category_name=None, language='id'):
        """Focused research for one specific article topic.

        research_category() researches a broad category name, which produces generic
        evidence for a specific article. This runs the same providers against the
        actual title/topic, so the article is written against evidence for what it
        is really about. Cheaper than a full category pass: no Trends, no news.
        """
        logger.info(f"Topic-level research: '{topic}' (category={category_name})")
        self.source_status = {}

        collected = self._run_providers(
            independent={
                'suggestions': lambda: self.get_keyword_suggestions(topic, limit=10, language=language),
                'questions': lambda: self.get_related_questions(topic, limit=8, language=language),
            },
            duckduckgo={
                'competitors': lambda: self.analyze_competitors(topic, language=language, limit=3),
                'social': lambda: self.get_social_insights(topic, language=language),
            },
            label=f" for '{topic}'",
        )

        suggestions = collected.get('suggestions') or []
        questions = collected.get('questions') or []

        autocomplete_is_fallback = (self.source_status.get('google_autocomplete') or {}).get('status') == 'fallback'
        questions_are_fallback = (self.source_status.get('related_questions') or {}).get('status') == 'fallback'

        return {
            'topic': topic,
            'category': category_name,
            'keywords': [] if autocomplete_is_fallback else suggestions,
            'questions': [] if questions_are_fallback else questions,
            'competitor_outlines': collected.get('competitors') or [],
            'social_insights': collected.get('social') or [],
            'long_tail_keywords': self.build_long_tail_keywords(topic, suggestions, questions),
            'source_metadata': self.source_status,
            'timestamp': datetime.now(timezone.utc).isoformat(),
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
                
        update_progress(30, f'Gathering evidence for {category_name}...')
        collected = self._run_providers(
            independent={
                'suggestions': lambda: self.get_keyword_suggestions(category_name, limit=10, language=language),
                'trend_analysis': lambda: self.get_trend_analysis(category_name, language=language),
                'questions': lambda: self.get_related_questions(category_name, limit=10, language=language),
                'wikipedia': lambda: self.get_wikipedia_context(category_name, language=language),
            },
            duckduckgo={
                'competitors': lambda: self.analyze_competitors(category_name, language=language),
                'social': lambda: self.get_social_insights(category_name, language=language),
                'youtube': lambda: self.get_youtube_insights(category_name, language=language),
                'news': lambda: self.get_latest_news(category_name, limit=3),
            },
            label=f" for {category_name}",
        )
        update_progress(90, f'Scoring evidence for {category_name}...')

        suggestions = collected.get('suggestions') or []
        trend_analysis = collected.get('trend_analysis') or {'score': None, 'status': 'unavailable'}
        trend_score = trend_analysis.get('score') or 0
        competitor_outlines = collected.get('competitors') or []
        social_insights = collected.get('social') or []
        youtube_insights = collected.get('youtube') or []
        questions = collected.get('questions') or []
        semantic_context = collected.get('wikipedia') or ''
        news_insights = collected.get('news') or []

        update_progress(95, f'Scoring evidence for {category_name}...')
        long_tail_keywords = self.build_long_tail_keywords(category_name, suggestions, questions)

        # Keywords produced by the offline fallback are invented, not observed. They
        # are fine as UI hints but must not reach the article generator, which is now
        # under an evidence policy.
        autocomplete_is_fallback = (self.source_status.get('google_autocomplete') or {}).get('status') == 'fallback'
        questions_are_fallback = (self.source_status.get('related_questions') or {}).get('status') == 'fallback'
        evidence_suggestions = [] if autocomplete_is_fallback else suggestions
        evidence_questions = [] if questions_are_fallback else questions
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
            # Only observed evidence is passed to the generator; see above.
            'evidence_suggestions': evidence_suggestions,
            'evidence_questions': evidence_questions,
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
