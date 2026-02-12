import { useEffect, useState } from 'react';
import { TrendingUp, TrendingDown, Scale } from 'lucide-react';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts';
import { getSummary, getTransactions } from '../api/client';
import type { TransactionSummary, Transaction } from '../api/types';
import { StatCard } from '../components/StatCard';
import { TypeBadge } from '../components/CategoryBadge';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { formatCurrency, formatDate } from '../lib/utils';

export function Dashboard() {
  const [summary, setSummary] = useState<TransactionSummary | null>(null);
  const [recent, setRecent] = useState<Transaction[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([getSummary(), getTransactions()])
      .then(([s, tx]) => {
        setSummary(s);
        setRecent(tx.slice(0, 8));
      })
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="flex items-center justify-center h-64 text-muted-foreground">Loading...</div>;

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Dashboard</h1>

      {/* Stat cards */}
      <div className="grid grid-cols-3 gap-4">
        <StatCard
          title="Total Income"
          amount={summary?.total_income ?? 0}
          icon={TrendingUp}
          trend="up"
        />
        <StatCard
          title="Total Expenses"
          amount={summary?.total_expenses ?? 0}
          icon={TrendingDown}
          trend="down"
        />
        <StatCard
          title="Balance"
          amount={summary?.balance ?? 0}
          icon={Scale}
          trend={summary && summary.balance >= 0 ? 'up' : 'down'}
        />
      </div>

      {/* Monthly chart */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Monthly Overview</CardTitle>
        </CardHeader>
        <CardContent>
          <ResponsiveContainer width="100%" height={280}>
            <BarChart data={summary?.monthly ?? []}>
              <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
              <XAxis dataKey="month" tick={{ fontSize: 12 }} />
              <YAxis tick={{ fontSize: 12 }} tickFormatter={(v) => `$${v}`} />
              <Tooltip formatter={(v: number) => formatCurrency(v)} />
              <Legend />
              <Bar dataKey="income" name="Income" fill="#22c55e" radius={[4, 4, 0, 0]} />
              <Bar dataKey="expenses" name="Expenses" fill="#ef4444" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </CardContent>
      </Card>

      {/* Recent transactions */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Recent Transactions</CardTitle>
        </CardHeader>
        <CardContent>
          {recent.length === 0 ? (
            <p className="text-sm text-muted-foreground py-4 text-center">No transactions yet</p>
          ) : (
            <div className="divide-y">
              {recent.map((tx) => (
                <div key={tx.id} className="flex items-center justify-between py-3">
                  <div className="flex items-center gap-3">
                    <TypeBadge type={tx.type} />
                    <div>
                      <p className="text-sm font-medium">{tx.description}</p>
                      <p className="text-xs text-muted-foreground">{tx.vendor} · {formatDate(tx.date)}</p>
                    </div>
                  </div>
                  <span
                    className={`text-sm font-semibold ${
                      tx.type === 'income' ? 'text-green-600' : 'text-red-600'
                    }`}
                  >
                    {tx.type === 'income' ? '+' : '-'}{formatCurrency(tx.amount, tx.currency)}
                  </span>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
