import { useEffect, useState, useMemo } from 'react';
import {
  TrendingUp, TrendingDown,
  ArrowUpRight, ArrowDownRight, Users, CalendarClock,
  AlertCircle, Clock, CheckCircle2,
} from 'lucide-react';
import {
  AreaChart, Area, BarChart, Bar,
  XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Cell,
} from 'recharts';
import { getSummary, getTransactions, getTransactionYears, listStaffMembers, getTerms } from '../api/client';
import type { TransactionSummary, Transaction, StaffMember, Term } from '../api/types';
import { TypeBadge } from '../components/CategoryBadge';
import { cn, formatCurrency, formatDate } from '../lib/utils';
import { HelpTooltip } from '../components/HelpTooltip';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select';
import { TermSelect } from '../components/TermSelect';

// ── Tax deadline utilities ────────────────────────────────────────────────────

type TaxType = 'CIT' | 'PAYE' | 'VAT' | 'WHT' | 'Pension' | 'NSITF' | 'ITF' | 'CAC' | 'EDT';

const TAX_BADGE: Record<TaxType, string> = {
  CIT:     'bg-purple-100 text-purple-800',
  PAYE:    'bg-blue-100 text-blue-800',
  VAT:     'bg-indigo-100 text-indigo-800',
  WHT:     'bg-cyan-100 text-cyan-700',
  Pension: 'bg-green-100 text-green-800',
  NSITF:   'bg-teal-100 text-teal-800',
  ITF:     'bg-orange-100 text-orange-800',
  CAC:     'bg-amber-100 text-amber-800',
  EDT:     'bg-pink-100 text-pink-800',
};

interface DeadlineEntry {
  type: TaxType;
  label: string;
  deadline: Date;
  daysLeft: number;
  frequency: 'monthly' | 'annual';
}

function getUpcomingDeadlines(n = 5): DeadlineEntry[] {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const year = today.getFullYear();
  const results: DeadlineEntry[] = [];

  const monthly: Array<{ type: TaxType; day: number; label: string }> = [
    { type: 'PAYE',    day: 10, label: 'PAYE Remittance' },
    { type: 'VAT',     day: 21, label: 'VAT Filing & Remittance' },
    { type: 'WHT',     day: 21, label: 'WHT Remittance' },
    { type: 'Pension', day: 28, label: 'Pension Contribution (PENCOM)' },
    { type: 'NSITF',   day: 28, label: 'NSITF Monthly Levy' },
  ];

  const annual: Array<{ type: TaxType; day: number; month: number; label: string }> = [
    { type: 'ITF', day: 28, month: 2, label: 'ITF Annual Levy' },
    { type: 'CAC', day: 31, month: 3, label: 'CAC Annual Return' },
    { type: 'CIT', day: 30, month: 6, label: 'CIT Self-Assessment Return' },
    { type: 'EDT', day: 30, month: 6, label: 'EDT Education Tax' },
  ];

  // Scan next 3 months of monthly deadlines
  for (let offset = 0; offset <= 2; offset++) {
    const ref = new Date(today);
    ref.setMonth(ref.getMonth() + offset);
    const yr = ref.getFullYear();
    const mo = ref.getMonth() + 1;
    for (const t of monthly) {
      const dl = new Date(yr, mo - 1, t.day);
      if (dl >= today) {
        results.push({ ...t, deadline: dl, daysLeft: Math.ceil((dl.getTime() - today.getTime()) / 86_400_000), frequency: 'monthly' });
      }
    }
  }

  // Annual deadlines — this year or next year if already past
  for (const t of annual) {
    let dl = new Date(year, t.month - 1, t.day);
    if (dl < today) dl = new Date(year + 1, t.month - 1, t.day);
    results.push({ ...t, deadline: dl, daysLeft: Math.ceil((dl.getTime() - today.getTime()) / 86_400_000), frequency: 'annual' });
  }

  return results.sort((a, b) => a.deadline.getTime() - b.deadline.getTime()).slice(0, n);
}

// ── Misc helpers ─────────────────────────────────────────────────────────────

