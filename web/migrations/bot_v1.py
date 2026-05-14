"""
Bot v1 schema — every table the in-process Telegram bot writes to.

All DDL is idempotent (CREATE TABLE IF NOT EXISTS / ALTER … IF NOT EXISTS) and
lives behind a dedicated migration entry-point so a future bot v2 can keep its
own incremental schema without churning v2_init.

Tables added here:

* users.telegram_chat_id            — link app user → Telegram private chat
* couple_settings                   — anniversary date + bot prefs (1 row per user)
* chores + chore_assignments        — household rotation (kitchen/bath/floors …)
* audit_sessions                    — Sunday family audit history (host, snack, notes)
* user_streaks                      — generic counters (audit_weeks, under_budget …)
* user_milestones                   — configurable net-worth thresholds per user
* transaction_mood                  — 👍/👎/🤷 reactions on big purchases
* merchant_seen                     — tracks "first time at merchant" detection
* recurring_price_snapshots         — price history for subscription creep alerts
* notifications_queue               — outbound bot pushes (P0/P1/P2 priority)
* notifications_log                 — dedup + sent history
* user_notification_prefs           — quiet hours + per-alert opt-ins
* receipts + receipt_lines          — OCR archive linked to a cash transaction

Frontend "Bot" section reads/writes everything through /api/bot/*. The bot
itself reads/writes the same tables via the same repos — single source of
truth, no separate datastore.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

# Reuse the V2 lock-wait knob; bot DDL is small but ALTER USERS can wait
# behind a long Plaid sync if startup races.
_DDL_TIMEOUT = float(os.getenv("V2_DDL_TIMEOUT", "120"))


async def _ddl(conn, query: str) -> str:
    return await conn.execute(query, timeout=_DDL_TIMEOUT)


# ---------------------------------------------------------------------------
# Telegram link on the existing users table
# ---------------------------------------------------------------------------

ALTER_USERS_TELEGRAM = """
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS telegram_chat_id BIGINT,
    ADD COLUMN IF NOT EXISTS telegram_username TEXT,
    ADD COLUMN IF NOT EXISTS telegram_link_code TEXT,
    ADD COLUMN IF NOT EXISTS telegram_link_code_expires_at TIMESTAMPTZ
"""

USERS_TELEGRAM_UNIQUE_IDX = """
CREATE UNIQUE INDEX IF NOT EXISTS users_telegram_chat_id_uniq
    ON users(telegram_chat_id) WHERE telegram_chat_id IS NOT NULL
