/**
 * V2 TypeScript type definitions — exactly matching the Plaid API fields
 * and V2 backend response models.
 */

// ---------------------------------------------------------------------------
// Members (family users)
// ---------------------------------------------------------------------------

export interface Member {
  id: number;
  username: string;
}

// ---------------------------------------------------------------------------
// Accounts
// ---------------------------------------------------------------------------

export interface Account {
  id: number;
  plaid_account_id: string | null;
  plaid_item_id: string | null;
  name: string;
  official_name: string | null;
  mask: string | null;
  /** depository | credit | loan | investment | other */
  type: string;
  subtype: string | null;
  current_balance_cents: number;
  available_balance_cents: number | null;
  credit_limit_cents: number | null;
  apr_percent: string | null;
  /** User-entered fallback for credit_limit. Shown only when credit_limit_cents is null. */
  credit_limit_cents_manual: number | null;
  /** User-entered fallback for APR. Shown only when apr_percent is null. */
  apr_percent_manual: string | null;
  /** Liability fields Plaid did not return on the last sync, e.g. ["apr","credit_limit"]. */
  plaid_missing_fields: string[];
  min_payment_cents: number | null;
  due_day: number | null;
  is_overdue: boolean | null;
  last_payment_date: string | null;
  last_statement_balance_cents: number | null;
  expected_payoff_date: string | null;
  ytd_interest_paid_cents: number | null;
  currency: string;
  holder_category: string | null;
  is_active: boolean;
  last_synced_at: string | null;
  created_at: string;
  updated_at: string;
  /** Institution branding from plaid_items (may be null if not available) */
  institution_name: string | null;
  institution_logo: string | null;
  /** Hex color, e.g. "#004966" */
  institution_color: string | null;
  /** FK to users.id — who owns this account */
  user_id: number | null;
  /** Username of the owner (joined from users) */
  owner_username: string | null;
  /** True when this row is the per-user manual Cash wallet (no Plaid link). */
  is_cash_wallet?: boolean;
}

// ---------------------------------------------------------------------------
// Categories
// ---------------------------------------------------------------------------

export interface Category {
  id: number;
  name: string;
  plaid_pfc_primary: string | null;
  plaid_pfc_detailed: string | null;
  color: string;
  icon: string | null;
  pfc_icon_url: string | null;
  /** plaid_pfc = from Plaid sync; custom = user-created */
  source: "plaid_pfc" | "custom";
  created_at: string;
  /** FK to categories.id; null = top-level primary (depth ≤ 2 enforced). */
  parent_id: number | null;
  /**
   * Family-wide flag: when TRUE, transactions in this category count as
   * income everywhere in the app (Income tab, Cash Flow, Financial Health).
   * Defaults are seeded from Plaid PFC=INCOME; any family member can toggle.
   */
  is_income: boolean;
}

// ---------------------------------------------------------------------------
// Tags
// ---------------------------------------------------------------------------

export interface Tag {
  id: number;
  name: string;
  color: string;
  created_at: string;
}

export interface MerchantRule {
  id: number;
  merchant_key: string;
  display_label: string;
  category_id: number;
  category_name: string;
  /**
   * Optional substring filter (lower-cased on the server) that narrows the
   * rule to transactions whose ``name`` or ``display_title`` contains the
   * value. Null means "match every transaction with this merchant_key" —
   * the legacy behavior. See ``docs/categorization-precedence.md`` §3.
   */
  description_contains?: string | null;
}

export interface MerchantRulePreviewResult {
  /** Number of transactions that would be updated *with this category*. */
  eligible_count?: number | null;
  skipped_splits_count?: number | null;
  skipped_custom_category_count?: number | null;
  skipped_has_entity_id_count?: number | null;
  sample_merchant_names: string[];
  /** Category-less match count (only present when preview was called without category_id). */
  match_count?: number | null;
  /**
   * Distinct ``name`` values for this merchant in the table. Used by the
   * smart popover to decide whether to surface the "narrow with
   * description" affordance — showing it for a merchant with only one
   * distinct description would be noise.
   */
  distinct_description_count?: number | null;
  merchant_key?: string | null;
  display_label?: string | null;
}