function greeting() {
  const h = new Date().getHours();
  if (h < 12) return 'Good morning';
  if (h < 17) return 'Good afternoon';
  return 'Good evening';
}

function SavingsGauge({ rate }: { rate: number }) {
  const clamped = Math.max(0, Math.min(100, rate));
  const circ = Math.PI * 50;
  const dashOffset = circ * (1 - clamped / 100);
  const stroke     = clamped >= 20 ? '#6366f1' : clamped >= 10 ? '#f59e0b' : '#ef4444';
  const dotClass   = clamped >= 20 ? 'bg-indigo-500' : clamped >= 10 ? 'bg-amber-500' : 'bg-red-500';
  return (
    <div className="flex flex-col items-center">
      <svg viewBox="0 0 120 68" className="w-36 h-20">
        <path d="M 10 60 A 50 50 0 0 1 110 60" fill="none" stroke="#e5e7eb" strokeWidth="10" strokeLinecap="round" />
        <path
          d="M 10 60 A 50 50 0 0 1 110 60"
          fill="none" stroke={stroke} strokeWidth="10" strokeLinecap="round"
          strokeDasharray={`${circ}`} strokeDashoffset={`${dashOffset}`}
          className="savings-gauge-path"
        />
        <text x="60" y="58" textAnchor="middle" fontSize="18" fontWeight="700" fill="currentColor">
          {clamped.toFixed(1)}%
        </text>
      </svg>
      <div className="flex items-center gap-1 text-xs text-muted-foreground mt-1">
        <span className={`h-1.5 w-1.5 rounded-full ${dotClass}`} />
        Savings rate
      </div>
    </div>
  );
}

// Used only for Recharts SVG fill props (must be hex — Tailwind classes won't work there)
const CATEGORY_COLORS = ['#6366f1', '#8b5cf6', '#a78bfa', '#c4b5fd', '#ddd6fe'];
// Tailwind equivalents for DOM elements (dots, progress bars)
const CATEGORY_DOT_CLASSES  = ['bg-indigo-500', 'bg-violet-500', 'bg-violet-400', 'bg-violet-300', 'bg-violet-200'];
const CATEGORY_BAR_CLASSES  = ['bg-indigo-500', 'bg-violet-500', 'bg-violet-400', 'bg-violet-300', 'bg-violet-200'];

function formatAxisNaira(v: number): string {
  if (v >= 1_000_000) {
    const m = v / 1_000_000;
    return `₦${m % 1 === 0 ? m.toFixed(0) : m.toFixed(1)}M`;
  }
  if (v >= 1000) return `₦${Math.round(v / 1000)}k`;
  return `₦${v}`;
}

