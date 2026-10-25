import random
import uuid
from datetime import datetime, timedelta

import requests
from flask import Blueprint, request, jsonify
from requests.auth import HTTPBasicAuth
from rq.job import Job
from rq.exceptions import NoSuchJobError

from core_extensions import db, q, redis_conn, logger, load_config, require_jwt, require_admin
from database import debit_credits, add_credits
from models import ContentQueue, PostLog, WordPressSite
from services.article_generator import ArticleGenerator
from services.job_locks import claim_lock, regeneration_lock_key, release_lock
from services.url_safety import validate_public_http_url

queue_bp = Blueprint('queue', __name__)

# RQ timeout of the article generation / regeneration jobs: research, writing
# brief, article, helpfulness assessment and rewrite, fact-check and image.
# Keep in sync with GENERATE_AND_POST_JOB_TIMEOUT in dispatcher.py.
ARTICLE_JOB_TIMEOUT = '45m'

MAX_REORDER_IDS = 1000


def _error(message, status):
    return jsonify({'success': False, 'error': message, 'code': status}), status


def _site_required():
    return _error('site_id wajib diisi.', 400)


def _site_not_found():
    return _error('Website tidak ditemukan.', 404)


def _insufficient_credits():
    return _error('Kredit tidak mencukupi.', 402)


@queue_bp.route('/api/queue', methods=['GET'])
@require_jwt
def api_queue(user_id):
    site_id = request.args.get('site_id', type=int)
    if not site_id:
        return _site_required()

    with db.get_session() as session:
        site = session.query(WordPressSite).filter_by(id=site_id, user_id=user_id).first()
        if not site:
            return _site_not_found()

        queue = session.query(ContentQueue).filter(
            ContentQueue.user_id == user_id,
            ContentQueue.site_id == site_id,
            ContentQueue.status.in_(['pending', 'posting'])
        ).order_by(ContentQueue.created_at.asc()).all()
        queue_data = [{
            'id': item.id,
            'title': item.title,
            'category': item.category,
            'target_keywords': item.target_keywords or '',
            'status': item.status,
            'created_at': item.created_at.isoformat() + ('Z' if item.created_at.tzinfo is None else '')
        } for item in queue]
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
    data = request.get_json(silent=True) or {}
    site_id = data.get('site_id')
    title = data.get('title')
    category = data.get('category')
    target_keywords = data.get('target_keywords', '')

    if not title or not category or not site_id:
        return _error('Judul, kategori, dan site_id wajib diisi.', 400)

    with db.get_session() as session:
        site = session.query(WordPressSite).filter_by(id=site_id, user_id=user_id).first()
        if not site:
            return _site_not_found()

        session.add(ContentQueue(
            user_id=user_id,
            site_id=site_id,
            title=title,
            category=category,
            target_keywords=target_keywords,
            status='pending'
        ))
        session.commit()
    return jsonify({'success': True})


@queue_bp.route('/api/queue/shuffle', methods=['POST'])
@require_jwt
def shuffle_queue(user_id):
    data = request.get_json(silent=True) or {}
    site_id = data.get('site_id')
    if not site_id:
        return _site_required()

    with db.get_session() as session:
        items = session.query(ContentQueue).filter_by(
            user_id=user_id,
            site_id=site_id,
            status='pending'
        ).order_by(ContentQueue.created_at.asc()).all()

        if len(items) <= 1:
            return jsonify({'success': True, 'message': 'Item antrean terlalu sedikit untuk diacak.'})

        # The queue is ordered by created_at, so shuffling the items and handing
        # them the existing timestamps reorders the queue.
        timestamps = [item.created_at for item in items]
        shuffled_items = list(items)
        random.shuffle(shuffled_items)
        for item, timestamp in zip(shuffled_items, timestamps):
            item.created_at = timestamp

        session.commit()

    return jsonify({'success': True, 'message': 'Antrean berhasil diacak!'})


