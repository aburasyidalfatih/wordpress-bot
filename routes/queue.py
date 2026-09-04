from datetime import datetime

from flask import Blueprint, request, jsonify
from rq.job import Job
from rq.exceptions import NoSuchJobError

from core_extensions import db, q, redis_conn, logger, load_config, require_jwt
from services.article_generator import ArticleGenerator
from config import DEFAULT_GEMINI_MODEL, DEFAULT_GEMINI_IMAGE_MODEL

queue_bp = Blueprint('queue', __name__)

@queue_bp.route('/api/queue', methods=['GET'])
@require_jwt
def api_queue(user_id):
    site_id = request.args.get('site_id', type=int)
    if not site_id:
        return jsonify({'success': False, 'error': 'site_id is required', 'code': 400}), 400
        
    with db.get_session() as session:
        from models import ContentQueue, WordPressSite
        site = session.query(WordPressSite).filter_by(id=site_id, user_id=user_id).first()
        if not site:
            return jsonify({'success': False, 'error': 'Site not found', 'code': 404}), 404
            
        queue = session.query(ContentQueue).filter(
            ContentQueue.user_id == user_id,
            ContentQueue.site_id == site_id,
            ContentQueue.status.in_(['pending', 'posting'])
        ).order_by(ContentQueue.created_at.asc()).all()
        queue_data = [{'id': q.id, 'title': q.title, 'category': q.category, 'status': q.status, 'created_at': q.created_at.isoformat() + ('Z' if q.created_at.tzinfo is None else '')} for q in queue]
        categories = site.selected_categories or []
    
    history_data = db.get_logs(user_id, site_id=site_id, limit=50)
    return jsonify({
        'success': True,
        'queue': queue_data,
        'history': history_data,
        'categories': categories
    })

@queue_bp.route('/api/queue', methods=['POST'])
@require_jwt
def add_queue_api(user_id):
    from models import ContentQueue, WordPressSite
    data = request.get_json(silent=True) or {}
    site_id = data.get('site_id')
    title = data.get('title')
    category = data.get('category')
    target_keywords = data.get('target_keywords', '')
    
    if not title or not category or not site_id:
        return jsonify({'success': False, 'error': 'Title, category, and site_id are required', 'code': 400}), 400
        
    with db.get_session() as session:
        site = session.query(WordPressSite).filter_by(id=site_id, user_id=user_id).first()
        if not site:
            return jsonify({'success': False, 'error': 'Site not found', 'code': 404}), 404

        new_item = ContentQueue(
            user_id=user_id,
            site_id=site_id,
            title=title,
            category=category,
            target_keywords=target_keywords,
            status='pending'
        )
        session.add(new_item)
        session.commit()
    return jsonify({'success': True})

@queue_bp.route('/api/queue/shuffle', methods=['POST'])
@require_jwt
def shuffle_queue(user_id):
    import random
    from models import ContentQueue
    data = request.get_json(silent=True) or {}
    site_id = data.get('site_id')
    if not site_id:
        return jsonify({'success': False, 'error': 'site_id is required', 'code': 400}), 400
        
    with db.get_session() as session:
        items = session.query(ContentQueue).filter_by(
            user_id=user_id, 
            site_id=site_id, 
            status='pending'
        ).order_by(ContentQueue.created_at.asc()).all()
        
        if len(items) <= 1:
            return jsonify({'success': True, 'message': 'Not enough items to shuffle'})
            
        # Extract existing created_at values
        timestamps = [item.created_at for item in items]
        
        # Shuffle items
        shuffled_items = list(items)
        random.shuffle(shuffled_items)
        
        # Re-assign timestamps to change their order
        for i, item in enumerate(shuffled_items):
            item.created_at = timestamps[i]
            
        session.commit()
        
    return jsonify({'success': True, 'message': 'Antrean berhasil diacak!'})

@queue_bp.route('/api/queue', methods=['DELETE'])
@require_jwt
def delete_queue_api(user_id):
    from models import ContentQueue
    data = request.get_json(silent=True) or {}
    item_id = data.get('id')
    if not item_id:
        return jsonify({'success': False, 'error': 'id is required', 'code': 400}), 400
    
    with db.get_session() as session:
        item = session.query(ContentQueue).filter_by(id=item_id, user_id=user_id).first()
        if not item:
            return jsonify({'success': False, 'error': 'Item not found', 'code': 404}), 404
        session.delete(item)
        session.commit()
    return jsonify({'success': True})

@queue_bp.route('/api/queue/clear', methods=['POST'])
@require_jwt
def clear_queue_api(user_id):
    from models import ContentQueue
    data = request.get_json(silent=True) or {}
    site_id = data.get('site_id')
    if not site_id:
        return jsonify({'success': False, 'error': 'site_id is required', 'code': 400}), 400
    
    try:
        with db.get_session() as session:
            session.query(ContentQueue).filter_by(
                user_id=user_id, 
                site_id=site_id, 
                status='pending'
            ).delete()
            session.commit()
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Clear queue error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@queue_bp.route('/api/queue/edit/<int:item_id>', methods=['POST'])
@require_jwt
def edit_queue_api(user_id, item_id):
    from models import ContentQueue
    data = request.get_json(silent=True) or {}
    title = data.get('title')
    target_keywords = data.get('target_keywords', '')
    
    with db.get_session() as session:
        item = session.query(ContentQueue).filter_by(id=item_id, user_id=user_id).first()
        if not item:
            return jsonify({'success': False, 'error': 'Item not found', 'code': 404}), 404
        if title:
            item.title = title
        item.target_keywords = target_keywords
        session.commit()
    return jsonify({'success': True})

