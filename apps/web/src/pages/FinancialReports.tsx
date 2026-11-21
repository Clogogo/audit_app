import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Card } from '../components/ui/card';
import { REPORT_GROUPS, recentReportKeys, rememberReport, type ReportCard } from '../lib/financialReports';
import { formatDate } from '../lib/utils';

const ALL = REPORT_GROUPS.flatMap((g) => g.reports);
const today = () => new Date().toISOString().slice(0, 10);

function Tile({ report, asAt, small }: { report: ReportCard; asAt: string; small?: boolean }) {
  const Icon = report.icon;
  const to = report.to.startsWith('/financial-reports/') ? `${report.to}?as_at=${asAt}` : report.to;
  return (
    <Link to={to} onClick={() => rememberReport(report.key)} className="block h-full">
      <Card className={`flex h-full items-center gap-3 transition-colors hover:border-primary/60 ${small ? 'px-3 py-2' : 'px-4 py-4'}`}>
        <span className="rounded-md bg-primary/10 p-2 text-primary"><Icon className="h-4 w-4" /></span>
        <span className="min-w-0">
          <span className="block text-sm font-semibold">{report.title}</span>
          {!small && <span className="block text-xs text-muted-foreground">{report.description}</span>}
        </span>
      </Card>
    </Link>
  );
}

export function FinancialReports() {
  const [asAt, setAsAt] = useState(today());
  const recent = recentReportKeys().map((k) => ALL.find((r) => r.key === k)).filter((r): r is ReportCard => !!r);

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Financial Reports</h1>
          <p className="mt-0.5 text-sm text-muted-foreground">Figures up to {formatDate(asAt)}</p>
        </div>
        <label className="flex items-center gap-2 text-sm">
          <span className="text-xs uppercase tracking-wide text-muted-foreground">As at</span>
          <input type="date" value={asAt} max={today()} onChange={(e) => e.target.value && setAsAt(e.target.value)}
            className="rounded-md border bg-background px-2 py-1" aria-label="Report date" />
        </label>
      </div>

      {recent.length > 0 && (
        <section aria-label="Where you left off">
          <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Where you left off</h2>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">{recent.map((r) => <Tile key={r.key} report={r} asAt={asAt} small />)}</div>
        </section>
      )}

      {REPORT_GROUPS.map((g) => (
        <section key={g.title} aria-label={g.title}>
          <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide">{g.title} <span className="ml-1 font-normal normal-case text-muted-foreground">{g.hint}</span></h2>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{g.reports.map((r) => <Tile key={r.key} report={r} asAt={asAt} />)}</div>
        </section>
      ))}

      <p className="text-xs text-muted-foreground">
        Looking for charts? <Link to="/reports" className="underline">Reports &amp; Analytics</Link>
      </p>
    </div>
  );
}
