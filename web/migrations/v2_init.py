"""
V2 database migration — creates all new tables for the Plaid-first rewrite.
All statements use CREATE TABLE IF NOT EXISTS so this is idempotent and safe to run on startup.
"""
import logging
import os

logger = logging.getLogger(__name__)

# Startup DDL can wait on locks (e.g. overlapping uvicorn --reload); pool default is 30s.
_DDL_TIMEOUT = float(os.getenv("V2_DDL_TIMEOUT", "120"))


async def _ddl(conn, query: str) -> str:
    return await conn.execute(query, timeout=_DDL_TIMEOUT)

# ---------------------------------------------------------------------------
# DDL statements
# ---------------------------------------------------------------------------

CREATE_ACCOUNTS = """
CREATE TABLE IF NOT EXISTS accounts (
    id                           SERIAL PRIMARY KEY,
    plaid_account_id             TEXT UNIQUE,
    plaid_item_id                TEXT REFERENCES plaid_items(item_id) ON DELETE SET NULL,
    name                         TEXT NOT NULL,
    official_name                TEXT,
    mask                         TEXT,
    type                         TEXT NOT NULL,
    subtype                      TEXT,
    current_balance_cents        BIGINT DEFAULT 0,
    available_balance_cents      BIGINT,
    credit_limit_cents           BIGINT,
    credit_limit_cents_manual    BIGINT,
    apr_percent                  NUMERIC(6,3),
    apr_percent_manual           NUMERIC(6,3),
    plaid_missing_fields         JSONB,
    min_payment_cents            BIGINT,
    due_day                      SMALLINT,
    is_overdue                   BOOLEAN,
    last_payment_date            DATE,
    last_statement_balance_cents BIGINT,
    expected_payoff_date         DATE,
    ytd_interest_paid_cents      BIGINT,
    currency                     TEXT DEFAULT 'USD',
    holder_category              TEXT,
    is_active                    BOOLEAN DEFAULT TRUE,
    last_synced_at               TIMESTAMPTZ,
    created_at                   TIMESTAMPTZ DEFAULT NOW(),
    updated_at                   TIMESTAMPTZ DEFAULT NOW()
)
"""

CREATE_CATEGORIES = """
CREATE TABLE IF NOT EXISTS categories (
    id                SERIAL PRIMARY KEY,
    name              TEXT UNIQUE NOT NULL,
    plaid_pfc_primary TEXT,
    plaid_pfc_detailed TEXT UNIQUE,
    color             TEXT DEFAULT '#3b82f6',
    icon              TEXT,
    pfc_icon_url      TEXT,
    source            TEXT NOT NULL DEFAULT 'custom',
    created_at        TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT categories_source_check CHECK (source IN ('plaid_pfc', 'custom'))
)
"""

CREATE_TRANSACTIONS = """
CREATE TABLE IF NOT EXISTS transactions (
    id                   SERIAL PRIMARY KEY,
    plaid_transaction_id TEXT UNIQUE,
    account_id           INTEGER NOT NULL REFERENCES accounts(id),
    category_id          INTEGER REFERENCES categories(id),
    amount_cents         BIGINT NOT NULL,
    currency             TEXT DEFAULT 'USD',
    date                 DATE NOT NULL,
    authorized_date      DATE,
    datetime             TIMESTAMPTZ,
    authorized_datetime  TIMESTAMPTZ,
    name                 TEXT NOT NULL,
    merchant_name        TEXT,
    merchant_entity_id   TEXT,
    logo_url             TEXT,
    website              TEXT,
    payment_channel      TEXT,
    pfc_primary          TEXT,
    pfc_detailed         TEXT,
    pfc_confidence       TEXT,
    pfc_icon_url         TEXT,
    counterparties       JSONB,
    location             JSONB,
    payment_meta         JSONB,
    is_pending           BOOLEAN DEFAULT FALSE,
    source               TEXT DEFAULT 'manual',
    user_note            TEXT,
    created_at           TIMESTAMPTZ DEFAULT NOW(),
    updated_at           TIMESTAMPTZ DEFAULT NOW()
)
"""

CREATE_TAGS = """
CREATE TABLE IF NOT EXISTS tags (
    id         SERIAL PRIMARY KEY,
    name       TEXT UNIQUE NOT NULL,
    color      TEXT DEFAULT '#8b5cf6',
    created_at TIMESTAMPTZ DEFAULT NOW()
)
"""

CREATE_TRANSACTION_TAGS = """
CREATE TABLE IF NOT EXISTS transaction_tags (
    transaction_id INTEGER NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
    tag_id         INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (transaction_id, tag_id)
)
"""

CREATE_RECURRING_STREAMS = """
CREATE TABLE IF NOT EXISTS recurring_streams (
    id                          SERIAL PRIMARY KEY,
    plaid_stream_id             TEXT UNIQUE NOT NULL,
    account_id                  INTEGER REFERENCES accounts(id),
    direction                   TEXT NOT NULL,
    description                 TEXT NOT NULL,
    merchant_name               TEXT,
    frequency                   TEXT,
    average_amount_cents        BIGINT,
    last_amount_cents           BIGINT,
    currency                    TEXT DEFAULT 'USD',
    pfc_primary                 TEXT,
    pfc_detailed                TEXT,
    first_date                  DATE,
    last_date                   DATE,
    is_active                   BOOLEAN DEFAULT TRUE,
    status                      TEXT,
    category_id                 INTEGER REFERENCES categories(id),
    user_label                  TEXT,
    price_change_pct            NUMERIC(6,2),
    last_synced_at              TIMESTAMPTZ DEFAULT NOW(),
    user_status                 TEXT NOT NULL DEFAULT 'active'
        CHECK (user_status IN ('active', 'paused', 'cancelled')),
    paused_until                DATE,
    cancelled_at                TIMESTAMPTZ,
    price_change_snoozed_until  DATE
)
"""

CREATE_SECURITIES = """
CREATE TABLE IF NOT EXISTS securities (
    id                 SERIAL PRIMARY KEY,
    plaid_security_id  TEXT UNIQUE NOT NULL,
    name               TEXT,
    ticker_symbol      TEXT,
    type               TEXT,
    subtype            TEXT,
    close_price        NUMERIC(12,4),
    close_price_as_of  DATE,
    sector             TEXT,
    industry           TEXT,
    currency           TEXT DEFAULT 'USD',
    updated_at         TIMESTAMPTZ DEFAULT NOW()
)
"""

CREATE_INVESTMENT_HOLDINGS = """
CREATE TABLE IF NOT EXISTS investment_holdings (
    id                      SERIAL PRIMARY KEY,
    account_id              INTEGER NOT NULL REFERENCES accounts(id),
    security_id             TEXT NOT NULL REFERENCES securities(plaid_security_id),
    quantity                NUMERIC(15,6) NOT NULL,
    institution_price       NUMERIC(12,4),
    institution_value_cents BIGINT,
    cost_basis_cents        BIGINT,
    currency                TEXT DEFAULT 'USD',
    last_synced_at          TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (account_id, security_id)
)
"""

CREATE_CATEGORY_BUDGETS = """
CREATE TABLE IF NOT EXISTS category_budgets (
    id           SERIAL PRIMARY KEY,
    category_id  INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    month        TEXT NOT NULL,
    budget_cents BIGINT NOT NULL,
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (category_id, month)
)
"""

CREATE_TRANSACTION_SPLITS = """
CREATE TABLE IF NOT EXISTS transaction_splits (
    id                    SERIAL PRIMARY KEY,
    parent_transaction_id INTEGER NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
    category_id           INTEGER REFERENCES categories(id),
    tag_id                INTEGER REFERENCES tags(id),
    amount_cents          BIGINT NOT NULL,
    note                  TEXT,
    created_at            TIMESTAMPTZ DEFAULT NOW()
)
"""

