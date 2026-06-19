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
                time.sleep(1)  # Rate limiting
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
            time.sleep(1)
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
                return self._generate_fallback_topics(category_name, count, language=language)
            
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
            
            return suggestions if suggestions else self._generate_fallback_topics(category_name, count, language=language)
        except Exception as e:
            logger.error(f"Suggest topics error: {e}")
            return self._generate_fallback_topics(category_name, count, language=language)
    
    def _generate_fallback_topics(self, category_name, count=5, language='id'):
        """Generate fallback topics when API fails"""
        if language == 'en':
            fallback_map = {
                'Digital Education': [
                    'Implementing AI in learning',
                    'Best LMS platforms for schools',
                    'Digitalization of school administration',
                    'E-learning for modern education',
                    'Latest education technology'
                ],
                'Marketing Strategy': [
                    'School digital marketing tips',
                    'Social media strategy for schools',
                    'School branding strategies',
                    'Effective student recruitment',
                    'School website SEO'
                ],
                'Curriculum Development': [
                    'Modern curriculum implementation',
                    'Student-centered learning models',
                    'Innovative assessment methods',
                    'Teacher professional training',
                    'In-house teacher training guides'
                ],
                'Financial Management': [
                    'School financial management best practices',
                    'Educational budgeting templates',
                    'Financial transparency in schools',
                    'Accounting software for education',
                    'Financial compliance guidelines'
                ],
                'Legality and Licensing': [
                    'School operational permit guides',
                    'Accreditation preparation checklist',
                    'Educational compliance tips',
                    'School legal documentation'
                ],
                'HR Management': [
                    'Teacher recruitment best practices',
                    'Teacher performance management',
                    'Teacher training strategies',
                    'Staff retention in schools',
                    'HR development in education'
                ],
                'Parent Services': [
                    'School-parent communication tools',
                    'Parent engagement strategies',
                    'Parent portal implementation',
                    'Family involvement in education'
                ],
                'SOP Creation': [
                    'School standard operating procedures template',
                    'School process documentation guide',
                    'Educational quality assurance SOPs'
                ],
                'Dormitory Management': [
                    'Dormitory management systems',
                    'Boarding school management software',
                    'Student welfare in dormitories'
                ],
                'School Business Unit': [
                    'School entrepreneurship ideas',
                    'Income generating activities for schools',
                    'School cooperative management',
                    'Education business ventures'
                ],
                'Education Hotnews': [
                    'Viral: Inspiring educational innovations',
                    'Trending: Latest education policy changes',
                    'Hot topic: Viral phenomena in schools',
                    'Viral story: Inspiring teachers changing lives'
                ],
                'Education Cost': [
                    'Private school tuition trends',
                    'University admission cost guide',
                    'Student enrollment budgeting',
                    'Tuition fee calculators',
                    'Scholarships and financial aid'
                ]
            }
        else:
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
        
        # Try to find matching category case-insensitively or use default fallback topics
        topics = []
        for cat, list_topics in fallback_map.items():
            if cat.lower() in category_name.lower() or category_name.lower() in cat.lower():
                topics = list_topics
                break
        
        if not topics:
            if language == 'en':
                topics = [
                    f"Understanding {category_name} deeply",
                    f"Top 5 tips for managing {category_name}",
                    f"Common mistakes in {category_name} and how to avoid them",
                    f"How to implement {category_name} successfully",
                    f"The future of {category_name} in 2026"
                ]
            else:
                topics = [
                    f"Panduan lengkap memahami {category_name}",
                    f"5 tips sukses mengelola {category_name}",
                    f"Kesalahan umum dalam {category_name} dan solusinya",
                    f"Cara praktis menerapkan {category_name}",
                    f"Tren terbaru {category_name} tahun 2026"
                ]
        
        import random
        selected = random.sample(topics, min(len(topics), count))
        return [{'topic': t, 'type': 'fallback', 'category': category_name} for t in selected]
