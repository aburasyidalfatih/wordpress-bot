from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
import secrets

import jwt
from flask import Blueprint, jsonify, redirect, request

from config import Config
from core_extensions import db, q, redis_conn, logger, require_jwt
from models import SearchConsoleMetric, WordPressSite
from services.search_console import (
    SearchConsoleClient,
    SearchConsoleError,
    build_authorization_url,
    build_search_opportunities,
    exchange_authorization_code,
    find_matching_property,
)


search_console_bp = Blueprint('search_console', __name__)

OAUTH_STATE_TTL_SECONDS = 600
OAUTH_STATE_KEY_PREFIX = 'gsc_oauth_state:'
GOOGLE_REQUEST_FAILED = 'Permintaan ke Google Search Console gagal. Silakan coba lagi atau hubungkan ulang akun Google.'


class _SiteSetupError(SearchConsoleError):
    """A setup problem on our side whose (Indonesian) message is safe to show the user."""


def _user_message(exc):
    """Message for the UI.

    SearchConsoleError messages are composed by services/search_console.py in
    Indonesian (status code plus Google's short reason, e.g. a missing
    permission), so they are safe and actionable to show as-is.
    """
    if isinstance(exc, SearchConsoleError):
        logger.warning(f'Search Console request failed: {exc}')
        return str(exc) or GOOGLE_REQUEST_FAILED
    return GOOGLE_REQUEST_FAILED


def _store_oauth_nonce(nonce, user_id, site_id):
    redis_conn.set(f'{OAUTH_STATE_KEY_PREFIX}{nonce}', f'{user_id}:{site_id}', ex=OAUTH_STATE_TTL_SECONDS)


def _consume_oauth_nonce(nonce):
    """Atomically fetch and delete a stored nonce (one-time use)."""
    key = f'{OAUTH_STATE_KEY_PREFIX}{nonce}'
    pipe = redis_conn.pipeline()
    pipe.get(key)
    pipe.delete(key)
    value, _ = pipe.execute()
    if isinstance(value, bytes):
        value = value.decode('utf-8')
    return value


def _clear_search_console_metrics(session, user_id, site_id):
    """Drop synced metrics so data from an old account/property is not reused."""
    session.query(SearchConsoleMetric).filter_by(
        user_id=user_id, site_id=site_id
    ).delete(synchronize_session=False)


def _google_credentials(site=None):
    return (
        site.gsc_client_id if site else None,
        site.gsc_client_secret if site else None,
    )


def _redirect_uri():
    # Traefik terminates TLS; use its forwarded scheme to derive the callback
    # shown in the website form without requiring an environment variable.
    forwarded_proto = request.headers.get('X-Forwarded-Proto', request.scheme).split(',')[0].strip()
    base_url = f'{forwarded_proto}://{request.host}'
    return f'{base_url}/api/search-console/callback'


def _frontend_redirect(status, message=None):
    params = {'gsc': status}
    if message:
        params['message'] = message[:160]
    return redirect(f'/sites?{urlencode(params)}')


def _site_for_user(session, user_id, site_id):
    return session.query(WordPressSite).filter_by(id=site_id, user_id=user_id).first()


def _client_for_site(site):
    client_id, client_secret = _google_credentials(site)
    if not client_id or not client_secret:
        raise _SiteSetupError('Google OAuth belum dikonfigurasi untuk website ini.')
    if not site.gsc_refresh_token:
        raise _SiteSetupError('Search Console belum terhubung.')
    return SearchConsoleClient(client_id, client_secret, refresh_token=site.gsc_refresh_token)


