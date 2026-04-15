"""
APScheduler job: sync all Plaid items daily.
"""
import logging
from typing import List

logger = logging.getLogger(__name__)


async def sync_all_items() -> List[dict]:
    """
    Sync transactions, income and balances for every connected Plaid item.
    Called both by the scheduler and by the manual /api/plaid/sync endpoint.
    """
    from .repo import get_plaid_repo
    from .client import get_transactions_sync, get_account_balances, get_liabilities

    repo = get_plaid_repo()
    items = await repo.get_all_items_with_tokens()
    results = []

    for item in items:
        item_id = item["item_id"]
        access_token = item["access_token"]
        cursor = item.get("cursor")

        transactions_added = 0
        income_added = 0
        balances_updated = 0
        status = "ok"
        error_msg = None

        try:
            # --- Transactions sync ---
            category_map = await repo.get_category_map()
            txn_data = get_transactions_sync(access_token, cursor)
            added_txns = txn_data["added"]
            modified_txns = txn_data["modified"]
            removed_txns = txn_data["removed"]

            # Import new transactions
            transactions_added = await repo.import_transactions(added_txns, category_map)
            income_added = await repo.import_income(added_txns)

            # Update modified transactions (ON CONFLICT DO UPDATE handles field refresh)
            if modified_txns:
                transactions_added += await repo.import_transactions(modified_txns, category_map)
                income_added += await repo.import_income(modified_txns)

            # Delete transactions removed by Plaid
            if removed_txns:
                await repo.remove_transactions(removed_txns)

            await repo.update_cursor(item_id, txn_data["next_cursor"])

            # --- Balance sync ---
            accounts = get_account_balances(access_token)
            # Auto-create finance_credit_cards / finance_loans for new Plaid accounts
            await repo.provision_finance_accounts(accounts)
            balances_updated = await repo.sync_balances(accounts)

            # --- Liabilities sync (APR, min payment, due date) ---
            liabilities = get_liabilities(access_token)
            await repo.sync_liabilities(liabilities)

            logger.info(
                "Plaid sync OK: item=%s txn_added=%d income_added=%d balances_updated=%d "
                "modified=%d removed=%d",
                item_id, transactions_added, income_added, balances_updated,
                len(modified_txns), len(removed_txns),
            )
        except Exception as e:
            status = "error"
            error_msg = str(e)
            logger.error("Plaid sync failed for item %s: %s", item_id, e)

        await repo.log_sync(item_id, transactions_added, balances_updated, status, error_msg, income_added)
        results.append({
            "item_id": item_id,
            "transactions_added": transactions_added,
            "income_added": income_added,
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
