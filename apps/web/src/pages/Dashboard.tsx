import { useEffect, useState } from 'react';
import {
  TrendingUp, TrendingDown, Scale, Wallet,
  ArrowUpRight, ArrowDownRight, MoreHorizontal,
} from 'lucide-react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Cell,
} from 'recharts';
import { getSummary, getTransactions } from '../api/client';
import type { TransactionSummary, Transaction } from '../api/types';
import { TypeBadge } from '../components/CategoryBadge';
import { formatCurrency, formatDate } from '../lib/utils';

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
  const color = clamped >= 20 ? '#6366f1' : clamped >= 10 ? '#f59e0b' : '#ef4444';
  return (
    <div className="flex flex-col items-center">
      <svg viewBox="0 0 120 68" className="w-36 h-20">
        <path d="M 10 60 A 50 50 0 0 1 110 60" fill="none" stroke="#e5e7eb" strokeWidth="10" strokeLinecap="round" />
        <path
          d="M 10 60 A 50 50 0 0 1 110 60"
          fill="none" stroke={color} strokeWidth="10" strokeLinecap="round"
          strokeDasharray={`${circ}`} strokeDashoffset={`${dashOffset}`}
          style={{ transition: 'stroke-dashoffset 0.6s ease' }}
        />
        <text x="60" y="58" textAnchor="middle" fontSize="18" fontWeight="700" fill="currentColor">
          {clamped.toFixed(1)}%
        </text>
      </svg>
      <div className="flex items-center gap-1 text-xs text-muted-foreground mt-1">
        <span className="h-1.5 w-1.5 rounded-full" style={{ background: color }} />
        Savings rate
      </div>
    </div>
  );
}

const CATEGORY_COLORS = ['#6366f1', '#8b5cf6', '#a78bfa', '#c4b5fd', '#ddd6fe'];

