"""Small Redis counters for per-user / per-IP limits that Flask-Limiter's
per-route decorators do not cover (failed logins, paid AI helper calls).

Every function fails open: a Redis outage must not take login or the AI
helpers offline, so errors are logged and the request is allowed.
"""
import logging

import core_extensions

logger = logging.getLogger(__name__)


def _conn():
    # Looked up at call time so tests can patch core_extensions.redis_conn.
    return core_extensions.redis_conn


def hit(key, limit, window_seconds):
    """Count one request against `key`. Returns (allowed, retry_after_seconds)."""
    conn = _conn()
    if conn is None:
        return True, 0
    try:
        count = conn.incr(key)
        if count == 1 or conn.ttl(key) < 0:
            conn.expire(key, window_seconds)
        if count > limit:
            return False, max(conn.ttl(key), 1)
    except Exception as e:
        logger.error(f"Rate limit check failed for {key}: {e}")
    return True, 0


def blocked(limits):
    """Check counters without counting. `limits` is [(key, max_count), ...].

    Returns (is_blocked, retry_after_seconds) for the first exhausted counter.
    """
    conn = _conn()
    if conn is None:
        return False, 0
    try:
        for key, max_count in limits:
            current = conn.get(key)
            if current and int(current) >= max_count:
                return True, max(conn.ttl(key), 1)
    except Exception as e:
        logger.warning(f"Rate limit check failed: {e}")
    return False, 0


def record(keys, window_seconds):
    """Count one event on each key (e.g. a failed login), resetting the window."""
    conn = _conn()
    if conn is None:
        return
    try:
        pipe = conn.pipeline()
        for key in keys:
            pipe.incr(key)
            pipe.expire(key, window_seconds)
        pipe.execute()
    except Exception as e:
        logger.warning(f"Could not record rate limit event: {e}")


def clear(key):
    conn = _conn()
    if conn is None:
        return
    try:
        conn.delete(key)
    except Exception as e:
        logger.warning(f"Could not clear rate limit counter {key}: {e}")
