# Budget Pet

<a href="https://www.loom.com/share/e9eba267ccd24963a013de2d6e3079c6">
  <img src="https://cdn.loom.com/sessions/thumbnails/e9eba267ccd24963a013de2d6e3079c6-with-play.gif" width="640" alt="Watch the 5-minute walkthrough on Loom">
</a>

Family budget app: **FastAPI** backend, **Next.js** frontend, **PostgreSQL** (asyncpg) on Railway. **Plaid** is the source of truth for linked banks, transactions, categories (PFC), recurring streams, liabilities, and investments.

> 🎥 **[Watch the 5-minute walkthrough on Loom](https://www.loom.com/share/e9eba267ccd24963a013de2d6e3079c6)** — live demo + code tour.
>
> 📺 **Live sandbox demo (no Telegram bot):** see [`DEMO.md`](DEMO.md) for the URL, login, and Plaid Sandbox walkthrough.
>
> 🧠 **Engineering decisions log:** [`docs/engineering-decisions.md`](docs/engineering-decisions.md) — the design calls behind the codebase, with the trade-offs.

## Documentation

Authoritative specs live in [`docs/`](docs/README.md):

- [`docs/architecture.md`](docs/architecture.md) — modules, data flow, Railway envs, encryption-at-rest
- [`docs/api.md`](docs/api.md) — HTTP API
- [`docs/data-model.md`](docs/data-model.md) — tables and invariants
- [`docs/plaid.md`](docs/plaid.md) — Plaid products, sync, access-token encryption
- [`docs/reports-math.md`](docs/reports-math.md) — income/expense classification rules
- [`docs/insights-math.md`](docs/insights-math.md) — insights feed math

Legacy V1 docs: [`docs/archive/v1/`](docs/archive/v1/README.md) (reference only).
Working with this codebase via Claude / agents: see [`CLAUDE.md`](CLAUDE.md).

## Stack

| Layer | Technology |
|--------|------------|
| API | Python 3.12, FastAPI, Uvicorn |
| Web UI | Next.js 15, React 19, TypeScript, Tailwind CSS 4, TanStack Query |
| DB | PostgreSQL, asyncpg |
| Hosting | Railway (FastAPI hosts the in-process Telegram bot too + Next.js + Postgres) |

## Local development

1. Python: create a venv, install deps, configure `.env` from [`.env.template`](.env.template) (database URL, `ADMIN_LOGIN` / `ADMIN_PASSWORD`, optional Plaid keys).

    ```bash
    # Runtime only (what ships in the Docker image):
    pip install -r requirements.txt
    # Runtime + test / CI tooling (pytest, httpx, coverage):
    pip install -r requirements-dev.txt
    ```

2. Run API (watch only `web/` so edits under `tests/` do not restart the server and re-run migrations):

```bash
PYTHONPATH=. uvicorn web.main:app --reload --reload-dir web --host 127.0.0.1 --port 8000
```

3. Frontend (`frontend/`): `npm install`, set `NEXT_PUBLIC_API_URL`, then `npm run dev`.

## Tests (release gate)

Run V2 API tests and auth tests before merging:

```bash
pytest tests/v2 tests/test_auth_routes.py tests/test_auth_users.py -q
```

Plaid and domain logic should be covered in `tests/v2/` only.

## Railway checklist (short)

The project (`protective-clarity` on Railway) hosts two environments:

| Environment | Branch | Purpose |
|---|---|---|
| `production` | `main` | Real Plaid, real users; auto-deploys on merge |
| `demo` | `demo` | Plaid sandbox + reviewer login `demo` / `demo_pass` |

Per service:

- **FastAPI**: `DATABASE_URL=${{Postgres-DB.DATABASE_URL}}` (templated — required so `POSTGRES_PASSWORD` rotations propagate). Set `ADMIN_LOGIN`, `ADMIN_PASSWORD`, session-related vars per [`docs/architecture.md`](docs/architecture.md). Plaid: `PLAID_CLIENT_ID`, `PLAID_SECRET`, `PLAID_ENV`. Encryption: `PLAID_ENCRYPTION_KEY` (generate once with `Fernet.generate_key()`, never rotate — see [`docs/plaid.md#access-token-encryption-at-rest`](docs/plaid.md#access-token-encryption-at-rest)). Optional: `PLAID_SDK_TIMEOUT` (default 90s), `PLAID_WEBHOOK_URL`.
- **Telegram bot** (optional): `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`, `OPENAI_API_KEY` (for receipt OCR). Bot runs in-process inside FastAPI — there is no separate worker. See [`docs/bot.md`](docs/bot.md) for `setWebhook` instructions.
- **Next.js**: `NEXT_PUBLIC_API_URL` pointed at the FastAPI public URL. `CORS_ORIGINS` on FastAPI must include this origin (cookies + credentials).
