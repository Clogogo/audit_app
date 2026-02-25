import { useEffect, useState } from 'react';
import {
  PieChart,
  Pie,
  Cell,
  Tooltip,
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Legend,
} from 'recharts';
import { ArrowLeft, Calendar, TrendingUp, TrendingDown, DollarSign } from 'lucide-react';
import { getBankAccountReports, getBankAccountReport } from '../api/client';
import type { BankAccountReportSummary, BankAccountReport } from '../api/types';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { formatCurrency } from '../lib/utils';

const EXPENSE_COLORS = ['#ef4444', '#f97316', '#f59e0b', '#eab308', '#84cc16', '#14b8a6'];
const INCOME_COLORS = ['#22c55e', '#16a34a', '#0ea5e9', '#6366f1', '#f59e0b', '#ec4899'];

type ViewMode = 'list' | 'detail';

export default function BankAccountReports() {
  const [viewMode, setViewMode] = useState<ViewMode>('list');
  const [summaries, setSummaries] = useState<BankAccountReportSummary[]>([]);
  const [selectedReport, setSelectedReport] = useState<BankAccountReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');

  // Fetch summary list
  const fetchSummaries = async () => {
    setLoading(true);
    try {
      const params: { start_date?: string; end_date?: string } = {};
      if (startDate) params.start_date = startDate;
      if (endDate) params.end_date = endDate;
      const data = await getBankAccountReports(params);
      setSummaries(data);
    } catch (error) {
      console.error('Failed to fetch bank account reports:', error);
    } finally {
      setLoading(false);
    }
  };

  // Fetch detailed report for specific account
  const fetchDetailedReport = async (accountId: number) => {
    setLoading(true);
    try {
      const params: { start_date?: string; end_date?: string } = {};
      if (startDate) params.start_date = startDate;
      if (endDate) params.end_date = endDate;
      const data = await getBankAccountReport(accountId, params);
      setSelectedReport(data);
      setViewMode('detail');
    } catch (error) {
      console.error('Failed to fetch detailed report:', error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchSummaries();
  }, []);

  const handleApplyFilters = () => {
    if (viewMode === 'list') {
      fetchSummaries();
    } else if (selectedReport) {
      fetchDetailedReport(selectedReport.bank_account_id);
    }
  };

  const handleBackToList = () => {
    setViewMode('list');
    setSelectedReport(null);
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          {viewMode === 'detail' && (
            <Button variant="outline" size="sm" onClick={handleBackToList}>
              <ArrowLeft className="w-4 h-4 mr-1" />
              Back
            </Button>
          )}
          <h1 className="text-2xl font-bold">
            {viewMode === 'list' ? 'Bank Account Reports' : 'Account Details'}
          </h1>
        </div>
      </div>

      {/* Date Filters */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm flex items-center gap-2">
            <Calendar className="w-4 h-4" />
            Date Range Filter
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex gap-3 items-end">
            <div className="flex-1">
              <label className="block text-xs font-medium mb-1 text-muted-foreground">
                Start Date
              </label>
              <Input
                type="date"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
              />
            </div>
            <div className="flex-1">
              <label className="block text-xs font-medium mb-1 text-muted-foreground">
                End Date
              </label>
              <Input
                type="date"
                value={endDate}
                onChange={(e) => setEndDate(e.target.value)}
              />
            </div>
            <Button onClick={handleApplyFilters} disabled={loading}>
              Apply Filters
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* List View: Summary Cards */}
      {viewMode === 'list' && (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {summaries.map((summary) => (
            <Card
              key={summary.bank_account_id}
              className="cursor-pointer hover:shadow-lg transition-shadow"
              onClick={() => fetchDetailedReport(summary.bank_account_id)}
            >
              <CardHeader>
                <CardTitle className="text-base">{summary.bank_name}</CardTitle>
                <p className="text-xs text-muted-foreground">
                  {summary.account_number || 'No account number'}
                </p>
              </CardHeader>
              <CardContent className="space-y-3">
                {/* Net Amount */}
                <div className="flex items-center justify-between p-3 bg-muted/50 rounded-lg">
                  <span className="text-sm font-medium">Net Amount</span>
                  <span
                    className={`text-lg font-bold ${
                      summary.net_amount >= 0 ? 'text-green-600' : 'text-red-600'
                    }`}
                  >
                    {formatCurrency(summary.net_amount, summary.currency)}
                  </span>
                </div>

                {/* Income */}
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2 text-green-600">
                    <TrendingUp className="w-4 h-4" />
                    <span className="text-sm">Income</span>
                  </div>
                  <div className="text-right">
                    <div className="font-semibold">
                      {formatCurrency(summary.total_income, summary.currency)}
                    </div>
                    <div className="text-xs text-muted-foreground">
                      {summary.income_count} transactions
                    </div>
                  </div>
                </div>

                {/* Expense */}
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2 text-red-600">
                    <TrendingDown className="w-4 h-4" />
                    <span className="text-sm">Expense</span>
                  </div>
                  <div className="text-right">
                    <div className="font-semibold">
                      {formatCurrency(summary.total_expense, summary.currency)}
                    </div>
                    <div className="text-xs text-muted-foreground">
                      {summary.expense_count} transactions
                    </div>
                  </div>
                </div>

                {/* Date Range */}
                {summary.first_transaction_date && summary.last_transaction_date && (
                  <div className="text-xs text-muted-foreground pt-2 border-t">
                    {new Date(summary.first_transaction_date).toLocaleDateString()} -{' '}
                    {new Date(summary.last_transaction_date).toLocaleDateString()}
                  </div>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Detail View: Detailed Report */}
      {viewMode === 'detail' && selectedReport && (
        <div className="space-y-6">
          {/* Summary Stats */}
          <div className="grid gap-4 md:grid-cols-4">
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium text-muted-foreground">
                  Total Income
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold text-green-600">
                  {formatCurrency(selectedReport.total_income, selectedReport.currency)}
                </div>
                <p className="text-xs text-muted-foreground mt-1">
                  {selectedReport.income_count} transactions
                </p>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium text-muted-foreground">
                  Total Expense
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold text-red-600">
                  {formatCurrency(selectedReport.total_expense, selectedReport.currency)}
                </div>
                <p className="text-xs text-muted-foreground mt-1">
                  {selectedReport.expense_count} transactions
                </p>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium text-muted-foreground">
                  Net Amount
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div
                  className={`text-2xl font-bold ${
                    selectedReport.net_amount >= 0 ? 'text-green-600' : 'text-red-600'
                  }`}
                >
                  {formatCurrency(selectedReport.net_amount, selectedReport.currency)}
                </div>
                <p className="text-xs text-muted-foreground mt-1">Income - Expense</p>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium text-muted-foreground">
                  Total Transactions
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">{selectedReport.total_transactions}</div>
                <p className="text-xs text-muted-foreground mt-1">
                  {selectedReport.transfer_count} transfers
                </p>
              </CardContent>
            </Card>
          </div>

          {/* Category Breakdowns */}
          <div className="grid gap-6 md:grid-cols-2">
            {/* Expense by Category */}
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Expense by Category</CardTitle>
              </CardHeader>
              <CardContent>
                {Object.keys(selectedReport.expense_by_category).length > 0 ? (
                  <>
                    <ResponsiveContainer width="100%" height={250}>
                      <PieChart>
                        <Pie
                          data={Object.entries(selectedReport.expense_by_category).map(
                            ([name, value]) => ({ name, value })
                          )}
                          dataKey="value"
                          nameKey="name"
                          cx="50%"
                          cy="50%"
                          outerRadius={80}
                          label={(entry) => entry.name}
                        >
                          {Object.keys(selectedReport.expense_by_category).map((_, idx) => (
                            <Cell
                              key={`cell-${idx}`}
                              fill={EXPENSE_COLORS[idx % EXPENSE_COLORS.length]}
                            />
                          ))}
                        </Pie>
                        <Tooltip formatter={(value) => formatCurrency(value as number)} />
                      </PieChart>
                    </ResponsiveContainer>
                    <div className="space-y-2 mt-4">
                      {Object.entries(selectedReport.expense_by_category).map(
                        ([category, amount], idx) => (
                          <div key={category} className="flex items-center justify-between">
                            <div className="flex items-center gap-2">
                              <div
                                className="w-3 h-3 rounded-full"
                                style={{
                                  backgroundColor:
                                    EXPENSE_COLORS[idx % EXPENSE_COLORS.length],
                                }}
                              />
                              <span className="text-sm">{category}</span>
                            </div>
                            <span className="text-sm font-medium">
                              {formatCurrency(amount, selectedReport.currency)}
                            </span>
                          </div>
                        )
                      )}
                    </div>
                  </>
                ) : (
                  <p className="text-sm text-muted-foreground">No expense data available</p>
                )}
              </CardContent>
            </Card>

            {/* Income by Category */}
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Income by Category</CardTitle>
              </CardHeader>
              <CardContent>
                {Object.keys(selectedReport.income_by_category).length > 0 ? (
                  <>
                    <ResponsiveContainer width="100%" height={250}>
                      <PieChart>
                        <Pie
                          data={Object.entries(selectedReport.income_by_category).map(
                            ([name, value]) => ({ name, value })
                          )}
                          dataKey="value"
                          nameKey="name"
                          cx="50%"
                          cy="50%"
                          outerRadius={80}
                          label={(entry) => entry.name}
                        >
                          {Object.keys(selectedReport.income_by_category).map((_, idx) => (
                            <Cell
                              key={`cell-${idx}`}
                              fill={INCOME_COLORS[idx % INCOME_COLORS.length]}
                            />
                          ))}
                        </Pie>
                        <Tooltip formatter={(value) => formatCurrency(value as number)} />
                      </PieChart>
                    </ResponsiveContainer>
                    <div className="space-y-2 mt-4">
                      {Object.entries(selectedReport.income_by_category).map(
                        ([category, amount], idx) => (
                          <div key={category} className="flex items-center justify-between">
                            <div className="flex items-center gap-2">
                              <div
                                className="w-3 h-3 rounded-full"
                                style={{
                                  backgroundColor: INCOME_COLORS[idx % INCOME_COLORS.length],
                                }}
                              />
                              <span className="text-sm">{category}</span>
                            </div>
                            <span className="text-sm font-medium">
                              {formatCurrency(amount, selectedReport.currency)}
                            </span>
                          </div>
                        )
                      )}
                    </div>
                  </>
                ) : (
                  <p className="text-sm text-muted-foreground">No income data available</p>
                )}
              </CardContent>
            </Card>
          </div>

          {/* Monthly Breakdown */}
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Monthly Trend</CardTitle>
            </CardHeader>
            <CardContent>
              {Object.keys(selectedReport.monthly_breakdown).length > 0 ? (
                <ResponsiveContainer width="100%" height={300}>
                  <BarChart
                    data={Object.entries(selectedReport.monthly_breakdown)
                      .sort(([a], [b]) => a.localeCompare(b))
                      .map(([month, data]) => ({
                        month,
                        income: data.income,
                        expense: data.expense,
                        transfer: data.transfer,
                      }))}
                  >
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="month" />
                    <YAxis />
                    <Tooltip formatter={(value) => formatCurrency(value as number)} />
                    <Legend />
                    <Bar dataKey="income" fill="#22c55e" name="Income" />
                    <Bar dataKey="expense" fill="#ef4444" name="Expense" />
                    <Bar dataKey="transfer" fill="#6366f1" name="Transfer" />
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <p className="text-sm text-muted-foreground">No monthly data available</p>
              )}
            </CardContent>
          </Card>
        </div>
      )}

      {loading && (
        <div className="flex justify-center items-center py-12">
          <div className="text-muted-foreground">Loading...</div>
        </div>
      )}
    </div>
  );
}
