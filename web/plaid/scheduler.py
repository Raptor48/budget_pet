"""
APScheduler job: sync all Plaid items daily — V2 version.

V2 sync flow per item:
  1. transactions/sync → import to transactions table
  2. accounts/balance/get → provision + update accounts table
  3. liabilities/get → update APR, min_payment, overdue on accounts
  4. recurring/get → upsert recurring_streams
  5. investments/holdings/get → upsert securities + investment_holdings
  6. snapshot net worth
  7. update cursor + log
"""
import asyncio
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

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


def start_scheduler():
    """Start APScheduler with a daily sync job at 03:00."""
    import asyncio
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    scheduler = AsyncIOScheduler()

    def _run_sync():
        loop = asyncio.get_event_loop()
        loop.create_task(sync_all_items())

    scheduler.add_job(_run_sync, "cron", hour=3, minute=0, id="plaid_daily_sync")
    scheduler.start()
    logger.info("Plaid daily sync scheduler started (runs at 03:00)")
    return scheduler
