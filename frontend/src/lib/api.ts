import {
  Expense,
  ExpenseCreate,
  ExpenseUpdate,
  ExpenseResponse,
  Limit,
  LimitCreate,
  ReportResponse,
  SyncStatus,
  HealthResponse,
  Loan,
  LoanCreate,
  LoanUpdate,
  CreditCard,
  CreditCardCreate,
  CreditCardUpdate,
  Payment,
  PaymentCreate,
  Income,
  IncomeCreate,
  IncomeUpdate,
  RecurringExpense,
  RecurringExpenseCreate,
  RecurringExpenseUpdate,
  PiggyBank,
  PiggyBankCreate,
  PiggyBankUpdate,
  FinanceSummary,
  Account,
  InterestSummary,
  AccountAnalytics,
  PaymentAnalytics,
  PlaidItem,
  PlaidSyncResult,
  PlaidSyncLogEntry,
  PlaidCategoryMapEntry,
} from '@/types/api';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || '';

class ApiError extends Error {
  public detail?: string;
  constructor(public status: number, message: string, detail?: string) {
    super(message);
    this.name = 'ApiError';
    this.detail = detail || message;
  }
}

async function apiRequest<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const url = `${API_BASE_URL}${endpoint}`;

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string> || {}),
  };

  try {
    const response = await fetch(url, {
      method: options.method || 'GET',
      headers,
      credentials: 'include', // Include cookies for cross-origin requests
      mode: 'cors', // Explicitly set CORS mode for Safari compatibility
      ...options,
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ detail: 'Unknown error' }));
      const errorMessage = errorData.detail || errorData.message || 'Unknown error';
      throw new ApiError(response.status, errorMessage, errorData.detail);
    }

    return response.json();
  } catch (error) {
    // Handle network errors or fetch failures
    if (error instanceof ApiError) {
      throw error; // Re-throw API errors as-is
    }
    
    // Network error or fetch failed
    const networkError = error instanceof Error ? error.message : 'Network error';
    
    // Safari-specific error handling
    if (error instanceof TypeError && networkError.includes('Failed to fetch')) {
      const isSafari = typeof navigator !== 'undefined' && 
        /^((?!chrome|android).)*safari/i.test(navigator.userAgent);
      
      if (isSafari) {
        console.error('Safari network error:', { url, error: networkError, apiBaseUrl: API_BASE_URL });
        throw new ApiError(
          0, 
          `Safari network error. Please check: 1) CORS settings, 2) SSL certificate, 3) Try disabling "Prevent cross-site tracking" in Safari settings. API URL: ${API_BASE_URL || 'NOT SET'}`
        );
      }
    }
    
    console.error('API request failed:', { url, error: networkError, apiBaseUrl: API_BASE_URL });
    throw new ApiError(0, `Failed to fetch: ${networkError}. API URL: ${API_BASE_URL || 'NOT SET'}`);
  }
}

// Health check
export const healthApi = {
  check: (): Promise<HealthResponse> =>
    apiRequest('/healthz'),
};

