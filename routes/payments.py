import os
import uuid
import hmac
import hashlib
import math
import re
import secrets
from datetime import datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode
from flask import Blueprint, request, jsonify
from sqlalchemy import func
import requests

from core_extensions import db, logger, require_jwt, authenticate_token, send_email_notification, send_whatsapp_notification
from config import Config
from models import User, Transaction

payments_bp = Blueprint('payments', __name__)
VALID_PAYMENT_METHODS = {'manual', 'tripay', 'paypal'}
PAYPAL_ORDER_ID_RE = re.compile(r'[A-Za-z0-9-]{1,64}')

# Ensure uploads directory exists
UPLOAD_FOLDER = os.path.join('static', 'uploads', 'receipts')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

MAX_RECEIPT_BYTES = 5 * 1024 * 1024
ALLOWED_RECEIPT_EXTENSIONS = {'jpg', 'jpeg', 'png', 'webp', 'pdf'}
# Status a manual transaction may be in when a (re-)upload is accepted.
RECEIPT_UPLOADABLE_STATUSES = ('pending', 'awaiting_approval')


def detect_receipt_type(head):
    """Identify an uploaded receipt from its magic bytes. Returns the extension to store, or None."""
    if head.startswith(b'\xff\xd8\xff'):
        return 'jpg'
    if head.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'png'
    if len(head) >= 12 and head[:4] == b'RIFF' and head[8:12] == b'WEBP':
        return 'webp'
    if head.startswith(b'%PDF-'):
        return 'pdf'
    return None


def fulfill_transaction(session, transaction_id, from_statuses, payment_method=None):
    """Atomically mark a transaction successful and credit its user.

    The conditional UPDATE row-locks the transaction, so of any number of
    concurrent callers (webhook retries, double-clicked approve, parallel
    captures) exactly one sees rowcount == 1 and grants the credits. Credits are
    added with an SQL increment so they cannot clobber concurrent reservations.
    Returns the transaction's credits_purchased if this call fulfilled it, else None.
    The caller's session commit makes both updates durable together.
    """
    query = session.query(Transaction).filter(
        Transaction.id == transaction_id,
        Transaction.status.in_(tuple(from_statuses)),
    )
    if payment_method:
        query = query.filter(Transaction.payment_method == payment_method)
    if query.update({Transaction.status: 'success'}, synchronize_session=False) != 1:
        return None

    tx_user_id, credits = session.query(Transaction.user_id, Transaction.credits_purchased).filter(
        Transaction.id == transaction_id
    ).one()
    credits = int(credits or 0)
    session.query(User).filter(User.id == tx_user_id).update({
        User.credits: func.coalesce(User.credits, 0) + credits,
        User.tier: 'pro',
    }, synchronize_session=False)
    return credits

# Helper function to generate Tripay signature
def _is_mock_value(value):
    return not value or str(value).startswith('MOCK')

def _setting_value(system_settings, key, default):
    value = system_settings.get(key)
    if value is None or value == '':
        return default
    return value

def _setting_bool(system_settings, key, default):
    if key not in system_settings or system_settings[key] in (None, ''):
        return default
    return str(system_settings[key]).lower() == 'true'

def _setting_float(system_settings, key, default):
    try:
        return float(_setting_value(system_settings, key, default))
    except (TypeError, ValueError):
        return default

def _usd_rate(system_settings):
    rate = _setting_float(system_settings, 'PAYMENT_USD_RATE', Config.PAYMENT_USD_RATE)
    if math.isfinite(rate) and rate > 0:
        return rate
    logger.error(f"Ignoring invalid PAYMENT_USD_RATE {rate!r}")
    return Config.PAYMENT_USD_RATE if Config.PAYMENT_USD_RATE > 0 else 16000.0

