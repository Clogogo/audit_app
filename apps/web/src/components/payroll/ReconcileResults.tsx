import type { PayrollReconcileResult, ReconcileStatus } from '../../api/types';
import { formatCurrency } from '../../lib/utils';
import { Card, CardContent, CardHeader, CardTitle } from '../ui/card';

const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
];

const STATUS_STYLES: Record<ReconcileStatus, { label: string; className: string }> = {
  matched: { label: 'Matched', className: 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300' },
  underpaid: { label: 'Underpaid', className: 'bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300' },
  overpaid: { label: 'Overpaid', className: 'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300' },
  not_paid: { label: 'Not paid', className: 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300' },
};

function StatusBadge({ status }: { status: ReconcileStatus }) {
  const { label, className } = STATUS_STYLES[status];
  return <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${className}`}>{label}</span>;
}

function SummaryTile({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="rounded-lg border p-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={`text-lg font-semibold ${tone ?? ''}`}>{value}</p>
    </div>
  );
}

/** The reconciliation of a payroll schedule with the bank payments; collapsed to a one-line summary. */
export function ReconcileResults({ result }: { result: PayrollReconcileResult }) {
  const { summary, lines } = result;
  const problemRows = result.skipped_rows.filter((r) => !r.ignored);
  const ignoredRows = result.skipped_rows.filter((r) => r.ignored);
  const attention = summary.underpaid + summary.overpaid + summary.not_paid;
  const outOfSync = lines.filter((l) => l.in_sync === false).length;
  const duplicates = lines.filter((l) => l.extra_payment_ids.length > 0).length;
  const gap = summary.paid_total - summary.expected_total;

  return (
    <details className="rounded-lg border bg-card">
      <summary className="cursor-pointer px-4 py-3 text-sm font-medium">
        Schedule vs bank — {MONTHS[result.month - 1]} {result.year}: {summary.matched} of {summary.rows} matched
        {attention > 0 && ` · ${attention} need attention`}
        {duplicates > 0 && ` · ${duplicates} possible duplicate payment${duplicates === 1 ? '' : 's'}`}
        {outOfSync > 0 && ` · ${outOfSync} total${outOfSync === 1 ? '' : 's'} differ from the staff directory`}
        {result.unlinked_staff.length > 0 && ` · ${result.unlinked_staff.length} staff not on the schedule`}
      </summary>
      <div className="space-y-4 px-4 pb-4">
        {result.notes.length > 0 && (
          <div role="note" className="rounded-lg border border-blue-300 bg-blue-50 px-4 py-3 text-sm text-blue-900 dark:bg-blue-900/20 dark:text-blue-200">
            {result.notes.map((n) => <p key={n}>{n}</p>)}
          </div>
        )}
        {problemRows.length > 0 && (
          <div className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:bg-amber-900/20 dark:text-amber-200">
            <p className="font-medium">
              {problemRows.length} row{problemRows.length === 1 ? '' : 's'} in the file could not be used and {problemRows.length === 1 ? 'was' : 'were'} left out:
            </p>
            <ul className="mt-1 list-disc pl-5 text-xs">
              {problemRows.map((r) => (
                <li key={r.row_number}>
                  Row {r.row_number}: {r.reason}
                  {r.label && <span className="text-muted-foreground"> ({r.label})</span>}
                </li>
              ))}
            </ul>
          </div>
        )}
        {ignoredRows.length > 0 && (
          <p className="text-xs text-muted-foreground">
            Ignored {ignoredRows.length} row{ignoredRows.length === 1 ? '' : 's'} that look like labels or totals:{' '}
            {ignoredRows.map((r) => `row ${r.row_number} “${r.label}”`).join(', ')}. Check none of them is a person.
          </p>
        )}

        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <SummaryTile label="Expected (schedule)" value={formatCurrency(summary.expected_total)} />
          <SummaryTile label="Paid (bank)" value={formatCurrency(summary.paid_total)} />
          <SummaryTile
            label="Difference"
            value={formatCurrency(gap)}
            tone={Math.abs(gap) < 100 ? 'text-green-600' : gap < 0 ? 'text-amber-600' : 'text-blue-600'}
          />
          <SummaryTile label="Matched" value={`${summary.matched} of ${summary.rows}`} />
          <SummaryTile label="Underpaid" value={String(summary.underpaid)} />
          <SummaryTile label="Overpaid" value={String(summary.overpaid)} />
          <SummaryTile label="Not paid" value={String(summary.not_paid)} />
          <SummaryTile label="Paid, not on schedule" value={`${summary.unmatched_payments} · ${formatCurrency(summary.unmatched_total)}`} />
        </div>

        <Card>
          <CardHeader><CardTitle>Schedule vs bank</CardTitle></CardHeader>
          <CardContent className="overflow-x-auto">
            <table className="w-full text-sm">
              <caption className="sr-only">Payroll schedule compared with bank payments</caption>
              <thead>
                <tr className="border-b text-left text-xs text-muted-foreground">
                  <th scope="col" className="py-2 pr-3">Row</th>
                  <th scope="col" className="py-2 pr-3">Name</th>
                  <th scope="col" className="py-2 pr-3 text-right">Expected</th>
                  <th scope="col" className="py-2 pr-3 text-right">Paid</th>
                  <th scope="col" className="py-2 pr-3 text-right">Difference</th>
                  <th scope="col" className="py-2 pr-3">Status</th>
                  <th scope="col" className="py-2 pr-3">Staff directory</th>
                  <th scope="col" className="py-2">Paid to</th>
                </tr>
              </thead>
              <tbody>
                {lines.map((l) => (
                  <tr key={l.row_number} className="border-b last:border-0">
                    <td className="py-2 pr-3 text-muted-foreground">{l.row_number}</td>
                    <td className="py-2 pr-3 font-medium">{l.name}</td>
                    <td className="py-2 pr-3 text-right">{formatCurrency(l.expected_amount)}</td>
                    <td className="py-2 pr-3 text-right">{formatCurrency(l.paid_amount)}</td>
                    <td className="py-2 pr-3 text-right">{l.difference === 0 ? '—' : formatCurrency(l.difference)}</td>
                    <td className="py-2 pr-3"><StatusBadge status={l.status} /></td>
                    <td className="py-2 pr-3 text-xs">
                      {l.staff_id == null ? (
                        <span className="text-amber-600">Not in staff directory</span>
                      ) : l.in_sync ? (
                        <span className="text-green-700">In sync</span>
                      ) : (
                        <span className="text-amber-600">
                          Total {formatCurrency(l.computed_net ?? 0)} ({l.net_difference && l.net_difference > 0 ? '+' : ''}{formatCurrency(l.net_difference ?? 0)})
                        </span>
                      )}
                    </td>
                    <td className="py-2 text-muted-foreground">
                      {l.paid_to ?? '—'}{l.paid_date ? ` · ${l.paid_date}` : ''}
                      {l.transaction_ids.length > 1 ? ` (${l.transaction_ids.length} payments)` : ''}
                      {l.note && <span className="block text-xs text-amber-600">{l.note}</span>}
                      {l.extra_payment_ids.length > 0 && (
                        <span className="block text-xs text-amber-600">
                          Also paid {formatCurrency(l.extra_paid_amount)} in {l.extra_payment_ids.length} other payment{l.extra_payment_ids.length === 1 ? '' : 's'} — possible duplicate
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>

        {result.unlinked_staff.length > 0 && (
          <p className="text-xs text-amber-700 dark:text-amber-400">
            In the staff directory but not on the schedule: {result.unlinked_staff.map((s) => `${s.full_name} (${formatCurrency(s.computed_net)})`).join(', ')}.
          </p>
        )}

        {result.unmatched_transactions.length > 0 && (
          <Card>
            <CardHeader><CardTitle>Paid from the account but not on the schedule</CardTitle></CardHeader>
            <CardContent className="overflow-x-auto">
              <table className="w-full text-sm">
                <caption className="sr-only">Bank payments not on the schedule</caption>
                <thead>
                  <tr className="border-b text-left text-xs text-muted-foreground">
                    <th scope="col" className="py-2 pr-3">Date</th>
                    <th scope="col" className="py-2 pr-3">Paid to</th>
                    <th scope="col" className="py-2 pr-3 text-right">Amount</th>
                    <th scope="col" className="py-2">Description</th>
                  </tr>
                </thead>
                <tbody>
                  {result.unmatched_transactions.map((t) => (
                    <tr key={t.id} className="border-b last:border-0">
                      <td className="py-2 pr-3">{t.date}</td>
                      <td className="py-2 pr-3 font-medium">{t.vendor ?? '—'}</td>
                      <td className="py-2 pr-3 text-right">{formatCurrency(t.amount)}</td>
                      <td className="py-2 text-muted-foreground">{t.description}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </CardContent>
          </Card>
        )}
      </div>
    </details>
  );
}
