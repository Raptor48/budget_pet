"""Tests for Plaid sync — mocking all Plaid API calls."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.v2.conftest import make_mock_pool
from web.plaid.repo import PlaidRepository


def _make_txn(
    txn_id: str,
    account_id: str,
    amount: float = 12.50,
    pending_transaction_id: str | None = None,
    pending: bool = False,
):
    txn = MagicMock()
    txn.to_dict.return_value = {
        "transaction_id": txn_id,
        "account_id": account_id,
        "amount": amount,
        "iso_currency_code": "USD",
        "date": "2026-04-15",
        "authorized_date": "2026-04-14",
        "datetime": None,
        "authorized_datetime": None,
        "name": "Test Merchant",
        "merchant_name": "Test",
        "merchant_entity_id": None,
        "logo_url": None,
        "website": None,
        "payment_channel": "online",
        "personal_finance_category": {
            "primary": "FOOD_AND_DRINK",
            "detailed": "FOOD_AND_DRINK_COFFEE",
            "confidence_level": "HIGH",
        },
        "personal_finance_category_icon_url": None,
        "counterparties": [],
        "location": None,
        "payment_meta": None,
        "pending": pending,
        "pending_transaction_id": pending_transaction_id,
    }
    return txn


class TestPlaidRepository:
    @pytest.fixture
    def repo(self):
        return PlaidRepository()

    def test_extract_txn_maps_personal_finance_category(self, repo):
        """PFC fields must match Plaid's personal_finance_category object (unchanged contract)."""
        raw = {
            "transaction_id": "t-pfc",
            "account_id": "acct-x",
            "amount": 10.0,
            "iso_currency_code": "USD",
            "date": "2026-04-15",
            "authorized_date": None,
            "datetime": None,
            "authorized_datetime": None,
            "name": "Airline",
            "merchant_name": "Air",
            "merchant_entity_id": None,
            "logo_url": None,
            "website": None,
            "payment_channel": "online",
            "personal_finance_category": {
                "primary": "TRAVEL",
                "detailed": "TRAVEL_FLIGHTS",
                "confidence_level": "VERY_HIGH",
            },
            "personal_finance_category_icon_url": "https://cdn.plaid.com/pfc/travel.png",
            "counterparties": [],
            "location": None,
            "payment_meta": None,
            "pending": False,
            "pending_transaction_id": "pending-123",
        }
        row = repo._extract_txn(raw, account_id=42, source="plaid")
        assert row["pfc_primary"] == "TRAVEL"
        assert row["pfc_detailed"] == "TRAVEL_FLIGHTS"
        assert row["pfc_confidence"] == "VERY_HIGH"
        assert row["pfc_icon_url"] == "https://cdn.plaid.com/pfc/travel.png"
        assert row["pending_transaction_id"] == "pending-123"

    @pytest.mark.asyncio
    async def test_import_transactions_counts_correctly(self, repo):
        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.execute = AsyncMock()

        txns = [_make_txn("txn-1", "acct-1"), _make_txn("txn-2", "acct-1", 5.0)]
        account_id_map = {"acct-1": 1}

        with patch("web.plaid.repo.get_pool", AsyncMock(return_value=pool)), patch(
            "web.merchant_rules.repo.MerchantRulesRepository.lookup_category",
            new_callable=AsyncMock,
            return_value=None,
        ):
            count = await repo.import_transactions(txns, account_id_map, source="plaid")

        assert count == 2

    @pytest.mark.asyncio
    async def test_import_skips_unknown_account(self, repo):
        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.execute = AsyncMock()

        txns = [_make_txn("txn-unknown", "unknown-acct")]
        account_id_map = {}

        with patch("web.plaid.repo.get_pool", AsyncMock(return_value=pool)):
            count = await repo.import_transactions(txns, account_id_map, source="plaid")

        assert count == 0
        conn.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_pending_to_posted_preserves_user_flags(self, repo):
        """
        When Plaid posts a previously-pending transaction it issues a brand new
        ``transaction_id`` and marks the pending row ``removed``. The import
        loop must look up the pending twin via ``pending_transaction_id`` and
        forward user-set flags (is_private, user_note) into the newly inserted
        posted row. Otherwise, anything a family member privately tagged while
        the transaction was pending would leak to the rest of the family after
        autosync.
        """
        conn = AsyncMock()
        pool = make_mock_pool(conn)

        executed_args: list[tuple] = []

        async def fake_execute(sql, *args):
            executed_args.append(args)
            return "INSERT 0 1"

        async def fake_fetchrow(sql, *args):
            if "FROM transactions" not in sql or "plaid_transaction_id = $1" not in sql:
                return None
            # Single unified pending-twin lookup since 2026-04-27: one
            # SELECT pulls every field that needs carrying so we don't
            # round-trip twice for the same row.
            return {
                "is_private": True,
                "user_note": "honeymoon surprise",
                "category_id": 77,
                "manual_class_override": None,
                "is_internal_transfer": False,
                "is_internal_transfer_manual": False,
            }

        conn.execute = AsyncMock(side_effect=fake_execute)
        conn.fetchrow = AsyncMock(side_effect=fake_fetchrow)

        posted = _make_txn(
            "txn-posted-1",
            "acct-1",
            pending_transaction_id="txn-pending-1",
        )
        account_id_map = {"acct-1": 1}

        with patch("web.plaid.repo.get_pool", AsyncMock(return_value=pool)), patch(
            "web.merchant_rules.repo.MerchantRulesRepository.lookup_category",
            new_callable=AsyncMock,
            return_value=None,
        ):
            count = await repo.import_transactions(
                [posted], account_id_map, source="plaid"
            )

        assert count == 1
        assert executed_args, "expected an INSERT"
        args = executed_args[0]
        # Column order ends with:
        #   ... pending_transaction_id, is_private, user_note,
        #       is_internal_transfer, is_internal_transfer_manual,
        #       manual_class_override
        assert args[-6] == "txn-pending-1"
        assert args[-5] is True, "is_private must be carried from the pending twin"
        assert args[-4] == "honeymoon surprise", "user_note must be carried forward"
        assert args[-3] is False, "internal-transfer flag stays False when twin wasn't flagged"
        assert args[-2] is False, "manual-override sentinel stays False"
        assert args[-1] is None, "no manual class override on the pending twin"
        # Category from pending twin should win when no merchant rule applied.
        assert args[2] == 77

    @pytest.mark.asyncio
    async def test_pending_to_posted_carries_manual_class_override(self, repo):
        """Regression for the 2026-04-27 audit: a user who pinned a pending
        row's class to ``expense`` (e.g. a refund the rule-5.5 default of
        ``income`` mis-tagged) must keep that pin when the row goes posted.
        Previously only ``is_internal_transfer_manual`` was carried, so
        expense / income pins silently reverted on the next sync."""
        conn = AsyncMock()
        pool = make_mock_pool(conn)
        executed_args: list[tuple] = []

        async def fake_execute(sql, *args):
            executed_args.append(args)
            return "INSERT 0 1"

        async def fake_fetchrow(sql, *args):
            if "FROM transactions" not in sql:
                return None
            return {
                "is_private": False,
                "user_note": None,
                "category_id": None,
                "manual_class_override": "expense",
                "is_internal_transfer": False,
                "is_internal_transfer_manual": False,
            }

        conn.execute = AsyncMock(side_effect=fake_execute)
        conn.fetchrow = AsyncMock(side_effect=fake_fetchrow)

        posted = _make_txn(
            "txn-posted-refund",
            "acct-1",
            pending_transaction_id="txn-pending-refund",
        )
        with patch("web.plaid.repo.get_pool", AsyncMock(return_value=pool)), patch(
            "web.merchant_rules.repo.MerchantRulesRepository.lookup_category",
            new_callable=AsyncMock,
            return_value=None,
        ):
            await repo.import_transactions(
                [posted], {"acct-1": 1}, source="plaid"
            )

        args = executed_args[0]
        assert args[-1] == "expense", (
            "manual_class_override='expense' on the pending twin must "
            "land on the posted row's INSERT — otherwise the user's "
            "refund pin reverts to rule-5.5 income on next rescan"
        )

    @pytest.mark.asyncio
    async def test_posted_without_pending_twin_defaults_to_public(self, repo):
        """A brand-new posted transaction with no pending predecessor must
        insert with ``is_private=False`` — carrying over should be a no-op."""
        conn = AsyncMock()
        pool = make_mock_pool(conn)

        executed_args: list[tuple] = []

        async def fake_execute(sql, *args):
            executed_args.append(args)
            return "INSERT 0 1"

        conn.execute = AsyncMock(side_effect=fake_execute)
        conn.fetchrow = AsyncMock(return_value=None)

        fresh = _make_txn("txn-fresh", "acct-1")  # no pending_transaction_id
        with patch("web.plaid.repo.get_pool", AsyncMock(return_value=pool)), patch(
            "web.merchant_rules.repo.MerchantRulesRepository.lookup_category",
            new_callable=AsyncMock,
            return_value=None,
        ):
            await repo.import_transactions([fresh], {"acct-1": 1}, source="plaid")

        args = executed_args[0]
        # No pending_transaction_id, defaults for is_private/user_note/
        # is_internal_transfer/is_internal_transfer_manual/
        # manual_class_override.
        assert args[-6] is None
        assert args[-5] is False
        assert args[-4] is None
        assert args[-3] is False
        assert args[-2] is False
        assert args[-1] is None

    @pytest.mark.asyncio
    async def test_delete_removed_transactions(self, repo):
        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.execute.return_value = "DELETE 2"

        removed = [
            MagicMock(**{"to_dict.return_value": {"transaction_id": "txn-a"}}),
            MagicMock(**{"to_dict.return_value": {"transaction_id": "txn-b"}}),
        ]

        with patch("web.plaid.repo.get_pool", AsyncMock(return_value=pool)):
            count = await repo.delete_removed_transactions(removed)

        assert count == 2