def get_payment_settings():
    try:
        system_settings = db.get_system_settings()
    except Exception as e:
        logger.error(f"Failed to read payment settings from database: {e}")
        system_settings = {}

    return {
        'PAYMENT_TRIPAY_ENABLED': _setting_bool(system_settings, 'PAYMENT_TRIPAY_ENABLED', Config.PAYMENT_TRIPAY_ENABLED),
        'PAYMENT_PAYPAL_ENABLED': _setting_bool(system_settings, 'PAYMENT_PAYPAL_ENABLED', Config.PAYMENT_PAYPAL_ENABLED),
        'PAYMENT_MANUAL_ENABLED': _setting_bool(system_settings, 'PAYMENT_MANUAL_ENABLED', Config.PAYMENT_MANUAL_ENABLED),
        'TRIPAY_API_KEY': _setting_value(system_settings, 'TRIPAY_API_KEY', Config.TRIPAY_API_KEY),
        'TRIPAY_PRIVATE_KEY': _setting_value(system_settings, 'TRIPAY_PRIVATE_KEY', Config.TRIPAY_PRIVATE_KEY),
        'TRIPAY_MERCHANT_CODE': _setting_value(system_settings, 'TRIPAY_MERCHANT_CODE', Config.TRIPAY_MERCHANT_CODE),
        'TRIPAY_API_URL': _setting_value(system_settings, 'TRIPAY_API_URL', Config.TRIPAY_API_URL),
        'PAYPAL_CLIENT_ID': _setting_value(system_settings, 'PAYPAL_CLIENT_ID', Config.PAYPAL_CLIENT_ID),
        'PAYPAL_SECRET': _setting_value(system_settings, 'PAYPAL_SECRET', Config.PAYPAL_SECRET),
        'PAYPAL_API_URL': _setting_value(system_settings, 'PAYPAL_API_URL', Config.PAYPAL_API_URL),
        'PAYMENT_USD_RATE': _usd_rate(system_settings),
        'MANUAL_BANK_NAME': _setting_value(system_settings, 'MANUAL_BANK_NAME', Config.MANUAL_BANK_NAME),
        'MANUAL_BANK_ACCOUNT': _setting_value(system_settings, 'MANUAL_BANK_ACCOUNT', Config.MANUAL_BANK_ACCOUNT),
        'MANUAL_BANK_HOLDER': _setting_value(system_settings, 'MANUAL_BANK_HOLDER', Config.MANUAL_BANK_HOLDER),
        'ADMIN_WHATSAPP': _setting_value(system_settings, 'ADMIN_WHATSAPP', Config.ADMIN_WHATSAPP),
        'SMTP_SENDER_EMAIL': _setting_value(system_settings, 'SMTP_SENDER_EMAIL', Config.SMTP_SENDER_EMAIL),
        'SMTP_USER': _setting_value(system_settings, 'SMTP_USER', Config.SMTP_USER),
        'STARSENDER_DEVICE_ID': _setting_value(system_settings, 'STARSENDER_DEVICE_ID', Config.STARSENDER_DEVICE_ID),
        'ALLOW_MOCK_PAYMENTS': Config.ALLOW_MOCK_PAYMENTS,
    }

def tripay_is_mock(settings):
    return any(_is_mock_value(settings[key]) for key in ('TRIPAY_API_KEY', 'TRIPAY_PRIVATE_KEY', 'TRIPAY_MERCHANT_CODE'))

def paypal_is_mock(settings):
    return any(_is_mock_value(settings[key]) for key in ('PAYPAL_CLIENT_ID', 'PAYPAL_SECRET'))

