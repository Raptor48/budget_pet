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
    apr_percent                  NUMERIC(6,3),
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
    id                   SERIAL PRIMARY KEY,
    plaid_stream_id      TEXT UNIQUE NOT NULL,
    account_id           INTEGER REFERENCES accounts(id),
    direction            TEXT NOT NULL,
    description          TEXT NOT NULL,
    merchant_name        TEXT,
    frequency            TEXT,
    average_amount_cents BIGINT,
    last_amount_cents    BIGINT,
    currency             TEXT DEFAULT 'USD',
    pfc_primary          TEXT,
    pfc_detailed         TEXT,
    first_date           DATE,
    last_date            DATE,
    is_active            BOOLEAN DEFAULT TRUE,
    status               TEXT,
    category_id          INTEGER REFERENCES categories(id),
    user_label           TEXT,
    price_change_pct     NUMERIC(6,2),
    last_synced_at       TIMESTAMPTZ DEFAULT NOW()
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
    *CREATE_INDEXES,
    *CREATE_TRGM_INDEXES,
    *PLAID_ITEMS_COLUMNS,
    *ACCOUNTS_COLUMNS,
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
        ):
            try:
                await _ddl(conn, col)
            except Exception:
                pass

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
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            merchant_key TEXT NOT NULL,
            category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (user_id, merchant_key)
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
    logger.info("V2 database migrations completed successfully.")
