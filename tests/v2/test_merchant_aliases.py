"""Tests for the merchant alias feature.

Covers:

* ``alias_join_sql`` produces the same key-precedence as ``merchant_key()``.
* ``upsert_alias`` writes both ``eid:`` and ``name:`` rows when both
  identifiers are available, single row otherwise.
* ``delete_alias`` removes both twin keys when the trio is supplied.
* ``transactions.list_transactions`` surfaces the alias as ``merchant_alias``
  and overrides ``display_title`` in-place.
* ``recurring.list_streams`` joins by the ``name:`` key (recurring rows
  have no ``merchant_entity_id``).
* The reports top-merchants query groups by the aliased name.
"""
from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

from tests.v2.conftest import make_mock_pool
from web.merchant_rules.aliases import (
    MerchantAliasesRepository,
    alias_join_sql,
)


class TestAliasJoinSql:
    def test_clause_has_three_branches(self):
        sql = alias_join_sql("t", "ma")
        # eid:..., name:<merchant_name>, name:<display_title> fallback
        assert "eid:" in sql
        assert "name:" in sql
        assert "merchant_entity_id" in sql
        assert "merchant_name" in sql
        assert "display_title" in sql
        # Joined alias name is what we asked for
        assert "merchant_aliases ma" in sql
        assert "ma.merchant_key" in sql

    def test_table_alias_is_respected(self):
        sql = alias_join_sql("rs", "x")
        assert "rs.merchant_entity_id" in sql
        assert "rs.merchant_name" in sql
        assert "merchant_aliases x" in sql


class TestUpsertAlias:
    @pytest.mark.asyncio
    async def test_writes_two_rows_when_eid_and_name_present(self):
        conn = AsyncMock()
        pool = make_mock_pool(conn)
        # Both INSERTs return a fake row; the primary (eid) is the one
        # exposed in the response.
        async def fake_fetchrow(_sql, key, _name):
            return {
                "merchant_key": key,
                "display_name": "Rent",
                "created_at": None,
                "updated_at": None,
            }

        conn.fetchrow.side_effect = fake_fetchrow
        # asyncpg connection has a transaction() context manager — mock it.
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=None)
        ctx.__aexit__ = AsyncMock(return_value=False)
        conn.transaction = lambda: ctx

        with patch(
            "web.merchant_rules.aliases.get_pool", AsyncMock(return_value=pool)
        ):
            row = await MerchantAliasesRepository().upsert_alias(
                merchant_entity_id="ABC123",
                merchant_name="Nyflower",
                fallback_display=None,
                display_name="Rent",
            )

        # Two INSERTs (eid: + name:)
        assert conn.fetchrow.await_count == 2
        keys_inserted = sorted(call.args[1] for call in conn.fetchrow.await_args_list)
        assert keys_inserted == ["eid:abc123", "name:nyflower"]
        # Returned row reflects the *primary* (eid) key
        assert row["merchant_key"] == "eid:abc123"
        assert row["display_name"] == "Rent"

    @pytest.mark.asyncio
    async def test_writes_single_row_when_only_name_present(self):
        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.fetchrow.return_value = {
            "merchant_key": "name:nyflower",
            "display_name": "Rent",
            "created_at": None,
            "updated_at": None,
        }
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=None)
        ctx.__aexit__ = AsyncMock(return_value=False)
        conn.transaction = lambda: ctx

        with patch(
            "web.merchant_rules.aliases.get_pool", AsyncMock(return_value=pool)
        ):
            row = await MerchantAliasesRepository().upsert_alias(
                merchant_entity_id=None,
                merchant_name="Nyflower",
                fallback_display=None,
                display_name="Rent",
            )

        assert conn.fetchrow.await_count == 1
        assert row["merchant_key"] == "name:nyflower"

    @pytest.mark.asyncio
    async def test_rejects_empty_display_name(self):
        repo = MerchantAliasesRepository()
        with pytest.raises(ValueError, match="display_name"):
            await repo.upsert_alias(
                merchant_entity_id="X",
                merchant_name=None,
                fallback_display=None,
                display_name="   ",
            )

    @pytest.mark.asyncio
    async def test_rejects_when_no_identifier(self):
        repo = MerchantAliasesRepository()
        with pytest.raises(ValueError, match="merchant_entity_id"):
            await repo.upsert_alias(
                merchant_entity_id=None,
                merchant_name=None,
                fallback_display=None,
                display_name="Rent",
            )


