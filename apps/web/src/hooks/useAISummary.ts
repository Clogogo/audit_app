import { useAsync } from './useAsync';
import { getAISummary, getStaffAISummary } from '../api/client';
import type { TransactionAISummary } from '../api/types';

/** AI narrative for a date range, normalized so callers never need optional
 * chaining/nullish-coalescing for the loading-or-unfetched state. Passing
 * termId also folds a payroll forecast for the rest of that term into the
 * narrative (see GET /transactions/ai-summary). */
export function useAISummary(startDate?: string, endDate?: string, termId?: number) {
  const start = startDate || undefined;
  const end = endDate || undefined;

  const { data, loading } = useAsync<TransactionAISummary>(
    () => getAISummary({ start_date: start, end_date: end, term_id: termId }),
    [start, end, termId]
  );

  if (!data) {
    return { narrative: null, available: false, loading };
  }
  return { narrative: data.narrative, available: data.available, loading };
}

/** AI narrative over staff directory, staff loans, IOUs, payroll status,
 * and the current term (see GET /staff-directory/ai-summary). No filters —
 * always summarizes current staffing state. */
export function useStaffAISummary() {
  const { data, loading } = useAsync<TransactionAISummary>(() => getStaffAISummary(), []);

  if (!data) {
    return { narrative: null, available: false, loading };
  }
  return { narrative: data.narrative, available: data.available, loading };
}