@queue_bp.route('/api/queue', methods=['DELETE'])
@require_jwt
def delete_queue_api(user_id):
    data = request.get_json(silent=True) or {}
    item_id = data.get('id')
    if not item_id:
        return _error('id wajib diisi.', 400)

    with db.get_session() as session:
        item = session.query(ContentQueue).filter_by(id=item_id, user_id=user_id).first()
        if not item:
            return _error('Item antrean tidak ditemukan.', 404)
        if item.status == 'posting':
            # A worker already reserved credit and is generating this item.
            return _error('Item sedang diposting dan tidak dapat dihapus.', 409)
        session.delete(item)
        session.commit()
    return jsonify({'success': True})


@queue_bp.route('/api/queue/clear', methods=['POST'])
@require_jwt
def clear_queue_api(user_id):
    data = request.get_json(silent=True) or {}
    site_id = data.get('site_id')
    if not site_id:
        return _site_required()

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
        return jsonify({'success': False, 'error': 'Gagal mengosongkan antrean.'}), 500


@queue_bp.route('/api/queue/edit/<int:item_id>', methods=['POST'])
@require_jwt
def edit_queue_api(user_id, item_id):
    data = request.get_json(silent=True) or {}
    title = data.get('title')
    if 'title' in data and (not isinstance(title, str) or not title.strip()):
        return _error('Judul wajib diisi dan harus berupa teks.', 400)
    if 'target_keywords' in data and data['target_keywords'] is not None and not isinstance(data['target_keywords'], str):
        return _error('target_keywords harus berupa teks.', 400)

    with db.get_session() as session:
        item = session.query(ContentQueue).filter_by(id=item_id, user_id=user_id).first()
        if not item:
            return _error('Item antrean tidak ditemukan.', 404)
        if title is not None:
            item.title = title.strip()
        # Only touch keywords when the client sent them; a title-only edit must
        # not wipe the researched keywords.
        if 'target_keywords' in data:
            item.target_keywords = (data['target_keywords'] or '').strip()
        session.commit()
    return jsonify({'success': True})


@queue_bp.route('/api/queue/reorder', methods=['POST'])
@require_jwt
def reorder_queue_api(user_id):
    data = request.get_json(silent=True) or {}
    ids = data.get('ids', [])

    if not ids:
        return jsonify({'success': True})
    if (not isinstance(ids, list) or len(ids) > MAX_REORDER_IDS
            or not all(isinstance(i, int) and not isinstance(i, bool) for i in ids)):
        return _error('ids harus berupa daftar angka.', 400)

    with db.get_session() as session:
        # Keep order compatible with the queue query, which sorts created_at ascending.
        base_time = datetime.now() - timedelta(seconds=len(ids))
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
                item.created_at = base_time + timedelta(seconds=idx)
        session.commit()
    return jsonify({'success': True})


def _release_posting_claim(user_id, item_id, job_id):
    """Undo post_queue_api's claim and refund its credit, unless already settled.

    Only acts while the item is still ours (same job id) and the credit is still
    held, so a job or dispatcher sweep that already settled it is not undone.
    """
    with db.get_session() as session:
        released = session.query(ContentQueue).filter(
            ContentQueue.id == item_id,
            ContentQueue.user_id == user_id,
            ContentQueue.status == 'posting',
            ContentQueue.job_id == job_id,
            ContentQueue.credit_held.is_(True)
        ).update({
            'status': 'pending', 'posting_started_at': None,
            'job_id': None, 'credit_held': False,
        }, synchronize_session=False)
        if released == 1:
            add_credits(session, user_id, 1)


