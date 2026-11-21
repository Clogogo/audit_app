import { useEffect, useMemo, useState } from 'react';
import { AlertCircle, BookOpen, CheckCircle2, Loader2, Upload } from 'lucide-react';
import {
  applyMappingSuggestions, getAccountMappings, getChartOfAccounts, importChartOfAccounts, setAccountMapping,
} from '../api/client';
import type { CategoryMappingRow, ChartAccount } from '../api/types';
import { AccountSelect } from '../components/accounting/AccountSelect';
import { Button } from '../components/ui/button';
import { Card, CardContent } from '../components/ui/card';
import { formatCurrency } from '../lib/utils';

type Tab = 'mapping' | 'chart';

const errorText = (err: unknown, fallback: string): string => {
  const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof detail === 'string' ? detail : fallback;
};

export function ChartOfAccounts() {
  const [accounts, setAccounts] = useState<ChartAccount[]>([]);
  const [imported, setImported] = useState(false);
  const [rows, setRows] = useState<CategoryMappingRow[]>([]);
  const [tab, setTab] = useState<Tab>('mapping');
  const [search, setSearch] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    try {
      const [chart, mappings] = await Promise.all([getChartOfAccounts(), getAccountMappings()]);
      setAccounts(chart.accounts);
      setImported(chart.imported);
      setRows(mappings.rows);
    } catch {
      setError('Could not load the chart of accounts.');
    }
  };
  useEffect(() => { void load(); }, []);

  const postable = useMemo(() => accounts.filter((a) => a.is_postable && a.status === 'Active'), [accounts]);
  const byCode = useMemo(() => new Map(accounts.map((a) => [a.code, a])), [accounts]);
  const unmapped = rows.filter((r) => !r.account_code);
  const unmappedTx = unmapped.reduce((n, r) => n + r.tx_count, 0);

  const run = async (work: () => Promise<string>) => {
    setBusy(true); setError(null); setMessage(null);
    try {
      setMessage(await work());
      await load();
    } catch (err) {
      setError(errorText(err, 'That did not work. Please try again.'));
    } finally {
      setBusy(false);
    }
  };

  const importChart = (file?: File) => run(async () => {
    const r = await importChartOfAccounts(file);
    return `Chart imported: ${r.created} added, ${r.updated} updated (${r.total} accounts).`;
  });
  const applySuggestions = () => run(async () => {
    const r = await applyMappingSuggestions();
    return `${r.applied} categor${r.applied === 1 ? 'y' : 'ies'} mapped to their suggested account; ${r.without_suggestion} still need your choice.`;
  });

  const choose = async (row: CategoryMappingRow, code: string | null) => {
    setError(null);
    const before = rows;
    setRows((rs) => rs.map((r) => (r === row ? { ...r, account_code: code } : r)));
    try {
      await setAccountMapping(row.category, row.type, code);
    } catch (err) {
      setRows(before);
      setError(errorText(err, `Could not save the mapping for ${row.category}.`));
    }
  };

  const shownAccounts = useMemo(() => {
    const q = search.trim().toLowerCase();
    return (q ? accounts.filter((a) => `${a.code} ${a.name} ${a.statement_section}`.toLowerCase().includes(q)) : accounts).slice(0, 300);
  }, [accounts, search]);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2"><BookOpen className="h-6 w-6 text-primary" />Chart of Accounts</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Each transaction category posts to an account. The Trial Balance and Profit &amp; Loss are built from this mapping.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button type="button" variant={imported ? 'outline' : 'default'} disabled={busy} onClick={() => importChart()}>
            {busy ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <Upload className="h-4 w-4 mr-2" />}
            {imported ? 'Re-import bundled chart' : 'Import chart of accounts'}
          </Button>
          <label className="text-xs underline cursor-pointer text-muted-foreground">
            or upload a CSV
            <input type="file" accept=".csv" className="sr-only" aria-label="Upload chart CSV" disabled={busy}
              onChange={(e) => { const f = e.target.files?.[0]; if (f) void importChart(f); e.target.value = ''; }} />
          </label>
        </div>
      </div>

      {error && (
        <div role="alert" className="flex items-center gap-2 rounded-lg border border-destructive/20 bg-destructive/5 px-4 py-3 text-sm text-destructive">
          <AlertCircle className="h-4 w-4 shrink-0" /><span>{error}</span>
        </div>
      )}
      {message && (
        <div role="status" className="flex items-center gap-2 rounded-lg border border-green-300 bg-green-50 px-4 py-3 text-sm text-green-800 dark:bg-green-950/20 dark:text-green-300">
          <CheckCircle2 className="h-4 w-4 shrink-0" /><span>{message}</span>
        </div>
      )}

      <div className="flex gap-2" role="group" aria-label="View">
        <Button type="button" size="sm" variant={tab === 'mapping' ? 'default' : 'outline'} aria-pressed={tab === 'mapping'} onClick={() => setTab('mapping')}>Category mapping</Button>
        <Button type="button" size="sm" variant={tab === 'chart' ? 'default' : 'outline'} aria-pressed={tab === 'chart'} onClick={() => setTab('chart')}>The chart ({accounts.length})</Button>
      </div>

      {!imported && (
        <Card><CardContent className="pt-6 text-sm text-muted-foreground">
          No chart imported yet. Click <strong>Import chart of accounts</strong> to load the 240-account chart that comes with the app.
        </CardContent></Card>
      )}

      {tab === 'mapping' && (
        <Card>
          <CardContent className="pt-6 space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="text-sm" data-testid="mapping-summary">
                {rows.length - unmapped.length} of {rows.length} categories mapped
                {unmapped.length > 0 && <span className="text-amber-700 dark:text-amber-400"> · {unmappedTx} transactions still unmapped</span>}
              </p>
              <Button type="button" size="sm" disabled={busy || !imported || unmapped.length === 0} onClick={applySuggestions}>
                Apply suggested accounts
              </Button>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <caption className="sr-only">Transaction categories and the account each posts to</caption>
                <thead>
                  <tr className="border-b text-left text-xs text-muted-foreground">
                    <th scope="col" className="py-2 pr-3">Category</th>
                    <th scope="col" className="py-2 pr-3">Money</th>
                    <th scope="col" className="py-2 pr-3 text-right">Transactions</th>
                    <th scope="col" className="py-2 pr-3 text-right">Total</th>
                    <th scope="col" className="py-2">Posts to account</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => {
                    const suggestion = r.suggested_code ? byCode.get(r.suggested_code) : undefined;
                    return (
                      <tr key={`${r.type}-${r.category}`} className="border-b last:border-0 align-top">
                        <td className="py-2 pr-3 font-medium">{r.category}</td>
                        <td className="py-2 pr-3 text-muted-foreground">{r.type === 'income' ? 'In' : 'Out'}</td>
                        <td className="py-2 pr-3 text-right">{r.tx_count}</td>
                        <td className="py-2 pr-3 text-right">{formatCurrency(r.total)}</td>
                        <td className="py-2 space-y-1">
                          <AccountSelect accounts={postable} value={r.account_code} disabled={!imported}
                            label={`Account for ${r.category} (${r.type})`} onChange={(code) => choose(r, code)} />
                          {!r.account_code && suggestion?.is_postable && (
                            <button type="button" className="block text-xs text-primary underline" onClick={() => choose(r, suggestion.code)}>
                              Use {suggestion.code} {suggestion.name}
                            </button>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {rows.length === 0 && <p className="py-4 text-sm text-muted-foreground">No transactions yet.</p>}
            </div>
          </CardContent>
        </Card>
      )}

      {tab === 'chart' && (
        <Card>
          <CardContent className="pt-6 space-y-3">
            <input type="search" aria-label="Search accounts" placeholder="Search by code, name or section…" value={search}
              onChange={(e) => setSearch(e.target.value)} className="w-full max-w-sm rounded-md border border-input bg-background px-3 py-2 text-sm" />
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <caption className="sr-only">Chart of accounts</caption>
                <thead>
                  <tr className="border-b text-left text-xs text-muted-foreground">
                    <th scope="col" className="py-2 pr-3">Code</th><th scope="col" className="py-2 pr-3">Name</th>
                    <th scope="col" className="py-2 pr-3">Type</th><th scope="col" className="py-2 pr-3">Section</th>
                    <th scope="col" className="py-2 pr-3">Normal</th><th scope="col" className="py-2">Posting</th>
                  </tr>
                </thead>
                <tbody>
                  {shownAccounts.map((a) => (
                    <tr key={a.code} className="border-b last:border-0">
                      <td className="py-1.5 pr-3 font-mono text-xs">{a.code}</td><td className="py-1.5 pr-3">{a.name}</td>
                      <td className="py-1.5 pr-3 text-muted-foreground">{a.category}</td><td className="py-1.5 pr-3 text-muted-foreground">{a.statement_section}</td>
                      <td className="py-1.5 pr-3 text-muted-foreground">{a.normal_balance}</td>
                      <td className="py-1.5 text-xs">{a.is_postable ? 'Yes' : <span className="text-muted-foreground">Group</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {shownAccounts.length === 0 && <p className="py-4 text-sm text-muted-foreground">No accounts match.</p>}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