@queue_bp.route('/api/queue/reorder', methods=['POST'])
@require_jwt
def reorder_queue_api(user_id):
    from models import ContentQueue
    data = request.get_json(silent=True) or {}
    ids = data.get('ids', [])
    
    if not ids:
        return jsonify({'success': True})
        
    import datetime
    
    with db.get_session() as session:
        # Keep order compatible with the queue query, which sorts created_at ascending.
        base_time = datetime.datetime.now() - datetime.timedelta(seconds=len(ids))
        # Fetch every item in one query rather than one per id; a drag-and-drop
        # reorder posts the whole list.
        items_by_id = {
            item.id: item for item in session.query(ContentQueue).filter(
                ContentQueue.id.in_(ids),
                ContentQueue.user_id == user_id
            ).all()
        }
        for idx, item_id in enumerate(ids):
            item = items_by_id.get(item_id)
            if item:
                item.created_at = base_time + datetime.timedelta(seconds=idx)
        session.commit()
    return jsonify({'success': True})

@queue_bp.route('/api/queue/post/<int:item_id>', methods=['POST'])
@require_jwt
def post_queue_api(user_id, item_id):
    from models import ContentQueue, User
    with db.get_session() as session:
        user = session.query(User).filter_by(id=user_id).first()
        item = session.query(ContentQueue).filter_by(id=item_id, user_id=user_id).first()
        if not item:
            return jsonify({'success': False, 'error': 'Item not found', 'code': 404}), 404
        if item.status == 'posting':
            return jsonify({'success': True, 'message': 'Item is already being processed'})
        if item.status == 'posted':
            return jsonify({'success': False, 'error': 'Item has already been posted', 'code': 400}), 400

        # Atomic credit reservation to prevent race conditions
        if not db.reserve_user_credits(user_id, 1):
            return jsonify({'success': False, 'error': 'Kredit tidak mencukupi', 'code': 402}), 402

        item.status = 'posting'
        item.posting_started_at = datetime.now()
        session.commit()

    try:
        q.enqueue('tasks.article_jobs.generate_and_post', user_id, item_id, None, True, job_timeout='10m')
    except Exception as e:
        # Refund credit on enqueue failure
        db.refund_user_credits(user_id, 1)
        with db.get_session() as session:
            item = session.query(ContentQueue).filter_by(id=item_id, user_id=user_id).first()
            if item:
                item.status = 'pending'
        logger.error(f"Queue post enqueue failed for item {item_id}: {e}")
        return jsonify({'success': False, 'error': 'Failed to enqueue posting job'}), 500
    return jsonify({'success': True})

@queue_bp.route('/api/queue/history/regenerate-image/<int:log_id>', methods=['POST'])
@require_jwt
def regenerate_image_api(user_id, log_id):
    from models import PostLog
    with db.get_session() as session:
        log = session.query(PostLog).filter_by(id=log_id, user_id=user_id).first()
        if not log:
            return jsonify({'success': False, 'error': 'Log not found', 'code': 404}), 404
        if not log.post_id:
            return jsonify({'success': False, 'error': 'Cannot regenerate image: No post ID found in WordPress', 'code': 400}), 400

    # Credit validation before enqueue
    if not db.reserve_user_credits(user_id, 1):
        return jsonify({'success': False, 'error': 'Kredit tidak mencukupi'}), 402

    try:
        q.enqueue('tasks.article_jobs.regenerate_image_job', user_id, log_id, job_timeout='5m')
    except Exception as e:
        db.refund_user_credits(user_id, 1)
        logger.error(f"Regenerate image enqueue failed: {e}")
        return jsonify({'success': False, 'error': 'Failed to enqueue job'}), 500
    return jsonify({'success': True})

@queue_bp.route('/api/queue/history/regenerate-article/<int:log_id>', methods=['POST'])
@require_jwt
def regenerate_article_api(user_id, log_id):
    from models import PostLog
    with db.get_session() as session:
        log = session.query(PostLog).filter_by(id=log_id, user_id=user_id).first()
        if not log:
            return jsonify({'success': False, 'error': 'Log not found', 'code': 404}), 404
        if not log.post_id:
            return jsonify({'success': False, 'error': 'Cannot regenerate article: No post ID found in WordPress', 'code': 400}), 400

    # Credit validation before enqueue
    if not db.reserve_user_credits(user_id, 1):
        return jsonify({'success': False, 'error': 'Kredit tidak mencukupi'}), 402

    try:
        q.enqueue('tasks.article_jobs.regenerate_article_job', user_id, log_id, job_timeout='10m')
    except Exception as e:
        db.refund_user_credits(user_id, 1)
        logger.error(f"Regenerate article enqueue failed: {e}")
        return jsonify({'success': False, 'error': 'Failed to enqueue job'}), 500
    return jsonify({'success': True})