class TestUpsertModelValidator:
    """The Pydantic-side ``MerchantAliasUpsert`` validator must accept any
    one of the three identifier fields. Earlier versions had a generator
    bug that always evaluated ``merchant_entity_id`` and rejected
    ``{merchant_entity_id: null, merchant_name: "Nyflower"}`` as 422
    "Provide ...". This regression test pins the behaviour."""

    def test_accepts_merchant_name_only(self):
        from web.merchant_rules.aliases_routes import MerchantAliasUpsert

        m = MerchantAliasUpsert(
            display_name="Rent",
            merchant_entity_id=None,
            merchant_name="Nyflower",
            merchant_label=None,
        )
        assert m.merchant_name == "Nyflower"

    def test_accepts_merchant_entity_id_only(self):
        from web.merchant_rules.aliases_routes import MerchantAliasUpsert

        m = MerchantAliasUpsert(
            display_name="Rent",
            merchant_entity_id="abc123",
            merchant_name=None,
            merchant_label=None,
        )
        assert m.merchant_entity_id == "abc123"

    def test_accepts_merchant_label_only(self):
        from web.merchant_rules.aliases_routes import MerchantAliasUpsert

        m = MerchantAliasUpsert(
            display_name="Rent",
            merchant_entity_id=None,
            merchant_name=None,
            merchant_label="Pmts Sec: Ind",
        )
        assert m.merchant_label == "Pmts Sec: Ind"

    def test_rejects_all_blank(self):
        import pydantic

        from web.merchant_rules.aliases_routes import MerchantAliasUpsert

        with pytest.raises(pydantic.ValidationError):
            MerchantAliasUpsert(
                display_name="Rent",
                merchant_entity_id=None,
                merchant_name=None,
                merchant_label=None,
            )

    def test_rejects_all_whitespace(self):
        import pydantic

        from web.merchant_rules.aliases_routes import MerchantAliasUpsert

        with pytest.raises(pydantic.ValidationError):
            MerchantAliasUpsert(
                display_name="Rent",
                merchant_entity_id="   ",
                merchant_name="",
                merchant_label="\t",
            )


class TestDeleteAlias:
    @pytest.mark.asyncio
    async def test_deletes_both_keys_when_trio_supplied(self):
        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.execute.return_value = "DELETE 1"
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=None)
        ctx.__aexit__ = AsyncMock(return_value=False)
        conn.transaction = lambda: ctx

        with patch(
            "web.merchant_rules.aliases.get_pool", AsyncMock(return_value=pool)
        ):
            ok = await MerchantAliasesRepository().delete_alias(
                merchant_entity_id="ABC123",
                merchant_name="Nyflower",
            )

        assert ok is True
        assert conn.execute.await_count == 2  # eid: + name:
        keys_deleted = sorted(c.args[1] for c in conn.execute.await_args_list)
        assert keys_deleted == ["eid:abc123", "name:nyflower"]

    @pytest.mark.asyncio
    async def test_deletes_single_key_by_merchant_key(self):
        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.execute.return_value = "DELETE 1"
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=None)
        ctx.__aexit__ = AsyncMock(return_value=False)
        conn.transaction = lambda: ctx

        with patch(
            "web.merchant_rules.aliases.get_pool", AsyncMock(return_value=pool)
        ):
            ok = await MerchantAliasesRepository().delete_alias(
                merchant_key="eid:abc123",
            )

        assert ok is True
        assert conn.execute.await_count == 1