@queue_bp.route('/api/queue/post/<int:item_id>', methods=['POST'])
@require_jwt
def post_queue_api(user_id, item_id):
    job_id = f"queue-post-{item_id}-{uuid.uuid4().hex}"

    # Claim the item and reserve the credit in ONE transaction, recording the
    # reservation on the row (credit_held + the job id we are about to enqueue).
    # The job recognizes its own job_id and takes the reservation over; if the
    # job never runs, the dispatcher's stuck-item sweep refunds it because
    # credit_held is set. A conditional UPDATE stops two concurrent clicks from
    # both claiming the item.
    with db.get_session() as session:
        claimed = session.query(ContentQueue).filter(
            ContentQueue.id == item_id,
            ContentQueue.user_id == user_id,
            ContentQueue.status == 'pending'
        ).update({
            'status': 'posting',
            'posting_started_at': datetime.now(),
            'job_id': job_id,
            'credit_held': True,
        }, synchronize_session=False)
        if claimed != 1:
            item = session.query(ContentQueue).filter_by(id=item_id, user_id=user_id).first()
            if not item:
                return _error('Item antrean tidak ditemukan.', 404)
            if item.status == 'posted':
                return _error('Item ini sudah diposting.', 400)
            return _error('Item ini sedang diposting.', 409)
        if not debit_credits(session, user_id, 1):
            session.rollback()
            return _insufficient_credits()

    try:
        q.enqueue(
            'tasks.article_jobs.generate_and_post', user_id,
            item_id=item_id, credit_pre_reserved=True, job_timeout=ARTICLE_JOB_TIMEOUT, job_id=job_id
        )
    except Exception as e:
        _release_posting_claim(user_id, item_id, job_id)
        logger.error(f"Queue post enqueue failed for item {item_id}: {e}")
        return jsonify({'success': False, 'error': 'Gagal memasukkan tugas posting ke antrean. Silakan coba lagi.'}), 500
    return jsonify({'success': True})


# The lock ("job_id|epoch", services.job_locks) is taken just before the job is
# enqueued. It must outlive the time the job may wait in the queue behind other
# long article jobs; when the job starts it shortens the TTL to just above
# ARTICLE_JOB_TIMEOUT, and it deletes the lock when it ends. A lock older than
# job_locks.LOCK_GRACE_SECONDS whose job no longer exists is taken over.
REGENERATION_LOCK_TTL_SECONDS = 6 * 3600
REGENERATION_BUSY_ERROR = 'Artikel ini sedang dibuat ulang. Tunggu hingga prosesnya selesai.'


def _job_may_still_run(job_id):
    """True while job_id is queued or running. Unknown counts as running, so a
    Redis hiccup never lets a second regeneration through."""
    try:
        status = Job.fetch(job_id, connection=redis_conn).get_status(refresh=True)
    except NoSuchJobError:
        return False
    except Exception as e:
        logger.warning(f"Could not check job {job_id}: {e}")
        return True
    return str(getattr(status, 'value', status) or '') in {'queued', 'started', 'scheduled', 'deferred', 'created'}


def _take_regeneration_lock(log_id, job_id):
    """Atomically claim the post log for one regeneration. False when another
    regeneration of it is queued, running, or was requested moments ago."""
    return claim_lock(redis_conn, regeneration_lock_key(log_id), job_id, REGENERATION_LOCK_TTL_SECONDS,
                      is_alive=_job_may_still_run)


def _release_regeneration_lock(log_id, job_id):
    try:
        release_lock(redis_conn, regeneration_lock_key(log_id), job_id)
    except Exception as e:
        logger.warning(f"Could not release the regeneration lock of log {log_id}: {e}")


def _enqueue_paid_regeneration(user_id, log_id, task, job_timeout, missing_post_error, exclusive=False):
    """Shared flow of the regenerate-image / regenerate-article endpoints.

    exclusive=True allows one queued or running job per post log (article
    regeneration takes many minutes; a second click would charge twice and two
    jobs would overwrite the same post). The response carries the job id so the
    UI can follow it through /api/job-status.
    """
    with db.get_session() as session:
        log = session.query(PostLog).filter_by(id=log_id, user_id=user_id).first()
        if not log:
            return _error('Riwayat tidak ditemukan.', 404)
        if not log.post_id:
            return _error(missing_post_error, 400)

    job_id = f"regenerate-{log_id}-{uuid.uuid4().hex}"
    if exclusive:
        try:
            if not _take_regeneration_lock(log_id, job_id):
                return _error(REGENERATION_BUSY_ERROR, 409)
        except Exception as e:
            logger.error(f"Regeneration lock for log {log_id} unavailable: {e}")
            return _error('Gagal memasukkan tugas ke antrean. Silakan coba lagi.', 500)

    # Reserve the credit before enqueueing; the job settles it.
    if not db.reserve_user_credits(user_id, 1):
        if exclusive:
            _release_regeneration_lock(log_id, job_id)
        return jsonify({'success': False, 'error': 'Kredit tidak mencukupi.'}), 402

    try:
        q.enqueue(task, user_id, log_id, job_timeout=job_timeout, job_id=job_id)
    except Exception as e:
        db.refund_user_credits(user_id, 1)
        if exclusive:
            _release_regeneration_lock(log_id, job_id)
        logger.error(f"Enqueue of {task} failed for log {log_id}: {e}")
        return jsonify({'success': False, 'error': 'Gagal memasukkan tugas ke antrean. Silakan coba lagi.'}), 500
    return jsonify({'success': True, 'job_id': job_id})