export function Dashboard() {
  const [summary, setSummary] = useState<TransactionSummary | null>(null);
  const [recent, setRecent] = useState<Transaction[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([getSummary(), getTransactions()])
      .then(([s, tx]) => { setSummary(s); setRecent(tx.slice(0, 6)); })
      .finally(() => setLoading(false));
  }, []);

  const totalIncome = summary?.total_income ?? 0;
  const totalExpenses = summary?.total_expenses ?? 0;
  const balance = summary?.balance ?? 0;
  const savingsRate = totalIncome > 0 ? ((totalIncome - totalExpenses) / totalIncome) * 100 : 0;
  const topExpenses = Object.entries(summary?.expense_by_category ?? {})
    .sort((a, b) => b[1] - a[1]).slice(0, 5);

  if (loading) return <div className="flex items-center justify-center h-64 text-muted-foreground">Loading...</div>;

  const statCards = [
    {
      label: 'Net balance',
      value: formatCurrency(balance),
      sub: balance >= 0 ? 'Surplus' : 'Deficit',
      up: balance >= 0,
      bg: 'bg-indigo-100 dark:bg-indigo-950/40',
      icon: <Wallet className="h-5 w-5 text-indigo-600" />,
      textColor: balance >= 0 ? 'text-indigo-600' : 'text-red-600',
    },
    {
      label: 'Total income',
      value: formatCurrency(totalIncome),
      sub: `${Object.keys(summary?.income_by_category ?? {}).length} categories`,
      up: true,
      bg: 'bg-green-100 dark:bg-green-950/40',
      icon: <TrendingUp className="h-5 w-5 text-green-600" />,
      textColor: 'text-green-600',
    },
    {
      label: 'Total expenses',
      value: formatCurrency(totalExpenses),
      sub: `${Object.keys(summary?.expense_by_category ?? {}).length} categories`,
      up: false,
      bg: 'bg-red-100 dark:bg-red-950/40',
      icon: <TrendingDown className="h-5 w-5 text-red-500" />,
      textColor: 'text-red-500',
    },
    {
      label: 'Savings rate',
      value: `${savingsRate.toFixed(1)}%`,
      sub: savingsRate >= 20 ? 'On track' : savingsRate >= 0 ? 'Below target' : 'Overspent',
      up: savingsRate >= 0,
      bg: 'bg-violet-100 dark:bg-violet-950/40',
      icon: <Scale className="h-5 w-5 text-violet-600" />,
      textColor: 'text-violet-600',
    },
  ];

  return (
    <div className="space-y-6">
      {/* Greeting */}
      <div>
        <h1 className="text-2xl font-bold">{greeting()}!</h1>
        <p className="text-sm text-muted-foreground mt-0.5">
          Here&apos;s your financial overview for{' '}
          {new Date().toLocaleDateString('en-US', { month: 'long', year: 'numeric' })}
        </p>
      </div>

      {/* 4 Stat cards */}
      <div className="grid grid-cols-4 gap-4">
        {statCards.map((card) => (
          <div key={card.label} className="rounded-2xl border bg-card p-5 flex flex-col gap-3">
            <div className="flex items-center justify-between">
              <div className={`h-10 w-10 rounded-xl ${card.bg} flex items-center justify-center`}>
                {card.icon}
              </div>
              <button className="text-muted-foreground hover:text-foreground" type="button" title={`More options for ${card.label}`}>
                <MoreHorizontal className="h-4 w-4" />
              </button>
            </div>
            <div>
              <p className={`text-2xl font-bold ${card.textColor}`}>{card.value}</p>
              <p className="text-xs text-muted-foreground mt-0.5">{card.label}</p>
            </div>
            <div className={`flex items-center gap-1 text-xs font-medium ${card.textColor}`}>
              {card.up ? <ArrowUpRight className="h-3.5 w-3.5" /> : <ArrowDownRight className="h-3.5 w-3.5" />}
              {card.sub}
            </div>
          </div>
        ))}
      </div>

      {/* Main 3-col layout */}
      <div className="grid grid-cols-3 gap-6">
        {/* Chart 2/3 */}
        <div className="col-span-2 rounded-2xl border bg-card p-6">
          <div className="flex items-start justify-between mb-5">
            <div>
              <h2 className="text-base font-semibold">Monthly Overview</h2>
              <p className="text-xs text-muted-foreground mt-0.5">Income vs expenses by month</p>
            </div>
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-1.5">
                <span className="h-2.5 w-2.5 rounded-sm bg-green-500" />
                <span className="text-xs text-muted-foreground">Income</span>
              </div>
              <div className="flex items-center gap-1.5">
                <span className="h-2.5 w-2.5 rounded-sm bg-red-400" />
                <span className="text-xs text-muted-foreground">Expenses</span>
              </div>
            </div>
          </div>

          {/* Summary row */}
          <div className="grid grid-cols-2 gap-3 mb-5">
            <div className="rounded-xl bg-green-50 dark:bg-green-950/20 p-4">
              <p className="text-xs text-green-700 font-medium uppercase tracking-wide">Income</p>
              <p className="text-xl font-bold text-green-700 mt-1">{formatCurrency(totalIncome)}</p>
              <div className="flex items-center gap-1 mt-1">
                <ArrowUpRight className="h-3 w-3 text-green-600" />
                <span className="text-xs text-green-600">
                  {Object.keys(summary?.income_by_category ?? {}).length} sources
                </span>
              </div>
            </div>
            <div className="rounded-xl bg-red-50 dark:bg-red-950/20 p-4">
              <p className="text-xs text-red-700 font-medium uppercase tracking-wide">Expenses</p>
              <p className="text-xl font-bold text-red-700 mt-1">{formatCurrency(totalExpenses)}</p>
              <div className="flex items-center gap-1 mt-1">
                <ArrowDownRight className="h-3 w-3 text-red-500" />
                <span className="text-xs text-red-500">
                  {Object.keys(summary?.expense_by_category ?? {}).length} categories
                </span>
              </div>
            </div>
          </div>

          {(summary?.monthly ?? []).length === 0 ? (
            <div className="flex items-center justify-center h-40 text-sm text-muted-foreground">No data yet</div>
          ) : (
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={summary?.monthly ?? []} barGap={4} barCategoryGap="30%">
                <CartesianGrid strokeDasharray="3 3" vertical={false} className="stroke-muted/60" />
                <XAxis dataKey="month" tick={{ fontSize: 11 }} axisLine={false} tickLine={false} />
                <YAxis
                  tick={{ fontSize: 11 }} axisLine={false} tickLine={false}
                  tickFormatter={(v) => `₦${(v / 1000).toFixed(0)}k`} width={46}
                />
                <Tooltip
                  formatter={(v: number) => formatCurrency(v)}
                  contentStyle={{ borderRadius: '12px', fontSize: '12px', border: '1px solid hsl(var(--border))' }}
                  cursor={{ fill: 'hsl(var(--muted))', radius: 6 }}
                />
                <Bar dataKey="income" name="Income" fill="#22c55e" radius={[6, 6, 0, 0]} maxBarSize={26} />
                <Bar dataKey="expenses" name="Expenses" fill="#f87171" radius={[6, 6, 0, 0]} maxBarSize={26} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>

        {/* Sidebar 1/3 */}
        <div className="flex flex-col gap-4">
          {/* Savings gauge */}
          <div className="rounded-2xl border bg-card p-5">
            <h3 className="text-sm font-semibold">Savings Rate</h3>
            <p className="text-xs text-muted-foreground mt-0.5">
              {savingsRate >= 20
                ? 'Great job! Keep it up.'
                : savingsRate >= 0
                  ? 'Try to save more.'
                  : 'Spending exceeds income.'}
            </p>
            <div className="flex items-center justify-center py-3">
              <SavingsGauge rate={savingsRate} />
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div className="rounded-xl bg-muted/50 p-3 text-center">
                <p className="text-xs text-muted-foreground">Saved</p>
                <p className="text-sm font-bold text-indigo-600 mt-0.5">{formatCurrency(Math.max(0, balance))}</p>
              </div>
              <div className="rounded-xl bg-muted/50 p-3 text-center">
                <p className="text-xs text-muted-foreground">Spent</p>
                <p className="text-sm font-bold text-red-500 mt-0.5">{formatCurrency(totalExpenses)}</p>
              </div>
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
                    return (
                      <div key={name}>
                        <div className="flex items-center justify-between text-xs mb-1">
                          <div className="flex items-center gap-1.5 min-w-0">
                            <span
                              className="h-2 w-2 rounded-full shrink-0"
                              style={{ background: CATEGORY_COLORS[i % CATEGORY_COLORS.length] }}
                            />
                            <span className="truncate">{name}</span>
                          </div>
                          <span className="text-muted-foreground shrink-0 ml-2">{pct.toFixed(0)}%</span>
                        </div>
                        <div className="h-1.5 rounded-full bg-muted overflow-hidden">
                          <div
                            className="h-full rounded-full"
                            style={{ width: `${pct}%`, background: CATEGORY_COLORS[i % CATEGORY_COLORS.length] }}
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
                      <YAxis
                        type="category" dataKey="name"
                        tick={{ fontSize: 9 }} width={48} axisLine={false} tickLine={false}
                      />
                      <Tooltip
                        formatter={(v: number) => formatCurrency(v)}
                        contentStyle={{ fontSize: '11px', borderRadius: '8px' }}
                      />
                      <Bar dataKey="value" radius={[0, 4, 4, 0]} maxBarSize={9}>
                        {topExpenses.map((_, i) => (
                          <Cell key={i} fill={CATEGORY_COLORS[i % CATEGORY_COLORS.length]} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </>
            )}
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
