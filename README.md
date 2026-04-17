# Budget Pet (V2)

Family budget app: **FastAPI** backend, **Next.js** frontend, **PostgreSQL** (asyncpg) on Railway. **Plaid** is the source of truth for linked banks, transactions, categories (PFC), recurring streams, liabilities, and investments.

## Documentation

Authoritative specs live in [`docs/`](docs/README.md):

- [`docs/architecture.md`](docs/architecture.md) — modules and data flow  
- [`docs/api.md`](docs/api.md) — HTTP API  
- [`docs/data-model.md`](docs/data-model.md) — tables and invariants  
- [`docs/plaid.md`](docs/plaid.md) — Plaid products and sync  

Legacy V1 docs: [`docs/archive/v1/`](docs/archive/v1/README.md) (reference only).

## Stack

| Layer | Technology |
|--------|------------|
| API | Python 3.11, FastAPI, Uvicorn |
| Web UI | Next.js 15, React 19, TypeScript, Tailwind CSS 4, TanStack Query |
| DB | PostgreSQL, asyncpg |
| Hosting | Railway (FastAPI + Next.js + optional Telegram bot) |

## Local development

1. Python: create a venv, `pip install -r requirements.txt`, configure `.env` from [`.env.template`](.env.template) (database URL, `ADMIN_LOGIN` / `ADMIN_PASSWORD`, optional Plaid keys).

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

- Set Postgres and point `DATABASE_URL` at the API service.  
- Set `ADMIN_LOGIN`, `ADMIN_PASSWORD`, session-related vars per [`docs/architecture.md`](docs/architecture.md).  
- Configure `NEXT_PUBLIC_API_URL` for the Next.js service.  
- Plaid: set `PLAID_CLIENT_ID`, `PLAID_SECRET`, `PLAID_ENV`; register webhook URL if using webhooks (see [`docs/plaid.md`](docs/plaid.md)).  
- Optional: `CORS_ORIGINS` — comma-separated origins for browser API access (cookies + credentials).

## Out of scope in this README

Telegram bot (`bot.py`, `services/`) may still target older APIs; migrate in a separate effort.
