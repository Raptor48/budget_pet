# Budget Pet V2 — Data Model

## Tables

### accounts
Single source of truth for all financial accounts (checking, savings, credit cards, loans, investments).

| Column | Type | Notes |
|---|---|---|
| id | SERIAL PK | Internal ID |
| plaid_account_id | TEXT UNIQUE | From Plaid account.account_id |
| plaid_item_id | TEXT | References plaid_items |
| name | TEXT | Account display name |
| official_name | TEXT | Full legal name from Plaid |
| mask | TEXT | Last 4 digits |
| type | TEXT | depository\|credit\|loan\|investment\|other |
| subtype | TEXT | checking\|savings\|credit card\|student\|mortgage\|... |
| current_balance_cents | BIGINT | Current balance (cents) |
| available_balance_cents | BIGINT | Available (depository) or available credit |
| credit_limit_cents | BIGINT | Credit limit (credit accounts) |
| apr_percent | NUMERIC(6,3) | APR from liabilities |
| min_payment_cents | BIGINT | Minimum payment due |
| due_day | SMALLINT | Day of month payment due |
| is_overdue | BOOLEAN | From liabilities |
| last_payment_date | DATE | |
| last_statement_balance_cents | BIGINT | |
| expected_payoff_date | DATE | Loans |
| ytd_interest_paid_cents | BIGINT | Year-to-date interest paid |
| currency | TEXT | ISO code, default USD |
| holder_category | TEXT | personal\|business |
| is_active | BOOLEAN | Soft delete |
| last_synced_at | TIMESTAMPTZ | |

### categories
PFC-backed rows created on Plaid sync plus user-defined custom rows.
Categories form a **two-level hierarchy**: every `plaid_pfc_primary` gets an
own primary-only row (e.g. *Entertainment*), and each `plaid_pfc_detailed`
row is linked to its parent via `parent_id`. Depth > 2 is not allowed (a
CHECK constraint forbids `parent_id = id`; a category with `parent_id` never
becomes a parent itself in practice).

| Column | Type | Notes |
|---|---|---|
| id | SERIAL PK | |
| name | TEXT UNIQUE | Human-readable name (display; may differ from raw PFC) |
| plaid_pfc_primary | TEXT | e.g. FOOD_AND_DRINK — set on BOTH the primary row and all detailed children for easy roll-up |
| plaid_pfc_detailed | TEXT UNIQUE | e.g. FOOD_AND_DRINK_RESTAURANTS (used for auto-mapping); NULL for primary-only or custom rows |
| parent_id | INTEGER NULL | Self-FK to `categories.id`. NULL on top-level primary or custom categories; filled for every PFC-detailed child. Index: `idx_categories_parent_id`. |
| color | TEXT | Hex color |
| icon | TEXT | Emoji or icon name |
| pfc_icon_url | TEXT | From Plaid personal_finance_category_icon_url |
| source | TEXT | `plaid_pfc` \| `custom` — Plaid rows come from sync; custom from API only |
| is_income | BOOLEAN NOT NULL | Family-wide flag: when TRUE, transactions mapped here count as **income** in every aggregate (Income tab, Cash Flow, Financial Health). Seeded TRUE for `plaid_pfc_primary = 'INCOME'` on first migration and for any new INCOME PFC rows created by sync. Editable via `PATCH /api/categories/{id}`; once the column exists the migration never overwrites it, so a user toggling OFF sticks. Partial index `idx_categories_is_income` keeps income lookups fast. |

Resolution contract (`web/categories/repo.py::resolve_category`):
1. If `pfc_primary` is provided, the primary-only parent row is upserted
   (`name = prettified pfc_primary`, `parent_id = NULL`) before any detailed
   work happens. This keeps the tree consistent even if Plaid ever changes a
   taxonomy family.
2. If only `pfc_primary` is given, the parent id is returned directly.
3. If `pfc_detailed` is also given, the detailed child is upserted and its
   `parent_id` is refreshed (relinking orphans created before the V2
   hierarchy migration was available).

Migration `web/migrations/v2_init.py::_migrate_categories_parent_id` adds
`parent_id` + index + the self-FK check, then backfills primary-only rows
for every known PFC family and links existing detailed rows. Custom rows
with matching names are never overwritten (`ON CONFLICT (name) DO NOTHING`).

