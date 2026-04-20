# Budget Rollover + Spending-vs-Limit History — Design

Status: Draft (for review)
Scope: Settings → Budgets + Reports → Cash Flow
Stack touched: `web/budgets/`, `web/migrations/`, `frontend/src/components/budgets/`, `frontend/src/components/reports/`, `frontend/src/app/reports/page.tsx`, `frontend/src/lib/api.ts`, `frontend/src/types/v2.ts`, `tests/v2/`

## 1. Motivation

Two user-facing gaps in the current V2 budgets surface:

1. **No way to carry a monthly limit forward.** A user who sets `$200` for "Shops" in April must re-enter the same limit in May, June, July. For predictable categories (rent, subscriptions, groceries) this is friction with no upside.
2. **No historical view of limit vs actual.** The Reports → Cash Flow tab shows income/expense history but has no way to answer "did I spend less on Shops in January than this month?" — even though the underlying data (budgets, classified expenses) already exists.

Only the **limit** is part of the rollover product promise. Remainders and spent totals never carry forward — each month is its own envelope.

## 2. Scope

In scope:

- Per-row `rollover` flag on `category_budgets`.
- Lazy materialization of next-month rows when the user views that month.
- UI affordance in Settings → Budgets (Add / Edit dialogs + card badge).
- New `GET /api/budgets/history` endpoint reusing existing progress math.
- New "Spending vs limit — 12 months" section in Reports → Cash Flow tab.
- Tests in `tests/v2/` for repo + route behavior.

Out of scope:

- Rollover of *remaining balance* (explicit non-goal; doc body states "limit only").
- Cross-category redistribution.
- Auto-suggestion of limits from past actuals.
- Editing rollover values in bulk.
- Telegram bot surface (API is stack-agnostic; bot can pick it up later).

## 3. Data model

### 3.1 Migration

Idempotent additive column on the existing table:

```sql
ALTER TABLE category_budgets
  ADD COLUMN IF NOT EXISTS rollover BOOLEAN NOT NULL DEFAULT FALSE;
```

- `FALSE` default preserves behavior for every existing row.
- Applied via the same auto-migration path in `web/migrations/v2_init.py` (additive ALTER list). No destructive changes.

### 3.2 Invariants

- `rollover` is a per-row property. Turning it on for "Shops / 2026-04" does not retroactively create rows for earlier months.
- Enabling `rollover` on row M guarantees row M+1 will be materialized **on first read** of M+1. It does not promise M+2, M+3 — the chain is carried forward by the newly materialized row (which is also created with `rollover = TRUE`).
- The chain breaks if any intermediate row has `rollover = FALSE` or is deleted. Opening a month more than one step past the last rollover-enabled row **does not** skip-forward-materialize; the user is expected to move through months in order, and this keeps the semantics of a deleted month = explicit "stop" intact.
- Hierarchy conflict rules (parent vs child budget mutual exclusion, `web/budgets/repo.py::create_budget`) are **not** re-checked during materialization: the previous month was already valid, and categories do not change structure over time.

## 4. Lazy materialization

### 4.1 Algorithm

On entry to `BudgetsRepository.get_progress(month, ...)` and `BudgetsRepository.list_budgets(month)` (when `month` is provided), execute a single idempotent SQL statement **before** the main query:

```sql
INSERT INTO category_budgets (category_id, month, budget_cents, rollover)
SELECT prev.category_id, $1, prev.budget_cents, TRUE
FROM category_budgets prev
WHERE prev.rollover = TRUE
  AND prev.month = to_char(($1 || '-01')::date - INTERVAL '1 month', 'YYYY-MM')
  AND NOT EXISTS (
    SELECT 1 FROM category_budgets cur
    WHERE cur.category_id = prev.category_id AND cur.month = $1
  )
ON CONFLICT (category_id, month) DO NOTHING;
```

- Single round-trip, no app-side logic.
- `ON CONFLICT` is a belt-and-suspenders guard against racing family members opening the same month in parallel.
- Wrapped in a new private method `BudgetsRepository._ensure_rollovers(conn, month)` called from both `get_progress` and `list_budgets(month=...)` inside the same connection acquire to avoid double-acquire.

### 4.2 Edits and deletes

- `PATCH /api/budgets/{id} { budget_cents }` on row M only mutates M. If M+1 is already materialized, its `budget_cents` stays. Users who want cascading edits delete M+1 manually — it will re-materialize from the updated M at next view.
- `PATCH /api/budgets/{id} { rollover }` toggles the flag on the current row only. Effect is visible on the next open of M+1.
- `DELETE /api/budgets/{id}` on row M breaks the chain going forward (since M+1 no longer has a previous row with `rollover = TRUE` unless it was also materialized).

## 5. API

### 5.1 Existing endpoint changes

`POST /api/budgets` — request body gains optional `rollover: bool = False`.
`PATCH /api/budgets/{id}` — request body gains optional `rollover: Optional[bool] = None`.
`GET /api/budgets` — response items include `rollover: bool`.
`GET /api/budgets/progress` — response items include `rollover: bool`; runs materialization first.

