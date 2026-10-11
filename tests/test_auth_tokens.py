import os
import sys
import time
import types
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

os.environ.setdefault('DATABASE_URL', 'postgresql://test:test@127.0.0.1:1/test')
# The optimizer/trend modules pull in heavy ML deps that are irrelevant here.
for _name, _attr in (('ml_optimizer', 'ContentOptimizer'), ('trending_research', 'TrendingResearch')):
    try:
        __import__(_name)
    except Exception:
        _stub = types.ModuleType(_name)
        setattr(_stub, _attr, lambda *a, **k: None)
        sys.modules[_name] = _stub

import jwt
from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from werkzeug.security import generate_password_hash

import core_extensions
from config import Config
from models import Base, User
from routes import auth, settings as settings_routes


class SqliteDb:
    def __init__(self):
        self.engine = create_engine('sqlite://', poolclass=StaticPool,
                                    connect_args={'check_same_thread': False})
        Base.metadata.create_all(self.engine, tables=[User.__table__])
        self.session_factory = sessionmaker(bind=self.engine)
        self.system_settings = {}

    @contextmanager
    def get_session(self):
        session = self.session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get_system_settings(self):
        return dict(self.system_settings)


class FakeRedis:
    """Just enough of redis.Redis for counters and revocation timestamps."""

    def __init__(self):
        self.data = {}

    def get(self, key):
        value = self.data.get(key)
        return None if value is None else str(value).encode()

    def set(self, key, value, ex=None):
        self.data[key] = value

    def incr(self, key):
        self.data[key] = int(self.data.get(key, 0)) + 1
        return self.data[key]

    def expire(self, key, seconds):
        return True

    def ttl(self, key):
        return 300

    def delete(self, key):
        self.data.pop(key, None)

    def exists(self, key):
        return int(key in self.data)

    def pipeline(self):
        redis = self

        class Pipe:
            def __init__(self):
                self.ops = []

            def incr(self, key):
                self.ops.append(lambda: redis.incr(key))

            def expire(self, key, seconds):
                self.ops.append(lambda: redis.expire(key, seconds))

            def execute(self):
                return [op() for op in self.ops]

        return Pipe()


class AuthTestCase(unittest.TestCase):
    def setUp(self):
        self.db = SqliteDb()
        self.redis = FakeRedis()
        with self.db.get_session() as session:
            session.add(User(id=1, email='u@example.com', is_active=True, role='user',
                             password_hash=generate_password_hash('correct-password')))
            session.add(User(id=2, email='off@example.com', is_active=False, role='user'))
        for p in (
            patch.object(core_extensions, 'db', self.db),
            patch.object(core_extensions, 'redis_conn', self.redis),
            patch.object(auth, 'db', self.db),
            patch.object(auth, 'redis_conn', self.redis),
            patch.object(settings_routes, 'db', self.db),
        ):
            p.start()
            self.addCleanup(p.stop)
        core_extensions._user_auth_cache.clear()
        self.addCleanup(core_extensions._user_auth_cache.clear)

        app = Flask(__name__)
        app.config['SECRET_KEY'] = 'test'
        app.register_blueprint(auth.auth_bp)
        app.register_blueprint(settings_routes.settings_bp)
        self.client = app.test_client()


class AccessTokenTests(AuthTestCase):
    def test_issued_token_authenticates(self):
        self.assertEqual(core_extensions.authenticate_token(core_extensions.issue_access_token(1)), 1)

    def test_legacy_token_without_typ_still_accepted(self):
        legacy = jwt.encode({'user_id': 1, 'exp': datetime.now(timezone.utc) + timedelta(days=1)},
                            Config.SECRET_KEY, algorithm='HS256')
        self.assertEqual(core_extensions.authenticate_token(legacy), 1)

    def test_oauth_state_token_rejected(self):
        state = jwt.encode({'purpose': 'gsc_oauth', 'user_id': 1, 'site_id': 3,
                            'exp': datetime.now(timezone.utc) + timedelta(minutes=10)},
                           Config.SECRET_KEY, algorithm='HS256')
        self.assertIsNone(core_extensions.authenticate_token(state))

    def test_other_token_type_rejected(self):
        token = jwt.encode({'user_id': 1, 'typ': 'refresh'}, Config.SECRET_KEY, algorithm='HS256')
        self.assertIsNone(core_extensions.authenticate_token(token))

    def test_inactive_or_missing_user_rejected(self):
        self.assertIsNone(core_extensions.authenticate_token(core_extensions.issue_access_token(2)))
        self.assertIsNone(core_extensions.authenticate_token(core_extensions.issue_access_token(99)))

    def test_revoked_tokens_rejected(self):
        old = jwt.encode({'user_id': 1, 'typ': 'access', 'iat': int(time.time()) - 60},
                         Config.SECRET_KEY, algorithm='HS256')
        legacy = jwt.encode({'user_id': 1}, Config.SECRET_KEY, algorithm='HS256')
        core_extensions.revoke_user_tokens(1)
        self.assertIsNone(core_extensions.authenticate_token(old))
        self.assertIsNone(core_extensions.authenticate_token(legacy))
        self.assertEqual(core_extensions.authenticate_token(core_extensions.issue_access_token(1)), 1)

    def test_logout_revokes_legacy_tokens(self):
        # Tokens without a jti cannot be singled out, so logout revokes them all.
        old = jwt.encode({'user_id': 1, 'typ': 'access', 'iat': int(time.time()) - 60},
                         Config.SECRET_KEY, algorithm='HS256')
        self.client.post('/logout', headers={'Authorization': f'Bearer {old}'})
        self.assertIsNone(core_extensions.authenticate_token(old))

    def test_logout_revokes_only_this_device(self):
        this_device = core_extensions.issue_access_token(1)
        other_device = core_extensions.issue_access_token(1)
        self.client.post('/logout', headers={'Authorization': f'Bearer {this_device}'})
        self.assertIsNone(core_extensions.authenticate_token(this_device))
        self.assertEqual(core_extensions.authenticate_token(other_device), 1)

    def test_logout_rejects_get(self):
        token = core_extensions.issue_access_token(1)
        resp = self.client.get('/logout', headers={'Authorization': f'Bearer {token}'})
        self.assertEqual(resp.status_code, 405)
        self.assertEqual(core_extensions.authenticate_token(token), 1)

    def test_password_change_revokes_other_sessions_and_reissues(self):
        old = jwt.encode({'user_id': 1, 'typ': 'access', 'iat': int(time.time()) - 60},
                         Config.SECRET_KEY, algorithm='HS256')
        resp = self.client.post('/api/profile', json={'password': 'new-password-123'},
                                headers={'Authorization': f'Bearer {old}'})
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(core_extensions.authenticate_token(old))
        self.assertEqual(core_extensions.authenticate_token(resp.get_json()['token']), 1)


