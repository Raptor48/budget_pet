/**
 * V2 API client — all calls go to the V2 backend via /api/*.
 * Uses cookie auth with Authorization: Bearer fallback from sessionStorage.
 */
import { getAuthHeaders } from '@/lib/auth';
import type {
  Account,
  Budget,
  BudgetProgress,
  CashFlowMonth,
  Category,
  CategorySpend,
  FinancialHealthScore,
  ForecastEntry,
  InvestmentHolding,
  Member,
  MerchantSpend,
  NetWorthSnapshot,
  PlaidItem,
  PlaidSyncLogEntry,
  PlaidSyncResult,
  RecurringStream,
  Tag,
  TagSpend,
  Transaction,
  TransactionFilters,
  TransactionSplit,
  ManualCashTransactionCreate,
  MerchantRule,
} from '@/types/v2';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || '';

// ---------------------------------------------------------------------------
// Base request helper
// ---------------------------------------------------------------------------

export class ApiError extends Error {
  public detail?: string;
  constructor(
    public status: number,
    message: string,
    detail?: string,
  ) {
    super(message);
    this.name = 'ApiError';
    this.detail = detail || message;
  }
}

async function apiRequest<T>(
  endpoint: string,
  options: RequestInit = {},
): Promise<T> {
  const url = `${API_BASE}${endpoint}`;
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(getAuthHeaders() as Record<string, string>),
    ...(options.headers as Record<string, string> || {}),
  };

  const response = await fetch(url, {
    ...options,
    headers,
    credentials: 'include',
  });

  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const body = await response.json();
      detail = body.detail || body.message || detail;
    } catch {
      // ignore parse errors
    }
    throw new ApiError(response.status, detail, detail);
  }

  if (response.status === 204) {
    return undefined as unknown as T;
  }
  return response.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// Accounts
// ---------------------------------------------------------------------------

export const accountsApi = {
  list: (activeOnly = true): Promise<Account[]> =>
    apiRequest(`/api/accounts?active_only=${activeOnly}`),

  get: (id: number): Promise<Account> =>
    apiRequest(`/api/accounts/${id}`),

  cashWallet: (): Promise<Account> => apiRequest("/api/accounts/cash-wallet"),

  create: (data: Partial<Account>): Promise<Account> =>
    apiRequest('/api/accounts', { method: 'POST', body: JSON.stringify(data) }),

  update: (id: number, data: Partial<Account>): Promise<Account> =>
    apiRequest(`/api/accounts/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),

  assignOwner: (accountId: number, userId: number | null): Promise<Account> =>
    apiRequest(`/api/accounts/${accountId}`, {
      method: 'PATCH',
      body: JSON.stringify({ user_id: userId }),
    }),

  delete: (id: number): Promise<void> =>
    apiRequest(`/api/accounts/${id}`, { method: 'DELETE' }),
};

// ---------------------------------------------------------------------------
// Members (all authenticated users — for person filter)
// ---------------------------------------------------------------------------

export const membersApi = {
  list: (): Promise<Member[]> => apiRequest('/api/auth/members'),
};

// ---------------------------------------------------------------------------
// Categories
// ---------------------------------------------------------------------------

export const categoriesApi = {
  list: (): Promise<Category[]> => apiRequest('/api/categories'),

  get: (id: number): Promise<Category> => apiRequest(`/api/categories/${id}`),

  create: (data: Pick<Category, 'name' | 'color'> & { icon?: string | null }): Promise<Category> =>
    apiRequest('/api/categories', { method: 'POST', body: JSON.stringify(data) }),

  update: (id: number, data: Partial<Category>): Promise<Category> =>
    apiRequest(`/api/categories/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),

  delete: (id: number): Promise<void> =>
    apiRequest(`/api/categories/${id}`, { method: 'DELETE' }),
};

// ---------------------------------------------------------------------------
// Tags
// ---------------------------------------------------------------------------