### transactions
All transactions from Plaid, cash wallet (`source=cash`), and legacy `manual` rows.

| Column | Type | Notes |
|---|---|---|
| id | SERIAL PK | |
| plaid_transaction_id | TEXT UNIQUE | From Plaid, NULL for manual/cash |
| account_id | INTEGER | References accounts (cash rows use the per-user **Cash** wallet) |
| category_id | INTEGER | References categories (auto-resolved from PFC) |
| amount_cents | BIGINT | >0 = expense, <0 = income (Plaid convention) |
| currency | TEXT | |
| date | DATE | Posted date |
| authorized_date | DATE | Auth date (preferred for UI) |
| datetime | TIMESTAMPTZ | Full timestamp if available |
| authorized_datetime | TIMESTAMPTZ | |
| name | TEXT | Raw bank name |
| merchant_name | TEXT | Enriched by Plaid |
| merchant_entity_id | TEXT | Stable Plaid merchant ID |
| logo_url | TEXT | 100x100 PNG from Plaid |
| website | TEXT | |
| payment_channel | TEXT | online\|in store\|other |
| pfc_primary | TEXT | FOOD_AND_DRINK |
| pfc_detailed | TEXT | FOOD_AND_DRINK_RESTAURANTS |
| pfc_confidence | TEXT | VERY_HIGH\|HIGH\|MEDIUM\|LOW\|UNKNOWN |
| pfc_icon_url | TEXT | |
| counterparties | JSONB | Array of counterparty objects |
| location | JSONB | {city, lat, lon, address, ...} |
| payment_meta | JSONB | Reference numbers, processor |
| is_pending | BOOLEAN | |
| source | TEXT | plaid \| plaid_sandbox \| cash \| manual (cash = offline cash via API). Whether `plaid_sandbox` participates in reports/budgets/export is controlled by `web.env_flags.reports_include_plaid_sandbox()` (see `docs/plaid.md`). |
| user_note | TEXT | User annotation |
| is_private | BOOLEAN NOT NULL DEFAULT FALSE | Hide the row from other family members. Enforced by a sparse index `idx_transactions_is_private` and the `viewer_user_id` filter applied in every list/detail/report/export/insight query. When Plaid promotes a pending transaction to posted (new `plaid_transaction_id` + pending row reported as `removed`) the flag is carried from the pending twin via `pending_transaction_id` during import, so privacy survives autosync. |
| pending_transaction_id | TEXT | Plaid's link from a posted transaction back to its pending twin (`pending_transaction_id` on the Plaid transaction object). Populated on import; used to forward user-set flags (`is_private`, `user_note`, user-chosen `category_id`) before the pending row is deleted by `/transactions/sync`. Indexed sparsely. |
| is_internal_transfer | BOOLEAN NOT NULL DEFAULT FALSE | Flags Zelle-style intra-family transfers (Plaid `TRANSFER_IN` / `TRANSFER_OUT` where the counterparty name matches the family-wide list in `app_settings.internal_transfer_names`). Every income/expense aggregate in `web/reports/repo.py` and `web/budgets/repo.py` filters these rows out to avoid double-counting (sender's `TRANSFER_OUT` + recipient's subsequent purchase). Indexed by `idx_transactions_is_internal_transfer`. Classified on INSERT by `web/plaid/internal_transfer.py::classify_internal_transfer` and retroactively by `rescan_internal_transfers`. |
| is_internal_transfer_manual | BOOLEAN NOT NULL DEFAULT FALSE | Sentinel flipped whenever the user PATCHes `is_internal_transfer`. Both the auto-classifier and the rescan routine skip rows with `is_internal_transfer_manual = TRUE`, so manual overrides survive future names-list edits and /rescan calls. |
| display_title | TEXT | Materialized output of `normalize_transaction_title(...)`. Written on every upsert/import (Plaid + cash) and recomputed when `merchant_name` is edited; `update_transaction` refreshes it in the same transaction. Indexed on `lower(display_title)` and used by merchant-rule matching to fall back when `merchant_name` is NULL (ACH / checks / bill pays). Historical rows are backfilled by `_migrate_transactions_display_title_backfill` in batches of 1000 (idempotent: rows with a non-NULL value are skipped). API clients should read this column; `_enrich` still falls back to runtime normalization if the column is NULL for any reason. |

