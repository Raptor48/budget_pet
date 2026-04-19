"""
Detects which Plaid credit/loan fields are missing on a per-account basis
and records an audit entry *only* when the set of missing fields changes
for that account. Idempotent by design — a sync that sees the same gaps
as the previous one writes nothing.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.v2.conftest import make_mock_pool
from web.accounts.missing_fields import (
    compute_missing_fields,
    detect_and_record_missing,
)


class TestComputeMissingFields:
    def test_credit_card_both_missing(self):
        row = {
            "id": 1,
            "type": "credit",
            "credit_limit_cents": None,
            "apr_percent": None,
        }
        assert compute_missing_fields(row) == ["apr", "credit_limit"]

    def test_credit_card_only_limit_missing(self):
        row = {
            "id": 1,
            "type": "credit",
            "credit_limit_cents": None,
            "apr_percent": "19.990",
        }
        assert compute_missing_fields(row) == ["credit_limit"]

    def test_credit_card_complete(self):
        row = {
            "id": 1,
            "type": "credit",
            "credit_limit_cents": 500000,
            "apr_percent": "19.990",
        }
        assert compute_missing_fields(row) == []

    def test_loan_tracks_apr_not_credit_limit(self):
        row = {
            "id": 1,
            "type": "loan",
            "credit_limit_cents": None,
            "apr_percent": None,
        }
        assert compute_missing_fields(row) == ["apr"]

    def test_depository_tracks_nothing(self):
        row = {
            "id": 1,
            "type": "depository",
            "credit_limit_cents": None,
            "apr_percent": None,
        }
        assert compute_missing_fields(row) == []


class TestDetectAndRecord:
    @pytest.mark.asyncio
    async def test_writes_audit_and_updates_cache_on_first_detection(self):
        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.fetch = AsyncMock(
            return_value=[
                {
                    "id": 25,
                    "name": "Quicksilver",
                    "type": "credit",
                    "credit_limit_cents": None,
                    "apr_percent": None,
                    "plaid_missing_fields": None,
                    "institution_name": "Capital One",
                }
            ]
        )
        conn.execute = AsyncMock(return_value="UPDATE 1")
        audit = AsyncMock(return_value=99)

        with patch("web.db.get_pool", AsyncMock(return_value=pool)), patch(
            "web.accounts.missing_fields.audit_record", audit
        ):
            n = await detect_and_record_missing(
                item_id="item-1", source="scheduler"
            )

        assert n == 1
        audit.assert_awaited_once()
        ev_kwargs = audit.await_args.kwargs
        assert ev_kwargs["event_type"] == "plaid.liabilities.missing_field"
        assert ev_kwargs["source"] == "scheduler"
        assert ev_kwargs["target_kind"] == "account"
        assert ev_kwargs["target_id"] == "25"
        md = ev_kwargs["metadata"]
        assert md["missing_now"] == ["apr", "credit_limit"]
        assert md["missing_prev"] == []
        assert md["institution_name"] == "Capital One"

        conn.execute.assert_awaited_once()
        sql = conn.execute.await_args.args[0]
        assert "UPDATE accounts" in sql
        assert "plaid_missing_fields" in sql

    @pytest.mark.asyncio
    async def test_noop_when_set_unchanged(self):
        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.fetch = AsyncMock(
            return_value=[
                {
                    "id": 25,
                    "name": "Quicksilver",
                    "type": "credit",
                    "credit_limit_cents": None,
                    "apr_percent": None,
                    "plaid_missing_fields": ["apr", "credit_limit"],
                    "institution_name": "Capital One",
                }
            ]
        )
        conn.execute = AsyncMock(return_value="UPDATE 1")
        audit = AsyncMock(return_value=1)

        with patch("web.db.get_pool", AsyncMock(return_value=pool)), patch(
            "web.accounts.missing_fields.audit_record", audit
        ):
            n = await detect_and_record_missing(
                item_id="item-1", source="scheduler"
            )

        assert n == 0
        audit.assert_not_awaited()
        conn.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_writes_audit_when_plaid_starts_reporting(self):
        """Going from missing → complete is a transition too — we log it."""
        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.fetch = AsyncMock(
            return_value=[
                {
                    "id": 25,
                    "name": "Quicksilver",
                    "type": "credit",
                    "credit_limit_cents": 500000,
                    "apr_percent": "19.990",
                    "plaid_missing_fields": ["apr", "credit_limit"],
                    "institution_name": "Capital One",
                }
            ]
        )
        conn.execute = AsyncMock(return_value="UPDATE 1")
        audit = AsyncMock(return_value=2)

        with patch("web.db.get_pool", AsyncMock(return_value=pool)), patch(
            "web.accounts.missing_fields.audit_record", audit
        ):
            n = await detect_and_record_missing(
                item_id="item-1", source="webhook"
            )

        assert n == 1
        audit.assert_awaited_once()
        md = audit.await_args.kwargs["metadata"]
        assert md["missing_now"] == []
        assert md["missing_prev"] == ["apr", "credit_limit"]

    @pytest.mark.asyncio
    async def test_skips_depository_accounts(self):
        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.fetch = AsyncMock(
            return_value=[
                {
                    "id": 1,
                    "name": "Checking",
                    "type": "depository",
                    "credit_limit_cents": None,
                    "apr_percent": None,
                    "plaid_missing_fields": None,
                    "institution_name": "Chase",
                }
            ]
        )
        conn.execute = AsyncMock(return_value="UPDATE 0")
        audit = AsyncMock(return_value=None)

        with patch("web.db.get_pool", AsyncMock(return_value=pool)), patch(
            "web.accounts.missing_fields.audit_record", audit
        ):
            n = await detect_and_record_missing(
                item_id="item-1", source="scheduler"
            )

        assert n == 0
        audit.assert_not_awaited()
