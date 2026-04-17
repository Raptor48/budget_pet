# Budget Pet V2 — Architecture

## Overview

V2 is centered on Plaid API for linked institutions (transactions, accounts, categories, recurring). Offline **cash** spending uses the same `transactions` table with `source=cash` on a per-user **Cash** wallet account (see `docs/data-model.md`).

## Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11, FastAPI, Uvicorn, asyncpg |
| Frontend | Next.js 15, React 19, TypeScript 5, Tailwind CSS 4, TanStack Query |
| Database | PostgreSQL (Railway) |
| Plaid | plaid-python 39+, products: transactions, liabilities, investments, recurring_transactions |
| Hosting | Railway (FastAPI, Next.js, Postgres services) |

## Module Structure

```
web/
├── main.py              — FastAPI app, startup, router registration
├── db.py                — Shared asyncpg pool singleton
├── migrations/
│   └── v2_init.py       — CREATE TABLE IF NOT EXISTS for all V2 tables
├── auth/                — DB-backed sessions, multi-user, rate limiting
├── plaid/               — Plaid Link, sync, scheduler
│   ├── client.py        — Plaid API wrappers (transactions, liabilities, investments, recurring)
│   ├── repo.py          — PlaidRepository: items, sync log, transaction import
│   └── scheduler.py     — APScheduler daily sync (03:00)
├── accounts/            — /api/accounts CRUD
├── transactions/        — /api/transactions CRUD + splits + CSV export
├── categories/          — /api/categories CRUD + PFC auto-mapping
├── tags/                — /api/tags CRUD + transaction-tag linking
├── recurring/           — /api/recurring + price change detector
├── budgets/             — /api/budgets + progress calculation
├── investments/         — /api/investments/holdings
└── reports/             — /api/reports/* (cash flow, net worth, forecast, health)
```

## Data Flow

```
Plaid API
    │
    ▼
plaid/scheduler.py (daily 03:00 + manual POST /api/plaid/sync)
    │
    ├── accounts/balance/get  ──→ accounts table (provision + update balances)
    ├── transactions/sync     ──→ transactions table (upsert by plaid_transaction_id)
    │                              └── categories (auto-resolve via PFC)
    ├── liabilities/get       ──→ accounts table (APR, min_payment, overdue)
    ├── recurring/get         ──→ recurring_streams table
    ├── investments/holdings  ──→ securities + investment_holdings tables
    └── snapshot_net_worth()  ──→ net_worth_snapshots table
```

## Authentication

- DB-backed sessions (users + sessions tables)
- Owner accounts manage family members via /api/auth/users
- Emergency bypass via ADMIN_LOGIN / ADMIN_PASSWORD env vars
- Cookie auth + Authorization: Bearer fallback for cross-origin

## Key Conventions

- **asyncpg only** — no psycopg2
- **All routes under /api/** — protected by AuthMiddleware
- **PFC auto-mapping** — categories auto-created on first sync from personal_finance_category
- **Split transactions** — invariant: SUM(splits.amount_cents) = parent.amount_cents
- **plaid_sandbox source** — excluded from reports/budgets/CSV when `reports_include_plaid_sandbox()` is false; **by default included** if `PLAID_ENV=sandbox`, or force with `REPORTS_INCLUDE_PLAID_SANDBOX=true` (see `web/env_flags.py`)