def generate_tripay_signature(merchant_ref, amount, settings=None):
    settings = settings or get_payment_settings()
    signature_data = f"{settings['TRIPAY_MERCHANT_CODE']}{merchant_ref}{amount}"
    return hmac.new(
        settings['TRIPAY_PRIVATE_KEY'].encode('utf-8'),
        signature_data.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()

# Helper function to get PayPal access token
def get_paypal_access_token(settings=None):
    settings = settings or get_payment_settings()
    if paypal_is_mock(settings):
        return None
    try:
        url = f"{settings['PAYPAL_API_URL']}/v1/oauth2/token"
        resp = requests.post(
            url,
            data={'grant_type': 'client_credentials'},
            auth=(settings['PAYPAL_CLIENT_ID'], settings['PAYPAL_SECRET']),
            timeout=10
        )
        if resp.status_code == 200:
            return resp.json().get('access_token')
    except Exception as e:
        logger.error(f"Failed to get PayPal access token: {e}")
    return None

def decode_bearer_user_id():
    auth_header = request.headers.get('Authorization', '')
    if not auth_header.startswith('Bearer '):
        return None
    try:
        return authenticate_token(auth_header.split(' ', 1)[1])
    except Exception:
        return None


def _paypal_amount(value):
    """PayPal amounts are decimal strings; compare them as cents."""
    try:
        return Decimal(str(value)).quantize(Decimal('0.01'))
    except (InvalidOperation, TypeError, ValueError):
        return None


def expected_paypal_usd(transaction, settings):
    return _paypal_amount(f"{transaction.amount / settings['PAYMENT_USD_RATE']:.2f}")


def _paypal_custom_id_signature(invoice_id, usd):
    msg = f"{invoice_id}|{usd}".encode()
    return hmac.new(Config.SECRET_KEY.encode(), msg, hashlib.sha256).hexdigest()[:32]


def sign_paypal_custom_id(invoice_id, usd):
    """custom_id carrying the USD amount quoted at invoice time, HMAC-signed.

    Capture checks against this amount, so an admin changing PAYMENT_USD_RATE
    between invoice creation and the buyer's return does not strand an approved
    payment, and nobody can forge a different amount for the invoice.
    """
    usd = _paypal_amount(usd)
    return f"{invoice_id}|{usd}|{_paypal_custom_id_signature(invoice_id, usd)}"


def _signed_usd_for_invoice(custom_ids, invoice_id):
    """Return the signed amount from a custom_id for invoice_id, else None."""
    for custom_id in custom_ids:
        parts = (custom_id or '').split('|')
        if len(parts) != 3 or parts[0] != invoice_id:
            continue
        usd = _paypal_amount(parts[1])
        if usd is not None and hmac.compare_digest(parts[2], _paypal_custom_id_signature(invoice_id, usd)):
            return usd
    return None


def _billing_return_url(**params):
    # ProxyFix makes url_root reflect the public scheme/host behind Traefik.
    return f"{request.url_root.rstrip('/')}/billing?{urlencode(params)}"


def _paypal_approve_url(paypal_order):
    for link in paypal_order.get('links') or []:
        if link.get('rel') in ('approve', 'payer-action'):
            return link.get('href')
    return None


def verify_paypal_order(order_data, invoice_id, expected_usd):
    """Check a PayPal order/capture payload belongs to invoice_id for expected_usd.

    Returns (ok, reason). Works on both GET /orders/{id} and the capture response:
    for a completed order the captured amount is checked, otherwise the order amount.
    """
    units = order_data.get('purchase_units') or []
    if len(units) != 1:
        return False, 'unexpected purchase units'
    unit = units[0]
    captures = ((unit.get('payments') or {}).get('captures')) or []
    custom_ids = {unit.get('custom_id')}
    custom_ids.update(c.get('custom_id') for c in captures)
    signed_usd = _signed_usd_for_invoice(custom_ids, invoice_id)
    if signed_usd is not None:
        # The amount quoted when the invoice was created wins over today's rate.
        expected_usd = signed_usd
    ref_ids = {unit.get('reference_id')} | custom_ids
    ref_ids.update(c.get('invoice_id') for c in captures)
    if invoice_id not in ref_ids and signed_usd is None:
        return False, 'order does not belong to this invoice'

    if order_data.get('status') == 'COMPLETED':
        completed = [c for c in captures if c.get('status') == 'COMPLETED']
        if not completed:
            return False, 'no completed capture'
        currencies = {(c.get('amount') or {}).get('currency_code') for c in completed}
        amounts = [_paypal_amount((c.get('amount') or {}).get('value')) for c in completed]
        if currencies != {'USD'} or None in amounts:
            return False, 'unexpected capture currency'
        paid = sum(amounts, Decimal('0.00'))
    else:
        amount = unit.get('amount') or {}
        if amount.get('currency_code') != 'USD':
            return False, 'unexpected order currency'
        paid = _paypal_amount(amount.get('value'))

    if expected_usd is None or paid != expected_usd:
        return False, f'amount mismatch (paid {paid}, expected {expected_usd})'
    return True, ''

@payments_bp.route('/api/payments/create-invoice', methods=['POST'])
@require_jwt
def create_invoice(user_id):
    data = request.get_json(silent=True) or {}
    try:
        credits_count = int(data.get('credits_count', 0))
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'Jumlah kredit tidak valid'}), 400

    payment_method = data.get('payment_method') # 'manual', 'tripay', 'paypal'
    payment_code = data.get('payment_code', '') # Tripay payment codes (e.g. 'BRIVA', 'QRIS2', etc.)
    settings = get_payment_settings()

    if payment_method not in VALID_PAYMENT_METHODS:
        return jsonify({'success': False, 'error': 'Invalid payment method'}), 400
    
    if credits_count < 25:
        return jsonify({'success': False, 'error': 'Minimal pembelian adalah 25 kredit'}), 400
        
    if payment_method == 'tripay' and not settings['PAYMENT_TRIPAY_ENABLED']:
        return jsonify({'success': False, 'error': 'Tripay payment method is currently disabled'}), 400
    if payment_method == 'paypal' and not settings['PAYMENT_PAYPAL_ENABLED']:
        return jsonify({'success': False, 'error': 'PayPal payment method is currently disabled'}), 400
    if payment_method == 'manual' and not settings['PAYMENT_MANUAL_ENABLED']:
        return jsonify({'success': False, 'error': 'Manual transfer payment method is currently disabled'}), 400

    if payment_method == 'tripay' and tripay_is_mock(settings) and not settings['ALLOW_MOCK_PAYMENTS']:
        return jsonify({'success': False, 'error': 'Tripay belum dikonfigurasi. Hubungi admin.'}), 400
    if payment_method == 'paypal' and paypal_is_mock(settings) and not settings['ALLOW_MOCK_PAYMENTS']:
        return jsonify({'success': False, 'error': 'PayPal belum dikonfigurasi. Hubungi admin.'}), 400
        
    amount = credits_count * 2000 # Rp 2.000 per credit
    invoice_id = f"INV-{uuid.uuid4().hex[:8].upper()}-{int(datetime.now().timestamp())}"
    
    with db.get_session() as session:
        user = session.query(User).filter_by(id=user_id).first()
        if not user:
            return jsonify({'success': False, 'error': 'User not found'}), 404
            
        # Create a pending transaction
        transaction = Transaction(
            user_id=user.id,
            payment_method=payment_method,
            invoice_id=invoice_id,
            credits_purchased=credits_count,
            amount=amount,
            status='pending',
            created_at=datetime.now()
        )
        session.add(transaction)
        session.commit()
        
        # Payment Gateway Integrations
        if payment_method == 'tripay':
            # Check if using mock
            if tripay_is_mock(settings):
                logger.info(f"Simulating Tripay invoice for invoice_id: {invoice_id}")
                return jsonify({
                    'success': True,
                    'invoice_id': invoice_id,
                    'payment_method': 'tripay',
                    'is_mock': True,
                    'tripay_data': {
                        'reference': f"T-MOCK-{uuid.uuid4().hex[:8].upper()}",
                        'pay_code': '1234567890',
                        'qr_string': 'mock_qr_string_for_testing',
                        'amount': amount,
                        'payment_name': f"Tripay {payment_code or 'MOCK VA'}",
                        'status': 'UNPAID'
                    }
                })
            
            try:
                headers = {'Authorization': f"Bearer {settings['TRIPAY_API_KEY']}"}
                payload = {
                    'method': payment_code or 'QRIS2',
                    'merchant_ref': invoice_id,
                    'amount': amount,
                    'customer_name': user.name or 'Customer',
                    'customer_email': user.email,
                    'order_items': [
                        {
                            'name': f"Top Up {credits_count} Credits",
                            'price': 2000,
                            'quantity': credits_count
                        }
                    ],
                    'return_url': _billing_return_url(tripay_invoice=invoice_id),
                    'signature': generate_tripay_signature(invoice_id, amount, settings)
                }

                resp = requests.post(f"{settings['TRIPAY_API_URL']}/transaction/create", json=payload, headers=headers, timeout=15)
                if resp.status_code == 200:
                    tripay_res = resp.json()
                    if tripay_res.get('success'):
                        tripay_data = tripay_res.get('data') or {}
                        return jsonify({
                            'success': True,
                            'invoice_id': invoice_id,
                            'payment_method': 'tripay',
                            'is_mock': False,
                            'checkout_url': tripay_data.get('checkout_url'),
                            'tripay_data': tripay_data
                        })
                    else:
                        return jsonify({'success': False, 'error': tripay_res.get('message', 'Tripay failed')}), 400
                else:
                    return jsonify({'success': False, 'error': f"Tripay error {resp.status_code}: {resp.text}"}), 400
            except Exception as e:
                logger.error(f"Tripay connection error: {e}")
                return jsonify({'success': False, 'error': f"Failed to connect to Tripay: {e}"}), 500
                
        elif payment_method == 'paypal':
            # Convert IDR to USD
            amount_usd = amount / settings['PAYMENT_USD_RATE']
            
            token = get_paypal_access_token(settings)
            if not token:
                if settings['ALLOW_MOCK_PAYMENTS'] and paypal_is_mock(settings):
                    logger.info(f"Simulating PayPal invoice for invoice_id: {invoice_id}")
                    return jsonify({
                        'success': True,
                        'invoice_id': invoice_id,
                        'payment_method': 'paypal',
                        'is_mock': True,
                        'amount_usd': round(amount_usd, 2),
                        'paypal_order_id': f"PAY-MOCK-{uuid.uuid4().hex[:12].upper()}"
                    })
                return jsonify({'success': False, 'error': 'Failed to connect to PayPal'}), 500

            try:
                headers = {
                    'Authorization': f'Bearer {token}',
                    'Content-Type': 'application/json'
                }
                payload = {
                    'intent': 'CAPTURE',
                    'purchase_units': [{
                        # Both ids tie the PayPal order to this invoice; capture verifies them.
                        'reference_id': invoice_id,
                        'custom_id': sign_paypal_custom_id(invoice_id, f"{amount_usd:.2f}"),
                        'amount': {
                            'currency_code': 'USD',
                            'value': f"{amount_usd:.2f}"
                        },
                        'description': f"Top Up {credits_count} Credits - {invoice_id}"
                    }],
                    'application_context': {
                        'brand_name': 'AutoWP',
                        'shipping_preference': 'NO_SHIPPING',
                        'user_action': 'PAY_NOW',
                        'return_url': _billing_return_url(paypal_invoice=invoice_id),
                        'cancel_url': _billing_return_url(paypal_invoice=invoice_id, paypal_cancel='1'),
                    }
                }
                resp = requests.post(f"{settings['PAYPAL_API_URL']}/v2/checkout/orders", json=payload, headers=headers, timeout=15)
                if resp.status_code == 201:
                    paypal_order = resp.json()
                    return jsonify({
                        'success': True,
                        'invoice_id': invoice_id,
                        'payment_method': 'paypal',
                        'is_mock': False,
                        'amount_usd': round(amount_usd, 2),
                        'paypal_order_id': paypal_order.get('id'),
                        'paypal_approve_url': _paypal_approve_url(paypal_order)
                    })
                else:
                    return jsonify({'success': False, 'error': f"PayPal order creation failed: {resp.text}"}), 400
            except Exception as e:
                logger.error(f"PayPal connection error: {e}")
                return jsonify({'success': False, 'error': f"Failed to connect to PayPal: {e}"}), 500
                
        elif payment_method == 'manual':
            # Manual bank transfer
            return jsonify({
                'success': True,
                'invoice_id': invoice_id,
                'payment_method': 'manual',
                'amount': amount,
                    'bank_details': {
                    'bank_name': settings['MANUAL_BANK_NAME'],
                    'account_number': settings['MANUAL_BANK_ACCOUNT'],
                    'account_holder': settings['MANUAL_BANK_HOLDER'],
                    'whatsapp_number': settings['ADMIN_WHATSAPP']
                }
            })