@queue_bp.route('/api/queue/history/regenerate-image/<int:log_id>', methods=['POST'])
@require_jwt
def regenerate_image_api(user_id, log_id):
    return _enqueue_paid_regeneration(
        user_id, log_id, 'tasks.article_jobs.regenerate_image_job', '5m',
        'Gambar tidak dapat dibuat ulang: artikel ini tidak memiliki ID post WordPress.'
    )


@queue_bp.route('/api/queue/history/regenerate-article/<int:log_id>', methods=['POST'])
@require_jwt
def regenerate_article_api(user_id, log_id):
    return _enqueue_paid_regeneration(
        user_id, log_id, 'tasks.article_jobs.regenerate_article_job', ARTICLE_JOB_TIMEOUT,
        'Artikel tidak dapat dibuat ulang: artikel ini tidak memiliki ID post WordPress.',
        exclusive=True,
    )


def _trash_wordpress_post(site, post_id, log_id):
    """Move a post to the WordPress trash. Returns (deleted, error_message_or_None)."""
    ok, url_or_error = validate_public_http_url(site.wordpress_url)
    if not ok:
        return False, f'URL WordPress tidak valid: {url_or_error}'
    try:
        resp = requests.delete(
            f"{url_or_error}/wp-json/wp/v2/posts/{post_id}",
            auth=HTTPBasicAuth(site.wordpress_username, site.wordpress_password),
            timeout=10,
            allow_redirects=False
        )
    except Exception as e:
        logger.error(f"Failed to delete post from WP for log {log_id}: {e}")
        return False, 'Tidak dapat terhubung ke WordPress'
    # 404/410 means the post is already gone, which is the goal.
    if resp.status_code in (404, 410) or 200 <= resp.status_code < 300:
        return True, None
    return False, f'WordPress menolak penghapusan artikel (HTTP {resp.status_code})'


@queue_bp.route('/api/queue/history/<int:log_id>', methods=['DELETE'])
@require_jwt
def delete_history_log(user_id, log_id):
    wp_deleted = False
    wp_error = None
    with db.get_session() as session:
        log = session.query(PostLog).filter_by(id=log_id, user_id=user_id).first()
        if not log:
            return _error('Riwayat tidak ditemukan.', 404)

        # Best effort, as the UI promises ("will also attempt to delete the
        # article"): the post goes to the WordPress trash (recoverable), and a
        # WordPress failure never blocks removing the log.
        if log.post_id and log.site_id:
            site = session.query(WordPressSite).filter_by(id=log.site_id, user_id=user_id).first()
            if site and site.wordpress_url and site.wordpress_username and site.wordpress_password:
                wp_deleted, wp_error = _trash_wordpress_post(site, log.post_id, log_id)
                if wp_error:
                    logger.warning(f"WP delete for log {log_id} skipped/failed: {wp_error}")

        session.delete(log)
        session.commit()

    if wp_deleted:
        message = 'Riwayat dihapus dan artikel dipindahkan ke tempat sampah WordPress.'
    elif wp_error:
        message = f'Riwayat dihapus, tetapi artikel di WordPress tidak terhapus: {wp_error}'
    else:
        message = 'Riwayat berhasil dihapus.'
    # wp_deleted / wp_error let the UI tell "log removed but the article survived"
    # apart from a full success without parsing the message.
    return jsonify({'success': True, 'message': message, 'wp_deleted': wp_deleted, 'wp_error': wp_error})


