"""NDJSON streaming manual Plaid sync."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_iter_sync_all_items_matches_sync_all_items():
    """Refactor guard: sync_all_items must aggregate the async iterator."""
    from web.plaid import scheduler as sched

    async def fake_iter(*, audit_source: str = "manual"):
        yield {"item_id": "a", "status": "ok", "transactions_added": 0, "balances_updated": 0, "error_msg": None}
        yield {"item_id": "b", "status": "ok", "transactions_added": 1, "balances_updated": 2, "error_msg": None}

    with patch.object(sched, "iter_sync_all_items", fake_iter):
        got = await sched.sync_all_items(audit_source="manual")

    assert got == [
        {"item_id": "a", "status": "ok", "transactions_added": 0, "balances_updated": 0, "error_msg": None},
        {"item_id": "b", "status": "ok", "transactions_added": 1, "balances_updated": 2, "error_msg": None},
    ]


@pytest.mark.asyncio
async def test_sync_now_stream_emits_ndjson_lines():
    from web.plaid import routes as plaid_routes

    async def fake_iter(*, audit_source: str = "manual"):
        yield {"item_id": "x", "status": "ok", "transactions_added": 0, "balances_updated": 0, "error_msg": None}

    mock_repo = MagicMock()
    mock_repo.get_items = AsyncMock(return_value=[{"item_id": "x"}, {"item_id": "y"}])

    req = MagicMock()
    req.state = MagicMock()
    req.state.user = {"id": 1}

    with patch("web.plaid.routes.get_plaid_repo", lambda: mock_repo), \
         patch("web.plaid.scheduler.iter_sync_all_items", fake_iter), \
         patch.object(plaid_routes, "_audit_manual_plaid_sync", new_callable=AsyncMock) as aud:
        resp = await plaid_routes.sync_now_stream(req)  # type: ignore[arg-type]
        assert resp.media_type == "application/x-ndjson"
        raw = b""
        async for chunk in resp.body_iterator:
            raw += chunk if isinstance(chunk, bytes) else chunk.encode()
        lines = [json.loads(s) for s in raw.decode().strip().split("\n") if s.strip()]
        assert len(lines) == 1
        assert lines[0]["index"] == 1
        assert lines[0]["total"] == 2
        assert lines[0]["result"]["item_id"] == "x"
        aud.assert_awaited_once()