@payments_bp.route('/api/payments/upload-receipt', methods=['POST'])
@require_jwt
def upload_receipt(user_id):
    invoice_id = request.form.get('invoice_id')
    if not invoice_id:
        return jsonify({'success': False, 'error': 'Invoice ID is required'}), 400
        
    if 'receipt' not in request.files:
        return jsonify({'success': False, 'error': 'No file uploaded'}), 400
        
    file = request.files['receipt']
    if file.filename == '':
        return jsonify({'success': False, 'error': 'No file selected'}), 400

    extension = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if extension not in ALLOWED_RECEIPT_EXTENSIONS:
        return jsonify({'success': False, 'error': 'Receipt must be a JPG, PNG, WEBP or PDF file'}), 400

    content = file.stream.read(MAX_RECEIPT_BYTES + 1)
    if len(content) > MAX_RECEIPT_BYTES:
        return jsonify({'success': False, 'error': 'Receipt file is too large (max 5 MB)'}), 413
    detected = detect_receipt_type(content[:16])
    if detected is None or detected != ('jpg' if extension == 'jpeg' else extension):
        return jsonify({'success': False, 'error': 'Receipt content does not match a JPG, PNG, WEBP or PDF file'}), 400

    settings = get_payment_settings()

    with db.get_session() as session:
        transaction = session.query(Transaction).filter_by(invoice_id=invoice_id).first()
        if not transaction:
            return jsonify({'success': False, 'error': 'Transaction not found'}), 404

        if transaction.user_id != user_id:
            return jsonify({'success': False, 'error': 'Unauthorized'}), 403

        if transaction.payment_method != 'manual':
            return jsonify({'success': False, 'error': 'Receipts can only be uploaded for manual transfers'}), 400
        if transaction.status not in RECEIPT_UPLOADABLE_STATUSES:
            return jsonify({'success': False, 'error': f'Transaction status is {transaction.status}, receipt can no longer be uploaded'}), 409

        # Never trust the client filename: random name, extension from the sniffed content.
        filename = f"{secrets.token_hex(16)}.{detected}"
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        with open(filepath, 'wb') as out:
            out.write(content)

        # Store web-accessible url
        receipt_url = f"/static/uploads/receipts/{filename}"

        # Conditional so an approval/rejection racing this upload is never undone.
        updated = session.query(Transaction).filter(
            Transaction.id == transaction.id,
            Transaction.payment_method == 'manual',
            Transaction.status.in_(RECEIPT_UPLOADABLE_STATUSES),
        ).update({
            Transaction.receipt_url: receipt_url,
            Transaction.status: 'awaiting_approval',
        }, synchronize_session=False)
        if updated != 1:
            session.rollback()
            try:
                os.remove(filepath)
            except OSError:
                pass
            return jsonify({'success': False, 'error': 'Transaction was already processed'}), 409
        session.commit()

        logger.info(f"Receipt uploaded for invoice {invoice_id} by user {user_id}")
        
        # Notify Admin
        try:
            import threading
            user = session.query(User).filter_by(id=user_id).first()
            user_info = f"{user.name} ({user.email})" if user else f"User ID {user_id}"
            
            admin_subject = f"AutoWP - Receipt Uploaded ({invoice_id})"
            admin_body = f"Halo Admin,\n\nUser {user_info} baru saja mengunggah bukti transfer untuk invoice {invoice_id}.\n- Jumlah Kredit: {transaction.credits_purchased}\n- Nominal Transfer: Rp {transaction.amount:,}\n\nSilakan periksa menu pending payments di dashboard admin untuk melakukan verifikasi."
            
            admin_email = settings['SMTP_SENDER_EMAIL'] or settings['SMTP_USER']
            if admin_email:
                threading.Thread(target=send_email_notification, args=(admin_email, admin_subject, admin_body)).start()
            if settings['STARSENDER_DEVICE_ID']:
                threading.Thread(target=send_whatsapp_notification, args=(settings['STARSENDER_DEVICE_ID'], admin_body)).start()
        except Exception as e:
            logger.error(f"Error launching receipt upload notification threads: {e}")
            
        return jsonify({'success': True, 'message': 'Receipt uploaded successfully. Waiting for admin approval.', 'receipt_url': receipt_url})

