import numpy as np
from sklearn.preprocessing import StandardScaler
from collections import defaultdict

class ContentOptimizer:
    def __init__(self, db):
        self.db = db
        self.scaler = StandardScaler()
    
    def analyze_performance(self, user_id, site_id=None):
        """Analyze category performance and return insights"""
        performance = self.db.get_category_performance(user_id, site_id=site_id)
        
        if not performance:
            return None
        
        # Calculate scores
        for cat in performance:
            # Normalize metrics
            engagement_weight = 0.5
            views_weight = 0.3
            comments_weight = 0.2
            
            cat['performance_score'] = (
                cat['avg_engagement'] * engagement_weight +
                (cat['total_views'] / max(cat['total_posts'], 1)) * views_weight +
                (cat['total_comments'] / max(cat['total_posts'], 1)) * comments_weight
            )
        
        # Sort by performance
        performance.sort(key=lambda x: x['performance_score'], reverse=True)
        
        return performance
    
    def get_content_recommendations(self, user_id, site_id=None):
        """Get AI-powered content recommendations"""
        performance = self.analyze_performance(user_id, site_id=site_id)
        
        if not performance or len(performance) < 3:
            return {
                'status': 'insufficient_data',
                'message': 'Butuh minimal 3 kategori dengan data untuk analisis',
                'recommendations': []
            }
        
        top_performers = performance[:3]
        low_performers = performance[-3:]
        
        recommendations = []
        
        # Recommend increasing frequency for top performers
        for cat in top_performers:
            if cat['performance_score'] > 10:
                recommendations.append({
                    'type': 'increase_frequency',
                    'category': cat['category'],
                    'reason': f"Engagement tinggi ({cat['avg_engagement']:.1f}), views {cat['total_views']}",
                    'action': 'Tingkatkan frekuensi posting untuk kategori ini'
                })
        
        # Recommend content improvement for low performers
        for cat in low_performers:
            if cat['performance_score'] < 5 and cat['total_posts'] > 2:
                recommendations.append({
                    'type': 'improve_content',
                    'category': cat['category'],
                    'reason': f"Engagement rendah ({cat['avg_engagement']:.1f})",
                    'action': 'Perbaiki kualitas konten atau ubah angle penulisan'
                })
        
        return {
            'status': 'success',
            'top_categories': [c['category'] for c in top_performers],
            'recommendations': recommendations,
            'performance_data': performance
        }
    
    def optimize_category_order(self, current_categories, user_id, site_id=None):
        """Reorder categories based on performance"""
        performance = self.analyze_performance(user_id, site_id=site_id)
        
        if not performance:
            return current_categories
        
        # Create performance map
        perf_map = {p['category']: p['performance_score'] for p in performance}
        
        # Sort categories by performance score
        optimized = sorted(
            current_categories,
            key=lambda x: perf_map.get(x['name'], 0),
            reverse=True
        )
        
        return optimized
    
    def predict_engagement(self, category_name, user_id, site_id=None):
        """Predict expected engagement for a category"""
        performance = self.db.get_category_performance(user_id, site_id=site_id)
        
        for cat in performance:
            if cat['category'] == category_name:
                return {
                    'predicted_views': cat['total_views'] / max(cat['total_posts'], 1),
                    'predicted_engagement': cat['avg_engagement'],
                    'confidence': 'high' if cat['total_posts'] > 5 else 'medium'
                }
        
        return {
            'predicted_views': 0,
            'predicted_engagement': 0,
            'confidence': 'low'
        }
