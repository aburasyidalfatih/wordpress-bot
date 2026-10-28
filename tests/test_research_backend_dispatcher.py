"""Dispatcher research maintenance: daily scheduled research, reservation
reconciliation (exactly once) and research retention."""
import sys
import types
import unittest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

import database
from models import ResearchData, User
from test_research_backend_support import FakeRedis, make_db

with patch('database.Database', Mock()):
    sys.modules.pop('dispatcher', None)
    import dispatcher  # noqa: E402

MIDNIGHT = datetime(2026, 10, 14, 0, 20)


class DispatcherTestCase(unittest.TestCase):
    def setUp(self):
        self.db = make_db()
        with self.db.get_session() as s:
            s.add(User(id=1, email='u@example.com', credits=0))
        self.redis = FakeRedis()
        self.queue = Mock()
        self.statuses = {}
        patches = [
            patch.object(dispatcher, 'db', self.db),
            patch.object(dispatcher, 'redis_conn', self.redis),
            patch.object(dispatcher, 'research_q', self.queue),
            patch.object(dispatcher, '_job_status_or_missing', lambda job_id: self.statuses.get(job_id, 'missing')),
            patch.object(dispatcher, 'StartedJobRegistry', Mock()),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def credits(self):
        with self.db.get_session() as s:
            return s.get(User, 1).credits


class ScheduledResearchTests(DispatcherTestCase):
    def site(self, names=('Keuangan', 'keuangan', 'Parenting', 'Bisnis'), auto_post=True, site_id=1):
        return types.SimpleNamespace(id=site_id, user_id=1, auto_post=auto_post, timezone='Asia/Jakarta',
                                     selected_categories=[{'name': n} for n in names])

    def test_sites_are_staggered_across_the_hour(self):
        site = self.site(site_id=30)
        self.assertIsNone(dispatcher._schedule_daily_research(site, now_site=MIDNIGHT))  # 00:20 < offset 30
        self.queue.enqueue.assert_not_called()
        self.assertTrue(dispatcher._schedule_daily_research(site, now_site=MIDNIGHT.replace(minute=31)))
        offsets = {dispatcher._research_schedule_offset(i) for i in range(200)}
        self.assertEqual(max(offsets), dispatcher.RESEARCH_SCHEDULE_SPREAD_MINUTES - 1)

    def add_research(self, category, age_days, topics=None, used=False, confidence='high'):
        stamp = datetime.now() - timedelta(days=age_days)
        with self.db.get_session() as s:
            s.add(ResearchData(user_id=1, site_id=1, category=category, confidence_level=confidence,
                               researched_at=stamp, created_at=stamp, used=used,
                               suggested_topics=list(topics) if topics is not None else None))

    def test_category_running_out_of_topics_is_refreshed_early(self):
        self.add_research('Keuangan', 10, topics=[{'topic': 'Dana darurat'}])  # 1 topic left, 10 days old
        self.add_research('Parenting', 10, topics=['Disiplin anak', {'topic': 'Bermain'}, {'topic': ' '}])  # 2 left
        self.add_research('Bisnis', 3, topics=[])  # none left, but too young for an early refresh
        self.assertTrue(dispatcher._schedule_daily_research(self.site(), now_site=MIDNIGHT))
        self.assertEqual(self.queue.enqueue.call_args.kwargs['categories'], ['Keuangan'])
        # Same free scheduled job: force=False, never charged.
        self.assertEqual(self.queue.enqueue.call_args.args[2], False)

    def test_topics_of_older_fresh_rows_count_but_used_or_expired_rows_do_not(self):
        self.add_research('Keuangan', 20, topics=['A'])
        self.add_research('Keuangan', 10, topics=['B'])
        self.add_research('Keuangan', 12, topics=['C', 'D'], used=True)
        self.add_research('Keuangan', 40, topics=['E', 'F'])
        self.add_research('Keuangan', 15, topics=['G', 'H'], confidence='insufficient')
        self.assertEqual(self.db.unused_research_topic_counts(1, 1), {'Keuangan': 2})
        self.assertEqual(dispatcher._stale_research_categories(self.site(names=('Keuangan',))), [])

    def test_enqueues_only_stale_or_missing_categories_once_per_day(self):
        self.add_research('Keuangan', 30.5)  # older than 30 days: refresh before it expires (35)
        self.add_research('Parenting', 2)    # fresh
        job_id = dispatcher._schedule_daily_research(self.site(), now_site=MIDNIGHT)
        self.assertTrue(job_id)
        args, kwargs = self.queue.enqueue.call_args
        self.assertEqual(args, ('tasks.research_jobs.deep_research_job', 1, False, 1, None))
        self.assertEqual(kwargs['categories'], ['Keuangan', 'Bisnis'])
        self.assertEqual(kwargs['job_id'], job_id)
        self.assertEqual(database.get_research_lock(self.redis, 1), job_id)

        # Idempotent for the rest of the day, even after the job ended.
        database.release_research_lock(self.redis, 1, job_id)
        self.assertIsNone(dispatcher._schedule_daily_research(self.site(), now_site=MIDNIGHT))
        self.assertIsNone(dispatcher._schedule_daily_research(
            self.site(), now_site=MIDNIGHT + timedelta(minutes=30)))
        self.assertEqual(self.queue.enqueue.call_count, 1)
        # The next day runs again.
        self.assertTrue(dispatcher._schedule_daily_research(self.site(), now_site=MIDNIGHT + timedelta(days=1)))

    def test_outside_the_hour_or_without_auto_post_nothing_happens(self):
        self.assertIsNone(dispatcher._schedule_daily_research(self.site(), now_site=MIDNIGHT.replace(hour=1)))
        self.assertIsNone(dispatcher._schedule_daily_research(self.site(auto_post=False), now_site=MIDNIGHT))
        self.queue.enqueue.assert_not_called()

    def test_all_fresh_marks_the_day_done(self):
        for name in ('Keuangan', 'Parenting', 'Bisnis'):
            self.add_research(name, 1)
        self.assertIsNone(dispatcher._schedule_daily_research(self.site(), now_site=MIDNIGHT))
        self.queue.enqueue.assert_not_called()
        self.assertTrue(self.redis.exists('research_sched:1:2026-10-14'))

    def test_active_manual_job_defers_to_a_later_pass(self):
        database.acquire_research_lock(self.redis, 1, 'manual-job', 5000)
        self.statuses['manual-job'] = 'started'
        self.assertIsNone(dispatcher._schedule_daily_research(self.site(), now_site=MIDNIGHT))
        self.queue.enqueue.assert_not_called()
        self.statuses['manual-job'] = 'finished'
        self.assertTrue(dispatcher._schedule_daily_research(self.site(), now_site=MIDNIGHT))

    def test_enqueue_failure_allows_retry(self):
        self.queue.enqueue.side_effect = RuntimeError('redis down')
        self.assertIsNone(dispatcher._schedule_daily_research(self.site(), now_site=MIDNIGHT))
        self.assertIsNone(database.get_research_lock(self.redis, 1))
        self.queue.enqueue.side_effect = None
        self.assertTrue(dispatcher._schedule_daily_research(self.site(), now_site=MIDNIGHT))


class ReconciliationTests(DispatcherTestCase):
    def reserve(self, job_id, charged=3, successful=0):
        database.acquire_research_lock(self.redis, 1, job_id, 5000)
        record = database.record_research_charge(self.redis, job_id, 1, 1, charged, 600, now=self.redis.now)
        if successful:
            record['successful'] = successful
            database.update_research_charge(self.redis, job_id, record)

    def test_killed_job_is_refunded_exactly_once(self):
        self.reserve('job-1', charged=3, successful=1)
        self.statuses['job-1'] = 'failed'
        # Too young: the job's timeout has not passed yet.
        self.assertEqual(dispatcher.reconcile_research_charges(now=self.redis.now + 60), 0)
        self.assertEqual(self.credits(), 0)
        now = self.redis.now + 601
        self.assertEqual(dispatcher.reconcile_research_charges(now=now), 2)
        self.assertEqual(dispatcher.reconcile_research_charges(now=now), 0)
        self.assertEqual(self.credits(), 2)
        self.assertIsNone(database.get_research_lock(self.redis, 1))

    def test_job_and_sweep_never_both_refund(self):
        self.reserve('job-2', charged=2)
        self.statuses['job-2'] = 'failed'
        dispatcher.reconcile_research_charges(now=self.redis.now + 601)
        # The job's own settlement afterwards finds the record gone.
        self.assertIsNone(database.take_research_charge(self.redis, 'job-2'))
        self.assertEqual(self.credits(), 2)

    def test_live_and_finished_jobs_are_not_refunded(self):
        self.reserve('live', charged=2)
        self.statuses['live'] = 'started'
        dispatcher.reconcile_research_charges(now=self.redis.now + 10_000)
        self.assertIsNotNone(database.read_research_charge(self.redis, 'live'))
        self.statuses['live'] = 'finished'  # settled itself; only the record was left behind
        dispatcher.reconcile_research_charges(now=self.redis.now + 10_000)
        self.assertIsNone(database.read_research_charge(self.redis, 'live'))
        self.assertEqual(self.credits(), 0)

    def test_failed_refund_keeps_the_record(self):
        self.reserve('job-3', charged=1)
        self.statuses['job-3'] = 'failed'
        with patch.object(self.db, 'refund_user_credits', side_effect=RuntimeError('db down')):
            dispatcher.reconcile_research_charges(now=self.redis.now + 601)
        self.assertIsNotNone(database.read_research_charge(self.redis, 'job-3'))
        dispatcher.reconcile_research_charges(now=self.redis.now + 601)
        self.assertEqual(self.credits(), 1)

    def test_job_never_started_is_cancelled_and_refunded(self):
        self.reserve('stuck', charged=2)
        self.statuses['stuck'] = 'queued'
        cancelled = []

        def cancel(job_id):
            cancelled.append(job_id)
            self.statuses[job_id] = 'canceled'
            return 'canceled'

        with patch.object(dispatcher, '_cancel_research_job', cancel):
            # Still within the queue-wait allowance: left alone.
            dispatcher.reconcile_research_charges(now=self.redis.now + 3600)
            self.assertEqual((cancelled, self.credits()), ([], 0))
            dispatcher.reconcile_research_charges(now=self.redis.now + database.RESEARCH_MAX_QUEUE_WAIT_SECONDS)
        self.assertEqual(cancelled, ['stuck'])
        self.assertEqual(self.credits(), 2)
        self.assertIsNone(database.get_research_lock(self.redis, 1))

    def test_record_handed_back_after_failed_refund_is_refunded_even_if_finished(self):
        record = database.record_research_charge(self.redis, 'job-4', 1, 1, 3, 600, now=self.redis.now)
        database.take_research_charge(self.redis, 'job-4')
        database.restore_research_charge(self.redis, 'job-4', record, owed=1)
        self.statuses['job-4'] = 'finished'
        self.assertEqual(dispatcher.reconcile_research_charges(now=self.redis.now + 601), 1)
        self.assertEqual(self.credits(), 1)

    def test_lock_sweep_cancels_a_job_that_never_started(self):
        database.acquire_research_lock(self.redis, 9, 'sched-stuck', now=1000)
        self.statuses['sched-stuck'] = 'queued'

        def cancel(job_id):
            self.statuses[job_id] = 'canceled'
            return 'canceled'

        with patch.object(dispatcher, '_cancel_research_job', cancel):
            dispatcher.release_stale_research_locks(now=1000 + 3600)
            self.assertEqual(database.get_research_lock(self.redis, 9), 'sched-stuck')
            dispatcher.release_stale_research_locks(now=1000 + database.RESEARCH_MAX_QUEUE_WAIT_SECONDS)
        self.assertIsNone(database.get_research_lock(self.redis, 9))

    def test_missing_worker_warning_is_throttled(self):
        self.queue.count = 3
        with patch.object(dispatcher, 'Worker', Mock(**{'count.return_value': 0})),                 patch.object(dispatcher.logger, 'warning') as warning:
            self.assertTrue(dispatcher.warn_if_research_worker_missing())
            self.assertTrue(dispatcher.warn_if_research_worker_missing())
        self.assertEqual(warning.call_count, 1)
        with patch.object(dispatcher, 'Worker', Mock(**{'count.return_value': 1})):
            self.assertFalse(dispatcher.warn_if_research_worker_missing())

    def test_stale_lock_sweep(self):
        database.acquire_research_lock(self.redis, 7, 'dead', 5000)
        database.acquire_research_lock(self.redis, 8, 'alive', 5000)
        self.statuses.update({'dead': 'failed', 'alive': 'queued'})
        dispatcher.release_stale_research_locks()
        self.assertIsNone(database.get_research_lock(self.redis, 7))
        self.assertEqual(database.get_research_lock(self.redis, 8), 'alive')


class RetentionTests(DispatcherTestCase):
    def test_old_rows_deleted_except_latest_two_per_category(self):
        now = datetime.now()
        with self.db.get_session() as s:
            for i, age in enumerate((200, 150, 120, 100, 10)):
                stamp = now - timedelta(days=age)
                s.add(ResearchData(id=i + 1, user_id=1, site_id=1, category='Keuangan',
                                   researched_at=stamp, created_at=stamp))
            for i, age in enumerate((300, 250)):
                stamp = now - timedelta(days=age)
                s.add(ResearchData(id=10 + i, user_id=1, site_id=1, category='Parenting',
                                   researched_at=stamp, created_at=stamp))
        self.assertEqual(dispatcher.cleanup_old_research_daily(), 3)
        with self.db.get_session() as s:
            self.assertEqual(sorted(r.id for r in s.query(ResearchData)), [4, 5, 10, 11])
        # Once a day.
        self.assertIsNone(dispatcher.cleanup_old_research_daily())


if __name__ == '__main__':
    unittest.main()
