"""Sync marks plaid_items.item_login_required when Plaid demands re-auth."""

import json
from unittest.mock import AsyncMock, patch

import pytest
from plaid.exceptions import ApiException

from web.plaid import scheduler as scheduler_module


@pytest.mark.asyncio
async def test_sync_item_payload_sets_login_required_on_item_login_error() -> None:
    item = {
        "item_id": "itm_test_login",
        "access_token": "access-sandbox-xxx",
        "cursor": None,
        "user_id": 1,
    }
    exc = ApiException(status=400, reason="Bad Request")
    exc.body = json.dumps(
        {
            "error_type": "ITEM_ERROR",
            "error_code": "ITEM_LOGIN_REQUIRED",
            "error_message": "user login required",
        }
    )

    mock_repo = MagicAsyncRepo()

    async def boom(*_a, **_k):
        raise exc

    with patch("web.plaid.repo.get_plaid_repo", return_value=mock_repo), patch(
        "web.plaid.scheduler.asyncio.to_thread", side_effect=boom
    ):
        result = await scheduler_module._sync_item_payload(
            item, "plaid", audit_source="manual"
        )

    assert result["status"] == "error"
    mock_repo.set_item_login_required.assert_awaited_once_with("itm_test_login", True)
    mock_repo.log_sync.assert_awaited()


class MagicAsyncRepo:
    """Minimal repo stub for _sync_item_payload error path."""

    def __init__(self) -> None:
        self.set_item_login_required = AsyncMock()
        self.log_sync = AsyncMock()
