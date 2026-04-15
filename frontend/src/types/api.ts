export interface Expense {
  id: number;
  category: string;
  amount: number;
  date: string;
}

export interface ExpenseCreate {
  category: string;
  amount: number;
  date?: string;
}

export interface ExpenseUpdate {
  category?: string;
  amount?: number;
  date?: string;
}

export interface ExpenseResponse {
  exceeded: boolean;
  remaining: number;
}

export interface Limit {
  category: string;
  default_limit: number;
}

export interface LimitCreate {
  category: string;
  default_limit: number;
}

export interface ReportItem {
  budget: number;
  spent: number;
  remaining: number;
  rolled_over: number;
}

export interface ReportResponse {
  report: Record<string, ReportItem>;
  comparison?: Record<string, number>;
}

export interface SyncStatus {
  sha?: string;
  last_sync?: string;
}

export interface HealthResponse {
  ok: boolean;
}

export interface ApiError {
  detail: string;
}

// Finance API Types
export interface Loan {
  id: number;
  name: string;
  category_name: string;
  apr_percent: number;
  current_balance_cents: number;
  due_day?: number;
  min_payment_cents: number;
  remaining_months?: number;
  close_date?: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface LoanCreate {
  name: string;
  category_name: string;
  apr_percent: number;
  current_balance_cents: number;
  due_day?: number;
  min_payment_cents: number;
  remaining_months?: number;
  close_date?: string;
}

export interface LoanUpdate {
  name?: string;
  category_name?: string;
  apr_percent?: number;
  current_balance_cents?: number;
  due_day?: number;
  min_payment_cents?: number;
  remaining_months?: number;
  close_date?: string;
  is_active?: boolean;
}

export interface CreditCard {
  id: number;
  name: string;
  category_name: string;
  apr_percent: number;
  current_balance_cents: number;
  credit_limit_cents?: number;
  due_day?: number;
  min_payment_cents: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface CreditCardCreate {
  name: string;
  category_name: string;
  apr_percent: number;
  current_balance_cents: number;
  credit_limit_cents?: number;
  due_day?: number;
  min_payment_cents: number;
}

export interface CreditCardUpdate {
  name?: string;
  category_name?: string;
  apr_percent?: number;
  current_balance_cents?: number;
  credit_limit_cents?: number;
  due_day?: number;
  min_payment_cents?: number;
  is_active?: boolean;
}

export interface Payment {
  id: number;
  account_type: 'loan' | 'card';
  account_id: number;
  amount_cents: number;
  occurred_at: string;
  person?: 'Denis' | 'Taya';
  note?: string;
  created_at: string;
}

export interface PaymentCreate {
  account_type: 'loan' | 'card';
  account_id: number;
  amount_cents: number;
  occurred_at?: string;
  person?: 'Denis' | 'Taya';
  note?: string;
}

export interface Income {
  id: number;
  person: 'Denis' | 'Taya';
  amount_cents: number;
  occurred_at: string;
  note?: string;
  created_at: string;
}

export interface IncomeCreate {
  person: 'Denis' | 'Taya';
  amount_cents: number;
  occurred_at?: string;
  note?: string;
}

export interface IncomeUpdate {
  person?: 'Denis' | 'Taya';
  amount_cents?: number;
  occurred_at?: string;
  note?: string;
}

// Recurring Expenses Types
export interface RecurringExpense {
  id: number;
  name: string;
  category_name: string;
  monthly_amount_cents: number;
  due_day?: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface RecurringExpenseCreate {
  name: string;
  category_name: string;
  monthly_amount_cents: number;
  due_day?: number;
  is_active?: boolean;
}

export interface RecurringExpenseUpdate {
  name?: string;
  category_name?: string;
  monthly_amount_cents?: number;
  due_day?: number;
  is_active?: boolean;
}

export interface DebtTotals {
  loans_balance_cents: number;
  cards_balance_cents: number;
  combined_balance_cents: number;
  loans_min_payment_cents: number;
  cards_min_payment_cents: number;
  min_payments_cents: number;
  recurring_expenses_total_cents: number;
}

export interface LoanEstimatedClose {
  name: string;
  remaining_months: number;
  estimated_close_date: string;
}

export interface FinanceSummary {
  income_total_cents: number;
  income_by_person: {
    Denis: number;
    Taya: number;
  };
  debt_totals: DebtTotals;
  loans_estimated_close: LoanEstimatedClose[];
}

export interface Account {
  id: number;
  name: string;
  category_name: string;
  account_type: 'loan' | 'card';
}

// Interest and analytics types
export interface MonthlyInterest {
  account_id: number;
  account_type: 'loan' | 'card';
  month: string;
  interest_accrued_cents: number;
  balance_start_cents: number;
  balance_end_cents: number;
  apr_percent: number;
  days_in_month: number;
}

export interface PaymentAnalytics {
  payment_id: number;
  amount_cents: number;
  interest_portion_cents: number;
  principal_portion_cents: number;
  remaining_balance_cents: number;
  months_saved?: number;
}

export interface AccountAnalytics {
  account_id: number;
  account_type: 'loan' | 'card';
  name: string;
  current_balance_cents: number;
  apr_percent: number;
  
  // Interest calculations
  monthly_interest_rate: number;
  monthly_interest_cents: number;
  
  // Payoff projections (minimum payments)
  min_payment_months?: number;
  min_payment_total_interest_cents: number;
  min_payment_total_cost_cents: number;
  
  // Current payment projections
  current_payoff_months?: number;
  current_total_interest_cents: number;
  current_total_cost_cents: number;
  
  // Savings from current payment strategy
  interest_savings_cents: number;
  months_saved: number;
}

export interface InterestSummary {
  month: string;
  
  // Total interest accrued this month
  total_interest_accrued_cents: number;
  loans_interest_cents: number;
  cards_interest_cents: number;
  
  // Projected totals (minimum payments)
  total_projected_interest_cents: number;
  total_projected_cost_cents: number;
  projected_payoff_months: number;
  
  // Current strategy totals
  current_projected_interest_cents: number;
  current_projected_cost_cents: number;
  current_payoff_months: number;
  
  // Savings from current strategy vs minimum
  total_interest_savings_cents: number;
  total_months_saved: number;
  
  // Account analytics
  account_analytics: AccountAnalytics[];
}

// Piggy Banks Types
export interface PiggyBank {
  id: number;
  name: string;
  target_amount_cents: number;
  current_amount_cents: number;
  color: string; // hex color
  icon: string | null;
  description: string | null;
  deadline: string | null; // ISO date
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
  deadline?: string | null; // ISO date
  is_active?: boolean;
}

export interface PiggyBankUpdate {
  name?: string;
  target_amount_cents?: number;
  current_amount_cents?: number;
  color?: string;
  icon?: string | null;
  description?: string | null;
  deadline?: string | null; // ISO date
  is_active?: boolean;
}

// Plaid types
export interface PlaidItem {
  id: number;
  item_id: string;
  institution_name: string | null;
  connected_at: string;
  last_synced_at: string | null;
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

export interface PlaidCategoryMapEntry {
  plaid_category: string;
  budget_category: string;
}