// Expenses API
export const expensesApi = {
  getAll: (month?: string, query?: string, source?: string): Promise<Expense[]> => {
    if (!month) return apiRequest('/expenses');
    const params = new URLSearchParams({ month });
    if (query) params.set('query', query);
    if (source) params.set('source', source);
    return apiRequest(`/expenses?${params.toString()}`);
  },

  create: (expense: ExpenseCreate): Promise<ExpenseResponse> =>
    apiRequest('/expenses', {
      method: 'POST',
      body: JSON.stringify(expense),
    }),

  update: (id: number, expense: ExpenseUpdate): Promise<ExpenseResponse> =>
    apiRequest(`/expenses/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(expense),
    }),

  delete: (id: number): Promise<void> =>
    apiRequest(`/expenses/${id}`, {
      method: 'DELETE',
    }),
};

// Limits API
export const limitsApi = {
  getAll: (): Promise<Limit[]> =>
    apiRequest('/limits'),

  create: (limit: LimitCreate): Promise<Limit> =>
    apiRequest('/limits', {
      method: 'POST',
      body: JSON.stringify(limit),
    }),

  update: (category: string, limit: { default_limit: number } | { category: string }): Promise<Limit> =>
    apiRequest(`/limits/${encodeURIComponent(category)}`, {
      method: 'PATCH',
      body: JSON.stringify(limit),
    }),

  delete: (category: string): Promise<void> =>
    apiRequest(`/limits/${encodeURIComponent(category)}`, {
      method: 'DELETE',
    }),
};

// Reports API
export const reportsApi = {
  getReport: (month?: string, compare?: string): Promise<ReportResponse> =>
    apiRequest(`/report${month ? `?month=${month}${compare ? `&compare=${compare}` : ''}` : ''}`),
};

// Sync API
export const syncApi = {
  getStatus: (): Promise<SyncStatus> =>
    apiRequest('/sync/status'),

  pull: (): Promise<{ message: string; sha?: string }> =>
    apiRequest('/sync/pull', { method: 'POST' }),

  push: (): Promise<{ message: string; sha?: string }> =>
    apiRequest('/sync/push', { method: 'POST' }),
};

// Categories API
export const categoriesApi = {
  delete: (name: string): Promise<{ message: string }> =>
    apiRequest(`/categories/${name}`, { method: 'DELETE' }),
};

// Finance API
export const financeApi = {
  // Summary
  getSummary: (month?: string): Promise<FinanceSummary> =>
    apiRequest(`/api/finances/summary${month ? `?month=${month}` : ''}`),

  // Loans
  getLoans: (isActive?: boolean): Promise<Loan[]> =>
    apiRequest(`/api/finances/loans${isActive !== undefined ? `?is_active=${isActive}` : ''}`),

  createLoan: (loan: LoanCreate): Promise<Loan> =>
    apiRequest('/api/finances/loans', {
      method: 'POST',
      body: JSON.stringify(loan),
    }),

  updateLoan: (id: number, loan: LoanUpdate): Promise<Loan> =>
    apiRequest(`/api/finances/loans/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(loan),
    }),

  deleteLoan: (id: number): Promise<void> =>
    apiRequest(`/api/finances/loans/${id}`, { method: 'DELETE' }),

  // Credit Cards
  getCards: (isActive?: boolean): Promise<CreditCard[]> =>
    apiRequest(`/api/finances/cards${isActive !== undefined ? `?is_active=${isActive}` : ''}`),

  createCard: (card: CreditCardCreate): Promise<CreditCard> =>
    apiRequest('/api/finances/cards', {
      method: 'POST',
      body: JSON.stringify(card),
    }),

  updateCard: (id: number, card: CreditCardUpdate): Promise<CreditCard> =>
    apiRequest(`/api/finances/cards/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(card),
    }),

  deleteCard: (id: number): Promise<void> =>
    apiRequest(`/api/finances/cards/${id}`, { method: 'DELETE' }),

  // Payments
  getPayments: (accountType?: 'loan' | 'card', accountId?: number): Promise<Payment[]> => {
    const params = new URLSearchParams();
    if (accountType) params.append('account_type', accountType);
    if (accountId) params.append('account_id', accountId.toString());
    return apiRequest(`/api/finances/payments${params.toString() ? `?${params.toString()}` : ''}`);
  },

  createPayment: (payment: PaymentCreate): Promise<Payment> =>
    apiRequest('/api/finances/payments', {
      method: 'POST',
      body: JSON.stringify(payment),
    }),

  // Income
  getIncome: (month?: string, person?: 'Denis' | 'Taya'): Promise<Income[]> => {
    const params = new URLSearchParams();
    if (month) params.append('month', month);
    if (person) params.append('person', person);
    return apiRequest(`/api/finances/income${params.toString() ? `?${params.toString()}` : ''}`);
  },

  createIncome: (income: IncomeCreate): Promise<Income> =>
    apiRequest('/api/finances/income', {
      method: 'POST',
      body: JSON.stringify(income),
    }),

  updateIncome: (id: number, income: IncomeUpdate): Promise<Income> =>
    apiRequest(`/api/finances/income/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(income),
    }),

  deleteIncome: (id: number): Promise<void> =>
    apiRequest(`/api/finances/income/${id}`, { method: 'DELETE' }),

  // Recurring Expenses
  getRecurringExpenses: (activeOnly?: boolean): Promise<RecurringExpense[]> =>
    apiRequest(`/api/finances/recurring-expenses${activeOnly !== undefined ? `?active_only=${activeOnly}` : ''}`),

  createRecurringExpense: (expense: RecurringExpenseCreate): Promise<RecurringExpense> =>
    apiRequest('/api/finances/recurring-expenses', {
      method: 'POST',
      body: JSON.stringify(expense),
    }),

  updateRecurringExpense: (id: number, expense: RecurringExpenseUpdate): Promise<RecurringExpense> =>
    apiRequest(`/api/finances/recurring-expenses/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(expense),
    }),

  deleteRecurringExpense: (id: number): Promise<void> =>
    apiRequest(`/api/finances/recurring-expenses/${id}`, { method: 'DELETE' }),

  // Piggy Banks
  getPiggyBanks: (activeOnly?: boolean): Promise<PiggyBank[]> =>
    apiRequest(`/api/finances/piggy-banks${activeOnly !== undefined ? `?active_only=${activeOnly}` : ''}`),

  createPiggyBank: (piggy: PiggyBankCreate): Promise<PiggyBank> =>
    apiRequest('/api/finances/piggy-banks', {
      method: 'POST',
      body: JSON.stringify(piggy),
    }),

  updatePiggyBank: (id: number, piggy: PiggyBankUpdate): Promise<PiggyBank> =>
    apiRequest(`/api/finances/piggy-banks/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(piggy),
    }),

  deletePiggyBank: (id: number): Promise<void> =>
    apiRequest(`/api/finances/piggy-banks/${id}`, { method: 'DELETE' }),

  addToPiggyBank: (id: number, amountCents: number): Promise<PiggyBank> =>
    apiRequest(`/api/finances/piggy-banks/${id}/add-amount?amount_cents=${amountCents}`, {
      method: 'POST',
    }),

  // Accounts
  getAccounts: (): Promise<{ loans: Account[]; cards: Account[] }> =>
    apiRequest('/api/finances/accounts'),

  // Analytics
  getInterestSummary: (month?: string): Promise<InterestSummary> =>
    apiRequest(`/api/finances/analytics/interest-summary${month ? `?month=${month}` : ''}`),

  getAccountAnalytics: (type: 'loan' | 'card', id: number): Promise<AccountAnalytics> =>
    apiRequest(`/api/finances/analytics/account/${type}/${id}`),

  getPaymentAnalytics: (id: number): Promise<PaymentAnalytics> =>
    apiRequest(`/api/finances/analytics/payment/${id}`),
};

