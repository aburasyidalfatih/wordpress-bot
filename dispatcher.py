import time
import os
import logging
import random
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from redis import Redis
from rq import Queue
from database import Database
from models import WordPressSite, User
from config import Config

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('dispatcher')

# Init Redis and Queue
redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
redis_conn = Redis.from_url(redis_url, protocol=2)
q = Queue('default', connection=redis_conn)

# Init DB
db = Database(Config.DATABASE_URL)

# A queue item is marked 'posting' before its job is enqueued with up to 50 minutes
# of jitter. If the worker dies or the job is lost, nothing ever resets it. Anything
# still 'posting' after this long is considered abandoned and returned to 'pending'.
STUCK_POSTING_TIMEOUT_MINUTES = 90


# Monitoring used to hardcode scheduler_running=True, so a dead dispatcher still
# showed green. It now writes a heartbeat each pass; the monitor treats a missing
# or expired key as "not running". TTL is generous enough to survive one slow pass.
HEARTBEAT_KEY = 'scheduler:heartbeat'
HEARTBEAT_TTL_SECONDS = 180


def write_heartbeat():
    try:
        redis_conn.setex(HEARTBEAT_KEY, HEARTBEAT_TTL_SECONDS, datetime.now().isoformat())
    except Exception as e:
        logger.warning(f"Could not write scheduler heartbeat: {e}")


def reset_stuck_queue_items():
    """Return abandoned 'posting' queue items to 'pending' so they get retried."""
    from models import ContentQueue

    cutoff = datetime.now() - timedelta(minutes=STUCK_POSTING_TIMEOUT_MINUTES)
    with db.get_session() as session:
        stuck = session.query(ContentQueue).filter(
            ContentQueue.status == 'posting',
            ContentQueue.posting_started_at.isnot(None),
            ContentQueue.posting_started_at < cutoff
        ).all()
        for item in stuck:
            logger.warning(
                f"Resetting stuck queue item id={item.id} (user_id={item.user_id}, "
                f"site_id={item.site_id}) from 'posting' back to 'pending'."
            )
            item.status = 'pending'
            item.posting_started_at = None
        if stuck:
            logger.info(f"Reset {len(stuck)} stuck queue item(s).")


def dispatch_jobs():
    with db.get_session() as session:
        # Get all active WordPress sites
        sites = session.query(WordPressSite).filter_by(is_active=True).all()
        if not sites:
            return
        
        # Batch load users to prevent N+1 queries
        user_ids = list(set([site.user_id for site in sites]))
        users = session.query(User).filter(User.id.in_(user_ids)).all()
        users_dict = {user.id: user for user in users}
        
        for site in sites:
            try:
                user_id = site.user_id
                site_id = site.id
                user = users_dict.get(user_id)

                # Search Console intelligence is read-only and does not consume
                # credits. Keep snapshots fresh even when auto-post is paused or
                # the user's article credits are exhausted.
                if site.gsc_refresh_token and site.gsc_property_url:
                    sync_due = (
                        not site.gsc_last_synced_at
                        or datetime.now() - site.gsc_last_synced_at >= timedelta(hours=24)
                    )
                    if sync_due:
                        gsc_lock = f"scheduler:gsc_sync:{site_id}"
                        if redis_conn.set(gsc_lock, "1", nx=True, ex=6 * 3600):
                            try:
                                q.enqueue(
                                    'tasks.gsc_jobs.sync_search_console_job',
                                    user_id,
                                    site_id,
                                    job_timeout='10m'
                                )
                                logger.info(f"Enqueued daily Search Console sync for site_id={site_id}")
                            except Exception:
                                redis_conn.delete(gsc_lock)
                                raise
                
                # Check user credits
                if not user or (user.credits or 0) <= 0:
                    # Log only once every hour to avoid spamming the log
                    lock_key_log = f"scheduler:log_credit_warning:{site_id}"
                    has_logged = redis_conn.get(lock_key_log)
                    if not has_logged:
                        logger.info(f"Skipping auto-post for site_id={site_id}: user_id={user_id} has insufficient credits.")
                        redis_conn.setex(lock_key_log, 3600, "1")
                    continue
                
                tz_name = site.timezone or 'Asia/Jakarta'
                try:
                    tz = ZoneInfo(tz_name)
                except Exception as e:
                    logger.error(f"Invalid timezone '{tz_name}' for site_id={site_id}, falling back to Asia/Jakarta: {e}")
                    tz = ZoneInfo('Asia/Jakarta')
                
                now_site = datetime.now(tz)
                current_hour = now_site.hour
                current_hour_str = now_site.strftime("%Y-%m-%d %H")
                
                # 1. Check auto post
                if site.auto_post and site.selected_categories:
                    schedule_hours = site.schedule_hours or '0,6,12,18'
                    try:
                        hours_list = [int(h.strip()) for h in schedule_hours.split(',') if h.strip().isdigit()]
                        if current_hour in hours_list:
                            lock_key = f"scheduler:last_run_post:{site_id}:{current_hour_str}"
                            lock_set = redis_conn.set(lock_key, "1", nx=True, ex=7200)
                            if not lock_set:
                                continue
                            delay_minutes = random.randint(0, 50)
                            
                            # Check if there is a pending item in ContentQueue (pick oldest pending)
                            from models import ContentQueue
                            queue_item = session.query(ContentQueue).filter_by(
                                user_id=user_id, 
                                site_id=site_id, 
                                status='pending'
                            ).order_by(ContentQueue.created_at.asc()).first()
                            
                            item_id = None
                            if queue_item:
                                item_id = queue_item.id
                                queue_item.status = 'posting' # Mark as posting to prevent duplicate pickup
                                queue_item.posting_started_at = datetime.now()
                                session.commit()
                            
                            logger.info(f"Enqueueing generate_and_post for user_id={user_id}, site_id={site_id}, item_id={item_id} (delayed by {delay_minutes}m, hour={current_hour} in {tz_name})")
                            try:
                                q.enqueue_in(
                                    timedelta(minutes=delay_minutes),
                                    'tasks.article_jobs.generate_and_post',
                                    user_id,
                                    item_id,
                                    site_id,
                                    job_timeout='10m'
                                )
                            except Exception:
                                # Rollback: release lock and revert queue item status
                                redis_conn.delete(lock_key)
                                if queue_item:
                                    queue_item.status = 'pending'
                                    session.commit()
                                raise
                    except Exception as e:
                        logger.error(f"Error checking auto post schedule for site_id={site_id}: {e}")
            except Exception as loop_err:
                logger.error(f"Error processing site_id={site.id}: {loop_err}")
                continue
            
            # Auto research scheduler check removed since manual research is used instead.

if __name__ == '__main__':
    logger.info("Dispatcher started.")

    # Only sweep for abandoned queue items every Nth pass; it is a cheap query but
    # there is no point running it once a minute.
    STUCK_SWEEP_EVERY_N_PASSES = 10
    pass_count = 0

    while True:
        # Written before the work so a slow or failing pass still reports "alive";
        # only a genuinely dead process lets the key expire.
        write_heartbeat()

        try:
            dispatch_jobs()
        except Exception as e:
            logger.error(f"Error in scheduler main loop: {e}")

        if pass_count % STUCK_SWEEP_EVERY_N_PASSES == 0:
            try:
                reset_stuck_queue_items()
            except Exception as e:
                logger.error(f"Error resetting stuck queue items: {e}")
        pass_count += 1

        # Check every 60 seconds to reduce CPU and DB overhead
        time.sleep(60)