export interface MerchantRuleApplyResult extends MerchantRulePreviewResult {
  updated_count: number;
  description_contains?: string | null;
}

// ---------------------------------------------------------------------------
// Transactions
// ---------------------------------------------------------------------------

export interface Counterparty {
  name: string;
  entity_id: string | null;
  /** merchant | financial_institution | payment_app | marketplace */
  type: string;
  website: string | null;
  logo_url: string | null;
  confidence_level: string;
}

export interface Location {
  address: string | null;
  city: string | null;
  region: string | null;
  postal_code: string | null;
  country: string | null;
  lat: number | null;
  lon: number | null;
  store_number: string | null;
}

export interface PaymentMeta {
  reference_number: string | null;
  ppd_id: string | null;
  payee: string | null;
  payer: string | null;
  payment_method: string | null;
  payment_processor: string | null;
  reason: string | null;
}

export interface TransactionSplit {
  id: number;
  parent_transaction_id: number;
  category_id: number | null;
  tag_id: number | null;
  amount_cents: number;
  note: string | null;
  created_at: string;
}

/**
 * Canonical classification of a transaction for reports / budgets / health
 * math. Materialized on the server in ``transactions.transaction_class``;
 * see ``docs/reports-math.md`` for the four-class definition and the rule
 * priority the classifier uses.
 *
 *  - "income"             — money flowing in from outside the family
 *  - "expense"            — money flowing out to an external party
 *  - "internal_transfer"  — money moving between the family's own tracked
 *                           accounts (CC payment, Zelle between spouses,
 *                           savings-to-checking sweep, …). Excluded from
 *                           both income and expense totals.
 *  - "uncategorized"      — classifier declined to pick a class (rare —
 *                           surfaces in the owner-only diagnostics page).
 */
export type TransactionClass =
  | "income"
  | "expense"
  | "internal_transfer"
  | "uncategorized";

export interface Transaction {
  id: number;
  plaid_transaction_id: string | null;
  account_id: number;
  category_id: number | null;
  amount_cents: number;
  currency: string;
  date: string;
  authorized_date: string | null;
  datetime: string | null;
  authorized_datetime: string | null;
  name: string;
  merchant_name: string | null;
  merchant_entity_id: string | null;
  logo_url: string | null;
  website: string | null;
  /** online | in store | other */
  payment_channel: string | null;
  pfc_primary: string | null;
  pfc_detailed: string | null;
  /** VERY_HIGH | HIGH | MEDIUM | LOW | UNKNOWN */
  pfc_confidence: string | null;
  pfc_icon_url: string | null;
  counterparties: Counterparty[] | null;
  location: Location | null;
  payment_meta: PaymentMeta | null;
  is_pending: boolean;
  is_private: boolean;
  /**
   * True when the transaction is a transfer between family members (e.g.
   * Zelle between spouses). Excluded from every income/expense aggregate
   * across the app, so the same dollar isn't counted twice.
   *
   * Legacy mirror of `transaction_class === "internal_transfer"`. Prefer
   * reading `transaction_class` directly; this boolean is kept for older
   * UI code paths that only care whether a row counts as a transfer.
   */
  is_internal_transfer: boolean;
  /**
   * True when a user explicitly toggled `is_internal_transfer`. The auto
   * re-classifier (run after editing the names list or via explicit rescan)
   * skips rows with this flag so manual decisions are preserved.
   *
   * Legacy sentinel — succeeded by `manual_class_override` (which can pin a
   * row to any of the four classes, not just internal_transfer).
   */
  is_internal_transfer_manual: boolean;
  /**
   * Canonical class of the transaction. Read this instead of
   * `is_internal_transfer` whenever possible.
   */
  transaction_class: TransactionClass;
  /**
   * When non-null, the user pinned this row to a specific class and the
   * auto-classifier never touches it again. `null` means "auto" — the
   * classifier is in charge and re-evaluates on every sync.
   */
  manual_class_override: TransactionClass | null;
  /** plaid | plaid_sandbox | manual | cash */
  source: string;
  user_note: string | null;
  created_at: string;
  updated_at: string;
  tags: Tag[];
  has_splits: boolean;
  /**
   * True when a receipt is attached to this transaction. Drives the
   * receipt-icon affordance in the list + an expandable lines breakdown
   * in the detail modal. The receipt payload itself is fetched on demand.
   */
  has_receipt: boolean;
  splits: TransactionSplit[];
  /** Joined from accounts table */
  account_name: string | null;
  /** Last 4 digits of the card, e.g. "4242" */
  account_mask: string | null;
  /** Username of the account owner (joined via accounts.user_id → users) */
  owner_username: string | null;
  /** Derived display title — short, human-friendly. Server-computed via web/transactions/display.py.
   * When ``merchant_alias`` is set, the server overrides this field with the alias on read. */
  display_title?: string | null;
  /** User-chosen merchant rename (e.g. "Nyflower" → "Rent"). NULL when no alias is set.
   * The server already layers this onto ``display_title``; the field is exposed so the UI
   * can render an "aliased" affordance and expose a quick revert. */
  merchant_alias?: string | null;
}

