"""
Route-level contract for DELETE /api/audit and DELETE /api/plaid/sync/log:

* Both endpoints require the owner role. A non-owner (or anonymous user)
  must not be able to wipe logs.
* The owner receives a ``{deleted, cleared_by}`` payload.
* A final breadcrumb is written to ``audit_log`` so "who cleared the
  log and when" is always answerable.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException


@pytest.mark.asyncio
async def test_audit_clear_owner_only_forbidden():
    from web.audit import routes as audit_routes

    request = MagicMock()
    request.state.user = {"id": 2, "username": "alice", "is_owner": False}

    with pytest.raises(HTTPException) as exc:
        await audit_routes.clear_audit_log(request, category=None, before_id=None)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_audit_clear_anonymous_unauthorized():
    from web.audit import routes as audit_routes

    request = MagicMock()
    request.state.user = None

    with pytest.raises(HTTPException) as exc:
        await audit_routes.clear_audit_log(request, category=None, before_id=None)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_audit_clear_owner_success_writes_breadcrumb():
    from web.audit import routes as audit_routes

    fake_repo = MagicMock()
    fake_repo.delete = AsyncMock(return_value=17)

    recorded: dict = {}

    async def fake_record(event_type, **kwargs):
        recorded["event_type"] = event_type
        recorded.update(kwargs)
        return 99

    request = MagicMock()
    request.state.user = {"id": 1, "username": "denis", "is_owner": True}

    with patch.object(audit_routes, "get_audit_repo", return_value=fake_repo), patch.object(
        audit_routes, "audit_record", fake_record
    ):
        result = await audit_routes.clear_audit_log(
            request, category="plaid", before_id=None
        )

    assert result == {"deleted": 17, "cleared_by": "denis"}
    fake_repo.delete.assert_awaited_once_with(event_prefix="plaid.", before_id=None)
    assert recorded["event_type"] == "audit.log_cleared"
    assert recorded["source"] == "manual"
    assert recorded["metadata"]["rows_deleted"] == 17
    assert recorded["metadata"]["category"] == "plaid"


@pytest.mark.asyncio
async def test_plaid_sync_log_clear_owner_only_forbidden():
    from web.plaid import routes as plaid_routes

    request = MagicMock()
    request.state.user = {"id": 4, "username": "bob", "is_owner": False}

    with pytest.raises(HTTPException) as exc:
        await plaid_routes.clear_sync_log(request)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_plaid_sync_log_clear_owner_success_writes_breadcrumb():
    from web.plaid import routes as plaid_routes

    fake_repo = MagicMock()
    fake_repo.clear_sync_log = AsyncMock(return_value=50)

    recorded: dict = {}

    async def fake_record(event_type, **kwargs):
        recorded["event_type"] = event_type
        recorded.update(kwargs)
        return 1

    request = MagicMock()
    request.state.user = {"id": 1, "username": "denis", "is_owner": True}

    with patch.object(plaid_routes, "get_plaid_repo", return_value=fake_repo), patch.object(
        plaid_routes, "audit_record", fake_record
    ):
        result = await plaid_routes.clear_sync_log(request)

    assert result == {"deleted": 50, "cleared_by": "denis"}
    fake_repo.clear_sync_log.assert_awaited_once()
    assert recorded["event_type"] == "plaid.sync_log_cleared"
    assert recorded["metadata"]["rows_deleted"] == 50
