"""Redis locks held by RQ jobs, with atomic compare-and-set/expire/delete.

A lock value is "owner|epoch": the owner is the RQ job id (or a random token)
and the epoch is when the lock was taken. Web routes take a lock for a job
they are about to enqueue, so for a short while the lock names a job that does
not exist in RQ yet; a lock younger than LOCK_GRACE_SECONDS is therefore always
treated as busy, and only an older lock whose job is gone is taken over, with a
compare-and-set so two requests racing for a stale lock cannot both win.

Every conditional write is a Lua script (one atomic Redis call). The scripts are
module constants so test fakes can recognise and emulate them.
"""
import time

# A lock taken this recently counts as busy even when its job is not (yet)
# visible in RQ: the route enqueues the job only after the credit reservation.
LOCK_GRACE_SECONDS = 120

# Value matches the owner when it is "owner" or starts with "owner|".
_OWNER_MATCH = "local v = redis.call('GET', KEYS[1]) " \
               "local own = v and (v == ARGV[1] or string.sub(v, 1, string.len(ARGV[1]) + 1) == ARGV[1] .. '|') "

# KEYS[1]; ARGV[1] expected exact value, ARGV[2] new value, ARGV[3] TTL seconds.
COMPARE_AND_SET_LUA = (
    "if redis.call('GET', KEYS[1]) == ARGV[1] then "
    "redis.call('SET', KEYS[1], ARGV[2], 'EX', tonumber(ARGV[3])) return 1 end return 0"
)
# KEYS[1]; ARGV[1] owner, ARGV[2] TTL seconds.
OWNER_EXPIRE_LUA = _OWNER_MATCH + "if own then return redis.call('EXPIRE', KEYS[1], tonumber(ARGV[2])) end return 0"
# KEYS[1]; ARGV[1] owner.
OWNER_DELETE_LUA = _OWNER_MATCH + "if own then return redis.call('DEL', KEYS[1]) end return 0"


def _text(value):
    return value.decode('utf-8') if isinstance(value, bytes) else value


def lock_value(owner, now=None):
    return f"{owner}|{int(now if now is not None else time.time())}"


def parse_lock_value(raw):
    """(owner, epoch or None) of a lock value; (None, None) for no lock."""
    raw = _text(raw)
    if not raw:
        return None, None
    owner, _, created = raw.rpartition('|')
    if not owner:
        return raw, None
    try:
        return owner, float(created)
    except ValueError:
        return raw, None


def compare_and_set(conn, key, expected, new_value, ttl_seconds):
    """Set key to new_value (with TTL) only while it still holds `expected`."""
    return bool(conn.eval(COMPARE_AND_SET_LUA, 1, key, expected, new_value, int(ttl_seconds)))


def refresh_lock(conn, key, owner, ttl_seconds):
    """Reset the TTL while owner holds the lock. False when it does not."""
    return bool(conn.eval(OWNER_EXPIRE_LUA, 1, key, owner, int(ttl_seconds)))


def release_lock(conn, key, owner):
    """Delete the lock while owner holds it. False when it does not."""
    return bool(conn.eval(OWNER_DELETE_LUA, 1, key, owner))


def claim_lock(conn, key, owner, ttl_seconds, is_alive, now=None, grace_seconds=LOCK_GRACE_SECONDS):
    """Take key for owner. True when taken, or already held by owner (TTL reset).

    is_alive(holder) tells whether the holding job may still run; it is asked
    only about locks older than grace_seconds (or without a recorded time).
    """
    now = time.time() if now is None else now
    value = lock_value(owner, now)
    if conn.set(key, value, nx=True, ex=int(ttl_seconds)):
        return True
    raw = _text(conn.get(key))
    if raw is None:  # released or expired in between
        return bool(conn.set(key, value, nx=True, ex=int(ttl_seconds)))
    holder, created = parse_lock_value(raw)
    if holder == owner:
        return refresh_lock(conn, key, owner, ttl_seconds)
    if created is not None and now - created < grace_seconds:
        return False
    if is_alive(holder):
        return False
    return compare_and_set(conn, key, raw, value, ttl_seconds)


# ---------------------------------------------------------------------------
# Keys shared by the web routes that take a lock and the jobs that hold it
# ---------------------------------------------------------------------------

def regeneration_lock_key(log_id):
    """Held while an article regeneration of this post log is queued or running."""
    return f"regenerate_article_lock:{log_id}"


def gsc_sync_lock_key(site_id):
    """Held while a Search Console sync of this site is queued (manual) or running."""
    return f"gsc_sync_lock:{site_id}"


LIVE_JOB_STATUSES = frozenset({'queued', 'started', 'scheduled', 'deferred', 'created'})


def rq_job_may_run(connection, job_id):
    """True while job_id is queued or running in RQ. An unknown state counts as
    running, so a Redis hiccup never lets a second job through."""
    try:
        from rq.exceptions import NoSuchJobError
        from rq.job import Job
        try:
            status = Job.fetch(job_id, connection=connection).get_status(refresh=True)
        except NoSuchJobError:
            return False
        return str(getattr(status, 'value', status) or '') in LIVE_JOB_STATUSES
    except Exception:
        return True

