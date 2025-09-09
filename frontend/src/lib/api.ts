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
  FinanceSummary,
  Account,
  InterestSummary,
  AccountAnalytics,
  PaymentAnalytics
} from '@/types/api';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || '';

class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = 'ApiError';
  }
}

async function apiRequest<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const url = `${API_BASE_URL}${endpoint}`;

  const response = await fetch(url, {
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
    ...options,
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({ detail: 'Unknown error' }));
    throw new ApiError(response.status, errorData.detail || 'Unknown error');
  }

  return response.json();
}

// Health check
export const healthApi = {
  check: (): Promise<HealthResponse> =>
    apiRequest('/healthz'),
};

// Expenses API
export const expensesApi = {
  getAll: (month?: string, query?: string): Promise<Expense[]> =>
    apiRequest(`/expenses${month ? `?month=${month}${query ? `&query=${query}` : ''}` : ''}`),

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
