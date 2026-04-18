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
                enabled=True, hour_utc=3, minute_utc=0
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
                enabled=True, hour_utc=7, minute_utc=30
            )
            job = sched.get_job(scheduler_module._JOB_ID)
            trig = job.trigger
            # CronTrigger keeps fields; inspect by string for portability
            repr_str = str(trig)
            assert "hour='7'" in repr_str
            assert "minute='30'" in repr_str

            # Reschedule live
            scheduler_module.apply_autosync_config(
                enabled=True, hour_utc=21, minute_utc=15
            )
            job = sched.get_job(scheduler_module._JOB_ID)
            repr_str = str(job.trigger)
            assert "hour='21'" in repr_str
            assert "minute='15'" in repr_str
        finally:
            sched.shutdown(wait=False)

    @pytest.mark.asyncio
    async def test_apply_autosync_config_disabled_removes_job(self):
        sched = scheduler_module._ensure_scheduler()
        sched.start(paused=True)
        try:
            scheduler_module.apply_autosync_config(
                enabled=True, hour_utc=3, minute_utc=0
            )
            assert sched.get_job(scheduler_module._JOB_ID) is not None

            scheduler_module.apply_autosync_config(
                enabled=False, hour_utc=3, minute_utc=0
            )
            assert sched.get_job(scheduler_module._JOB_ID) is None
        finally:
            sched.shutdown(wait=False)


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
