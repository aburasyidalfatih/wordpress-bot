"""Minimal read-only Google Search Console OAuth and API client."""
from datetime import date, timedelta
from urllib.parse import quote, urlencode, urlparse

import requests


GSC_READONLY_SCOPE = 'https://www.googleapis.com/auth/webmasters.readonly'
GOOGLE_AUTH_URL = 'https://accounts.google.com/o/oauth2/v2/auth'
GOOGLE_TOKEN_URL = 'https://oauth2.googleapis.com/token'
GSC_API_BASE = 'https://www.googleapis.com/webmasters/v3'


class SearchConsoleError(RuntimeError):
    pass


def build_authorization_url(client_id, redirect_uri, state):
    params = {
        'client_id': client_id,
        'redirect_uri': redirect_uri,
        'response_type': 'code',
        'scope': GSC_READONLY_SCOPE,
        'access_type': 'offline',
        'include_granted_scopes': 'true',
        'prompt': 'consent',
        'state': state,
    }
    return GOOGLE_AUTH_URL + '?' + urlencode(params)


def exchange_authorization_code(client_id, client_secret, redirect_uri, code):
    response = requests.post(GOOGLE_TOKEN_URL, data={
        'client_id': client_id,
        'client_secret': client_secret,
        'redirect_uri': redirect_uri,
        'code': code,
        'grant_type': 'authorization_code',
    }, timeout=20)
    if not response.ok:
        raise SearchConsoleError(f'Google OAuth token exchange failed ({response.status_code})')
    payload = response.json()
    if not payload.get('access_token'):
        raise SearchConsoleError('Google OAuth did not return an access token')
    return payload


class SearchConsoleClient:
    def __init__(self, client_id, client_secret, refresh_token=None, access_token=None):
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self._access_token = access_token

    def _token(self):
        if self._access_token:
            return self._access_token
        if not self.refresh_token:
            raise SearchConsoleError('Search Console refresh token is unavailable')
        response = requests.post(GOOGLE_TOKEN_URL, data={
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'refresh_token': self.refresh_token,
            'grant_type': 'refresh_token',
        }, timeout=20)
        if not response.ok:
            raise SearchConsoleError(f'Google OAuth refresh failed ({response.status_code})')
        self._access_token = response.json().get('access_token')
        if not self._access_token:
            raise SearchConsoleError('Google OAuth refresh returned no access token')
        return self._access_token

    def _request(self, method, url, **kwargs):
        headers = dict(kwargs.pop('headers', {}))
        headers['Authorization'] = f'Bearer {self._token()}'
        response = requests.request(method, url, headers=headers, timeout=30, **kwargs)
        if not response.ok:
            detail = ''
            try:
                detail = response.json().get('error', {}).get('message', '')
            except Exception:
                pass
            raise SearchConsoleError(
                f'Search Console API failed ({response.status_code})'
                + (f': {detail[:200]}' if detail else '')
            )
        return response.json()

    def list_properties(self):
        payload = self._request('GET', f'{GSC_API_BASE}/sites')
        return [
            {
                'site_url': item.get('siteUrl'),
                'permission_level': item.get('permissionLevel'),
            }
            for item in payload.get('siteEntry', [])
            if item.get('siteUrl')
        ]

    def query_search_analytics(self, property_url, start_date, end_date,
                               dimensions=('query', 'page'), row_limit=5000):
        encoded_property = quote(property_url, safe='')
        payload = self._request(
            'POST',
            f'{GSC_API_BASE}/sites/{encoded_property}/searchAnalytics/query',
            json={
                'startDate': start_date.isoformat(),
                'endDate': end_date.isoformat(),
                'dimensions': list(dimensions),
                'type': 'web',
                'dataState': 'final',
                'rowLimit': min(max(int(row_limit), 1), 25000),
                'startRow': 0,
            },
        )
        rows = []
        for row in payload.get('rows', []):
            keys = row.get('keys', [])
            rows.append({
                'query': keys[0] if len(keys) > 0 else '',
                'page': keys[1] if len(keys) > 1 else '',
                'clicks': float(row.get('clicks', 0)),
                'impressions': float(row.get('impressions', 0)),
                'ctr': float(row.get('ctr', 0)),
                'position': float(row.get('position', 0)),
            })
        return rows

    def query_current_and_previous_periods(self, property_url, period_days=28):
        # Search Console finalized data can lag; end two days before today.
        current_end = date.today() - timedelta(days=2)
        current_start = current_end - timedelta(days=period_days - 1)
        previous_end = current_start - timedelta(days=1)
        previous_start = previous_end - timedelta(days=period_days - 1)
        return {
            'current': {
                'start': current_start,
                'end': current_end,
                'rows': self.query_search_analytics(property_url, current_start, current_end),
            },
            'previous': {
                'start': previous_start,
                'end': previous_end,
                'rows': self.query_search_analytics(property_url, previous_start, previous_end),
            },
        }


