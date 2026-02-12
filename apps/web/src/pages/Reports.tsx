import { useEffect, useState } from 'react';
import {
  PieChart, Pie, Cell, Tooltip, ResponsiveContainer,
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Legend,
} from 'recharts';
import { Download, TrendingUp, TrendingDown, Scale, ArrowUpRight } from 'lucide-react';
import { getSummary, exportReport } from '../api/client';
import type { TransactionSummary } from '../api/types';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { formatCurrency } from '../lib/utils';

const EXPENSE_COLORS = [
  '#ef4444', '#f97316', '#f59e0b', '#eab308',
  '#84cc16', '#14b8a6', '#06b6d4', '#3b82f6',
  '#8b5cf6', '#ec4899', '#6366f1', '#6b7280',
];
const INCOME_COLORS = [
  '#22c55e', '#16a34a', '#0ea5e9', '#6366f1',
  '#f59e0b', '#ec4899', '#14b8a6',
];

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

export function Reports() {
  const [summary, setSummary] = useState<TransactionSummary | null>(null);
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [loading, setLoading] = useState(true);

  const load = () => {
    setLoading(true);
    getSummary({ start_date: startDate || undefined, end_date: endDate || undefined })
      .then(setSummary)
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  const expensePieData = Object.entries(summary?.expense_by_category ?? {})
    .map(([name, value]) => ({ name, value }))
    .sort((a, b) => b.value - a.value);

  const incomePieData = Object.entries(summary?.income_by_category ?? {})
    .map(([name, value]) => ({ name, value }))
    .sort((a, b) => b.value - a.value);

  const handleExport = async (format: 'csv' | 'pdf') => {
    const blob = await exportReport(format, {
      start_date: startDate || undefined,
      end_date: endDate || undefined,
    });
    downloadBlob(blob, `transactions-report.${format}`);
  };

  const balance = summary?.balance ?? 0;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Reports &amp; Analytics</h1>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => handleExport('csv')}>
            <Download className="h-4 w-4" /> Export CSV
          </Button>
          <Button variant="outline" size="sm" onClick={() => handleExport('pdf')}>
            <Download className="h-4 w-4" /> Export PDF
          </Button>
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

      {loading ? (
        <div className="text-center py-16 text-muted-foreground">Loading...</div>
      ) : (
        <div className="space-y-6">
          {/* ── Stat cards ── */}
          <div className="grid grid-cols-3 gap-4">
            <Card className="border-green-200 bg-green-50/50 dark:bg-green-950/20">
              <CardContent className="py-5 px-5">
                <div className="flex items-start justify-between">
                  <div>
                    <p className="text-xs font-medium text-green-700 uppercase tracking-wide">Total Income</p>
                    <p className="text-2xl font-bold text-green-700 mt-1">
                      {formatCurrency(summary?.total_income ?? 0)}
                    </p>
                  </div>
                  <div className="h-9 w-9 rounded-full bg-green-100 flex items-center justify-center">
                    <TrendingUp className="h-5 w-5 text-green-600" />
                  </div>
                </div>
                <p className="text-xs text-green-600 mt-2 flex items-center gap-1">
                  <ArrowUpRight className="h-3 w-3" />
                  {incomePieData.length} categor{incomePieData.length === 1 ? 'y' : 'ies'}
                </p>
              </CardContent>
            </Card>

            <Card className="border-red-200 bg-red-50/50 dark:bg-red-950/20">
              <CardContent className="py-5 px-5">
                <div className="flex items-start justify-between">
                  <div>
                    <p className="text-xs font-medium text-red-700 uppercase tracking-wide">Total Expenses</p>
                    <p className="text-2xl font-bold text-red-700 mt-1">
                      {formatCurrency(summary?.total_expenses ?? 0)}
                    </p>
                  </div>
                  <div className="h-9 w-9 rounded-full bg-red-100 flex items-center justify-center">
                    <TrendingDown className="h-5 w-5 text-red-600" />
                  </div>
                </div>
                <p className="text-xs text-red-600 mt-2 flex items-center gap-1">
                  <ArrowUpRight className="h-3 w-3" />
                  {expensePieData.length} categor{expensePieData.length === 1 ? 'y' : 'ies'}
                </p>
              </CardContent>
            </Card>

            <Card className={balance >= 0
              ? 'border-blue-200 bg-blue-50/50 dark:bg-blue-950/20'
              : 'border-orange-200 bg-orange-50/50 dark:bg-orange-950/20'}>
              <CardContent className="py-5 px-5">
                <div className="flex items-start justify-between">
                  <div>
                    <p className={`text-xs font-medium uppercase tracking-wide ${balance >= 0 ? 'text-blue-700' : 'text-orange-700'}`}>
                      Net Balance
                    </p>
                    <p className={`text-2xl font-bold mt-1 ${balance >= 0 ? 'text-blue-700' : 'text-orange-700'}`}>
                      {formatCurrency(balance)}
                    </p>
                  </div>
                  <div className={`h-9 w-9 rounded-full flex items-center justify-center ${balance >= 0 ? 'bg-blue-100' : 'bg-orange-100'}`}>
                    <Scale className={`h-5 w-5 ${balance >= 0 ? 'text-blue-600' : 'text-orange-600'}`} />
                  </div>
                </div>
                <p className={`text-xs mt-2 ${balance >= 0 ? 'text-blue-600' : 'text-orange-600'}`}>
                  {balance >= 0 ? 'Surplus' : 'Deficit'} of {formatCurrency(Math.abs(balance))}
                </p>
              </CardContent>
            </Card>
          </div>

          {/* ── Monthly trend ── */}
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Income vs Expenses Over Time</CardTitle>
            </CardHeader>
            <CardContent>
              {(summary?.monthly ?? []).length === 0 ? (
                <p className="text-sm text-muted-foreground py-8 text-center">No data</p>
              ) : (
                <ResponsiveContainer width="100%" height={260}>
                  <AreaChart data={summary?.monthly ?? []} margin={{ top: 4, right: 16, left: 0, bottom: 0 }}>
                    <defs>
                      <linearGradient id="colorIncome" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#22c55e" stopOpacity={0.25} />
                        <stop offset="95%" stopColor="#22c55e" stopOpacity={0} />
                      </linearGradient>
                      <linearGradient id="colorExpenses" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#ef4444" stopOpacity={0.25} />
                        <stop offset="95%" stopColor="#ef4444" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" className="stroke-muted/60" />
                    <XAxis dataKey="month" tick={{ fontSize: 11 }} />
                    <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => `₦${(v / 1000).toFixed(0)}k`} width={52} />
                    <Tooltip formatter={(v: number) => formatCurrency(v)} />
                    <Legend />
                    <Area type="monotone" dataKey="income" name="Income" stroke="#22c55e" strokeWidth={2}
                      fill="url(#colorIncome)" dot={false} activeDot={{ r: 4 }} />
                    <Area type="monotone" dataKey="expenses" name="Expenses" stroke="#ef4444" strokeWidth={2}
                      fill="url(#colorExpenses)" dot={false} activeDot={{ r: 4 }} />
                  </AreaChart>
                </ResponsiveContainer>
              )}
            </CardContent>
          </Card>

          {/* ── Category breakdowns ── */}
          <div className="grid grid-cols-2 gap-6">
            {/* Expenses */}
            <Card>
              <CardHeader>
                <CardTitle className="text-base flex items-center gap-2">
                  <span className="h-3 w-3 rounded-full bg-red-500" />
                  Spending by Category
                </CardTitle>
              </CardHeader>
              <CardContent>
                {expensePieData.length === 0 ? (
                  <p className="text-sm text-muted-foreground py-8 text-center">No expense data</p>
                ) : (
                  <>
                    <ResponsiveContainer width="100%" height={200}>
                      <PieChart>
                        <Pie data={expensePieData} cx="50%" cy="50%"
                          innerRadius={55} outerRadius={85} paddingAngle={2} dataKey="value">
                          {expensePieData.map((_, i) => (
                            <Cell key={i} fill={EXPENSE_COLORS[i % EXPENSE_COLORS.length]} />
                          ))}
                        </Pie>
                        <Tooltip formatter={(v: number) => formatCurrency(v)} />
                      </PieChart>
                    </ResponsiveContainer>
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
                  <span className="h-3 w-3 rounded-full bg-green-500" />
                  Income by Category
                </CardTitle>
              </CardHeader>
              <CardContent>
                {incomePieData.length === 0 ? (
                  <p className="text-sm text-muted-foreground py-8 text-center">No income data</p>
                ) : (
                  <>
                    <ResponsiveContainer width="100%" height={200}>
                      <PieChart>
                        <Pie data={incomePieData} cx="50%" cy="50%"
                          innerRadius={55} outerRadius={85} paddingAngle={2} dataKey="value">
                          {incomePieData.map((_, i) => (
                            <Cell key={i} fill={INCOME_COLORS[i % INCOME_COLORS.length]} />
                          ))}
                        </Pie>
                        <Tooltip formatter={(v: number) => formatCurrency(v)} />
                      </PieChart>
                    </ResponsiveContainer>
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
