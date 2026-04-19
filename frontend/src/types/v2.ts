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
  merchant_key?: string | null;
  display_label?: string | null;
}

export interface MerchantRuleApplyResult extends MerchantRulePreviewResult {
  updated_count: number;
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
  splits: TransactionSplit[];
  /** Joined from accounts table */
  account_name: string | null;
  /** Last 4 digits of the card, e.g. "4242" */
  account_mask: string | null;
  /** Username of the account owner (joined via accounts.user_id → users) */
  owner_username: string | null;
  /** Derived display title — short, human-friendly. Server-computed via web/transactions/display.py. */
  display_title?: string | null;
}

export interface TransactionFilters {
  month?: string;
  account_id?: number;
  category_id?: number;
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
  /** Short, human-friendly label for the stream (normalized from description). */
  display_title?: string | null;
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
  merchant_name: string;
  logo_url: string | null;
  amount_cents: number;
  transaction_count: number;
}

export interface NetWorthSnapshot {
  snapshot_date: string;
  liquid_cents: number;
  investment_cents: number;
  debt_cents: number;
  net_worth_cents: number;
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
}

/** A single suspicious row flagged by the classifier diagnostics. */
export interface DiagnosticsRow {
  transaction_id: number;
  account_id: number;
  account_name: string | null;
  date: string;
  name: string;
  amount_cents: number;
  transaction_class: TransactionClass;
  category_id: number | null;
  category_name: string | null;
  /** Why the classifier flagged the row (free-form, human-readable). */
  reason: string;
}

export interface Diagnostics {
  month: string;
  class_counts: DiagnosticsClassCounts;
  /** Income-flagged category paired with a positive amount (sign mismatch). */
  positive_income_rows: DiagnosticsRow[];
  /** `TRANSFER_IN` / `TRANSFER_OUT` without pair match and without a name hit. */
  unmatched_transfers: DiagnosticsRow[];
  /** Uncategorized rows whose magnitude is large enough to warrant review. */
  large_uncategorized: DiagnosticsRow[];
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
