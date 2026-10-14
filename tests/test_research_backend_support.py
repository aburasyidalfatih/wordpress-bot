"""Shared fakes for the research backend tests (no test cases here).

FakeRedis implements the handful of commands the research lock, reservation
records and rate limits use, including the two Lua scripts, with a manual clock.
"""
import fnmatch
import importlib
import logging
import sys
import types
from functools import wraps
from unittest.mock import Mock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Database
from models import Base


def _b(value):
    return value if isinstance(value, bytes) else str(value).encode()


class FakeRedis:
    def __init__(self):
        self.data = {}
        self.expiry = {}
        self.now = 1000.0

    def advance(self, seconds):
        self.now += seconds

    def _purge(self, key):
        if key in self.expiry and self.expiry[key] <= self.now:
            self.data.pop(key, None)
            self.expiry.pop(key, None)

    def set(self, key, value, nx=False, xx=False, ex=None, keepttl=False):
        self._purge(key)
        exists = key in self.data
        if (nx and exists) or (xx and not exists):
            return None
        self.data[key] = _b(value)
        if ex is not None:
            self.expiry[key] = self.now + int(ex)
        elif not keepttl:
            self.expiry.pop(key, None)
        return True

    def setex(self, key, seconds, value):
        return self.set(key, value, ex=seconds)

    def get(self, key):
        self._purge(key)
        return self.data.get(key)

    def getdel(self, key):
        value = self.get(key)
        self.data.pop(key, None)
        self.expiry.pop(key, None)
        return value

    def delete(self, *keys):
        removed = 0
        for key in keys:
            self._purge(key)
            if key in self.data:
                removed += 1
            self.data.pop(key, None)
            self.expiry.pop(key, None)
        return removed

    def exists(self, *keys):
        return sum(1 for key in keys if self.get(key) is not None)

    def ttl(self, key):
        self._purge(key)
        if key not in self.data:
            return -2
        if key not in self.expiry:
            return -1
        return int(self.expiry[key] - self.now)

    def expire(self, key, seconds):
        if self.get(key) is None:
            return False
        self.expiry[key] = self.now + int(seconds)
        return True

    def incr(self, key):
        value = int(self.get(key) or 0) + 1
        self.set(key, value, keepttl=True)
        return value

    def scan_iter(self, match=None, count=None):
        for key in list(self.data):
            self._purge(key)
            if key in self.data and (match is None or fnmatch.fnmatchcase(key, match)):
                yield key.encode()

    def eval(self, script, numkeys, *args):
        keys, argv = args[:numkeys], args[numkeys:]
        if "string.sub" in script:  # research lock compare-and-delete ("job_id" or "job_id|epoch")
            value = self.get(keys[0])
            owner = _b(argv[0])
            if value is not None and (value == owner or value.startswith(owner + b'|')):
                return self.delete(keys[0])
            return 0
        if "DECR" in script:
            value = int(self.get(keys[0]) or 0)
            if value > 0:
                self.set(keys[0], value - 1, keepttl=True)
                return value - 1
            return value
        raise NotImplementedError(script)


def make_db():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    database = Database.__new__(Database)
    database.engine = engine
    database.session_factory = sessionmaker(bind=engine)
    return database


def stub_core_extensions(user_id=1):
    """A core_extensions stand-in: no Redis/Postgres, require_jwt injects user_id."""
    core = types.ModuleType('core_extensions')
    core.db = None
    core.q = None
    core.research_q = None
    core.trending = None
    core.redis_conn = None
    core.logger = logging.getLogger('test-research-backend')
    core.load_config = lambda *a, **k: {}
    for name in ('send_telegram_notification', 'post_to_telegram_channel', 'post_to_facebook_page',
                 'post_to_twitter', 'post_to_threads', 'post_to_pinterest'):
        setattr(core, name, Mock())

    def require_jwt(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            return f(user_id, *args, **kwargs)
        return wrapper

    core.require_jwt = require_jwt
    core.require_admin = require_jwt
    return core


def load_with_stubbed_core(module_name, extra=()):
    """Import module_name (fresh) against a stubbed core_extensions."""
    core = stub_core_extensions()
    names = (module_name, 'routes.prompts', 'rate_limit') + tuple(extra)
    with patch.dict(sys.modules, {'core_extensions': core}):
        for name in names:
            sys.modules.pop(name, None)
        module = importlib.import_module(module_name)
    for name in names:
        sys.modules.pop(name, None)
    return module, core