@payments_bp.route('/api/payments/webhook/tripay', methods=['POST'])
def tripay_webhook():
    signature = request.headers.get('X-Callback-Signature')
    if not signature:
        return jsonify({'success': False, 'message': 'No signature header'}), 400
        
    data = request.get_json(silent=True) or {}
    settings = get_payment_settings()
    # Verify Tripay IP/Signature for security
    # Skip HMAC validation locally if mock
    is_mock = _is_mock_value(settings['TRIPAY_PRIVATE_KEY'])
    mock_user_id = None
    
    if is_mock:
        if not settings['ALLOW_MOCK_PAYMENTS']:
            return jsonify({'success': False, 'message': 'Mock Tripay webhook is disabled'}), 403
        mock_user_id = decode_bearer_user_id()
        if not mock_user_id:
            return jsonify({'success': False, 'message': 'Mock webhook requires authenticated admin/user session'}), 401
    else:
        raw_payload = request.data
        calculated_signature = hmac.new(
            settings['TRIPAY_PRIVATE_KEY'].encode('utf-8'),
            raw_payload,
            hashlib.sha256
        ).hexdigest()
        
        if not hmac.compare_digest(signature, calculated_signature):
            logger.warning("Tripay webhook signature mismatch!")
            return jsonify({'success': False, 'message': 'Signature mismatch'}), 400
            
    # Process the callback
    invoice_id = data.get('merchant_ref')
    status = data.get('status')
    
    if not invoice_id:
        return jsonify({'success': False, 'message': 'Missing merchant_ref'}), 400
        
    if status == 'PAID':
        with db.get_session() as session:
            transaction = session.query(Transaction).filter_by(invoice_id=invoice_id).first()
            if transaction and transaction.payment_method == 'tripay' and transaction.status == 'pending':
                if is_mock and transaction.user_id != mock_user_id:
                    mock_user = session.query(User).filter_by(id=mock_user_id).first()
                    if not mock_user or mock_user.role != 'admin':
                        return jsonify({'success': False, 'message': 'Unauthorized mock webhook target'}), 403

                # Tripay retries callbacks; only the first one may grant credits.
                credits = fulfill_transaction(session, transaction.id, ('pending',), payment_method='tripay')
                session.commit()
                if credits is not None:
                    logger.info(f"Fulfill Tripay purchase: {credits} credits for User {transaction.user_id} ({invoice_id})")
                return jsonify({'success': True})

    return jsonify({'success': True, 'message': 'Processed successfully'})

