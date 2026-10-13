import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from flask import Blueprint, jsonify, request

from core_extensions import db, logger, optimizer, require_jwt, get_cached_stats
from models import ContentQueue, WordPressSite
from services.wp_publisher import WordPressPublisher
from services.url_safety import validate_public_http_url

dashboard_bp = Blueprint('dashboard', __name__)

# One sync request must not tie up a web worker for minutes: each post costs up
# to two WordPress requests with a 10s timeout.
SYNC_ENGAGEMENT_MAX_POSTS = 20
SYNC_ENGAGEMENT_MAX_SECONDS = 25
DEFAULT_SCHEDULE_HOURS = '0,6,12,18'
DEFAULT_TIMEZONE = 'Asia/Jakarta'


def _utc_iso(value):
    """ISO timestamp; naive values are marked as UTC with a trailing Z."""
    return value.isoformat() + ('Z' if value.tzinfo is None else '')


def _next_post_time(schedule_hours, tz_name):
    """Next scheduled auto-post time in the site's timezone, or None."""
    hours_list = sorted(int(h.strip()) for h in schedule_hours.split(',') if h.strip().isdigit())
    if not hours_list:
        return None

    try:
        local_tz = ZoneInfo(tz_name or DEFAULT_TIMEZONE)
    except Exception:
        local_tz = ZoneInfo(DEFAULT_TIMEZONE)  # invalid stored timezone: use the default

    now_local = datetime.now(local_tz)
    for hour in hours_list:
        candidate = now_local.replace(hour=hour, minute=0, second=0, microsecond=0)
        if candidate > now_local:
            return candidate
    return (now_local + timedelta(days=1)).replace(hour=hours_list[0], minute=0, second=0, microsecond=0)


def _posting_queue_entries(session, user_id, site_id):
    """Items being generated right now, shaped like log rows for the activity list."""
    active_queue = session.query(ContentQueue).filter_by(
        user_id=user_id, site_id=site_id, status='posting'
    ).order_by(ContentQueue.created_at.desc()).all()
    return [{
        'id': f"q_{item.id}",
        'post_id': None,
        'post_url': None,
        'category': item.category,
        'title': item.title,
        'success': 'pending',
        'image_failed': False,
        'result': 'Menunggu jadwal / Proses pembuatan',
        'timestamp': _utc_iso(item.created_at),
        'views': 0,
        'comments': 0,
        'engagement_score': 0
    } for item in active_queue]


@dashboard_bp.route('/api/dashboard')
@require_jwt
def api_dashboard(user_id):
    site_id = request.args.get('site_id', type=int)
    if not site_id:
        return jsonify({'success': False, 'error': 'site_id wajib diisi.', 'code': 400}), 400

    with db.get_session() as session:
        site = session.query(WordPressSite).filter_by(id=site_id, user_id=user_id).first()
        if not site:
            return jsonify({'success': False, 'error': 'Website tidak ditemukan.', 'code': 404}), 404

        site_auto_post = site.auto_post
        site_selected_categories = site.selected_categories
        site_schedule_hours = site.schedule_hours
        site_timezone = site.timezone

        logs = db.get_logs(user_id, site_id=site_id, limit=20)
        # Show the items being generated right now above the finished logs.
        for entry in _posting_queue_entries(session, user_id, site_id):
            logs.insert(0, entry)

        # Use the shared 5s cache instead of hitting the database on every poll;
        # the dashboard is refreshed frequently.
        stats = get_cached_stats(user_id, site_id=site_id)
        insights = optimizer.get_content_recommendations(user_id, site_id=site_id)
        performance = db.get_category_performance(user_id, site_id=site_id)

        next_post_time = None
        if site_auto_post and site_selected_categories:
            try:
                next_post_time = _next_post_time(site_schedule_hours or DEFAULT_SCHEDULE_HOURS, site_timezone)
            except Exception as e:
                logger.error(f"Error calculating next post time: {e}")

        return jsonify({
            'success': True,
            'logs': logs if logs else [],
            'stats': stats,
            'insights': insights,
            'performance': performance if performance else [],
            'next_post_time': _utc_iso(next_post_time) if next_post_time else None
        })


@dashboard_bp.route("/sync-engagement", methods=["POST"])
@require_jwt
def sync_engagement(user_id):
    """Sync engagement metrics from WordPress"""
    site_id = (request.get_json(silent=True) or {}).get('site_id')
    if not site_id:
        return jsonify({'success': False, 'error': 'site_id wajib diisi.', 'code': 400}), 400

    try:
        with db.get_session() as session:
            site = session.query(WordPressSite).filter_by(id=site_id, user_id=user_id).first()
            if not site:
                return jsonify({'success': False, 'error': 'Website tidak ditemukan.'}), 404
            if not site.wordpress_url or not site.wordpress_username or not site.wordpress_password:
                return jsonify({'success': False, 'error': 'Mohon isi kredensial WordPress terlebih dahulu.'}), 400

            # Re-validate the stored URL before the server fetches it.
            url_ok, url_or_error = validate_public_http_url(site.wordpress_url)
            if not url_ok:
                return jsonify({'success': False, 'error': f'URL WordPress tidak valid: {url_or_error}'}), 400

            publisher = WordPressPublisher(
                url_or_error,
                site.wordpress_username,
                site.wordpress_password
            )

        logs = db.get_logs(user_id, site_id=site_id, limit=SYNC_ENGAGEMENT_MAX_POSTS)
        synced = 0
        deadline = time.monotonic() + SYNC_ENGAGEMENT_MAX_SECONDS

        for log in logs:
            if time.monotonic() >= deadline:
                break
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
            'message': f'Berhasil sinkronisasi {synced} artikel.',
            'synced': synced
        })
    except Exception as e:
        logger.error(f"Sync engagement error: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Terjadi kesalahan saat sinkronisasi data.'}), 500


@dashboard_bp.route("/optimize-categories", methods=["POST"])
@require_jwt
def optimize_categories(user_id):
    """Auto-optimize category order based on performance"""
    site_id = (request.get_json(silent=True) or {}).get('site_id')
    if not site_id:
        return jsonify({'success': False, 'error': 'site_id wajib diisi.', 'code': 400}), 400

    try:
        with db.get_session() as session:
            site = session.query(WordPressSite).filter_by(id=site_id, user_id=user_id).first()
            if not site:
                return jsonify({'success': False, 'error': 'Website tidak ditemukan.'}), 404

            optimized = optimizer.optimize_category_order(site.selected_categories or [], user_id, site_id=site.id)
            site.selected_categories = optimized
            session.commit()

        return jsonify({
            'success': True,
            'message': 'Kategori berhasil dioptimasi berdasarkan performa',
            'categories': [c['name'] for c in optimized]
        })
    except Exception as e:
        logger.error(f"Optimize categories error: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Terjadi kesalahan saat optimasi kategori.'}), 500