### Cash wallet (accounts)
One designated manual account per user: `name='Cash'`, `type=depository`, `subtype=cash`, `plaid_account_id` NULL, `is_cash_wallet=true`, `user_id` set. Created lazily via `GET /api/accounts/cash-wallet` or first cash transaction. `current_balance_cents` is adjusted when cash transactions are inserted/deleted; it may also be set via `PATCH /api/accounts/{id}` with `current_balance_cents` **only** on this wallet (not on Plaid-linked accounts). `DELETE /api/accounts/{id}` performs a soft delete (`is_active=false`); a new wallet is re-created the next time the user adds cash.

Note on family scope: `categories`, `tags`, and `category_budgets` are intentionally **not** scoped per user in V2 — the family shares the taxonomy and the envelope. **`accounts`** rows are still tied to `user_id` (who linked Plaid or owns the cash wallet). **`transactions`** are listed for the whole household via the API (everyone sees every account’s activity except rows hidden with `is_private`). **`sessions`** remain per user.

### tags + transaction_tags
User-defined tags for custom classification (e.g., "alcohol", "business").

### recurring_streams
From Plaid `/transactions/recurring/get`, plus **manual** rows created via `POST /api/recurring`. Plaid upsert skips rows where `stream_source = 'manual'`.

| Column | Type | Notes |
|---|---|---|
| plaid_stream_id | TEXT UNIQUE | Plaid `stream_id`, or synthetic `manual:{uuid}` for user-created streams |
| direction | TEXT | inflow\|outflow |
| frequency | TEXT | WEEKLY\|BIWEEKLY\|SEMI_MONTHLY\|MONTHLY\|ANNUALLY\|UNKNOWN |
| average_amount_cents | BIGINT | |
| last_amount_cents | BIGINT | |
| price_change_pct | NUMERIC(6,2) | Computed on sync as a **signed** percentage: `(last - avg) / abs(avg) * 100`. Positive = last charge higher than the long-term average, negative = lower. Historical rows are backfilled by `_migrate_recurring_price_change_signed` (idempotent). |
| status | TEXT | MATURE\|EARLY_DETECTION\|TOMBSTONED\|MANUAL (manual rows) |
| stream_source | TEXT | `plaid` (default) \| `manual` — Plaid `ON CONFLICT` update does not overwrite `manual` |

### plaid_items (connection metadata)
| Column | Type | Notes |
|---|---|---|
| item_login_required | BOOLEAN | Set from Plaid `ITEM_LOGIN_REQUIRED` webhook; cleared after successful sync |
| sync_updates_pending | BOOLEAN | Set from `SYNC_UPDATES_AVAILABLE`; cleared after successful sync |

### plaid_webhook_events
| Column | Type | Notes |
| webhook_id | TEXT PK | Plaid `webhook_id` for idempotent processing |

### merchant_category_rules
Family-wide rules: on **import** (after PFC resolution) the rule whose `merchant_key` matches the incoming transaction overrides the resolved category. At most one row per `merchant_key`.

Key-building priority (see `web/merchant_rules/keys.py`):
1. `merchant_entity_id` → `eid:<lower>` — stable Plaid merchant id.
2. `merchant_name`      → `name:<lower>` — Plaid's enriched label.
3. `display_title`      → `name:<lower>` — fallback used for ACH / checks /
   bill-pays where Plaid did not supply a merchant. The rule key and the
   matching SQL both coalesce `NULLIF(merchant_name, '')` onto `display_title`,
   so a rule created for "Pmts Sec: Ind" matches every such transaction.

| Column | Type | Notes |
|---|---|---|
| id | SERIAL PK | |
| merchant_key | TEXT UNIQUE | Internal key `eid:…` or `name:…` (lowercased) |
| category_id | INTEGER FK | |
| created_at | TIMESTAMPTZ | |

### user_preferences
| Column | Type | Notes |
| insights_last_viewed_at | TIMESTAMPTZ | Optional; used for Insights “new since last visit” UX |

### Pending → posted (reports)
Plaid may surface the same spend as **pending** then **posted** with different `plaid_transaction_id`s. Aggregates and budgets use **posted** rows as they appear in `transactions`; when both exist in the same month, treat as one economic event in UI (dedupe / pair) — see `docs/plaid.md` for sync behavior.

### category_budgets
Budget envelopes: limit per category per month. Participate in the
two-level category hierarchy:

