---
name: budget-pet-v2
description: "Budget Pet V2.0 — family budget monorepo (FastAPI, Next.js, PostgreSQL/asyncpg, Railway) with Plaid as the source of truth for accounts, transactions, categories, recurring streams, and investments. Use when implementing, refactoring, or debugging code under web/, frontend/, tests/v2/, Plaid sync/scheduler, budgets, reports, tags, piggy goals, auth/sessions, or data migrations; when explaining product goals or system behavior; or when requirements are ambiguous and must be grounded in repository documentation. Authoritative specs live in docs/ at repo root (ignore docs/archive/v1 unless explicitly comparing to V1). Also consult .cursor/rules/project-overview.mdc for stack-wide conventions."
---

# Budget Pet V2

## What this skill is for

Give another agent **fast, correct orientation** in this codebase: product intent, where truth lives, and how to change code without fighting the architecture.

## Product intent (V2)

- **Plaid-first**: bank-linked accounts, transactions, PFC-backed categories, recurring, liabilities, investments flow from Plaid sync into unified V2 tables.
- **Family / multi-user**: DB-backed sessions; owner-managed users (see docs and auth module).
- **Single app surface**: REST API (`web/`), web UI (`frontend/`), Telegram bot (migration in progress — see `bot.py` / `services/`).
- **Manual / cash** (when implemented): same `transactions` row model; details evolve — verify `docs/` and current routes, not memory.

## Authoritative documentation (read before guessing)

| Need | Open in repo |
|------|----------------|
| Index of all V2 docs | `docs/README.md` |
| Modules, stack, Plaid data flow | `docs/architecture.md` |
| HTTP API contract | `docs/api.md` |
| Tables, columns, invariants | `docs/data-model.md` |
| Plaid products, sync, field mapping, sandbox | `docs/plaid.md` |
| V1 only (historical) | `docs/archive/v1/` — **not** default source of truth |

If a detail is not in `docs/`, treat it as unknown or verify in code; prefer adding/clarifying `docs/` over improvising.

## Working workflow

1. **Scope**: Identify layer — `web/<module>/`, `frontend/src/`, `tests/v2/`, `web/migrations/`.
2. **Spec**: Read the smallest set of rows from [references/docs-index.md](references/docs-index.md) for the task, then open the linked `docs/*.md` files.
3. **Conventions**: Match existing patterns in the target module; new features = **new focused module** (not giant files). DB access = **`asyncpg` via `web/db.py` pool only**.
4. **Tests**: Add or extend `tests/v2/` for behavior changes.
5. **Plaid**: Never assume undocumented Plaid fields — cross-check `docs/plaid.md` and `web/plaid/`.

## Non-negotiables (check before merging)

- **Docs first** for API shape, tables, and Plaid behavior.
- **No psycopg2** — asyncpg only.
- **`transactions.source`**: values and report rules are defined in docs and code — read `docs/data-model.md` and grep `source` in `web/` when touching reports, budgets, or imports.
- **Sandbox**: `plaid_sandbox` handling may differ between list vs aggregates — verify budgets, reports, and cleanup flows in code if you change filters.

## When to load references

- Use [references/docs-index.md](references/docs-index.md) as a **routing table** (task → file).
- Do not mirror full architecture in the skill; keep the skill lean and send the agent to `docs/`.