class TestManualSyncAudit:
    @pytest.mark.asyncio
    async def test_manual_sync_writes_audit_row(self):
        """``POST /api/plaid/sync`` must leave one ``plaid.sync_manual`` audit
        entry with the per-run summary so the Log tab shows who triggered it."""
        from web.plaid import routes as plaid_routes

        recorded: list[dict] = []

        async def fake_record(event_type, *, source="manual", metadata=None, **_):
            recorded.append(
                {"event_type": event_type, "source": source, "metadata": metadata or {}}
            )

        fake_results = [
            {
                "item_id": "item-A",
                "transactions_added": 5,
                "balances_updated": 1,
                "status": "ok",
                "error_msg": None,
            },
            {
                "item_id": "item-B",
                "transactions_added": 0,
                "balances_updated": 0,
                "status": "error",
                "error_msg": "rate limited",
            },
        ]

        class FakeState:
            user = {"id": 3, "username": "denis"}

        class FakeRequest:
            state = FakeState()
            headers: dict[str, str] = {}
            client = None
            cookies: dict[str, str] = {}

        with patch(
            "web.plaid.scheduler.sync_all_items",
            AsyncMock(return_value=fake_results),
        ), patch.object(plaid_routes, "audit_record", fake_record):
            results = await plaid_routes.sync_now(FakeRequest())  # type: ignore[arg-type]

        assert results == fake_results
        assert len(recorded) == 1
        entry = recorded[0]
        assert entry["event_type"] == "plaid.sync_manual"
        assert entry["source"] == "manual"
        assert entry["metadata"]["items_synced"] == 2
        assert entry["metadata"]["transactions_added"] == 5
        assert entry["metadata"]["balances_updated"] == 1
        assert len(entry["metadata"]["errors"]) == 1
        assert entry["metadata"]["errors"][0]["item_id"] == "item-B"