@search_console_bp.route('/api/search-console/sites/<int:site_id>/authorize', methods=['POST'])
@require_jwt
def authorize_search_console(user_id, site_id):
    with db.get_session() as session:
        site = _site_for_user(session, user_id, site_id)
        if not site:
            return jsonify({'success': False, 'error': 'Website tidak ditemukan.'}), 404
        client_id, client_secret = _google_credentials(site)
        if not client_id or not client_secret:
            return jsonify({'success': False, 'error': 'Isi Google OAuth Client ID dan Client Secret, lalu simpan website terlebih dahulu.'}), 400

    now = datetime.now(timezone.utc)
    nonce = secrets.token_urlsafe(24)
    try:
        _store_oauth_nonce(nonce, user_id, site_id)
    except Exception as exc:
        logger.error(f'Could not store Search Console OAuth state: {exc}')
        return jsonify({'success': False, 'error': 'Gagal memulai otorisasi Google. Coba lagi.'}), 500
    state = jwt.encode({
        'purpose': 'gsc_oauth',
        'user_id': user_id,
        'site_id': site_id,
        'nonce': nonce,
        'iat': now,
        'exp': now + timedelta(seconds=OAUTH_STATE_TTL_SECONDS),
    }, Config.SECRET_KEY, algorithm='HS256')
    return jsonify({
        'success': True,
        'authorization_url': build_authorization_url(client_id, _redirect_uri(), state),
        'redirect_uri': _redirect_uri(),
    })


@search_console_bp.route('/api/search-console/callback', methods=['GET'])
def search_console_callback():
    if request.args.get('error'):
        return _frontend_redirect('error', 'Izin Google dibatalkan atau ditolak.')
    code = request.args.get('code')
    state = request.args.get('state')
    if not code or not state:
        return _frontend_redirect('error', 'Callback Google tidak lengkap.')
    try:
        payload = jwt.decode(state, Config.SECRET_KEY, algorithms=['HS256'])
        if payload.get('purpose') != 'gsc_oauth':
            raise ValueError('Invalid OAuth state purpose')
        user_id = int(payload['user_id'])
        site_id = int(payload['site_id'])
        nonce = payload.get('nonce')
        # The nonce must have been issued by /authorize and is single use, so
        # a captured callback URL cannot be replayed.
        if not nonce or _consume_oauth_nonce(nonce) != f'{user_id}:{site_id}':
            return _frontend_redirect('error', 'Sesi otorisasi Google tidak valid atau kedaluwarsa. Silakan hubungkan ulang.')
        with db.get_session() as session:
            site = _site_for_user(session, user_id, site_id)
            if not site:
                return _frontend_redirect('error', 'Website tidak ditemukan.')
            client_id, client_secret = _google_credentials(site)
            existing_refresh_token = site.gsc_refresh_token
            wordpress_url = site.wordpress_url
            if not client_id or not client_secret:
                raise _SiteSetupError('Credential OAuth website tidak ditemukan.')

        tokens = exchange_authorization_code(
            client_id, client_secret, _redirect_uri(), code
        )
        refresh_token = tokens.get('refresh_token') or existing_refresh_token
        if not refresh_token:
            raise _SiteSetupError('Google tidak memberikan refresh token; hubungkan ulang dengan consent.')
        client = SearchConsoleClient(
            client_id, client_secret,
            refresh_token=refresh_token,
            access_token=tokens.get('access_token'),
        )
        properties = client.list_properties()
        match = find_matching_property(properties, wordpress_url)

        with db.get_session() as session:
            site = _site_for_user(session, user_id, site_id)
            if not site:
                return _frontend_redirect('error', 'Website tidak ditemukan.')
            site.gsc_refresh_token = refresh_token
            if match:
                if match['site_url'] != site.gsc_property_url:
                    _clear_search_console_metrics(session, user_id, site_id)
                    site.gsc_last_synced_at = None
                site.gsc_property_url = match['site_url']
                site.gsc_permission_level = match.get('permission_level')
            site.gsc_connected_at = datetime.now()
            site.gsc_last_error = None
        return _frontend_redirect('connected')
    except Exception as exc:
        logger.error(f'Search Console OAuth callback failed: {exc}')
        if isinstance(exc, SearchConsoleError):
            message = _user_message(exc)
        else:
            message = 'Gagal menghubungkan Search Console.'
        return _frontend_redirect('error', message)


@search_console_bp.route('/api/search-console/sites/<int:site_id>/properties', methods=['GET'])
@require_jwt
def list_search_console_properties(user_id, site_id):
    try:
        with db.get_session() as session:
            site = _site_for_user(session, user_id, site_id)
            if not site:
                return jsonify({'success': False, 'error': 'Website tidak ditemukan.'}), 404
            properties = _client_for_site(site).list_properties()
            selected = site.gsc_property_url
        return jsonify({'success': True, 'properties': properties, 'selected_property': selected})
    except SearchConsoleError as exc:
        return jsonify({'success': False, 'error': _user_message(exc)}), 400