CREATE_APP_SETTINGS = """
CREATE TABLE IF NOT EXISTS app_settings (
    id                    SMALLINT PRIMARY KEY DEFAULT 1,
    autosync_frequency    VARCHAR(16) NOT NULL DEFAULT 'daily',
    autosync_hour_utc     SMALLINT NOT NULL DEFAULT 3,
    autosync_minute_utc   SMALLINT NOT NULL DEFAULT 0,
    webhooks_enabled      BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by            INTEGER REFERENCES users(id) ON DELETE SET NULL,
    CONSTRAINT app_settings_singleton_chk CHECK (id = 1),
    CONSTRAINT app_settings_hour_chk CHECK (autosync_hour_utc BETWEEN 0 AND 23),
    CONSTRAINT app_settings_minute_chk CHECK (autosync_minute_utc BETWEEN 0 AND 59),
    CONSTRAINT app_settings_frequency_chk
        CHECK (autosync_frequency IN ('off','daily','weekly','semimonthly','monthly'))
)
"""

ALTER_APP_SETTINGS_WEBHOOKS = (
    "ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS webhooks_enabled BOOLEAN NOT NULL DEFAULT TRUE"
)

# --- autosync frequency migration (idempotent) -----------------------------
# V2.1 replaced the boolean ``autosync_enabled`` with an enum-ish
# ``autosync_frequency``. The steps below are safe on:
#   • a brand-new DB (new column created above by CREATE TABLE) — all become no-ops;
#   • an older DB where only ``autosync_enabled`` exists — we add the new column,
#     backfill from the old one, then drop the old column.
# Statements are split so the idempotency-by-IF-NOT-EXISTS mechanic holds
# regardless of which state we're in.
ALTER_APP_SETTINGS_FREQUENCY = (
    "ALTER TABLE app_settings "
    "ADD COLUMN IF NOT EXISTS autosync_frequency VARCHAR(16) NOT NULL DEFAULT 'daily'"
)

# Backfill once, only when the legacy column still exists. Wrapped in a DO
# block so a fresh DB (no ``autosync_enabled`` column) skips the UPDATE
# without an error.
BACKFILL_APP_SETTINGS_FREQUENCY = """
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'app_settings' AND column_name = 'autosync_enabled'
    ) THEN
        EXECUTE
            'UPDATE app_settings '
            'SET autosync_frequency = CASE '
            '    WHEN autosync_enabled = FALSE THEN ''off'' '
            '    ELSE COALESCE(NULLIF(autosync_frequency, ''''), ''daily'') '
            'END';
    END IF;
END
$$;
"""

DROP_APP_SETTINGS_ENABLED = "ALTER TABLE app_settings DROP COLUMN IF EXISTS autosync_enabled"

# Add the check constraint only if missing (older DBs upgraded in place).
ADD_APP_SETTINGS_FREQUENCY_CHK = """
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'app_settings_frequency_chk'
    ) THEN
        ALTER TABLE app_settings
            ADD CONSTRAINT app_settings_frequency_chk
            CHECK (autosync_frequency IN ('off','daily','weekly','semimonthly','monthly'));
    END IF;
END
$$;
"""

SEED_APP_SETTINGS = """
INSERT INTO app_settings (id, autosync_frequency, autosync_hour_utc, autosync_minute_utc)
VALUES (1, 'daily', 3, 0)
ON CONFLICT (id) DO NOTHING
"""

CREATE_AUDIT_LOG = """
CREATE TABLE IF NOT EXISTS audit_log (
    id              BIGSERIAL PRIMARY KEY,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    actor_user_id   INTEGER REFERENCES users(id) ON DELETE SET NULL,
    actor_username  TEXT,
    event_type      TEXT NOT NULL,
    source          TEXT NOT NULL DEFAULT 'manual',
    target_kind     TEXT,
    target_id       TEXT,
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
    request_ip      INET,
    CONSTRAINT audit_log_source_chk CHECK (source IN ('manual', 'scheduler', 'webhook', 'system'))
)
"""

CREATE_NET_WORTH_SNAPSHOTS = """
CREATE TABLE IF NOT EXISTS net_worth_snapshots (
    id               SERIAL PRIMARY KEY,
    snapshot_date    DATE UNIQUE NOT NULL,
    liquid_cents     BIGINT NOT NULL DEFAULT 0,
    investment_cents BIGINT NOT NULL DEFAULT 0,
    debt_cents       BIGINT NOT NULL DEFAULT 0,
    net_worth_cents  BIGINT NOT NULL,
    created_at       TIMESTAMPTZ DEFAULT NOW()
)
"""

# Indexes for performance
CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_accounts_plaid_id ON accounts(plaid_account_id)",
    "CREATE INDEX IF NOT EXISTS idx_accounts_type ON accounts(type)",
    "CREATE INDEX IF NOT EXISTS idx_transactions_account ON transactions(account_id)",
    "CREATE INDEX IF NOT EXISTS idx_transactions_category ON transactions(category_id)",
    "CREATE INDEX IF NOT EXISTS idx_transactions_date ON transactions(date DESC)",
    "CREATE INDEX IF NOT EXISTS idx_transactions_authorized_date ON transactions(authorized_date DESC)",
    "CREATE INDEX IF NOT EXISTS idx_transactions_plaid_id ON transactions(plaid_transaction_id)",
    "CREATE INDEX IF NOT EXISTS idx_transactions_source ON transactions(source)",
    "CREATE INDEX IF NOT EXISTS idx_transactions_pending ON transactions(is_pending)",
    "CREATE INDEX IF NOT EXISTS idx_recurring_account ON recurring_streams(account_id)",
    "CREATE INDEX IF NOT EXISTS idx_recurring_active ON recurring_streams(is_active)",
    "CREATE INDEX IF NOT EXISTS idx_category_budgets_month ON category_budgets(month)",
    "CREATE INDEX IF NOT EXISTS idx_net_worth_date ON net_worth_snapshots(snapshot_date DESC)",
    "CREATE INDEX IF NOT EXISTS idx_transaction_splits_parent ON transaction_splits(parent_transaction_id)",
]

# Full-text trigram indexes for ILIKE search on transactions.
# Requires pg_trgm extension (available on all standard PostgreSQL installations).
CREATE_TRGM_INDEXES = [
    "CREATE EXTENSION IF NOT EXISTS pg_trgm",
    "CREATE INDEX IF NOT EXISTS idx_transactions_merchant_trgm ON transactions USING gin(merchant_name gin_trgm_ops)",
    "CREATE INDEX IF NOT EXISTS idx_transactions_name_trgm ON transactions USING gin(name gin_trgm_ops)",
]

# Additive columns for existing tables — idempotent, safe to run on every startup.
PLAID_ITEMS_COLUMNS = [
    "ALTER TABLE plaid_items ADD COLUMN IF NOT EXISTS institution_logo TEXT",
    "ALTER TABLE plaid_items ADD COLUMN IF NOT EXISTS institution_color VARCHAR(7)",
    "ALTER TABLE plaid_items ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id) ON DELETE SET NULL",
]

ACCOUNTS_COLUMNS = [
    "ALTER TABLE accounts ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id) ON DELETE SET NULL",
]

TRANSACTIONS_COLUMNS = [
    "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS is_private BOOLEAN NOT NULL DEFAULT FALSE",
    "CREATE INDEX IF NOT EXISTS idx_transactions_is_private ON transactions(is_private) WHERE is_private = TRUE",
    "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS display_title TEXT",
    "CREATE INDEX IF NOT EXISTS idx_transactions_display_title_lower ON transactions(lower(display_title))",
    # Plaid links a newly-posted transaction back to its pending twin via
    # `pending_transaction_id`. We store it so the sync loop can copy user-set
    # flags (is_private, user_note) from the pending row before it is removed.
    "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS pending_transaction_id TEXT",
    "CREATE INDEX IF NOT EXISTS idx_transactions_pending_transaction_id ON transactions(pending_transaction_id) WHERE pending_transaction_id IS NOT NULL",
    # Internal-transfer flag: TRUE when the transaction is a payment between
    # family members (e.g. Zelle spouse-to-spouse). Excluded from every
    # income/expense aggregate so the same dollar isn't counted twice.
    # `_manual` is TRUE when the user set the flag explicitly — the auto
    # re-classifier never overrides a manual setting.
    "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS is_internal_transfer BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS is_internal_transfer_manual BOOLEAN NOT NULL DEFAULT FALSE",
    "CREATE INDEX IF NOT EXISTS idx_transactions_is_internal_transfer ON transactions(is_internal_transfer) WHERE is_internal_transfer = TRUE",
]

