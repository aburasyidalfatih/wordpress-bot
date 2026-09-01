from datetime import datetime

from core_extensions import db, logger
from models import SearchConsoleMetric, WordPressSite
from services.search_console import SearchConsoleClient


def sync_search_console_job(user_id, site_id):
    """Synchronize finalized current/previous 28-day GSC snapshots."""
    try:
        with db.get_session() as session:
            site = session.query(WordPressSite).filter_by(id=site_id, user_id=user_id).first()
            if not site:
                raise ValueError('Website tidak ditemukan')
            refresh_token = site.gsc_refresh_token
            property_url = site.gsc_property_url
            site_client_id = site.gsc_client_id
            site_client_secret = site.gsc_client_secret
        if not refresh_token or not property_url:
            raise ValueError('Search Console belum terhubung atau property belum dipilih')

        client_id, client_secret = site_client_id, site_client_secret
        if not client_id or not client_secret:
            raise ValueError('Google OAuth belum dikonfigurasi untuk website ini')
        client = SearchConsoleClient(client_id, client_secret, refresh_token=refresh_token)
        periods = client.query_current_and_previous_periods(property_url)
        synced_at = datetime.now()

        with db.get_session() as session:
            site = session.query(WordPressSite).filter_by(id=site_id, user_id=user_id).first()
            if not site:
                raise ValueError('Website tidak ditemukan saat menyimpan hasil sinkronisasi')
            # Keep one comparable current/previous snapshot pair per site.
            session.query(SearchConsoleMetric).filter_by(
                user_id=user_id, site_id=site_id
            ).delete(synchronize_session=False)
            total_rows = 0
            for label, period in periods.items():
                for row in period['rows']:
                    session.add(SearchConsoleMetric(
                        user_id=user_id,
                        site_id=site_id,
                        property_url=property_url,
                        period_start=datetime.combine(period['start'], datetime.min.time()),
                        period_end=datetime.combine(period['end'], datetime.min.time()),
                        period_label=label,
                        query=row['query'][:1000],
                        page=row['page'][:1500],
                        clicks=row['clicks'],
                        impressions=row['impressions'],
                        ctr=row['ctr'],
                        position=row['position'],
                        synced_at=synced_at,
                    ))
                    total_rows += 1
            site.gsc_last_synced_at = synced_at
            site.gsc_last_error = None

        logger.info(f'Search Console sync completed for site_id={site_id}: {total_rows} rows')
        return {'rows_saved': total_rows, 'property_url': property_url}
    except Exception as exc:
        logger.error(f'Search Console sync failed for site_id={site_id}: {exc}')
        try:
            with db.get_session() as session:
                site = session.query(WordPressSite).filter_by(id=site_id, user_id=user_id).first()
                if site:
                    site.gsc_last_error = str(exc)[:500]
        except Exception as save_exc:
            logger.error(f'Could not persist Search Console sync error: {save_exc}')
        raise
