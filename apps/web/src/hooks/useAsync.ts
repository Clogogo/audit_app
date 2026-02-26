import { useState, useEffect, useCallback } from 'react';

interface UseAsyncState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
}

export function useAsync<T>(
  asyncFunction: () => Promise<T>,
  dependencies: any[] = []
) {
  const [state, setState] = useState<UseAsyncState<T>>({
    data: null,
    loading: true,
    error: null,
  });

  const execute = useCallback(async () => {
    setState({ data: null, loading: true, error: null });
    try {
      const result = await asyncFunction();
      setState({ data: result, loading: false, error: null });
    } catch (err: any) {
      setState({ data: null, loading: false, error: err.message || 'An error occurred' });
    }
  }, dependencies);

  useEffect(() => {
    execute();
  }, [execute]);

  return { ...state, refetch: execute };
}