@search_console_bp.route('/api/search-console/sites/<int:site_id>/property', methods=['PUT'])
@require_jwt
def select_search_console_property(user_id, site_id):
    property_url = (request.get_json(silent=True) or {}).get('property_url')
    property_url = property_url.strip() if isinstance(property_url, str) else ''
    if not property_url:
        return jsonify({'success': False, 'error': 'Property Search Console wajib dipilih.'}), 400
    try:
        with db.get_session() as session:
            site = _site_for_user(session, user_id, site_id)
            if not site:
                return jsonify({'success': False, 'error': 'Website tidak ditemukan.'}), 404
            properties = _client_for_site(site).list_properties()
            selected = next((item for item in properties if item['site_url'] == property_url), None)
            if not selected:
                return jsonify({'success': False, 'error': 'Property tidak tersedia untuk akun Google ini.'}), 403
            if property_url != site.gsc_property_url:
                _clear_search_console_metrics(session, user_id, site_id)
                site.gsc_last_synced_at = None
            site.gsc_property_url = property_url
            site.gsc_permission_level = selected.get('permission_level')
            site.gsc_last_error = None
        return jsonify({'success': True, 'message': 'Property Search Console tersimpan.'})
    except SearchConsoleError as exc:
        return jsonify({'success': False, 'error': _user_message(exc)}), 400


@search_console_bp.route('/api/search-console/sites/<int:site_id>/sync', methods=['POST'])
@require_jwt
def sync_search_console(user_id, site_id):
    with db.get_session() as session:
        site = _site_for_user(session, user_id, site_id)
        if not site:
            return jsonify({'success': False, 'error': 'Website tidak ditemukan.'}), 404
        if not site.gsc_refresh_token or not site.gsc_property_url:
            return jsonify({'success': False, 'error': 'Hubungkan akun dan pilih property terlebih dahulu.'}), 400
    job = q.enqueue('tasks.gsc_jobs.sync_search_console_job', user_id, site_id, job_timeout='10m')
    return jsonify({'success': True, 'job_id': job.id, 'message': 'Sinkronisasi Search Console dimulai.'})


@search_console_bp.route('/api/search-console/sites/<int:site_id>/disconnect', methods=['POST'])
@require_jwt
def disconnect_search_console(user_id, site_id):
    with db.get_session() as session:
        site = _site_for_user(session, user_id, site_id)
        if not site:
            return jsonify({'success': False, 'error': 'Website tidak ditemukan.'}), 404
        site.gsc_refresh_token = None
        site.gsc_property_url = None
        site.gsc_permission_level = None
        site.gsc_connected_at = None
        site.gsc_last_error = None
        site.gsc_last_synced_at = None
        _clear_search_console_metrics(session, user_id, site_id)
    return jsonify({'success': True})


@search_console_bp.route('/api/search-console/sites/<int:site_id>/opportunities', methods=['GET'])
@require_jwt
def search_console_opportunities(user_id, site_id):
    with db.get_session() as session:
        site = _site_for_user(session, user_id, site_id)
        if not site:
            return jsonify({'success': False, 'error': 'Website tidak ditemukan.'}), 404
        metrics = session.query(SearchConsoleMetric).filter_by(
            user_id=user_id, site_id=site_id
        ).order_by(SearchConsoleMetric.synced_at.desc()).all()
        current = [metric_to_dict(row) for row in metrics if row.period_label == 'current']
        previous = [metric_to_dict(row) for row in metrics if row.period_label == 'previous']
        opportunities = build_search_opportunities(current, previous)
        return jsonify({
            'success': True,
            'connected': bool(site.gsc_refresh_token),
            'property_url': site.gsc_property_url,
            'permission_level': site.gsc_permission_level,
            'last_synced_at': site.gsc_last_synced_at.isoformat() if site.gsc_last_synced_at else None,
            'last_error': site.gsc_last_error,
            'metric_count': len(metrics),
            'opportunities': opportunities,
        })


def metric_to_dict(row):
    return {
        'query': row.query,
        'page': row.page,
        'clicks': row.clicks,
        'impressions': row.impressions,
        'ctr': row.ctr,
        'position': row.position,
    }
