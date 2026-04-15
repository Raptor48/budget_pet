"""
APScheduler job: sync all Plaid items daily.
"""
import logging
from typing import List

logger = logging.getLogger(__name__)


async def sync_all_items() -> List[dict]:
    """
    Sync transactions and balances for every connected Plaid item.
    Called both by the scheduler and by the manual /api/plaid/sync endpoint.
    """
    from .repo import get_plaid_repo
    from .client import get_transactions_sync, get_account_balances

    repo = get_plaid_repo()
    items = await repo.get_all_items_with_tokens()
    results = []

    for item in items:
        item_id = item["item_id"]
        access_token = item["access_token"]
        cursor = item.get("cursor")

        transactions_added = 0
        balances_updated = 0
        status = "ok"
        error_msg = None

        try:
            # --- Transactions sync ---
            category_map = await repo.get_category_map()
            txn_data = get_transactions_sync(access_token, cursor)
            transactions_added = await repo.import_transactions(txn_data["added"], category_map)
            await repo.update_cursor(item_id, txn_data["next_cursor"])

            # --- Balance sync ---
            accounts = get_account_balances(access_token)
            balances_updated = await repo.sync_balances(accounts)

            logger.info(
                "Plaid sync OK: item=%s txn_added=%d balances_updated=%d",
                item_id, transactions_added, balances_updated
            )
        except Exception as e:
            status = "error"
            error_msg = str(e)
            logger.error("Plaid sync failed for item %s: %s", item_id, e)

        await repo.log_sync(item_id, transactions_added, balances_updated, status, error_msg)
        results.append({
            "item_id": item_id,
            "transactions_added": transactions_added,
            "balances_updated": balances_updated,
            "status": status,
            "error_msg": error_msg,
        })

    return results


def start_scheduler():
    """Start APScheduler with a daily sync job at 03:00."""
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    import asyncio

    scheduler = AsyncIOScheduler()

    def _run_sync():
        loop = asyncio.get_event_loop()
        loop.create_task(sync_all_items())

    scheduler.add_job(_run_sync, "cron", hour=3, minute=0, id="plaid_daily_sync")
    scheduler.start()
    logger.info("Plaid daily sync scheduler started (runs at 03:00)")
    return scheduler