// Plaid API
export const plaidApi = {
  getLinkToken: (): Promise<{ link_token: string; expiration: string }> =>
    apiRequest('/api/plaid/link-token', { method: 'POST' }),

  exchangeToken: (publicToken: string, institutionName?: string): Promise<PlaidItem> =>
    apiRequest('/api/plaid/exchange-token', {
      method: 'POST',
      body: JSON.stringify({ public_token: publicToken, institution_name: institutionName }),
    }),

  getItems: (): Promise<PlaidItem[]> =>
    apiRequest('/api/plaid/items'),

  deleteItem: (itemId: string): Promise<{ message: string }> =>
    apiRequest(`/api/plaid/items/${itemId}`, { method: 'DELETE' }),

  syncNow: (): Promise<PlaidSyncResult[]> =>
    apiRequest('/api/plaid/sync', { method: 'POST' }),

  getSyncLog: (): Promise<PlaidSyncLogEntry[]> =>
    apiRequest('/api/plaid/sync/log'),

  getCategoryMap: (): Promise<PlaidCategoryMapEntry[]> =>
    apiRequest('/api/plaid/category-map'),

  updateCategoryMap: (mappings: PlaidCategoryMapEntry[]): Promise<{ message: string }> =>
    apiRequest('/api/plaid/category-map', {
      method: 'PATCH',
      body: JSON.stringify({ mappings }),
    }),
};

export interface UserPublic {
  id: number;
  username: string;
  is_owner: boolean;
  created_at: string;
}

export const usersApi = {
  list: (): Promise<UserPublic[]> =>
    apiRequest('/api/auth/users'),

  create: (data: { username: string; password: string }): Promise<UserPublic> =>
    apiRequest('/api/auth/users', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  delete: (id: number): Promise<void> =>
    apiRequest(`/api/auth/users/${id}`, { method: 'DELETE' }),
};
