"""
BotRepository — every table the Telegram bot interacts with that doesn't
already have a home in another module.

Read by the FastAPI router under /api/bot/* AND directly by the bot's own
handlers (web.telegram.handlers.*). Keep methods small + composable so both
callers can build whatever flow they need.
"""
from __future__ import annotations

import logging
import secrets
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence

from web.db import get_pool

logger = logging.getLogger(__name__)


# Default mood threshold = $300 (matches docs/CLAUDE.md and Settings UI).
DEFAULT_MOOD_THRESHOLD_CENTS = 30000

# Default morning brief — 09:00 in the household timezone (defaults to ET so
# the legacy autosync schedule still feels right; overridable per user).
DEFAULT_MORNING_BRIEF = time(9, 0)
DEFAULT_TIMEZONE = "America/New_York"

# Streak labels the UI knows how to render. Adding a new streak type? Add a
# label here so the Bot section prints something humans understand.
STREAK_LABELS: Dict[str, str] = {
    "audit_weeks": "Audit Sundays",
    "under_budget": "Months under budget",
    "no_impulse": "Days without impulse spend",
}

# Notification alert types the user can toggle. Tuple of (key, label, default,
# description). Bot only sends an alert when the row is missing OR enabled.
DEFAULT_NOTIFICATION_PREFS: List[Dict[str, Any]] = [
    {
        "alert_type": "budget_threshold",
        "label": "Budget threshold",
        "enabled": True,
        "description": "Push when a category crosses 100% of its monthly budget.",
    },
    {
        "alert_type": "recurring_tomorrow",
        "label": "Recurring tomorrow",
        "enabled": True,
        "description": "Heads-up the day before a recurring charge is expected.",
    },
    {
        "alert_type": "plaid_reauth",
        "label": "Bank needs re-auth",
        "enabled": True,
        "description": "Push the moment Plaid flags a connection broken.",
    },
    {
        "alert_type": "new_merchant",
        "label": "New merchant",
        "enabled": True,
        "description": "Notify the first time a never-before-seen merchant shows up.",
    },
    {
        "alert_type": "subscription_creep",
        "label": "Subscription creep / price hike",
        "enabled": True,
        "description": "New subscription detected or existing one charged more.",
    },
    {
        "alert_type": "milestone",
        "label": "Net-worth milestones",
        "enabled": True,
        "description": "Tiny celebration when a saved milestone is reached.",
    },
    {
        "alert_type": "mood_check",
        "label": "Mood check",
        "enabled": True,
        "description": "Bundled into the morning brief — never wakes you up.",
    },
    {
        "alert_type": "leaderboard",
        "label": "Couple leaderboard",
        "enabled": True,
        "description": "Weekly snapshot of who topped each category.",
    },
    {
        "alert_type": "sunday_brief",
        "label": "Sunday Audit brief",
        "enabled": True,
        "description": "All-in-one Sunday morning summary right after sync.",
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row_to_dict(row) -> Optional[Dict[str, Any]]:
    return dict(row) if row else None


def _week_start(d: Optional[date] = None) -> date:
    """ISO week — Monday as start. Used for chore rotation + audit sessions."""
    base = d or date.today()
    return base - timedelta(days=base.weekday())


class BotRepository:
    """Single repository for every bot-only table."""

    async def _pool(self):
        return await get_pool()

    # ------------------------------------------------------------------
    # Telegram link
    # ------------------------------------------------------------------

    async def get_telegram_link_status(self, user_id: int) -> Dict[str, Any]:
        pool = await self._pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT telegram_chat_id, telegram_username,
                       telegram_link_code, telegram_link_code_expires_at
                FROM users WHERE id = $1
                """,
                user_id,
            )
        if not row:
            return {"linked": False}
        chat_id = row["telegram_chat_id"]
        return {
            "linked": chat_id is not None,
            "chat_id": chat_id,
            "telegram_username": row["telegram_username"],
            "pending_code": (
                row["telegram_link_code"] if chat_id is None else None
            ),
            "pending_expires_at": (
                row["telegram_link_code_expires_at"] if chat_id is None else None
            ),
        }

    async def issue_telegram_link_code(self, user_id: int) -> Dict[str, Any]:
        """Generate a fresh 6-char alphanumeric code valid for 15 minutes."""
        code = secrets.token_urlsafe(8)[:8].upper().replace("_", "X").replace("-", "X")
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)
        pool = await self._pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE users
                   SET telegram_link_code = $2,
                       telegram_link_code_expires_at = $3
                 WHERE id = $1
                """,
                user_id,
                code,
                expires_at,
            )
        return {"code": code, "expires_at": expires_at}

    async def find_user_by_link_code(self, code: str) -> Optional[Dict[str, Any]]:
        pool = await self._pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, username, telegram_link_code_expires_at
                FROM users
                WHERE telegram_link_code = $1
                """,
                code.strip().upper(),
            )
        return _row_to_dict(row)

    async def attach_telegram_chat(
        self,
        user_id: int,
        chat_id: int,
        telegram_username: Optional[str] = None,
    ) -> None:
        pool = await self._pool()
        async with pool.acquire() as conn:
            # Detach this chat from any other user first (admin re-link case).
            await conn.execute(
                """
                UPDATE users SET telegram_chat_id = NULL,
                                 telegram_username = NULL
                 WHERE telegram_chat_id = $1 AND id <> $2
                """,
                chat_id,
                user_id,
            )
            await conn.execute(
                """
                UPDATE users
                   SET telegram_chat_id = $2,
                       telegram_username = $3,
                       telegram_link_code = NULL,
                       telegram_link_code_expires_at = NULL
                 WHERE id = $1
                """,
                user_id,
                chat_id,
                telegram_username,
            )

    async def detach_telegram_chat(self, user_id: int) -> None:
        pool = await self._pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE users
                   SET telegram_chat_id = NULL,
                       telegram_username = NULL,
                       telegram_link_code = NULL,
                       telegram_link_code_expires_at = NULL
                 WHERE id = $1
                """,
                user_id,
            )

    async def find_user_by_chat_id(self, chat_id: int) -> Optional[Dict[str, Any]]:
        pool = await self._pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, username, is_owner
                FROM users WHERE telegram_chat_id = $1
                """,
                chat_id,
            )
        return _row_to_dict(row)

    async def list_users_with_chat(self) -> List[Dict[str, Any]]:
        pool = await self._pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, username, telegram_chat_id, telegram_username
                FROM users
                WHERE telegram_chat_id IS NOT NULL
                ORDER BY id
                """,
            )
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Couple settings (one row per user, lazily upserted)
    # ------------------------------------------------------------------

    async def get_couple_settings(self, user_id: int) -> Dict[str, Any]:
        pool = await self._pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT cs.*, p.username AS partner_username
                  FROM couple_settings cs
                  LEFT JOIN users p ON p.id = cs.partner_user_id
                 WHERE cs.user_id = $1
                """,
                user_id,
            )
            if row:
                return dict(row)
            # Auto-seed defaults so the UI always gets a populated row.
            await conn.execute(
                """
                INSERT INTO couple_settings (
                    user_id, mood_threshold_cents,
                    morning_brief_local, morning_brief_tz
                ) VALUES ($1, $2, $3, $4)
                ON CONFLICT (user_id) DO NOTHING
                """,
                user_id,
                DEFAULT_MOOD_THRESHOLD_CENTS,
                DEFAULT_MORNING_BRIEF,
                DEFAULT_TIMEZONE,
            )
            row = await conn.fetchrow(
                """
                SELECT cs.*, p.username AS partner_username
                  FROM couple_settings cs
                  LEFT JOIN users p ON p.id = cs.partner_user_id
                 WHERE cs.user_id = $1
                """,
                user_id,
            )
        return dict(row)

    async def update_couple_settings(
        self, user_id: int, patch: Dict[str, Any]
    ) -> Dict[str, Any]:
        if not patch:
            return await self.get_couple_settings(user_id)
        # Make sure a row exists first.
        await self.get_couple_settings(user_id)
        pool = await self._pool()
        async with pool.acquire() as conn:
            cols = []
            args: List[Any] = [user_id]
            for k, v in patch.items():
                args.append(v)
                cols.append(f"{k} = ${len(args)}")
            cols.append("updated_at = NOW()")
            sql = (
                "UPDATE couple_settings SET "
                + ", ".join(cols)
                + " WHERE user_id = $1"
            )
            await conn.execute(sql, *args)
        return await self.get_couple_settings(user_id)

    # ------------------------------------------------------------------
    # Notification preferences
    # ------------------------------------------------------------------

    async def list_notification_prefs(self, user_id: int) -> List[Dict[str, Any]]:
        pool = await self._pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT alert_type, enabled FROM user_notification_prefs WHERE user_id = $1",
                user_id,
            )
        seen = {r["alert_type"]: r["enabled"] for r in rows}
        out = []
        for default in DEFAULT_NOTIFICATION_PREFS:
            out.append(
                {
                    "alert_type": default["alert_type"],
                    "label": default["label"],
                    "description": default["description"],
                    "enabled": seen.get(default["alert_type"], default["enabled"]),
                }
            )
        return out

    async def set_notification_pref(
        self, user_id: int, alert_type: str, enabled: bool
    ) -> Dict[str, Any]:
        pool = await self._pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO user_notification_prefs (user_id, alert_type, enabled)
                VALUES ($1, $2, $3)
                ON CONFLICT (user_id, alert_type) DO UPDATE SET enabled = EXCLUDED.enabled
                """,
                user_id,
                alert_type,
                enabled,
            )
        # Return the freshly merged value.
        for pref in await self.list_notification_prefs(user_id):
            if pref["alert_type"] == alert_type:
                return pref
        raise ValueError(f"Unknown alert type {alert_type}")

    async def is_alert_enabled(self, user_id: int, alert_type: str) -> bool:
        pool = await self._pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT enabled FROM user_notification_prefs WHERE user_id = $1 AND alert_type = $2",
                user_id,
                alert_type,
            )
        if row is not None:
            return bool(row["enabled"])
        # Fall back to the static default.
        for default in DEFAULT_NOTIFICATION_PREFS:
            if default["alert_type"] == alert_type:
                return bool(default["enabled"])
        return True

    # ------------------------------------------------------------------
    # Chores
    # ------------------------------------------------------------------

    async def list_chores(self) -> List[Dict[str, Any]]:
        pool = await self._pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM chores ORDER BY sort_order, id"
            )
        return [dict(r) for r in rows]

    async def create_chore(self, data: Dict[str, Any]) -> Dict[str, Any]:
        pool = await self._pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO chores (name, icon, rotation, fixed_user_id, sort_order)
                VALUES ($1, $2, $3, $4, COALESCE($5, 0))
                RETURNING *
                """,
                data["name"],
                data.get("icon"),
                data.get("rotation", "weekly"),
                data.get("fixed_user_id"),
                data.get("sort_order"),
            )
        return dict(row)

    async def update_chore(
        self, chore_id: int, patch: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        if not patch:
            pool = await self._pool()
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM chores WHERE id = $1", chore_id
                )
            return _row_to_dict(row)
        pool = await self._pool()
        async with pool.acquire() as conn:
            cols = []
            args: List[Any] = [chore_id]
            for k, v in patch.items():
                args.append(v)
                cols.append(f"{k} = ${len(args)}")
            sql = (
                "UPDATE chores SET "
                + ", ".join(cols)
                + " WHERE id = $1 RETURNING *"
            )
            row = await conn.fetchrow(sql, *args)
        return _row_to_dict(row)

    async def delete_chore(self, chore_id: int) -> bool:
        pool = await self._pool()
        async with pool.acquire() as conn:
            res = await conn.execute("DELETE FROM chores WHERE id = $1", chore_id)
        return res.endswith(" 1")

    async def list_assignments_for_week(
        self, week_start: date
    ) -> List[Dict[str, Any]]:
        pool = await self._pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT ca.chore_id, ca.user_id, ca.week_start, ca.completed_at,
                       c.name AS chore_name, c.icon AS chore_icon,
                       u.username
                FROM chore_assignments ca
                JOIN chores c ON c.id = ca.chore_id
                JOIN users u ON u.id = ca.user_id
                WHERE ca.week_start = $1
                ORDER BY c.sort_order, c.id
                """,
                week_start,
            )
        return [dict(r) for r in rows]

    async def upsert_assignment(
        self,
        chore_id: int,
        week_start: date,
        user_id: int,
    ) -> Dict[str, Any]:
        pool = await self._pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO chore_assignments (chore_id, week_start, user_id)
                VALUES ($1, $2, $3)
                ON CONFLICT (chore_id, week_start) DO UPDATE SET user_id = EXCLUDED.user_id
                RETURNING *
                """,
                chore_id,
                week_start,
                user_id,
            )
        return dict(row)

    async def set_assignment_completed(
        self, chore_id: int, week_start: date, completed: bool
    ) -> Optional[Dict[str, Any]]:
        pool = await self._pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE chore_assignments
                   SET completed_at = CASE WHEN $3 THEN NOW() ELSE NULL END
                 WHERE chore_id = $1 AND week_start = $2
                RETURNING *
                """,
                chore_id,
                week_start,
                completed,
            )
        return _row_to_dict(row)

    async def regenerate_week_assignments(
        self, week_start: date, household_user_ids: Sequence[int]
    ) -> List[Dict[str, Any]]:
        """Auto-fill assignments for the given week.

        For ``rotation = 'weekly'`` we alternate between household members
        based on (week_index + sort_order). For ``'biweekly'`` we change every
        14 days. ``'fixed'`` always falls to ``fixed_user_id`` (or the first
        household member if unset). Existing rows are preserved so the user
        can override an auto pick from the UI without losing it next week.
        """
        if not household_user_ids:
            return []
        members = list(household_user_ids)
        chores = await self.list_chores()
        assignments: List[Dict[str, Any]] = []
        # Use the ordinal of the Monday since 1970 to keep rotation stable
        # across deploys / DST adjustments.
        week_idx = week_start.toordinal() // 7
        existing = {
            r["chore_id"]: r for r in await self.list_assignments_for_week(week_start)
        }
        for chore in chores:
            if not chore["is_active"]:
                continue
            if chore["id"] in existing:
                assignments.append(existing[chore["id"]])
                continue
            if chore["rotation"] == "fixed" and chore["fixed_user_id"]:
                user_id = chore["fixed_user_id"]
            else:
                period = 2 if chore["rotation"] == "biweekly" else 1
                rotated_idx = (week_idx // period + chore["sort_order"]) % len(members)
                user_id = members[rotated_idx]
            row = await self.upsert_assignment(chore["id"], week_start, user_id)
            assignments.append(
                {**row, "chore_name": chore["name"], "chore_icon": chore["icon"]}
            )
        return assignments

    # ------------------------------------------------------------------
    # Audit sessions
    # ------------------------------------------------------------------

    async def get_or_create_audit_session(
        self, week_start: Optional[date] = None
    ) -> Dict[str, Any]:
        ws = week_start or _week_start()
        pool = await self._pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT a.*, u.username AS host_username
                FROM audit_sessions a
                LEFT JOIN users u ON u.id = a.host_user_id
                WHERE a.week_start = $1
                """,
                ws,
            )
            if row:
                return dict(row)
            await conn.execute(
                "INSERT INTO audit_sessions (week_start) VALUES ($1) ON CONFLICT DO NOTHING",
                ws,
            )
            row = await conn.fetchrow(
                """
                SELECT a.*, u.username AS host_username
                FROM audit_sessions a
                LEFT JOIN users u ON u.id = a.host_user_id
                WHERE a.week_start = $1
                """,
                ws,
            )
        return dict(row)

    async def update_audit_session(
        self, week_start: date, patch: Dict[str, Any]
    ) -> Dict[str, Any]:
        if not patch:
            return await self.get_or_create_audit_session(week_start)
        pool = await self._pool()
        await self.get_or_create_audit_session(week_start)
        async with pool.acquire() as conn:
            cols = []
            args: List[Any] = [week_start]
            for k, v in patch.items():
                if k == "completed":
                    args.append(v)
                    cols.append(
                        f"completed_at = CASE WHEN ${len(args)} THEN NOW() ELSE NULL END"
                    )
                else:
                    args.append(v)
                    cols.append(f"{k} = ${len(args)}")
            sql = (
                "UPDATE audit_sessions SET "
                + ", ".join(cols)
                + " WHERE week_start = $1"
            )
            await conn.execute(sql, *args)
        return await self.get_or_create_audit_session(week_start)

    async def list_audit_sessions(self, limit: int = 26) -> List[Dict[str, Any]]:
        pool = await self._pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT a.*, u.username AS host_username
                FROM audit_sessions a
                LEFT JOIN users u ON u.id = a.host_user_id
                ORDER BY a.week_start DESC
                LIMIT $1
                """,
                limit,
            )
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Streaks
    # ------------------------------------------------------------------

    async def list_streaks(self, user_id: int) -> List[Dict[str, Any]]:
        pool = await self._pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM user_streaks WHERE user_id = $1 ORDER BY streak_type",
                user_id,
            )
        seen = {r["streak_type"]: dict(r) for r in rows}
        out = []
        for streak_type, label in STREAK_LABELS.items():
            r = seen.get(streak_type, {})
            out.append(
                {
                    "streak_type": streak_type,
                    "label": label,
                    "current_count": r.get("current_count", 0),
                    "longest_count": r.get("longest_count", 0),
                    "last_event_at": r.get("last_event_at"),
                }
            )
        return out

    async def bump_streak(
        self, user_id: int, streak_type: str, *, reset: bool = False
    ) -> Dict[str, Any]:
        pool = await self._pool()
        async with pool.acquire() as conn:
            if reset:
                row = await conn.fetchrow(
                    """
                    INSERT INTO user_streaks (user_id, streak_type, current_count, longest_count, last_event_at)
                    VALUES ($1, $2, 0, 0, NOW())
                    ON CONFLICT (user_id, streak_type) DO UPDATE SET
                        current_count = 0,
                        last_event_at = NOW()
                    RETURNING *
                    """,
                    user_id,
                    streak_type,
                )
            else:
                row = await conn.fetchrow(
                    """
                    INSERT INTO user_streaks (user_id, streak_type, current_count, longest_count, last_event_at)
                    VALUES ($1, $2, 1, 1, NOW())
                    ON CONFLICT (user_id, streak_type) DO UPDATE SET
                        current_count = user_streaks.current_count + 1,
                        longest_count = GREATEST(user_streaks.longest_count, user_streaks.current_count + 1),
                        last_event_at = NOW()
                    RETURNING *
                    """,
                    user_id,
                    streak_type,
                )
        return dict(row)

    # ------------------------------------------------------------------
    # Net-worth milestones
    # ------------------------------------------------------------------

    async def list_milestones(self, user_id: int) -> List[Dict[str, Any]]:
        pool = await self._pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM user_milestones
                WHERE user_id = $1
                ORDER BY threshold_cents
                """,
                user_id,
            )
        return [dict(r) for r in rows]

    async def add_milestone(
        self, user_id: int, threshold_cents: int, label: Optional[str] = None
    ) -> Dict[str, Any]:
        pool = await self._pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO user_milestones (user_id, threshold_cents, label)
                VALUES ($1, $2, $3)
                ON CONFLICT (user_id, threshold_cents) DO UPDATE SET label = EXCLUDED.label
                RETURNING *
                """,
                user_id,
                threshold_cents,
                label,
            )
        return dict(row)

    async def delete_milestone(self, user_id: int, milestone_id: int) -> bool:
        pool = await self._pool()
        async with pool.acquire() as conn:
            res = await conn.execute(
                "DELETE FROM user_milestones WHERE id = $1 AND user_id = $2",
                milestone_id,
                user_id,
            )
        return res.endswith(" 1")

    async def mark_milestone_reached(
        self, user_id: int, threshold_cents: int
    ) -> Optional[Dict[str, Any]]:
        pool = await self._pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE user_milestones
                   SET reached_at = COALESCE(reached_at, NOW())
                 WHERE user_id = $1 AND threshold_cents = $2
                RETURNING *
                """,
                user_id,
                threshold_cents,
            )
        return _row_to_dict(row)

    # ------------------------------------------------------------------
    # Mood log
    # ------------------------------------------------------------------

    async def upsert_mood(
        self,
        transaction_id: int,
        user_id: int,
        mood: str,
        note: Optional[str] = None,
    ) -> Dict[str, Any]:
        pool = await self._pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO transaction_mood (transaction_id, user_id, mood, note)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (transaction_id) DO UPDATE SET
                    user_id = EXCLUDED.user_id,
                    mood = EXCLUDED.mood,
                    note = EXCLUDED.note,
                    created_at = NOW()
                RETURNING *
                """,
                transaction_id,
                user_id,
                mood,
                note,
            )
        return dict(row)

    async def list_recent_moods(
        self, user_id: int, limit: int = 50
    ) -> List[Dict[str, Any]]:
        pool = await self._pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT m.transaction_id, m.mood, m.note, m.created_at,
                       t.amount_cents AS transaction_amount_cents,
                       COALESCE(t.display_title, t.name) AS transaction_name,
                       t.date AS transaction_date
                FROM transaction_mood m
                JOIN transactions t ON t.id = m.transaction_id
                WHERE m.user_id = $1
                ORDER BY m.created_at DESC
                LIMIT $2
                """,
                user_id,
                limit,
            )
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Merchant-seen
    # ------------------------------------------------------------------

    async def remember_merchant(self, merchant_key: str) -> Dict[str, Any]:
        """Insert an entry; returns ``{"new": True}`` only on the first sighting."""
        pool = await self._pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO merchant_seen (merchant_key)
                VALUES ($1)
                ON CONFLICT (merchant_key) DO NOTHING
                RETURNING id, first_seen_at
                """,
                merchant_key,
            )
        if row:
            return {"new": True, "first_seen_at": row["first_seen_at"]}
        return {"new": False}

    async def mark_merchant_notified(self, merchant_key: str) -> None:
        pool = await self._pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE merchant_seen SET notified_at = NOW() WHERE merchant_key = $1",
                merchant_key,
            )

    # ------------------------------------------------------------------
    # Recurring price snapshots
    # ------------------------------------------------------------------

    async def record_recurring_amount(
        self, recurring_id: int, amount_cents: int, currency: str = "USD"
    ) -> None:
        pool = await self._pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT amount_cents
                FROM recurring_price_snapshots
                WHERE recurring_id = $1
                ORDER BY observed_at DESC
                LIMIT 1
                """,
                recurring_id,
            )
            # Skip insert if the amount hasn't changed; we only care about deltas.
            if row is not None and row["amount_cents"] == amount_cents:
                return
            await conn.execute(
                """
                INSERT INTO recurring_price_snapshots (recurring_id, amount_cents, currency)
                VALUES ($1, $2, $3)
                """,
                recurring_id,
                amount_cents,
                currency,
            )

    async def get_recurring_price_history(
        self, recurring_id: int, limit: int = 12
    ) -> List[Dict[str, Any]]:
        pool = await self._pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT amount_cents, currency, observed_at
                FROM recurring_price_snapshots
                WHERE recurring_id = $1
                ORDER BY observed_at DESC
                LIMIT $2
                """,
                recurring_id,
                limit,
            )
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Receipts
    # ------------------------------------------------------------------

    async def create_receipt(
        self,
        user_id: int,
        image_data: bytes,
        image_mime: str,
        merchant_name: Optional[str] = None,
        receipt_date: Optional[date] = None,
        total_cents: Optional[int] = None,
        tax_cents: Optional[int] = None,
        currency: str = "USD",
        raw_ocr_json: Optional[Any] = None,
        parse_status: str = "parsed",
        transaction_id: Optional[int] = None,
        lines: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        pool = await self._pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """
                    INSERT INTO receipts (
                        user_id, transaction_id, merchant_name, receipt_date,
                        total_cents, tax_cents, currency, image_data, image_mime,
                        raw_ocr_json, parse_status
                    ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
                    RETURNING *
                    """,
                    user_id,
                    transaction_id,
                    merchant_name,
                    receipt_date,
                    total_cents,
                    tax_cents,
                    currency,
                    image_data,
                    image_mime,
                    raw_ocr_json,
                    parse_status,
                )
                receipt_id = row["id"]
                if lines:
                    for idx, line in enumerate(lines, start=1):
                        await conn.execute(
                            """
                            INSERT INTO receipt_lines (
                                receipt_id, line_number, description,
                                quantity, unit_price_cents, total_cents
                            ) VALUES ($1,$2,$3,$4,$5,$6)
                            """,
                            receipt_id,
                            idx,
                            line["description"],
                            line.get("quantity"),
                            line.get("unit_price_cents"),
                            line["total_cents"],
                        )
        return dict(row)

    async def attach_receipt_to_transaction(
        self, receipt_id: int, transaction_id: int
    ) -> None:
        pool = await self._pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE receipts SET transaction_id = $2 WHERE id = $1",
                receipt_id,
                transaction_id,
            )

    async def list_receipts(
        self, user_id: int, limit: int = 40
    ) -> List[Dict[str, Any]]:
        pool = await self._pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, transaction_id, merchant_name, receipt_date,
                       total_cents, tax_cents, currency, parse_status,
                       image_mime, created_at,
                       (image_data IS NOT NULL) AS has_image
                FROM receipts
                WHERE user_id = $1
                ORDER BY created_at DESC
                LIMIT $2
                """,
                user_id,
                limit,
            )
        return [dict(r) for r in rows]

    async def get_receipt(
        self, user_id: int, receipt_id: int, with_image: bool = False
    ) -> Optional[Dict[str, Any]]:
        pool = await self._pool()
        cols = (
            "id, transaction_id, merchant_name, receipt_date, total_cents, "
            "tax_cents, currency, parse_status, image_mime, created_at, "
            "(image_data IS NOT NULL) AS has_image"
        )
        if with_image:
            cols += ", image_data"
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT {cols} FROM receipts WHERE id = $1 AND user_id = $2",
                receipt_id,
                user_id,
            )
            if not row:
                return None
            lines = await conn.fetch(
                """
                SELECT id, line_number, description, quantity,
                       unit_price_cents, total_cents
                FROM receipt_lines
                WHERE receipt_id = $1
                ORDER BY line_number
                """,
                receipt_id,
            )
        out = dict(row)
        out["lines"] = [dict(line) for line in lines]
        return out

    async def delete_receipt(self, user_id: int, receipt_id: int) -> bool:
        pool = await self._pool()
        async with pool.acquire() as conn:
            res = await conn.execute(
                "DELETE FROM receipts WHERE id = $1 AND user_id = $2",
                receipt_id,
                user_id,
            )
        return res.endswith(" 1")

    # ------------------------------------------------------------------
    # Couple leaderboard
    # ------------------------------------------------------------------

    async def get_weekly_leaderboard(
        self, week_start: Optional[date] = None
    ) -> Dict[str, Any]:
        """Per-user, per-category top spend over the trailing week.

        Joins transactions → accounts → users. Banks linked to a Plaid item
        are credited to the user who linked them (``plaid_items.user_id``);
        cash wallets to their owning user via ``accounts.user_id`` if set.
        """
        ws = week_start or _week_start()
        we = ws + timedelta(days=7)
        pool = await self._pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                WITH owned AS (
                    SELECT t.id, t.amount_cents, t.category_id,
                           COALESCE(pi.user_id, a.user_id) AS user_id
                    FROM transactions t
                    JOIN accounts a ON a.id = t.account_id
                    LEFT JOIN plaid_items pi ON pi.item_id = a.plaid_item_id
                    WHERE t.date >= $1 AND t.date < $2
                      AND COALESCE(t.transaction_class, 'expense') = 'expense'
                      -- Private transactions are excluded from the shared
                      -- leaderboard; the partner who didn't make the purchase
                      -- shouldn't see it surface in totals here either.
                      AND NOT t.is_private
                ),
                ranked AS (
                    SELECT o.user_id, c.id AS category_id, c.name AS category_name,
                           SUM(o.amount_cents) AS amount_cents,
                           ROW_NUMBER() OVER (
                               PARTITION BY c.id ORDER BY SUM(o.amount_cents) DESC
                           ) AS rn
                    FROM owned o
                    JOIN categories c ON c.id = o.category_id
                    WHERE o.user_id IS NOT NULL
                    GROUP BY o.user_id, c.id, c.name
                )
                SELECT r.user_id, u.username, r.category_id, r.category_name,
                       r.amount_cents
                FROM ranked r
                JOIN users u ON u.id = r.user_id
                WHERE rn = 1
                ORDER BY r.amount_cents DESC
                LIMIT 12
                """,
                ws,
                we,
            )
        return {
            "week_start": ws,
            "entries": [dict(r) for r in rows],
        }


_repo: Optional[BotRepository] = None


def get_bot_repo() -> BotRepository:
    global _repo
    if _repo is None:
        _repo = BotRepository()
    return _repo