class TestPlaidSyncScheduler:
    @pytest.mark.asyncio
    async def test_sync_all_items_handles_error_gracefully(self):
        """sync_all_items should catch errors and set status=error for failed items."""
        mock_repo = AsyncMock()
        mock_repo.get_items.return_value = [
            {"item_id": "item-1", "access_token": "token-1", "cursor": None},
        ]
        mock_repo.log_sync = AsyncMock()

        # All Plaid client functions are imported inside sync_all_items,
        # so patch at the source module level
        with patch("web.plaid.repo.get_plaid_repo", return_value=mock_repo), \
             patch("web.plaid.client.get_transactions_sync", side_effect=RuntimeError("API down")), \
             patch("web.plaid.client.get_account_balances", return_value=[]), \
             patch("web.plaid.client.get_liabilities", return_value={"credit": [], "student": [], "mortgage": [], "accounts": []}), \
             patch("web.plaid.client.get_recurring_transactions", return_value={"inflow_streams": [], "outflow_streams": []}), \
             patch("web.plaid.client.get_investment_holdings", return_value={"holdings": [], "securities": []}), \
             patch("web.accounts.repo.AccountsRepository.provision_from_plaid", AsyncMock(return_value=0)), \
             patch("web.categories.repo.CategoriesRepository.resolve_category", AsyncMock(return_value=1)), \
             patch("web.recurring.repo.RecurringRepository.upsert_streams", AsyncMock(return_value=0)), \
             patch("web.investments.repo.InvestmentsRepository.upsert_securities", AsyncMock(return_value=0)), \
             patch("web.reports.repo.ReportsRepository.snapshot_net_worth", AsyncMock(return_value={})):
            mock_repo.build_account_id_map = AsyncMock(return_value={})
            from web.plaid.scheduler import sync_all_items
            results = await sync_all_items()

        assert len(results) == 1
        assert results[0]["status"] == "error"
        assert results[0]["item_id"] == "item-1"
