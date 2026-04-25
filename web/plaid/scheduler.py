"""
APScheduler job: daily Plaid sync — V2.

Sync flow per item:
  1. transactions/sync → import to transactions table
  2. accounts/balance/get → provision + update accounts table
  3. liabilities/get → update APR, min_payment, overdue on accounts
  4. recurring/get → upsert recurring_streams
  5. investments/holdings/get → upsert securities + investment_holdings
  6. snapshot net worth
  7. update cursor + log

The job itself runs once a day at the time stored in ``app_settings``. The
schedule is reloaded live when the user edits it in Settings → App.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

_JOB_ID = "plaid_daily_sync"
_scheduler = None  # set by start_scheduler()


def _plaid_sdk_timeout() -> float:
    """Per-call timeout for Plaid SDK requests (seconds).

    Plaid SDK is synchronous and blocks a thread. Without a timeout, a
    hung Plaid response would freeze the whole daily sync. Override via
    the ``PLAID_SDK_TIMEOUT`` env var on Railway if needed (default 90s).
    """
    try:
        return float(os.getenv("PLAID_SDK_TIMEOUT", "90"))
    except (TypeError, ValueError):
        return 90.0


async def _plaid_call(fn: Callable[..., Any], *args: Any) -> Any:
    """Run a sync Plaid SDK call in a thread with a hard timeout.

    Raises :class:`asyncio.TimeoutError` if the call exceeds
    :func:`_plaid_sdk_timeout`. Callers' broad ``except Exception``
    handlers will catch it and surface it via ``log_sync(status='error')``.
    """
    timeout = _plaid_sdk_timeout()
    try:
        return await asyncio.wait_for(asyncio.to_thread(fn, *args), timeout=timeout)
    except asyncio.TimeoutError:
        logger.error("Plaid SDK call %s timed out after %.0fs", fn.__name__, timeout)
        raise


# Plaid environment → source tag stored on transactions
_PLAID_ENV_SOURCE = {
    "sandbox": "plaid_sandbox",
    "development": "plaid",
    "production": "plaid",
}


def _get_source() -> str:
    env = os.getenv("PLAID_ENV", "sandbox").lower()
    return _PLAID_ENV_SOURCE.get(env, "plaid")


def _investments_enabled() -> bool:
    """Check PLAID_ENABLE_INVESTMENTS env flag (default true for backward compat)."""
    val = os.getenv("PLAID_ENABLE_INVESTMENTS", "true").strip().lower()
    return val in ("1", "true", "yes")


async def _sync_item_payload(
    item: Dict[str, Any],
    source: str,
    *,
    audit_source: str = "manual",
) -> Dict[str, Any]:
    """Run full Plaid sync for one item dict (from plaid_items row).

    ``source`` tags ingested transactions (``plaid`` / ``plaid_sandbox``),
    while ``audit_source`` tells the audit log which driver triggered this
    run (``scheduler`` / ``webhook`` / ``manual``). They are separate
    because Plaid env tagging and who-did-it attribution are independent.
    """
    from .repo import get_plaid_repo
    from .client import (
        get_transactions_sync,
        get_account_balances,
        get_liabilities,
        get_recurring_transactions,
        get_investment_holdings,
    )
    from web.accounts.missing_fields import detect_and_record_missing
    from web.accounts.repo import AccountsRepository
    from web.categories.repo import CategoriesRepository
    from web.recurring.repo import RecurringRepository
    from web.investments.repo import InvestmentsRepository
    from web.reports.repo import ReportsRepository

    from .reauth_errors import plaid_error_requires_item_reauth

    repo = get_plaid_repo()
    item_id = item["item_id"]
    access_token = item["access_token"]
    cursor = item.get("cursor")
    user_id = item.get("user_id")

    transactions_added = 0
    balances_updated = 0
    status = "ok"
    error_msg = None

    try:
        # All Plaid SDK calls are synchronous (blocking HTTP). _plaid_call runs
        # them in a thread pool with a hard timeout so a hung Plaid response
        # cannot freeze the asyncio event loop or block the daily sync.
        txn_data = await _plaid_call(get_transactions_sync, access_token, cursor)
        added = txn_data["added"]
        modified = txn_data["modified"]
        removed = txn_data["removed"]

        raw_accounts = await _plaid_call(get_account_balances, access_token)
        accounts_repo = AccountsRepository()
        await accounts_repo.provision_from_plaid(raw_accounts, item_id)

        account_id_map = await repo.build_account_id_map()
        balances_updated = len([a for a in raw_accounts if a.get("account_id") in account_id_map])

        cat_repo = CategoriesRepository()
        transactions_added = await repo.import_transactions(
            added + modified,
            account_id_map,
            source=source,
            category_resolver=cat_repo.resolve_category,
            user_id=int(user_id) if user_id is not None else None,
        )

        if removed:
            await repo.delete_removed_transactions(removed)

        await repo.update_cursor(item_id, txn_data["next_cursor"])

        liabilities = await _plaid_call(get_liabilities, access_token)
        await repo.sync_liabilities_to_accounts(liabilities)
        try:
            await detect_and_record_missing(item_id=item_id, source=audit_source)
        except Exception as exc:  # defensive: detection must never break sync
            logger.warning("missing-fields detection failed for %s: %s", item_id, exc)

        recurring_data = await _plaid_call(get_recurring_transactions, access_token)
        rec_repo = RecurringRepository()
        await rec_repo.upsert_streams(recurring_data["outflow_streams"], "outflow", account_id_map)
        await rec_repo.upsert_streams(recurring_data["inflow_streams"], "inflow", account_id_map)

        if _investments_enabled():
            inv_data = await _plaid_call(get_investment_holdings, access_token)
            if inv_data["holdings"]:
                inv_repo = InvestmentsRepository()
                await inv_repo.upsert_securities(inv_data["securities"])
                await inv_repo.upsert_holdings(inv_data["holdings"], account_id_map)

        reports_repo = ReportsRepository()
        await reports_repo.snapshot_net_worth()

        await repo.clear_connection_flags(item_id)

        logger.info(
            "Plaid sync OK: item=%s txn_added=%d balances_updated=%d modified=%d removed=%d",
            item_id,
            transactions_added,
            balances_updated,
            len(modified),
            len(removed),
        )

    except Exception as exc:
        status = "error"
        error_msg = str(exc)
        logger.error("Plaid sync failed for item %s: %s", item_id, exc, exc_info=True)
        if plaid_error_requires_item_reauth(exc):
            await repo.set_item_login_required(item_id, True)
            logger.warning(
                "Marked item %s as item_login_required after re-auth Plaid error", item_id
            )

    await repo.log_sync(
        item_id,
        transactions_added=transactions_added,
        balances_updated=balances_updated,
        status=status,
        error_msg=error_msg,
    )
    return {
        "item_id": item_id,
        "transactions_added": transactions_added,
        "balances_updated": balances_updated,
        "status": status,
        "error_msg": error_msg,
    }


async def sync_single_item(
    item_id: str, *, audit_source: str = "webhook"
) -> Optional[dict]:
    """Sync one Plaid item by id. Returns result dict or None if item missing.

    Defaults ``audit_source='webhook'`` because the only current caller is
    the debounced webhook handler; manual single-item syncs should pass
    ``audit_source='manual'`` explicitly.
    """
    from .repo import get_plaid_repo

    repo = get_plaid_repo()
    item = await repo.get_item(item_id)
    if not item:
        return None
    source = _get_source()
    return await _sync_item_payload(item, source, audit_source=audit_source)


_debounce_tasks: dict[str, asyncio.Task] = {}


def schedule_debounced_sync_item(item_id: str, delay_sec: float = 12.0) -> None:
    """Coalesce SYNC_UPDATES_AVAILABLE bursts into a single delayed sync."""

    async def _job() -> None:
        try:
            await asyncio.sleep(delay_sec)
            await sync_single_item(item_id)
        finally:
            _debounce_tasks.pop(item_id, None)

    existing = _debounce_tasks.get(item_id)
    if existing and not existing.done():
        existing.cancel()
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.get_event_loop()
    _debounce_tasks[item_id] = loop.create_task(_job())


async def iter_sync_all_items(*, audit_source: str = "manual"):
    """Yield one result dict per Plaid item (same payloads as ``sync_all_items``)."""
    from .repo import get_plaid_repo

    repo = get_plaid_repo()
    items = await repo.get_items()
    source = _get_source()
    for item in items:
        yield await _sync_item_payload(item, source, audit_source=audit_source)


async def sync_all_items(*, audit_source: str = "manual") -> List[dict]:
    """
    Sync all connected Plaid items.
    Called by the daily scheduler and by the manual /api/plaid/sync endpoint.

    ``audit_source`` flags who drove this run for the audit log — the
    scheduler passes ``scheduler``, manual endpoints pass ``manual``.
    """
    return [r async for r in iter_sync_all_items(audit_source=audit_source)]


# ---------------------------------------------------------------------------
# Scheduler lifecycle
# ---------------------------------------------------------------------------


async def _scheduled_sync() -> None:
    """Coroutine invoked by APScheduler at the configured cron time.

    Runs the full sync for every connected item and appends one summary
    row to ``audit_log`` so the Log tab shows a scheduled event even when
    nothing changed on Plaid's side.
    """
    from web.audit import record as audit_record

    logger.info("Scheduled Plaid sync starting")
    results: List[dict] = []
    exception: Optional[BaseException] = None
    try:
        results = await sync_all_items(audit_source="scheduler")
    except BaseException as exc:  # noqa: BLE001 — we record and re-raise below
        exception = exc
        logger.error("Scheduled Plaid sync failed: %s", exc, exc_info=True)

    items_synced = len(results)
    txn_total = sum(int(r.get("transactions_added") or 0) for r in results)
    balances_total = sum(int(r.get("balances_updated") or 0) for r in results)
    errors = [r for r in results if r.get("status") != "ok"]

    await audit_record(
        "plaid.sync_scheduled",
        source="scheduler",
        metadata={
            "items_synced": items_synced,
            "transactions_added": txn_total,
            "balances_updated": balances_total,
            "errors": [
                {"item_id": e.get("item_id"), "error": e.get("error_msg")}
                for e in errors
            ],
            "failed": exception is not None,
        },
    )

    if exception is not None:
        # Let APScheduler surface the error in its own logs too.
        raise exception

    logger.info(
        "Scheduled Plaid sync complete: items=%d txn_added=%d errors=%d",
        items_synced,
        txn_total,
        len(errors),
    )


async def _load_autosync_config() -> dict:
    """Read autosync schedule from app_settings, falling back to defaults."""
    try:
        from web.app_settings.repo import get_app_settings_repo
        row = await get_app_settings_repo().get()
        return {
            "frequency": str(row["autosync_frequency"]),
            "hour_utc": int(row["autosync_hour_utc"]),
            "minute_utc": int(row["autosync_minute_utc"]),
        }
    except Exception as exc:
        logger.warning(
            "Could not load autosync config, using defaults (daily @ 03:00 UTC): %s", exc
        )
        return {"frequency": "daily", "hour_utc": 3, "minute_utc": 0}


def _ensure_scheduler():
    """Create the AsyncIOScheduler lazily (pinned to UTC)."""
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    _scheduler = AsyncIOScheduler(timezone="UTC")
    return _scheduler


# Anchor days per frequency. Kept here so the scheduler and any UI copy
# referring to "runs on …" agree. See `docs/plaid.md`.
_FREQUENCY_CRON_KWARGS = {
    # APScheduler CronTrigger kwargs (timezone is applied separately).
    "daily":        {},
    "weekly":       {"day_of_week": "sun"},
    "semimonthly":  {"day": "1,15"},
    "monthly":      {"day": "1"},
}


def _build_cron_trigger(frequency: str, hour_utc: int, minute_utc: int):
    """Return an APScheduler CronTrigger for the given frequency.

    ``off`` is intentionally *not* handled here — callers must check for it
    before building a trigger, because APScheduler cron would still fire
    daily at HH:MM if we returned a bare trigger.
    """
    from apscheduler.triggers.cron import CronTrigger

    if frequency == "off":
        raise ValueError("_build_cron_trigger should not be called with frequency='off'")
    extra = _FREQUENCY_CRON_KWARGS.get(frequency)
    if extra is None:
        raise ValueError(f"Unsupported frequency: {frequency!r}")
    return CronTrigger(
        hour=hour_utc,
        minute=minute_utc,
        timezone="UTC",
        **extra,
    )


def apply_autosync_config(*, frequency: str, hour_utc: int, minute_utc: int) -> None:
    """Reconcile the APScheduler job with the desired config.

    Idempotent: adds, reschedules or removes the cron job as needed. Safe to
    call from request handlers after the settings row changes. ``frequency``
    must be one of ``AUTOSYNC_FREQUENCIES`` (validated upstream by the model).
    """
    scheduler = _ensure_scheduler()
    existing = scheduler.get_job(_JOB_ID) if scheduler.running else None

    if frequency == "off":
        if existing is not None:
            scheduler.remove_job(_JOB_ID)
            logger.info("Autosync disabled — removed cron job")
        return

    trigger = _build_cron_trigger(frequency, hour_utc, minute_utc)

    if existing is None:
        scheduler.add_job(
            _scheduled_sync,
            trigger=trigger,
            id=_JOB_ID,
            coalesce=True,
            misfire_grace_time=3600,
            replace_existing=True,
        )
        logger.info(
            "Autosync scheduled (%s) at %02d:%02d UTC", frequency, hour_utc, minute_utc
        )
    else:
        scheduler.reschedule_job(_JOB_ID, trigger=trigger)
        logger.info(
            "Autosync rescheduled (%s) to %02d:%02d UTC", frequency, hour_utc, minute_utc
        )


def get_scheduler_status() -> Dict[str, Any]:
    """Return a small dict describing the live cron job (for UI/status)."""
    scheduler = _ensure_scheduler()
    if not scheduler.running:
        return {"running": False, "next_run_at": None}
    job = scheduler.get_job(_JOB_ID)
    return {
        "running": True,
        "next_run_at": getattr(job, "next_run_time", None) if job else None,
    }


def start_scheduler():
    """Start APScheduler with the autosync job loaded from ``app_settings``."""
    scheduler = _ensure_scheduler()

    async def _bootstrap() -> None:
        cfg = await _load_autosync_config()
        if cfg["frequency"] != "off":
            scheduler.add_job(
                _scheduled_sync,
                trigger=_build_cron_trigger(
                    cfg["frequency"], cfg["hour_utc"], cfg["minute_utc"]
                ),
                id=_JOB_ID,
                coalesce=True,
                misfire_grace_time=3600,
                replace_existing=True,
            )
            logger.info(
                "Plaid autosync scheduler started (frequency=%s, %02d:%02d UTC)",
                cfg["frequency"],
                cfg["hour_utc"],
                cfg["minute_utc"],
            )
        else:
            logger.info("Plaid autosync scheduler started (autosync off)")

    scheduler.start()
    # Load the saved schedule once the event loop is free.
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_bootstrap())
    except RuntimeError:
        # Not inside a running loop (e.g. unit tests) — run synchronously.
        asyncio.get_event_loop().run_until_complete(_bootstrap())

    return scheduler
