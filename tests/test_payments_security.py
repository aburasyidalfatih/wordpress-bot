import io
import os
import shutil
import sys
import tempfile
import types
import unittest
from contextlib import contextmanager
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

from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import core_extensions
from models import Base, User, Transaction
from routes import payments, admin

PNG = b'\x89PNG\r\n\x1a\n' + b'\x00' * 32
USER_ID = 1
ADMIN_ID = 2


class SqliteDb:
    """Minimal stand-in for database.Database backed by in-memory SQLite."""

    def __init__(self):
        self.engine = create_engine('sqlite://', poolclass=StaticPool,
                                    connect_args={'check_same_thread': False})
        Base.metadata.create_all(self.engine, tables=[User.__table__, Transaction.__table__])
        self.session_factory = sessionmaker(bind=self.engine)

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
        return {}


def payment_settings(**overrides):
    settings = {
        'PAYMENT_TRIPAY_ENABLED': True, 'PAYMENT_PAYPAL_ENABLED': True, 'PAYMENT_MANUAL_ENABLED': True,
        'TRIPAY_API_KEY': 'k', 'TRIPAY_PRIVATE_KEY': 'p', 'TRIPAY_MERCHANT_CODE': 'm',
        'TRIPAY_API_URL': 'https://tripay.test', 'PAYPAL_CLIENT_ID': 'client', 'PAYPAL_SECRET': 'secret',
        'PAYPAL_API_URL': 'https://paypal.test', 'PAYMENT_USD_RATE': 16000.0,
        'MANUAL_BANK_NAME': 'B', 'MANUAL_BANK_ACCOUNT': '1', 'MANUAL_BANK_HOLDER': 'H', 'ADMIN_WHATSAPP': '',
        'SMTP_SENDER_EMAIL': '', 'SMTP_USER': '', 'STARSENDER_DEVICE_ID': '', 'ALLOW_MOCK_PAYMENTS': False,
    }
    settings.update(overrides)
    return settings


def paypal_order(invoice_id, value='6.25', status='APPROVED', currency='USD'):
    return {
        'id': 'ORDER123', 'status': status,
        'purchase_units': [{'reference_id': invoice_id, 'custom_id': invoice_id,
                            'amount': {'currency_code': currency, 'value': value}}],
    }


def paypal_capture_response(invoice_id, value='6.25', currency='USD'):
    return {
        'id': 'ORDER123', 'status': 'COMPLETED',
        'purchase_units': [{'reference_id': invoice_id, 'payments': {'captures': [{
            'status': 'COMPLETED', 'custom_id': invoice_id,
            'amount': {'currency_code': currency, 'value': value}}]}}],
    }


def http_response(status_code, body):
    return Mock(status_code=status_code, json=Mock(return_value=body), text=str(body))


class ReceiptDetectionTests(unittest.TestCase):
    def test_known_signatures(self):
        self.assertEqual(payments.detect_receipt_type(b'\xff\xd8\xff\xe0rest'), 'jpg')
        self.assertEqual(payments.detect_receipt_type(PNG[:16]), 'png')
        self.assertEqual(payments.detect_receipt_type(b'RIFF\x00\x00\x00\x00WEBPVP8 '), 'webp')
        self.assertEqual(payments.detect_receipt_type(b'%PDF-1.7\n'), 'pdf')

    def test_rejects_markup_and_svg(self):
        self.assertIsNone(payments.detect_receipt_type(b'<html><script>'))
        self.assertIsNone(payments.detect_receipt_type(b'<svg xmlns='))