### 5.2 New endpoint: budget history

`GET /api/budgets/history`

Query params:

- `months: int = 12` (range 1..24).
- `category_ids: str | None` — comma-separated ints. Omitted = all categories with at least one budget in the window.

Response:

```json
[
  {
    "category_id": 12,
    "category_name": "Shops",
    "category_color": "#3b82f6",
    "months": [
      { "month": "2025-05", "budget_cents": 20000, "actual_cents": 18500 },
      { "month": "2025-06", "budget_cents": null,  "actual_cents": 22100 }
    ]
  }
]
```

- Window is `[today - months, today]` anchored to month starts, inclusive, returned in ascending month order.
- `budget_cents = null` when no budget row exists for that (category, month) pair; `actual_cents` is still populated from classified expenses.
- Ordering: categories sorted by `category_name`; each category's `months` array always spans the full window (missing months included with `budget_cents: null`).
- Respects `reports_include_plaid_sandbox()` and `viewer_user_id` (same filters as `get_progress`).

### 5.3 Repository changes

New method `BudgetsRepository.get_history(months, category_ids, viewer_user_id)` in `web/budgets/repo.py`:

- Reuses the CTE shape of `get_progress` but aggregates across the full `[start, end)` date range and groups by `(category_id, month_bucket)` where `month_bucket = to_char(COALESCE(authorized_date, date), 'YYYY-MM')`.
- Joins against a generated `months` series (e.g. `generate_series(start::date, end::date, '1 month')`) to produce a row for every (category, month) in the window even when spend or budget is zero.
- Filters category scope via `category_id = ANY($2)` when `category_ids` is non-empty.

Budget values are taken from `category_budgets` directly (not materialized for missing months — the history endpoint never mutates data).

## 6. Frontend

### 6.1 Settings → Budgets (`frontend/src/components/budgets/budgets-view.tsx`)

**Add dialog:** new checkbox below the Amount field.

- Label: "Roll over limit to next month"
- Helper text: "On the first of each month, the same limit is recreated automatically. Spent amounts and remainders do not roll over."
- State: `createRollover: boolean` (default `false`).
- Sent as `rollover` in the `POST /api/budgets` body.

**Edit dialog:** same checkbox, initialized from `editRow.rollover`, sent as `rollover` in `PATCH /api/budgets/{id}`.

**BudgetCard indicator:** when `row.rollover === true`, render a small `RefreshCw` (lucide) icon next to `CardTitle`:

- Size `size-3.5`, `text-muted-foreground`.
- Wrapped in shadcn `<Tooltip>` with content "Rolls over to next month automatically".
- Placed **before** the `Parent` badge when both are present.

**Types** (`frontend/src/types/v2.ts`): add `rollover: boolean` to both `Budget` and `BudgetProgress`.

**API client** (`frontend/src/lib/api.ts`):

- `budgetsApi.create` accepts `{ category_id, month, budget_cents, rollover? }`.
- `budgetsApi.update` accepts `{ budget_cents?, rollover? }`.
- New `budgetsApi.getHistory({ months, category_ids? })` hitting `/api/budgets/history`.

### 6.2 Reports → Cash Flow (`frontend/src/app/reports/page.tsx`)

New section rendered **inside** the existing Cash Flow tab `CardContent`, immediately after the "12-month history" block:

- Component: `BudgetHistorySection` imported from `frontend/src/components/reports/budget-history-section.tsx` (new focused module per user_rules).
- Props: none (self-contained; fetches its own data via React Query).

### 6.3 `BudgetHistorySection` component

State:

- `activeCategoryIds: number[]` — default: first 3 (alphabetical) returned by API. Persisted in URL param `budget_history_categories` for shareable links.
- `hoveredMonthIndex: number | null` — for tooltip.

Data:

- React Query `["reports", "budget-history", 12]` → `budgetsApi.getHistory({ months: 12 })`. Returns every category with a budget in window; user filters client-side with chips.

Layout (top → bottom inside the section):

1. **Header row:** `h3 text-sm font-medium` "Spending vs limit" on the left, `text-xs text-muted-foreground` "Last 12 months" on the right.
2. **Chip picker row:** horizontally scrollable `flex gap-1.5 flex-wrap`. Each chip = rounded-full button:
   - Active: `bg-muted text-foreground` + `size-2 rounded-full` dot (category color) + name + `X` icon.
   - Inactive: `border border-dashed border-border/60 text-muted-foreground` + dot + name.
   - Click toggles membership in `activeCategoryIds`.