function buildNiceAxis(maxVal: number): { domainMax: number; ticks: number[] } {
  if (!isFinite(maxVal) || maxVal <= 0) {
    return { domainMax: 1000, ticks: [0, 250, 500, 750, 1000] };
  }
  const rough = maxVal / 5;
  const pow = Math.pow(10, Math.floor(Math.log10(rough)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * pow).find((c) => c >= rough) ?? 10 * pow;
  const domainMax = Math.ceil(maxVal / step) * step;
  const ticks: number[] = [];
  for (let v = 0; v <= domainMax + step / 2; v += step) ticks.push(Math.round(v));
  return { domainMax, ticks };
}

// ── Dashboard ─────────────────────────────────────────────────────────────────

export function Dashboard() {
  const currentYear = new Date().getFullYear();

  const [selectedYear, setSelectedYear] = useState(currentYear);
  const [availableYears, setAvailableYears] = useState<number[]>([currentYear]);
  const [terms, setTerms] = useState<Term[]>([]);
  const [selectedTerm, setSelectedTerm] = useState<Term | null>(null);
  const [summary, setSummary] = useState<TransactionSummary | null>(null);
  const [recent, setRecent] = useState<Transaction[]>([]);
  const [staff, setStaff] = useState<StaffMember[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => { getTerms().then(setTerms); }, []);

  useEffect(() => {
    setLoading(true);
    const start = selectedTerm ? selectedTerm.start_date : `${selectedYear}-01-01`;
    const end   = selectedTerm ? selectedTerm.end_date   : `${selectedYear}-12-31`;
    Promise.all([
      getSummary({ start_date: start, end_date: end }),
      getTransactions({ limit: 6 }),
      listStaffMembers(true),
      getTransactionYears(),
    ])
      .then(([s, tx, staffList, years]) => {
        setSummary(s);
        setRecent(tx.items ?? []);
        setStaff(staffList);
        if (years.length > 0) setAvailableYears(years);
      })
      .finally(() => setLoading(false));
  }, [selectedYear, selectedTerm]);

  const totalIncome   = summary?.total_income   ?? 0;
  const totalExpenses = summary?.total_expenses  ?? 0;
  const balance       = summary?.balance         ?? 0;
  const savingsRate   = totalIncome > 0 ? ((totalIncome - totalExpenses) / totalIncome) * 100 : 0;
  const topExpenses   = Object.entries(summary?.expense_by_category ?? {}).sort((a, b) => b[1] - a[1]).slice(0, 5);

  const monthlyData = summary?.monthly ?? [];
  const monthlyMax  = Math.max(0, ...monthlyData.flatMap((m) => [m.income, m.expenses]));
  const { domainMax: yMax, ticks: yTicks } = buildNiceAxis(monthlyMax);

  // Staff analytics
  const totalMonthlyPayroll = staff.reduce((s, m) => s + m.monthly_gross, 0);
  const avgSalary = staff.length > 0 ? totalMonthlyPayroll / staff.length : 0;
  const roleGroups = useMemo(() => {
    const map: Record<string, number> = {};
    staff.forEach((m) => { const r = m.role || 'Other'; map[r] = (map[r] ?? 0) + 1; });
    return Object.entries(map).sort((a, b) => b[1] - a[1]).slice(0, 4);
  }, [staff]);

  // Tax deadlines
  const upcomingDeadlines = useMemo(() => getUpcomingDeadlines(5), []);

  if (loading) return <div className="flex items-center justify-center h-64 text-muted-foreground">Loading...</div>;

  return (
    <div className="space-y-6">
      {/* Greeting + year selector */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold">{greeting()}!</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Financial overview for{' '}
            <span className="font-medium text-foreground">
              {selectedTerm ? selectedTerm.name : selectedYear}
            </span>
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Select
            value={String(selectedYear)}
            onValueChange={(v) => { setSelectedYear(Number(v)); setSelectedTerm(null); }}
          >
            <SelectTrigger className="w-28">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {availableYears.map((y) => (
                <SelectItem key={y} value={String(y)}>{y}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <TermSelect
            terms={terms}
            selectedTermId={selectedTerm?.id ?? null}
            onSelectTerm={setSelectedTerm}
          />
        </div>
      </div>

      {/* Net balance (featured) + income/expense (compact list) — one composition, not 4 identical cards */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2 rounded-2xl bg-primary text-primary-foreground p-6 flex flex-col justify-between">
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-xs font-semibold uppercase tracking-widest text-primary-foreground/70">
                Net balance · {selectedTerm ? selectedTerm.name : selectedYear}
              </p>
              <p className="font-display text-4xl md:text-5xl font-semibold mt-2 leading-none">
                {formatCurrency(balance)}
              </p>
            </div>
            <HelpTooltip
              className="text-primary-foreground/70 [&_button:hover]:text-primary-foreground [&_button:hover]:bg-white/10"
              content="Net Balance = Total Income − Total Expenses for the selected year.&#10;&#10;Positive = surplus. Negative = spending exceeded income."
              align="right"
            />
          </div>
          <div className="flex items-center gap-2 mt-6">
            <span className="inline-flex items-center gap-1 text-xs font-medium px-2.5 py-1 rounded-full bg-white/15">
              {balance >= 0 ? <ArrowUpRight className="h-3.5 w-3.5" /> : <ArrowDownRight className="h-3.5 w-3.5" />}
              {balance >= 0 ? 'Surplus' : 'Deficit'}
            </span>
            <span
              className={cn(
                'inline-flex items-center gap-1 text-xs font-medium px-2.5 py-1 rounded-full',
                savingsRate >= 20 ? 'bg-white/15' : 'bg-brand-accent text-brand-accent-foreground',
              )}
            >
              Savings rate {savingsRate.toFixed(1)}%
            </span>
          </div>
        </div>

        <div className="rounded-2xl border bg-card divide-y">
          <div className="p-4 flex items-center justify-between gap-3">
            <div className="flex items-center gap-2.5 min-w-0">
              <div className="h-8 w-8 rounded-lg bg-income/10 flex items-center justify-center shrink-0">
                <TrendingUp className="h-4 w-4 text-income" />
              </div>
              <div className="min-w-0">
                <p className="text-xs text-muted-foreground">Total income</p>
                <p className="text-lg font-semibold text-income truncate">{formatCurrency(totalIncome)}</p>
              </div>
            </div>
            <HelpTooltip content="Sum of all income transactions in the selected year." align="right" />
          </div>
          <div className="p-4 flex items-center justify-between gap-3">
            <div className="flex items-center gap-2.5 min-w-0">
              <div className="h-8 w-8 rounded-lg bg-expense/10 flex items-center justify-center shrink-0">
                <TrendingDown className="h-4 w-4 text-expense" />
              </div>
              <div className="min-w-0">
                <p className="text-xs text-muted-foreground">Total expenses</p>
                <p className="text-lg font-semibold text-expense truncate">{formatCurrency(totalExpenses)}</p>
              </div>
            </div>
            <HelpTooltip content="Sum of all expense transactions in the selected year." align="right" />
          </div>
        </div>
      </div>

      {/* Main 3-col layout */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Chart 2/3 */}
        <div className="lg:col-span-2 rounded-2xl border bg-card overflow-hidden">
          {/* Header strip */}
          <div className="px-6 pt-6 pb-4 flex items-start justify-between">
            <div>
              <p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">Monthly Overview</p>
              <h2 className="text-xl font-bold mt-0.5">{selectedYear}</h2>
            </div>
            <div className="flex items-center gap-5 mt-1">
              <div className="flex items-center gap-2">
                <span className="h-2.5 w-2.5 rounded-full bg-emerald-500" />
                <span className="text-xs font-medium text-muted-foreground">Income</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="h-2.5 w-2.5 rounded-full bg-rose-400" />
                <span className="text-xs font-medium text-muted-foreground">Expenses</span>
              </div>
            </div>
          </div>

          {/* KPI row */}
          <div className="grid grid-cols-3 gap-px bg-border mx-6 mb-5 rounded-xl overflow-hidden">
            <div className="bg-card px-4 py-3">
              <p className="text-xs text-muted-foreground">Total Income</p>
              <p className="text-base font-bold text-emerald-600 mt-0.5">{formatCurrency(totalIncome)}</p>
            </div>
            <div className="bg-card px-4 py-3 border-x border-border">
              <p className="text-xs text-muted-foreground">Total Expenses</p>
              <p className="text-base font-bold text-rose-500 mt-0.5">{formatCurrency(totalExpenses)}</p>
            </div>
            <div className="bg-card px-4 py-3">
              <p className="text-xs text-muted-foreground">Net</p>
              <p className={`text-base font-bold mt-0.5 ${balance >= 0 ? 'text-indigo-600' : 'text-red-500'}`}>
                {balance >= 0 ? '+' : ''}{formatCurrency(balance)}
              </p>
            </div>
          </div>

          {/* Area chart */}
          {monthlyData.length === 0 ? (
            <div className="flex items-center justify-center h-48 text-sm text-muted-foreground pb-6">
              No data for {selectedYear}
            </div>
          ) : (
            <div className="px-2 pb-4">
              <ResponsiveContainer width="100%" height={230}>
                <AreaChart data={monthlyData} margin={{ top: 4, right: 16, left: 0, bottom: 0 }}>
                  <defs>
                    <linearGradient id="gradIncome" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%"  stopColor="#10b981" stopOpacity={0.25} />
                      <stop offset="95%" stopColor="#10b981" stopOpacity={0} />
                    </linearGradient>
                    <linearGradient id="gradExpenses" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%"  stopColor="#fb7185" stopOpacity={0.2} />
                      <stop offset="95%" stopColor="#fb7185" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="hsl(var(--border))" />
                  <XAxis
                    dataKey="month" tick={{ fontSize: 11, fill: 'hsl(var(--muted-foreground))' }}
                    axisLine={false} tickLine={false}
                  />
                  <YAxis
                    tick={{ fontSize: 11, fill: 'hsl(var(--muted-foreground))' }}
                    axisLine={false} tickLine={false}
                    domain={[0, yMax]} ticks={yTicks}
                    tickFormatter={formatAxisNaira} width={54}
                  />
                  <Tooltip
                    formatter={(v: number, name: string) => [formatCurrency(v), name]}
                    contentStyle={{
                      borderRadius: '14px',
                      fontSize: '12px',
                      border: '1px solid hsl(var(--border))',
                      boxShadow: '0 4px 24px rgba(0,0,0,0.08)',
                      padding: '10px 14px',
                    }}
                    cursor={{ stroke: 'hsl(var(--border))', strokeWidth: 1 }}
                  />
                  <Area
                    type="monotone" dataKey="income" name="Income"
                    stroke="#10b981" strokeWidth={2.5}
                    fill="url(#gradIncome)" dot={false} activeDot={{ r: 5, strokeWidth: 0 }}
                  />
                  <Area
                    type="monotone" dataKey="expenses" name="Expenses"
                    stroke="#fb7185" strokeWidth={2.5}
                    fill="url(#gradExpenses)" dot={false} activeDot={{ r: 5, strokeWidth: 0 }}
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>

        {/* Sidebar 1/3 */}
        <div className="flex flex-col gap-4">
          {/* Savings gauge */}
          <div className="rounded-2xl border bg-card p-5">
            <div className="flex items-center gap-1.5">
              <h3 className="text-sm font-semibold">Savings Rate</h3>
              <HelpTooltip
                content={"(Income − Expenses) ÷ Income × 100\n\n· Purple (≥ 20%): healthy buffer\n· Amber (10–19%): review spending\n· Red (< 10%): dangerously thin margin"}
                align="left"
              />
            </div>
            <p className="text-xs text-muted-foreground mt-0.5">
              {savingsRate >= 20 ? 'Great job! Keep it up.' : savingsRate >= 0 ? 'Try to save more.' : 'Spending exceeds income.'}
            </p>
            <div className="flex items-center justify-center py-3">
              <SavingsGauge rate={savingsRate} />
            </div>
            <div className="rounded-xl bg-indigo-50 dark:bg-indigo-950/20 p-3 text-center">
              <p className="text-xs text-indigo-600 font-medium">Amount saved</p>
              <p className="text-lg font-bold text-indigo-700 mt-0.5">{formatCurrency(Math.max(0, balance))}</p>
            </div>
          </div>

          {/* Top spending */}
          <div className="rounded-2xl border bg-card p-5 flex-1">
            <h3 className="text-sm font-semibold mb-3">Top Spending</h3>
            {topExpenses.length === 0 ? (
              <p className="text-xs text-muted-foreground py-4 text-center">No expense data</p>
            ) : (
              <>
                <div className="space-y-3">
                  {topExpenses.map(([name, value], i) => {
                    const pct = totalExpenses > 0 ? (value / totalExpenses) * 100 : 0;
                    const idx = i % CATEGORY_DOT_CLASSES.length;
                    return (
                      <div key={name}>
                        <div className="flex items-center justify-between text-xs mb-1">
                          <div className="flex items-center gap-1.5 min-w-0">
                            <span className={`h-2 w-2 rounded-full shrink-0 ${CATEGORY_DOT_CLASSES[idx]}`} />
                            <span className="truncate">{name}</span>
                          </div>
                          <span className="text-muted-foreground shrink-0 ml-2">{pct.toFixed(0)}%</span>
                        </div>
                        <div className="h-1.5 rounded-full bg-muted overflow-hidden">
                          <div
                            className={`h-full rounded-full chart-bar-fill ${CATEGORY_BAR_CLASSES[idx]}`}
                            style={{ '--bar-w': `${pct}%` } as React.CSSProperties}
                          />
                        </div>
                      </div>
                    );
                  })}
                </div>
                <div className="mt-4 pt-4 border-t">
                  <ResponsiveContainer width="100%" height={90}>
                    <BarChart
                      data={topExpenses.map(([name, value]) => ({ name: name.split(' ')[0], value }))}
                      layout="vertical" margin={{ left: 0, right: 6, top: 0, bottom: 0 }}
                    >
                      <XAxis type="number" hide />
                      <YAxis type="category" dataKey="name" tick={{ fontSize: 9 }} width={48} axisLine={false} tickLine={false} />
                      <Tooltip formatter={(v: number) => formatCurrency(v)} contentStyle={{ fontSize: '11px', borderRadius: '8px' }} />
                      <Bar dataKey="value" radius={[0, 4, 4, 0]} maxBarSize={9}>
                        {topExpenses.map((_, i) => <Cell key={i} fill={CATEGORY_COLORS[i % CATEGORY_COLORS.length]} />)}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </>
            )}
          </div>
        </div>
      </div>

      {/* Staff + Tax deadlines row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

        {/* Staff snapshot */}
        <div className="rounded-2xl border bg-card p-6">
          <div className="flex items-center gap-2 mb-4">
            <div className="h-8 w-8 rounded-lg bg-blue-100 dark:bg-blue-950/40 flex items-center justify-center">
              <Users className="h-4 w-4 text-blue-600" />
            </div>
            <div>
              <h2 className="text-base font-semibold">Staff Snapshot</h2>
              <p className="text-xs text-muted-foreground">Active staff members</p>
            </div>
          </div>

          {staff.length === 0 ? (
            <p className="text-sm text-muted-foreground py-6 text-center">No active staff found</p>
          ) : (
            <>
              {/* Key metrics */}
              <div className="grid grid-cols-3 gap-3 mb-4">
                <div className="rounded-xl bg-blue-50 dark:bg-blue-950/20 p-3 text-center">
                  <p className="text-2xl font-bold text-blue-700">{staff.length}</p>
                  <p className="text-xs text-blue-600 mt-0.5">Total staff</p>
                </div>
                <div className="rounded-xl bg-green-50 dark:bg-green-950/20 p-3 text-center">
                  <p className="text-sm font-bold text-green-700">{formatCurrency(totalMonthlyPayroll)}</p>
                  <p className="text-xs text-green-600 mt-0.5">Monthly payroll</p>
                </div>
                <div className="rounded-xl bg-violet-50 dark:bg-violet-950/20 p-3 text-center">
                  <p className="text-sm font-bold text-violet-700">{formatCurrency(avgSalary)}</p>
                  <p className="text-xs text-violet-600 mt-0.5">Avg. salary</p>
                </div>
              </div>

              {/* Role breakdown */}
              {roleGroups.length > 0 && (
                <div>
                  <p className="text-xs font-medium text-muted-foreground mb-2 uppercase tracking-wide">By role</p>
                  <div className="space-y-2">
                    {roleGroups.map(([role, count]) => {
                      const pct = (count / staff.length) * 100;
                      return (
                        <div key={role}>
                          <div className="flex items-center justify-between text-xs mb-1">
                            <span className="truncate font-medium">{role}</span>
                            <span className="text-muted-foreground ml-2 shrink-0">{count} staff</span>
                          </div>
                          <div className="h-1.5 rounded-full bg-muted overflow-hidden">
                            <div
                              className="h-full rounded-full bg-blue-400 role-bar-fill"
                              style={{ '--bar-w': `${pct}%` } as React.CSSProperties}
                            />
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* Annual payroll estimate */}
              <div className="mt-4 pt-4 border-t flex items-center justify-between text-xs">
                <span className="text-muted-foreground">Estimated annual payroll</span>
                <span className="font-semibold text-foreground">{formatCurrency(totalMonthlyPayroll * 12)}</span>
              </div>
            </>
          )}
        </div>

        {/* Upcoming tax deadlines */}
        <div className="rounded-2xl border bg-card p-6">
          <div className="flex items-center gap-2 mb-4">
            <div className="h-8 w-8 rounded-lg bg-amber-100 dark:bg-amber-950/40 flex items-center justify-center">
              <CalendarClock className="h-4 w-4 text-amber-600" />
            </div>
            <div>
              <h2 className="text-base font-semibold">Upcoming Tax Deadlines</h2>
              <p className="text-xs text-muted-foreground">Nigerian statutory obligations</p>
            </div>
          </div>

          <div className="space-y-3">
            {upcomingDeadlines.map((d, i) => {
              const isToday   = d.daysLeft === 0;
              const isOverdue = d.daysLeft < 0;
              const isDueSoon = d.daysLeft > 0 && d.daysLeft <= 7;

              const StatusIcon = isOverdue
                ? AlertCircle
                : isToday
                  ? AlertCircle
                  : isDueSoon
                    ? Clock
                    : CheckCircle2;

              const statusColor = isOverdue || isToday
                ? 'text-red-500'
                : isDueSoon
                  ? 'text-amber-500'
                  : 'text-green-500';

              const statusText = isOverdue
                ? `${Math.abs(d.daysLeft)}d overdue`
                : isToday
                  ? 'Due today'
                  : `${d.daysLeft}d left`;

              return (
                <div key={i} className="flex items-center justify-between gap-3 p-3 rounded-xl bg-muted/40 hover:bg-muted/60 transition-colors">
                  <div className="flex items-center gap-2.5 min-w-0">
                    <span className={`text-xs font-semibold px-2 py-0.5 rounded-full shrink-0 ${TAX_BADGE[d.type]}`}>
                      {d.type}
                    </span>
                    <div className="min-w-0">
                      <p className="text-xs font-medium truncate">{d.label}</p>
                      <p className="text-xs text-muted-foreground">
                        {d.deadline.toLocaleDateString('en-NG', { day: 'numeric', month: 'short', year: 'numeric' })}
                        {d.frequency === 'annual' && <span className="ml-1 text-muted-foreground/70">· annual</span>}
                      </p>
                    </div>
                  </div>
                  <div className={`flex items-center gap-1 text-xs font-medium shrink-0 ${statusColor}`}>
                    <StatusIcon className="h-3.5 w-3.5" />
                    {statusText}
                  </div>
                </div>
              );
            })}
          </div>

          <div className="mt-4 pt-3 border-t">
            <a href="/tax/calendar" className="text-xs text-indigo-600 hover:underline font-medium">
              View full tax calendar →
            </a>
          </div>
        </div>
      </div>

      {/* Recent transactions */}
      <div className="rounded-2xl border bg-card p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-base font-semibold">Recent Transactions</h2>
          <a href="/transactions" className="text-xs text-indigo-600 hover:underline font-medium">View all →</a>
        </div>

        {recent.length === 0 ? (
          <p className="text-sm text-muted-foreground py-8 text-center">No transactions yet</p>
        ) : (
          <div className="divide-y">
            {recent.map((tx) => (
              <div key={tx.id} className="flex items-center justify-between py-3">
                <div className="flex items-center gap-3 min-w-0">
                  <div className={`h-9 w-9 rounded-full shrink-0 flex items-center justify-center font-bold text-sm
                    ${tx.type === 'income' ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-600'}`}>
                    {tx.type === 'income' ? '↑' : '↓'}
                  </div>
                  <div className="min-w-0">
                    <p className="text-sm font-medium truncate">{tx.description}</p>
                    <div className="flex items-center gap-2 mt-0.5">
                      <TypeBadge type={tx.type} />
                      <span className="text-xs text-muted-foreground">
                        {tx.vendor ? `${tx.vendor} · ` : ''}{formatDate(tx.date)}
                      </span>
                    </div>
                  </div>
                </div>
                <div className="text-right shrink-0 ml-4">
                  <p className={`text-sm font-semibold ${tx.type === 'income' ? 'text-green-600' : 'text-red-600'}`}>
                    {tx.type === 'income' ? '+' : '-'}{formatCurrency(tx.amount, tx.currency ?? 'NGN')}
                  </p>
                  <p className="text-xs text-muted-foreground mt-0.5">{tx.category}</p>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
