/**
 * V2 API client — all calls go to the V2 backend via /api/*.
 * Uses cookie auth with Authorization: Bearer fallback from sessionStorage.
 */
import { getAuthHeaders } from '@/lib/auth';
import { getApiBaseUrl } from '@/lib/api-base';
import type {
  Account,
  AuditEntry,
  AuditListResponse,
  AutosyncConfig,
  AutosyncConfigUpdate,
  Budget,
  BudgetCopyResult,
  BudgetHistoryRow,
  BudgetProgress,
  CashFlowMonth,
  Category,
  CategorySpend,
  Diagnostics,
  ExpenseBreakdown,
  FinancialHealthScore,
  ForecastEntry,
  IncomeBreakdown,
  InvestmentHolding,
  Member,
  MerchantSpend,
  NetWorthSnapshot,
  NetWorthSummary,
  PlaidItem,
  PlaidSyncLogEntry,
  PlaidSyncResult,
  RecurringStream,
  Tag,
  Transaction,
  TransactionDateRange,
  TransactionFilters,
  TransactionSplit,
  ManualCashTransactionCreate,
  MerchantAlias,
  MerchantRule,
  MerchantRuleApplyResult,
  MerchantRulePreviewResult,
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

/**
 * Coerce a FastAPI / Pydantic error response body into a *plain string*
 * suitable for `<p>{detail}</p>` rendering and toast messages.
 *
 * Pydantic v2 validation failures (HTTP 422) come back as
 * `{ detail: [{ type, loc, msg, input, ctx }, ...] }` — an **array of
 * objects**, not a string. Treating that array as the error message and
 * letting it land inside the React tree (e.g. via `toast.error(...)` or
 * `<p>{err.detail}</p>`) triggers React error #31 ("Objects are not
 * valid as a React child") and crashes the page. Always normalise here
 * so callers can assume `ApiError.detail` is a string.
 */
function extractErrorDetail(body: unknown, fallback: string): string {
  if (!body || typeof body !== 'object') return fallback;
  const obj = body as Record<string, unknown>;
  const raw = obj.detail ?? obj.message;
  if (typeof raw === 'string' && raw.length > 0) return raw;
  if (Array.isArray(raw)) {
    // Pydantic 422: pick the human-readable `msg` from each entry; fall
    // back to the loc-joined path if msg is missing on a malformed item.
    const messages = raw
      .map((entry) => {
        if (!entry || typeof entry !== 'object') return null;
        const e = entry as Record<string, unknown>;
        const msg = typeof e.msg === 'string' ? e.msg : null;
        const loc = Array.isArray(e.loc) ? e.loc.filter((p) => p !== 'body').join('.') : null;
        if (msg && loc) return `${loc}: ${msg}`;
        return msg ?? loc ?? null;
      })
      .filter((s): s is string => Boolean(s));
    if (messages.length > 0) return messages.join('; ');
  }
  return fallback;
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
    const fallback = `HTTP ${response.status}`;
    let detail = fallback;
    try {
      const body = await response.json();
      detail = extractErrorDetail(body, fallback);
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

  cashWallet: (): Promise<Account> => apiRequest("/api/accounts/cash-wallet"),

  /** Create a custom-named manual cash wallet. */
  createCashWallet: (data: {
    name: string;
    initial_balance_cents: number;
    owner_user_id?: number | null;
  }): Promise<Account> =>
    apiRequest("/api/accounts/cash-wallet", {
      method: "POST",
      body: JSON.stringify(data),
    }),

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
    /** Fallback label for ACH / check / bill-pay rows without a Plaid merchant. */
    merchant_label?: string | null;
    /** Optional substring narrow — see MerchantRule.description_contains. */
    description_contains?: string | null;
  }): Promise<MerchantRule> =>
    apiRequest('/api/merchant-rules', { method: 'POST', body: JSON.stringify(data) }),

  delete: (id: number): Promise<{ ok: boolean }> =>
    apiRequest(`/api/merchant-rules/${id}`, { method: 'DELETE' }),

  preview: (data: {
    category_id?: number | null;
    rule_id?: number | null;
    merchant_entity_id?: string | null;
    merchant_name?: string | null;
    merchant_label?: string | null;
    description_contains?: string | null;
  }): Promise<MerchantRulePreviewResult> =>
    apiRequest('/api/merchant-rules/preview', { method: 'POST', body: JSON.stringify(data) }),

  applyExisting: (ruleId: number): Promise<MerchantRuleApplyResult> =>
    apiRequest(`/api/merchant-rules/${ruleId}/apply-existing`, { method: 'POST' }),
};

