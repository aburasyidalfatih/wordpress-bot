import os
import uuid
import hmac
import hashlib
import logging
from datetime import datetime
from flask import Blueprint, request, jsonify
from werkzeug.utils import secure_filename
import requests

from core_extensions import db, logger, require_jwt, send_email_notification, send_whatsapp_notification
from config import Config
from database import User, Transaction

payments_bp = Blueprint('payments', __name__)

# Ensure uploads directory exists
UPLOAD_FOLDER = os.path.join('static', 'uploads', 'receipts')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Helper function to generate Tripay signature
def generate_tripay_signature(merchant_ref, amount):
    signature_data = f"{Config.TRIPAY_MERCHANT_CODE}{merchant_ref}{amount}"
    return hmac.new(
        Config.TRIPAY_PRIVATE_KEY.encode('utf-8'),
        signature_data.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()

# Helper function to get PayPal access token
def get_paypal_access_token():
    if Config.PAYPAL_CLIENT_ID.startswith('MOCK') or Config.PAYPAL_SECRET.startswith('MOCK'):
        return None
    try:
        url = f"{Config.PAYPAL_API_URL}/v1/oauth2/token"
        resp = requests.post(
            url,
            data={'grant_type': 'client_credentials'},
            auth=(Config.PAYPAL_CLIENT_ID, Config.PAYPAL_SECRET),
            timeout=10
        )
        if resp.status_code == 200:
            return resp.json().get('access_token')
    except Exception as e:
        logger.error(f"Failed to get PayPal access token: {e}")
    return None

@payments_bp.route('/api/payments/create-invoice', methods=['POST'])
@require_jwt
def create_invoice(user_id):
    data = request.json or {}
    credits_count = int(data.get('credits_count', 0))
    payment_method = data.get('payment_method') # 'manual', 'tripay', 'paypal'
    payment_code = data.get('payment_code', '') # Tripay payment codes (e.g. 'BRIVA', 'QRIS2', etc.)
    
    if credits_count < 25:
        return jsonify({'success': False, 'error': 'Minimal pembelian adalah 25 kredit'}), 400
        
    if payment_method == 'tripay' and not Config.PAYMENT_TRIPAY_ENABLED:
        return jsonify({'success': False, 'error': 'Tripay payment method is currently disabled'}), 400
    if payment_method == 'paypal' and not Config.PAYMENT_PAYPAL_ENABLED:
        return jsonify({'success': False, 'error': 'PayPal payment method is currently disabled'}), 400
    if payment_method == 'manual' and not Config.PAYMENT_MANUAL_ENABLED:
        return jsonify({'success': False, 'error': 'Manual transfer payment method is currently disabled'}), 400
        
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
            if Config.TRIPAY_API_KEY.startswith('MOCK') or Config.TRIPAY_MERCHANT_CODE.startswith('MOCK'):
                logger.info(f"Simulating Tripay invoice for invoice_id: {invoice_id}")
                return jsonify({
                    'success': True,
                    'invoice_id': invoice_id,
                    'payment_method': 'tripay',
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
                headers = {'Authorization': f"Bearer {Config.TRIPAY_API_KEY}"}
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
                    'signature': generate_tripay_signature(invoice_id, amount)
                }
                
                resp = requests.post(f"{Config.TRIPAY_API_URL}/transaction/create", json=payload, headers=headers, timeout=15)
                if resp.status_code == 200:
                    tripay_res = resp.json()
                    if tripay_res.get('success'):
                        return jsonify({
                            'success': True,
                            'invoice_id': invoice_id,
                            'payment_method': 'tripay',
                            'tripay_data': tripay_res.get('data')
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
            amount_usd = amount / Config.PAYMENT_USD_RATE
            
            token = get_paypal_access_token()
            if not token:
                logger.info(f"Simulating PayPal invoice for invoice_id: {invoice_id}")
                return jsonify({
                    'success': True,
                    'invoice_id': invoice_id,
                    'payment_method': 'paypal',
                    'amount_usd': round(amount_usd, 2),
                    'paypal_order_id': f"PAY-MOCK-{uuid.uuid4().hex[:12].upper()}"
                })
                
            try:
                headers = {
                    'Authorization': f'Bearer {token}',
                    'Content-Type': 'application/json'
                }
                payload = {
                    'intent': 'CAPTURE',
                    'purchase_units': [{
                        'reference_id': invoice_id,
                        'amount': {
                            'currency_code': 'USD',
                            'value': f"{amount_usd:.2f}"
                        },
                        'description': f"Top Up {credits_count} Credits - {invoice_id}"
                    }]
                }
                resp = requests.post(f"{Config.PAYPAL_API_URL}/v2/checkout/orders", json=payload, headers=headers, timeout=15)
                if resp.status_code == 201:
                    paypal_order = resp.json()
                    return jsonify({
                        'success': True,
                        'invoice_id': invoice_id,
                        'payment_method': 'paypal',
                        'amount_usd': round(amount_usd, 2),
                        'paypal_order_id': paypal_order.get('id')
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
                    'bank_name': Config.MANUAL_BANK_NAME,
                    'account_number': Config.MANUAL_BANK_ACCOUNT,
                    'account_holder': Config.MANUAL_BANK_HOLDER,
                    'whatsapp_number': Config.ADMIN_WHATSAPP
                }
            })
            
        else:
            return jsonify({'success': False, 'error': 'Invalid payment method'}), 400

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
        
    filename = secure_filename(f"{invoice_id}_{file.filename}")
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    file.save(filepath)
    
    # Store web-accessible url
    receipt_url = f"/static/uploads/receipts/{filename}"
    
    with db.get_session() as session:
        transaction = session.query(Transaction).filter_by(invoice_id=invoice_id).first()
        if not transaction:
            return jsonify({'success': False, 'error': 'Transaction not found'}), 404
            
        if transaction.user_id != user_id:
            return jsonify({'success': False, 'error': 'Unauthorized'}), 403
            
        transaction.receipt_url = receipt_url
        transaction.status = 'awaiting_approval'
        session.commit()
        
        logger.info(f"Receipt uploaded for invoice {invoice_id} by user {user_id}")
        
        # Notify Admin
        try:
            import threading
            user = session.query(User).filter_by(id=user_id).first()
            user_info = f"{user.name} ({user.email})" if user else f"User ID {user_id}"
            
            admin_subject = f"AutoWP - Receipt Uploaded ({invoice_id})"
            admin_body = f"Halo Admin,\n\nUser {user_info} baru saja mengunggah bukti transfer untuk invoice {invoice_id}.\n- Jumlah Kredit: {transaction.credits_purchased}\n- Nominal Transfer: Rp {transaction.amount:,}\n\nSilakan periksa menu pending payments di dashboard admin untuk melakukan verifikasi."
            
            admin_email = Config.SMTP_SENDER_EMAIL or Config.SMTP_USER
            if admin_email:
                threading.Thread(target=send_email_notification, args=(admin_email, admin_subject, admin_body)).start()
            if Config.STARSENDER_DEVICE_ID:
                threading.Thread(target=send_whatsapp_notification, args=(Config.STARSENDER_DEVICE_ID, admin_body)).start()
        except Exception as e:
            logger.error(f"Error launching receipt upload notification threads: {e}")
            
        return jsonify({'success': True, 'message': 'Receipt uploaded successfully. Waiting for admin approval.', 'receipt_url': receipt_url})

@payments_bp.route('/api/payments/webhook/tripay', methods=['POST'])
def tripay_webhook():
    signature = request.headers.get('X-Callback-Signature')
    if not signature:
        return jsonify({'success': False, 'message': 'No signature header'}), 400
        
    data = request.json or {}
    # Verify Tripay IP/Signature for security
    # Skip HMAC validation locally if mock
    is_mock = Config.TRIPAY_PRIVATE_KEY.startswith('MOCK')
    
    if not is_mock:
        raw_payload = request.data
        calculated_signature = hmac.new(
            Config.TRIPAY_PRIVATE_KEY.encode('utf-8'),
            raw_payload,
            hashlib.sha256
        ).hexdigest()
        
        if signature != calculated_signature:
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
            if transaction and transaction.status != 'success':
                transaction.status = 'success'
                
                # Update user credits and tier
                user = session.query(User).filter_by(id=transaction.user_id).first()
                if user:
                    user.credits = (user.credits or 0) + transaction.credits_purchased
                    user.tier = 'pro'
                    logger.info(f"Fulfill Tripay purchase: {transaction.credits_purchased} credits for User {user.email}")
                    
                session.commit()
                return jsonify({'success': True})
                
    return jsonify({'success': True, 'message': 'Processed successfully'})

@payments_bp.route('/api/payments/paypal-capture', methods=['POST'])
@require_jwt
def paypal_capture(user_id):
    data = request.json or {}
    order_id = data.get('order_id')
    invoice_id = data.get('invoice_id')
    
    if not order_id or not invoice_id:
        return jsonify({'success': False, 'error': 'order_id and invoice_id are required'}), 400
        
    # Standard flow
    success = False
    
    # Check if using mock
    if order_id.startswith('PAY-MOCK-'):
        logger.info(f"Fulfilling mock PayPal capture for {invoice_id}")
        success = True
    else:
        token = get_paypal_access_token()
        if token:
            try:
                headers = {
                    'Authorization': f'Bearer {token}',
                    'Content-Type': 'application/json'
                }
                # Capture payment
                url = f"{Config.PAYPAL_API_URL}/v2/checkout/orders/{order_id}/capture"
                resp = requests.post(url, json={}, headers=headers, timeout=15)
                if resp.status_code in (200, 201):
                    capture_data = resp.json()
                    if capture_data.get('status') == 'COMPLETED':
                        success = True
                    else:
                        logger.error(f"PayPal capture status was: {capture_data.get('status')}")
                else:
                    logger.error(f"PayPal capture API failed: {resp.text}")
            except Exception as e:
                logger.error(f"PayPal capture request error: {e}")
        else:
            logger.error("No PayPal token available, capture failed.")
            
    if success:
        with db.get_session() as session:
            transaction = session.query(Transaction).filter_by(invoice_id=invoice_id).first()
            if transaction and transaction.status != 'success':
                transaction.status = 'success'
                user = session.query(User).filter_by(id=transaction.user_id).first()
                if user:
                    user.credits = (user.credits or 0) + transaction.credits_purchased
                    user.tier = 'pro'
                    logger.info(f"Fulfill PayPal purchase: {transaction.credits_purchased} credits for User {user.email}")
                session.commit()
                return jsonify({'success': True, 'message': 'Payment captured and credits added!'})
            else:
                return jsonify({'success': False, 'error': 'Transaction not found or already processed'}), 404
                
    return jsonify({'success': False, 'error': 'Capture failed'}), 400

@payments_bp.route('/api/payments/history', methods=['GET'])
@require_jwt
def get_payment_history(user_id):
    with db.get_session() as session:
        transactions = session.query(Transaction).filter_by(user_id=user_id).order_by(Transaction.created_at.desc()).all()
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
                    'bank_name': Config.MANUAL_BANK_NAME,
                    'account_number': Config.MANUAL_BANK_ACCOUNT,
                    'account_holder': Config.MANUAL_BANK_HOLDER,
                    'whatsapp_number': Config.ADMIN_WHATSAPP
                } if tx.payment_method == 'manual' else None
            })
        return jsonify({'success': True, 'history': history})
