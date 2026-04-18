# Budget Pet V2 — Tests

Mock-based pytest suite covering the V2 FastAPI backend
(Plaid sync, transactions, categories, budgets/reports, recurring,
merchant rules, auth). No real database required — asyncpg pools and
connections are mocked via `tests/v2/conftest.py::make_mock_pool`.

Authoritative product specs live in `docs/`. This file only documents
how to run and add tests.

## Layout

```
tests/
├── conftest.py              # legacy fixtures (kept for root-level tests)
├── test_auth_routes.py      # auth API endpoints
├── test_auth_users.py       # user/session logic
└── v2/
    ├── conftest.py          # make_mock_pool, make_record
    ├── test_accounts*.py            # accounts list, cash wallet, PATCH balance
    ├── test_categories.py           # category CRUD + resolve_category
    ├── test_category_hierarchy.py   # parent/child rollup
    ├── test_plaid_*.py              # sync, webhook, purge, PFC version, link token
    ├── test_recurring*.py           # streams + manual create
    ├── test_reports*.py             # cash flow, by-category, sandbox filter
    ├── test_transaction_*.py        # display_title, privacy, splits, bulk enrich, date range, manual
    ├── test_merchant_rules_*.py     # key building + display_title fallback
    ├── test_net_worth.py
    ├── test_insights_feed.py
    └── test_env_flags_sandbox.py
```

## Stack

- `pytest` with `asyncio_mode = auto` (see `pytest.ini`)
- `unittest.mock.AsyncMock` / `MagicMock` for asyncpg pool + connection
- No network, no Postgres, no Plaid — everything stubbed

## Run

```bash
# Full V2 suite
python3 -m pytest tests/v2/

# Single file
python3 -m pytest tests/v2/test_merchant_rules_fallback.py

# Single test, verbose
python3 -m pytest tests/v2/test_reports.py::test_cash_flow_sums -v

# Everything (V2 + legacy auth tests)
python3 -m pytest
```

`pytest.ini` already sets `-v --tb=short --strict-markers
--disable-warnings`, so no extra flags are needed.

## Writing a new test

1. Put it under `tests/v2/` next to the closest existing module
   (`test_<feature>.py`). Create a new file only for a new feature
   area — do not grow existing files past ~50 lines per function.
2. Build a mock pool:

   ```python
   from unittest.mock import AsyncMock
   from tests.v2.conftest import make_mock_pool, make_record

   async def test_something(monkeypatch):
       conn = AsyncMock()
       conn.fetchrow.return_value = make_record(id=1, name="Netflix")
       pool = make_mock_pool(conn)
       monkeypatch.setattr("web.db.get_pool", AsyncMock(return_value=pool))
       ...
   ```
3. For repo-level SQL-shape assertions, prefer calling the function
   directly and asserting on the captured `conn.fetch*` call args
   (SQL string + params) rather than hitting a real database.
4. Every new feature or fix MUST land with a matching test — the
   project rule is no silent behaviour changes.

Keep tests hermetic (no network, no filesystem state, no live DB)
so they can run anywhere, including Railway builds, without secrets.
