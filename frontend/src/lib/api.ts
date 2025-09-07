import {
  Expense,
  ExpenseCreate,
  ExpenseUpdate,
  ExpenseResponse,
  Limit,
  LimitCreate,
  ReportResponse,
  SyncStatus,
  HealthResponse
} from '@/types/api';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

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
