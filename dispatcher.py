import time
import os
import logging
import random
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from redis import Redis
from rq import Queue, Worker
from rq.exceptions import NoSuchJobError
from rq.job import Job
from rq.registry import StartedJobRegistry, ScheduledJobRegistry, DeferredJobRegistry
from sqlalchemy import or_
from database import (
    Database, add_credits, RESEARCH_MAX_QUEUE_WAIT_SECONDS, RESEARCH_MIN_TIMEOUT_SECONDS,
    EARLY_REFRESH_MIN_AGE_DAYS, EARLY_REFRESH_MIN_TOPICS, RQ_LIVE_JOB_STATUSES, SCHEDULED_RESEARCH_REFRESH_DAYS,
    acquire_research_lock,
    active_research_job_id, category_key, read_research_charge, read_research_lock, release_research_lock,
    research_charge_job_ids, research_charge_owed, research_job_timeout, research_lock_key, research_lock_ttl,
    restore_research_charge, take_research_charge,
)
from models import ContentQueue, WordPressSite, User
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
# Research has its own queue and worker (research-worker), so a long research
# run never delays article posting. Keep the name in sync with core_extensions.
research_q = Queue('research', connection=redis_conn)

# Init DB
db = Database(Config.DATABASE_URL)

# A queue item is marked 'posting' before its job is enqueued with up to 50 minutes
# of jitter. If the worker dies or the job is lost, nothing ever resets it. Anything
# still 'posting' after this long, with no live RQ job owning it, is considered
# abandoned and returned to 'pending'.
STUCK_POSTING_TIMEOUT_MINUTES = 90

# An article job runs research, a writing brief, the article (with a quality
# correction pass), a helpfulness assessment, possibly a full rewrite and a
# second assessment, then up to two fact-check rounds and the image. On a slow
# model the worst case passed 25 minutes and RQ killed the job mid-pipeline.
# Keep in sync with ARTICLE_JOB_TIMEOUT in routes/queue.py, and below
# STUCK_POSTING_TIMEOUT_MINUTES (the sweep must never reset a running job).
GENERATE_AND_POST_JOB_TIMEOUT = '45m'

# RQ statuses in which a job may still run or is running.
LIVE_JOB_STATUSES = {'queued', 'started', 'scheduled', 'deferred', 'created'}


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


def _job_is_alive(job_id):
    """True while the RQ job can still run (or is running). Raises on Redis errors."""
    try:
        job = Job.fetch(job_id, connection=redis_conn)
    except NoSuchJobError:
        return False
    return _status_value(job.get_status(refresh=True)) in LIVE_JOB_STATUSES


def _status_value(status):
    return str(getattr(status, 'value', status) or '')


def _items_with_live_unclaimed_jobs():
    """Queue item ids referenced by a generate_and_post job that is still alive.

    Needed for items flipped to 'posting' by the web app, which enqueues the job
    without recording its id; the job records it (ContentQueue.job_id) only once
    it starts.
    """
    job_ids = set(q.get_job_ids())
    for registry in (StartedJobRegistry(queue=q), ScheduledJobRegistry(queue=q),
                     DeferredJobRegistry(queue=q)):
        job_ids.update(registry.get_job_ids())
    item_ids = set()
    for job in Job.fetch_many(list(job_ids), connection=redis_conn):
        if job is None or not (job.func_name or '').endswith('generate_and_post'):
            continue
        if _status_value(job.get_status(refresh=False)) not in LIVE_JOB_STATUSES:
            continue
        args, kwargs = job.args or (), job.kwargs or {}
        item_id = args[1] if len(args) > 1 else kwargs.get('item_id')
        if item_id:
            item_ids.add(int(item_id))
    return item_ids