// ---------------------------------------------------------------------------
// Merchant aliases (display rename — separate from category rules)
// ---------------------------------------------------------------------------

export const merchantAliasesApi = {
  list: (): Promise<MerchantAlias[]> => apiRequest('/api/merchant-aliases'),

  upsert: (data: {
    display_name: string;
    merchant_entity_id?: string | null;
    merchant_name?: string | null;
    /** Fallback for transactions without a Plaid merchant (ACH / checks). */
    merchant_label?: string | null;
  }): Promise<MerchantAlias> =>
    apiRequest('/api/merchant-aliases', {
      method: 'PUT',
      body: JSON.stringify(data),
    }),

  /** Delete by merchant_entity_id + merchant_name (clears both eid: and name:
   * twin rows the upsert wrote). Pass merchant_key directly to delete a
   * single key. */
  delete: (data: {
    merchant_key?: string | null;
    merchant_entity_id?: string | null;
    merchant_name?: string | null;
    merchant_label?: string | null;
  }): Promise<void> =>
    apiRequest('/api/merchant-aliases/delete', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
};

// ---------------------------------------------------------------------------
// Transactions
// ---------------------------------------------------------------------------

function buildTransactionQuery(filters: TransactionFilters): string {
  const params = new URLSearchParams();
  if (filters.month) params.set('month', filters.month);
  if (filters.account_id != null) params.set('account_id', String(filters.account_id));
  if (filters.category_id != null) params.set('category_id', String(filters.category_id));
  if (filters.parent_category_id != null)
    params.set('parent_category_id', String(filters.parent_category_id));
  if (filters.tag_id != null) params.set('tag_id', String(filters.tag_id));
  if (filters.search) params.set('search', filters.search);
  if (filters.channel) params.set('channel', filters.channel);
  if (filters.pending_only != null) params.set('pending_only', String(filters.pending_only));
  if (filters.user_id != null) params.set('user_id', String(filters.user_id));
  if (filters.transaction_class) params.set('transaction_class', filters.transaction_class);
  if (filters.exclude_internal_transfers != null)
    params.set('exclude_internal_transfers', String(filters.exclude_internal_transfers));
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

  /**
   * PATCH /api/transactions/{id}
   *
   * `transaction_class` is the preferred knob — it writes
   * `manual_class_override` on the server so the auto-classifier never
   * overwrites the user's choice on the next sync. The legacy
   * `is_internal_transfer` boolean still works for backward compat (it
   * maps to override='internal_transfer' when true, back to 'auto' when
   * false). Changing `category_id` re-runs the classifier on just that
   * row.
   */
  update: (
    id: number,
    data: {
      category_id?: number | null;
      user_note?: string;
      merchant_name?: string;
      is_private?: boolean;
      is_internal_transfer?: boolean;
      transaction_class?: import('@/types/v2').TransactionClass;
    },
  ): Promise<Transaction> =>
    apiRequest(`/api/transactions/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),

  delete: (id: number): Promise<void> =>
    apiRequest(`/api/transactions/${id}`, { method: 'DELETE' }),

  addTag: (transactionId: number, tagId: number): Promise<void> =>
    apiRequest(`/api/transactions/${transactionId}/tags/${tagId}`, { method: 'POST' }),

  removeTag: (transactionId: number, tagId: number): Promise<void> =>
    apiRequest(`/api/transactions/${transactionId}/tags/${tagId}`, { method: 'DELETE' }),

  getDateRange: (): Promise<TransactionDateRange> =>
    apiRequest('/api/transactions/date-range'),

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

  exportUrl: (filters: TransactionFilters = {}): string => {
    const params = new URLSearchParams();
    if (filters.month) params.set('month', filters.month);
    if (filters.account_id != null) params.set('account_id', String(filters.account_id));
    if (filters.category_id != null) params.set('category_id', String(filters.category_id));
    if (filters.tag_id != null) params.set('tag_id', String(filters.tag_id));
    if (filters.exclude_internal_transfers != null)
      params.set('exclude_internal_transfers', String(filters.exclude_internal_transfers));
    const qs = params.toString();
    return `${API_BASE}/api/transactions/export${qs ? '?' + qs : ''}`;
  },
};

// ---------------------------------------------------------------------------
// Recurring
// ---------------------------------------------------------------------------

export const recurringApi = {
  list: (
    direction?: 'inflow' | 'outflow',
    activeOnly = true,
    userStatuses?: Array<'active' | 'paused' | 'cancelled'>,
  ): Promise<RecurringStream[]> => {
    const params = new URLSearchParams();
    if (direction) params.set('direction', direction);
    params.set('active_only', String(activeOnly));
    if (userStatuses && userStatuses.length > 0) {
      for (const s of userStatuses) params.append('user_status', s);
    }
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
    data: {
      user_label?: string | null;
      category_id?: number | null;
      user_status?: 'active' | 'paused' | 'cancelled';
      paused_until?: string | null;
      price_change_snoozed_until?: string | null;
    },
  ): Promise<RecurringStream> =>
    apiRequest(`/api/recurring/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),

  bulk: (data: {
    ids: number[];
    action: 'cancel' | 'pause' | 'reactivate' | 'snooze_price_change';
    paused_until?: string | null;
    snooze_days?: number;
  }): Promise<{ updated: number }> =>
    apiRequest('/api/recurring/bulk', { method: 'POST', body: JSON.stringify(data) }),
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

  /** Bulk-copy every budget from one month to another. Idempotent. */
  copy: (fromMonth: string, toMonth: string): Promise<BudgetCopyResult> =>
    apiRequest(
      `/api/budgets/copy?from=${encodeURIComponent(fromMonth)}&to=${encodeURIComponent(toMonth)}`,
      { method: 'POST' },
    ),

  /** Heatmap data for Reports → Budget History. */
  getHistory: (months = 12): Promise<BudgetHistoryRow[]> =>
    apiRequest(`/api/budgets/history?months=${months}`),
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

  /**
   * GET /api/reports/by-category
   *
   * - rollup='primary' (default) aggregates detailed PFC children into their
   *   parent bucket so charts show ~10–15 slices. Each row has
   *   `bucket_key='p:<id>'` and `children_count`.
   * - rollup='detailed' + parent_category_id scopes the result to children of
   *   that primary bucket — used for the Focus-mode drilldown on Reports.
   */
  getByCategory: (
    month?: string,
    opts?: { rollup?: "primary" | "detailed"; parent_category_id?: number },
  ): Promise<CategorySpend[]> => {
    const params = new URLSearchParams();
    if (month) params.set("month", month);
    if (opts?.rollup) params.set("rollup", opts.rollup);
    if (opts?.parent_category_id != null) {
      params.set("parent_category_id", String(opts.parent_category_id));
    }
    const qs = params.toString();
    return apiRequest(`/api/reports/by-category${qs ? `?${qs}` : ""}`);
  },

  getTopMerchants: (month?: string, limit = 10): Promise<MerchantSpend[]> => {
    const params = new URLSearchParams();
    if (month) params.set('month', month);
    params.set('limit', String(limit));
    return apiRequest(`/api/reports/merchants?${params}`);
  },

  getNetWorth: (): Promise<NetWorthSummary> =>
    apiRequest('/api/reports/net-worth'),

  getNetWorthHistory: (months = 12): Promise<NetWorthSnapshot[]> =>
    apiRequest(`/api/reports/net-worth/history?months=${months}`),

  getForecast: (days: 30 | 60 | 90 = 30): Promise<ForecastEntry[]> =>
    apiRequest(`/api/reports/forecast?days=${days}`),

  getFinancialHealth: (): Promise<FinancialHealthScore> =>
    apiRequest('/api/reports/financial-health'),

  getIncome: (month?: string): Promise<IncomeBreakdown> => {
    const qs = month ? `?month=${month}` : '';
    return apiRequest(`/api/reports/income${qs}`);
  },

  /**
   * GET /api/reports/expenses — family expenses for a month broken down by
   * user + category. Mirror of `getIncome`; refunds naturally reduce
   * category totals.
   */
  getExpenses: (month?: string): Promise<ExpenseBreakdown> => {
    const qs = month ? `?month=${month}` : '';
    return apiRequest(`/api/reports/expenses${qs}`);
  },

  /**
   * GET /api/reports/diagnostics — owner-only. Surfaces suspicious rows
   * the classifier is unsure about (positive income, unmatched transfers,
   * large uncategorized amounts). Returns 403 for non-owners.
   */
  getDiagnostics: (month?: string): Promise<Diagnostics> => {
    const qs = month ? `?month=${month}` : '';
    return apiRequest(`/api/reports/diagnostics${qs}`);
  },
};

// ---------------------------------------------------------------------------
// Plaid
// ---------------------------------------------------------------------------

/** One bank finished during ``POST /api/plaid/sync/stream`` (NDJSON line). */
export type PlaidSyncStreamEvent = {
  index: number;
  total: number;
  result: PlaidSyncResult;
};

/**
 * Manual Plaid sync with NDJSON progress (Settings → Sync Now).
 * Yields one event per item as it completes; resolves with the full result list.
 */
export async function plaidSyncStream(
  onProgress: (ev: PlaidSyncStreamEvent) => void,
): Promise<PlaidSyncResult[]> {
  const url = `${getApiBaseUrl()}/api/plaid/sync/stream`;
  const headers: Record<string, string> = {
    ...(getAuthHeaders() as Record<string, string>),
  };
  const response = await fetch(url, { method: 'POST', headers, credentials: 'include' });
  if (!response.ok) {
    const fallback = `HTTP ${response.status}`;
    let detail = fallback;
    try {
      const body = await response.json();
      detail = extractErrorDetail(body, fallback);
    } catch {
      // ignore
    }
    throw new ApiError(response.status, detail, detail);
  }
  const reader = response.body?.getReader();
  if (!reader) {
    throw new ApiError(0, 'No response body', 'No response body');
  }
  const decoder = new TextDecoder();
  let buffer = '';
  const collected: PlaidSyncResult[] = [];

  const flushLine = (raw: string) => {
    const trimmed = raw.trim();
    if (!trimmed) return;
    const msg = JSON.parse(trimmed) as PlaidSyncStreamEvent;
    onProgress(msg);
    collected.push(msg.result);
  };

  for (;;) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });
    let nl: number;
    while ((nl = buffer.indexOf('\n')) >= 0) {
      const line = buffer.slice(0, nl);
      buffer = buffer.slice(nl + 1);
      flushLine(line);
    }
    if (done) break;
  }
  flushLine(buffer);
  return collected;
}

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

  getItemDataSummary: (
    itemId: string,
  ): Promise<{ transactions_count: number; accounts_count: number }> =>
    apiRequest(`/api/plaid/items/${itemId}/data-summary`),

  deleteItem: (
    itemId: string,
    options: { purge?: boolean } = {},
  ): Promise<{
    message: string;
    transactions_deleted?: number;
    accounts_deleted?: number;
    recurring_streams_deleted?: number;
    plaid_items_deleted?: number;
  }> => {
    const qs = options.purge ? '?purge=true' : '';
    return apiRequest(`/api/plaid/items/${itemId}${qs}`, { method: 'DELETE' });
  },

  resetCursor: (itemId: string): Promise<{ message: string }> =>
    apiRequest(`/api/plaid/items/${itemId}/reset-cursor`, { method: 'POST' }),

  /** Re-fetch institution branding (logo, color) from Plaid and overwrite
   * the stored values — used by the "Refresh bank logo" UI when a previously
   * missing logo might now be available. */
  refreshBranding: (
    itemId: string,
  ): Promise<{
    logo_present: boolean;
    color_present: boolean;
    item_id: string;
    institution_name: string | null;
  }> =>
    apiRequest(`/api/plaid/items/${itemId}/refresh-branding`, { method: 'POST' }),

  sync: (): Promise<PlaidSyncResult[]> =>
    apiRequest('/api/plaid/sync', { method: 'POST' }),

  /** Same end state as ``sync``, but streams NDJSON progress for the UI. */
  syncStream: (onProgress: (ev: PlaidSyncStreamEvent) => void): Promise<PlaidSyncResult[]> =>
    plaidSyncStream(onProgress),

  getSyncLog: (): Promise<PlaidSyncLogEntry[]> =>
    apiRequest('/api/plaid/sync/log'),

  clearSyncLog: (): Promise<{ deleted: number; cleared_by: string | null }> =>
    apiRequest('/api/plaid/sync/log', { method: 'DELETE' }),

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