export interface TransactionFilters {
  month?: string;
  account_id?: number;
  category_id?: number;
  /**
   * Roll a primary PFC bucket up: include the parent itself PLUS every
   * detailed PFC child linked via `categories.parent_id`. Mirrors the
   * COALESCE rule used in /api/reports/by-category so the Reports →
   * By Category drill-down sums match the primary bucket total exactly.
   * Use `category_id` for the exact row (no roll-up), `parent_category_id`
   * for the primary bucket.
   */
  parent_category_id?: number;
  tag_id?: number;
  search?: string;
  channel?: string;
  pending_only?: boolean;
  /** Filter by account owner user_id */
  user_id?: number;
  /**
   * Filter by canonical class (powers the Income / Expenses tab drill-downs
   * and the diagnostics page).
   */
  transaction_class?: TransactionClass;
  /**
   * When true, excludes rows with `transaction_class === 'internal_transfer'`
   * from the response. Backs the "Show internal transactions" toggle on the
   * Transactions page (default OFF — intra-family transfers stay hidden).
   */
  exclude_internal_transfers?: boolean;
  limit?: number;
  offset?: number;
}

/** GET /api/transactions/date-range — bounds used by the shared month/year picker. */
export interface TransactionDateRange {
  /** Earliest visible month in "YYYY-MM" format, or null when no transactions exist. */
  min_month: string | null;
  /** Latest visible month in "YYYY-MM" format, or null when no transactions exist. */
  max_month: string | null;
  /** Raw earliest date ("YYYY-MM-DD") — useful for day-level pickers later. */
  earliest: string | null;
  /** Raw latest date ("YYYY-MM-DD") — useful for day-level pickers later. */
  latest: string | null;
}

/** POST /api/transactions — cash row; server sets source, wallet, channel, currency, pending. */
export interface ManualCashTransactionCreate {
  amount_cents: number;
  date: string;
  name: string;
  category_id?: number | null;
  authorized_date?: string | null;
  merchant_name?: string | null;
  user_note?: string | null;
}

// ---------------------------------------------------------------------------
// Recurring Streams
// ---------------------------------------------------------------------------