export const tagsApi = {
  list: (): Promise<Tag[]> => apiRequest('/api/tags'),

  create: (data: { name: string; color?: string }): Promise<Tag> =>
    apiRequest('/api/tags', { method: 'POST', body: JSON.stringify(data) }),

  update: (id: number, data: Partial<Tag>): Promise<Tag> =>
    apiRequest(`/api/tags/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),

  delete: (id: number): Promise<void> =>
    apiRequest(`/api/tags/${id}`, { method: 'DELETE' }),
};

// ---------------------------------------------------------------------------
// Merchant → category rules
// ---------------------------------------------------------------------------

export const merchantRulesApi = {
  list: (): Promise<MerchantRule[]> => apiRequest('/api/merchant-rules'),

  create: (data: {
    category_id: number;
    merchant_entity_id?: string | null;
    merchant_name?: string | null;
  }): Promise<MerchantRule> =>
    apiRequest('/api/merchant-rules', { method: 'POST', body: JSON.stringify(data) }),

  delete: (id: number): Promise<{ ok: boolean }> =>
    apiRequest(`/api/merchant-rules/${id}`, { method: 'DELETE' }),
};

// ---------------------------------------------------------------------------
// Transactions
// ---------------------------------------------------------------------------

function buildTransactionQuery(filters: TransactionFilters): string {
  const params = new URLSearchParams();
  if (filters.month) params.set('month', filters.month);
  if (filters.account_id != null) params.set('account_id', String(filters.account_id));
  if (filters.category_id != null) params.set('category_id', String(filters.category_id));
  if (filters.tag_id != null) params.set('tag_id', String(filters.tag_id));
  if (filters.search) params.set('search', filters.search);
  if (filters.channel) params.set('channel', filters.channel);
  if (filters.pending_only != null) params.set('pending_only', String(filters.pending_only));
  if (filters.user_id != null) params.set('user_id', String(filters.user_id));
  if (filters.limit != null) params.set('limit', String(filters.limit));
  if (filters.offset != null) params.set('offset', String(filters.offset));
  const qs = params.toString();
  return qs ? `?${qs}` : '';
}

export const transactionsApi = {
  list: (filters: TransactionFilters = {}): Promise<Transaction[]> =>
    apiRequest(`/api/transactions${buildTransactionQuery(filters)}`),

  get: (id: number): Promise<Transaction> =>
    apiRequest(`/api/transactions/${id}`),

  create: (data: ManualCashTransactionCreate): Promise<Transaction> =>
    apiRequest('/api/transactions', { method: 'POST', body: JSON.stringify(data) }),

  update: (
    id: number,
    data: { category_id?: number | null; user_note?: string; merchant_name?: string; is_private?: boolean },
  ): Promise<Transaction> =>
    apiRequest(`/api/transactions/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),

  delete: (id: number): Promise<void> =>
    apiRequest(`/api/transactions/${id}`, { method: 'DELETE' }),

  addTag: (transactionId: number, tagId: number): Promise<void> =>
    apiRequest(`/api/transactions/${transactionId}/tags/${tagId}`, { method: 'POST' }),

  removeTag: (transactionId: number, tagId: number): Promise<void> =>
    apiRequest(`/api/transactions/${transactionId}/tags/${tagId}`, { method: 'DELETE' }),

  getSplits: (transactionId: number): Promise<TransactionSplit[]> =>
    apiRequest(`/api/transactions/${transactionId}/splits`),

  setSplits: (
    transactionId: number,
    splits: Array<{ category_id?: number | null; tag_id?: number | null; amount_cents: number; note?: string }>,
  ): Promise<TransactionSplit[]> =>
    apiRequest(`/api/transactions/${transactionId}/splits`, {
      method: 'POST',
      body: JSON.stringify({ splits }),
    }),

  deleteSplits: (transactionId: number): Promise<void> =>
    apiRequest(`/api/transactions/${transactionId}/splits`, { method: 'DELETE' }),

  exportUrl: (filters: TransactionFilters = {}): string => {
    const params = new URLSearchParams();
    if (filters.month) params.set('month', filters.month);
    if (filters.account_id != null) params.set('account_id', String(filters.account_id));
    if (filters.category_id != null) params.set('category_id', String(filters.category_id));
    if (filters.tag_id != null) params.set('tag_id', String(filters.tag_id));
    const qs = params.toString();
    return `${API_BASE}/api/transactions/export${qs ? '?' + qs : ''}`;
  },
};

// ---------------------------------------------------------------------------
// Recurring
// ---------------------------------------------------------------------------