def reset_stuck_queue_items():
    """Return abandoned 'posting' queue items to 'pending' so they get retried.

    An item is abandoned only when no live RQ job owns it. If its job was killed
    without running its own failure handling (SIGKILL, OOM, container restart)
    the 1-credit reservation for that attempt was never refunded, so it is
    refunded here, in the same row-locked transaction that resets the item. The
    job settles the reservation under the same lock and clears credit_held, so
    the two can never both refund it.
    """
    try:
        # Moves jobs whose worker died (expired entries) to failed, so their
        # status stops reading 'started'.
        StartedJobRegistry(queue=q).cleanup()
    except Exception as e:
        logger.warning(f"Could not clean up the started job registry: {e}")

    # posting_started_at is reset when the job actually starts, so the cutoff is
    # measured from job start, not from dispatch. It is a grace period that keeps
    # the sweep away from items that were just flipped and are being enqueued.
    cutoff = datetime.now() - timedelta(minutes=STUCK_POSTING_TIMEOUT_MINUTES)
    with db.get_session() as session:
        candidate_ids = [row[0] for row in session.query(ContentQueue.id).filter(
            ContentQueue.status == 'posting',
            or_(ContentQueue.posting_started_at.is_(None),
                ContentQueue.posting_started_at < cutoff)
        ).all()]
    if not candidate_ids:
        return

    unclaimed_live = None
    reset_count = 0
    for item_id in candidate_ids:
        try:
            with db.get_session() as session:
                item = session.query(ContentQueue).filter(
                    ContentQueue.id == item_id
                ).with_for_update().first()
                if not item or item.status != 'posting':
                    continue
                if item.posting_started_at and item.posting_started_at >= cutoff:
                    continue  # its job started again since the candidate query

                if item.job_id:
                    if _job_is_alive(item.job_id):
                        continue
                else:
                    if unclaimed_live is None:
                        unclaimed_live = _items_with_live_unclaimed_jobs()
                    if item.id in unclaimed_live:
                        continue

                # Refund only a reservation recorded on the row (credit_held):
                # the web app sets it together with the job id when it reserves,
                # and the job sets it when it reserves for scheduler items.
                # Rows left 'posting' by older code (no credit_held) are reset
                # without a refund, since nothing proves a credit was taken.
                refund = bool(item.credit_held)
                logger.warning(
                    f"Resetting stuck queue item id={item.id} (user_id={item.user_id}, "
                    f"site_id={item.site_id}, job_id={item.job_id}) from 'posting' back to "
                    f"'pending'{' and refunding its reserved credit' if refund else ''}."
                )
                if refund:
                    add_credits(session, item.user_id, 1)
                item.status = 'pending'
                item.posting_started_at = None
                item.job_id = None
                item.credit_held = False
                reset_count += 1
        except Exception as e:
            # Redis unreachable etc.: leave the item for the next sweep rather
            # than resetting something that may still be running.
            logger.error(f"Could not check stuck queue item id={item_id}: {e}")
    if reset_count:
        logger.info(f"Reset {reset_count} stuck queue item(s).")


def _schedule_gsc_sync(site):
    """Enqueue the daily Search Console sync for a site when it is due.

    Search Console intelligence is read-only and does not consume credits, so
    snapshots stay fresh even when auto-post is paused or the user's article
    credits are exhausted. Errors are logged here: a Redis or GSC failure used
    to abort the site's iteration and silently skip its auto-post.
    """
    site_id = site.id
    try:
        if not (site.gsc_refresh_token and site.gsc_property_url):
            return
        sync_due = (
            not site.gsc_last_synced_at
            or datetime.now() - site.gsc_last_synced_at >= timedelta(hours=24)
        )
        if not sync_due:
            return
        gsc_lock = f"scheduler:gsc_sync:{site_id}"
        if not redis_conn.set(gsc_lock, "1", nx=True, ex=6 * 3600):
            return
        try:
            q.enqueue(
                'tasks.gsc_jobs.sync_search_console_job',
                site.user_id,
                site_id,
                job_timeout='10m'
            )
            logger.info(f"Enqueued daily Search Console sync for site_id={site_id}")
        except Exception:
            redis_conn.delete(gsc_lock)
            raise
    except Exception as gsc_err:
        logger.error(f"Error scheduling Search Console sync for site_id={site_id}: {gsc_err}")