- A **parent-level** budget (`categories.parent_id IS NULL`) rolls up actuals
  from both the parent row itself and any of its detailed children via
  `COALESCE(parent_id, category_id)` in `web/budgets/repo.py::get_progress`.
- A **child-level** budget (`categories.parent_id IS NOT NULL`) sums only
  transactions with the child's exact `category_id`.
- Parent and child budgets for the same month are **mutually exclusive**.
  `web/budgets/repo.py::create_budget` raises `ValueError` (surfaced as HTTP
  409 by the API layer) if they would conflict.

### transaction_splits
Split a transaction into multiple category/tag parts.
Invariant: SUM(splits.amount_cents) == parent.amount_cents.

### net_worth_snapshots
Created after each sync. One row per day (ON CONFLICT DO UPDATE).

### securities + investment_holdings
From Plaid /investments/holdings/get.

### app_settings
Singleton row (`id = 1`) holding application-wide preferences. Read on startup
by `web.plaid.scheduler.start_scheduler` to register the daily cron job and
re-read live by `PATCH /api/settings/app` so Settings → App changes take effect
without a redeploy. Defaults are seeded by `web/migrations/v2_init.py`.

| Column | Type | Notes |
|---|---|---|
| id | SMALLINT PK | Always 1 (CHECK constraint) |
| autosync_frequency | VARCHAR(16) | One of `off`, `daily`, `weekly`, `semimonthly`, `monthly` (CHECK enforced). Anchor days are fixed (`weekly` → Sunday, `semimonthly` → 1st + 15th, `monthly` → 1st); only the cadence + time are editable. `off` removes the APScheduler job entirely |
| autosync_hour_utc | SMALLINT | 0-23 (CHECK enforced). UTC is stored so DB/server/clock stay aligned; UI converts to the user's local zone |
| autosync_minute_utc | SMALLINT | 0-59 (CHECK enforced) |
| webhooks_enabled | BOOLEAN | When FALSE the app ignores incoming Plaid webhooks and (on flip) pushes an empty webhook URL to every linked item via `/item/webhook/update`. Designed to cut Plaid Balance-call costs for personal / family deployments. Default TRUE |
| internal_transfer_names | TEXT[] NOT NULL DEFAULT '{}' | Family-wide list of counterparty names that flag a Plaid `TRANSFER_IN` / `TRANSFER_OUT` transaction as an intra-family transfer (see `transactions.is_internal_transfer`). Edited via `PUT /api/settings/internal-transfers`; normalization + matching logic lives in `web/plaid/internal_transfer.py`. |
| updated_at | TIMESTAMPTZ | NOW() on every update |
| updated_by | INTEGER FK | `users.id`, ON DELETE SET NULL |

### audit_log
Append-only activity feed used by Settings → Log. Written by
`web.audit.record(...)` — a single non-throwing helper called from auth, Plaid
and settings routes plus the scheduler. Audit writes never break product
flows: insert failures are logged and swallowed.

| Column | Type | Notes |
|---|---|---|
| id | BIGSERIAL PK | Cursor for `GET /api/audit?before_id=...` |
| created_at | TIMESTAMPTZ | Indexed DESC for reverse chronological list |
| actor_user_id | INTEGER FK | `users.id`, ON DELETE SET NULL (nullable for scheduler/system events) |
| actor_username | TEXT | Snapshotted so deleted users still render |
| event_type | TEXT | Namespaced, e.g. `auth.login`, `auth.logout`, `auth.login_failed`, `plaid.sync_manual`, `plaid.sync_scheduled`, `plaid.item_connect`, `plaid.item_remove`, `plaid.cursor_reset`, `plaid.sandbox_wiped`, `settings.autosync_updated` |
| source | TEXT | `manual` \| `scheduler` \| `webhook` \| `system` (CHECK enforced) |
| target_kind | TEXT | e.g. `plaid_item` |
| target_id | TEXT | Free-form id (institution item_id, etc.) |
| metadata | JSONB | Event-specific payload; always `{}` when empty |
| request_ip | INET | From `X-Forwarded-For` (last entry) or `request.client.host` |

Indexes: `idx_audit_log_created_at (created_at DESC)`,
`idx_audit_log_event_type (event_type, created_at DESC)`,
`idx_audit_log_actor (actor_user_id, created_at DESC)`.
