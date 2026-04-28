# Live Demo

> [▶️ Watch 5-minute walkthrough](https://www.loom.com/share/e9eba267ccd24963a013de2d6e3079c6)

This branch (`demo`) is the public, sandbox-only deployment of Budget Pet for
portfolio / hiring review. The Telegram bot surface is suppressed so the app
reads as a focused web product; everything else is the real V2.3 codebase.

> 🌐 **Live URL:** <https://nextjs-web-ui-demo.up.railway.app>
>
> 🔐 **Login:** `demo` / `demo_pass`
>
> 🏦 **API:** <https://fastapi-demo-e11c.up.railway.app> (Plaid sandbox only)

## What you can do in the demo

- **Connect a bank** via Plaid Sandbox (no real-money risk — the deployment is
  pinned to `PLAID_ENV=sandbox`). Use Plaid's standard test login:
  - Username: `user_good`
  - Password: `pass_good`
  - Any MFA code: `1234`
- Browse imported transactions across linked accounts. Categorize, split,
  flag as private, attach receipts.
- Define monthly **budgets** by category and watch threshold tracking.
- View **recurring streams** detected from your transactions, with surfaced
  next-payment dates and price-change history.
- Open the **Reports** tab for income/expense breakdowns, internal-transfer
  detection, and savings-rate trends.
- Read the **Insights** feed for auto-detected patterns (subscription creep,
  new merchants, anomalies).
- Set savings **Goals** and watch milestone thresholds light up as net worth
  changes.

## What's hidden in the demo

- **Telegram bot** — the `Bot` sidebar tab and `/bot` route are suppressed via
  `NEXT_PUBLIC_HIDE_BOT_TAB=true`. The backend `/api/bot/*` and Telegram
  webhook endpoints are not registered when no `TELEGRAM_BOT_TOKEN` is set, so
  there's no Bot surface to test even if you tried URL-pasting.
- **OCR receipts** — works in production, dormant in the demo unless OCR
  provider keys are configured.

## What's interesting in the code

If you've got 15 minutes to skim, these are the files I'd open first.
Each illustrates a different chunk of the product:

| File | Why look |
|------|---------|
| [`web/transactions/display.py`](web/transactions/display.py) | ACH descriptor normalization. Heuristic pipeline for turning raw bank-statement strings (`PAYPAL INST XFER PYPL PAYMTHLY WEB ID:…`) into something a human can read. The frontend mirror lives at `frontend/src/lib/transaction-display.ts`. |
| [`web/notifications/producers.py`](web/notifications/producers.py) | Detection layer for the alerts pipeline. Brand-aware merchant cleanup + denylist for bank artefacts (interest charges, self-transfers) so the morning brief stops being noise. |
| [`web/notifications/builders.py`](web/notifications/builders.py) | Render layer for the same pipeline. Aggregates per-section notifications into a single header + top-N bulleted summary so a brief with 12 events still fits on one screen. |
| [`web/notifications/dispatcher.py`](web/notifications/dispatcher.py) | Per-minute drain loop. P0 immediate, P1 batched into a daily brief at the user's local 09:00, P2 rolled into a Sunday digest. Quiet-hours handling and tz-aware brief windows live here. |
| [`web/recurring/repo.py`](web/recurring/repo.py) and [`web/reports/calculations.py`](web/reports/calculations.py) | Recurring-stream detection on top of Plaid recurring + a `next_future_occurrence` helper that walks cadence forward to today (so the UI never shows "next payment Mar 9" when today is Apr 27). |
| [`web/auth/telegram_webapp.py`](web/auth/telegram_webapp.py) | HMAC-SHA256 verifier for Telegram Mini App initData (dormant in the demo, but illustrative of crypto-correctness). |
| [`web/migrations/`](web/migrations/) | Idempotent `ALTER TABLE … ADD COLUMN IF NOT EXISTS` migrations. Boring on purpose: every migration is safe to re-run. |
| [`tests/v2/`](tests/v2/) | 498 tests covering transactions, recurring, reports, splits, Plaid sync edge cases, internal-transfer detection. Runs in ~1.3s. |

For a tour of the design decisions, read
[`docs/engineering-decisions.md`](docs/engineering-decisions.md).

## How the deployment is wired

- **Frontend** (Next.js 15) and **backend** (FastAPI + asyncpg) are separate
  Railway services in the same project. Postgres is a managed Railway plugin.
- `NEXT_PUBLIC_API_URL` points the frontend at the FastAPI service.
- `PLAID_ENV=sandbox` and the sandbox `PLAID_CLIENT_ID` / `PLAID_SECRET` keep
  the demo isolated from any production Plaid items.
- `NEXT_PUBLIC_HIDE_BOT_TAB=true` and the absence of `TELEGRAM_BOT_TOKEN`
  hide the Telegram bot UI.

If you want to run it locally, follow [`README.md`](README.md) — the only
delta from the demo is what env vars you set.

## Stack

- Python 3.12, FastAPI, Uvicorn, asyncpg, APScheduler, python-telegram-bot v22
- Next.js 15, React 19, TypeScript, Tailwind 4, Radix UI primitives, TanStack Query
- PostgreSQL on Railway, Plaid sandbox for bank connectivity

## Contact

Source repo and full discussion threads available on request.