def _has_credits(site, user):
    """False (logged at most once an hour per site) when the owner has no credits."""
    if user and (user.credits or 0) > 0:
        return True
    lock_key_log = f"scheduler:log_credit_warning:{site.id}"
    if not redis_conn.get(lock_key_log):
        logger.info(f"Skipping auto-post for site_id={site.id}: user_id={site.user_id} has insufficient credits.")
        redis_conn.setex(lock_key_log, 3600, "1")
    return False


def _site_timezone(site):
    """Returns (tz name, ZoneInfo), falling back to Asia/Jakarta for an invalid name."""
    tz_name = site.timezone or 'Asia/Jakarta'
    try:
        return tz_name, ZoneInfo(tz_name)
    except Exception as e:
        logger.error(f"Invalid timezone '{tz_name}' for site_id={site.id}, falling back to Asia/Jakarta: {e}")
        return tz_name, ZoneInfo('Asia/Jakarta')


def _claim_next_queue_item(session, site, job_id):
    """Flip the oldest pending queue item to 'posting' for job_id. Returns it, or None."""
    queue_item = session.query(ContentQueue).filter_by(
        user_id=site.user_id,
        site_id=site.id,
        status='pending'
    ).order_by(ContentQueue.created_at.asc()).with_for_update(skip_locked=True).first()
    if queue_item:
        queue_item.status = 'posting'  # Mark as posting to prevent duplicate pickup
        # Baseline only; the job resets it when it starts.
        queue_item.posting_started_at = datetime.now()
        queue_item.job_id = job_id
        queue_item.credit_held = False
        session.commit()
    return queue_item


def _dispatch_auto_post(session, site):
    """Enqueue this hour's generate_and_post for a site, once per scheduled hour."""
    user_id = site.user_id
    site_id = site.id
    tz_name, tz = _site_timezone(site)
    now_site = datetime.now(tz)
    current_hour = now_site.hour

    schedule_hours = site.schedule_hours or '0,6,12,18'
    hours_list = [int(h.strip()) for h in schedule_hours.split(',') if h.strip().isdigit()]
    if current_hour not in hours_list:
        return

    lock_key = f"scheduler:last_run_post:{site_id}:{now_site.strftime('%Y-%m-%d %H')}"
    if not redis_conn.set(lock_key, "1", nx=True, ex=7200):
        return
    delay_minutes = random.randint(0, 50)

    # The scheduler does not reserve credit; the job reserves it itself once it
    # has claimed the item. Recording the job id up front lets the stuck-item
    # sweep see that the (delayed) job is still scheduled.
    job_id = str(uuid.uuid4())
    queue_item = _claim_next_queue_item(session, site, job_id)
    item_id = queue_item.id if queue_item else None

    logger.info(
        f"Enqueueing generate_and_post for user_id={user_id}, site_id={site_id}, item_id={item_id} "
        f"(delayed by {delay_minutes}m, hour={current_hour} in {tz_name})"
    )
    try:
        q.enqueue_in(
            timedelta(minutes=delay_minutes),
            'tasks.article_jobs.generate_and_post',
            user_id,
            item_id,
            site_id,
            job_timeout=GENERATE_AND_POST_JOB_TIMEOUT,
            job_id=job_id
        )
    except Exception:
        # Rollback: release lock and revert queue item status
        redis_conn.delete(lock_key)
        if queue_item:
            queue_item.status = 'pending'
            queue_item.posting_started_at = None
            queue_item.job_id = None
            session.commit()
        raise


# ---- Research: daily refresh, reservation reconciliation, retention ----

# Scheduled research runs once a day per site, in this hour of the site's
# timezone (00:00-00:59). Each site starts at its own minute offset within the
# first RESEARCH_SCHEDULE_SPREAD_MINUTES, so all sites of one timezone do not
# hit the research worker at once; the remaining minutes of the hour leave room
# to retry a pass skipped because a manual run holds the site's lock.
RESEARCH_SCHEDULE_HOUR = 0
RESEARCH_SCHEDULE_SPREAD_MINUTES = 50
RESEARCH_SCHEDULE_KEY_TTL_SECONDS = 2 * 86400
RESEARCH_WORKER_WARNING_KEY = 'scheduler:log_research_worker_warning'
RESEARCH_WORKER_WARNING_INTERVAL_SECONDS = 3600


