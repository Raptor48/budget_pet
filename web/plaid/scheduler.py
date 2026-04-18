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
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_JOB_ID = "plaid_daily_sync"
_scheduler = None  # set by start_scheduler()


# Plaid environment → source tag stored on transactions
_PLAID_ENV_SOURCE = {
    "sandbox": "plaid_sandbox",
    "development": "plaid",
    "production": "plaid",
}


def _get_source() -> str:
    import os

    env = os.getenv("PLAID_ENV", "sandbox").lower()
    return _PLAID_ENV_SOURCE.get(env, "plaid")


def _investments_enabled() -> bool:
    """Check PLAID_ENABLE_INVESTMENTS env flag (default true for backward compat)."""
    import os

    val = os.getenv("PLAID_ENABLE_INVESTMENTS", "true").strip().lower()
    return val in ("1", "true", "yes")


async def _sync_item_payload(item: Dict[str, Any], source: str) -> Dict[str, Any]:
    """Run full Plaid sync for one item dict (from plaid_items row)."""
    import asyncio
    from .repo import get_plaid_repo
    from .client import (
        get_transactions_sync,
        get_account_balances,
        get_liabilities,
        get_recurring_transactions,
        get_investment_holdings,
    )
    from web.accounts.repo import AccountsRepository
    from web.categories.repo import CategoriesRepository
    from web.recurring.repo import RecurringRepository
    from web.investments.repo import InvestmentsRepository
    from web.reports.repo import ReportsRepository

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
        # All Plaid SDK calls are synchronous (blocking HTTP). Run them in a thread
        # pool so they don't block the asyncio event loop.
        txn_data = await asyncio.to_thread(get_transactions_sync, access_token, cursor)
        added = txn_data["added"]
        modified = txn_data["modified"]
        removed = txn_data["removed"]

        raw_accounts = await asyncio.to_thread(get_account_balances, access_token)
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

        liabilities = await asyncio.to_thread(get_liabilities, access_token)
        await repo.sync_liabilities_to_accounts(liabilities)

        recurring_data = await asyncio.to_thread(get_recurring_transactions, access_token)
        rec_repo = RecurringRepository()
        await rec_repo.upsert_streams(recurring_data["outflow_streams"], "outflow", account_id_map)
        await rec_repo.upsert_streams(recurring_data["inflow_streams"], "inflow", account_id_map)

        if _investments_enabled():
            inv_data = await asyncio.to_thread(get_investment_holdings, access_token)
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


async def sync_single_item(item_id: str) -> Optional[dict]:
    """Sync one Plaid item by id. Returns result dict or None if item missing."""
    from .repo import get_plaid_repo

    repo = get_plaid_repo()
    item = await repo.get_item(item_id)
    if not item:
        return None
    source = _get_source()
    return await _sync_item_payload(item, source)


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


async def sync_all_items() -> List[dict]:
    """
    Sync all connected Plaid items.
    Called by the daily scheduler and by the manual /api/plaid/sync endpoint.
    """
    from .repo import get_plaid_repo

    repo = get_plaid_repo()
    items = await repo.get_items()
    source = _get_source()
    results: List[dict] = []
    for item in items:
        results.append(await _sync_item_payload(item, source))
    return results


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
        results = await sync_all_items()
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
            "enabled": bool(row["autosync_enabled"]),
            "hour_utc": int(row["autosync_hour_utc"]),
            "minute_utc": int(row["autosync_minute_utc"]),
        }
    except Exception as exc:
        logger.warning(
            "Could not load autosync config, using defaults (03:00 UTC): %s", exc
        )
        return {"enabled": True, "hour_utc": 3, "minute_utc": 0}


def _ensure_scheduler():
    """Create the AsyncIOScheduler lazily (pinned to UTC)."""
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    _scheduler = AsyncIOScheduler(timezone="UTC")
    return _scheduler


def apply_autosync_config(*, enabled: bool, hour_utc: int, minute_utc: int) -> None:
    """Reconcile the APScheduler job with the desired config.

    Idempotent: adds, reschedules or removes the cron job as needed. Safe to
    call from request handlers after the settings row changes.
    """
    scheduler = _ensure_scheduler()
    existing = scheduler.get_job(_JOB_ID) if scheduler.running else None

    if not enabled:
        if existing is not None:
            scheduler.remove_job(_JOB_ID)
            logger.info("Autosync disabled — removed cron job")
        return

    if existing is None:
        scheduler.add_job(
            _scheduled_sync,
            "cron",
            hour=hour_utc,
            minute=minute_utc,
            id=_JOB_ID,
            coalesce=True,
            misfire_grace_time=3600,
            replace_existing=True,
        )
        logger.info("Autosync scheduled daily at %02d:%02d UTC", hour_utc, minute_utc)
    else:
        from apscheduler.triggers.cron import CronTrigger

        scheduler.reschedule_job(
            _JOB_ID,
            trigger=CronTrigger(hour=hour_utc, minute=minute_utc, timezone="UTC"),
        )
        logger.info("Autosync rescheduled to %02d:%02d UTC", hour_utc, minute_utc)


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
        if cfg["enabled"]:
            scheduler.add_job(
                _scheduled_sync,
                "cron",
                hour=cfg["hour_utc"],
                minute=cfg["minute_utc"],
                id=_JOB_ID,
                coalesce=True,
                misfire_grace_time=3600,
                replace_existing=True,
            )
            logger.info(
                "Plaid daily sync scheduler started (runs at %02d:%02d UTC)",
                cfg["hour_utc"],
                cfg["minute_utc"],
            )
        else:
            logger.info("Plaid daily sync scheduler started (autosync disabled)")

    scheduler.start()
    # Load the saved schedule once the event loop is free.
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_bootstrap())
    except RuntimeError:
        # Not inside a running loop (e.g. unit tests) — run synchronously.
        asyncio.get_event_loop().run_until_complete(_bootstrap())

    return scheduler