"""

# ---------------------------------------------------------------------------
# Couple settings — one row per user (anniversary, mood threshold, leaderboard)
# ---------------------------------------------------------------------------

CREATE_COUPLE_SETTINGS = """
CREATE TABLE IF NOT EXISTS couple_settings (
    user_id                 INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    anniversary_date        DATE,
    partner_user_id         INTEGER REFERENCES users(id) ON DELETE SET NULL,
    mood_threshold_cents    BIGINT NOT NULL DEFAULT 30000,
    leaderboard_enabled     BOOLEAN NOT NULL DEFAULT TRUE,
    morning_brief_local     TIME NOT NULL DEFAULT '09:00',
    morning_brief_tz        TEXT NOT NULL DEFAULT 'America/New_York',
    quiet_hours_start       TIME NOT NULL DEFAULT '22:00',
    quiet_hours_end         TIME NOT NULL DEFAULT '08:00',
    sunday_brief_enabled    BOOLEAN NOT NULL DEFAULT TRUE,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""

# ---------------------------------------------------------------------------
# Chores — rotation of household tasks
# rotation: 'weekly' (alternate every week) | 'fixed' (always the same person)
# ---------------------------------------------------------------------------

CREATE_CHORES = """
CREATE TABLE IF NOT EXISTS chores (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL,
    icon            TEXT,
    rotation        TEXT NOT NULL DEFAULT 'weekly'
        CHECK (rotation IN ('weekly', 'biweekly', 'fixed')),
    fixed_user_id   INTEGER REFERENCES users(id) ON DELETE SET NULL,
    sort_order      INTEGER NOT NULL DEFAULT 0,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""

CREATE_CHORE_ASSIGNMENTS = """
CREATE TABLE IF NOT EXISTS chore_assignments (
    id            SERIAL PRIMARY KEY,
    chore_id      INTEGER NOT NULL REFERENCES chores(id) ON DELETE CASCADE,
    week_start    DATE NOT NULL,
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    completed_at  TIMESTAMPTZ,
    UNIQUE (chore_id, week_start)
)
"""

CHORE_ASSIGNMENTS_USER_IDX = """
CREATE INDEX IF NOT EXISTS chore_assignments_user_week_idx
    ON chore_assignments(user_id, week_start DESC)
"""

# ---------------------------------------------------------------------------
# Audit sessions — Sunday family ritual log
# ---------------------------------------------------------------------------

CREATE_AUDIT_SESSIONS = """
CREATE TABLE IF NOT EXISTS audit_sessions (
    id            SERIAL PRIMARY KEY,
    week_start    DATE NOT NULL UNIQUE,
    host_user_id  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    snack         TEXT,
    tea_choice    TEXT,
    notes         TEXT,
    completed_at  TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""

# ---------------------------------------------------------------------------
# Streaks — generic per-user counters keyed by streak type
# ---------------------------------------------------------------------------

CREATE_USER_STREAKS = """
CREATE TABLE IF NOT EXISTS user_streaks (
    id            SERIAL PRIMARY KEY,
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    streak_type   TEXT NOT NULL,
    current_count INTEGER NOT NULL DEFAULT 0,
    longest_count INTEGER NOT NULL DEFAULT 0,
    last_event_at TIMESTAMPTZ,
    UNIQUE (user_id, streak_type)
)
"""

# ---------------------------------------------------------------------------
# Net-worth milestones — configurable per user
# ---------------------------------------------------------------------------

CREATE_USER_MILESTONES = """
CREATE TABLE IF NOT EXISTS user_milestones (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    threshold_cents BIGINT NOT NULL,
    label           TEXT,
    reached_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, threshold_cents)
)
"""

# ---------------------------------------------------------------------------
# Mood log — 👍/👎/🤷 on big purchases
# ---------------------------------------------------------------------------

CREATE_TRANSACTION_MOOD = """
CREATE TABLE IF NOT EXISTS transaction_mood (
    transaction_id  INTEGER PRIMARY KEY REFERENCES transactions(id) ON DELETE CASCADE,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    mood            TEXT NOT NULL CHECK (mood IN ('happy', 'meh', 'regret')),
    note            TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""

# Gift mode is the existing transactions.is_private flag (see
# `web/transactions/repo.py`). Toggle it on a transaction → it is hidden
# from anyone who isn't the owner of the underlying account. The bot
# producers below honour the same invariant; no extra table needed.

# ---------------------------------------------------------------------------
# Merchant-seen log — fires "first time at merchant" alert exactly once
# ---------------------------------------------------------------------------

CREATE_MERCHANT_SEEN = """
CREATE TABLE IF NOT EXISTS merchant_seen (
    id              SERIAL PRIMARY KEY,
    merchant_key    TEXT NOT NULL,
    first_seen_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    notified_at     TIMESTAMPTZ,
    UNIQUE (merchant_key)
)
"""

# ---------------------------------------------------------------------------
# Recurring price snapshots — used by subscription-creep / price-hike alerts
# ---------------------------------------------------------------------------

CREATE_RECURRING_PRICE_SNAPSHOTS = """
CREATE TABLE IF NOT EXISTS recurring_price_snapshots (
    id                SERIAL PRIMARY KEY,
    recurring_id      INTEGER NOT NULL REFERENCES recurring_streams(id) ON DELETE CASCADE,
    amount_cents      BIGINT NOT NULL,
    currency          TEXT NOT NULL DEFAULT 'USD',
    observed_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""

RECURRING_PRICE_SNAPSHOTS_IDX = """
CREATE INDEX IF NOT EXISTS recurring_price_snapshots_stream_idx
    ON recurring_price_snapshots(recurring_id, observed_at DESC)
"""

# ---------------------------------------------------------------------------
# Notification queue — central pipe for every outbound bot push
# ---------------------------------------------------------------------------

CREATE_NOTIFICATIONS_QUEUE = """
CREATE TABLE IF NOT EXISTS notifications_queue (
    id              BIGSERIAL PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    type            TEXT NOT NULL,
    priority        TEXT NOT NULL DEFAULT 'P1' CHECK (priority IN ('P0', 'P1', 'P2')),
    payload         JSONB NOT NULL DEFAULT '{}'::jsonb,
    dedup_key       TEXT,
    scheduled_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    sent_at         TIMESTAMPTZ,
    failed_at       TIMESTAMPTZ,
    error           TEXT,
    bundled_into_id BIGINT REFERENCES notifications_queue(id) ON DELETE SET NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""

NOTIFICATIONS_QUEUE_PENDING_IDX = """
CREATE INDEX IF NOT EXISTS notifications_queue_pending_idx
    ON notifications_queue(scheduled_at, priority)
    WHERE sent_at IS NULL AND failed_at IS NULL
"""

NOTIFICATIONS_QUEUE_DEDUP_IDX = """
CREATE INDEX IF NOT EXISTS notifications_queue_dedup_idx
    ON notifications_queue(user_id, type, dedup_key)
    WHERE dedup_key IS NOT NULL
"""

CREATE_USER_NOTIFICATION_PREFS = """
CREATE TABLE IF NOT EXISTS user_notification_prefs (
    user_id           INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    alert_type        TEXT NOT NULL,
    enabled           BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (user_id, alert_type)
)
"""

# ---------------------------------------------------------------------------
# Receipts archive — image + OCR'd line items, optionally linked to a tx
# ---------------------------------------------------------------------------

CREATE_RECEIPTS = """
CREATE TABLE IF NOT EXISTS receipts (
    id                SERIAL PRIMARY KEY,
    user_id           INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    transaction_id    INTEGER REFERENCES transactions(id) ON DELETE SET NULL,
    merchant_name     TEXT,
    receipt_date      DATE,
    total_cents       BIGINT,
    tax_cents         BIGINT,
    currency          TEXT NOT NULL DEFAULT 'USD',
    image_data        BYTEA,
    image_mime        TEXT,
    image_width       INTEGER,
    image_height      INTEGER,
    raw_ocr_json      JSONB,
    parse_status      TEXT NOT NULL DEFAULT 'parsed'
        CHECK (parse_status IN ('pending', 'parsed', 'failed')),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""

CREATE_RECEIPT_LINES = """
CREATE TABLE IF NOT EXISTS receipt_lines (
    id           SERIAL PRIMARY KEY,
    receipt_id   INTEGER NOT NULL REFERENCES receipts(id) ON DELETE CASCADE,
    line_number  INTEGER NOT NULL,
    description  TEXT NOT NULL,
    quantity     NUMERIC(10,3),
    unit_price_cents BIGINT,
    total_cents  BIGINT NOT NULL,
    UNIQUE (receipt_id, line_number)
)
"""

RECEIPTS_USER_IDX = """
CREATE INDEX IF NOT EXISTS receipts_user_idx
    ON receipts(user_id, created_at DESC)
"""

RECEIPTS_TRANSACTION_IDX = """
CREATE INDEX IF NOT EXISTS receipts_transaction_idx
    ON receipts(transaction_id) WHERE transaction_id IS NOT NULL
"""

# ---------------------------------------------------------------------------
# Default chores — seeded on first run, kept idempotent via NOT EXISTS guard
# ---------------------------------------------------------------------------

SEED_DEFAULT_CHORES = """
INSERT INTO chores (name, icon, rotation, sort_order)
SELECT 'Kitchen',  'kitchen', 'weekly', 1
WHERE NOT EXISTS (SELECT 1 FROM chores);
"""

SEED_DEFAULT_CHORES_2 = """
INSERT INTO chores (name, icon, rotation, sort_order)
SELECT 'Bathroom', 'bathroom', 'weekly', 2
WHERE NOT EXISTS (SELECT 1 FROM chores WHERE name = 'Bathroom');
"""

SEED_DEFAULT_CHORES_3 = """
INSERT INTO chores (name, icon, rotation, sort_order)
SELECT 'Floors',   'floors', 'weekly', 3
WHERE NOT EXISTS (SELECT 1 FROM chores WHERE name = 'Floors');
"""


# Drop the short-lived transaction_gifts table — gift mode is the existing
# transactions.is_private flag; the redundant table never had any code paths.
DROP_TRANSACTION_GIFTS = """
DROP TABLE IF EXISTS transaction_gifts
"""

# ---------------------------------------------------------------------------
# Bot activity log — visible in the frontend Bot → Activity tab so the user
# doesn't have to dig through Railway logs to see if the bot is failing.
# ---------------------------------------------------------------------------

CREATE_BOT_ACTIVITY_LOG = """
CREATE TABLE IF NOT EXISTS bot_activity_log (
    id          BIGSERIAL PRIMARY KEY,
    user_id     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    chat_id     BIGINT,
    kind        TEXT NOT NULL,
    severity    TEXT NOT NULL DEFAULT 'info'
                CHECK (severity IN ('info', 'warn', 'error')),
    summary     TEXT NOT NULL,
    payload     JSONB NOT NULL DEFAULT '{}'::jsonb,
    error       TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""

BOT_ACTIVITY_LOG_USER_IDX = """
CREATE INDEX IF NOT EXISTS bot_activity_log_user_idx
    ON bot_activity_log(user_id, created_at DESC)
"""

BOT_ACTIVITY_LOG_SEVERITY_IDX = """
CREATE INDEX IF NOT EXISTS bot_activity_log_severity_idx
    ON bot_activity_log(severity, created_at DESC)
    WHERE severity <> 'info'
"""

BOT_ACTIVITY_LOG_KIND_IDX = """
CREATE INDEX IF NOT EXISTS bot_activity_log_kind_idx
    ON bot_activity_log(kind, created_at DESC)
"""


ALL_STATEMENTS = [
    ALTER_USERS_TELEGRAM,
    USERS_TELEGRAM_UNIQUE_IDX,
    CREATE_COUPLE_SETTINGS,
    CREATE_CHORES,
    CREATE_CHORE_ASSIGNMENTS,
    CHORE_ASSIGNMENTS_USER_IDX,
    CREATE_AUDIT_SESSIONS,
    CREATE_USER_STREAKS,
    CREATE_USER_MILESTONES,
    CREATE_TRANSACTION_MOOD,
    DROP_TRANSACTION_GIFTS,
    CREATE_MERCHANT_SEEN,
    CREATE_RECURRING_PRICE_SNAPSHOTS,
    RECURRING_PRICE_SNAPSHOTS_IDX,
    CREATE_NOTIFICATIONS_QUEUE,
    NOTIFICATIONS_QUEUE_PENDING_IDX,
    NOTIFICATIONS_QUEUE_DEDUP_IDX,
    CREATE_USER_NOTIFICATION_PREFS,
    CREATE_RECEIPTS,
    CREATE_RECEIPT_LINES,
    RECEIPTS_USER_IDX,
    RECEIPTS_TRANSACTION_IDX,
    CREATE_BOT_ACTIVITY_LOG,
    BOT_ACTIVITY_LOG_USER_IDX,
    BOT_ACTIVITY_LOG_SEVERITY_IDX,
    BOT_ACTIVITY_LOG_KIND_IDX,
    SEED_DEFAULT_CHORES,
    SEED_DEFAULT_CHORES_2,
    SEED_DEFAULT_CHORES_3,
]


async def _migrate_merchant_seen_by_key(conn) -> None:
    """V2.3: switch ``merchant_seen`` from raw ``lower(merchant_name)`` to the
    canonical ``merchant_key`` from ``web/merchant_rules/keys.py``.

    Old behaviour: producer keyed merchant_seen by ``merchant_name.lower()``.
    Plaid sometimes returns subtle variants of the same merchant
    (``Apple``, ``APPLE.COM/BILL``, ``Apple Inc.``) — each variant became
    its own ``merchant_seen`` row, so the same merchant fired a "first time
    at X" alert multiple times.

    New behaviour: ``canonical_key`` is ``eid:<entity_id>`` when Plaid
    supplies a stable entity ID, otherwise ``name:<lower(name)>``. Same key
    contract used by ``merchant_aliases`` and ``merchant_category_rules``.

    Migration is additive and idempotent:

    * Add ``canonical_key`` column (nullable until backfilled).
    * Backfill it for every existing row from the legacy ``merchant_key``
      column value, prepending ``name:`` when the row predates the
      structured key namespace, so old rows fall through the same lookup
      branch as new ``name:`` keys.
    * Add a partial UNIQUE index on the new column so producers can
      ON CONFLICT against it. The legacy ``UNIQUE (merchant_key)`` invariant
      stays in place for backwards compat.
    """
    has_canonical = await conn.fetchval(
        """
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'merchant_seen' AND column_name = 'canonical_key'
        """
    )
    if not has_canonical:
        await _ddl(
            conn,
            "ALTER TABLE merchant_seen ADD COLUMN canonical_key TEXT",
        )
        await conn.execute(
            """
            UPDATE merchant_seen
               SET canonical_key = CASE
                   WHEN merchant_key LIKE 'eid:%' OR merchant_key LIKE 'name:%'
                       THEN merchant_key
                   ELSE 'name:' || merchant_key
               END
             WHERE canonical_key IS NULL
            """
        )
    await _ddl(
        conn,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS merchant_seen_canonical_key_uidx
            ON merchant_seen(canonical_key)
            WHERE canonical_key IS NOT NULL
        """,
    )


async def _migrate_telegram_seen_updates(conn) -> None:
    """V2.3 hot-fix: idempotency table for Telegram webhook deliveries.

    Telegram guarantees *at-least-once* delivery — if our 200 response is
    delayed (Railway cold start, DB lock, etc.) the same ``update_id``
    arrives a second time. Without dedup the side effects (cash entry,
    OCR billing, /chores ack) fired twice. The table is keyed by the
    Telegram-supplied ``update_id`` and pruned on a rolling 1-hour window
    so it stays small. Insertions are ``ON CONFLICT DO NOTHING`` and the
    webhook returns 200 immediately when the update was already seen.
    """
    await _ddl(
        conn,
        """
        CREATE TABLE IF NOT EXISTS telegram_seen_updates (
            update_id BIGINT PRIMARY KEY,
            seen_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
    )
    await _ddl(
        conn,
        """
        CREATE INDEX IF NOT EXISTS telegram_seen_updates_seen_at_idx
            ON telegram_seen_updates(seen_at)
        """,
    )


async def _migrate_users_telegram_blocked(conn) -> None:
    """V2.3 hot-fix: ``users.telegram_blocked`` so the dispatcher stops
    re-sending to chats where the bot has been blocked or kicked.

    Before this column the loop kept retrying every minute and producing
    a steady stream of ``Forbidden: bot was blocked by the user`` errors
    in ``bot_activity_log``. The dispatcher now flips this flag the
    first time it sees a permanent Telegram error and short-circuits all
    subsequent sends for that user.
    """
    await _ddl(
        conn,
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS telegram_blocked BOOLEAN NOT NULL DEFAULT FALSE",
    )


async def _migrate_bot_llm_usage(conn) -> None:
    """V2.3: ``bot_llm_usage`` — per-user daily counter for LLM calls.

    Used by :mod:`web.telegram.cash_parser` to cap how many times the
    smart cash-entry fallback hits OpenAI per user per day. Without a
    cap a user with broken keyboard mashing could rack up real cost
    (gpt-4o-mini is cheap but not free). Default cap is 30/day; the
    quota resets at UTC midnight.

    Composite primary key on (user_id, day) lets us upsert atomically
    via ``ON CONFLICT``. Days older than ~30 are pruned by the daily
    log-prune job alongside ``bot_activity_log`` for storage hygiene.
    """
    await _ddl(
        conn,
        """
        CREATE TABLE IF NOT EXISTS bot_llm_usage (
            user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            day        DATE    NOT NULL,
            calls      INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (user_id, day)
        )
        """,
    )


async def _migrate_notifications_queue_not_before(conn) -> None:
    """V2.3 hot-fix: ``notifications_queue.not_before`` so the dispatcher
    can honour Telegram ``RetryAfter`` (HTTP 429) without losing the
    enqueued row.

    Pre-fix: a 429 was caught by the dispatcher's broad ``except`` and the
    row was marked ``failed``. The next tick re-enqueued nothing (failed
    row), so the brief silently went missing. Post-fix: ``RetryAfter``
    leaves the row pending, stamps ``not_before = now + retry_seconds``,
    and the queue selector's pending filter excludes rows whose embargo
    hasn't lifted.
    """
    await _ddl(
        conn,
        "ALTER TABLE notifications_queue ADD COLUMN IF NOT EXISTS not_before TIMESTAMPTZ",
    )


async def _migrate_recurring_price_snapshots_alerted(conn) -> None:
    """V2.3 hot-fix: ``recurring_price_snapshots.alerted_at`` — per-snapshot
    "we already told the user about this price change" stamp.

    The bug it fixes: ``detect_subscription_changes`` decided a stream had
    a price change purely by comparing the two latest snapshots
    (``history[0] != history[1]``). ``record_recurring_amount`` is a no-op
    when the amount is unchanged, so once Plaid reports a new price the
    history freezes at ``[new, old]`` forever. The producer re-detected
    "price changed!" on every run, and the 24h ``notifications_queue``
    dedup expired every night — so the *same* "Con Edison $133.66 →
    $134.57" line shipped in the morning brief every single day.

    The first-detection path was already protected by
    ``recurring_streams.subscription_alerted_at``; this is the matching
    stamp for the price-change path, but at *snapshot* granularity so a
    genuinely new price change (new snapshot row) still alerts exactly
    once.

    Backfill: every existing snapshot is stamped ``alerted_at = NOW()``.
    Anything already in the table predates this migration, so the user
    has either already seen the alert or it's stale — either way, do not
    re-alert. The next genuine price change inserts a fresh, un-stamped
    snapshot and alerts normally.
    """
    await _ddl(
        conn,
        "ALTER TABLE recurring_price_snapshots "
        "ADD COLUMN IF NOT EXISTS alerted_at TIMESTAMPTZ",
    )
    await conn.execute(
        "UPDATE recurring_price_snapshots SET alerted_at = NOW() "
        "WHERE alerted_at IS NULL"
    )


async def _migrate_couple_settings_last_brief_sent(conn) -> None:
    """V2.3: add ``couple_settings.last_brief_sent_date`` so the dispatcher can
    de-dup the morning/Sunday brief within a single local day.

    The dispatcher fires once a minute and the brief window is 15 minutes
    wide. On weekdays the early-return guard in ``_drain_user`` (no pending
    rows ⇒ skip) makes the loop self-stopping after the first send. On
    Sunday that guard is bypassed (the Sunday brief always carries the
    streak summary + audit invite even with zero queue items), so without
    a per-day sentinel the same brief was being delivered every minute
    until the window closed.

    Backfill leaves the column NULL — the very next dispatcher tick after
    deploy will send today's brief if it's due, then stamp the date and
    skip subsequent ticks.
    """
    await _ddl(
        conn,
        "ALTER TABLE couple_settings ADD COLUMN IF NOT EXISTS last_brief_sent_date DATE",
    )


async def run_bot_migrations(pool) -> None:
    """Idempotent migration entry point — called from main.py startup."""
    logger.info("Running bot v1 migrations…")
    async with pool.acquire() as conn:
        for stmt in ALL_STATEMENTS:
            try:
                await _ddl(conn, stmt)
            except Exception as exc:
                logger.error(
                    "Bot migration failed: %s\nSQL: %s", exc, stmt.strip()[:160]
                )
                raise
        await _migrate_merchant_seen_by_key(conn)
        await _migrate_couple_settings_last_brief_sent(conn)
        await _migrate_telegram_seen_updates(conn)
        await _migrate_users_telegram_blocked(conn)
        await _migrate_notifications_queue_not_before(conn)
        await _migrate_bot_llm_usage(conn)
        await _migrate_recurring_price_snapshots_alerted(conn)
    logger.info("Bot v1 migrations complete.")