APP_SETTINGS_INTERNAL_TRANSFER_COLUMN = (
    # TEXT[] so we can store a flat list of counterparty names (e.g. "ANASTASIIA STOLPOVSKAIA")
    # that should be treated as internal transfers when they appear on a
    # TRANSFER_IN/TRANSFER_OUT transaction. Family-wide setting; one list per family.
    "ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS internal_transfer_names TEXT[] NOT NULL DEFAULT '{}'::TEXT[]"
)

# Auto-prune toggles for the two log surfaces. Both default to keeping a
# rolling 7-day window when ON; OFF means the daily prune skips that table
# (manual clear still works). Stored as separate columns so the user can
# turn one on and the other off independently — debugging the bot can
# benefit from a tighter window than the security audit log, where the
# default is to keep history forever.
APP_SETTINGS_LOG_PRUNE_COLUMNS = [
    (
        "ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS "
        "bot_activity_auto_prune_enabled BOOLEAN NOT NULL DEFAULT TRUE"
    ),
    (
        "ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS "
        "audit_log_auto_prune_enabled BOOLEAN NOT NULL DEFAULT FALSE"
    ),
]

AUDIT_LOG_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_audit_log_created_at ON audit_log(created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_audit_log_event_type ON audit_log(event_type, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_audit_log_actor ON audit_log(actor_user_id, created_at DESC)",
]

ALL_STATEMENTS = [
    CREATE_ACCOUNTS,
    CREATE_CATEGORIES,
    CREATE_TRANSACTIONS,
    CREATE_TAGS,
    CREATE_TRANSACTION_TAGS,
    CREATE_RECURRING_STREAMS,
    CREATE_SECURITIES,
    CREATE_INVESTMENT_HOLDINGS,
    CREATE_CATEGORY_BUDGETS,
    CREATE_TRANSACTION_SPLITS,
    CREATE_NET_WORTH_SNAPSHOTS,
    CREATE_APP_SETTINGS,
    ALTER_APP_SETTINGS_WEBHOOKS,
    ALTER_APP_SETTINGS_FREQUENCY,
    APP_SETTINGS_INTERNAL_TRANSFER_COLUMN,
    *APP_SETTINGS_LOG_PRUNE_COLUMNS,
    BACKFILL_APP_SETTINGS_FREQUENCY,
    DROP_APP_SETTINGS_ENABLED,
    ADD_APP_SETTINGS_FREQUENCY_CHK,
    SEED_APP_SETTINGS,
    CREATE_AUDIT_LOG,
    *AUDIT_LOG_INDEXES,
    *CREATE_INDEXES,
    *CREATE_TRGM_INDEXES,
    *PLAID_ITEMS_COLUMNS,
    *ACCOUNTS_COLUMNS,
    *TRANSACTIONS_COLUMNS,
]


async def _migrate_categories_source(conn) -> None:
    """
    Add categories.source (plaid_pfc | custom), backfill, remove legacy is_system seed rows.
    Idempotent for repeated startup. Runs inside a transaction so partial failures are safe.
    """
    async with conn.transaction():
        flags = await conn.fetchrow(
            """
            SELECT
                EXISTS(
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = 'categories' AND column_name = 'is_system'
                ) AS has_is_system,
                EXISTS(
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = 'categories' AND column_name = 'source'
                ) AS has_source
            """
        )
        if not flags["has_source"]:
            await _ddl(conn, "ALTER TABLE categories ADD COLUMN source TEXT")

        if flags["has_is_system"]:
            await _ddl(conn,
                """
                UPDATE categories SET source = 'plaid_pfc'
                WHERE is_system = FALSE
                  AND (plaid_pfc_detailed IS NOT NULL OR plaid_pfc_primary IS NOT NULL)
                """
            )
            await _ddl(conn,
                """
                UPDATE categories SET source = 'custom'
                WHERE is_system = FALSE AND source IS NULL
                """
            )
            await _ddl(conn,
                """
                UPDATE transactions SET category_id = NULL
                WHERE category_id IN (SELECT id FROM categories WHERE is_system = TRUE)
                """
            )
            await _ddl(conn,
                """
                UPDATE recurring_streams SET category_id = NULL
                WHERE category_id IN (SELECT id FROM categories WHERE is_system = TRUE)
                """
            )
            await _ddl(conn,
                """
                UPDATE transaction_splits SET category_id = NULL
                WHERE category_id IN (SELECT id FROM categories WHERE is_system = TRUE)
                """
            )
            await _ddl(conn, "DELETE FROM categories WHERE is_system = TRUE")
            await _ddl(conn, "ALTER TABLE categories DROP COLUMN is_system")
        else:
            await _ddl(conn,
                """
                UPDATE categories SET source = 'plaid_pfc'
                WHERE source IS NULL
                  AND (plaid_pfc_detailed IS NOT NULL OR plaid_pfc_primary IS NOT NULL)
                """
            )
            await _ddl(conn, "UPDATE categories SET source = 'custom' WHERE source IS NULL")

        await _ddl(conn, "ALTER TABLE categories ALTER COLUMN source SET DEFAULT 'custom'")
        await _ddl(conn, "UPDATE categories SET source = 'custom' WHERE source IS NULL OR source = ''")
        await _ddl(conn, "ALTER TABLE categories ALTER COLUMN source SET NOT NULL")

        chk = await conn.fetchval(
            "SELECT 1 FROM pg_constraint WHERE conname = 'categories_source_check'"
        )
        if not chk:
            await _ddl(conn,
                """
                ALTER TABLE categories ADD CONSTRAINT categories_source_check
                CHECK (source IN ('plaid_pfc', 'custom'))
                """
            )


async def _migrate_v21_addons(conn) -> None:
    """Additive V2.1 columns and tables (idempotent)."""
    await _ddl(conn,
        "ALTER TABLE recurring_streams ADD COLUMN IF NOT EXISTS stream_source TEXT NOT NULL DEFAULT 'plaid'"
    )
    chk = await conn.fetchval(
        "SELECT 1 FROM pg_constraint WHERE conname = 'recurring_streams_stream_source_check'"
    )
    if not chk:
        await _ddl(conn,
            """
            ALTER TABLE recurring_streams ADD CONSTRAINT recurring_streams_stream_source_check
            CHECK (stream_source IN ('plaid', 'manual'))
            """
        )

    reg = await conn.fetchval("SELECT to_regclass('public.plaid_items')")
    if reg:
        for col in (
            "ALTER TABLE plaid_items ADD COLUMN IF NOT EXISTS item_login_required BOOLEAN NOT NULL DEFAULT FALSE",
            "ALTER TABLE plaid_items ADD COLUMN IF NOT EXISTS sync_updates_pending BOOLEAN NOT NULL DEFAULT FALSE",
            # Encryption-at-rest for Plaid access_tokens (see web/plaid/crypto.py).
            # Plain access_token is kept (NULL after backfill) for graceful rollout
            # before PLAID_ENCRYPTION_KEY is configured on Railway.
            "ALTER TABLE plaid_items ADD COLUMN IF NOT EXISTS access_token_encrypted BYTEA",
            "ALTER TABLE plaid_items ALTER COLUMN access_token DROP NOT NULL",
        ):
            try:
                await _ddl(conn, col)
            except Exception:
                # IF NOT EXISTS should make this idempotent. A failure here
                # signals a real schema mismatch (e.g. column exists with a
                # different type) — log so it's not silently swallowed.
                logger.warning("plaid_items column upgrade failed: %s", col, exc_info=True)

    await _ddl(conn,
        """
        CREATE TABLE IF NOT EXISTS plaid_webhook_events (
            webhook_id TEXT PRIMARY KEY,
            received_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )

    await _ddl(conn,
        """
        CREATE TABLE IF NOT EXISTS merchant_category_rules (
            id SERIAL PRIMARY KEY,
            merchant_key TEXT NOT NULL,
            category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (merchant_key)
        )
        """
    )

    await _ddl(conn,
        """
        CREATE TABLE IF NOT EXISTS user_preferences (
            user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            insights_last_viewed_at TIMESTAMPTZ,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )


async def _migrate_accounts_manual_and_missing(conn) -> None:
    """
    Additive V2.1 columns for accounts:

    * ``credit_limit_cents_manual``, ``apr_percent_manual`` — user-entered
      fallback values used only when Plaid does not expose them for the
      institution (Capital One is the canonical case). Effective value in
      the API is ``COALESCE(plaid, manual)`` — Plaid always wins if it
      starts reporting.
    * ``plaid_missing_fields`` — cached set of fields Plaid did not provide
      on the last sync (``["apr", "credit_limit"]`` etc.). Used by the
      change-detector so we only write an audit entry when the set
      transitions, not on every sync.

    All changes are idempotent and safe to run many times.
    """
    for stmt in (
        "ALTER TABLE accounts ADD COLUMN IF NOT EXISTS credit_limit_cents_manual BIGINT",
        "ALTER TABLE accounts ADD COLUMN IF NOT EXISTS apr_percent_manual NUMERIC(6,3)",
        "ALTER TABLE accounts ADD COLUMN IF NOT EXISTS plaid_missing_fields JSONB",
    ):
        try:
            await _ddl(conn, stmt)
        except Exception as exc:
            logger.warning("Account addon column failed (continuing): %s", exc)


async def _migrate_categories_parent_id(conn) -> None:
    """
    Add categories.parent_id (self-FK) + index, then idempotently backfill a
    primary-only row for every distinct plaid_pfc_primary and link each detailed
    PFC row to its primary parent. Safe to run multiple times.

    Invariant: depth ≤ 2. Primary rows have parent_id IS NULL; detail rows
    reference their primary parent.
    """
    from web.categories.pfc_display import PFC_PRIMARY_LABELS

    async with conn.transaction():
        await _ddl(
            conn,
            "ALTER TABLE categories ADD COLUMN IF NOT EXISTS parent_id INTEGER REFERENCES categories(id) ON DELETE SET NULL",
        )
        await _ddl(
            conn,
            "CREATE INDEX IF NOT EXISTS idx_categories_parent_id ON categories(parent_id)",
        )

        # CHECK: a row cannot be its own parent. Depth-2 invariant is enforced
        # in `resolve_category`; a SQL-level trigger is overkill for that.
        chk = await conn.fetchval(
            "SELECT 1 FROM pg_constraint WHERE conname = 'categories_parent_not_self_chk'"
        )
        if not chk:
            try:
                await _ddl(
                    conn,
                    "ALTER TABLE categories ADD CONSTRAINT categories_parent_not_self_chk CHECK (parent_id IS NULL OR parent_id <> id)",
                )
            except Exception as exc:
                logger.warning("categories parent self-ref check skipped: %s", exc)

        # 1. Upsert a primary-only category row for every known PFC primary.
        #    A row is considered a primary-parent if plaid_pfc_primary matches
        #    and plaid_pfc_detailed IS NULL. Reuse it if it already exists;
        #    otherwise insert with the human-readable name.
        #    We never overwrite custom-sourced rows that happen to share a name.
        for primary_code, label in PFC_PRIMARY_LABELS.items():
            existing = await conn.fetchval(
                """
                SELECT id FROM categories
                WHERE plaid_pfc_primary = $1 AND plaid_pfc_detailed IS NULL
                ORDER BY CASE WHEN source = 'plaid_pfc' THEN 0 ELSE 1 END, id
                LIMIT 1
                """,
                primary_code,
            )
            if existing:
                continue
            # No primary-only row yet — insert one. If `name` collides with a
            # custom row we just skip (DO NOTHING); the child rows will still
            # work but roll-up will fall back to self.
            await conn.execute(
                """
                INSERT INTO categories (name, plaid_pfc_primary, plaid_pfc_detailed, source)
                VALUES ($1, $2, NULL, 'plaid_pfc')
                ON CONFLICT (name) DO NOTHING
                """,
                label,
                primary_code,
            )

        # 2. Link every detailed Plaid row to its primary parent. Idempotent.
        await _ddl(
            conn,
            """
            UPDATE categories AS c
            SET parent_id = p.id
            FROM categories p
            WHERE c.plaid_pfc_primary IS NOT NULL
              AND c.plaid_pfc_detailed IS NOT NULL
              AND p.plaid_pfc_primary = c.plaid_pfc_primary
              AND p.plaid_pfc_detailed IS NULL
              AND p.source = 'plaid_pfc'
              AND c.id <> p.id
              AND (c.parent_id IS DISTINCT FROM p.id)
            """,
        )

async def _migrate_recurring_price_change_signed(conn) -> None:
    """
    One-shot backfill to rewrite `recurring_streams.price_change_pct` as a
    **signed** percentage: positive = last > avg (got more expensive), negative
    = cheaper. Historically the column stored ABS(), losing direction.

    Idempotent: re-applying produces the same result for each row.
    """
    await _ddl(
        conn,
        """
        UPDATE recurring_streams
        SET price_change_pct = ROUND(
            (last_amount_cents - average_amount_cents)::numeric
            / NULLIF(ABS(average_amount_cents), 0) * 100,
            2
        )
        WHERE last_amount_cents IS NOT NULL
          AND average_amount_cents IS NOT NULL
          AND average_amount_cents <> 0
        """,
    )


async def _migrate_merchant_aliases(conn) -> None:
    """V2.3: per-merchant display rename (Plaid alias).

    Family-global lookup table keyed by ``merchant_key`` (same algorithm as
    ``merchant_category_rules``, see ``web/merchant_rules/keys.py``). Read paths
    LEFT JOIN this table and ``COALESCE(alias.display_name, t.display_title)``
    so the alias overrides the auto-normalized merchant title in **display
    only** — categorization, merchant_key matching, math, and Plaid sync are
    untouched. Idempotent.

    Two example rows for context:

        merchant_key                    | display_name
        --------------------------------+-------------
        eid:6mnxz3jp3wp4j4yze4kx4vl9p   | Rent
        name:nyflower                   | Rent
    """
    await _ddl(
        conn,
        """
        CREATE TABLE IF NOT EXISTS merchant_aliases (
            merchant_key  TEXT PRIMARY KEY,
            display_name  TEXT NOT NULL CHECK (length(trim(display_name)) > 0),
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
    )


async def _migrate_merchant_logos(conn) -> None:
    """V2.5: Brandfetch-sourced cache of merchant logos.

    Plaid populates ``transactions.logo_url`` for ~57% of named merchants
    (the licensed brand set). The remaining ~43% — local businesses,
    niche subscriptions, sketchy bank descriptors — show up with NULL
    logos. Brandfetch's free Brand Search covers most of the recognizable
    long tail (DoorDash, Affirm, Revolut, Con Edison ...); the truly
    local merchants (NYC bodegas, smoke shops) stay on our gradient
    avatars.

    Joined onto ``transactions`` and ``recurring_streams`` at read time
    rather than backfilled onto ``transactions.logo_url`` so a single
    enrichment lookup fixes every past and future row of the same
    merchant in one shot. The COALESCE in those queries always prefers
    Plaid's own logo when it exists (Plaid licenses higher-quality
    asset sets than Brandfetch for the brands it covers).

    Schema notes:

    * ``merchant_name`` is the natural key — Plaid keeps it stable per
      merchant_entity_id, and we never look up without it.
    * ``logo_url`` may be NULL when we looked but found no hit. The
      presence of the row (with NULL logo + status='no_hit') is the
      "don't bother re-checking for a while" marker.
    * ``status`` makes the no-hit cases inspectable from the audit log.
    * ``miss_count`` + ``refreshed_at`` drive exponential backoff so
      we don't burn the rate budget on the same dead lookups every
      sync. Resolved rows are never re-checked.

    All additive + idempotent.
    """
    await _ddl(
        conn,
        """
        CREATE TABLE IF NOT EXISTS merchant_logos (
            merchant_name   TEXT PRIMARY KEY,
            logo_url        TEXT,
            brand_domain    TEXT,
            quality_score   REAL,
            status          TEXT NOT NULL DEFAULT 'no_hit'
                CHECK (status IN ('resolved', 'no_hit', 'low_quality')),
            miss_count      INTEGER NOT NULL DEFAULT 0,
            refreshed_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
    )
    # Read-path JOINs match case-insensitively (Plaid's display titles
    # drift in casing for the same merchant), so back the LOWER() lookup
    # with a functional index. Cheap — the table is small, but keeps the
    # scalar subquery off a seq-scan-per-row plan as it grows.
    await _ddl(
        conn,
        "CREATE INDEX IF NOT EXISTS idx_merchant_logos_lower_name "
        "ON merchant_logos (LOWER(merchant_name))",
    )


async def _migrate_merchant_aliases_website(conn) -> None:
    """V2.5.x: per-merchant user-provided website URL.

    Backs the "I know the website for this merchant" UX in the rename-
    merchant popover. When set, the backend resolves logo candidates
    (Brandfetch + faviconextractor + Google s2/favicons) and the user
    picks one — the chosen URL lands in ``merchant_logos`` with
    ``status='user_curated'``.

    Stored alongside ``display_name`` rather than in its own table
    because they're the same UX concept: "the user knows better than
    Plaid/Brandfetch for this merchant". One row per merchant_key,
    either column nullable so the user can set just one.

    Idempotent. Pure ALTER, no data movement.
    """
    await _ddl(
        conn,
        "ALTER TABLE merchant_aliases "
        "ADD COLUMN IF NOT EXISTS website TEXT",
    )


async def _migrate_merchant_logos_user_curated(conn) -> None:
    """V2.5.x: extend ``merchant_logos.status`` to include ``user_curated``.

    The existing CHECK constraint accepted only Brandfetch-pipeline
    statuses (``resolved``, ``no_hit``, ``low_quality``). User-curated
    picks need their own status so the read-path can distinguish
    them (and so ``names_to_enrich`` can skip them — a user pick is
    sticky and never re-enriched by the auto pipeline).

    Drop + recreate the CHECK constraint with the wider set. Idempotent
    via the standard `IF EXISTS` / `IF NOT EXISTS` constraint guards.
    """
    # PostgreSQL doesn't have ALTER CONSTRAINT for CHECK redefinition,
    # so the dance is DROP + ADD with the new clause.
    await _ddl(
        conn,
        "ALTER TABLE merchant_logos "
        "DROP CONSTRAINT IF EXISTS merchant_logos_status_check",
    )
    await _ddl(
        conn,
        "ALTER TABLE merchant_logos "
        "ADD CONSTRAINT merchant_logos_status_check "
        "CHECK (status IN ('resolved', 'no_hit', 'low_quality', 'user_curated'))",
    )


async def _migrate_recurring_user_status(conn) -> None:
    """V2.3: user-managed lifecycle for recurring streams.

    Plaid's API can detect streams but cannot pause / cancel third-party
    subscriptions, so we keep the local state ourselves:

    * ``user_status`` — 'active' (default) | 'paused' | 'cancelled'.
      The Plaid upsert (``recurring/repo.py::upsert_streams``) deliberately
      does NOT touch this column on ON CONFLICT, so user choices survive
      every sync.
    * ``paused_until`` — optional auto-resume date (NULL = pause indefinitely).
    * ``cancelled_at`` — audit timestamp; set whenever ``user_status`` flips
      to 'cancelled'.
    * ``price_change_snoozed_until`` — hide the price-change alert (UI badge
      and Insights card) until this date.

    All columns are additive and idempotent.
    """
    for stmt in (
        "ALTER TABLE recurring_streams ADD COLUMN IF NOT EXISTS user_status TEXT NOT NULL DEFAULT 'active'",
        "ALTER TABLE recurring_streams ADD COLUMN IF NOT EXISTS paused_until DATE",
        "ALTER TABLE recurring_streams ADD COLUMN IF NOT EXISTS cancelled_at TIMESTAMPTZ",
        "ALTER TABLE recurring_streams ADD COLUMN IF NOT EXISTS price_change_snoozed_until DATE",
    ):
        await _ddl(conn, stmt)
    chk = await conn.fetchval(
        "SELECT 1 FROM pg_constraint WHERE conname = 'recurring_streams_user_status_check'"
    )
    if not chk:
        await _ddl(
            conn,
            """
            ALTER TABLE recurring_streams ADD CONSTRAINT recurring_streams_user_status_check
            CHECK (user_status IN ('active', 'paused', 'cancelled'))
            """,
        )


async def _migrate_recurring_unsubscribed_state(conn) -> None:
    """V2.3: ``unsubscribed`` lifecycle state for recurring streams.

    Difference from ``cancelled``: ``cancelled`` is a terminal user-declared
    state; ``unsubscribed`` is a *pending verification* state. The user says
    "I cancelled at the merchant" but we don't trust them yet — we wait one
    cadence + a grace period, then check whether Plaid still posts charges
    for the same merchant. The verifier (``web/recurring/verifier.py``) then
    flips the row to ``cancelled`` (no charge → confirmed) or fires a P0
    alert (charge came through → cancellation may not have gone through).

    Columns added:

    * ``unsubscribed_at`` — stamped when the user toggles into the
      ``unsubscribed`` state. The verifier uses this as the floor for
      "is the charge BEFORE or AFTER the unsubscribe action?"
    * ``unsubscribe_verify_after`` — the earliest moment the verifier is
      allowed to act. Computed as
      ``next_future_occurrence(last_date, frequency) + 7 days grace``
      so we tolerate Plaid lag + bank T+N settlement.
    * ``unsubscribed_charge_alerted_at`` — last time we fired the
      "you got charged after unsubscribing" alert. Prevents duplicate P0
      pushes when the user hasn't acted on the previous one.

    The CHECK constraint is rebuilt to add the ``unsubscribed`` value while
    keeping the existing ``active / paused / cancelled`` ones intact.
    """
    for stmt in (
        "ALTER TABLE recurring_streams ADD COLUMN IF NOT EXISTS unsubscribed_at TIMESTAMPTZ",
        "ALTER TABLE recurring_streams ADD COLUMN IF NOT EXISTS unsubscribe_verify_after TIMESTAMPTZ",
        "ALTER TABLE recurring_streams ADD COLUMN IF NOT EXISTS unsubscribed_charge_alerted_at TIMESTAMPTZ",
    ):
        await _ddl(conn, stmt)
    # Rebuild the user_status CHECK so 'unsubscribed' is allowed. We drop
    # whatever's there (the column has a defined-default fallback to
    # 'active', so no rows will be invalid against the new check) and
    # recreate with the wider set.
    await _ddl(
        conn,
        "ALTER TABLE recurring_streams DROP CONSTRAINT IF EXISTS recurring_streams_user_status_check",
    )
    await _ddl(
        conn,
        """
        ALTER TABLE recurring_streams ADD CONSTRAINT recurring_streams_user_status_check
        CHECK (user_status IN ('active', 'paused', 'cancelled', 'unsubscribed'))
        """,
    )
    # Index for the nightly verifier scan. Partial index keeps it tiny —
    # only the rows in 'unsubscribed' state appear, which is a small
    # fraction of recurring_streams.
    await _ddl(
        conn,
        """
        CREATE INDEX IF NOT EXISTS idx_recurring_streams_unsubscribe_verify
            ON recurring_streams(unsubscribe_verify_after)
         WHERE user_status = 'unsubscribed'
        """,
    )


async def _migrate_recurring_first_detected_alerted(conn) -> None:
    """V2.3: per-stream "we already alerted the user about this stream" stamp.

    Without this column the Morning Brief produced a "🆕 N new subscriptions"
    block every single day for streams whose price has never changed:

    * ``recurring_price_snapshots`` only inserts a row when the amount
      actually changes, so a stable stream has only ONE snapshot for its
      whole life.
    * ``detect_subscription_changes`` interprets ``len(history) < 2`` as
      "brand-new stream" and fires "🆕 new subscription detected".
    * The ``notifications_queue`` dedup window is 24h, so the same
      "new subscription" line fires every morning forever.

    The fix: stamp ``subscription_alerted_at`` the moment we first emit the
    "new subscription" notification, and refuse to emit it again if the stamp
    is set. Price-change alerts are unaffected (they use the snapshot
    history and a separate code path).

    The column is backfilled to NOW() for every existing stream on first
    apply so the next morning brief is silent rather than dumping the entire
    catalogue as "new".
    """
    await _ddl(
        conn,
        "ALTER TABLE recurring_streams ADD COLUMN IF NOT EXISTS subscription_alerted_at TIMESTAMPTZ",
    )
    # Backfill: anything older than ~10 minutes was already known to the
    # system at the time this migration runs, so mark it as already-alerted
    # to suppress the historical flood. Streams ingested in the last 10
    # minutes are likely from the Plaid sync that just kicked off; leave
    # them NULL so they get a one-shot "new" alert.
    await conn.execute(
        """
        UPDATE recurring_streams
           SET subscription_alerted_at = NOW()
         WHERE subscription_alerted_at IS NULL
           AND COALESCE(last_synced_at, NOW()) < NOW() - INTERVAL '10 minutes'
        """
    )


async def _migrate_merchant_rules_global_family(conn) -> None:
    """
    One global rule per merchant_key (family-wide). Legacy table had (user_id, merchant_key).

    On duplicate merchant_key across users, keep the row with max(id). Does not touch transactions.
    """
    reg = await conn.fetchval("SELECT to_regclass('public.merchant_category_rules')")
    if not reg:
        return
    has_user_id = await conn.fetchval(
        """
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'merchant_category_rules' AND column_name = 'user_id'
        """
    )
    if not has_user_id:
        # Table already family-global (new installs); UNIQUE(merchant_key) from CREATE.
        return

    # Dedupe rules only: keep max(id) per merchant_key (surviving row wins).
    await _ddl(
        conn,
        """
        DELETE FROM merchant_category_rules m
        WHERE EXISTS (
            SELECT 1 FROM merchant_category_rules m2
            WHERE m2.merchant_key = m.merchant_key AND m2.id > m.id
        )
        """,
    )

    # CASCADE drops FK and composite UNIQUE on (user_id, merchant_key).
    await _ddl(conn, "ALTER TABLE merchant_category_rules DROP COLUMN IF EXISTS user_id CASCADE")

    await _ddl(
        conn,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS merchant_category_rules_merchant_key_uidx
        ON merchant_category_rules (merchant_key)
        """,
    )


async def _migrate_merchant_rules_description_filter(conn) -> None:
    """Add ``description_contains`` to ``merchant_category_rules`` so a
    single rule can be narrowed to transactions whose description / name
    contains a substring (case-insensitive).

    Use case (see ``docs/categorization-precedence.md`` §3): a household
    pays rent via Zelle to one specific person while also using Zelle for
    other things. Without a description filter the only options were
    "categorize every Zelle as Rent" (wrong) or "manually re-tag every new
    Zelle to that person" (tedious). With ``description_contains = 'alla'``
    the rule fires only on rows whose ``name`` or ``display_title``
    matches.

    Schema notes:

    * Nullable. ``NULL`` preserves the legacy "match every transaction
      with this merchant_key" behavior — every existing rule keeps
      working unchanged.
    * Lowercased on write so the matcher can do a single ``LOWER(...) LIKE
      '%' || description_contains || '%'`` without per-row case folding.
    * The unique constraint moves from ``(merchant_key)`` to
      ``(merchant_key, COALESCE(description_contains, ''))`` so a user
      can have both a generic ``name:zelle → Transfer Out`` rule AND a
      narrow ``name:zelle + 'alla' → Rent`` rule for the same merchant.
      The ``COALESCE(..., '')`` makes ``NULL`` a normal value for index
      purposes (Postgres treats two NULLs as distinct otherwise).

    All changes are additive and idempotent.
    """
    reg = await conn.fetchval("SELECT to_regclass('public.merchant_category_rules')")
    if not reg:
        return

    # Add the column. Nullable so legacy rules keep working unchanged.
    await _ddl(
        conn,
        "ALTER TABLE merchant_category_rules ADD COLUMN IF NOT EXISTS description_contains TEXT",
    )

    # Drop the old single-column UNIQUE in favour of a composite that
    # treats NULL and '' as the same slot. Done in two steps so we never
    # hold both indexes on a busy production table at once.
    has_old_idx = await conn.fetchval(
        """
        SELECT 1 FROM pg_indexes
        WHERE schemaname = 'public'
          AND tablename = 'merchant_category_rules'
          AND indexname = 'merchant_category_rules_merchant_key_uidx'
        """
    )
    has_old_constraint = await conn.fetchval(
        """
        SELECT 1 FROM information_schema.table_constraints
        WHERE table_schema = 'public'
          AND table_name = 'merchant_category_rules'
          AND constraint_name = 'merchant_category_rules_merchant_key_key'
        """
    )

    await _ddl(
        conn,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS merchant_category_rules_key_filter_uidx
        ON merchant_category_rules (merchant_key, COALESCE(description_contains, ''))
        """,
    )

    if has_old_idx:
        await _ddl(
            conn,
            "DROP INDEX IF EXISTS merchant_category_rules_merchant_key_uidx",
        )
    if has_old_constraint:
        # The original CREATE TABLE used inline UNIQUE(merchant_key) which
        # Postgres surfaces as ``merchant_category_rules_merchant_key_key``.
        await _ddl(
            conn,
            "ALTER TABLE merchant_category_rules DROP CONSTRAINT IF EXISTS merchant_category_rules_merchant_key_key",
        )


async def _migrate_transactions_display_title_backfill(conn) -> None:
    """
    Populate `transactions.display_title` for rows where it is NULL by running
    `normalize_transaction_title` in Python (the SQL pipeline is too complex to
    reproduce reliably). Idempotent: already-filled rows are skipped; subsequent
    runs just top-up new NULLs.

    Batches of 1000 rows keep each transaction short to avoid long-lived locks.
    Loop bound (max 2000 batches = 2M rows) is a safety net, not a hard limit.
    """
    import json as _json

    from web.transactions.display import normalize_transaction_title

    def _parse_cp(value):
        if value is None or isinstance(value, list):
            return value
        if isinstance(value, str):
            try:
                return _json.loads(value)
            except Exception:
                return None
        return value

    for _ in range(2000):
        rows = await conn.fetch(
            """
            SELECT id, name, merchant_name, website, counterparties
            FROM transactions
            WHERE display_title IS NULL
            ORDER BY id
            LIMIT 1000
            """
        )
        if not rows:
            return
        updates: list[tuple[int, str]] = []
        for r in rows:
            # asyncpg decodes JSONB as str by default; counterparties stays Python-safe.
            txn = {
                "id": r["id"],
                "name": r["name"],
                "merchant_name": r["merchant_name"],
                "website": r["website"],
                "counterparties": _parse_cp(r["counterparties"]),
            }
            updates.append((r["id"], normalize_transaction_title(txn)))
        await conn.executemany(
            "UPDATE transactions SET display_title = $2 WHERE id = $1 AND display_title IS NULL",
            updates,
        )


async def _migrate_purge_generic_merchant_logos(conn) -> None:
    """V2.5.2: drop Brandfetch entries cached against generic merchant names.

    Same root cause as the display-title fix: Plaid hands us a generic
    word like "Online" as merchant_name, the Brandfetch search confidently
    resolves it to a real-but-unrelated brand (qS 0.96 → ``rs-online.com``
    in the wild), and the bogus logo lands in every transaction sharing
    that fake merchant_name. After this migration the read-time JOIN
    against ``merchant_logos`` returns NULL for those names and the UI
    falls back to its deterministic gradient avatar.

    Going forward, ``MerchantLogosRepository.names_to_enrich`` filters
    these out so the bad rows never come back. Idempotent + cheap (the
    blocklist is ~20 names; the DELETE rarely touches more than a row
    or two in practice).
    """
    from web.transactions.display import _GENERIC_MERCHANT_NAMES

    await conn.execute(
        """
        DELETE FROM merchant_logos
        WHERE LOWER(REGEXP_REPLACE(merchant_name, '\\s+', ' ', 'g'))
              = ANY($1::text[])
        """,
        list(_GENERIC_MERCHANT_NAMES),
    )


async def _migrate_recompute_display_title_for_generic_merchants(conn) -> None:
    """V2.5.1: re-derive ``display_title`` for transactions whose stored
    title is a generic Plaid-leaked word.

    Plaid sometimes serves single-word merchant_name values like "Online"
    or "Mobile" for transactions it failed to actually enrich (e.g. a
    Bank of America credit-card autopay coming back as "Online" with
    PFC "RENT_AND_UTILITIES_TELEPHONE"). The pre-V2.5.1 display logic
    treated those as pretty merchants and stored them verbatim, leaving
    the user staring at a useless "Online" row.

    ``_looks_pretty`` now rejects those words, but every transaction
    written before that fix still has the stale display_title in the
    DB. This migration recomputes those rows once, in place. Subsequent
    Plaid syncs will keep them correct on their own (the upsert
    overwrites display_title with the freshly-computed value).

    Same batching / safety-net pattern as the original backfill.
    """
    import json as _json

    from web.transactions.display import (
        _GENERIC_MERCHANT_NAMES,
        normalize_transaction_title,
    )

    def _parse_cp(value):
        if value is None or isinstance(value, list):
            return value
        if isinstance(value, str):
            try:
                return _json.loads(value)
            except Exception:
                return None
        return value

    # Match LOWER(display_title) against the same set the runtime check
    # uses — keeps the SQL filter cheap (no Python-side dance over every
    # transaction row) and stays in sync with the blocklist automatically.
    generic_lower = list(_GENERIC_MERCHANT_NAMES)
    for _ in range(2000):
        rows = await conn.fetch(
            """
            SELECT id, name, merchant_name, website, counterparties, display_title
            FROM transactions
            WHERE display_title IS NOT NULL
              AND LOWER(REGEXP_REPLACE(display_title, '\\s+', ' ', 'g')) = ANY($1::text[])
            ORDER BY id
            LIMIT 1000
            """,
            generic_lower,
        )
        if not rows:
            return
        updates: list[tuple[int, str]] = []
        for r in rows:
            txn = {
                "id": r["id"],
                "name": r["name"],
                "merchant_name": r["merchant_name"],
                "website": r["website"],
                "counterparties": _parse_cp(r["counterparties"]),
            }
            new_title = normalize_transaction_title(txn)
            # Only write when the recomputed title actually differs — a
            # row whose `name` is also generic (rare) might land on the
            # same fallback and re-running the UPDATE would just churn
            # updated_at for no reason.
            if new_title != r["display_title"]:
                updates.append((r["id"], new_title))
        if updates:
            await conn.executemany(
                "UPDATE transactions SET display_title = $2 WHERE id = $1",
                updates,
            )
        # If nothing changed in this batch, but rows matched the filter,
        # there's no progress to be made — exit to avoid infinite loop.
        if not updates:
            return


async def _migrate_categories_is_income(conn) -> None:
    """
    Add ``categories.is_income`` (user-controlled flag that defines what counts
    as income across the app). On first run, backfill every category whose
    Plaid personal-finance-category primary is ``INCOME`` to TRUE. On
    subsequent runs the backfill is skipped so a user-toggled OFF flag is not
    silently re-enabled.
    """
    async with conn.transaction():
        has_col = await conn.fetchval(
            """
            SELECT EXISTS(
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'categories'
                  AND column_name = 'is_income'
            )
            """
        )
        if not has_col:
            await _ddl(
                conn,
                "ALTER TABLE categories ADD COLUMN is_income BOOLEAN NOT NULL DEFAULT FALSE",
            )
            await _ddl(
                conn,
                """
                UPDATE categories
                SET is_income = TRUE
                WHERE plaid_pfc_primary = 'INCOME'
                """,
            )
        await _ddl(
            conn,
            "CREATE INDEX IF NOT EXISTS idx_categories_is_income ON categories(is_income) WHERE is_income = TRUE",
        )


async def _migrate_transactions_transaction_class(conn) -> None:
    """
    Add ``transactions.transaction_class`` + ``manual_class_override`` and
    run the classifier once over the full history.

    The new column is materialized so every hot aggregate (cash-flow, by
    category, budgets, health) can predicate on a single indexed value
    instead of re-computing ``amount_cents > 0 AND NOT is_internal_transfer
    AND EXISTS (categories.is_income = TRUE)`` on every row.

    Schema changes are idempotent; the initial backfill is guarded by a
    "never classified yet" check so re-running the migration is cheap
    once the column exists. User-set ``is_internal_transfer`` flags (the
    legacy binary UI toggle) are migrated into ``manual_class_override``
    so they survive the switch to the four-class model.
    """
    async with conn.transaction():
        has_class_col = await conn.fetchval(
            """
            SELECT EXISTS(
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'transactions'
                  AND column_name = 'transaction_class'
            )
            """
        )
        has_override_col = await conn.fetchval(
            """
            SELECT EXISTS(
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'transactions'
                  AND column_name = 'manual_class_override'
            )
            """
        )

        if not has_override_col:
            await _ddl(
                conn,
                """
                ALTER TABLE transactions
                ADD COLUMN manual_class_override TEXT NULL
                CHECK (
                    manual_class_override IS NULL OR manual_class_override IN (
                        'income', 'expense', 'internal_transfer', 'uncategorized'
                    )
                )
                """,
            )

        if not has_class_col:
            # NOT NULL default so existing rows get a value immediately; the
            # backfill below recomputes the real class straight after.
            await _ddl(
                conn,
                """
                ALTER TABLE transactions
                ADD COLUMN transaction_class TEXT NOT NULL DEFAULT 'uncategorized'
                CHECK (transaction_class IN (
                    'income', 'expense', 'internal_transfer', 'uncategorized'
                ))
                """,
            )

        await _ddl(
            conn,
            """
            CREATE INDEX IF NOT EXISTS idx_transactions_transaction_class
            ON transactions(transaction_class)
            """,
        )

        # Carry user-set manual internal-transfer choices into the new
        # override column. Only copy when the manual flag AND the internal
        # bit are both TRUE — a user who *explicitly* said "this is not an
        # internal transfer" (manual = TRUE, is_internal_transfer = FALSE)
        # would be locked out of the rest of the classifier if we wrote
        # ``expense`` here, so we leave that case alone and let the normal
        # rules decide. Idempotent: only writes where override is NULL.
        await conn.execute(
            """
            UPDATE transactions SET manual_class_override = 'internal_transfer'
            WHERE manual_class_override IS NULL
              AND is_internal_transfer_manual = TRUE
              AND is_internal_transfer = TRUE
            """
        )

        # First-run backfill: if *no* row has been classified yet (default
        # 'uncategorized' only and no overrides applied), run the full
        # classifier. This is deliberately not gated behind ``not has_class_col``
        # alone so a partial previous run can be re-completed simply by
        # restarting the app.
        needs_backfill = await conn.fetchval(
            """
            SELECT NOT EXISTS(
                SELECT 1 FROM transactions
                WHERE transaction_class <> 'uncategorized'
                   OR manual_class_override IS NOT NULL
            )
            """
        )
        if needs_backfill:
            from web.classification.classifier import rescan_all

            stats = await rescan_all(conn, horizon_days=None)
            logger.info(
                "transactions.transaction_class backfill done: %s", stats
            )


async def _migrate_fix_internal_transfer_class_drift(conn) -> None:
    """One-shot fix for rows whose ``transaction_class`` is stale relative
    to the current rules / counterparty-name list.

    Two failure modes the migration repairs:

    1. **Legacy/modern column drift.** ``import_transactions`` writes the
       legacy ``is_internal_transfer`` boolean inline (counterparty match)
       but never sets ``transaction_class`` on INSERT. Until 2026-04-27
       the post-import rescan used a 7-day horizon, so rows older than
       that stayed at ``transaction_class = 'uncategorized'`` while the
       mirror flag was already TRUE. Symptom users saw: "INTERNAL" pill
       in the list, "Auto (uncategorized)" in the modal.

    2. **Stale rule-5.5 income classification.** When ``classify_row``
       rule 4 (counterparty name match) didn't fire (e.g. because the
       names list was empty at the time of the rescan, or the row's
       counterparties metadata was missing), rule 5.5 took over for
       ``TRANSFER_IN`` rows on a depository account and tagged them
       ``income``. The legacy boolean and the modern class agreed
       (``FALSE`` ↔ "not internal"), so the column-drift probe alone
       wouldn't catch them — but the row is still wrong: now that the
       names list contains the family member, the row should be
       ``internal_transfer``. These rows leak into Income reports and
       inflate the family-income totals.

    The first failure mode is detectable by a SQL probe (drift between
    columns). The second isn't — the classifier needs to actually run
    against the current names list to know if a re-classification is
    warranted. So this migration uses **two triggers**:

      a) A one-shot sentinel ``app_settings.itr_v2_rescan_done``. When
         FALSE (first deploy of this fix), force a full rescan
         unconditionally. Set TRUE after success. Future startups skip
         the unconditional path.
      b) A drift probe (kept from the original implementation). Catches
         column drift on any future startup, e.g. if a future bug
         re-introduces the INSERT-skips-class problem.

    Manual class overrides are always preserved by ``classify_row``
    rule 1, and the matching legacy ``is_internal_transfer_manual``
    rows are excluded from both the probe and the classifier mirror-
    update — user decisions stay sacred.
    """
    # ---- Sentinel column ------------------------------------------------
    # Idempotent column add. Default FALSE so existing installs trigger
    # the one-shot rescan once after this code lands.
    await _ddl(
        conn,
        "ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS itr_v2_rescan_done BOOLEAN NOT NULL DEFAULT FALSE",
    )

    # On a brand-new DB the singleton row may not exist yet (it's
    # ensured by ``AppSettingsRepository.get`` lazily). For the sentinel
    # check we treat "no row" the same as "flag = FALSE" — but we need a
    # row to UPDATE later, so insert one if missing.
    await conn.execute(
        """
        INSERT INTO app_settings (id, itr_v2_rescan_done)
        VALUES (1, FALSE)
        ON CONFLICT (id) DO NOTHING
        """
    )

    flag_done = await conn.fetchval(
        "SELECT itr_v2_rescan_done FROM app_settings WHERE id = 1"
    )

    # ---- Drift probe (column-level) ------------------------------------
    # Catches case (1). Cheap; runs on every startup as a safety net
    # even after the one-shot has fired.
    has_drift = await conn.fetchval(
        """
        SELECT EXISTS(
            SELECT 1 FROM transactions
            WHERE manual_class_override IS NULL
              AND is_internal_transfer_manual = FALSE
              AND is_internal_transfer <> (transaction_class = 'internal_transfer')
        )
        """
    )

    needs_rescan = (not flag_done) or has_drift
    if not needs_rescan:
        return

    from web.classification.classifier import rescan_all

    stats = await rescan_all(conn, horizon_days=None)
    logger.info(
        "internal-transfer rescan complete (trigger=%s): changed=%d total=%d paired=%d by_class=%s",
        "first-run" if not flag_done else "drift-probe",
        stats.changed,
        stats.total,
        stats.paired,
        stats.by_class,
    )

    # Mark the one-shot done so subsequent startups skip the
    # unconditional path. The drift probe stays active forever.
    if not flag_done:
        await conn.execute(
            "UPDATE app_settings SET itr_v2_rescan_done = TRUE WHERE id = 1"
        )


async def _migrate_insights_persistence(conn) -> None:
    """Create persistence tables for the Insights feed (V2.1 Phase 4).

    ``insights_cards`` stores the latest snapshot of each distinct
    ``dedupe_key`` produced by the feed builder. ``insights_card_user_state``
    tracks per-user dismiss/snooze state so spouses have independent
    visibility (wife can hide a card that the husband still sees).

    Both tables are created idempotently. ``insights_card_user_state``
    intentionally has **no FK** to ``insights_cards(dedupe_key)`` so a
    recompute that purges a stale card does not delete the user's hide
    state — if the card recurs, the user's hide decision still applies.
    """
    await _ddl(
        conn,
        """
        CREATE TABLE IF NOT EXISTS insights_cards (
            id             BIGSERIAL PRIMARY KEY,
            dedupe_key     TEXT NOT NULL UNIQUE,
            type           TEXT NOT NULL,
            severity       TEXT NOT NULL,
            title          TEXT NOT NULL,
            summary        TEXT NOT NULL,
            detail         TEXT,
            action_url     TEXT,
            action_label   TEXT,
            payload        JSONB NOT NULL DEFAULT '{}'::jsonb,
            first_seen_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_seen_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
    )
    await _ddl(
        conn,
        "CREATE INDEX IF NOT EXISTS idx_insights_cards_last_seen ON insights_cards(last_seen_at)",
    )
    await _ddl(
        conn,
        """
        CREATE TABLE IF NOT EXISTS insights_card_user_state (
            user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            dedupe_key      TEXT NOT NULL,
            dismissed_at    TIMESTAMPTZ,
            snoozed_until   TIMESTAMPTZ,
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (user_id, dedupe_key)
        )
        """,
    )
    await _ddl(
        conn,
        "CREATE INDEX IF NOT EXISTS idx_insights_user_state_key ON insights_card_user_state(dedupe_key)",
    )

    # Thresholds in app_settings.insights_config (JSONB blob). Stored as a
    # single JSON column to avoid schema churn every time we add a knob.
    await _ddl(
        conn,
        "ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS insights_config JSONB NOT NULL DEFAULT '{}'::jsonb",
    )


async def _migrate_transactions_manual_amount_override(conn) -> None:
    """V2.3: per-transaction "do not let Plaid sync overwrite my amount" flag.

    Plaid's ``/transactions/sync`` upsert (``web/plaid/repo.py``) refreshes
    every column on conflict, including ``amount_cents``. Without a guard,
    an admin who hand-corrects a transaction amount sees the value silently
    revert on the next sync (~6h later).

    The override mirrors the pattern already used for class
    (``manual_class_override``) and internal-transfer flag
    (``is_internal_transfer_manual``): a boolean column the Plaid upsert
    explicitly checks before deciding whether to overwrite.

    Default is FALSE so existing rows are unaffected. Idempotent.
    """
    await _ddl(
        conn,
        "ALTER TABLE transactions "
        "ADD COLUMN IF NOT EXISTS manual_amount_override BOOLEAN NOT NULL DEFAULT FALSE",
    )


async def run_v2_migrations(pool) -> None:
    """Execute all V2 DDL statements against the provided asyncpg pool."""
    logger.info("Running V2 database migrations...")
    async with pool.acquire() as conn:
        for stmt in ALL_STATEMENTS:
            try:
                await _ddl(conn, stmt)
            except Exception as exc:
                logger.error("Migration statement failed: %s\nSQL: %s", exc, stmt[:120])
                raise
        await _migrate_categories_source(conn)
        await _migrate_v21_addons(conn)
        await _migrate_accounts_manual_and_missing(conn)
        await _migrate_merchant_rules_global_family(conn)
        await _migrate_merchant_rules_description_filter(conn)
        await _migrate_categories_parent_id(conn)
        await _migrate_categories_is_income(conn)
        await _migrate_recurring_price_change_signed(conn)
        await _migrate_recurring_user_status(conn)
        await _migrate_recurring_unsubscribed_state(conn)
        await _migrate_recurring_first_detected_alerted(conn)
        await _migrate_merchant_aliases(conn)
        await _migrate_merchant_aliases_website(conn)
        await _migrate_merchant_logos(conn)
        await _migrate_merchant_logos_user_curated(conn)
        await _migrate_transactions_display_title_backfill(conn)
        await _migrate_recompute_display_title_for_generic_merchants(conn)
        await _migrate_purge_generic_merchant_logos(conn)
        await _migrate_transactions_transaction_class(conn)
        await _migrate_fix_internal_transfer_class_drift(conn)
        await _migrate_insights_persistence(conn)
        await _migrate_transactions_manual_amount_override(conn)
    logger.info("V2 database migrations completed successfully.")
