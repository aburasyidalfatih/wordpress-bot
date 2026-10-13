import urllib3_compat  # noqa: F401  (must run before pytrends is imported)

try:
    from pytrends.request import TrendReq
except ImportError:
    TrendReq = None
import logging
from datetime import datetime
import time
import re

logger = logging.getLogger(__name__)

class TrendingResearch:
    def __init__(self):
        # One client per language; dropped after a failure so the next call
        # fetches fresh cookies.
        self._pytrends_cache = {}

    def _get_pytrends(self, language='id'):
        if TrendReq is None:
            raise RuntimeError('pytrends provider is not installed')
        hl = 'en-US' if language == 'en' else 'id-ID'
        tz = 360 if language == 'en' else 420
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
                self._pytrends_cache.pop(language, None)

            # Try to get trending searches (general country trends)
            try:
                trending_searches = self._get_pytrends(language).trending_searches(pn=pn)
                if not trending_searches.empty:
                    candidates = trending_searches.values.flatten().tolist()
                    # Country-wide trends are not category evidence by themselves.
                    # Keep only candidates sharing meaningful terms with the category.
                    results['trending_now'] = [
                        topic for topic in candidates
                        if self.is_relevant(topic, category_name)
                    ][:limit]
            except Exception as e:
                logger.warning(f"Could not get trending searches: {e}")
                self._pytrends_cache.pop(language, None)

            return results
        except Exception as e:
            logger.error(f"Trending research error: {e}")
            return None

    @staticmethod
    def _tokens(value):
        stopwords = {'dan', 'atau', 'yang', 'untuk', 'dengan', 'the', 'and', 'for', 'with'}
        return {
            token for token in re.findall(r'[a-z0-9]+', str(value).lower())
            if len(token) > 2 and token not in stopwords
        }

    @classmethod
    def is_relevant(cls, topic, category):
        category_tokens = cls._tokens(category)
        return bool(category_tokens and category_tokens.intersection(cls._tokens(topic)))

    @staticmethod
    def build_topic_suggestions(category_name, trending_data, count=5):
        """Build deterministic, deduplicated suggestions from one trend snapshot."""
        suggestions = []
        seen = set()
        groups = (
            ('rising', (trending_data or {}).get('related_rising', [])),
            ('popular', (trending_data or {}).get('related_top', [])),
            ('trending', (trending_data or {}).get('trending_now', [])),
        )
        for topic_type, topics in groups:
            for topic in topics:
                normalized = ' '.join(str(topic).lower().split())
                if not normalized or normalized in seen:
                    continue
                seen.add(normalized)
                suggestions.append({
                    'topic': str(topic).strip(),
                    'type': topic_type,
                    'category': category_name,
                })
                if len(suggestions) >= count:
                    return suggestions
        return suggestions

    def suggest_article_topics(self, category_name, count=5, language='id'):
        """Suggest article topics based on trending data"""
        try:
            trending_data = self.get_trending_topics(category_name, limit=20, language=language)

            if not trending_data:
                # Fallback: generate generic topics based on category
                return []

            return self.build_topic_suggestions(category_name, trending_data, count)
        except Exception as e:
            logger.error(f"Suggest topics error: {e}")
            return []