export const recurringApi = {
  list: (direction?: 'inflow' | 'outflow', activeOnly = true): Promise<RecurringStream[]> => {
    const params = new URLSearchParams();
    if (direction) params.set('direction', direction);
    params.set('active_only', String(activeOnly));
    return apiRequest(`/api/recurring?${params}`);
  },

  create: (data: {
    account_id: number;
    direction: 'inflow' | 'outflow';
    description: string;
    merchant_name?: string | null;
    frequency?: string | null;
    average_amount_cents: number;
    last_amount_cents?: number | null;
    currency?: string;
    first_date?: string | null;
    last_date?: string | null;
    category_id?: number | null;
  }): Promise<RecurringStream> =>
    apiRequest('/api/recurring', { method: 'POST', body: JSON.stringify(data) }),

  getPriceChanges: (): Promise<RecurringStream[]> =>
    apiRequest('/api/recurring/price-changes'),

  update: (
    id: number,
    data: { user_label?: string | null; category_id?: number | null },
  ): Promise<RecurringStream> =>
    apiRequest(`/api/recurring/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
};

// ---------------------------------------------------------------------------
// Budgets
// ---------------------------------------------------------------------------

export const budgetsApi = {
  list: (month?: string): Promise<Budget[]> => {
    const qs = month ? `?month=${month}` : '';
    return apiRequest(`/api/budgets${qs}`);
  },

  getProgress: (month?: string): Promise<BudgetProgress[]> => {
    const qs = month ? `?month=${month}` : '';
    return apiRequest(`/api/budgets/progress${qs}`);
  },

  create: (data: { category_id: number; month: string; budget_cents: number }): Promise<Budget> =>
    apiRequest('/api/budgets', { method: 'POST', body: JSON.stringify(data) }),

  update: (id: number, data: { budget_cents: number }): Promise<Budget> =>
    apiRequest(`/api/budgets/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),

  delete: (id: number): Promise<void> =>
    apiRequest(`/api/budgets/${id}`, { method: 'DELETE' }),
};

// ---------------------------------------------------------------------------
// Investments
// ---------------------------------------------------------------------------

export const investmentsApi = {
  listHoldings: (accountId?: number): Promise<InvestmentHolding[]> => {
    const qs = accountId != null ? `?account_id=${accountId}` : '';
    return apiRequest(`/api/investments/holdings${qs}`);
  },
};

// ---------------------------------------------------------------------------
// Reports
// ---------------------------------------------------------------------------

export const reportsApi = {
  getCashFlow: (month?: string): Promise<CashFlowMonth> => {
    const qs = month ? `?month=${month}` : '';
    return apiRequest(`/api/reports/cash-flow${qs}`);
  },

  getCashFlowHistory: (months = 12): Promise<CashFlowMonth[]> =>
    apiRequest(`/api/reports/cash-flow/history?months=${months}`),

  getByCategory: (month?: string): Promise<CategorySpend[]> => {
    const qs = month ? `?month=${month}` : '';
    return apiRequest(`/api/reports/by-category${qs}`);
  },

  getByTag: (month?: string, tagId?: number): Promise<TagSpend[]> => {
    const params = new URLSearchParams();
    if (month) params.set('month', month);
    if (tagId != null) params.set('tag_id', String(tagId));
    const qs = params.toString();
    return apiRequest(`/api/reports/by-tag${qs ? '?' + qs : ''}`);
  },

  getTopMerchants: (month?: string, limit = 10): Promise<MerchantSpend[]> => {
    const params = new URLSearchParams();
    if (month) params.set('month', month);
    params.set('limit', String(limit));
    return apiRequest(`/api/reports/merchants?${params}`);
  },

  getNetWorth: (): Promise<{ liquid_cents: number; investment_cents: number; debt_cents: number; net_worth_cents: number }> =>
    apiRequest('/api/reports/net-worth'),

  getNetWorthHistory: (months = 12): Promise<NetWorthSnapshot[]> =>
    apiRequest(`/api/reports/net-worth/history?months=${months}`),

  getForecast: (days: 30 | 60 | 90 = 30): Promise<ForecastEntry[]> =>
    apiRequest(`/api/reports/forecast?days=${days}`),

  getFinancialHealth: (): Promise<FinancialHealthScore> =>
    apiRequest('/api/reports/financial-health'),
};

