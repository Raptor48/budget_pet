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
  category_id: number;
  category_name: string;
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
  limit?: number;
  offset?: number;
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
  price_change_pct: string | null;
  last_synced_at: string | null;
  /** plaid | manual — manual streams are not overwritten by Plaid sync */
  stream_source?: string;
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
  net_cents: number;
}

export interface CategorySpend {
  category_id: number | null;
  category_name: string;
  amount_cents: number;
  percent: number;
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