export interface RecurringStream {
  id: number;
  plaid_stream_id: string;
  account_id: number | null;
  /** inflow | outflow */
  direction: string;
  description: string;
  merchant_name: string | null;
  /** WEEKLY | BIWEEKLY | SEMI_MONTHLY | MONTHLY | ANNUALLY | UNKNOWN */
  frequency: string | null;
  average_amount_cents: number | null;
  last_amount_cents: number | null;
  currency: string;
  pfc_primary: string | null;
  pfc_detailed: string | null;
  first_date: string | null;
  last_date: string | null;
  is_active: boolean;
  /** MATURE | EARLY_DETECTION | TOMBSTONED */
  status: string | null;
  category_id: number | null;
  user_label: string | null;
  /**
   * Signed percentage change of `last_amount_cents` vs `average_amount_cents`.
   * Positive = last payment is higher than average (got more expensive).
   * Negative = cheaper. Decoded as string by the backend (NUMERIC(6,2)).
   */
  price_change_pct: string | null;
  last_synced_at: string | null;
  /** plaid | manual — manual streams are not overwritten by Plaid sync */
  stream_source?: string;
  /**
   * User-managed lifecycle. Plaid cannot pause/cancel third-party
   * subscriptions, so we just mark intent locally. KPI sums and Insights
   * skip non-`active` rows.
   *
   * - `active` — counted in forecasts and Insights.
   * - `paused` — temporary mute; ignore for forecast, keep visible.
   * - `unsubscribed` — pending verification. User declared they cancelled
   *   at the merchant; the nightly verifier checks the next expected
   *   cycle, then either moves the row to `cancelled` (no charge → done)
   *   or fires a P0 alert (charge posted → cancellation didn't go
   *   through).
   * - `cancelled` — terminal. Hidden from the default recurring view.
   */
  user_status?: "active" | "paused" | "unsubscribed" | "cancelled";
  /** Optional auto-resume date for paused streams. */
  paused_until?: string | null;
  /** Stamped when user_status flips to `cancelled`. */
  cancelled_at?: string | null;
  /** Stamped when user_status flips to `unsubscribed`. */
  unsubscribed_at?: string | null;
  /**
   * Earliest moment the verifier is allowed to resolve an unsubscribe.
   * NULL for ANNUALLY / UNKNOWN cadences (no auto-verification).
   */
  unsubscribe_verify_after?: string | null;
  /** Last time we fired the "charge after unsubscribe" P0 alert. */
  unsubscribed_charge_alerted_at?: string | null;
  /** Hide the price-change badge / Insight until this date. */
  price_change_snoozed_until?: string | null;
  // --- Enrichment (joined, optional for backwards compatibility) ---
  /** Joined from accounts.name. */
  account_name?: string | null;
  /** Last 4 of the card / account (accounts.mask). */
  account_mask?: string | null;
  /** Owner of the account (users.username via accounts.user_id). */
  owner_username?: string | null;
  /** Primary (rolled-up) category id — always at the top of the hierarchy. */
  primary_category_id?: number | null;
  /** Primary category human name, e.g. "Rent & Utilities". */
  primary_category_name?: string | null;
  /** Primary category color (hex) for chips and dots. */
  primary_category_color?: string | null;
  /** Short, human-friendly label for the stream (normalized from description).
   * When ``merchant_alias`` is set, the server layers it onto this field. */
  display_title?: string | null;
  /** User-chosen merchant rename. Recurring rows from Plaid have no
   * merchant_entity_id so the alias is matched by ``name:<lower(merchant_name)>``. */
  merchant_alias?: string | null;
}

// ---------------------------------------------------------------------------
// Budgets
// ---------------------------------------------------------------------------

export interface Budget {
  id: number;
  category_id: number;
  month: string;
  budget_cents: number;
  created_at: string;
}

export interface BudgetProgress {
  category_id: number;
  category_name: string;
  category_color: string;
  month: string;
  budget_cents: number;
  actual_cents: number;
  remaining_cents: number;
  percent_used: number;
  /**
   * Signed delta of last month's (budget − actual) for the same category:
   * positive = saved (under-spent), negative = over-spent. `null` when no
   * budget existed for the previous month. Surfaced as a "saved last
   * month" badge — informational only, never folded into current totals.
   */
  previous_month_diff_cents: number | null;
}

export interface BudgetCopyResult {
  from_month: string;
  to_month: string;
  copied: number;
  skipped_existing: number;
}

export interface BudgetHistoryMonth {
  month: string;
  budget_cents: number;
  actual_cents: number;
  /** spent / budget. `null` when no budget for that month → render neutral cell. */
  ratio: number | null;
}

export interface BudgetHistoryRow {
  category_id: number;
  category_name: string;
  category_color: string;
  parent_id: number | null;
  months: BudgetHistoryMonth[];
  months_with_budget: number;
  months_under_or_at: number;
}

// ---------------------------------------------------------------------------
// Investments
// ---------------------------------------------------------------------------

