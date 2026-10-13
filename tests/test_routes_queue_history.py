"""DELETE /api/queue/history/<id>: the log is always removed, and the response
says (machine-readably) whether the WordPress post went to the trash."""
import os
import unittest
from unittest.mock import Mock, patch

from cryptography.fernet import Fernet
from flask import Flask

os.environ.setdefault('FERNET_KEY', Fernet.generate_key().decode())

from models import PostLog, WordPressSite
from tests.test_routes_queue_post import load_queue_module, make_db


class DeleteHistoryLogTests(unittest.TestCase):
    def setUp(self):
        self.db = make_db()
        self.queue = load_queue_module(self.db, Mock())
        app = Flask(__name__)
        app.register_blueprint(self.queue.queue_bp)
        self.client = app.test_client()
        with self.db.get_session() as s:
            s.add(WordPressSite(id=3, user_id=1, site_name='S', wordpress_url='https://blog.example.com',
                                wordpress_username='u', wordpress_password='p'))
            s.add(PostLog(id=7, user_id=1, site_id=3, post_id=42, title='T', success=True))

    def delete(self, status_code=None, error=None):
        resp_mock = Mock(status_code=status_code)
        with patch.object(self.queue, 'validate_public_http_url', return_value=(True, 'https://blog.example.com')), \
                patch.object(self.queue.requests, 'delete', return_value=resp_mock, side_effect=error) as delete:
            resp = self.client.delete('/api/queue/history/7')
        return resp, delete

    def log_exists(self):
        with self.db.get_session() as s:
            return s.get(PostLog, 7) is not None

    def test_trashed_post(self):
        resp, delete = self.delete(status_code=200)
        body = resp.get_json()
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(body['wp_deleted'])
        self.assertIsNone(body['wp_error'])
        self.assertIn('/wp-json/wp/v2/posts/42', delete.call_args.args[0])
        self.assertFalse(self.log_exists())

    def test_wordpress_refusal_still_removes_log(self):
        resp, _ = self.delete(status_code=403)
        body = resp.get_json()
        self.assertTrue(body['success'])
        self.assertFalse(body['wp_deleted'])
        self.assertIn('HTTP 403', body['wp_error'])
        self.assertFalse(self.log_exists())

    def test_unreachable_wordpress(self):
        resp, _ = self.delete(error=ConnectionError('down'))
        body = resp.get_json()
        self.assertFalse(body['wp_deleted'])
        self.assertEqual(body['wp_error'], 'Tidak dapat terhubung ke WordPress')
        self.assertFalse(self.log_exists())

    def test_missing_log(self):
        resp = self.client.delete('/api/queue/history/999')
        self.assertEqual(resp.status_code, 404)


if __name__ == '__main__':
    unittest.main()
