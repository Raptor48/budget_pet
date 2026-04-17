# Budget Pet V2 — Plaid Integration

## Products Used

| Product | Purpose | Plaid Endpoint |
|---|---|---|
| transactions | Expense/income data | /transactions/sync |
| liabilities | Credit card + loan details | /liabilities/get |
| investments (optional) | Portfolio holdings | /investments/holdings/get |
| recurring_transactions (optional) | Subscriptions detection | /transactions/recurring/get |

## Sync Flow (per item)

1. **transactions/sync** — cursor-based pagination until has_more=False
   - Request `options.personal_finance_category_version` is set from env `PLAID_PERSONAL_FINANCE_CATEGORY_VERSION` (default **`v2`**) so responses use [PFCv2](https://plaid.com/docs/transactions/pfc-migration/) where supported.
   - Added + Modified transactions upserted to `transactions` table
   - Removed transactions deleted from `transactions` table
   - Category auto-resolved from `personal_finance_category.detailed` → `categories` table (`source = plaid_pfc`)
   
2. **accounts/balance/get** — provision new accounts, update balances

3. **liabilities/get** — update APR, min_payment, is_overdue on accounts
   - Credit cards: aprs[], minimum_payment_amount, next_payment_due_date, is_overdue
   - Student loans: interest_rate_percentage, minimum_payment_amount, expected_payoff_date
   - Mortgages: interest_rate.percentage, next_monthly_payment, maturity_date

4. **transactions/recurring/get** — upsert recurring_streams
   - Uses the same `personal_finance_category_version` option as **transactions/sync** (default **v2**).
   - Both inflow_streams and outflow_streams
   - price_change_pct computed: |last-avg|/avg * 100

5. **investments/holdings/get** — upsert securities + investment_holdings (if available)

6. **snapshot_net_worth()** — capture net worth into net_worth_snapshots

7. Update cursor, write to plaid_sync_log

## Transaction Fields

All fields mapped directly from Plaid API:

```
transaction_id         → plaid_transaction_id
account_id             → (mapped to accounts.id via plaid_account_id)
amount                 → amount_cents (×100, >0=expense <0=income)
iso_currency_code      → currency
date                   → date
authorized_date        → authorized_date
datetime               → datetime
authorized_datetime    → authorized_datetime
name                   → name
merchant_name          → merchant_name
merchant_entity_id     → merchant_entity_id
logo_url               → logo_url
website                → website
payment_channel        → payment_channel
personal_finance_category.primary    → pfc_primary
personal_finance_category.detailed   → pfc_detailed
personal_finance_category.confidence → pfc_confidence
personal_finance_category_icon_url   → pfc_icon_url
counterparties         → counterparties (JSONB)
location               → location (JSONB)
payment_meta           → payment_meta (JSONB)
pending                → is_pending
```

## PFC Category Auto-Mapping

There is **no** separate Plaid endpoint for the full PFC catalog; taxonomy reference is Plaid’s [CSV](https://plaid.com/documents/pfc-taxonomy-all.csv). Do **not** use deprecated **`/categories/get`** for PFC (that endpoint is for legacy `category` / `category_id` only).

When a transaction is imported:
1. Check if a category exists with `plaid_pfc_detailed = pfc_detailed` (or primary-only match when `detailed` is absent).
2. If not found, auto-create a row with `source = plaid_pfc`:
   - `name` = human-readable label derived from PFC strings
   - `plaid_pfc_primary`, `plaid_pfc_detailed`, `pfc_icon_url` from Plaid
3. Return `category_id`.

**Startup does not seed generic categories.** Rows appear only after sync sees real PFC values (or the user creates `source = custom` via `POST /api/categories`).

Users can rename or recolor any category for display; Plaid-derived rows cannot be deleted (only custom categories). Transactions can still be reassigned to another `category_id` via the transactions API.

## Environments

| PLAID_ENV | Source Tag | Description |
|---|---|---|
| sandbox | plaid_sandbox | Test data; **included in reports/budgets/CSV** when `PLAID_ENV=sandbox` unless `REPORTS_INCLUDE_PLAID_SANDBOX=false` |
| development | plaid | Real bank accounts, up to 100 items |
| production | plaid | Production (requires Plaid approval) |

## Sandbox Testing

- Use "First Platypus Bank" institution in sandbox
- Test credentials: user_good / pass_good
- Sandbox provides limited transaction data (merchant_name may be null)
- After connecting, click "Reset cursor" in Settings then "Sync Now"

## Link Token Products

```python
products = [transactions]
required_if_supported_products = [liabilities]
optional_products = [investments]            # gated by PLAID_ENABLE_INVESTMENTS
transactions.days_requested = 730            # set via PLAID_TRANSACTIONS_DAYS_REQUESTED
```

`required_if_supported_products` are requested but don't fail if the institution doesn't support them. The same is true for `optional_products`. `recurring_transactions` is **not** a Link product — data comes from `/transactions/recurring/get` after the Item is linked.

`transactions.days_requested` controls how many days of historical transactions Plaid returns after linking. Plaid default is 90 days and the maximum is **730** (~24 months); we request the maximum by default because Plaid's Transactions product is billed as a **per-Item monthly subscription** (see [Plaid billing docs](https://plaid.com/docs/account/billing#subscription-fee)), so a larger history window does **not** increase cost. The value is tunable via `PLAID_TRANSACTIONS_DAYS_REQUESTED` and clamped into `[1..730]`.

The value is passed in **both** `LinkTokenCreateRequest` branches (new connection and update-mode with `access_token`). Plaid supports extending history for an existing Item by re-running Link in update-mode with a larger `days_requested` — see [Plaid docs](https://plaid.com/docs/api/link/#link-token-create-request-transactions-days-requested).

## Reset Cursor

POST /api/plaid/items/{item_id}/reset-cursor

Sets cursor to NULL. Next sync will re-import ALL transactions from the beginning.
Use for testing or recovering from sync issues.

## Sync Idempotency

`transactions/sync` pages are collected by `get_transactions_sync` until
`has_more=False`, then `import_transactions` upserts them with
`ON CONFLICT (plaid_transaction_id) DO UPDATE`. The cursor in `plaid_items.cursor`
is advanced **only after** successful import, so the sync has at-least-once
semantics: a crash between pages or during import simply causes the next sync
to re-fetch from the previous cursor and re-upsert already-imported rows, which
is a no-op at the row level (no duplicates, existing edits like `category_id`
are preserved by `COALESCE`). Removed transactions reported by Plaid are
deleted in the same step.

## Removing a bank

`DELETE /api/plaid/items/{item_id}` supports two modes:

| Mode | What is deleted | When to use |
|---|---|---|
| `?purge=false` (default) | `plaid_items` row only; `accounts.plaid_item_id` is set to `NULL` via FK `ON DELETE SET NULL`; accounts, transactions, recurring streams and holdings stay. | You want to stop syncing this bank but keep the historical reports. |
| `?purge=true` | Above **plus** all accounts with this `plaid_item_id`, all Plaid-sourced transactions on those accounts (`source IN ('plaid','plaid_sandbox')`), their `transaction_tags` / `transaction_splits`, `recurring_streams` tied to those accounts, `investment_holdings` for those accounts, orphaned `securities`, and `plaid_sync_log` rows for the item. Cash/manual transactions are never removed. | You plan to reconnect the same bank and want to avoid duplicates. |

**Why purge matters on reconnect.** Plaid issues a fresh `item_id` and fresh
per-account `account_id` values on every Link flow, even for the same bank and
user. If you `purge=false` and later re-link BofA, the new Item brings in new
`accounts` rows and 730 days of transactions as entirely new `plaid_transaction_id`s,
while the old `accounts` / `transactions` remain — resulting in visible
duplicates in lists, budgets, reports and net worth. The UI surfaces this
trade-off via a confirmation dialog that pre-fetches row counts from
`GET /api/plaid/items/{item_id}/data-summary`.

## Webhooks

Budget Pet exposes **`POST /api/plaid/webhook`** on the FastAPI service (public HTTPS URL in production).

1. **Dashboard:** In the [Plaid Dashboard](https://dashboard.plaid.com/) → Developers → Webhooks, register the same URL you deploy (e.g. `https://<your-fastapi-host>/api/plaid/webhook`).
2. **Verification:** Payloads are verified with Plaid’s **JWT** (JWKS). For local tunneling without valid JWT, set **`PLAID_SKIP_WEBHOOK_VERIFY=true`** (never in production).
3. **Handled codes (minimum):** `ITEM_LOGIN_REQUIRED` (sets `plaid_items.item_login_required`), `SYNC_UPDATES_AVAILABLE` (debounced per-item sync; duplicate `webhook_event_id` rows are ignored for idempotency).
4. **Operations:** After deploy, watch **Railway → FastAPI → Logs** for webhook 4xx/5xx; repeated 5xx may cause Plaid retries — fix verification or handler before leaving broken for long.

Related env:

| Variable | Purpose |
|---|---|
| `CORS_ORIGINS` | Comma-separated browser origins (cookies + preflight); include your Next.js URL. |
| `PLAID_SKIP_WEBHOOK_VERIFY` | `true` only for dev when JWT cannot be validated. |
