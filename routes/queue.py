from flask import Blueprint, request, jsonify
from rq.job import Job
from rq.exceptions import NoSuchJobError

from core_extensions import db, q, redis_conn, logger, load_config, require_jwt
from bot import ArticleGenerator

queue_bp = Blueprint('queue', __name__)

@queue_bp.route('/api/queue', methods=['GET'])
@require_jwt
def api_queue(user_id):
    site_id = request.args.get('site_id', type=int)
    if not site_id:
        return jsonify({'success': False, 'error': 'site_id is required', 'code': 400}), 400
        
    with db.get_session() as session:
        from database import ContentQueue, WordPressSite
        site = session.query(WordPressSite).filter_by(id=site_id, user_id=user_id).first()
        if not site:
            return jsonify({'success': False, 'error': 'Site not found', 'code': 404}), 404
            
        queue = session.query(ContentQueue).filter_by(user_id=user_id, site_id=site_id).order_by(ContentQueue.created_at.desc()).all()
        queue_data = [{'id': q.id, 'title': q.title, 'category': q.category, 'status': q.status, 'created_at': q.created_at.isoformat()} for q in queue]
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
    from database import ContentQueue
    data = request.json
    site_id = data.get('site_id')
    title = data.get('title')
    category = data.get('category')
    target_keywords = data.get('target_keywords', '')
    
    if not title or not category or not site_id:
        return jsonify({'success': False, 'error': 'Title, category, and site_id are required', 'code': 400}), 400
        
    with db.get_session() as session:
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

@queue_bp.route('/api/queue', methods=['DELETE'])
@require_jwt
def delete_queue_api(user_id):
    from database import ContentQueue
    data = request.json
    item_id = data.get('id')
    
    with db.get_session() as session:
        item = session.query(ContentQueue).filter_by(id=item_id, user_id=user_id).first()
        if not item:
            return jsonify({'success': False, 'error': 'Item not found', 'code': 404}), 404
        session.delete(item)
        session.commit()
    return jsonify({'success': True})

@queue_bp.route('/api/queue/edit/<int:item_id>', methods=['POST'])
@require_jwt
def edit_queue_api(user_id, item_id):
    from database import ContentQueue
    data = request.json
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
    from database import ContentQueue
    data = request.json
    ids = data.get('ids', [])
    
    if not ids:
        return jsonify({'success': True})
        
    import datetime
    
    with db.get_session() as session:
        # Hack to reorder items based on created_at since there is no 'position' column
        # We assign descending times so the first item has the newest timestamp
        now = datetime.datetime.now()
        for idx, item_id in enumerate(ids):
            item = session.query(ContentQueue).filter_by(id=item_id, user_id=user_id).first()
            if item:
                # the first id should be ordered first, so it needs the largest created_at
                # subtract idx seconds from 'now'
                item.created_at = now - datetime.timedelta(seconds=idx)
        session.commit()
    return jsonify({'success': True})

@queue_bp.route('/api/queue/post/<int:item_id>', methods=['POST'])
@require_jwt
def post_queue_api(user_id, item_id):
    from database import ContentQueue, User
    with db.get_session() as session:
        user = session.query(User).filter_by(id=user_id).first()
        if not user or (user.credits or 0) <= 0:
            return jsonify({'success': False, 'error': 'Insufficient credits. Please top up.', 'code': 400}), 400

        item = session.query(ContentQueue).filter_by(id=item_id, user_id=user_id).first()
        if not item:
            return jsonify({'success': False, 'error': 'Item not found', 'code': 404}), 404
        item.status = 'posting'
        session.commit()
            
    q.enqueue('app.generate_and_post', user_id, item_id, job_timeout='10m')
    return jsonify({'success': True})

@queue_bp.route('/api/queue/history/regenerate-image/<int:log_id>', methods=['POST'])
@require_jwt
def regenerate_image_api(user_id, log_id):
    from database import PostLog
    with db.get_session() as session:
        log = session.query(PostLog).filter_by(id=log_id, user_id=user_id).first()
        if not log:
            return jsonify({'success': False, 'error': 'Log not found', 'code': 404}), 404
        if not log.post_id:
            return jsonify({'success': False, 'error': 'Cannot regenerate image: No post ID found in WordPress', 'code': 400}), 400
            
    q.enqueue('app.regenerate_image_job', user_id, log_id, job_timeout='5m')
    return jsonify({'success': True})

@queue_bp.route('/manual-post', methods=['POST'])
@require_jwt
def manual_post(user_id):
    from database import User
    site_id = request.json.get('site_id')
    if not site_id:
        return jsonify({'success': False, 'error': 'site_id is required', 'code': 400}), 400
        
    with db.get_session() as session:
        user = session.query(User).filter_by(id=user_id).first()
        if not user or (user.credits or 0) <= 0:
            return jsonify({'success': False, 'error': 'Insufficient credits. Please top up.', 'code': 400}), 400

    try:
        job = q.enqueue('app.generate_and_post', user_id, None, site_id, job_timeout='10m')
        return jsonify({'success': True, 'message': 'Artikel dijadwalkan untuk diposting'})
    except Exception as e:
        logger.error(f"Manual post error: {e}")
        return jsonify({'success': False, 'error': str(e), 'code': 500}), 500

@queue_bp.route('/api/job-status/<job_id>', methods=['GET'])
@require_jwt
def job_status(user_id, job_id):
    try:
        job = Job.fetch(job_id, connection=redis_conn)
        status = job.get_status()
        
        progress = 0
        message = 'Processing...'
        if status == 'finished':
            progress = 100
            message = 'Completed successfully'
        elif status == 'failed':
            progress = 100
            message = 'Job failed'
        elif status == 'started':
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
    category_name = request.json.get('category', '')
    site_id = request.json.get('site_id')
    
    if not site_id:
        return jsonify({'success': False, 'error': 'site_id is required', 'code': 400}), 400
        
    with db.get_session() as session:
        from database import WordPressSite
        site = session.query(WordPressSite).filter_by(id=site_id, user_id=user_id).first()
        if not site:
            return jsonify({'success': False, 'error': 'Site not found', 'code': 404}), 404
            
        try:
            # We will need to pass site prompts to ArticleGenerator, but let's keep it simple for now
            # The app.py generate_and_post will need refactoring to take site_id
            generator = ArticleGenerator(
                config['gemini_api_key'], 
                config.get('gemini_model', 'gemini-2.5-pro'),
                config.get('gemini_image_model', 'gemini-3.1-flash-image')
            )
            article = generator.generate_article(category_name, custom_prompt=site.article_prompt, site_name=site.site_name, language=site.language or 'id')
            return jsonify({'success': True, 'article': article})
        except Exception as e:
            logger.error(f"Test generate error: {e}")
            return jsonify({'success': False, 'error': str(e), 'code': 500}), 500
