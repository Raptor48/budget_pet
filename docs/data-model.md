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

| Column | Type | Notes |
|---|---|---|
| id | SERIAL PK | |
| name | TEXT UNIQUE | Human-readable name (display; may differ from raw PFC) |
| plaid_pfc_primary | TEXT | e.g. FOOD_AND_DRINK |
| plaid_pfc_detailed | TEXT UNIQUE | e.g. FOOD_AND_DRINK_RESTAURANTS (used for auto-mapping); NULL for primary-only or custom |
| color | TEXT | Hex color |
| icon | TEXT | Emoji or icon name |
| pfc_icon_url | TEXT | From Plaid personal_finance_category_icon_url |
| source | TEXT | `plaid_pfc` \| `custom` — Plaid rows come from sync; custom from API only |

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
| is_private | BOOLEAN NOT NULL DEFAULT FALSE | Hide the row from other family members. Enforced by a sparse index `idx_transactions_is_private` and the `viewer_user_id` filter applied in every list/detail/report/export/insight query. |

### Cash wallet (accounts)
One designated manual account per user: `name='Cash'`, `type=depository`, `subtype=cash`, `plaid_account_id` NULL, `is_cash_wallet=true`, `user_id` set. Created lazily via `GET /api/accounts/cash-wallet` or first cash transaction. `current_balance_cents` is adjusted when cash transactions are inserted/deleted; it may also be set via `PATCH /api/accounts/{id}` with `current_balance_cents` **only** on this wallet (not on Plaid-linked accounts). `DELETE /api/accounts/{id}` performs a soft delete (`is_active=false`); a new wallet is re-created the next time the user adds cash.

Note on family scope: `categories`, `tags`, and `category_budgets` are intentionally **not** scoped per user in V2 — the family shares the taxonomy and the envelope. The per-user `user_id` filter is only applied to `transactions`, `accounts`, and `sessions`.

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
| price_change_pct | NUMERIC(6,2) | Computed on sync: \|last-avg\|/avg * 100 |
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
Per-user overrides: if a rule matches `merchant_entity_id` or normalized `merchant_name`, its `category_id` is applied on **import** (after PFC resolution).

| Column | Type | Notes |
| user_id | INTEGER FK | |
| merchant_key | TEXT | Internal key `eid:…` or `name:…` (lowercased) |
| category_id | INTEGER FK | |

### user_preferences
| Column | Type | Notes |
| insights_last_viewed_at | TIMESTAMPTZ | Optional; used for Insights “new since last visit” UX |

### Pending → posted (reports)
Plaid may surface the same spend as **pending** then **posted** with different `plaid_transaction_id`s. Aggregates and budgets use **posted** rows as they appear in `transactions`; when both exist in the same month, treat as one economic event in UI (dedupe / pair) — see `docs/plaid.md` for sync behavior.

### category_budgets
Budget envelopes: limit per category per month.

### transaction_splits
Split a transaction into multiple category/tag parts.
Invariant: SUM(splits.amount_cents) == parent.amount_cents.

### net_worth_snapshots
Created after each sync. One row per day (ON CONFLICT DO UPDATE).

### securities + investment_holdings
From Plaid /investments/holdings/get.
