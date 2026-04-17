/**
 * useTransactionsDateRange — shared data source for the month/year picker bounds.
 *
 * Every page that renders a MonthYearPicker consumes this hook (directly or via
 * the picker itself), so all pickers in the app agree on:
 *   - the oldest selectable month (earliest transaction we have),
 *   - the newest selectable month (latest transaction we have).
 *
 * The underlying query is cached for a few minutes and invalidated whenever
 * transactions are imported, created or deleted — see `invalidateTransactionsDateRange`.
 */
import { useQuery, useQueryClient } from '@tanstack/react-query';

import { transactionsApi } from '@/lib/api';
import type { TransactionDateRange } from '@/types/v2';

export const TRANSACTIONS_DATE_RANGE_QUERY_KEY = ['transactions', 'date-range'] as const;

export function useTransactionsDateRange() {
  return useQuery<TransactionDateRange>({
    queryKey: TRANSACTIONS_DATE_RANGE_QUERY_KEY,
    queryFn: transactionsApi.getDateRange,
    staleTime: 5 * 60 * 1000,
  });
}

/**
 * Invalidate the transactions date-range cache.
 * Call this from mutation `onSuccess` handlers that change the set of
 * transactions (Plaid sync, item delete/purge, cash transaction create/delete).
 */
export function useInvalidateTransactionsDateRange() {
  const queryClient = useQueryClient();
  return () => {
    queryClient.invalidateQueries({ queryKey: TRANSACTIONS_DATE_RANGE_QUERY_KEY });
  };
}
