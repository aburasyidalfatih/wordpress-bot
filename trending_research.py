from pytrends.request import TrendReq
import logging
from datetime import datetime, timedelta
import time

logger = logging.getLogger(__name__)

class TrendingResearch:
    def __init__(self):
        self.pytrends = TrendReq(hl='id-ID', tz=420, timeout=(10, 25))  # Indonesia timezone
    
    def get_trending_topics(self, category_name, limit=10):
        """Get trending topics related to category"""
        try:
            results = {
                'category': category_name,
                'trending_now': [],
                'related_rising': [],
                'related_top': [],
                'timestamp': datetime.now().isoformat()
            }
            
            # Get related queries for category
            try:
                self.pytrends.build_payload([category_name], timeframe='now 7-d', geo='ID')
                time.sleep(1)  # Rate limiting
                related = self.pytrends.related_queries()
                
                if category_name in related:
                    if related[category_name]['rising'] is not None and not related[category_name]['rising'].empty:
                        results['related_rising'] = related[category_name]['rising'].head(limit)['query'].tolist()
                    if related[category_name]['top'] is not None and not related[category_name]['top'].empty:
                        results['related_top'] = related[category_name]['top'].head(limit)['query'].tolist()
            except Exception as e:
                logger.warning(f"Related queries error for {category_name}: {e}")
            
            # Try to get trending searches (general Indonesia trends)
            try:
                trending = self.pytrends.trending_searches(pn='indonesia')
                if not trending.empty:
                    results['trending_now'] = trending.head(limit).values.flatten().tolist()
            except Exception as e:
                logger.warning(f"Trending searches error: {e}")
            
            return results
        except Exception as e:
            logger.error(f"Trending research error: {e}")
            return None
    
    def get_interest_over_time(self, keywords):
        """Get interest over time for keywords"""
        try:
            self.pytrends.build_payload(keywords, timeframe='today 3-m', geo='ID')
            time.sleep(1)
            data = self.pytrends.interest_over_time()
            
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
    
    def suggest_article_topics(self, category_name, count=5):
        """Suggest article topics based on trending data"""
        try:
            trending_data = self.get_trending_topics(category_name, limit=20)
            
            if not trending_data:
                # Fallback: generate generic topics based on category
                return self._generate_fallback_topics(category_name, count)
            
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
            
            return suggestions if suggestions else self._generate_fallback_topics(category_name, count)
        except Exception as e:
            logger.error(f"Suggest topics error: {e}")
            return self._generate_fallback_topics(category_name, count)
    
    def _generate_fallback_topics(self, category_name, count=5):
        """Generate fallback topics when API fails"""
        fallback_map = {
            'Digitalisasi Pendidikan': [
                'Implementasi AI dalam pembelajaran',
                'Platform LMS terbaik untuk sekolah',
                'Digitalisasi administrasi sekolah',
                'E-learning untuk pendidikan Indonesia',
                'Teknologi pendidikan terkini'
            ],
            'Strategi Pemasaran': [
                'Digital marketing untuk sekolah',
                'Social media strategy pendidikan',
                'SEO untuk website sekolah',
                'Content marketing lembaga pendidikan',
                'Branding sekolah di era digital'
            ],
            'Pengembangan Kurikulum': [
                'Implementasi Kurikulum Merdeka',
                'Pembelajaran berbasis proyek',
                'Assessment autentik',
                'Diferensiasi pembelajaran',
                'Kurikulum abad 21'
            ],
            'Manajemen Keuangan': [
                'Software akuntansi sekolah',
                'Budgeting pendidikan',
                'Transparansi keuangan lembaga',
                'Manajemen kas sekolah',
                'Pelaporan keuangan pendidikan'
            ],
            'Hotnews Pendidikan': [
                'Viral: Inovasi pendidikan yang menginspirasi',
                'Trending: Kebijakan pendidikan terbaru',
                'Hot topic: Fenomena viral di dunia pendidikan',
                'Breaking news: Prestasi siswa Indonesia',
                'Viral story: Guru inspiratif yang mengubah pendidikan'
            ],
            'Biaya Pendidikan': [
                'Biaya masuk sekolah swasta terbaik di Jakarta',
                'Panduan lengkap biaya kuliah universitas negeri',
                'Info PSB: Biaya pendaftaran sekolah favorit',
                'Perbandingan biaya sekolah internasional',
                'Beasiswa dan bantuan biaya pendidikan'
            ]
        }
        
        topics = fallback_map.get(category_name, [
            f'Panduan {category_name}',
            f'Tips {category_name}',
            f'Strategi {category_name}',
            f'Best practices {category_name}',
            f'Implementasi {category_name}'
        ])
        
        return [{'topic': t, 'type': 'fallback', 'category': category_name} for t in topics[:count]]