class VerifyPayPalOrderTests(unittest.TestCase):
    expected = payments._paypal_amount('6.25')

    def test_matching_order(self):
        self.assertTrue(payments.verify_paypal_order(paypal_order('INV-1'), 'INV-1', self.expected)[0])

    def test_other_invoice_rejected(self):
        self.assertFalse(payments.verify_paypal_order(paypal_order('INV-2'), 'INV-1', self.expected)[0])

    def test_amount_and_currency_checked(self):
        self.assertFalse(payments.verify_paypal_order(paypal_order('INV-1', value='0.01'), 'INV-1', self.expected)[0])
        self.assertFalse(payments.verify_paypal_order(paypal_order('INV-1', currency='EUR'), 'INV-1', self.expected)[0])

    def test_completed_order_uses_captured_amount(self):
        self.assertTrue(payments.verify_paypal_order(paypal_capture_response('INV-1'), 'INV-1', self.expected)[0])
        self.assertFalse(payments.verify_paypal_order(
            paypal_capture_response('INV-1', value='1.00'), 'INV-1', self.expected)[0])

    def test_signed_amount_survives_rate_change(self):
        # Quoted 6.25 at invoice time; the admin has since changed the rate so
        # today's expected amount would be 5.00.
        order = paypal_order('INV-1')
        order['purchase_units'][0]['custom_id'] = payments.sign_paypal_custom_id('INV-1', '6.25')
        self.assertTrue(payments.verify_paypal_order(order, 'INV-1', payments._paypal_amount('5.00'))[0])

    def test_forged_signed_amount_rejected(self):
        order = paypal_order('INV-1', value='0.01')
        order['purchase_units'][0]['custom_id'] = 'INV-1|0.01|' + '0' * 32
        self.assertFalse(payments.verify_paypal_order(order, 'INV-1', self.expected)[0])
        # A valid signature for another invoice does not transfer.
        order = paypal_order('INV-2', value='0.01')
        order['purchase_units'][0]['custom_id'] = payments.sign_paypal_custom_id('INV-2', '0.01')
        self.assertFalse(payments.verify_paypal_order(order, 'INV-1', self.expected)[0])