export interface Security {
  plaid_security_id: string;
  name: string | null;
  ticker_symbol: string | null;
  type: string | null;
  subtype: string | null;
  close_price: string | null;
  close_price_as_of: string | null;
  sector: string | null;
  industry: string | null;
  currency: string;
  updated_at: string;
}

export interface InvestmentHolding {
  id: number;
  account_id: number;
  security_id: string;
  quantity: string;
  institution_price: string | null;
  institution_value_cents: number | null;
  cost_basis_cents: number | null;
  currency: string;
  last_synced_at: string;
  security: Security | null;
}

// ---------------------------------------------------------------------------
// Reports
// ---------------------------------------------------------------------------

export interface CashFlowMonth {
  month: string;
  income_cents: number;
  expenses_cents: number;
  /**
   * Total volume of intra-family transfers in the month (credit card
   * payments, Zelle between spouses, savings sweeps, …). Reported for
   * transparency — never part of `net_cents`.
   */
  internal_transfer_cents: number;
  net_cents: number;
}

export interface CategorySpend {
  category_id: number | null;
  category_name: string;
  amount_cents: number;
  percent: number;
  /** Hex color inherited from the bucket category (parent or self). */
  color?: string | null;
  /** Stable id for the UI, e.g. "p:12" (primary bucket) or "c:45" (child). */
  bucket_key?: string | null;
  /** Parent category id when known; null for top-level rows. */
  parent_category_id?: number | null;
  /** In rollup='primary' mode, number of detailed children aggregated. 0 otherwise. */
  children_count?: number;
}

export interface TagSpend {
  tag_id: number;
  tag_name: string;
  tag_color: string;
  amount_cents: number;
}

export interface MerchantSpend {
  /** Display name — already the alias when one is set (server-side COALESCE). */
  merchant_name: string;
  /** True when the row's display name is a user-chosen alias, not the raw Plaid label. */
  is_aliased?: boolean;
  logo_url: string | null;
  amount_cents: number;
  transaction_count: number;
}

// ---------------------------------------------------------------------------
// Merchant aliases (display rename for Plaid-detected merchants)
// ---------------------------------------------------------------------------