3. **SVG line chart** (`viewBox="0 0 100 42"`, `h-48 w-full`, `preserveAspectRatio="none"`):
   - Background grid: 3 horizontal lines at y=0, 21, 42, `stroke-muted stroke-width="0.1"`.
   - Y-axis labels on the right: max / mid / 0, `text-[10px] text-muted-foreground`.
   - For each active category:
     - Gradient fill below actual line (`linearGradient` from `category_color` @ 0.12 opacity → 0).
     - Actual: solid path, `strokeWidth="0.6"`, `stroke=category_color`, `vector-effect="non-scaling-stroke"`, `stroke-linejoin="round"`, `stroke-linecap="round"`.
     - Limit: dashed path, same stroke, `stroke-dasharray="2 1.5"`, `fill="none"`. Months with `budget_cents === null` produce gaps (path breaks).
     - Circle markers on actual line only: `r="0.9"`, `fill=category_color`.
   - Vertical guide: invisible hover zones (transparent `<rect>` per month) that set `hoveredMonthIndex`; on hover, render `line` from y=0 to y=42, `stroke-muted-foreground/40 stroke-width="0.15"`.
4. **Tooltip** (absolutely positioned popover above the chart area when `hoveredMonthIndex != null`): list of active categories for that month, each row `color dot | name | spent | / limit | % used`. `bg-popover border rounded-md shadow-md text-xs p-2`.
5. **X-axis labels:** month short names (Jan, Feb...), `text-[10px] text-muted-foreground`, evenly spaced under the chart.
6. **Summary mini-table:** one row per active category.
   - Columns: `Category | Avg spent | Avg limit | This month % used`.
   - Styles mirror the "By Category" table: `border-border/60`, `bg-muted/40` header, `tabular-nums`, `text-sm`.
   - "Avg limit" is `null` (`—`) when a category had no budgets in any month (defensive; normally impossible because the API only returns categories that had a budget in window).
7. **Empty states:**
   - API returned no categories → render a centered `PiggyBank` icon (lucide, `size-6 text-muted-foreground` in a `size-12 rounded-full bg-muted` wrapper) + "Set a budget in Settings → Budgets to track spending trends." + a secondary button linking to `/settings/budgets`.
   - API returned categories but none active → single-line hint "Select at least one category above." with subdued chart background.

Loading: `text-muted-foreground text-sm` "Loading history…" inside the chart slot.
Error: `text-destructive text-sm` "Could not load budget history."

## 7. Error handling

- Invalid `category_ids` (non-int tokens): return `400 Bad Request`.
- `months` out of range: `422 Unprocessable Entity` via Pydantic validator (matching existing pattern for `/reports/cash-flow/history`).
- Materialization failures (exceedingly unlikely): logged via `logger.warning` and **swallowed** — the user still sees `get_progress` results without carry-over rows rather than a 500. This is aligned with the V2 pattern of failing soft on non-critical background work.
- Session/viewer filtering: unchanged — endpoint requires auth, `viewer_user_id` derived from `request.state.user`.

## 8. Testing

New test module: `tests/v2/test_budgets_rollover.py`.

Cases (repo-level, using `AsyncMock`-based pool pattern from `tests/v2/test_category_hierarchy.py`):

1. `_ensure_rollovers`: row with `rollover=TRUE` in M-1 and no row in M → inserts new row with same `budget_cents` and `rollover=TRUE`.
2. `_ensure_rollovers`: row with `rollover=FALSE` in M-1 → no insert.
3. `_ensure_rollovers`: M already has a row → no insert (idempotency).
4. `_ensure_rollovers`: chain break — M-2 has rollover, M-1 has none → opening M yields nothing (we only look one step back).
5. `get_progress(M)` returns the newly materialized row.
6. `update_budget(id, { rollover: True })` flips the flag.
7. `create_budget` accepts `rollover` in payload.

New test module: `tests/v2/test_budgets_history.py`.

Cases:

1. `get_history` returns every month in window even when a category had no budget or no spending that month (`budget_cents: null`, `actual_cents: 0`).
2. `category_ids` filter narrows the result.
3. Month bucketing uses `COALESCE(authorized_date, date)` (regression guard mirroring the `get_progress` invariant).
4. `is_private` rows from another user are excluded when `viewer_user_id` is set.
5. `plaid_sandbox` respected via `reports_include_plaid_sandbox()`.

Route-level smoke test for `GET /api/budgets/history` — validates 200 response shape and 422 on out-of-range `months`.

## 9. Docs updates

- `docs/api.md` — append `rollover` field to Budgets section; add `GET /api/budgets/history` row.
- `docs/data-model.md` — note the new `rollover` column and materialization semantics under the `category_budgets` section.

## 10. Rollout

- Migration is additive (safe to deploy before frontend).
- Frontend gracefully handles absence of `rollover` in response (treats as `false`) and of `/api/budgets/history` (shows error state) — so there is no ordered deploy requirement, but the natural order is backend → frontend.
- No feature flags needed; the surface area is new and opt-in (user has to check the box).

## 11. Open questions

None at the time of writing. If performance of the history endpoint becomes a concern for households with many budgeted categories, we can cache the result per `(viewer_user_id, months)` for a few minutes in memory; not needed for v1.