class TestAliasInTransactions:
    """Verify ``list_transactions`` adds the JOIN, returns ``merchant_alias``,
    and overrides ``display_title`` for aliased rows.
    """

    @pytest.mark.asyncio
    async def test_alias_overrides_display_title_in_list(self):
        from web.transactions.repo import TransactionsRepository

        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.fetch.return_value = [
            {
                "id": 1,
                "display_title": "Nyflower",
                "merchant_alias": "Rent",
                "merchant_name": "Nyflower",
            },
            {
                "id": 2,
                "display_title": "Starbucks",
                "merchant_alias": None,
                "merchant_name": "Starbucks",
            },
        ]

        with patch("web.transactions.repo.get_pool", AsyncMock(return_value=pool)):
            rows = await TransactionsRepository().list_transactions(month="2026-04")

        # Aliased row's display_title flipped to the alias.
        assert rows[0]["display_title"] == "Rent"
        assert rows[0]["merchant_alias"] == "Rent"
        # Non-aliased row untouched.
        assert rows[1]["display_title"] == "Starbucks"
        assert rows[1]["merchant_alias"] is None

        # The query SQL contains the alias JOIN.
        sql = conn.fetch.call_args.args[0]
        assert "merchant_aliases ma" in sql

    @pytest.mark.asyncio
    async def test_alias_overrides_display_title_in_get(self):
        from web.transactions.repo import TransactionsRepository

        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.fetchrow.return_value = {
            "id": 5,
            "display_title": "Nyflower",
            "merchant_alias": "Rent",
            "is_private": False,
            "account_user_id": None,
        }

        with patch("web.transactions.repo.get_pool", AsyncMock(return_value=pool)):
            row = await TransactionsRepository().get_transaction(5)

        assert row is not None
        assert row["display_title"] == "Rent"


class TestAliasInRecurring:
    """Recurring streams have no merchant_entity_id; the alias must JOIN by
    the ``name:<lower(merchant_name)>`` key path.
    """

    @pytest.mark.asyncio
    async def test_recurring_query_joins_by_name_key(self):
        from web.recurring.repo import RecurringRepository

        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.fetch.return_value = [
            {
                "id": 1,
                "plaid_stream_id": "p1",
                "account_id": 1,
                "direction": "outflow",
                "description": "NYFLOWER ACH",
                "merchant_name": "Nyflower",
                "merchant_alias": "Rent",
                "frequency": "MONTHLY",
                "last_date": date(2026, 4, 1),
                "is_active": True,
                "status": "MATURE",
                "category_id": None,
                "user_label": None,
                "category_parent_id": None,
                "primary_category_id": None,
                "primary_category_name": None,
                "primary_category_color": None,
                "pfc_primary": None,
                "pfc_detailed": None,
                "stream_source": "plaid",
                "average_amount_cents": 100000,
                "last_amount_cents": 100000,
                "currency": "USD",
                "first_date": None,
                "price_change_pct": None,
                "last_synced_at": None,
                "account_name": "Chase",
                "account_mask": "1111",
                "owner_username": "denis",
            }
        ]

        with patch("web.recurring.repo.get_pool", AsyncMock(return_value=pool)):
            rows = await RecurringRepository().list_streams()

        sql = conn.fetch.call_args.args[0]
        # JOIN by the name: key (recurring has no merchant_entity_id).
        assert "merchant_aliases ma" in sql
        assert "'name:' || lower" in sql

        assert rows[0]["merchant_alias"] == "Rent"
        # Title normalizer treated the alias as the canonical merchant name.
        assert rows[0]["display_title"] == "Rent"


class TestAliasInTopMerchants:
    """The reports top-merchants query must group by the aliased label so
    multiple Plaid merchants renamed to the same string aggregate as one.
    """

    @pytest.mark.asyncio
    async def test_top_merchants_groups_by_aliased_name(self):
        from web.reports.repo import ReportsRepository

        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.fetch.return_value = []

        with patch("web.reports.repo.get_pool", AsyncMock(return_value=pool)):
            await ReportsRepository().get_top_merchants()

        sql = conn.fetch.call_args.args[0]
        assert "merchant_aliases ma" in sql
        assert "GROUP BY COALESCE(ma.display_name, t.merchant_name)" in sql
        assert "is_aliased" in sql
