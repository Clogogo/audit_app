import { Fragment, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { AlertCircle, CheckCircle2, Loader2, Scale } from 'lucide-react';
import { getLedger, getProfitAndLoss, getTrialBalance } from '../api/client';
import type { Ledger, ProfitAndLoss, TrialBalance, UnmappedItem } from '../api/types';
import { LedgerModal } from '../components/accounting/LedgerModal';
import { Button } from '../components/ui/button';
import { Card, CardContent } from '../components/ui/card';
import { formatCurrency } from '../lib/utils';

type Tab = 'pl' | 'tb';

const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

// Subtotals shown right after these Profit & Loss sections
const SUBTOTAL_AFTER: Record<string, { label: string; key: 'gross_profit' | 'operating_profit' }> = {
  'Cost of Sales': { label: 'Gross profit', key: 'gross_profit' },
  'Operating Expenses (OpEx)': { label: 'Operating profit', key: 'operating_profit' },
};

function AccountButton({ code, onOpen, children }: { code: string; onOpen: (code: string) => void; children: React.ReactNode }) {
  return (
    <button type="button" className="text-left underline decoration-dotted underline-offset-2 hover:text-primary" onClick={() => onOpen(code)}>{children}</button>
  );
}

function UnmappedNotice({ items }: { items: UnmappedItem[] }) {
  if (items.length === 0) return null;
  return (
    <div role="alert" className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:bg-amber-900/20 dark:text-amber-200">
      <p className="flex items-center gap-2 font-medium"><AlertCircle className="h-4 w-4" />
        Some transactions have no account yet. They are shown as "Unmapped" so the totals still add up.
      </p>
      <ul className="mt-1 list-disc pl-6 text-xs">
        {items.map((u) => (
          <li key={`${u.type}-${u.category}`}>{u.category} ({u.type === 'income' ? 'in' : 'out'}): {u.count} transaction{u.count === 1 ? '' : 's'}, {formatCurrency(u.amount)}</li>
        ))}
      </ul>
      <Link to="/tax/chart-of-accounts" className="mt-2 inline-block text-xs underline">Map these categories</Link>
    </div>
  );
}

export function AccountingReports() {
  const today = new Date();
  const [start, setStart] = useState(iso(new Date(today.getFullYear(), today.getMonth(), 1)));
  const [end, setEnd] = useState(iso(today));
  const [tab, setTab] = useState<Tab>('pl');
  const [pl, setPl] = useState<ProfitAndLoss | null>(null);
  const [tb, setTb] = useState<TrialBalance | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ledger, setLedger] = useState<Ledger | null>(null);
  const requestId = useRef(0);
  const validRange = start !== '' && end !== '' && start <= end;

  useEffect(() => {
    if (!validRange) return;
    const id = ++requestId.current;
    setLoading(true);
    setError(null);
    (tab === 'pl' ? getProfitAndLoss(start, end).then(setPl) : getTrialBalance(start, end).then(setTb))
      .catch(() => { if (id === requestId.current) setError('Could not load the report.'); })
      .finally(() => { if (id === requestId.current) setLoading(false); });
  }, [start, end, tab, validRange]);

  const drillDown = async (code: string) => {
    try {
      setLedger(await getLedger(code, start, end));
    } catch {
      setError('Could not load the transactions for that line.');
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold flex items-center gap-2"><Scale className="h-6 w-6 text-primary" />Accounting Reports</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Built from your transactions on a cash basis, using the <Link to="/tax/chart-of-accounts" className="underline">chart of accounts mapping</Link>.
          Click any account to see the transactions behind it.
        </p>
      </div>

      <div className="flex flex-wrap items-end gap-4">
        <div className="space-y-1">
          <label htmlFor="report-start" className="text-xs font-medium">From</label>
          <input id="report-start" type="date" value={start} onChange={(e) => setStart(e.target.value)} className="block rounded-md border border-input bg-background px-3 py-2 text-sm" />
        </div>
        <div className="space-y-1">
          <label htmlFor="report-end" className="text-xs font-medium">To</label>
          <input id="report-end" type="date" value={end} onChange={(e) => setEnd(e.target.value)} className="block rounded-md border border-input bg-background px-3 py-2 text-sm" />
        </div>
        <div className="flex gap-2" role="group" aria-label="Report">
          <Button type="button" size="sm" variant={tab === 'pl' ? 'default' : 'outline'} aria-pressed={tab === 'pl'} onClick={() => setTab('pl')}>Profit &amp; Loss</Button>
          <Button type="button" size="sm" variant={tab === 'tb' ? 'default' : 'outline'} aria-pressed={tab === 'tb'} onClick={() => setTab('tb')}>Trial Balance</Button>
        </div>
        {loading && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" aria-label="Loading" />}
      </div>

      {!validRange && <p role="alert" className="text-sm text-destructive">The start date must not be after the end date.</p>}
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}

      {tab === 'pl' && pl && validRange && (
        <>
          <UnmappedNotice items={pl.unmapped} />
          <Card>
            <CardContent className="pt-6">
              <table className="w-full text-sm">
                <caption className="sr-only">Profit and loss, {pl.start_date} to {pl.end_date}</caption>
                <tbody>
                  {pl.sections.map((s) => (
                    <Fragment key={s.section}>
                      <tr className="border-b font-semibold"><th scope="row" className="py-2 text-left">{s.section}</th><td className="py-2 text-right">{formatCurrency(s.total)}</td></tr>
                      {s.accounts.map((a) => (
                        <tr key={a.code} className="text-muted-foreground">
                          <td className="py-1 pl-6"><AccountButton onOpen={drillDown} code={a.code}>{a.code} {a.name}</AccountButton></td>
                          <td className="py-1 text-right">{formatCurrency(a.amount)}</td>
                        </tr>
                      ))}
                      {SUBTOTAL_AFTER[s.section] && (
                        <tr className="border-y bg-muted/30 font-semibold">
                          <th scope="row" className="py-2 text-left">{SUBTOTAL_AFTER[s.section].label}</th>
                          <td className="py-2 text-right">{formatCurrency(pl[SUBTOTAL_AFTER[s.section].key])}</td>
                        </tr>
                      )}
                    </Fragment>
                  ))}
                  {pl.unmapped_income !== 0 && (
                    <tr className="text-amber-700 dark:text-amber-400"><td className="py-1"><AccountButton onOpen={drillDown} code="UNMAPPED-INCOME">Unmapped income</AccountButton></td><td className="py-1 text-right">{formatCurrency(pl.unmapped_income)}</td></tr>
                  )}
                  {pl.unmapped_expense !== 0 && (
                    <tr className="text-amber-700 dark:text-amber-400"><td className="py-1"><AccountButton onOpen={drillDown} code="UNMAPPED-EXPENSE">Unmapped expenses</AccountButton></td><td className="py-1 text-right">{formatCurrency(pl.unmapped_expense)}</td></tr>
                  )}
                  <tr className="border-y bg-muted/30 font-semibold"><th scope="row" className="py-2 text-left">Profit before tax</th><td className="py-2 text-right">{formatCurrency(pl.profit_before_tax)}</td></tr>
                  <tr className="text-base font-bold"><th scope="row" className="py-3 text-left">Net profit</th><td className="py-3 text-right">{formatCurrency(pl.net_profit)}</td></tr>
                </tbody>
              </table>
            </CardContent>
          </Card>
        </>
      )}

      {tab === 'tb' && tb && validRange && (
        <>
          <UnmappedNotice items={tb.unmapped} />
          <p role="status" className={`flex items-center gap-2 text-sm font-medium ${tb.balanced ? 'text-green-700 dark:text-green-400' : 'text-destructive'}`}>
            {tb.balanced ? <><CheckCircle2 className="h-4 w-4" />Balanced: debits equal credits</> : <><AlertCircle className="h-4 w-4" />Does not balance — please tell whoever maintains the app</>}
          </p>
          <Card>
            <CardContent className="pt-6 overflow-x-auto">
              <table className="w-full text-sm">
                <caption className="sr-only">Trial balance, {tb.start_date} to {tb.end_date}</caption>
                <thead>
                  <tr className="border-b text-left text-xs text-muted-foreground">
                    <th scope="col" className="py-2 pr-3">Account</th><th scope="col" className="py-2 pr-3">Type</th>
                    <th scope="col" className="py-2 pr-3 text-right">Debit</th><th scope="col" className="py-2 text-right">Credit</th>
                  </tr>
                </thead>
                <tbody>
                  {tb.rows.map((r) => (
                    <tr key={r.code} className="border-b last:border-0">
                      <td className="py-1.5 pr-3"><AccountButton onOpen={drillDown} code={r.code}>{r.code} {r.name}</AccountButton></td>
                      <td className="py-1.5 pr-3 text-muted-foreground">{r.category}</td>
                      <td className="py-1.5 pr-3 text-right">{r.debit ? formatCurrency(r.debit) : '—'}</td>
                      <td className="py-1.5 text-right">{r.credit ? formatCurrency(r.credit) : '—'}</td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr className="border-t font-semibold"><td colSpan={2} className="py-2 pr-3">Total</td>
                    <td className="py-2 pr-3 text-right">{formatCurrency(tb.total_debit)}</td><td className="py-2 text-right">{formatCurrency(tb.total_credit)}</td></tr>
                </tfoot>
              </table>
              <p className="mt-3 text-xs text-muted-foreground">
                Bank balances start from each bank account's opening balance. "Accumulated funds brought forward" is the opening cash plus any profit earned before {tb.start_date}.
                Profit &amp; loss lines cover {tb.start_date} to {tb.end_date}; the rest are cumulative.
              </p>
            </CardContent>
          </Card>
        </>
      )}

      {ledger && <LedgerModal ledger={ledger} onClose={() => setLedger(null)} />}
    </div>
  );
}
