import { useEffect, useState } from 'react';
import { Loader2, X } from 'lucide-react';
import { getTransactions } from '../api/client';
import type { Transaction } from '../api/types';
import { Button } from './ui/button';
import { formatCurrency, formatDate } from '../lib/utils';

interface TransactionPickerModalProps {
  title: string;
  category: string;
  type?: 'income' | 'expense';
  startDate?: string;
  endDate?: string;
  excludeTransactionIds: number[];
  onSelect: (transaction: Transaction) => void;
  onClose: () => void;
}

export function TransactionPickerModal({
  title, category, type = 'expense', startDate, endDate, excludeTransactionIds, onSelect, onClose,
}: TransactionPickerModalProps) {
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    getTransactions({
      type,
      category,
      start_date: startDate,
      end_date: endDate,
      limit: 100,
    })
      .then((page) => {
        if (cancelled) return;
        const exclude = new Set(excludeTransactionIds);
        setTransactions(page.items.filter((t) => !exclude.has(t.id)));
      })
      .catch(() => {
        if (!cancelled) setError('Failed to load transactions');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => { cancelled = true; };
  }, [category, type, startDate, endDate, excludeTransactionIds.join(',')]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-lg bg-card rounded-xl shadow-xl border border-border p-6 space-y-4 max-h-[80vh] flex flex-col">
        <div className="flex items-center justify-between">
          <h2 className="text-base font-semibold">{title}</h2>
          <button type="button" onClick={onClose} aria-label="Close" className="text-muted-foreground hover:text-foreground">
            <X className="h-4 w-4" />
          </button>
        </div>

        {loading ? (
          <div className="flex items-center gap-2 py-6 justify-center text-muted-foreground text-sm">
            <Loader2 className="h-4 w-4 animate-spin" />
            Loading transactions…
          </div>
        ) : error ? (
          <p className="text-sm text-destructive">{error}</p>
        ) : transactions.length === 0 ? (
          <p className="text-sm text-muted-foreground py-4 text-center">
            No unclaimed "{category}" transactions found{startDate ? ' for this period' : ''}.
          </p>
        ) : (
          <div className="overflow-y-auto divide-y divide-border -mx-6 px-6">
            {transactions.map((t) => (
              <button
                key={t.id}
                type="button"
                onClick={() => onSelect(t)}
                className="w-full flex items-center justify-between gap-3 py-3 text-left hover:bg-accent rounded-md px-2 -mx-2"
              >
                <div className="min-w-0">
                  <p className="text-sm font-medium truncate">{t.vendor || t.description}</p>
                  <p className="text-xs text-muted-foreground">{formatDate(t.date)}</p>
                </div>
                <span className="text-sm font-semibold text-expense shrink-0">{formatCurrency(t.amount)}</span>
              </button>
            ))}
          </div>
        )}

        <div className="flex justify-end pt-2">
          <Button variant="outline" onClick={onClose}>Cancel</Button>
        </div>
      </div>
    </div>
  );
}
