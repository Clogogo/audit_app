import { useEffect, useState } from 'react';
import {
  PieChart, Pie, Cell, Tooltip, ResponsiveContainer,
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Legend,
} from 'recharts';
import { Download, TrendingUp, TrendingDown, Scale, ArrowUpRight, FileText } from 'lucide-react';
import { getSummary, exportReport, exportAuditReport } from '../api/client';
import type { TransactionSummary } from '../api/types';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { AISummaryCard } from '../components/AISummaryCard';
import { useAISummary } from '../hooks';
import { formatCurrency } from '../lib/utils';
import { HelpTooltip } from '../components/HelpTooltip';

const EXPENSE_COLORS = [
  '#dd405a', '#f97316', '#f59e0b', '#eab308',
  '#84cc16', '#14b8a6', '#06b6d4', '#3b82f6',
  '#8b5cf6', '#ec4899', '#6366f1', '#6b7280',
];
const INCOME_COLORS = [
  '#298e5f', '#16a34a', '#0ea5e9', '#6366f1',
  '#f59e0b', '#ec4899', '#14b8a6',
];

const MAX_PIE_SLICES = 8;

/** Keep top N categories; merge the rest into an "Other (n)" slice. */
function groupSmall(
  data: { name: string; value: number }[],
  max: number,
): { name: string; value: number }[] {
  if (data.length <= max) return data;
  const top = data.slice(0, max - 1);
  const rest = data.slice(max - 1);
  const otherTotal = rest.reduce((s, d) => s + d.value, 0);
  return [...top, { name: `Other (${rest.length})`, value: otherTotal }];
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function CategoryList({
  data,
  colors,
  total,
}: {
  data: { name: string; value: number }[];
  colors: string[];
  total: number;
}) {
  return (
    <div className="space-y-2 mt-3">
      {data.map((item, i) => {
        const pct = total > 0 ? (item.value / total) * 100 : 0;
        return (
          <div key={item.name} className="space-y-1">
            <div className="flex items-center justify-between text-xs">
              <div className="flex items-center gap-1.5 min-w-0">
                <span
                  className="h-2.5 w-2.5 rounded-sm shrink-0"
                  style={{ background: colors[i % colors.length] }}
                />
                <span className="truncate text-foreground">{item.name}</span>
              </div>
              <div className="flex items-center gap-2 shrink-0 ml-2">
                <span className="text-muted-foreground">{pct.toFixed(1)}%</span>
                <span className="font-medium tabular-nums">{formatCurrency(item.value)}</span>
              </div>
            </div>
            <div className="h-1 rounded-full bg-muted overflow-hidden">
              <div
                className="h-full rounded-full transition-all"
                style={{ width: `${pct}%`, background: colors[i % colors.length] }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}

/** Shared date-range query params, with empty strings normalized to undefined. */
function dateFilterParams(startDate: string, endDate: string) {
  return { start_date: startDate || undefined, end_date: endDate || undefined };
}

export function Reports() {
  const [summary, setSummary] = useState<TransactionSummary | null>(null);
  const [startDate, setStartDate] = useState('2026-01-01');
  const [endDate, setEndDate] = useState('2026-12-31');
  // Only updated on mount/Apply (not per-keystroke) — the AI summary should
  // refetch on the same cadence as the main summary, not on every keystroke
  // in the date inputs.
  const [appliedRange, setAppliedRange] = useState({ start: startDate, end: endDate });
  const aiSummary = useAISummary(appliedRange.start, appliedRange.end);
  const [loading, setLoading] = useState(true);
  const [auditYear, setAuditYear] = useState(String(new Date().getFullYear()));
  const [auditOpinion, setAuditOpinion] = useState<'unqualified' | 'qualified'>('unqualified');
  const [qualNote, setQualNote] = useState('');
  const [auditLoading, setAuditLoading] = useState(false);
  const AUDIT_YEARS = Array.from({ length: 3 }, (_, i) => String(new Date().getFullYear() - 1 + i));

  const load = () => {
    setLoading(true);
    getSummary(dateFilterParams(startDate, endDate))
      .then(setSummary)
      .finally(() => setLoading(false));
    setAppliedRange({ start: startDate, end: endDate });
  };

  useEffect(() => { load(); }, []);

  const expensePieData = Object.entries(summary?.expense_by_category ?? {})
    .map(([name, value]) => ({ name, value }))
    .sort((a, b) => b.value - a.value);

  const incomePieData = Object.entries(summary?.income_by_category ?? {})
    .map(([name, value]) => ({ name, value }))
    .sort((a, b) => b.value - a.value);

  // Grouped versions used only for the pie chart slices (prevents label/slice clutter)
  const expensePieGrouped = groupSmall(expensePieData, MAX_PIE_SLICES);
  const incomePieGrouped  = groupSmall(incomePieData, MAX_PIE_SLICES);

  const handleExport = async (format: 'csv' | 'pdf') => {
    const blob = await exportReport(format, {
      start_date: startDate || undefined,
      end_date: endDate || undefined,
    });
    downloadBlob(blob, `transactions-report.${format}`);
  };

  const handleAuditReport = async () => {
    setAuditLoading(true);
    try {
      const blob = await exportAuditReport({
        start_date: `${auditYear}-01-01`,
        end_date: `${auditYear}-12-31`,
        opinion: auditOpinion,
        qualification_note: auditOpinion === 'qualified' && qualNote ? qualNote : undefined,
      });
      downloadBlob(blob, `Audit_Report_${auditYear}.pdf`);
    } finally {
      setAuditLoading(false);
    }
  };

  const balance = summary?.balance ?? 0;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <h1 className="text-2xl font-bold">Reports &amp; Analytics</h1>
        <div className="flex items-center gap-2 flex-wrap">
          <div className="flex items-center gap-1.5">
            <Button variant="outline" size="sm" onClick={() => handleExport('csv')}>
              <Download className="h-4 w-4" /> Export CSV
            </Button>
            <HelpTooltip
              content={"Downloads a CSV (comma-separated) file of all transactions in the selected date range.\n\nCSV opens in Excel, Google Sheets, or any accounting software.\n\nIdeal for: bookkeeper handoffs, importing into QuickBooks/Sage, or your own analysis."}
              align="right"
            />
          </div>
          <div className="flex items-center gap-1.5">
            <Button variant="outline" size="sm" onClick={() => handleExport('pdf')}>
              <Download className="h-4 w-4" /> Export PDF
            </Button>
            <HelpTooltip
              content={"Downloads a formatted PDF report showing income, expenses, and balance for the selected period.\n\nIdeal for: board meetings, parent/governor reports, or filing with your accountant."}
              align="right"
            />
          </div>
        </div>
      </div>

      {/* Date filters */}
      <div className="flex items-center gap-3 flex-wrap">
        <Input type="date" className="w-40" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
        <span className="text-muted-foreground text-sm">to</span>
        <Input type="date" className="w-40" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
        <Button size="sm" onClick={load}>Apply</Button>
        {(startDate || endDate) && (
          <Button variant="ghost" size="sm" onClick={() => { setStartDate(''); setEndDate(''); }}>Clear</Button>
        )}
      </div>

      {/* Audit Report panel */}
      <Card className="border-secondary bg-secondary/40">
        <CardHeader className="pb-3">
          <CardTitle className="text-base flex items-center gap-2">
            <FileText className="h-4 w-4 text-primary" />
            Formal Audit Report
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-muted-foreground">
            Generates a full PDF audit report (1 Jan – 31 Dec) — cover page, auditor's opinion,
            Statement of Comprehensive Income, monthly summary, and detailed income &amp; expenditure schedules.
          </p>
          <div className="flex items-center gap-3 flex-wrap">
            <div className="flex flex-col gap-1">
              <span className="text-xs font-medium text-muted-foreground">Financial year</span>
              <Select value={auditYear} onValueChange={setAuditYear}>
                <SelectTrigger className="w-36 h-9">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {AUDIT_YEARS.map((y) => (
                    <SelectItem key={y} value={y}>{y}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="flex flex-col gap-1">
              <span className="text-xs font-medium text-muted-foreground">Opinion type</span>
              <Select value={auditOpinion} onValueChange={(v) => setAuditOpinion(v as 'unqualified' | 'qualified')}>
                <SelectTrigger className="w-52 h-9">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="unqualified">Unqualified (Clean)</SelectItem>
                  <SelectItem value="qualified">Qualified</SelectItem>
                </SelectContent>
              </Select>
            </div>
            {auditOpinion === 'qualified' && (
              <div className="flex flex-col gap-1 flex-1 min-w-[260px]">
                <span className="text-xs font-medium text-muted-foreground">Qualification note</span>
                <Input
                  placeholder="Describe the basis for the qualified opinion…"
                  value={qualNote}
                  onChange={(e) => setQualNote(e.target.value)}
                  className="h-9"
                />
              </div>
            )}
          </div>
          <Button
            size="sm"
            onClick={handleAuditReport}
            disabled={auditLoading}
            className="bg-primary hover:bg-primary/90 text-primary-foreground"
          >
            <FileText className="h-4 w-4" />
            {auditLoading ? 'Generating…' : `Download ${auditYear} Audit Report PDF`}
          </Button>
        </CardContent>
      </Card>

      {loading ? (
        <div className="space-y-6">
          <div className="text-center py-16 text-muted-foreground">Loading...</div>
          {/* AI summary has its own independent fetch (useAISummary above) —
              show it as soon as it's ready instead of waiting on report data. */}
          <AISummaryCard
            narrative={aiSummary.narrative}
            available={aiSummary.available}
            loading={aiSummary.loading}
            compact
          />
        </div>
      ) : (
        <div className="space-y-6">
          {/* ── Stat cards ── */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <Card>
              <CardContent className="py-5 px-5">
                <div className="flex items-start justify-between">
                  <div>
                    <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide flex items-center gap-1.5">
                      Total Income
                      <HelpTooltip
                        content={"Sum of all income transactions in the selected date range.\n\nFiltered by the date range above — leave both dates empty to see all-time totals.\n\nThe pie chart below shows how income is distributed across categories."}
                        align="left"
                      />
                    </p>
                    <p className="text-2xl font-bold text-income mt-1">
                      {formatCurrency(summary?.total_income ?? 0)}
                    </p>
                  </div>
                  <div className="h-9 w-9 rounded-full bg-income/10 flex items-center justify-center">
                    <TrendingUp className="h-5 w-5 text-income" />
                  </div>
                </div>
                <p className="text-xs text-muted-foreground mt-2 flex items-center gap-1">
                  <ArrowUpRight className="h-3 w-3" />
                  {incomePieData.length} categor{incomePieData.length === 1 ? 'y' : 'ies'}
                </p>
              </CardContent>
            </Card>

            <Card>
              <CardContent className="py-5 px-5">
                <div className="flex items-start justify-between">
                  <div>
                    <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide flex items-center gap-1.5">
                      Total Expenses
                      <HelpTooltip
                        content={"Sum of all expense transactions in the selected date range.\n\nThe pie chart below breaks this down by category so you can see your biggest cost areas.\n\nTip: categories with > 30% of total expenses are worth reviewing for savings."}
                        align="center"
                      />
                    </p>
                    <p className="text-2xl font-bold text-expense mt-1">
                      {formatCurrency(summary?.total_expenses ?? 0)}
                    </p>
                  </div>
                  <div className="h-9 w-9 rounded-full bg-expense/10 flex items-center justify-center">
                    <TrendingDown className="h-5 w-5 text-expense" />
                  </div>
                </div>
                <p className="text-xs text-muted-foreground mt-2 flex items-center gap-1">
                  <ArrowUpRight className="h-3 w-3" />
                  {expensePieData.length} categor{expensePieData.length === 1 ? 'y' : 'ies'}
                </p>
              </CardContent>
            </Card>

            {/* Net Balance — destination figure (Income − Expenses), visually distinct */}
            <Card className="bg-primary text-primary-foreground border-0">
              <CardContent className="py-5 px-5">
                <div className="flex items-start justify-between">
                  <div>
                    <p className="text-xs font-medium uppercase tracking-wide flex items-center gap-1.5 text-primary-foreground/70">
                      Net Balance
                      <HelpTooltip
                        className="text-primary-foreground/70 [&_button:hover]:text-primary-foreground [&_button:hover]:bg-white/10"
                        content={"Net Balance = Total Income − Total Expenses (for the selected period)\n\nNote: this is not a bank balance. It reflects your accounting entries, not physical cash in the account."}
                        align="right"
                      />
                    </p>
                    <p className="text-2xl font-bold mt-1 font-display">
                      {formatCurrency(balance)}
                    </p>
                  </div>
                  <div className="h-9 w-9 rounded-full flex items-center justify-center bg-white/15">
                    <Scale className="h-5 w-5" />
                  </div>
                </div>
                <p className="text-xs mt-2 text-primary-foreground/70">
                  {balance >= 0 ? 'Surplus' : 'Deficit'} of {formatCurrency(Math.abs(balance))}
                </p>
              </CardContent>
            </Card>
          </div>

          {/* ── Monthly trend + AI analysis ── */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 items-start">
          <Card className="lg:col-span-2">
            <CardHeader>
              <CardTitle className="text-base flex items-center gap-2">
                Income vs Expenses Over Time
                <HelpTooltip
                  content={"Monthly area chart showing income (green) and expenses (red) side by side.\n\nWhen the green area is above red: surplus month.\nWhen red is above green: deficit month.\n\nUse the date filters above to zoom into a specific period or term."}
                  align="left"
                />
              </CardTitle>
            </CardHeader>
            <CardContent>
              {(summary?.monthly ?? []).length === 0 ? (
                <p className="text-sm text-muted-foreground py-8 text-center">No data</p>
              ) : (
                <ResponsiveContainer width="100%" height={260}>
                  <AreaChart data={summary?.monthly ?? []} margin={{ top: 4, right: 16, left: 0, bottom: 0 }}>
                    <defs>
                      <linearGradient id="colorIncome" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#298e5f" stopOpacity={0.25} />
                        <stop offset="95%" stopColor="#298e5f" stopOpacity={0} />
                      </linearGradient>
                      <linearGradient id="colorExpenses" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#dd405a" stopOpacity={0.25} />
                        <stop offset="95%" stopColor="#dd405a" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" className="stroke-muted/60" />
                    <XAxis dataKey="month" tick={{ fontSize: 11 }} />
                    <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => `₦${(v / 1000).toFixed(0)}k`} width={52} />
                    <Tooltip formatter={(v: number) => formatCurrency(v)} />
                    <Legend />
                    <Area type="monotone" dataKey="income" name="Income" stroke="#298e5f" strokeWidth={2}
                      fill="url(#colorIncome)" dot={false} activeDot={{ r: 4 }} />
                    <Area type="monotone" dataKey="expenses" name="Expenses" stroke="#dd405a" strokeWidth={2}
                      fill="url(#colorExpenses)" dot={false} activeDot={{ r: 4 }} />
                  </AreaChart>
                </ResponsiveContainer>
              )}
            </CardContent>
          </Card>

            {/* AI analysis — right column */}
            <AISummaryCard
              narrative={aiSummary.narrative}
              available={aiSummary.available}
              loading={aiSummary.loading}
              compact
            />
          </div>

          {/* ── Category breakdowns ── */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {/* Expenses */}
            <Card>
              <CardHeader>
                <CardTitle className="text-base flex items-center gap-2">
                  <span className="h-3 w-3 rounded-full bg-expense" />
                  Expense by Category
                </CardTitle>
              </CardHeader>
              <CardContent>
                {expensePieData.length === 0 ? (
                  <p className="text-sm text-muted-foreground py-8 text-center">No expense data</p>
                ) : (
                  <>
                    <div className="outline-none focus-within:outline-none">
                      <ResponsiveContainer width="100%" height={220}>
                        <PieChart>
                          <Pie
                            data={expensePieGrouped}
                            cx="50%" cy="50%"
                            innerRadius={60} outerRadius={95}
                            paddingAngle={2}
                            dataKey="value"
                            label={false}
                            labelLine={false}
                          >
                            {expensePieGrouped.map((_, i) => (
                              <Cell key={i} fill={EXPENSE_COLORS[i % EXPENSE_COLORS.length]} />
                            ))}
                          </Pie>
                          <Tooltip
                            formatter={(v: number, name: string) => [formatCurrency(v), name]}
                            contentStyle={{ borderRadius: '8px', fontSize: '12px' }}
                          />
                        </PieChart>
                      </ResponsiveContainer>
                    </div>
                    {expensePieData.length > MAX_PIE_SLICES && (
                      <p className="text-xs text-muted-foreground text-center -mt-1 mb-2">
                        Chart shows top {MAX_PIE_SLICES - 1} categories — full breakdown below
                      </p>
                    )}
                    <CategoryList
                      data={expensePieData}
                      colors={EXPENSE_COLORS}
                      total={summary?.total_expenses ?? 0}
                    />
                  </>
                )}
              </CardContent>
            </Card>

            {/* Income */}
            <Card>
              <CardHeader>
                <CardTitle className="text-base flex items-center gap-2">
                  <span className="h-3 w-3 rounded-full bg-income" />
                  Income by Category
                </CardTitle>
              </CardHeader>
              <CardContent>
                {incomePieData.length === 0 ? (
                  <p className="text-sm text-muted-foreground py-8 text-center">No income data</p>
                ) : (
                  <>
                    <div className="outline-none focus-within:outline-none">
                      <ResponsiveContainer width="100%" height={220}>
                        <PieChart>
                          <Pie
                            data={incomePieGrouped}
                            cx="50%" cy="50%"
                            innerRadius={60} outerRadius={95}
                            paddingAngle={2}
                            dataKey="value"
                            label={false}
                            labelLine={false}
                          >
                            {incomePieGrouped.map((_, i) => (
                              <Cell key={i} fill={INCOME_COLORS[i % INCOME_COLORS.length]} />
                            ))}
                          </Pie>
                          <Tooltip
                            formatter={(v: number, name: string) => [formatCurrency(v), name]}
                            contentStyle={{ borderRadius: '8px', fontSize: '12px' }}
                          />
                        </PieChart>
                      </ResponsiveContainer>
                    </div>
                    {incomePieData.length > MAX_PIE_SLICES && (
                      <p className="text-xs text-muted-foreground text-center -mt-1 mb-2">
                        Chart shows top {MAX_PIE_SLICES - 1} categories — full breakdown below
                      </p>
                    )}
                    <CategoryList
                      data={incomePieData}
                      colors={INCOME_COLORS}
                      total={summary?.total_income ?? 0}
                    />
                  </>
                )}
              </CardContent>
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}
