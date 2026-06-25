import { useAsync } from './useAsync';
import { getAISummary } from '../api/client';
import type { TransactionAISummary } from '../api/types';

/** AI narrative for a date range, normalized so callers never need optional
 * chaining/nullish-coalescing for the loading-or-unfetched state. */
export function useAISummary(startDate?: string, endDate?: string) {
  const { data, loading } = useAsync<TransactionAISummary>(
    () => getAISummary({ start_date: startDate, end_date: endDate }),
    [startDate, endDate]
  );

  if (!data) {
    return { narrative: null, available: false, loading };
  }
  return { narrative: data.narrative, available: data.available, loading };
}
