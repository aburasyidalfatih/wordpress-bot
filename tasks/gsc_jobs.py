from datetime import datetime

from rq import get_current_job

import core_extensions
from core_extensions import db, logger
from models import SearchConsoleMetric, WordPressSite
from services.job_locks import claim_lock, gsc_sync_lock_key, release_lock, rq_job_may_run
from services.search_console import SearchConsoleClient

# Lock TTL once the sync runs: above its 10-minute RQ timeout, as a fallback for
# a worker killed before the finally block releases it.
GSC_SYNC_LOCK_RUNNING_TTL_SECONDS = 15 * 60


def _current_job():
    try:
        return get_current_job()
    except Exception:
        return None


def sync_search_console_job(user_id, site_id):
    """Synchronize finalized current/previous 28-day GSC snapshots.

    One sync per site at a time: each one deletes and re-inserts the site's
    rows, so an overlapping second sync (manual and scheduled) hit the unique
    constraint and recorded a false error. The per-site lock is taken by the
    manual route before enqueueing, or here for scheduled syncs; a sync that
    finds another one holding it is skipped quietly.
    """
    job = _current_job()
    connection = getattr(job, 'connection', None) or getattr(core_extensions, 'redis_conn', None)
    job_id = getattr(job, 'id', None)
    key = gsc_sync_lock_key(site_id)
    if connection is not None and job_id:
        try:
            claimed = claim_lock(connection, key, job_id, GSC_SYNC_LOCK_RUNNING_TTL_SECONDS,
                                 is_alive=lambda holder: rq_job_may_run(connection, holder))
        except Exception as e:
            logger.warning(f'Search Console sync lock for site_id={site_id} unavailable ({e}); syncing anyway.')
            claimed = True
        if not claimed:
            logger.info(f'Search Console sync for site_id={site_id} skipped: another sync is running.')
            return {'skipped': True, 'reason': 'Sinkronisasi lain untuk website ini sedang berjalan.'}
    try:
        return _sync_search_console(user_id, site_id)
    finally:
        if connection is not None and job_id:
            try:
                release_lock(connection, key, job_id)
            except Exception as e:
                logger.warning(f'Could not release the Search Console sync lock of site_id={site_id}: {e}')


def _sync_search_console(user_id, site_id):
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
