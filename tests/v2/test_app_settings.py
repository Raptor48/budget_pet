"""Tests for the app-settings module (autosync schedule + webhook toggle)."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from web.app_settings.repo import AppSettingsRepository, DEFAULTS
from tests.v2.conftest import make_mock_pool


def _seed_row(**overrides):
    """Return a repo-shaped dict matching the post-migration schema."""
    base = {
        "autosync_frequency": DEFAULTS["autosync_frequency"],
        "autosync_hour_utc": DEFAULTS["autosync_hour_utc"],
        "autosync_minute_utc": DEFAULTS["autosync_minute_utc"],
        "webhooks_enabled": DEFAULTS["webhooks_enabled"],
        "updated_at": None,
        "updated_by": None,
        "updated_by_username": None,
    }
    base.update(overrides)
    return base


class TestAppSettingsRepository:
    @pytest.mark.asyncio
    async def test_get_seeds_defaults_and_returns_row(self):
        conn = AsyncMock()
        pool = make_mock_pool(conn)

        conn.execute = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=_seed_row())

        repo = AppSettingsRepository()
        with patch("web.db.get_pool", AsyncMock(return_value=pool)):
            row = await repo.get()

        # INSERT ... ON CONFLICT DO NOTHING fires on every GET so the singleton
        # row exists even on a fresh deployment.
        assert conn.execute.await_count == 1
        assert row["autosync_frequency"] == DEFAULTS["autosync_frequency"]
        assert row["autosync_hour_utc"] == DEFAULTS["autosync_hour_utc"]
        assert row["autosync_minute_utc"] == DEFAULTS["autosync_minute_utc"]
        assert row["webhooks_enabled"] is DEFAULTS["webhooks_enabled"]

    @pytest.mark.asyncio
    async def test_update_validates_ranges_and_frequency(self):
        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.execute = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=_seed_row())

        repo = AppSettingsRepository()
        with patch("web.db.get_pool", AsyncMock(return_value=pool)):
            with pytest.raises(ValueError):
                await repo.update(hour_utc=24)
            with pytest.raises(ValueError):
                await repo.update(minute_utc=60)
            # Frequency must be one of the allowed enum values.
            with pytest.raises(ValueError):
                await repo.update(frequency="hourly")

    @pytest.mark.asyncio
    async def test_update_persists_frequency_and_time(self):
        """Update should write all four fields in one UPDATE and return the
        post-write row. We cover both the time change and a frequency change
        in one call to confirm the column is actually persisted."""
        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.execute = AsyncMock()
        conn.fetchrow = AsyncMock(
            side_effect=[
                _seed_row(),  # current
                _seed_row(
                    autosync_frequency="weekly",
                    autosync_hour_utc=21,
                    autosync_minute_utc=30,
                    updated_by=42,
                    updated_by_username="denis",
                ),  # post-write
            ]
        )

        repo = AppSettingsRepository()
        with patch("web.db.get_pool", AsyncMock(return_value=pool)):
            row = await repo.update(
                frequency="weekly", hour_utc=21, minute_utc=30, updated_by=42
            )

        assert row["autosync_frequency"] == "weekly"
        assert row["autosync_hour_utc"] == 21
        assert row["autosync_minute_utc"] == 30
        assert row["updated_by_username"] == "denis"

        update_calls = [
            call for call in conn.execute.await_args_list if "UPDATE app_settings" in str(call)
        ]
        assert update_calls, "expected an UPDATE against app_settings"
        # The UPDATE statement must set the frequency column in addition to the
        # hour/minute/webhooks_enabled columns — regression guard against any
        # future refactor that accidentally drops it.
        assert any(
            "autosync_frequency" in str(call) for call in update_calls
        ), "UPDATE must mention autosync_frequency"


def _fake_row(**overrides):
    base = {
        "autosync_frequency": "daily",
        "autosync_hour_utc": 7,
        "autosync_minute_utc": 15,
        "updated_by": 1,
        "updated_by_username": "owner",
    }
    base.update(overrides)
    return _seed_row(**base)


class FakeState:
    user = {"id": 1, "username": "owner"}


class FakeRequest:
    state = FakeState()
    headers: dict[str, str] = {}
    client = None
    cookies: dict[str, str] = {}


class TestAppSettingsRoutes:
    @pytest.mark.asyncio
    async def test_patch_writes_audit_row_and_reschedules(self):
        from web.app_settings import routes as routes_module
        from web.app_settings.models import AutosyncConfigUpdate

        repo = AsyncMock()
        repo.get = AsyncMock(return_value=_fake_row())
        repo.update = AsyncMock(return_value=_fake_row())

        apply_mock = MagicMock()
        audit_calls: list[dict] = []

        async def fake_record(event_type, *, source="manual", metadata=None, **kwargs):
            audit_calls.append({
                "event_type": event_type,
                "source": source,
                "metadata": metadata or {},
            })

        with patch.object(routes_module, "get_app_settings_repo", return_value=repo), \
             patch("web.plaid.scheduler.apply_autosync_config", apply_mock), \
             patch.object(routes_module, "audit_record", fake_record):
            result = await routes_module.update_app_settings(
                AutosyncConfigUpdate(hour_utc=7, minute_utc=15),
                FakeRequest(),  # type: ignore[arg-type]
            )

        assert result.hour_utc == 7
        assert result.minute_utc == 15
        assert result.frequency == "daily"

        apply_mock.assert_called_once_with(frequency="daily", hour_utc=7, minute_utc=15)

        assert len(audit_calls) == 1
        assert audit_calls[0]["event_type"] == "settings.autosync_updated"
        assert audit_calls[0]["metadata"]["hour_utc"] == 7
        assert audit_calls[0]["metadata"]["minute_utc"] == 15
        assert audit_calls[0]["metadata"]["frequency"] == "daily"

    @pytest.mark.asyncio
    async def test_patch_switches_frequency_to_monthly(self):
        """Changing frequency from daily → monthly should persist and push the
        new trigger to APScheduler via apply_autosync_config."""
        from web.app_settings import routes as routes_module
        from web.app_settings.models import AutosyncConfigUpdate

        repo = AsyncMock()
        repo.get = AsyncMock(return_value=_fake_row())
        repo.update = AsyncMock(return_value=_fake_row(autosync_frequency="monthly"))

        apply_mock = MagicMock()

        async def fake_record(*args, **kwargs):
            return None

        with patch.object(routes_module, "get_app_settings_repo", return_value=repo), \
             patch("web.plaid.scheduler.apply_autosync_config", apply_mock), \
             patch.object(routes_module, "audit_record", fake_record):
            result = await routes_module.update_app_settings(
                AutosyncConfigUpdate(frequency="monthly"),
                FakeRequest(),  # type: ignore[arg-type]
            )

        assert result.frequency == "monthly"
        apply_mock.assert_called_once_with(frequency="monthly", hour_utc=7, minute_utc=15)

    @pytest.mark.asyncio
    async def test_patch_off_removes_scheduler_job(self):
        """``frequency='off'`` must propagate to the scheduler so we actually
        stop firing Plaid calls — the UI choice is worthless otherwise."""
        from web.app_settings import routes as routes_module
        from web.app_settings.models import AutosyncConfigUpdate

        repo = AsyncMock()
        repo.get = AsyncMock(return_value=_fake_row())
        repo.update = AsyncMock(return_value=_fake_row(autosync_frequency="off"))

        apply_mock = MagicMock()

        async def fake_record(*args, **kwargs):
            return None

        with patch.object(routes_module, "get_app_settings_repo", return_value=repo), \
             patch("web.plaid.scheduler.apply_autosync_config", apply_mock), \
             patch.object(routes_module, "audit_record", fake_record):
            await routes_module.update_app_settings(
                AutosyncConfigUpdate(frequency="off"),
                FakeRequest(),  # type: ignore[arg-type]
            )

        apply_mock.assert_called_once_with(frequency="off", hour_utc=7, minute_utc=15)

    @pytest.mark.asyncio
    async def test_patch_reconciles_plaid_webhooks_on_flag_flip(self, monkeypatch):
        """Flipping webhooks_enabled must push the change to every Plaid item,
        otherwise Plaid keeps pushing and the $0.10 Balance calls keep coming."""
        from web.app_settings import routes as routes_module
        from web.app_settings.models import AutosyncConfigUpdate
        from web.plaid import webhook_config as webhook_config_module

        repo = AsyncMock()
        repo.get = AsyncMock(return_value=_fake_row(webhooks_enabled=True))
        repo.update = AsyncMock(return_value=_fake_row(webhooks_enabled=False))

        plaid_repo = AsyncMock()
        plaid_repo.get_items = AsyncMock(
            return_value=[
                {"item_id": "item-a", "access_token": "access-a"},
                {"item_id": "item-b", "access_token": "access-b"},
            ]
        )

        update_calls: list[tuple[str, str]] = []

        def fake_update_item_webhook(access_token: str, webhook: str) -> bool:
            update_calls.append((access_token, webhook))
            return True

        audit_calls: list[dict] = []

        async def fake_record(event_type, *, source="manual", metadata=None, **kwargs):
            audit_calls.append({"event_type": event_type, "metadata": metadata or {}})

        monkeypatch.setenv("PLAID_WEBHOOK_URL", "https://example.com/hook")

        with patch.object(routes_module, "get_app_settings_repo", return_value=repo), \
             patch("web.plaid.scheduler.apply_autosync_config", MagicMock()), \
             patch.object(webhook_config_module, "get_plaid_repo", return_value=plaid_repo), \
             patch.object(webhook_config_module, "update_item_webhook", fake_update_item_webhook), \
             patch.object(routes_module, "audit_record", fake_record):
            result = await routes_module.update_app_settings(
                AutosyncConfigUpdate(webhooks_enabled=False),
                FakeRequest(),  # type: ignore[arg-type]
            )

        # Plaid was told to clear the webhook URL ("" ≡ disable) on every item.
        assert update_calls == [("access-a", ""), ("access-b", "")]
        assert result.webhooks_enabled is False
        assert result.webhook_reconcile is not None
        assert result.webhook_reconcile.updated == 2
        assert result.webhook_reconcile.failed == 0
        # Audit carries the reconcile summary so it's visible on the Log tab.
        assert audit_calls[0]["metadata"]["webhook_reconcile"]["updated"] == 2

    @pytest.mark.asyncio
    async def test_patch_skips_reconcile_when_flag_unchanged(self):
        """Editing only the sync time must NOT call Plaid for every item."""
        from web.app_settings import routes as routes_module
        from web.app_settings.models import AutosyncConfigUpdate
        from web.plaid import webhook_config as webhook_config_module

        repo = AsyncMock()
        repo.get = AsyncMock(return_value=_fake_row(webhooks_enabled=True))
        repo.update = AsyncMock(return_value=_fake_row(webhooks_enabled=True, autosync_hour_utc=9))

        sentinel = MagicMock()

        async def fake_record(*args, **kwargs):
            return None

        with patch.object(routes_module, "get_app_settings_repo", return_value=repo), \
             patch("web.plaid.scheduler.apply_autosync_config", MagicMock()), \
             patch.object(webhook_config_module, "reconcile_item_webhooks", sentinel), \
             patch.object(routes_module, "audit_record", fake_record):
            await routes_module.update_app_settings(
                AutosyncConfigUpdate(hour_utc=9),
                FakeRequest(),  # type: ignore[arg-type]
            )

        sentinel.assert_not_called()

    @pytest.mark.asyncio
    async def test_patch_refuses_to_enable_without_webhook_url(self, monkeypatch):
        """Enabling webhooks when PLAID_WEBHOOK_URL is unset must surface an
        error rather than silently succeeding and leaving items un-subscribed."""
        from web.app_settings import routes as routes_module
        from web.app_settings.models import AutosyncConfigUpdate
        from web.plaid import webhook_config as webhook_config_module

        repo = AsyncMock()
        repo.get = AsyncMock(return_value=_fake_row(webhooks_enabled=False))
        repo.update = AsyncMock(return_value=_fake_row(webhooks_enabled=True))

        monkeypatch.delenv("PLAID_WEBHOOK_URL", raising=False)

        plaid_repo = AsyncMock()
        plaid_repo.get_items = AsyncMock(return_value=[{"item_id": "x", "access_token": "y"}])
        update_calls: list[tuple[str, str]] = []

        def fake_update_item_webhook(access_token: str, webhook: str) -> bool:
            update_calls.append((access_token, webhook))
            return True

        async def fake_record(*args, **kwargs):
            return None

        with patch.object(routes_module, "get_app_settings_repo", return_value=repo), \
             patch("web.plaid.scheduler.apply_autosync_config", MagicMock()), \
             patch.object(webhook_config_module, "get_plaid_repo", return_value=plaid_repo), \
             patch.object(webhook_config_module, "update_item_webhook", fake_update_item_webhook), \
             patch.object(routes_module, "audit_record", fake_record):
            result = await routes_module.update_app_settings(
                AutosyncConfigUpdate(webhooks_enabled=True),
                FakeRequest(),  # type: ignore[arg-type]
            )

        # No Plaid calls made, and the reconcile result surfaces the configuration error.
        assert update_calls == []
        assert result.webhook_reconcile is not None
        assert result.webhook_reconcile.total == 0
        assert any("PLAID_WEBHOOK_URL" in err for err in result.webhook_reconcile.errors)
