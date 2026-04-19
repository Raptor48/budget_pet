"""
Manual override for credit_limit / APR on accounts where Plaid does not
return those values (Capital One Quicksilver is the canonical example).

Contract:
* PATCH accepts ``credit_limit_cents_manual`` and ``apr_percent_manual``.
* Override is accepted only when the corresponding Plaid-sourced field
  is NULL. A bank that already reports the value locks manual entry
  (HTTP 409) to keep Plaid as the source of truth.
* Clearing the override (sending ``null``) is always allowed regardless
  of whether Plaid reports the value — the user has to be able to walk
  their manual number back.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from web.accounts.models import AccountUpdate


@pytest.mark.asyncio
async def test_manual_override_allowed_when_plaid_value_missing():
    from web.accounts import routes as acct_routes

    fake_repo = MagicMock()
    fake_repo.get_account = AsyncMock(
        return_value={
            "id": 25,
            "type": "credit",
            "credit_limit_cents": None,
            "apr_percent": None,
            "plaid_account_id": "plaid-123",
            "user_id": 1,
            "name": "Quicksilver",
            "subtype": "credit card",
            "is_active": True,
        }
    )
    fake_repo.update_account = AsyncMock(
        return_value={
            "id": 25,
            "credit_limit_cents_manual": 500000,
            "apr_percent_manual": "19.990",
        }
    )

    body = AccountUpdate(credit_limit_cents_manual=500000, apr_percent_manual="19.990")
    request = MagicMock()
    request.state.user = {"id": 1, "is_owner": True}

    with patch.object(acct_routes, "_repo", return_value=fake_repo):
        result = await acct_routes.update_account(25, body, request)

    assert result["id"] == 25
    fake_repo.update_account.assert_awaited_once()
    payload = fake_repo.update_account.await_args.args[1]
    assert payload["credit_limit_cents_manual"] == 500000
    # Decimal or string — both acceptable; assert key is present and not None.
    assert payload["apr_percent_manual"] is not None


@pytest.mark.asyncio
async def test_manual_override_rejected_when_plaid_reports_value():
    from web.accounts import routes as acct_routes

    fake_repo = MagicMock()
    fake_repo.get_account = AsyncMock(
        return_value={
            "id": 26,
            "type": "credit",
            "credit_limit_cents": 1000000,   # Plaid reports it
            "apr_percent": None,
            "plaid_account_id": "plaid-456",
            "user_id": 1,
            "name": "Chase Freedom",
            "subtype": "credit card",
            "is_active": True,
        }
    )
    fake_repo.update_account = AsyncMock()

    body = AccountUpdate(credit_limit_cents_manual=900000)
    request = MagicMock()
    request.state.user = {"id": 1, "is_owner": True}

    with patch.object(acct_routes, "_repo", return_value=fake_repo):
        with pytest.raises(HTTPException) as exc:
            await acct_routes.update_account(26, body, request)
    assert exc.value.status_code == 409
    assert "bank" in exc.value.detail.lower()
    fake_repo.update_account.assert_not_awaited()


@pytest.mark.asyncio
async def test_apr_override_rejected_when_plaid_reports_apr():
    from web.accounts import routes as acct_routes

    fake_repo = MagicMock()
    fake_repo.get_account = AsyncMock(
        return_value={
            "id": 27,
            "type": "credit",
            "credit_limit_cents": None,
            "apr_percent": "15.990",
            "plaid_account_id": "plaid-789",
            "user_id": 1,
            "name": "Chase Sapphire",
            "subtype": "credit card",
            "is_active": True,
        }
    )
    fake_repo.update_account = AsyncMock()

    body = AccountUpdate(apr_percent_manual="20.000")
    request = MagicMock()
    request.state.user = {"id": 1, "is_owner": True}

    with patch.object(acct_routes, "_repo", return_value=fake_repo):
        with pytest.raises(HTTPException) as exc:
            await acct_routes.update_account(27, body, request)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_clearing_manual_override_is_always_allowed():
    """Sending ``null`` always works — even if Plaid is reporting now."""
    from web.accounts import routes as acct_routes

    fake_repo = MagicMock()
    fake_repo.get_account = AsyncMock(
        return_value={
            "id": 28,
            "type": "credit",
            "credit_limit_cents": 800000,   # Plaid now reports
            "apr_percent": "12.000",
            "plaid_account_id": "plaid-aaa",
            "user_id": 1,
            "name": "Amex",
            "subtype": "credit card",
            "is_active": True,
        }
    )
    fake_repo.update_account = AsyncMock(return_value={"id": 28})

    body = AccountUpdate(
        credit_limit_cents_manual=None,
        apr_percent_manual=None,
    )
    request = MagicMock()
    request.state.user = {"id": 1, "is_owner": True}

    with patch.object(acct_routes, "_repo", return_value=fake_repo):
        result = await acct_routes.update_account(28, body, request)

    assert result["id"] == 28
    payload = fake_repo.update_account.await_args.args[1]
    assert payload["credit_limit_cents_manual"] is None
    assert payload["apr_percent_manual"] is None


@pytest.mark.asyncio
async def test_non_owner_non_account_owner_cannot_override():
    from web.accounts import routes as acct_routes

    fake_repo = MagicMock()
    fake_repo.get_account = AsyncMock(
        return_value={
            "id": 30,
            "type": "credit",
            "credit_limit_cents": None,
            "apr_percent": None,
            "plaid_account_id": "plaid-zzz",
            "user_id": 7,  # some other family member
            "name": "Someone else's card",
            "subtype": "credit card",
            "is_active": True,
        }
    )
    fake_repo.update_account = AsyncMock()

    body = AccountUpdate(credit_limit_cents_manual=100000)
    request = MagicMock()
    request.state.user = {"id": 42, "is_owner": False}

    with patch.object(acct_routes, "_repo", return_value=fake_repo):
        with pytest.raises(HTTPException) as exc:
            await acct_routes.update_account(30, body, request)
    assert exc.value.status_code == 403
    fake_repo.update_account.assert_not_awaited()