def _job_status_or_missing(job_id):
    """RQ status of job_id as a string, 'missing' when the job no longer exists."""
    try:
        job = Job.fetch(job_id, connection=redis_conn)
    except NoSuchJobError:
        return 'missing'
    return _status_value(job.get_status(refresh=True)) or 'missing'


def _cancel_research_job(job_id):
    """Cancel a research job that never started, so it cannot start later. Returns its status."""
    try:
        Job.fetch(job_id, connection=redis_conn).cancel()
    except NoSuchJobError:
        return 'missing'
    except Exception as e:
        logger.warning(f"Could not cancel research job {job_id}: {e}")
    return _job_status_or_missing(job_id)


def _research_schedule_offset(site_id):
    """Minute of the schedule hour at which this site's daily research may start."""
    try:
        return int(site_id) % RESEARCH_SCHEDULE_SPREAD_MINUTES
    except (TypeError, ValueError):
        return 0


def _stale_research_categories(site, now=None):
    """Selected category names whose newest usable research is missing or older than
    SCHEDULED_RESEARCH_REFRESH_DAYS (monthly), one per normalized name (first spelling).

    Refreshing days before research expires (MAX_RESEARCH_AGE_DAYS) keeps
    auto-posting from silently losing its research. A category whose unused
    article topics dropped below EARLY_REFRESH_MIN_TOPICS is refreshed early,
    once its research is at least EARLY_REFRESH_MIN_AGE_DAYS old.
    """
    latest_by_key = {}
    for name, researched_at in db.latest_research_times(site.user_id, site.id).items():
        key = category_key(name)
        if researched_at and (key not in latest_by_key or researched_at > latest_by_key[key]):
            latest_by_key[key] = researched_at
    topics_by_key = {}
    for name, count in db.unused_research_topic_counts(site.user_id, site.id).items():
        key = category_key(name)
        topics_by_key[key] = topics_by_key.get(key, 0) + count
    # researched_at is local naive time (database.save_research_data).
    now = now or datetime.now()
    cutoff = now - timedelta(days=SCHEDULED_RESEARCH_REFRESH_DAYS)
    early_cutoff = now - timedelta(days=EARLY_REFRESH_MIN_AGE_DAYS)
    stale, seen = [], set()
    for cat in site.selected_categories or []:
        name = cat.get('name') if isinstance(cat, dict) else None
        if not isinstance(name, str) or not name.strip():
            continue
        key = category_key(name)
        if key in seen:
            continue
        seen.add(key)
        researched_at = latest_by_key.get(key)
        if researched_at is None or researched_at < cutoff:
            stale.append(name)
        elif researched_at < early_cutoff and topics_by_key.get(key, 0) < EARLY_REFRESH_MIN_TOPICS:
            logger.info(f"Category '{name}' of site_id={site.id} has {topics_by_key.get(key, 0)} unused "
                        "research topic(s) left; refreshing its research early.")
            stale.append(name)
    return stale


