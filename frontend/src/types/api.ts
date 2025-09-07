export interface Expense {
  id: number;
  category: string;
  amount: number;
  date: string;
}

export interface ExpenseCreate {
  category: string;
  amount: number;
}

export interface ExpenseUpdate {
  category?: string;
  amount?: number;
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
