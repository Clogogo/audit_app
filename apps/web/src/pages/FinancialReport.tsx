import { useEffect, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { AlertCircle, ArrowLeft, Loader2, Printer } from 'lucide-react';
import { getFinancialReport } from '../api/client';
import type { FinancialReport as Report, ReportColumnKind } from '../api/types';
import { Button } from '../components/ui/button';
import { Card, CardContent } from '../components/ui/card';
import { formatCurrency, formatDate } from '../lib/utils';

const today = () => new Date().toLocaleDateString('en-CA');   // local date (YYYY-MM-DD), not UTC

function cell(value: unknown, kind: ReportColumnKind): string {
  if (value === undefined || value === null || value === '') return '';
  if (kind === 'money') return formatCurrency(Number(value));
  if (kind === 'pct') return `${(Number(value) * 100).toFixed(1)}%`;
  if (kind === 'date') return formatDate(String(value));
  return String(value);
}

export function FinancialReport() {
  const { slug = '' } = useParams();
  const [params, setParams] = useSearchParams();
  const asAt = params.get('as_at') || today();
  const start = params.get('start_date') || `${asAt.slice(0, 4)}-01-01`;
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    setReport(null);
    setError(null);
    getFinancialReport(slug, { as_at: asAt, start_date: start })
      .then((r) => live && setReport(r))
      .catch(() => live && setError('This report could not be loaded. Check the dates and try again.'));
    return () => { live = false; };
  }, [slug, asAt, start]);

  // Only the changed date goes in the URL, and a pinned start that would fall after the new end is dropped
  const setDate = (key: 'as_at' | 'start_date', value: string) => {
    if (!value) return;
    const next = new URLSearchParams(params);
    next.set(key, value);
    const pinned = next.get('start_date');
    if (pinned && pinned > (next.get('as_at') || today())) next.delete('start_date');
    setParams(next, { replace: true });
  };

  return (
    <div className="space-y-6">
      <Link to="/financial-reports" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground print:hidden">
        <ArrowLeft className="h-4 w-4" /> All reports
      </Link>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">{report?.title ?? 'Report'}</h1>
          {report && <p className="mt-0.5 text-sm text-muted-foreground">{report.subtitle}</p>}
        </div>
        <div className="flex flex-wrap items-end gap-3 text-sm print:hidden">
          {!report?.current_only && (<>
          <label className="grid gap-1"><span className="text-xs text-muted-foreground">From</span>
            <input type="date" value={start} onChange={(e) => setDate('start_date', e.target.value)} className="rounded-md border bg-background px-2 py-1" /></label>
          <label className="grid gap-1"><span className="text-xs text-muted-foreground">To (as at)</span>
            <input type="date" value={asAt} onChange={(e) => setDate('as_at', e.target.value)} className="rounded-md border bg-background px-2 py-1" /></label>
          </>)}
          <Button variant="outline" size="sm" onClick={() => window.print()}><Printer className="mr-1.5 h-4 w-4" />Print</Button>
        </div>
      </div>

      {error && <p role="alert" className="flex items-center gap-2 text-sm text-destructive"><AlertCircle className="h-4 w-4" />{error}</p>}
      {!report && !error && <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" />Loading…</p>}

      {report && (
        <>
          {report.estimate && (
            <div role="note" className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:bg-amber-900/20 dark:text-amber-200">
              <p className="font-medium">Estimate: check with your tax adviser before filing.</p>
              <ul className="mt-1 list-disc pl-5 text-xs">{report.assumptions.map((a) => <li key={a}>{a}</li>)}</ul>
            </div>
          )}
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {report.summary.map((s) => (
              <Card key={s.label}><CardContent className="pt-4">
                <p className="text-xs text-muted-foreground">{s.label}</p>
                <p className="mt-1 text-lg font-semibold tabular-nums">{cell(s.value, s.kind)}</p>
              </CardContent></Card>
            ))}
          </div>
          {report.sections.map((sec) => (
            <Card key={sec.title}>
              <CardContent className="overflow-x-auto pt-6">
                <h2 className="mb-3 text-sm font-semibold">{sec.title}</h2>
                {sec.rows.length === 0 ? <p className="text-sm text-muted-foreground">Nothing to show for this period.</p> : (
                  <table className="w-full text-sm">
                    <thead><tr className="border-b text-left text-xs text-muted-foreground">
                      {sec.columns.map((c) => <th key={c.key} scope="col" className={`py-2 pr-3 ${c.kind === 'money' || c.kind === 'pct' ? 'text-right' : ''}`}>{c.label}</th>)}
                    </tr></thead>
                    <tbody>{sec.rows.map((r, i) => (
                      <tr key={i} className="border-b last:border-0">
                        {sec.columns.map((c) => <td key={c.key} className={`py-1.5 pr-3 ${c.kind === 'money' || c.kind === 'pct' ? 'text-right tabular-nums' : ''}`}>{cell(r[c.key], c.kind)}</td>)}
                      </tr>
                    ))}</tbody>
                    {sec.total && (
                      <tfoot><tr className="border-t font-semibold">
                        {sec.columns.map((c) => <td key={c.key} className={`py-2 pr-3 ${c.kind === 'money' || c.kind === 'pct' ? 'text-right tabular-nums' : ''}`}>{cell(sec.total?.[c.key], c.kind)}</td>)}
                      </tr></tfoot>
                    )}
                  </table>
                )}
                {sec.note && <p className="mt-3 text-xs text-muted-foreground">{sec.note}</p>}
              </CardContent>
            </Card>
          ))}
        </>
      )}
    </div>
  );
}