@queue_bp.route('/api/queue/history/<int:log_id>', methods=['DELETE'])
@require_jwt
def delete_history_log(user_id, log_id):
    from models import PostLog
    import requests
    from requests.auth import HTTPBasicAuth
    
    with db.get_session() as session:
        log = session.query(PostLog).filter_by(id=log_id, user_id=user_id).first()
        if not log:
            return jsonify({'success': False, 'error': 'Log not found', 'code': 404}), 404
            
        post_id = log.post_id
        site_id = log.site_id
        
        if post_id and site_id:
            try:
                from models import WordPressSite
                site = session.query(WordPressSite).filter_by(id=site_id, user_id=user_id).first()
                if site:
                    wp_url = site.wp_url
                    wp_user = site.wp_username
                    wp_app_pass = site.wp_app_password
                    
                    if wp_url and wp_user and wp_app_pass:
                        delete_url = f"{wp_url.rstrip('/')}/wp-json/wp/v2/posts/{post_id}?force=true"
                        requests.delete(delete_url, auth=HTTPBasicAuth(wp_user, wp_app_pass), timeout=10)
            except Exception as e:
                logger.error(f"Failed to delete post from WP for log {log_id}: {e}")
                
        session.delete(log)
        session.commit()
        
    return jsonify({'success': True, 'message': 'Log and article deleted successfully'})

@queue_bp.route('/manual-post', methods=['POST'])
@require_jwt
def manual_post(user_id):
    from models import User, WordPressSite
    data = request.get_json(silent=True) or {}
    site_id = data.get('site_id')
    if not site_id:
        return jsonify({'success': False, 'error': 'site_id is required', 'code': 400}), 400
        
    with db.get_session() as session:
        user = session.query(User).filter_by(id=user_id).first()
        site = session.query(WordPressSite).filter_by(id=site_id, user_id=user_id).first()
        if not site:
            return jsonify({'success': False, 'error': 'Site not found', 'code': 404}), 404

    # Atomic credit reservation to prevent race conditions
    if not db.reserve_user_credits(user_id, 1):
        return jsonify({'success': False, 'error': 'Kredit tidak mencukupi', 'code': 402}), 402

    try:
        job = q.enqueue('tasks.article_jobs.generate_and_post', user_id, None, site_id, True, job_timeout='10m')
        return jsonify({'success': True, 'message': 'Artikel dijadwalkan untuk diposting'})
    except Exception as e:
        db.refund_user_credits(user_id, 1)
        logger.error(f"Manual post enqueue error: {e}")
        return jsonify({'success': False, 'error': 'Failed to enqueue posting job'}), 500

@queue_bp.route('/api/job-status/<job_id>', methods=['GET'])
@require_jwt
def job_status(user_id, job_id):
    try:
        job = Job.fetch(job_id, connection=redis_conn)
        if job.args and job.args[0] != user_id:
            return jsonify({'success': False, 'error': 'Job not found', 'code': 404}), 404
        status = job.get_status()
        
        progress = int(job.meta.get('progress', 0) or 0)
        message = job.meta.get('message') or 'Processing...'
        if status == 'finished':
            progress = 100
            message = 'Completed successfully'
        elif status == 'failed':
            progress = 100
            message = 'Job failed'
        elif status == 'started' and progress == 0:
            progress = 50
            message = 'In progress'
            
        return jsonify({
            'success': True,
            'status': status,
            'progress': progress,
            'message': message
        })
    except NoSuchJobError:
        return jsonify({'success': False, 'error': 'Job not found', 'code': 404}), 404

@queue_bp.route('/test-generate', methods=['POST'])
@require_jwt
def test_generate(user_id):
    config = load_config(user_id)
    data = request.get_json(silent=True) or {}
    category_name = data.get('category', '')
    site_id = data.get('site_id')
    
    if not site_id:
        return jsonify({'success': False, 'error': 'site_id is required', 'code': 400}), 400
        
    with db.get_session() as session:
        from models import WordPressSite
        site = session.query(WordPressSite).filter_by(id=site_id, user_id=user_id).first()
        if not site:
            return jsonify({'success': False, 'error': 'Site not found', 'code': 404}), 404
            
        try:
            # We will need to pass site prompts to ArticleGenerator, but let's keep it simple for now
            # The app.py generate_and_post will need refactoring to take site_id
            generator = ArticleGenerator(
                config['gemini_api_key'], 
                config.get('gemini_model', DEFAULT_GEMINI_MODEL),
                config.get('gemini_image_model', DEFAULT_GEMINI_IMAGE_MODEL)
            )
            article = generator.generate_article(category_name, custom_prompt=site.article_prompt, site_name=site.site_name, language=site.language or 'id')
            return jsonify({'success': True, 'article': article})
        except Exception as e:
            logger.error(f"Test generate error: {e}")
            return jsonify({'success': False, 'error': str(e), 'code': 500}), 500
