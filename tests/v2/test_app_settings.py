"""Tests for the app-settings module (autosync schedule)."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from web.app_settings.repo import AppSettingsRepository, DEFAULTS
from tests.v2.conftest import make_mock_pool


class TestAppSettingsRepository:
    @pytest.mark.asyncio
    async def test_get_seeds_defaults_and_returns_row(self):
        conn = AsyncMock()
        pool = make_mock_pool(conn)

        conn.execute = AsyncMock()
        conn.fetchrow = AsyncMock(
            return_value={
                "autosync_enabled": DEFAULTS["autosync_enabled"],
                "autosync_hour_utc": DEFAULTS["autosync_hour_utc"],
                "autosync_minute_utc": DEFAULTS["autosync_minute_utc"],
                "updated_at": None,
                "updated_by": None,
                "updated_by_username": None,
            }
        )

        repo = AppSettingsRepository()
        with patch("web.db.get_pool", AsyncMock(return_value=pool)):
            row = await repo.get()

        # INSERT ... ON CONFLICT DO NOTHING fires on every GET so the singleton
        # row exists even on a fresh deployment.
        assert conn.execute.await_count == 1
        assert row["autosync_enabled"] is DEFAULTS["autosync_enabled"]
        assert row["autosync_hour_utc"] == DEFAULTS["autosync_hour_utc"]
        assert row["autosync_minute_utc"] == DEFAULTS["autosync_minute_utc"]

    @pytest.mark.asyncio
    async def test_update_validates_hour_range(self):
        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.execute = AsyncMock()
        conn.fetchrow = AsyncMock(
            return_value={
                "autosync_enabled": True,
                "autosync_hour_utc": 3,
                "autosync_minute_utc": 0,
                "updated_at": None,
                "updated_by": None,
                "updated_by_username": None,
            }
        )

        repo = AppSettingsRepository()
        with patch("web.db.get_pool", AsyncMock(return_value=pool)):
            with pytest.raises(ValueError):
                await repo.update(hour_utc=24)
            with pytest.raises(ValueError):
                await repo.update(minute_utc=60)

    @pytest.mark.asyncio
    async def test_update_persists_new_values(self):
        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.execute = AsyncMock()
        # Two fetchrow calls: one for `current`, one after UPDATE.
        conn.fetchrow = AsyncMock(
            side_effect=[
                {
                    "autosync_enabled": True,
                    "autosync_hour_utc": 3,
                    "autosync_minute_utc": 0,
                    "updated_at": None,
                    "updated_by": None,
                    "updated_by_username": None,
                },
                {
                    "autosync_enabled": False,
                    "autosync_hour_utc": 21,
                    "autosync_minute_utc": 30,
                    "updated_at": None,
                    "updated_by": 42,
                    "updated_by_username": "denis",
                },
            ]
        )

        repo = AppSettingsRepository()
        with patch("web.db.get_pool", AsyncMock(return_value=pool)):
            row = await repo.update(
                enabled=False, hour_utc=21, minute_utc=30, updated_by=42
            )

        assert row["autosync_enabled"] is False
        assert row["autosync_hour_utc"] == 21
        assert row["autosync_minute_utc"] == 30
        assert row["updated_by_username"] == "denis"

        update_calls = [
            call for call in conn.execute.await_args_list if "UPDATE app_settings" in str(call)
        ]
        assert update_calls, "expected an UPDATE against app_settings"


class TestAppSettingsRoutes:
    @pytest.mark.asyncio
    async def test_patch_writes_audit_row_and_reschedules(self):
        from web.app_settings import routes as routes_module
        from web.app_settings.models import AutosyncConfigUpdate

        fake_row = {
            "autosync_enabled": True,
            "autosync_hour_utc": 7,
            "autosync_minute_utc": 15,
            "updated_at": None,
            "updated_by": 1,
            "updated_by_username": "owner",
        }

        repo = AsyncMock()
        repo.update = AsyncMock(return_value=fake_row)

        apply_mock = MagicMock()
        audit_calls: list[dict] = []

        async def fake_record(event_type, *, source="manual", metadata=None, **kwargs):
            audit_calls.append({
                "event_type": event_type,
                "source": source,
                "metadata": metadata or {},
            })

        class FakeState:
            user = {"id": 1, "username": "owner"}

        class FakeRequest:
            state = FakeState()
            headers = {}
            client = None
            cookies: dict[str, str] = {}

        with patch.object(routes_module, "get_app_settings_repo", return_value=repo), \
             patch("web.plaid.scheduler.apply_autosync_config", apply_mock), \
             patch.object(routes_module, "audit_record", fake_record):
            result = await routes_module.update_app_settings(
                AutosyncConfigUpdate(hour_utc=7, minute_utc=15),
                FakeRequest(),  # type: ignore[arg-type]
            )

        assert result.hour_utc == 7
        assert result.minute_utc == 15

        apply_mock.assert_called_once_with(enabled=True, hour_utc=7, minute_utc=15)

        assert len(audit_calls) == 1
        assert audit_calls[0]["event_type"] == "settings.autosync_updated"
        assert audit_calls[0]["metadata"]["hour_utc"] == 7
        assert audit_calls[0]["metadata"]["minute_utc"] == 15