@queue_bp.route('/manual-post', methods=['POST'])
@require_jwt
def manual_post(user_id):
    data = request.get_json(silent=True) or {}
    site_id = data.get('site_id')
    if not site_id:
        return _site_required()

    with db.get_session() as session:
        site = session.query(WordPressSite).filter_by(id=site_id, user_id=user_id).first()
        if not site:
            return _site_not_found()

    # Atomic credit reservation to prevent race conditions
    if not db.reserve_user_credits(user_id, 1):
        return _insufficient_credits()

    try:
        q.enqueue(
            'tasks.article_jobs.generate_and_post', user_id,
            site_id=site_id, credit_pre_reserved=True, manual=True, job_timeout=ARTICLE_JOB_TIMEOUT
        )
        return jsonify({'success': True, 'message': 'Artikel dijadwalkan untuk diposting'})
    except Exception as e:
        db.refund_user_credits(user_id, 1)
        logger.error(f"Manual post enqueue error: {e}")
        return jsonify({'success': False, 'error': 'Gagal memasukkan tugas posting ke antrean. Silakan coba lagi.'}), 500


def _job_return_value(job):
    """The finished job's return value when it is a JSON object, else None."""
    try:
        getter = getattr(job, 'return_value', None)
        value = getter() if callable(getter) else job.result
    except Exception as e:
        logger.warning(f"Could not read the result of job {job.id}: {e}")
        return None
    return value if isinstance(value, dict) else None


@queue_bp.route('/api/job-status/<job_id>', methods=['GET'])
@require_jwt
def job_status(user_id, job_id):
    # Job.fetch reads the job by id, so this serves jobs of every queue
    # (default and research).
    try:
        job = Job.fetch(job_id, connection=redis_conn)
        if job.args and job.args[0] != user_id:
            return _error('Tugas tidak ditemukan.', 404)
        status = job.get_status()
        status = str(getattr(status, 'value', status) or '')

        meta = job.meta or {}
        reports_progress = 'progress' in meta
        progress = max(0, min(100, int(meta.get('progress', 0) or 0)))
        message = meta.get('message') or 'Sedang diproses...'
        result = None
        if status == 'finished':
            progress = 100
            message = 'Selesai.'
            result = _job_return_value(job)
        elif status == 'failed':
            progress = 100
            message = 'Tugas gagal.'
        elif status == 'started' and not reports_progress:
            # Jobs that do not report progress (article posting) only say they run.
            progress = 50
            message = 'Sedang berjalan...'
        elif status == 'queued':
            message = meta.get('message') or 'Menunggu giliran di antrean...'

        try:
            timeout_seconds = int(job.timeout) if job.timeout else None
        except (TypeError, ValueError):
            timeout_seconds = None
        return jsonify({
            'success': True,
            'status': status,
            'progress': progress,
            'message': message,
            'result': result,
            # The job's RQ timeout, so the UI can size how long it keeps polling.
            'timeout_seconds': timeout_seconds,
        })
    except NoSuchJobError:
        return _error('Tugas tidak ditemukan.', 404)


@queue_bp.route('/test-generate', methods=['POST'])
@require_admin
def test_generate(user_id):
    # Admin-only debugging aid: it calls the configured AI provider without
    # charging credits, so it must not be open to all users.
    config = load_config(user_id)
    data = request.get_json(silent=True) or {}
    category_name = data.get('category', '')
    site_id = data.get('site_id')

    if not site_id:
        return _site_required()

    with db.get_session() as session:
        site = session.query(WordPressSite).filter_by(id=site_id, user_id=user_id).first()
        if not site:
            return _site_not_found()

        try:
            generator = ArticleGenerator.from_config(config)
            article = generator.generate_article(category_name, custom_prompt=site.article_prompt, site_name=site.site_name, language=site.language or 'id')
            return jsonify({'success': True, 'article': article})
        except Exception as e:
            logger.error(f"Test generate error: {e}")
            return _error('Uji pembuatan artikel gagal.', 500)
