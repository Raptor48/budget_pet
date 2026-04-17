# Budget Pet V2 — doc routing

Read paths relative to **repository root**. Top-level `docs/*.md` is current V2 unless noted.

| Task / question | Primary doc | Also check |
|----------------|-------------|------------|
| Routers, modules, sync pipeline | `docs/architecture.md` | `web/main.py`, `web/plaid/` |
| Endpoint paths, methods, auth | `docs/api.md` | Route files under `web/*/` |
| Table columns, FKs, invariants (splits sum, etc.) | `docs/data-model.md` | `web/migrations/v2_init.py` |
| Link token, exchange, sync, PFC mapping, sandbox | `docs/plaid.md` | `web/plaid/client.py`, `web/plaid/repo.py` |
| Local run, doc index | `docs/README.md` | `start_local.sh` |
| Cursor-wide stack summary | `.cursor/rules/project-overview.mdc` | (may lag code; prefer `docs/` on conflict) |

**Search hints** (ripgrep from repo root):

- `transactions.source` → `web/transactions/`, `web/budgets/`, `web/reports/`
- `AuthMiddleware` / sessions → `web/auth/`
- `get_pool` / asyncpg → `web/db.py`, `web/*/repo.py`