@payments_bp.route('/api/payments/paypal-capture', methods=['POST'])
@require_jwt
def paypal_capture(user_id):
    data = request.get_json(silent=True) or {}
    order_id = data.get('order_id')
    invoice_id = data.get('invoice_id')
    settings = get_payment_settings()
    
    if not isinstance(order_id, str) or not isinstance(invoice_id, str) or not order_id or not invoice_id:
        return jsonify({'success': False, 'error': 'order_id and invoice_id are required'}), 400
    # PayPal order ids are short alphanumerics; refuse anything that could alter the API path.
    if not PAYPAL_ORDER_ID_RE.fullmatch(order_id):
        return jsonify({'success': False, 'error': 'Invalid order_id'}), 400

    with db.get_session() as session:
        transaction = session.query(Transaction).filter_by(invoice_id=invoice_id, user_id=user_id).first()
        if not transaction:
            return jsonify({'success': False, 'error': 'Transaction not found'}), 404
        if transaction.payment_method != 'paypal':
            return jsonify({'success': False, 'error': 'Transaction is not a PayPal payment'}), 400
        if transaction.status != 'pending':
            return jsonify({'success': False, 'error': 'Transaction already processed'}), 400
        transaction_id = transaction.id
        expected_usd = expected_paypal_usd(transaction, settings)

    # Standard flow
    success = False

    # Check if using mock
    if order_id.startswith('PAY-MOCK-'):
        if not (settings['ALLOW_MOCK_PAYMENTS'] and paypal_is_mock(settings)):
            return jsonify({'success': False, 'error': 'Mock PayPal capture is disabled'}), 403
        logger.info(f"Fulfilling mock PayPal capture for {invoice_id}")
        success = True
    else:
        token = get_paypal_access_token(settings)
        if token:
            try:
                headers = {
                    'Authorization': f'Bearer {token}',
                    'Content-Type': 'application/json'
                }
                order_url = f"{settings['PAYPAL_API_URL']}/v2/checkout/orders/{order_id}"
                # Verify the order belongs to this invoice and amount *before* taking the money.
                resp = requests.get(order_url, headers=headers, timeout=15)
                if resp.status_code != 200:
                    logger.error(f"PayPal order lookup failed for {invoice_id}: {resp.status_code} {resp.text}")
                    return jsonify({'success': False, 'error': 'PayPal order not found'}), 400
                order_data = resp.json()
                ok, reason = verify_paypal_order(order_data, invoice_id, expected_usd)
                if not ok:
                    logger.warning(f"Rejected PayPal order {order_id} for {invoice_id} (user {user_id}): {reason}")
                    return jsonify({'success': False, 'error': 'PayPal order does not match this invoice'}), 400

                if order_data.get('status') == 'COMPLETED':
                    # Already captured (e.g. retry after a timeout): fulfil from the verified order.
                    capture_data = order_data
                else:
                    # Full representation so the captured amount is present for verification.
                    capture_headers = dict(headers, Prefer='return=representation')
                    resp = requests.post(f"{order_url}/capture", json={}, headers=capture_headers, timeout=15)
                    capture_data = resp.json() if resp.status_code in (200, 201) else None
                    if capture_data is None:
                        logger.error(f"PayPal capture API failed: {resp.text}")

                if capture_data is not None:
                    ok, reason = verify_paypal_order(capture_data, invoice_id, expected_usd)
                    if capture_data.get('status') == 'COMPLETED' and ok:
                        success = True
                    else:
                        logger.error(
                            f"PayPal capture for {invoice_id} not accepted "
                            f"(status {capture_data.get('status')}): {reason or 'not completed'}"
                        )
            except Exception as e:
                logger.error(f"PayPal capture request error: {e}")
        else:
            logger.error("No PayPal token available, capture failed.")

    if success:
        with db.get_session() as session:
            credits = fulfill_transaction(session, transaction_id, ('pending',), payment_method='paypal')
            session.commit()
            if credits is not None:
                logger.info(f"Fulfill PayPal purchase: {credits} credits for User {user_id} ({invoice_id})")
                return jsonify({'success': True, 'message': 'Payment captured and credits added!'})
            return jsonify({'success': False, 'error': 'Transaction not found or already processed'}), 409

    return jsonify({'success': False, 'error': 'Capture failed'}), 400

@payments_bp.route('/api/payments/history', methods=['GET'])
@require_jwt
def get_payment_history(user_id):
    settings = get_payment_settings()
    with db.get_session() as session:
        transactions = session.query(Transaction).filter_by(user_id=user_id).order_by(Transaction.created_at.desc()).limit(100).all()
        history = []
        for tx in transactions:
            history.append({
                'id': tx.id,
                'payment_method': tx.payment_method,
                'invoice_id': tx.invoice_id,
                'credits_purchased': tx.credits_purchased,
                'amount': tx.amount,
                'status': tx.status,
                'receipt_url': tx.receipt_url,
                'created_at': tx.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                'bank_details': {
                    'bank_name': settings['MANUAL_BANK_NAME'],
                    'account_number': settings['MANUAL_BANK_ACCOUNT'],
                    'account_holder': settings['MANUAL_BANK_HOLDER'],
                    'whatsapp_number': settings['ADMIN_WHATSAPP']
                } if tx.payment_method == 'manual' else None
            })
        return jsonify({'success': True, 'history': history})