// ---------------------------------------------------------------------------
// Plaid
// ---------------------------------------------------------------------------

export const plaidApi = {
  getLinkToken: (itemId?: string): Promise<{ link_token: string; expiration: string }> =>
    apiRequest('/api/plaid/link-token', {
      method: 'POST',
      body: JSON.stringify(itemId ? { item_id: itemId } : {}),
    }),

  exchangeToken: (publicToken: string, institutionName?: string): Promise<PlaidItem> =>
    apiRequest('/api/plaid/exchange-token', {
      method: 'POST',
      body: JSON.stringify({ public_token: publicToken, institution_name: institutionName }),
    }),

  listItems: (): Promise<PlaidItem[]> => apiRequest('/api/plaid/items'),

  deleteItem: (itemId: string): Promise<{ message: string }> =>
    apiRequest(`/api/plaid/items/${itemId}`, { method: 'DELETE' }),

  resetCursor: (itemId: string): Promise<{ message: string }> =>
    apiRequest(`/api/plaid/items/${itemId}/reset-cursor`, { method: 'POST' }),

  sync: (): Promise<PlaidSyncResult[]> =>
    apiRequest('/api/plaid/sync', { method: 'POST' }),

  getSyncLog: (): Promise<PlaidSyncLogEntry[]> =>
    apiRequest('/api/plaid/sync/log'),

  deleteSandboxData: (): Promise<{
    message: string;
    transactions_deleted: number;
    accounts_deleted: number;
    recurring_streams_deleted: number;
    net_worth_snapshots_deleted: number;
    plaid_items_deleted: number;
  }> => apiRequest('/api/plaid/sandbox-data', { method: 'DELETE' }),
};

// ---------------------------------------------------------------------------
// Insights
// ---------------------------------------------------------------------------

export const insightsApi = {
  getFeed: (): Promise<{
    generated_at: string;
    cards: Array<{
      type: string;
      severity: string;
      title: string;
      summary: string;
      detail?: string | null;
    }>;
    actionable_count: number;
  }> => apiRequest('/api/insights/feed'),

  markViewed: (): Promise<{ ok: boolean }> =>
    apiRequest('/api/insights/mark-viewed', { method: 'POST' }),
};

// ---------------------------------------------------------------------------
// Auth / Users (re-exported for compatibility)
// ---------------------------------------------------------------------------

export interface UserPublic {
  id: number;
  username: string;
  is_owner: boolean;
  created_at: string;
}

export const usersApi = {
  list: (): Promise<UserPublic[]> => apiRequest('/api/auth/users'),

  create: (data: { username: string; password: string }): Promise<UserPublic> =>
    apiRequest('/api/auth/users', { method: 'POST', body: JSON.stringify(data) }),

  delete: (id: number): Promise<void> =>
    apiRequest(`/api/auth/users/${id}`, { method: 'DELETE' }),
};

// ---------------------------------------------------------------------------
// Piggy Banks (savings goals)
// ---------------------------------------------------------------------------

import type { PiggyBank, PiggyBankCreate, PiggyBankUpdate } from '@/types/v2';

export const piggyApi = {
  list: (activeOnly = false): Promise<PiggyBank[]> =>
    apiRequest(`/api/piggy${activeOnly ? '?active_only=true' : ''}`),

  create: (data: PiggyBankCreate): Promise<PiggyBank> =>
    apiRequest('/api/piggy', { method: 'POST', body: JSON.stringify(data) }),

  update: (id: number, data: PiggyBankUpdate): Promise<PiggyBank> =>
    apiRequest(`/api/piggy/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),

  addAmount: (id: number, amountCents: number): Promise<PiggyBank> =>
    apiRequest(`/api/piggy/${id}/add?amount_cents=${amountCents}`, { method: 'POST' }),

  delete: (id: number): Promise<void> =>
    apiRequest(`/api/piggy/${id}`, { method: 'DELETE' }),
};

// ---------------------------------------------------------------------------
// Health
// ---------------------------------------------------------------------------

export const healthApi = {
  check: (): Promise<{ ok: boolean; version: string }> =>
    apiRequest('/healthz'),
};