export interface MerchantAlias {
  /** Family-global key used both here and by merchant_category_rules. */
  merchant_key: string;
  /** Human-readable rendering of merchant_key, e.g. "Nyflower". */
  display_label: string;
  /** Chosen rename (e.g. "Rent"). */
  display_name: string;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface NetWorthSnapshot {
  snapshot_date: string;
  liquid_cents: number;
  investment_cents: number;
  debt_cents: number;
  net_worth_cents: number;
}

/**
 * Per-account row in the redesigned Net Worth tab. ``role`` collapses
 * the internal ``type`` enum into the two visual buckets the breakdown
 * cards split on. ``balance_cents`` is always the magnitude (sign is
 * implied by ``role``), so summing one bucket gives that bucket's total.
 */
export interface NetWorthAccountRow {
  id: number;
  name: string;
  /** Plaid's longer descriptive name (sometimes more meaningful than ``name``). */
  official_name: string | null;
  /** Last 4 digits of the account number. */
  mask: string | null;
  type: string;
  subtype: string | null;
  role: "asset" | "debt";
  balance_cents: number;
  owner_username: string | null;
  institution_name: string | null;
  institution_logo: string | null;
  institution_color: string | null;
  is_cash_wallet: boolean;
}

export interface NetWorthSummary {
  liquid_cents: number;
  investment_cents: number;
  debt_cents: number;
  net_worth_cents: number;
  /** Net change vs the closest snapshot ~30 days ago (±15d tolerance). */
  mom_delta_cents: number | null;
  /** Net change vs the closest snapshot ~180 days ago (±45d tolerance). */
  six_month_delta_cents: number | null;
  /** ISO snapshot date used for ``mom_delta_cents``. */
  mom_compared_to: string | null;
  /** ISO snapshot date used for ``six_month_delta_cents``. */
  six_month_compared_to: string | null;
  accounts: NetWorthAccountRow[];
  /**
   * Months until projected debt payoff at the current 6-mo (or MoM)
   * trajectory. Null when there's no debt, no upward trajectory, or no
   * comparable snapshot to read a slope from.
   */
  debt_payoff_months: number | null;
}

export interface ForecastEntry {
  date: string;
  description: string;
  merchant_name: string | null;
  amount_cents: number;
  frequency: string | null;
  stream_id: number;
}

export interface IncomeSource {
  category_id: number | null;
  category_name: string;
  color: string | null;
  amount_cents: number;
  transaction_count: number;
}

export interface IncomeByUser {
  /** null when the owning account has no linked user (rare). */
  user_id: number | null;
  username: string;
  amount_cents: number;
  sources: IncomeSource[];
}

export interface IncomeBreakdown {
  month: string;
  total_cents: number;
  users: IncomeByUser[];
}

// ---------------------------------------------------------------------------
// Expenses (mirror of Income breakdown — GET /api/reports/expenses)
// ---------------------------------------------------------------------------

/** Per-category expense slice for one user within a month. */
export interface ExpenseSource {
  category_id: number | null;
  category_name: string;
  color: string | null;
  /**
   * Net expense in cents. Positive = net spending. A negative value is a
   * legitimate outcome when refunds for a category exceeded the period's
   * spending (e.g. a return processed after the original purchase) — the
   * UI should surface it as a credit against that category.
   */
  amount_cents: number;
  transaction_count: number;
}

export interface ExpenseByUser {
  /** null when the owning account has no linked user (rare). */
  user_id: number | null;
  username: string;
  amount_cents: number;
  sources: ExpenseSource[];
}

export interface ExpenseBreakdown {
  month: string;
  total_cents: number;
  users: ExpenseByUser[];
}

// ---------------------------------------------------------------------------
// Diagnostics (owner-only — GET /api/reports/diagnostics)
// ---------------------------------------------------------------------------

/** Per-class counts of transactions in the month (sanity check). */
export interface DiagnosticsClassCounts {
  income: number;
  expense: number;
  internal_transfer: number;
  uncategorized: number;
  total: number;
}

/** A single suspicious row flagged by the classifier diagnostics.
 *
 * The shape mirrors the permissive Pydantic model on the backend: not every
 * field is populated for every section (e.g. ``recent_expense_date`` only
 * shows on possible-refund rows). FE renders only the fields it knows about
 * for each section. */
export interface DiagnosticsRow {
  id: number;
  date: string | null;
  amount_cents: number;
  merchant_name: string | null;
  name: string | null;
  pfc_primary: string | null;
  pfc_detailed: string | null;
  category_name: string | null;
  account_type: string | null;
  transaction_class: TransactionClass | null;
  merchant_entity_id: string | null;
  /** ISO date of the most recent expense from the same merchant within the
   *  60-day refund-detection window. Only set for possible-refund rows. */
  recent_expense_date: string | null;
}

export interface Diagnostics {
  month: string;
  counts: DiagnosticsClassCounts;
  /** Income-flagged category paired with a positive amount (sign mismatch). */
  suspicious_income_category_with_positive_amount: DiagnosticsRow[];
  /** `TRANSFER_IN` / `TRANSFER_OUT` / `LOAN_PAYMENTS` without pair match
   *  and without a name hit. */
  transfer_pfc_not_classified_as_internal: DiagnosticsRow[];
  /** Uncategorized rows whose magnitude is large enough to warrant review. */
  large_uncategorized: DiagnosticsRow[];
  /** Rule-5.5 income rows whose merchant matches a recent expense from the
   *  same merchant_entity_id — likely refunds the classifier mis-tagged
   *  as income. */
  possible_refunds_misclassified_as_income: DiagnosticsRow[];
}

export interface FinancialHealthScore {
  score: number;
  label: string;
  color: string;
  debt_to_income: number | null;
  credit_utilization: number | null;
  savings_rate: number | null;
  emergency_fund_months: number | null;
  has_overdue: boolean;
  advice: string;
}

// ---------------------------------------------------------------------------
// Plaid
// ---------------------------------------------------------------------------

export interface PlaidItem {
  item_id: string;
  institution_name: string | null;
  institution_logo?: string | null;
  institution_color?: string | null;
  user_id?: number | null;
  cursor: string | null;
  last_synced_at: string | null;
  connected_at?: string | null;
  item_login_required?: boolean;
  sync_updates_pending?: boolean;
  created_at?: string;
  updated_at?: string;
}

export interface PlaidSyncResult {
  item_id: string;
  transactions_added: number;
  balances_updated: number;
  status: string;
  error_msg: string | null;
}

export interface PlaidSyncLogEntry {
  id: number;
  item_id: string;
  synced_at: string;
  transactions_added: number;
  balances_updated: number;
  status: string;
  error_msg: string | null;
}

// ---------------------------------------------------------------------------
// App settings — autosync schedule
// ---------------------------------------------------------------------------

export interface WebhookReconcileResult {
  updated: number;
  failed: number;
  total: number;
  errors: string[];
}

/**
 * Autosync cadence. Anchor days are fixed by the backend so the UI never has
 * to pick a day-of-week or day-of-month:
 *   - `off`          — scheduled sync disabled (manual still works)
 *   - `daily`        — every day at the configured UTC hour/minute
 *   - `weekly`       — every Sunday
 *   - `semimonthly`  — 1st and 15th of each month
 *   - `monthly`      — 1st of each month
 */
export type AutosyncFrequency = "off" | "daily" | "weekly" | "semimonthly" | "monthly";

export const AUTOSYNC_FREQUENCIES: AutosyncFrequency[] = [
  "off",
  "daily",
  "weekly",
  "semimonthly",
  "monthly",
];

export interface AutosyncConfig {
  frequency: AutosyncFrequency;
  hour_utc: number;
  minute_utc: number;
  webhooks_enabled: boolean;
  /** When true, the daily prune deletes bot_activity_log rows older than 7 days. */
  bot_activity_auto_prune_enabled: boolean;
  /** When true, the daily prune deletes audit_log rows older than 7 days. */
  audit_log_auto_prune_enabled: boolean;
  updated_at: string | null;
  updated_by_username: string | null;
  next_run_at: string | null;
  /** False when PLAID_WEBHOOK_URL is not set on the backend — webhooks cannot be enabled. */
  webhook_url_configured: boolean;
  /** Populated only on PATCH responses that actually flipped webhooks_enabled. */
  webhook_reconcile: WebhookReconcileResult | null;
}

export interface AutosyncConfigUpdate {
  frequency?: AutosyncFrequency;
  hour_utc?: number;
  minute_utc?: number;
  webhooks_enabled?: boolean;
  bot_activity_auto_prune_enabled?: boolean;
  audit_log_auto_prune_enabled?: boolean;
}

// ---------------------------------------------------------------------------
// Audit log
// ---------------------------------------------------------------------------

export type AuditSource = "manual" | "scheduler" | "webhook" | "system";

export interface AuditEntry {
  id: number;
  created_at: string;
  actor_user_id: number | null;
  actor_username: string | null;
  event_type: string;
  source: AuditSource;
  target_kind: string | null;
  target_id: string | null;
  metadata: Record<string, unknown>;
  request_ip: string | null;
}

export interface AuditListResponse {
  entries: AuditEntry[];
  next_before_id: number | null;
}

// ---------------------------------------------------------------------------
// Piggy Banks (savings goals)
// ---------------------------------------------------------------------------

export interface PiggyBank {
  id: number;
  name: string;
  target_amount_cents: number;
  current_amount_cents: number;
  color: string;
  icon: string | null;
  description: string | null;
  deadline: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface PiggyBankCreate {
  name: string;
  target_amount_cents: number;
  current_amount_cents?: number;
  color?: string;
  icon?: string | null;
  description?: string | null;
  deadline?: string | null;
  is_active?: boolean;
}

export interface PiggyBankUpdate {
  name?: string;
  target_amount_cents?: number;
  current_amount_cents?: number;
  color?: string;
  icon?: string | null;
  description?: string | null;
  deadline?: string | null;
  is_active?: boolean;
}
