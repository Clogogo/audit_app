import { useEffect, useState } from 'react';
import {
  PieChart,
  Pie,
  Cell,
  Tooltip,
  Legend,
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
} from 'recharts';
import { Download } from 'lucide-react';
import { getSummary, exportReport } from '../api/client';
import type { TransactionSummary } from '../api/types';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { formatCurrency } from '../lib/utils';

const COLORS = ['#3b82f6', '#ef4444', '#22c55e', '#f59e0b', '#8b5cf6', '#ec4899', '#14b8a6', '#f97316', '#6366f1', '#84cc16'];

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
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

  const pieData = Object.entries(summary?.by_category ?? {}).map(([name, value]) => ({ name, value }));

  const handleExport = async (format: 'csv' | 'pdf') => {
    const blob = await exportReport(format, {
      start_date: startDate || undefined,
      end_date: endDate || undefined,
    });
    downloadBlob(blob, `transactions-report.${format}`);
  };

  return (
    <div className="space-y-6">
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
      <div className="flex items-center gap-3">
        <Input type="date" className="w-40" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
        <span className="text-muted-foreground">to</span>
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
          {/* Summary */}
          <div className="grid grid-cols-3 gap-4">
            {[
              { label: 'Total Income', value: summary?.total_income ?? 0, color: 'text-green-600' },
              { label: 'Total Expenses', value: summary?.total_expenses ?? 0, color: 'text-red-600' },
              { label: 'Net Balance', value: summary?.balance ?? 0, color: (summary?.balance ?? 0) >= 0 ? 'text-green-600' : 'text-red-600' },
            ].map(({ label, value, color }) => (
              <Card key={label}>
                <CardContent className="py-4 px-5">
                  <p className="text-xs text-muted-foreground">{label}</p>
                  <p className={`text-2xl font-bold ${color}`}>{formatCurrency(value)}</p>
                </CardContent>
              </Card>
            ))}
          </div>

          <div className="grid grid-cols-2 gap-6">
            {/* Spending by category */}
            <Card>
              <CardHeader><CardTitle className="text-base">Spending by Category</CardTitle></CardHeader>
              <CardContent>
                {pieData.length === 0 ? (
                  <p className="text-sm text-muted-foreground py-8 text-center">No data</p>
                ) : (
                  <ResponsiveContainer width="100%" height={280}>
                    <PieChart>
                      <Pie
                        data={pieData}
                        cx="50%"
                        cy="50%"
                        innerRadius={60}
                        outerRadius={100}
                        paddingAngle={3}
                        dataKey="value"
                      >
                        {pieData.map((_, i) => (
                          <Cell key={i} fill={COLORS[i % COLORS.length]} />
                        ))}
                      </Pie>
                      <Tooltip formatter={(v: number) => formatCurrency(v)} />
                      <Legend />
                    </PieChart>
                  </ResponsiveContainer>
                )}
              </CardContent>
            </Card>

            {/* Monthly income vs expenses */}
            <Card>
              <CardHeader><CardTitle className="text-base">Income vs Expenses Over Time</CardTitle></CardHeader>
              <CardContent>
                {(summary?.monthly ?? []).length === 0 ? (
                  <p className="text-sm text-muted-foreground py-8 text-center">No data</p>
                ) : (
                  <ResponsiveContainer width="100%" height={280}>
                    <LineChart data={summary?.monthly ?? []}>
                      <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                      <XAxis dataKey="month" tick={{ fontSize: 11 }} />
                      <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => `$${v}`} />
                      <Tooltip formatter={(v: number) => formatCurrency(v)} />
                      <Legend />
                      <Line type="monotone" dataKey="income" name="Income" stroke="#22c55e" strokeWidth={2} dot={false} />
                      <Line type="monotone" dataKey="expenses" name="Expenses" stroke="#ef4444" strokeWidth={2} dot={false} />
                    </LineChart>
                  </ResponsiveContainer>
                )}
              </CardContent>
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}
