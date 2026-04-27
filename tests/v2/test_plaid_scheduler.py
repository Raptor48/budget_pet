"""Regression tests for the autosync scheduler.

The pre-V2.1 bug: the registered job was a synchronous wrapper that called
``asyncio.get_event_loop()`` from APScheduler's ThreadPoolExecutor worker,
which raised ``RuntimeError`` silently and caused the daily sync to never
run. The fix registers ``_scheduled_sync`` (a coroutine function) directly
so APScheduler's AsyncIOExecutor awaits it on the main event loop.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from web.plaid import scheduler as scheduler_module


def _reset_scheduler_singleton() -> None:
    """Drop any AsyncIOScheduler instance left by previous tests."""
    sched = scheduler_module._scheduler
    if sched is not None:
        try:
            if sched.running:
                sched.shutdown(wait=False)
        except Exception:
            pass
    scheduler_module._scheduler = None


@pytest.fixture(autouse=True)
def _isolate_scheduler():
    _reset_scheduler_singleton()
    yield
    _reset_scheduler_singleton()


class TestSchedulerRegistration:
    @pytest.mark.asyncio
    async def test_registered_job_is_a_coroutine_function(self):
        """The callable handed to APScheduler must be an async coroutine —
        this is exactly what was broken in V2.0 (sync wrapper in a worker
        thread)."""
        sched = scheduler_module._ensure_scheduler()
        sched.start(paused=True)
        try:
            scheduler_module.apply_autosync_config(
                frequency="daily", hour_utc=3, minute_utc=0
            )
            job = sched.get_job(scheduler_module._JOB_ID)
            assert job is not None, "expected the daily sync job to be registered"
            assert asyncio.iscoroutinefunction(job.func), (
                "job.func must be an async def coroutine — otherwise APScheduler "
                "submits it to a worker thread where asyncio.get_event_loop() "
                "raises RuntimeError and the sync never fires"
            )
        finally:
            sched.shutdown(wait=False)

    def test_timezone_is_utc(self):
        sched = scheduler_module._ensure_scheduler()
        # APScheduler exposes the configured timezone via .timezone
        assert str(sched.timezone) == "UTC"

    @pytest.mark.asyncio
    async def test_apply_autosync_config_sets_hour_and_minute(self):
        sched = scheduler_module._ensure_scheduler()
        sched.start(paused=True)
        try:
            scheduler_module.apply_autosync_config(
                frequency="daily", hour_utc=7, minute_utc=30
            )
            job = sched.get_job(scheduler_module._JOB_ID)
            trig = job.trigger
            # CronTrigger keeps fields; inspect by string for portability
            repr_str = str(trig)
            assert "hour='7'" in repr_str
            assert "minute='30'" in repr_str

            # Reschedule live
            scheduler_module.apply_autosync_config(
                frequency="daily", hour_utc=21, minute_utc=15
            )
            job = sched.get_job(scheduler_module._JOB_ID)
            repr_str = str(job.trigger)
            assert "hour='21'" in repr_str
            assert "minute='15'" in repr_str
        finally:
            sched.shutdown(wait=False)

    @pytest.mark.asyncio
    async def test_apply_autosync_config_off_removes_job(self):
        sched = scheduler_module._ensure_scheduler()
        sched.start(paused=True)
        try:
            scheduler_module.apply_autosync_config(
                frequency="daily", hour_utc=3, minute_utc=0
            )
            assert sched.get_job(scheduler_module._JOB_ID) is not None

            scheduler_module.apply_autosync_config(
                frequency="off", hour_utc=3, minute_utc=0
            )
            assert sched.get_job(scheduler_module._JOB_ID) is None
        finally:
            sched.shutdown(wait=False)


class TestFrequencyTriggers:
    """Every non-``off`` frequency must map to a sane CronTrigger.

    Why we test the trigger string: APScheduler normalises cron fields to
    strings inside the CronTrigger, so string assertions are the portable
    way to pin behaviour without depending on private attributes.
    """

    @pytest.mark.parametrize(
        ("frequency", "expected_fragments"),
        [
            # Daily: no day-of-week or day constraint — fires every 24h.
            ("daily", ["hour='6'", "minute='45'"]),
            # Weekly: Sunday anchor — keeps it predictable regardless of TZ.
            ("weekly", ["day_of_week='sun'", "hour='6'", "minute='45'"]),
            # Semi-monthly: 1st and 15th, a common payroll cadence.
            ("semimonthly", ["day='1,15'", "hour='6'", "minute='45'"]),
            # Monthly: 1st of each month.
            ("monthly", ["day='1'", "hour='6'", "minute='45'"]),
        ],
    )
    @pytest.mark.asyncio
    async def test_trigger_per_frequency(self, frequency, expected_fragments):
        sched = scheduler_module._ensure_scheduler()
        sched.start(paused=True)
        try:
            scheduler_module.apply_autosync_config(
                frequency=frequency, hour_utc=6, minute_utc=45
            )
            job = sched.get_job(scheduler_module._JOB_ID)
            assert job is not None
            repr_str = str(job.trigger)
            for fragment in expected_fragments:
                assert fragment in repr_str, (
                    f"{frequency!r} trigger should contain {fragment!r}; got {repr_str}"
                )
        finally:
            sched.shutdown(wait=False)

    @pytest.mark.asyncio
    async def test_reschedule_switches_frequency_in_place(self):
        """Switching daily → monthly must not duplicate the job (one job id,
        new trigger)."""
        sched = scheduler_module._ensure_scheduler()
        sched.start(paused=True)
        try:
            scheduler_module.apply_autosync_config(
                frequency="daily", hour_utc=2, minute_utc=0
            )
            first = sched.get_job(scheduler_module._JOB_ID)
            assert first is not None
            assert "day" not in str(first.trigger)

            scheduler_module.apply_autosync_config(
                frequency="monthly", hour_utc=2, minute_utc=0
            )
            # Still exactly one job under the same id.
            jobs = [j for j in sched.get_jobs() if j.id == scheduler_module._JOB_ID]
            assert len(jobs) == 1
            assert "day='1'" in str(jobs[0].trigger)
        finally:
            sched.shutdown(wait=False)

    def test_build_cron_trigger_rejects_off(self):
        """``off`` must never produce a trigger — callers must branch first."""
        with pytest.raises(ValueError):
            scheduler_module._build_cron_trigger("off", 3, 0)

    def test_build_cron_trigger_rejects_unknown(self):
        with pytest.raises(ValueError):
            scheduler_module._build_cron_trigger("hourly", 3, 0)


class TestScheduledSyncAuditHook:
    @pytest.mark.asyncio
    async def test_scheduled_sync_writes_audit_summary(self):
        """A successful run should leave one plaid.sync_scheduled audit row."""
        fake_results = [
            {
                "item_id": "item-1",
                "transactions_added": 3,
                "balances_updated": 2,
                "status": "ok",
                "error_msg": None,
            },
            {
                "item_id": "item-2",
                "transactions_added": 0,
                "balances_updated": 1,
                "status": "error",
                "error_msg": "boom",
            },
        ]

        recorded: list[dict] = []

        async def fake_record(event_type, *, source, metadata=None, **_):
            recorded.append(
                {"event_type": event_type, "source": source, "metadata": metadata or {}}
            )

        with patch(
            "web.plaid.scheduler.sync_all_items",
            AsyncMock(return_value=fake_results),
        ), patch("web.audit.record", fake_record):
            await scheduler_module._scheduled_sync()

        assert len(recorded) == 1
        entry = recorded[0]
        assert entry["event_type"] == "plaid.sync_scheduled"
        assert entry["source"] == "scheduler"
        meta = entry["metadata"]
        assert meta["items_synced"] == 2
        assert meta["transactions_added"] == 3
        assert meta["balances_updated"] == 3
        assert len(meta["errors"]) == 1
        assert meta["errors"][0]["item_id"] == "item-2"
        assert meta["failed"] is False

    @pytest.mark.asyncio
    async def test_scheduled_sync_records_failure_and_raises(self):
        """When sync_all_items raises, we still record a failed audit row and
        re-raise so APScheduler logs the error too."""
        recorded: list[dict] = []

        async def fake_record(event_type, *, source, metadata=None, **_):
            recorded.append({"event_type": event_type, "metadata": metadata or {}})

        with patch(
            "web.plaid.scheduler.sync_all_items",
            AsyncMock(side_effect=RuntimeError("db down")),
        ), patch("web.audit.record", fake_record):
            with pytest.raises(RuntimeError, match="db down"):
                await scheduler_module._scheduled_sync()

        assert len(recorded) == 1
        assert recorded[0]["event_type"] == "plaid.sync_scheduled"
        assert recorded[0]["metadata"]["failed"] is True


class TestPostSyncInsightsInvalidation:
    """``iter_sync_all_items`` must drop the Insights cache once the last
    item finishes — otherwise the dashboard / Insights feed keeps showing
    pre-sync data for up to the cache TTL (5 minutes by default).
    """

    @pytest.mark.asyncio
    async def test_invalidates_insights_cache_after_iter_sync(self):
        from unittest.mock import MagicMock

        from web.plaid import scheduler as scheduler_module

        fake_repo = MagicMock()
        fake_repo.get_items = AsyncMock(return_value=[
            {"item_id": "item-1", "access_token": "t1"},
        ])

        async def fake_payload(_item, _source, *, audit_source):
            return {"item_id": "item-1", "status": "ok"}

        with patch(
            "web.plaid.repo.get_plaid_repo", lambda: fake_repo
        ), patch(
            "web.plaid.scheduler._sync_item_payload", fake_payload
        ), patch(
            "web.insights.store.invalidate_cache",
        ) as invalidate_mock:
            results = [
                r async for r in scheduler_module.iter_sync_all_items(audit_source="manual")
            ]

        assert results == [{"item_id": "item-1", "status": "ok"}]
        # Called once, with viewer_user_id=None (drops every entry).
        invalidate_mock.assert_called_once_with(None)

    @pytest.mark.asyncio
    async def test_invalidates_even_when_sync_raises(self):
        """The ``try / finally`` guarantees the cache is flushed even if a
        per-item sync raises mid-iteration. Otherwise a partial sync would
        leave stale data behind a bad item."""
        from unittest.mock import MagicMock

        from web.plaid import scheduler as scheduler_module

        fake_repo = MagicMock()
        fake_repo.get_items = AsyncMock(return_value=[
            {"item_id": "item-1", "access_token": "t1"},
        ])

        async def explode(*_args, **_kwargs):
            raise RuntimeError("plaid 500")

        with patch(
            "web.plaid.repo.get_plaid_repo", lambda: fake_repo
        ), patch(
            "web.plaid.scheduler._sync_item_payload", explode
        ), patch(
            "web.insights.store.invalidate_cache",
        ) as invalidate_mock:
            with pytest.raises(RuntimeError, match="plaid 500"):
                async for _ in scheduler_module.iter_sync_all_items(audit_source="manual"):
                    pass

        invalidate_mock.assert_called_once_with(None)