export type InsightSeverity = 'info' | 'warn';

export interface InsightUserState {
  dismissed: boolean;
  dismissed_at?: string | null;
  snoozed_until?: string | null;
}

export interface InsightCard {
  type: string;
  severity: InsightSeverity;
  title: string;
  summary: string;
  detail?: string | null;
  dedupe_key: string;
  action_url?: string | null;
  action_label?: string | null;
  /** Overlay from per-user dismiss/snooze. Missing on feeds served before Phase 4. */
  user_state?: InsightUserState | null;
  /** Server-computed flag: first_seen_at > user_preferences.insights_last_viewed_at. */
  is_new?: boolean;
  /** ISO-8601 — when the card was first persisted. Drives the "since 3d" footer. */
  first_seen_at?: string | null;
}

export interface InsightsFeed {
  generated_at: string;
  cards: InsightCard[];
  actionable_count: number;
  new_count: number;
}

/**
 * The dismiss/snooze endpoints accept the `dedupe_key` in the URL path, which
 * can include characters that require percent-encoding (e.g. ``:`` in
 * ``budget_risk:10:2026-04``).
 */
const encodeDedupe = (k: string) => encodeURIComponent(k);

export const insightsApi = {
  getFeed: (includeHidden = false): Promise<InsightsFeed> =>
    apiRequest(`/api/insights/feed${includeHidden ? '?include_hidden=true' : ''}`),

  markViewed: (): Promise<{ ok: boolean }> =>
    apiRequest('/api/insights/mark-viewed', { method: 'POST' }),

  dismiss: (dedupeKey: string): Promise<{ ok: boolean }> =>
    apiRequest(`/api/insights/${encodeDedupe(dedupeKey)}/dismiss`, { method: 'POST' }),

  snooze: (dedupeKey: string, until: Date): Promise<{ ok: boolean; snoozed_until: string }> =>
    apiRequest(`/api/insights/${encodeDedupe(dedupeKey)}/snooze`, {
      method: 'POST',
      body: JSON.stringify({ until: until.toISOString() }),
    }),

  unhide: (dedupeKey: string): Promise<{ ok: boolean }> =>
    apiRequest(`/api/insights/${encodeDedupe(dedupeKey)}/unhide`, { method: 'POST' }),
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
// App settings (autosync schedule)
// ---------------------------------------------------------------------------

export const appSettingsApi = {
  get: (): Promise<AutosyncConfig> => apiRequest('/api/settings/app'),

  update: (patch: AutosyncConfigUpdate): Promise<AutosyncConfig> =>
    apiRequest('/api/settings/app', {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),
};

// ---------------------------------------------------------------------------
// Internal-transfer settings (family-wide names list + rescan)
// ---------------------------------------------------------------------------

export interface InternalTransferSettings {
  names: string[];
  normalized_names?: string[] | null;
}

export type InternalTransferRescanHorizon = 'last_90_days' | 'all_time';

export interface InternalTransferRescanResult {
  rows_updated: number;
  name_rows_updated?: number;
  pair_rows_updated?: number;
  horizon: InternalTransferRescanHorizon;
  configured_names_count: number;
}

export const internalTransfersApi = {
  get: (): Promise<InternalTransferSettings> =>
    apiRequest('/api/settings/internal-transfers'),

  update: (names: string[]): Promise<InternalTransferSettings> =>
    apiRequest('/api/settings/internal-transfers', {
      method: 'PUT',
      body: JSON.stringify({ names }),
    }),

  rescan: (
    horizon: InternalTransferRescanHorizon = 'last_90_days',
  ): Promise<InternalTransferRescanResult> =>
    apiRequest('/api/settings/internal-transfers/rescan', {
      method: 'POST',
      body: JSON.stringify({ horizon }),
    }),
};

// ---------------------------------------------------------------------------
// Audit log
// ---------------------------------------------------------------------------

export interface AuditListParams {
  limit?: number;
  beforeId?: number | null;
  eventType?: string | null;
  category?: string | null;
}

export const auditApi = {
  list: (params: AuditListParams = {}): Promise<AuditListResponse> => {
    const qs = new URLSearchParams();
    if (params.limit) qs.set('limit', String(params.limit));
    if (params.beforeId) qs.set('before_id', String(params.beforeId));
    if (params.eventType) qs.set('event_type', params.eventType);
    if (params.category) qs.set('category', params.category);
    const query = qs.toString();
    return apiRequest(`/api/audit${query ? `?${query}` : ''}`);
  },

  eventTypes: (): Promise<string[]> => apiRequest('/api/audit/event-types'),

  clear: (
    params: { category?: string | null; beforeId?: number | null } = {},
  ): Promise<{ deleted: number; cleared_by: string | null }> => {
    const qs = new URLSearchParams();
    if (params.category) qs.set('category', params.category);
    if (params.beforeId) qs.set('before_id', String(params.beforeId));
    const query = qs.toString();
    return apiRequest(`/api/audit${query ? `?${query}` : ''}`, { method: 'DELETE' });
  },
};

export type { AuditEntry, AuditListResponse, AutosyncConfig, AutosyncConfigUpdate };

// ---------------------------------------------------------------------------
// Bot (/api/bot/*) — settings, chores, audit, milestones, mood, receipts
// ---------------------------------------------------------------------------

export interface TelegramLinkStatus {
  linked: boolean;
  chat_id?: number | null;
  telegram_username?: string | null;
  pending_code?: string | null;
  pending_expires_at?: string | null;
}

export interface TelegramLinkCode {
  code: string;
  expires_at: string;
  bot_username?: string | null;
}

export interface CoupleSettings {
  user_id: number;
  anniversary_date?: string | null;
  partner_user_id?: number | null;
  partner_username?: string | null;
  mood_threshold_cents: number;
  leaderboard_enabled: boolean;
  morning_brief_local: string;
  morning_brief_tz: string;
  quiet_hours_start: string;
  quiet_hours_end: string;
  sunday_brief_enabled: boolean;
}

export interface CoupleSettingsUpdate {
  anniversary_date?: string | null;
  partner_user_id?: number | null;
  mood_threshold_cents?: number;
  leaderboard_enabled?: boolean;
  morning_brief_local?: string;
  morning_brief_tz?: string;
  quiet_hours_start?: string;
  quiet_hours_end?: string;
  sunday_brief_enabled?: boolean;
}

export interface NotificationPref {
  alert_type: string;
  enabled: boolean;
  label: string;
  description?: string | null;
}

export interface ChoreRow {
  id: number;
  name: string;
  icon?: string | null;
  rotation: 'weekly' | 'biweekly' | 'fixed';
  fixed_user_id?: number | null;
  sort_order: number;
  is_active: boolean;
}

export interface ChoreCreatePayload {
  name: string;
  icon?: string | null;
  rotation?: 'weekly' | 'biweekly' | 'fixed';
  fixed_user_id?: number | null;
  sort_order?: number;
}

export interface ChoreAssignment {
  chore_id: number;
  chore_name: string;
  chore_icon?: string | null;
  week_start: string;
  user_id: number;
  username: string;
  completed_at?: string | null;
}

export interface AuditSession {
  id: number;
  week_start: string;
  host_user_id?: number | null;
  host_username?: string | null;
  snack?: string | null;
  tea_choice?: string | null;
  notes?: string | null;
  completed_at?: string | null;
}

export interface MilestoneRow {
  id: number;
  threshold_cents: number;
  label?: string | null;
  reached_at?: string | null;
}

export interface StreakRow {
  streak_type: string;
  label: string;
  current_count: number;
  longest_count: number;
  last_event_at?: string | null;
}

export interface MoodEntry {
  transaction_id: number;
  mood: 'happy' | 'meh' | 'regret';
  note?: string | null;
  created_at: string;
  transaction_amount_cents: number;
  transaction_name: string;
  transaction_date: string;
}

export interface ReceiptLine {
  id: number;
  line_number: number;
  description: string;
  quantity?: number | null;
  unit_price_cents?: number | null;
  total_cents: number;
}

export interface ReceiptRow {
  id: number;
  transaction_id?: number | null;
  merchant_name?: string | null;
  receipt_date?: string | null;
  total_cents?: number | null;
  tax_cents?: number | null;
  currency: string;
  parse_status: string;
  created_at: string;
  image_mime?: string | null;
  has_image: boolean;
  lines: ReceiptLine[];
}

export interface LeaderboardEntry {
  user_id: number;
  username: string;
  category_id: number;
  category_name: string;
  amount_cents: number;
}

export interface LeaderboardOut {
  week_start: string;
  entries: LeaderboardEntry[];
}

export const botApi = {
  // Telegram link
  telegramStatus: (): Promise<TelegramLinkStatus> =>
    apiRequest('/api/bot/telegram/status'),
  generateLinkCode: (): Promise<TelegramLinkCode> =>
    apiRequest('/api/bot/telegram/link', { method: 'POST' }),
  unlinkTelegram: (): Promise<void> =>
    apiRequest('/api/bot/telegram/link', { method: 'DELETE' }),
  sendTestAlert: (): Promise<{ sent: boolean; deduped?: boolean; queued_id?: number }> =>
    apiRequest('/api/bot/telegram/test', { method: 'POST' }),

  // Settings
  getSettings: (): Promise<CoupleSettings> => apiRequest('/api/bot/settings'),
  updateSettings: (patch: CoupleSettingsUpdate): Promise<CoupleSettings> =>
    apiRequest('/api/bot/settings', {
      method: 'PUT',
      body: JSON.stringify(patch),
    }),

  // Notifications
  listNotificationPrefs: (): Promise<NotificationPref[]> =>
    apiRequest('/api/bot/notifications'),
  setNotificationPref: (
    alertType: string,
    enabled: boolean,
  ): Promise<NotificationPref> =>
    apiRequest(`/api/bot/notifications/${encodeURIComponent(alertType)}`, {
      method: 'PUT',
      body: JSON.stringify({ enabled }),
    }),

  // Chores
  listChores: (): Promise<ChoreRow[]> => apiRequest('/api/bot/chores'),
  createChore: (body: ChoreCreatePayload): Promise<ChoreRow> =>
    apiRequest('/api/bot/chores', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  updateChore: (
    id: number,
    patch: Partial<ChoreRow>,
  ): Promise<ChoreRow> =>
    apiRequest(`/api/bot/chores/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),
  deleteChore: (id: number): Promise<void> =>
    apiRequest(`/api/bot/chores/${id}`, { method: 'DELETE' }),
  listChoreAssignments: (
    weekStart?: string,
  ): Promise<ChoreAssignment[]> =>
    apiRequest(
      `/api/bot/chores/assignments${weekStart ? `?week_start=${weekStart}` : ''}`,
    ),
  reassignChore: (
    choreId: number,
    weekStart: string,
    userId: number,
  ): Promise<ChoreAssignment> =>
    apiRequest(
      `/api/bot/chores/${choreId}/assignments/${weekStart}?user_id=${userId}`,
      { method: 'PUT' },
    ),
  setChoreCompleted: (
    choreId: number,
    weekStart: string,
    completed: boolean,
  ): Promise<ChoreAssignment> =>
    apiRequest(`/api/bot/chores/${choreId}/assignments/${weekStart}/completed`, {
      method: 'PUT',
      body: JSON.stringify({ completed }),
    }),

  // Audit
  currentAudit: (): Promise<AuditSession> =>
    apiRequest('/api/bot/audit/current'),
  updateAudit: (
    weekStart: string,
    patch: Partial<AuditSession> & { completed?: boolean },
  ): Promise<AuditSession> =>
    apiRequest(`/api/bot/audit/${weekStart}`, {
      method: 'PUT',
      body: JSON.stringify(patch),
    }),
  listAudit: (limit = 26): Promise<AuditSession[]> =>
    apiRequest(`/api/bot/audit?limit=${limit}`),

  // Streaks
  listStreaks: (): Promise<StreakRow[]> => apiRequest('/api/bot/streaks'),

  // Milestones
  listMilestones: (): Promise<MilestoneRow[]> =>
    apiRequest('/api/bot/milestones'),
  addMilestone: (
    thresholdCents: number,
    label?: string | null,
  ): Promise<MilestoneRow> =>
    apiRequest('/api/bot/milestones', {
      method: 'POST',
      body: JSON.stringify({ threshold_cents: thresholdCents, label }),
    }),
  deleteMilestone: (id: number): Promise<void> =>
    apiRequest(`/api/bot/milestones/${id}`, { method: 'DELETE' }),

  // Mood
  listRecentMoods: (limit = 50): Promise<MoodEntry[]> =>
    apiRequest(`/api/bot/mood/recent?limit=${limit}`),
  upsertMood: (
    transactionId: number,
    mood: 'happy' | 'meh' | 'regret',
    note?: string,
  ): Promise<unknown> =>
    apiRequest(`/api/bot/mood/${transactionId}`, {
      method: 'PUT',
      body: JSON.stringify({ mood, note }),
    }),

  // Receipts
  listReceipts: (limit = 40): Promise<ReceiptRow[]> =>
    apiRequest(`/api/bot/receipts?limit=${limit}`),
  getReceipt: (id: number): Promise<ReceiptRow> =>
    apiRequest(`/api/bot/receipts/${id}`),
  receiptImageUrl: (id: number): string =>
    `${getApiBaseUrl()}/api/bot/receipts/${id}/image`,
  deleteReceipt: (id: number): Promise<void> =>
    apiRequest(`/api/bot/receipts/${id}`, { method: 'DELETE' }),
  linkReceipt: (id: number, transactionId: number | null): Promise<ReceiptRow> => {
    const qs =
      transactionId == null
        ? ''
        : `?transaction_id=${encodeURIComponent(String(transactionId))}`;
    return apiRequest(`/api/bot/receipts/${id}/link${qs}`, { method: 'PATCH' });
  },
  logReceiptAsCash: (id: number): Promise<ReceiptRow> =>
    apiRequest(`/api/bot/receipts/${id}/log-as-cash`, { method: 'POST' }),

  // Leaderboard
  weeklyLeaderboard: (): Promise<LeaderboardOut> =>
    apiRequest('/api/bot/leaderboard'),

  // Activity log — recent bot events visible in the Bot → Activity tab.
  listActivity: (
    params: {
      limit?: number;
      severity?: 'info' | 'warn' | 'error';
      kind_prefix?: string;
    } = {},
  ): Promise<BotActivityEntry[]> => {
    const qs = new URLSearchParams();
    qs.set('limit', String(params.limit ?? 200));
    if (params.severity) qs.set('severity', params.severity);
    if (params.kind_prefix) qs.set('kind_prefix', params.kind_prefix);
    return apiRequest(`/api/bot/activity?${qs.toString()}`);
  },
  clearActivity: (olderThanDays = 0): Promise<void> =>
    apiRequest(`/api/bot/activity?older_than_days=${olderThanDays}`, {
      method: 'DELETE',
    }),
};

export interface BotActivityEntry {
  id: number;
  user_id?: number | null;
  chat_id?: number | null;
  kind: string;
  severity: 'info' | 'warn' | 'error';
  summary: string;
  payload: Record<string, unknown>;
  error?: string | null;
  created_at: string;
}

// ---------------------------------------------------------------------------
// Health
// ---------------------------------------------------------------------------

export const healthApi = {
  check: (): Promise<{ ok: boolean; version: string }> =>
    apiRequest('/healthz'),
};