def _schedule_daily_research(site, now_site=None):
    """Enqueue the site's free daily research refresh, at most once per site-local day.

    Only for sites that auto-post (the research feeds those articles) and only
    for categories that need it. Skipped while another research job (e.g. a
    manual run) holds the site's lock. Returns the job id when one was enqueued.
    """
    site_id = site.id
    try:
        if not (site.auto_post and site.selected_categories):
            return None
        if now_site is None:
            _tz_name, tz = _site_timezone(site)
            now_site = datetime.now(tz)
        if now_site.hour != RESEARCH_SCHEDULE_HOUR or now_site.minute < _research_schedule_offset(site_id):
            return None
        schedule_key = f"research_sched:{site_id}:{now_site.strftime('%Y-%m-%d')}"
        if redis_conn.exists(schedule_key):
            return None

        stale = _stale_research_categories(site)
        if not stale:
            redis_conn.set(schedule_key, 'fresh', nx=True, ex=RESEARCH_SCHEDULE_KEY_TTL_SECONDS)
            return None
        if active_research_job_id(redis_conn, site_id, _job_status_or_missing):
            return None  # a research job is queued or running; try again on the next pass

        job_id = f"research-sched-{site_id}-{uuid.uuid4().hex}"
        timeout_seconds = research_job_timeout(len(stale))
        if not acquire_research_lock(redis_conn, site_id, job_id, ttl_seconds=research_lock_ttl(len(stale))):
            return None
        if not redis_conn.set(schedule_key, job_id, nx=True, ex=RESEARCH_SCHEDULE_KEY_TTL_SECONDS):
            release_research_lock(redis_conn, site_id, job_id)
            return None
        try:
            # force=False: free, never charged, never refunds.
            research_q.enqueue(
                'tasks.research_jobs.deep_research_job',
                site.user_id, False, site_id, None,
                categories=stale,
                job_timeout=timeout_seconds,
                job_id=job_id,
            )
        except Exception:
            redis_conn.delete(schedule_key)
            release_research_lock(redis_conn, site_id, job_id)
            raise
        logger.info(f"Enqueued scheduled research for site_id={site_id}: {', '.join(stale)}")
        return job_id
    except Exception as e:
        logger.error(f"Error scheduling research for site_id={site_id}: {e}")
        return None


def _reconcilable_status(job_id, age, timeout):
    """The job's status when its reservation may be settled now, else None.

    A job still 'queued' after RESEARCH_MAX_QUEUE_WAIT_SECONDS means no worker
    serves the research queue: it is cancelled first, so it can never start
    after its credits were refunded.
    """
    if age < timeout:
        return None
    status = _job_status_or_missing(job_id)
    if status == 'queued' and age >= RESEARCH_MAX_QUEUE_WAIT_SECONDS:
        logger.warning(f"Research job {job_id} waited {int(age)}s without starting; cancelling it.")
        status = _cancel_research_job(job_id)
    if status in RQ_LIVE_JOB_STATUSES:
        return None
    return status


def reconcile_research_charges(now=None):
    """Refund manual research reservations whose job will never settle them.

    The web app records each reservation (research_charge:{job_id}) and the job
    removes it when it settles. A record that outlives its job's timeout while
    the job is failed, stopped or gone means the work horse was killed (SIGKILL,
    OOM) before any of the job's own refund code ran; a job that never started
    within RESEARCH_MAX_QUEUE_WAIT_SECONDS is cancelled and refunded. The record
    is taken with an atomic GETDEL, so the job and this sweep can never both
    refund it. A record put back after a failed refund (needs_refund) is
    refunded even when its job finished.
    """
    try:
        # Moves jobs whose worker died to failed, so they stop reading 'started'.
        StartedJobRegistry(queue=research_q).cleanup()
    except Exception as e:
        logger.warning(f"Could not clean up the research started job registry: {e}")

    now = time.time() if now is None else now
    refunded_total = 0
    for job_id in research_charge_job_ids(redis_conn):
        try:
            record = read_research_charge(redis_conn, job_id)
            if not record:
                continue
            age = now - float(record.get('created_at') or 0)
            status = _reconcilable_status(job_id, age, int(record.get('timeout') or RESEARCH_MIN_TIMEOUT_SECONDS))
            if status is None:
                continue
            record = take_research_charge(redis_conn, job_id)
            if record is None:
                continue  # settled by the job in the meantime
            if status != 'finished' or record.get('needs_refund'):
                # A finished job settled its own reservation (it only leaves the
                # record behind when Redis failed it, or hands it back marked
                # needs_refund when its refund failed); anything else did not.
                owed = research_charge_owed(record)
                if owed:
                    try:
                        db.refund_user_credits(record['user_id'], owed)
                    except Exception:
                        # Put it back for the next sweep rather than losing it.
                        restore_research_charge(redis_conn, job_id, record, owed=owed)
                        raise
                    refunded_total += owed
                    logger.warning(
                        f"Refunded {owed} research credit(s) to user_id={record['user_id']}: "
                        f"job {job_id} ended as '{status}' without settling its reservation."
                    )
            release_research_lock(redis_conn, record.get('site_id'), job_id)
        except Exception as e:
            logger.error(f"Could not reconcile research reservation {job_id}: {e}")
    return refunded_total


