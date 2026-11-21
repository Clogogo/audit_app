import { XCircle } from 'lucide-react';
import type { Ledger } from '../../api/types';
import { formatCurrency } from '../../lib/utils';

/** The transactions behind one account line of a report. */
export function LedgerModal({ ledger, onClose }: { ledger: Ledger; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div role="dialog" aria-label={`Transactions for ${ledger.name}`}
        className="w-full max-w-3xl max-h-[85vh] overflow-y-auto rounded-xl border border-border bg-card p-6 shadow-xl space-y-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold">{ledger.name}</h2>
            <p className="text-xs text-muted-foreground">{ledger.code} · {ledger.start_date} to {ledger.end_date}</p>
          </div>
          <button type="button" aria-label="Close" onClick={onClose} className="text-muted-foreground hover:text-foreground">
            <XCircle className="h-5 w-5" />
          </button>
        </div>
        {ledger.rows.length === 0 ? (
          <p className="text-sm text-muted-foreground">No transactions in this period.</p>
        ) : (
          <table className="w-full text-sm">
            <caption className="sr-only">Transactions posted to {ledger.name}</caption>
            <thead>
              <tr className="border-b text-left text-xs text-muted-foreground">
                <th scope="col" className="py-2 pr-3">Date</th><th scope="col" className="py-2 pr-3">Description</th>
                <th scope="col" className="py-2 pr-3">Category</th>
                <th scope="col" className="py-2 pr-3 text-right">Debit</th><th scope="col" className="py-2 text-right">Credit</th>
              </tr>
            </thead>
            <tbody>
              {ledger.rows.map((r) => (
                <tr key={r.id} className="border-b last:border-0">
                  <td className="py-2 pr-3 whitespace-nowrap">{r.date}</td>
                  <td className="py-2 pr-3">{r.description}{r.vendor ? <span className="text-muted-foreground"> · {r.vendor}</span> : null}</td>
                  <td className="py-2 pr-3 text-muted-foreground">{r.category}</td>
                  <td className="py-2 pr-3 text-right">{r.debit ? formatCurrency(r.debit) : '—'}</td>
                  <td className="py-2 text-right">{r.credit ? formatCurrency(r.credit) : '—'}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="border-t font-semibold">
                <td colSpan={3} className="py-2 pr-3">Total</td>
                <td className="py-2 pr-3 text-right">{formatCurrency(ledger.total_debit)}</td>
                <td className="py-2 text-right">{formatCurrency(ledger.total_credit)}</td>
              </tr>
            </tfoot>
          </table>
        )}
      </div>
    </div>
  );
}
