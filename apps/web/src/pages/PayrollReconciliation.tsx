import { useEffect, useRef, useState } from 'react';
import { AlertCircle, ChevronLeft, ChevronRight, FileSpreadsheet, Loader2, Upload } from 'lucide-react';
import { getBankAccounts, reconcilePayroll } from '../api/client';
import type { BankAccount, PayrollReconcileResult, ReconcileStatus } from '../api/types';
import { Button } from '../components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { formatCurrency } from '../lib/utils';

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

export function extractErrorMessage(err: unknown): string {
  const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail) && detail.length > 0) return 'Please check the month and file, then try again.';
  return 'Reconciliation failed. Please try again.';
}

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

export function PayrollReconciliation() {
  const today = new Date();
  const [year, setYear] = useState(today.getFullYear());
  const [month, setMonth] = useState(today.getMonth() + 1);
  const [file, setFile] = useState<File | null>(null);
  const [accounts, setAccounts] = useState<BankAccount[]>([]);
  const [accountId, setAccountId] = useState<string>('');
  const [accountsFailed, setAccountsFailed] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<PayrollReconcileResult | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const requestId = useRef(0);

  useEffect(() => {
    getBankAccounts().then(setAccounts).catch(() => setAccountsFailed(true));
  }, []);

  const shiftMonth = (delta: number) => {
    requestId.current += 1;
    setLoading(false);
    const d = new Date(year, month - 1 + delta, 1);
    setYear(d.getFullYear());
    setMonth(d.getMonth() + 1);
    setResult(null);
    setError(null);
  };

  const run = async () => {
    if (!file) return;
    const id = ++requestId.current;
    setLoading(true);
    setError(null);
    try {
      const res = await reconcilePayroll(file, year, month, accountId ? Number(accountId) : undefined);
      if (id === requestId.current) setResult(res);
    } catch (err) {
      if (id !== requestId.current) return;
      setResult(null);
      setError(extractErrorMessage(err));
    } finally {
      if (id === requestId.current) setLoading(false);
    }
  };

  const summary = result?.summary;
  const gap = summary ? summary.paid_total - summary.expected_total : 0;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">Payroll Reconciliation</h1>
          <p className="text-sm text-muted-foreground">
            Upload the payroll schedule (.xlsx or .csv) and compare it with the salary payments in the bank account.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button type="button" aria-label="Previous month" onClick={() => shiftMonth(-1)}
            disabled={loading}
            className="p-1.5 rounded-md border border-input hover:bg-accent">
            <ChevronLeft className="h-4 w-4" />
          </button>
          <span className="text-sm font-semibold min-w-[130px] text-center">{MONTHS[month - 1]} {year}</span>
          <button type="button" aria-label="Next month" onClick={() => shiftMonth(1)}
            disabled={loading}
            className="p-1.5 rounded-md border border-input hover:bg-accent">
            <ChevronRight className="h-4 w-4" />
          </button>
        </div>
      </div>

      <Card>
        <CardContent className="pt-6 space-y-4">
          <div className="flex flex-wrap items-end gap-4">
            <div className="space-y-1">
              <label htmlFor="schedule-file" className="text-sm font-medium">Payroll schedule</label>
              <div className="flex items-center gap-2">
                <input
                  ref={inputRef}
                  id="schedule-file"
                  type="file"
                  accept=".xlsx,.xlsm,.csv"
                  className="sr-only peer"
                  onChange={(e) => { setFile(e.target.files?.[0] ?? null); setResult(null); setError(null); }}
                />
                <Button type="button" variant="outline" disabled={loading} onClick={() => inputRef.current?.click()}>
                  <FileSpreadsheet className="h-4 w-4 mr-2" />
                  {file ? 'Change file' : 'Choose file'}
                </Button>
                <span className="text-sm text-muted-foreground">{file?.name ?? 'No file chosen'}</span>
              </div>
            </div>
            <div className="space-y-1">
              <label htmlFor="bank-account" className="text-sm font-medium">Bank account (optional)</label>
              <select
                id="bank-account"
                value={accountId}
                disabled={loading}
                onChange={(e) => { setAccountId(e.target.value); setResult(null); setError(null); }}
                className="h-9 rounded-md border border-input bg-background px-3 text-sm"
              >
                <option value="">All accounts</option>
                {accounts.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.bank_name}{a.account_number ? ` · ${a.account_number}` : ''}
                  </option>
                ))}
              </select>
            </div>
            <Button type="button" onClick={run} disabled={!file || loading}>
              {loading ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <Upload className="h-4 w-4 mr-2" />}
              Reconcile
            </Button>
          </div>
          {accountsFailed && (
            <p className="text-xs text-amber-600">Couldn't load bank accounts — all accounts will be compared.</p>
          )}
          <p className="text-xs text-muted-foreground">
            The file needs a header row with a name column and an amount column (an account-number column helps matching).
            Only Salary and Wages expenses for {MONTHS[month - 1]} {year} are compared. Nothing is saved.
          </p>
        </CardContent>
      </Card>

      {error && (
        <div role="alert" className="flex items-center gap-2 rounded-lg border border-destructive/20 bg-destructive/5 px-4 py-3 text-sm text-destructive">
          <AlertCircle className="h-4 w-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      <div aria-live="polite" aria-busy={loading} className="space-y-6">
      {result && summary && (
        <>
          <h2 className="text-lg font-semibold">
            Results for {MONTHS[result.month - 1]} {result.year}
          </h2>
          {result.skipped_rows.length > 0 && (
            <div className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:bg-amber-900/20 dark:text-amber-200">
              <p className="font-medium">
                {result.skipped_rows.length} row{result.skipped_rows.length === 1 ? '' : 's'} in the file could not be used and {result.skipped_rows.length === 1 ? 'was' : 'were'} left out:
              </p>
              <ul className="mt-1 list-disc pl-5 text-xs">
                {result.skipped_rows.map((r) => (
                  <li key={r.row_number}>Row {r.row_number}: {r.reason}</li>
                ))}
              </ul>
            </div>
          )}
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <SummaryTile label="Expected (schedule)" value={formatCurrency(summary.expected_total)} />
            <SummaryTile label="Paid (bank)" value={formatCurrency(summary.paid_total)} />
            <SummaryTile
              label="Difference"
              value={formatCurrency(gap)}
              tone={Math.abs(gap) < 0.01 ? 'text-green-600' : gap < 0 ? 'text-amber-600' : 'text-blue-600'}
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
                    <th scope="col" className="py-2">Paid to</th>
                  </tr>
                </thead>
                <tbody>
                  {result.lines.map((l) => (
                    <tr key={l.row_number} className="border-b last:border-0">
                      <td className="py-2 pr-3 text-muted-foreground">{l.row_number}</td>
                      <td className="py-2 pr-3 font-medium">{l.name}</td>
                      <td className="py-2 pr-3 text-right">{formatCurrency(l.expected_amount)}</td>
                      <td className="py-2 pr-3 text-right">{formatCurrency(l.paid_amount)}</td>
                      <td className="py-2 pr-3 text-right">{l.difference === 0 ? '—' : formatCurrency(l.difference)}</td>
                      <td className="py-2 pr-3"><StatusBadge status={l.status} /></td>
                      <td className="py-2 text-muted-foreground">
                        {l.paid_to ?? '—'}{l.paid_date ? ` · ${l.paid_date}` : ''}
                        {l.transaction_ids.length > 1 ? ` (${l.transaction_ids.length} payments)` : ''}
                        {l.note && <span className="block text-xs text-amber-600">{l.note}</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </CardContent>
          </Card>

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
        </>
      )}
      </div>
    </div>
  );
}