def release_stale_research_locks(now=None):
    """Clear site research locks whose job ended without releasing them, and
    cancel a job that has waited in the queue too long (no research worker)."""
    now = time.time() if now is None else now
    prefix = research_lock_key('')
    for key in redis_conn.scan_iter(match=prefix + '*', count=200):
        key = key.decode('utf-8') if isinstance(key, bytes) else key
        site_id = key[len(prefix):]
        try:
            job_id, created = read_research_lock(redis_conn, site_id)
            if job_id and created is not None and now - created >= RESEARCH_MAX_QUEUE_WAIT_SECONDS \
                    and _job_status_or_missing(job_id) == 'queued':
                logger.warning(f"Research job {job_id} for site_id={site_id} never started; cancelling it.")
                _cancel_research_job(job_id)
            active_research_job_id(redis_conn, site_id, _job_status_or_missing, now=now)
        except Exception as e:
            logger.error(f"Could not check the research lock of site_id={site_id}: {e}")


def warn_if_research_worker_missing():
    """Warn (at most hourly) when research jobs wait but no worker serves the queue."""
    try:
        waiting = research_q.count
        if not waiting or Worker.count(connection=redis_conn, queue=research_q) > 0:
            return False
    except Exception as e:
        logger.warning(f"Could not check the research workers: {e}")
        return False
    if redis_conn.set(RESEARCH_WORKER_WARNING_KEY, '1', nx=True, ex=RESEARCH_WORKER_WARNING_INTERVAL_SECONDS):
        logger.warning(
            f"{waiting} research job(s) are waiting but no worker listens on the 'research' queue. "
            "Start the research-worker service (rq worker research)."
        )
    return True


def cleanup_old_research_daily():
    """Once a day, delete old research rows (keeping the latest runs per category)."""
    cleanup_key = f"research_cleanup:{datetime.now().strftime('%Y-%m-%d')}"
    if not redis_conn.set(cleanup_key, '1', nx=True, ex=RESEARCH_SCHEDULE_KEY_TTL_SECONDS):
        return None
    try:
        deleted = db.cleanup_old_research()
    except Exception:
        redis_conn.delete(cleanup_key)  # retry on a later pass
        raise
    if deleted:
        logger.info(f"Deleted {deleted} old research row(s).")
    return deleted


def run_research_maintenance():
    for name, task in (('reconcile research reservations', reconcile_research_charges),
                       ('release stale research locks', release_stale_research_locks),
                       ('check research workers', warn_if_research_worker_missing),
                       ('clean up old research', cleanup_old_research_daily)):
        try:
            task()
        except Exception as e:
            logger.error(f"Could not {name}: {e}")


def dispatch_jobs():
    with db.get_session() as session:
        sites = session.query(WordPressSite).filter_by(is_active=True).all()
        if not sites:
            return

        # Batch load users to prevent N+1 queries
        user_ids = list({site.user_id for site in sites})
        users_dict = {user.id: user for user in session.query(User).filter(User.id.in_(user_ids)).all()}

        for site in sites:
            try:
                _schedule_gsc_sync(site)
                # Free, so it does not depend on the owner's credits.
                _schedule_daily_research(site)
                if not _has_credits(site, users_dict.get(site.user_id)):
                    continue
                if site.auto_post and site.selected_categories:
                    try:
                        _dispatch_auto_post(session, site)
                    except Exception as e:
                        logger.error(f"Error checking auto post schedule for site_id={site.id}: {e}")
            except Exception as loop_err:
                logger.error(f"Error processing site_id={site.id}: {loop_err}")


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
            run_research_maintenance()
        pass_count += 1

        # Check every 60 seconds to reduce CPU and DB overhead
        time.sleep(60)
