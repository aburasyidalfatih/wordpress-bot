"""Admin AI settings: provider validation, keys never echoed back, model listing."""
import os
import sys
import tempfile
import types
import unittest
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

import anthropic
import httpx2
from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import core_extensions
from database import Database
from models import Base, User
from routes import admin

ADMIN_ID = 1


def make_db():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    database = Database.__new__(Database)
    database.engine = engine
    database.session_factory = sessionmaker(bind=engine)
    return database


class AdminAiConfigTests(unittest.TestCase):
    def setUp(self):
        self.db = make_db()
        with self.db.get_session() as session:
            session.add(User(id=ADMIN_ID, email='a@example.com', role='admin', is_active=True))
        self.stored = {'ai_text_provider': 'gemini', 'ai_image_provider': 'gemini',
                       'gemini_api_key': 'g-key', 'anthropic_api_key': '', 'openai_api_key': ''}
        self.saved = []
        env_file = tempfile.NamedTemporaryFile(delete=False, suffix='.env')
        env_file.close()
        self.addCleanup(os.unlink, env_file.name)

        patches = [
            patch.object(core_extensions, 'db', self.db),
            patch.object(admin, 'db', self.db),
            patch.object(core_extensions, 'authenticate_token', lambda token: ADMIN_ID),
            patch.object(admin, 'load_config', lambda user_id=None: dict(self.stored)),
            patch.object(admin, 'save_config', lambda user_id, data: self.saved.append(data)),
            patch.object(admin, 'bump_settings_version', Mock()),
            patch.object(admin, 'ENV_FILE_PATH', env_file.name),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        app = Flask(__name__)
        app.register_blueprint(admin.admin_bp)
        self.client = app.test_client()
        self.auth = {'Authorization': 'Bearer test'}

    def put(self, body):
        return self.client.put('/api/admin/config', json=body, headers=self.auth)

    def test_selecting_a_provider_without_key_is_rejected(self):
        resp = self.put({'ai_text_provider': 'anthropic'})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('Claude', resp.get_json()['error'])
        self.assertEqual(self.saved, [])

    def test_provider_with_key_in_same_request_is_saved(self):
        resp = self.put({'ai_text_provider': 'anthropic', 'anthropic_api_key': ' sk-ant-x ',
                         'anthropic_model': 'claude-sonnet-5-5', 'ai_image_provider': 'gemini'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.saved[-1]['ai_text_provider'], 'anthropic')
        self.assertEqual(self.saved[-1]['anthropic_api_key'], 'sk-ant-x')
        self.assertEqual(self.saved[-1]['anthropic_model'], 'claude-sonnet-5-5')

    def test_unknown_provider_and_bad_model_are_rejected(self):
        self.assertEqual(self.put({'ai_image_provider': 'anthropic'}).status_code, 400)
        self.assertEqual(self.put({'openai_model': 'x' * 101}).status_code, 400)

    def test_research_model_accepts_empty_and_supported_models(self):
        for value in ('', 'claude-sonnet-5-5', ' claude-opus-5-5 '):
            resp = self.put({'anthropic_research_model': value})
            self.assertEqual(resp.status_code, 200, value)
            self.assertEqual(self.saved[-1]['anthropic_research_model'], value.strip())

    def test_research_model_rejects_unsupported_models(self):
        resp = self.put({'anthropic_research_model': 'gpt-5'})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('Model riset web tidak didukung', resp.get_json()['error'])

        resp = self.put({'anthropic_research_model': 'claude-haiku-5-5'})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.get_json()['error'],
                         'Model Haiku tidak didukung untuk riset web (web search/fetch). '
                         'Pilih Claude Sonnet 5.5 atau Opus 5.5.')
        self.assertEqual(self.saved, [])

    def test_get_config_returns_the_research_model(self):
        self.stored['anthropic_research_model'] = 'claude-sonnet-5-5'
        data = self.client.get('/api/admin/config', headers=self.auth).get_json()
        self.assertEqual(data['config']['anthropic_research_model'], 'claude-sonnet-5-5')

    def test_research_model_is_stored_and_defaults_to_empty(self):
        # Real Database.save_config / get_config on SQLite.
        self.assertEqual(self.db.get_config(ADMIN_ID)['anthropic_research_model'], '')
        self.db.save_config(ADMIN_ID, {'anthropic_research_model': 'claude-sonnet-5-5'})
        config = self.db.get_config(ADMIN_ID)
        self.assertEqual(config['anthropic_research_model'], 'claude-sonnet-5-5')
        # The text model is untouched and the research model does not follow it.
        self.assertEqual(config['anthropic_model'], 'claude-opus-5-5')
        self.db.save_config(ADMIN_ID, {'anthropic_research_model': ''})
        self.assertEqual(self.db.get_config(ADMIN_ID)['anthropic_research_model'], '')

    def test_blank_key_keeps_the_stored_one(self):
        self.put({'gemini_api_key': '   ', 'gemini_model': 'gemini-3.5-flash'})
        self.assertNotIn('gemini_api_key', self.saved[-1])

    def test_get_config_reports_saved_keys_without_returning_them(self):
        self.stored['anthropic_api_key'] = 'secret'
        data = self.client.get('/api/admin/config', headers=self.auth).get_json()
        self.assertTrue(data['config']['has_anthropic_api_key'])
        self.assertEqual(data['config']['anthropic_api_key'], '')
        self.assertNotIn('secret', str(data))

    def test_model_list_prefers_typed_key_and_maps_errors(self):
        with patch.object(admin, 'list_models', Mock(return_value=['gpt-5.5'])) as listing:
            resp = self.client.post('/api/admin/ai-models', headers=self.auth,
                                    json={'provider': 'openai', 'api_key': 'typed'})
        self.assertEqual(resp.get_json(), {'success': True, 'models': ['gpt-5.5']})
        listing.assert_called_once_with('openai', 'typed')

        error = anthropic.APIStatusError(
            'bad key', response=httpx2.Response(401, request=httpx2.Request('GET', 'https://x')), body=None)
        self.stored['anthropic_api_key'] = 'stored'
        with patch.object(admin, 'list_models', Mock(side_effect=error)):
            resp = self.client.post('/api/admin/ai-models', headers=self.auth, json={'provider': 'anthropic'})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('tidak valid', resp.get_json()['error'])

    def test_model_list_needs_a_key(self):
        resp = self.client.post('/api/admin/ai-models', headers=self.auth, json={'provider': 'openai'})
        self.assertEqual(resp.status_code, 400)


if __name__ == '__main__':
    unittest.main()