class PaymentRouteTestCase(unittest.TestCase):
    def setUp(self):
        self.db = SqliteDb()
        with self.db.get_session() as session:
            session.add(User(id=USER_ID, email='u@example.com', credits=3, role='user', is_active=True))
            session.add(User(id=ADMIN_ID, email='a@example.com', credits=0, role='admin', is_active=True))

        self.upload_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.upload_dir, True)
        self.settings = payment_settings()
        self.current_user = USER_ID
        self.http = Mock()

        patches = [
            patch.object(core_extensions, 'db', self.db),
            patch.object(payments, 'db', self.db),
            patch.object(admin, 'db', self.db),
            patch.object(payments, 'UPLOAD_FOLDER', self.upload_dir),
            patch.object(payments, 'requests', self.http),
            patch.object(payments, 'get_payment_settings', lambda: self.settings),
            patch.object(payments, 'get_paypal_access_token', lambda settings=None: 'token'),
            patch.object(core_extensions, 'authenticate_token', lambda token: self.current_user),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

        app = Flask(__name__)
        app.register_blueprint(payments.payments_bp)
        app.register_blueprint(admin.admin_bp)
        self.client = app.test_client()

    def add_tx(self, invoice_id, method, status, credits=50, amount=100000):
        with self.db.get_session() as session:
            tx = Transaction(user_id=USER_ID, payment_method=method, invoice_id=invoice_id,
                             credits_purchased=credits, amount=amount, status=status)
            session.add(tx)
            session.flush()
            return tx.id

    def tx_status(self, invoice_id):
        with self.db.get_session() as session:
            return session.query(Transaction).filter_by(invoice_id=invoice_id).one().status

    def credits(self):
        with self.db.get_session() as session:
            return session.query(User).filter_by(id=USER_ID).one().credits

    def post(self, url, **kwargs):
        return self.client.post(url, headers={'Authorization': 'Bearer test'}, **kwargs)


class FulfillTransactionTests(PaymentRouteTestCase):
    def test_second_fulfilment_is_a_no_op(self):
        tx_id = self.add_tx('INV-F', 'tripay', 'pending')
        with self.db.get_session() as session:
            self.assertEqual(payments.fulfill_transaction(session, tx_id, ('pending',)), 50)
        with self.db.get_session() as session:
            self.assertIsNone(payments.fulfill_transaction(session, tx_id, ('pending',)))
        self.assertEqual(self.credits(), 53)
        self.assertEqual(self.tx_status('INV-F'), 'success')

    def test_payment_method_guard(self):
        tx_id = self.add_tx('INV-M', 'manual', 'pending')
        with self.db.get_session() as session:
            self.assertIsNone(payments.fulfill_transaction(session, tx_id, ('pending',), payment_method='tripay'))
        self.assertEqual(self.credits(), 3)


class PayPalCaptureTests(PaymentRouteTestCase):
    def capture(self, invoice_id, order_id='ORDER123'):
        return self.post('/api/payments/paypal-capture', json={'order_id': order_id, 'invoice_id': invoice_id})

    def test_verified_capture_credits_once(self):
        self.add_tx('INV-P', 'paypal', 'pending')
        self.http.get.return_value = http_response(200, paypal_order('INV-P'))
        self.http.post.return_value = http_response(201, paypal_capture_response('INV-P'))

        self.assertEqual(self.capture('INV-P').status_code, 200)
        self.assertEqual(self.credits(), 53)
        self.assertEqual(self.capture('INV-P').status_code, 400)
        self.assertEqual(self.credits(), 53)

    def test_order_for_another_invoice_is_not_captured(self):
        self.add_tx('INV-P', 'paypal', 'pending')
        self.http.get.return_value = http_response(200, paypal_order('INV-CHEAP', value='6.25'))

        self.assertEqual(self.capture('INV-P').status_code, 400)
        self.http.post.assert_not_called()
        self.assertEqual(self.credits(), 3)
        self.assertEqual(self.tx_status('INV-P'), 'pending')

    def test_underpaid_order_is_not_captured(self):
        self.add_tx('INV-P', 'paypal', 'pending')
        self.http.get.return_value = http_response(200, paypal_order('INV-P', value='0.50'))

        self.assertEqual(self.capture('INV-P').status_code, 400)
        self.http.post.assert_not_called()
        self.assertEqual(self.credits(), 3)

    def test_mock_order_rejected_when_paypal_is_live(self):
        self.settings['ALLOW_MOCK_PAYMENTS'] = True
        self.add_tx('INV-P', 'paypal', 'pending')
        self.assertEqual(self.capture('INV-P', order_id='PAY-MOCK-ABC').status_code, 403)
        self.assertEqual(self.credits(), 3)

    def test_mock_order_allowed_only_in_mock_mode(self):
        self.settings.update(ALLOW_MOCK_PAYMENTS=True, PAYPAL_CLIENT_ID='MOCK_ID', PAYPAL_SECRET='MOCK_SECRET')
        self.add_tx('INV-P', 'paypal', 'pending')
        self.assertEqual(self.capture('INV-P', order_id='PAY-MOCK-ABC').status_code, 200)
        self.assertEqual(self.credits(), 53)

    def test_non_paypal_transaction_rejected(self):
        self.settings.update(ALLOW_MOCK_PAYMENTS=True, PAYPAL_CLIENT_ID='MOCK_ID', PAYPAL_SECRET='MOCK_SECRET')
        self.add_tx('INV-M', 'manual', 'pending')
        self.assertEqual(self.capture('INV-M', order_id='PAY-MOCK-ABC').status_code, 400)
        self.assertEqual(self.credits(), 3)


class ReceiptUploadTests(PaymentRouteTestCase):
    def upload(self, invoice_id, content, filename):
        return self.post('/api/payments/upload-receipt', data={
            'invoice_id': invoice_id, 'receipt': (io.BytesIO(content), filename)},
            content_type='multipart/form-data')

    def test_valid_png_saved_under_random_name(self):
        self.add_tx('INV-R', 'manual', 'pending')
        resp = self.upload('INV-R', PNG, '../../evil name.png')
        self.assertEqual(resp.status_code, 200)
        saved = os.listdir(self.upload_dir)
        self.assertEqual(len(saved), 1)
        self.assertRegex(saved[0], r'^[0-9a-f]{32}\.png$')
        self.assertEqual(self.tx_status('INV-R'), 'awaiting_approval')

    def test_html_disguised_as_image_rejected(self):
        self.add_tx('INV-R', 'manual', 'pending')
        resp = self.upload('INV-R', b'<html><script>alert(1)</script>', 'x.png')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(os.listdir(self.upload_dir), [])

    def test_disallowed_extension_rejected(self):
        self.add_tx('INV-R', 'manual', 'pending')
        self.assertEqual(self.upload('INV-R', PNG, 'x.html').status_code, 400)

    def test_oversized_file_rejected(self):
        self.add_tx('INV-R', 'manual', 'pending')
        big = PNG + b'\x00' * payments.MAX_RECEIPT_BYTES
        self.assertEqual(self.upload('INV-R', big, 'x.png').status_code, 413)

    def test_settled_transaction_not_reopened(self):
        self.add_tx('INV-R', 'manual', 'success')
        self.assertEqual(self.upload('INV-R', PNG, 'x.png').status_code, 409)
        self.assertEqual(self.tx_status('INV-R'), 'success')
        self.assertEqual(os.listdir(self.upload_dir), [])

    def test_gateway_transaction_rejected(self):
        self.add_tx('INV-T', 'tripay', 'pending')
        self.assertEqual(self.upload('INV-T', PNG, 'x.png').status_code, 400)
        self.assertEqual(self.tx_status('INV-T'), 'pending')


class AdminApprovalTests(PaymentRouteTestCase):
    def setUp(self):
        super().setUp()
        self.current_user = ADMIN_ID
        notifier = patch.object(admin, 'send_email_notification', Mock())
        notifier.start()
        self.addCleanup(notifier.stop)

    def test_double_approve_credits_once(self):
        tx_id = self.add_tx('INV-A', 'manual', 'awaiting_approval')
        self.assertEqual(self.post(f'/api/admin/payments/{tx_id}/approve').status_code, 200)
        self.assertEqual(self.post(f'/api/admin/payments/{tx_id}/approve').status_code, 400)
        self.assertEqual(self.credits(), 53)

    def test_reject_after_approve_does_not_change_status(self):
        tx_id = self.add_tx('INV-A', 'manual', 'awaiting_approval')
        self.post(f'/api/admin/payments/{tx_id}/approve')
        self.assertEqual(self.post(f'/api/admin/payments/{tx_id}/reject').status_code, 400)
        self.assertEqual(self.tx_status('INV-A'), 'success')


class TripayWebhookTests(PaymentRouteTestCase):
    def webhook(self, body):
        import hashlib
        import hmac
        import json
        raw = json.dumps(body).encode()
        signature = hmac.new(b'p', raw, hashlib.sha256).hexdigest()
        return self.client.post('/api/payments/webhook/tripay', data=raw, content_type='application/json',
                                headers={'X-Callback-Signature': signature})

    def test_repeated_callback_credits_once(self):
        self.add_tx('INV-T', 'tripay', 'pending')
        for _ in range(3):
            self.assertEqual(self.webhook({'merchant_ref': 'INV-T', 'status': 'PAID'}).status_code, 200)
        self.assertEqual(self.credits(), 53)

    def test_callback_cannot_settle_manual_invoice(self):
        self.add_tx('INV-M', 'manual', 'pending')
        self.webhook({'merchant_ref': 'INV-M', 'status': 'PAID'})
        self.assertEqual(self.credits(), 3)
        self.assertEqual(self.tx_status('INV-M'), 'pending')


if __name__ == '__main__':
    unittest.main()
