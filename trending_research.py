import urllib3
import urllib3.util.retry

# Monkey-patch urllib3 Retry to support old method_whitelist parameter used by pytrends
original_init = urllib3.util.retry.Retry.__init__
def patched_init(self, *args, **kwargs):
    if 'method_whitelist' in kwargs:
        kwargs['allowed_methods'] = kwargs.pop('method_whitelist')
    original_init(self, *args, **kwargs)
urllib3.util.retry.Retry.__init__ = patched_init

from pytrends.request import TrendReq
import logging
from datetime import datetime, timedelta
import time

logger = logging.getLogger(__name__)

class TrendingResearch:
    def __init__(self):
        self.pytrends = None

    def _get_pytrends(self, language='id'):
        hl = 'en-US' if language == 'en' else 'id-ID'
        tz = 360 if language == 'en' else 420
        if not hasattr(self, '_pytrends_cache'):
            self._pytrends_cache = {}
        if language not in self._pytrends_cache:
            self._pytrends_cache[language] = TrendReq(hl=hl, tz=tz, timeout=(10, 25))
        return self._pytrends_cache[language]
    
    def get_trending_topics(self, category_name, limit=10, language='id'):
        """Get trending topics related to category"""
        try:
            results = {
                'category': category_name,
                'trending_now': [],
                'related_rising': [],
                'related_top': [],
                'timestamp': datetime.now().isoformat()
            }
            
            geo = 'US' if language == 'en' else 'ID'
            pn = 'united_states' if language == 'en' else 'indonesia'
            
            # Get related queries for category
            try:
                pytrends = self._get_pytrends(language)
                pytrends.build_payload([category_name], timeframe='now 7-d', geo=geo)
                time.sleep(5)  # Rate limiting
                related = pytrends.related_queries()
                
                if category_name in related:
                    if related[category_name]['rising'] is not None and not related[category_name]['rising'].empty:
                        results['related_rising'] = related[category_name]['rising'].head(limit)['query'].tolist()
                    if related[category_name]['top'] is not None and not related[category_name]['top'].empty:
                        results['related_top'] = related[category_name]['top'].head(limit)['query'].tolist()
            except Exception as e:
                logger.warning(f"Could not get related queries: {e}")
                if hasattr(self, '_pytrends_cache') and language in self._pytrends_cache:
                    del self._pytrends_cache[language] # Reset so it tries to get new cookies next time
            
            # Try to get trending searches (general country trends)
            try:
                trending_searches = self._get_pytrends(language).trending_searches(pn=pn)
                if not trending_searches.empty:
                    results['trending_now'] = trending_searches.head(limit).values.flatten().tolist()
            except Exception as e:
                logger.warning(f"Could not get trending searches: {e}")
                if hasattr(self, '_pytrends_cache') and language in self._pytrends_cache:
                    del self._pytrends_cache[language]
            
            return results
        except Exception as e:
            logger.error(f"Trending research error: {e}")
            return None
    
    def get_interest_over_time(self, keywords, language='id'):
        """Get interest over time for keywords"""
        try:
            geo = 'US' if language == 'en' else 'ID'
            pytrends = self._get_pytrends(language)
            pytrends.build_payload(keywords, timeframe='today 3-m', geo=geo)
            time.sleep(5)
            data = pytrends.interest_over_time()
            
            if data.empty:
                return None
            
            results = []
            for keyword in keywords:
                if keyword in data.columns:
                    avg_interest = data[keyword].mean()
                    current_interest = data[keyword].iloc[-1]
                    trend = 'rising' if current_interest > avg_interest else 'falling'
                    
                    results.append({
                        'keyword': keyword,
                        'current_interest': int(current_interest),
                        'avg_interest': int(avg_interest),
                        'trend': trend
                    })
            
            return results
        except Exception as e:
            logger.error(f"Interest over time error: {e}")
            return None
    
    def suggest_article_topics(self, category_name, count=5, language='id'):
        """Suggest article topics based on trending data"""
        try:
            trending_data = self.get_trending_topics(category_name, limit=20, language=language)
            
            if not trending_data:
                # Fallback: generate generic topics based on category
                return []
            
            suggestions = []
            
            # Prioritize rising queries
            for topic in trending_data['related_rising'][:count]:
                suggestions.append({
                    'topic': topic,
                    'type': 'rising',
                    'category': category_name
                })
            
            # Add top queries if needed
            remaining = count - len(suggestions)
            if remaining > 0:
                for topic in trending_data['related_top'][:remaining]:
                    suggestions.append({
                        'topic': topic,
                        'type': 'popular',
                        'category': category_name
                    })
            
            # If still not enough, use trending now
            remaining = count - len(suggestions)
            if remaining > 0:
                for topic in trending_data['trending_now'][:remaining]:
                    suggestions.append({
                        'topic': topic,
                        'type': 'trending',
                        'category': category_name
                    })
            
            return suggestions if suggestions else []
        except Exception as e:
            logger.error(f"Suggest topics error: {e}")
            return []
    