class LoginRateLimitTests(AuthTestCase):
    def login(self, email, password, ip='10.0.0.1'):
        return self.client.post('/api/login', json={'email': email, 'password': password},
                                environ_base={'REMOTE_ADDR': ip})

    def test_successful_logins_are_not_counted(self):
        for _ in range(8):
            self.assertEqual(self.login('u@example.com', 'correct-password').status_code, 200)

    def test_failures_lock_only_that_ip_and_email(self):
        for _ in range(auth.LOGIN_MAX_FAILURES_PER_ACCOUNT):
            self.assertEqual(self.login('u@example.com', 'wrong').status_code, 401)
        self.assertEqual(self.login('u@example.com', 'correct-password').status_code, 429)
        self.assertEqual(self.login('u@example.com', 'correct-password', ip='10.0.0.2').status_code, 200)
        self.assertEqual(self.login('other@example.com', 'wrong').status_code, 401)


class GoogleTokenTests(unittest.TestCase):
    def tokeninfo(self, **overrides):
        info = {'aud': 'client-id', 'iss': 'https://accounts.google.com', 'email_verified': 'true',
                'email': 'u@example.com', 'sub': '123'}
        info.update(overrides)
        return Mock(status_code=200, json=Mock(return_value=info))

    def test_fails_closed_without_client_id(self):
        with patch.object(auth, 'configured_google_client_id', return_value=''), \
                patch.object(auth.requests, 'get') as get:
            self.assertIsNone(auth.verify_google_token('tok'))
            get.assert_not_called()

    def test_checks_audience_issuer_and_verified_email(self):
        with patch.object(auth, 'configured_google_client_id', return_value='client-id'), \
                patch.object(auth.requests, 'get') as get:
            get.return_value = self.tokeninfo()
            self.assertIsNotNone(auth.verify_google_token('tok'))
            get.return_value = self.tokeninfo(aud='other-app')
            self.assertIsNone(auth.verify_google_token('tok'))
            get.return_value = self.tokeninfo(iss='https://evil.example')
            self.assertIsNone(auth.verify_google_token('tok'))
            get.return_value = self.tokeninfo(email_verified='false')
            self.assertIsNone(auth.verify_google_token('tok'))


class SystemSettingsRefreshTests(unittest.TestCase):
    def test_reloads_only_when_version_changes(self):
        fake_db = SqliteDb()
        fake_db.system_settings = {'__settings_version__': 'v2', 'MANUAL_BANK_NAME': 'Bank Baru',
                                   'PAYMENT_USD_RATE': '15500'}
        state = {'version': 'v1', 'checked_at': 0.0}
        with patch.object(core_extensions, 'db', fake_db), \
                patch.object(core_extensions, '_settings_state', state), \
                patch.object(core_extensions, '_read_settings_version', return_value='v2'), \
                patch.object(Config, 'MANUAL_BANK_NAME', 'Bank Lama'), \
                patch.object(Config, 'PAYMENT_USD_RATE', 16000.0), \
                patch.dict(os.environ, {}):
            self.assertTrue(core_extensions.refresh_system_settings_if_changed(force=True))
            self.assertEqual(Config.MANUAL_BANK_NAME, 'Bank Baru')
            self.assertEqual(Config.PAYMENT_USD_RATE, 15500.0)
            self.assertFalse(core_extensions.refresh_system_settings_if_changed(force=True))
            # Throttled: no DB check within the refresh interval.
            self.assertFalse(core_extensions.refresh_system_settings_if_changed())

    def test_invalid_usd_rate_is_ignored(self):
        with patch.object(Config, 'PAYMENT_USD_RATE', 16000.0), patch.dict(os.environ, {}):
            core_extensions.apply_system_settings({'PAYMENT_USD_RATE': '0'})
            self.assertEqual(Config.PAYMENT_USD_RATE, 16000.0)


if __name__ == '__main__':
    unittest.main()
