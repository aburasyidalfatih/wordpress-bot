from flask import Blueprint, jsonify, request

from core_extensions import db, optimizer, require_jwt, load_config
from bot import WordPressPublisher

dashboard_bp = Blueprint('dashboard', __name__)

@dashboard_bp.route('/api/dashboard')
@require_jwt
def api_dashboard(user_id):
    site_id = request.args.get('site_id', type=int)
    if not site_id:
        return jsonify({'success': False, 'error': 'site_id is required', 'code': 400}), 400
        
    with db.get_session() as session:
        from database import WordPressSite
        site = session.query(WordPressSite).filter_by(id=site_id, user_id=user_id).first()
        if not site:
            return jsonify({'success': False, 'error': 'Site not found', 'code': 404}), 404
            
        site_auto_post = site.auto_post
        site_selected_categories = site.selected_categories
        site_schedule_hours = site.schedule_hours
        site_timezone = site.timezone
            
        logs = db.get_logs(user_id, site_id=site_id, limit=20)
        stats = db.get_stats(user_id, site_id=site_id)
        insights = optimizer.get_content_recommendations(user_id, site_id=site_id) 
        performance = db.get_category_performance(user_id, site_id=site_id)
        
        # Get next scheduled post time dynamically
        next_post_time = None
        if site_auto_post and site_selected_categories:
            schedule_hours = site_schedule_hours or '0,6,12,18'
            try:
                hours_list = sorted([int(h.strip()) for h in schedule_hours.split(',') if h.strip().isdigit()])
                if hours_list:
                    from datetime import datetime, timedelta
                    from zoneinfo import ZoneInfo
                    
                    tz_name = site_timezone or 'Asia/Jakarta'
                    try:
                        local_tz = ZoneInfo(tz_name)
                    except Exception:
                        local_tz = ZoneInfo('Asia/Jakarta')
                        
                    now_local = datetime.now(local_tz)
                    next_time = None
                    for hour in hours_list:
                        candidate = now_local.replace(hour=hour, minute=0, second=0, microsecond=0)
                        if candidate > now_local:
                            next_time = candidate
                            break
                    if not next_time:
                        next_time = (now_local + timedelta(days=1)).replace(hour=hours_list[0], minute=0, second=0, microsecond=0)
                    next_post_time = next_time
            except Exception as e:
                from core_extensions import logger
                logger.error(f"Error calculating next post time: {e}")
        
        return jsonify({
            'success': True,
            'logs': logs if logs else [],
            'stats': stats,
            'insights': insights,
            'performance': performance if performance else [],
            'next_post_time': next_post_time.isoformat() + ('Z' if next_post_time.tzinfo is None else '') if next_post_time else None
        })

@dashboard_bp.route("/sync-engagement", methods=["POST"])
@require_jwt
def sync_engagement(user_id):
    """Sync engagement metrics from WordPress"""
    site_id = request.json.get('site_id')
    if not site_id:
        return jsonify({'success': False, 'error': 'site_id is required', 'code': 400}), 400
        
    try:
        with db.get_session() as session:
            from database import WordPressSite
            site = session.query(WordPressSite).filter_by(id=site_id, user_id=user_id).first()
            if not site:
                return jsonify({'success': False, 'error': 'Site not found'}), 404
                
            publisher = WordPressPublisher(
                site.wordpress_url,
                site.wordpress_username,
                site.wordpress_password
            )
            
        logs = db.get_logs(user_id, site_id=site_id, limit=50)
        synced = 0
        
        for log in logs:
            if log.get('post_id'):
                stats = publisher.get_post_stats(log['post_id'])
                if stats:
                    db.update_engagement(
                        log['id'],
                        views=stats.get('views', 0),
                        comments=stats.get('comments', 0),
                        likes=stats.get('likes', 0),
                        shares=stats.get('shares', 0)
                    )
                    synced += 1
        
        return jsonify({
            'success': True,
            'message': f'Berhasil sync {synced} artikel',
            'synced': synced
        })
    except Exception as e:
        from core_extensions import logger
        logger.error(f"Sync engagement error: {e}")
        return jsonify({'success': False, 'error': str(e)})

@dashboard_bp.route("/optimize-categories", methods=["POST"])
@require_jwt
def optimize_categories(user_id):
    """Auto-optimize category order based on performance"""
    site_id = request.json.get('site_id')
    if not site_id:
        return jsonify({'success': False, 'error': 'site_id is required', 'code': 400}), 400
        
    try:
        with db.get_session() as session:
            from database import WordPressSite
            site = session.query(WordPressSite).filter_by(id=site_id, user_id=user_id).first()
            if not site:
                return jsonify({'success': False, 'error': 'Site not found'}), 404
                
            optimized = optimizer.optimize_category_order(site.selected_categories, user_id)
            site.selected_categories = optimized
            session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Kategori berhasil dioptimasi berdasarkan performa',
            'categories': [c['name'] for c in optimized]
        })
    except Exception as e:
        from core_extensions import logger
        logger.error(f"Optimize categories error: {e}")
        return jsonify({'success': False, 'error': str(e)})