def find_matching_property(properties, wordpress_url):
    """Prefer an exact domain property, then the longest matching URL prefix."""
    host = (urlparse(wordpress_url).hostname or '').lower().removeprefix('www.')
    if not host:
        return None
    domain_match = next(
        (item for item in properties if item['site_url'].lower() == f'sc-domain:{host}'),
        None,
    )
    if domain_match:
        return domain_match
    prefixes = []
    for item in properties:
        site_url = item['site_url']
        if site_url.startswith(('http://', 'https://')):
            property_host = (urlparse(site_url).hostname or '').lower().removeprefix('www.')
            if property_host == host:
                prefixes.append(item)
    return max(prefixes, key=lambda item: len(item['site_url']), default=None)


def build_search_opportunities(current_rows, previous_rows, limit=20):
    """Create explainable quick wins from aggregate GSC evidence."""
    previous_map = {
        (row.get('query', ''), row.get('page', '')): row
        for row in previous_rows or []
    }
    opportunities = []
    for row in current_rows or []:
        impressions = float(row.get('impressions') or 0)
        clicks = float(row.get('clicks') or 0)
        position = float(row.get('position') or 0)
        ctr = float(row.get('ctr') or 0)
        if impressions < 20 or not row.get('query'):
            continue
        previous = previous_map.get((row.get('query', ''), row.get('page', '')), {})
        previous_clicks = float(previous.get('clicks') or 0)
        previous_position = float(previous.get('position') or 0)
        click_change = clicks - previous_clicks
        position_change = previous_position - position if previous_position else None

        if 4 <= position <= 20:
            opportunity_type = 'quick_win'
            rationale = 'Impression sudah ada dan posisi berada pada rentang 4–20.'
        elif position <= 10 and ctr < .02:
            opportunity_type = 'low_ctr'
            rationale = 'Sudah berada di halaman pertama tetapi CTR masih di bawah 2%.'
        elif previous_clicks > 0 and click_change < -(previous_clicks * .2):
            opportunity_type = 'declining'
            rationale = 'Klik turun lebih dari 20% dibanding periode sebelumnya.'
        else:
            continue

        # Transparent heuristic: demand + closeness to page one + CTR/headroom.
        demand = min(40, impressions / 25)
        rank_headroom = max(0, 35 - abs(8 - position) * 2)
        ctr_headroom = max(0, min(25, (.05 - ctr) * 500))
        score = round(max(0, min(100, demand + rank_headroom + ctr_headroom)))
        opportunities.append({
            'type': opportunity_type,
            'query': row.get('query'),
            'page': row.get('page'),
            'clicks': round(clicks, 1),
            'impressions': round(impressions, 1),
            'ctr': round(ctr * 100, 2),
            'position': round(position, 1),
            'click_change': round(click_change, 1),
            'position_change': round(position_change, 1) if position_change is not None else None,
            'opportunity_score': score,
            'rationale': rationale,
        })
    return sorted(
        opportunities,
        key=lambda item: (item['opportunity_score'], item['impressions']),
        reverse=True,
    )[:limit]
