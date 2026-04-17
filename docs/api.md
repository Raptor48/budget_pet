# Budget Pet V2 — API Reference

All endpoints require authentication (session cookie or Authorization: Bearer header).
Base URL: configured in NEXT_PUBLIC_API_URL.

## Accounts

| Method | Path | Description |
|---|---|---|
| GET | /api/accounts | List accounts (active_only=true default); each row includes `is_cash_wallet` when applicable |
| GET | /api/accounts/cash-wallet | Ensure and return the per-user **Cash** wallet (no Plaid link) |
| POST | /api/accounts | Create manual account |
| GET | /api/accounts/{id} | Get account |
| PATCH | /api/accounts/{id} | Update account; **`current_balance_cents` allowed only** on the designated Cash wallet (422 otherwise) |
| DELETE | /api/accounts/{id} | Soft-delete account |

## Categories

Each category has `source`: **`plaid_pfc`** (created when syncing Plaid transactions / streams) or **`custom`** (created via POST). Only **`custom`** rows can be deleted. All rows may be PATCHed for display `name` / `color` / `icon`.

| Method | Path | Description |
|---|---|---|
| GET | /api/categories | List all categories |
| POST | /api/categories | Create **custom** category (`name`, optional `color`, `icon`; no Plaid PFC fields) |
| GET | /api/categories/{id} | Get category |
| PATCH | /api/categories/{id} | Update `name`, `color`, `icon` |
| DELETE | /api/categories/{id} | Delete **custom** only (`404` if Plaid-derived or missing) |

## Tags

| Method | Path | Description |
|---|---|---|
| GET | /api/tags | List all tags |
| POST | /api/tags | Create tag |
| PATCH | /api/tags/{id} | Update tag |
| DELETE | /api/tags/{id} | Delete tag |

## Merchant category rules

| Method | Path | Description |
|---|---|---|
| GET | /api/merchant-rules | List rules (`merchant_key` is internal: `name:…` or `eid:…`) |
| POST | /api/merchant-rules | Upsert rule; body: `category_id` and **`merchant_entity_id` or `merchant_name`** |
| DELETE | /api/merchant-rules/{id} | Delete rule |

## Transactions

| Method | Path | Description |
|---|---|---|
| GET | /api/transactions | List transactions (filters: month, account_id, category_id, tag_id, search, channel, pending_only, limit, offset) |
| POST | /api/transactions | Create **cash** transaction on the user's Cash wallet (`source=cash`); body: `amount_cents`, `date`, `name`, optional `category_id`, `authorized_date`, `merchant_name`, `user_note`. Server sets `payment_channel=other`, `currency=USD`, `is_pending=false`. |
| GET | /api/transactions/{id} | Get transaction with tags and splits |
| PATCH | /api/transactions/{id} | Update category_id, user_note, merchant_name |
| DELETE | /api/transactions/{id} | Delete non-Plaid rows (`cash`, `manual`, etc.); reverses Cash wallet balance for `source=cash` |
| POST | /api/transactions/{id}/tags/{tag_id} | Add tag |
| DELETE | /api/transactions/{id}/tags/{tag_id} | Remove tag |
| GET | /api/transactions/{id}/splits | Get splits |
| POST | /api/transactions/{id}/splits | Replace splits (validates SUM invariant) |
| DELETE | /api/transactions/{id}/splits | Clear all splits |
| GET | /api/transactions/export | CSV export (same filters as list); **`plaid_sandbox` rows follow `reports_include_plaid_sandbox()`** (included when `PLAID_ENV=sandbox` unless `REPORTS_INCLUDE_PLAID_SANDBOX=false`; production defaults to exclude) |

## Recurring Streams

| Method | Path | Description |
|---|---|---|
| GET | /api/recurring | List streams (direction=inflow|outflow, active_only) |
| GET | /api/recurring/price-changes | Streams with >10% price change |
| GET | /api/recurring/{id} | Get stream |
| PATCH | /api/recurring/{id} | Update user_label, category_id |
| POST | /api/recurring | Create a **manual** recurring stream (same table as Plaid); `plaid_stream_id` is synthetic `manual:{uuid}`; excluded from Plaid upsert |

## Budgets

| Method | Path | Description |
|---|---|---|
| GET | /api/budgets | List budgets (optional month filter) |
| POST | /api/budgets | Create budget (category_id + month + budget_cents) |
| PATCH | /api/budgets/{id} | Update budget_cents |
| DELETE | /api/budgets/{id} | Delete budget |
| GET | /api/budgets/progress | Budget vs actual for month (split-aware) |

## Investments

| Method | Path | Description |
|---|---|---|
| GET | /api/investments/holdings | List holdings (optional account_id filter) |

## Reports

| Method | Path | Description |
|---|---|---|
| GET | /api/reports/cash-flow | Income vs expenses for a month |
| GET | /api/reports/cash-flow/history | Last N months (default 12) |
| GET | /api/reports/by-category | Spending by category for month (split-aware) |
| GET | /api/reports/by-tag | Spending by tag (optional month + tag_id filter) |
| GET | /api/reports/merchants | Top N merchants by spend |
| GET | /api/reports/net-worth | Current net worth snapshot |
| GET | /api/reports/net-worth/history | Historical snapshots (default 12 months) |
| GET | /api/reports/forecast | Cash flow forecast for next N days (30/60/90) |
| GET | /api/reports/financial-health | Health score 0–100 with metrics |

## Insights

| Method | Path | Description |
|---|---|---|
| GET | /api/insights/feed | Aggregated insight cards from existing reports (partial failures degrade per-card, not whole response) |
| POST | /api/insights/mark-viewed | Store `insights_last_viewed_at` in `user_preferences` (cross-device “seen” baseline for teaser) |

## Plaid

| Method | Path | Description |
|---|---|---|
| POST | /api/plaid/link-token | Create Plaid Link token |
| POST | /api/plaid/exchange-token | Exchange public_token for access_token |
| GET | /api/plaid/items | List connected bank items |
| DELETE | /api/plaid/items/{item_id} | Disconnect a bank |
| POST | /api/plaid/items/{item_id}/reset-cursor | Reset sync cursor |
| POST | /api/plaid/sync | Trigger manual sync for all items |
| GET | /api/plaid/sync/log | Last 50 sync log entries |
| POST | /api/plaid/webhook | Plaid webhooks (HTTPS); verifies Plaid JWT; handles `ITEM_LOGIN_REQUIRED`, `SYNC_UPDATES_AVAILABLE` |
| DELETE | /api/plaid/sandbox-data | **Sandbox only:** delete all rows tied to `source=plaid_sandbox` (transactions, accounts, recurring, net worth snapshots, Plaid items). Preserves manual/cash data, categories, tags, budgets. |

## Auth

| Method | Path | Description |
|---|---|---|
| POST | /api/auth/login | Login (returns session cookie + token) |
| POST | /api/auth/logout | Logout (clears cookie) |
| GET | /api/auth/me | Current user info |
| GET | /api/auth/status | Auth status check |
| GET | /api/auth/members | List family members (`id`, `username`) for attribution UI |
| GET | /api/auth/users | List users (owner only) |
| POST | /api/auth/users | Create user (owner only) |
| DELETE | /api/auth/users/{id} | Delete user (owner only) |

## Health

| Method | Path | Description |
|---|---|---|
| GET | /healthz | Health check |
