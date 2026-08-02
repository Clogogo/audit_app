import React, { useEffect, useRef, useState } from 'react';
import {
  PieChart, Pie, Cell, Tooltip, ResponsiveContainer,
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Legend,
} from 'recharts';
import {
  ArrowLeft, Calendar, TrendingUp, TrendingDown,
  CheckCircle2, AlertTriangle, XCircle, Pencil, Check, X,
  Lightbulb, Building2,
} from 'lucide-react';
import { getBankAccountReports, getBankAccountReport, getBankAccounts, updateBankAccountBalance, updateBankAccountOpeningBalance } from '../api/client';
import type { BankAccount, BankAccountReportSummary, BankAccountReport } from '../api/types';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { formatCurrency } from '../lib/utils';

// Hex values for Recharts SVG fill props
const EXPENSE_COLORS = ['#ef4444', '#f97316', '#f59e0b', '#eab308', '#84cc16', '#14b8a6'];
const INCOME_COLORS  = ['#22c55e', '#16a34a', '#0ea5e9', '#6366f1', '#f59e0b', '#ec4899'];
// Tailwind classes for DOM legend dots
const EXPENSE_DOT = ['bg-red-500', 'bg-orange-500', 'bg-amber-500', 'bg-yellow-500', 'bg-lime-500', 'bg-teal-500'];
const INCOME_DOT  = ['bg-green-500', 'bg-green-700', 'bg-sky-500', 'bg-indigo-500', 'bg-amber-500', 'bg-pink-500'];

type ViewMode = 'list' | 'detail';

// ── Reconciliation helpers ────────────────────────────────────────────────────

interface ReconcStatus {
  status: 'matched' | 'over' | 'under' | 'unknown';
  variance: number;
  label: string;
  color: string;
  suggestions: string[];
}

function reconcile(actual: number | null | undefined, bookBalance: number): ReconcStatus {
  if (actual == null) {
    return {
      status: 'unknown',
      variance: 0,
      label: 'No balance set',
      color: 'text-muted-foreground',
      suggestions: [
        'Enter the actual bank balance (from your bank statement or app) on each card to see reconciliation.',
      ],
    };
  }

  const variance = actual - bookBalance;
  const absPct = bookBalance !== 0 ? Math.abs(variance / bookBalance) * 100 : 100;

  if (Math.abs(variance) < 1) {
    return {
      status: 'matched',
      variance,
      label: 'Perfectly reconciled',
      color: 'text-green-600',
      suggestions: ['All transactions match the bank balance. No action needed.'],
    };
  }

  if (absPct < 2) {
    return {
      status: 'matched',
      variance,
      label: `Within tolerance (${absPct.toFixed(1)}% gap)`,
      color: 'text-green-600',
      suggestions: [
        'The gap is within 2% — likely bank charges or pending transactions not yet processed.',
        'Check for small service fees or uncleared cheques.',
      ],
    };
  }

  if (variance > 0) {
    return {
      status: 'under',
      variance,
      label: `${formatCurrency(variance)} unrecorded`,
      color: 'text-amber-600',
      suggestions: [
        `The bank shows ${formatCurrency(variance)} more than your records — income may be missing or some transactions aren't linked to this account.`,
        'Transfers received INTO this account (e.g. auto-saves, top-ups) are stored as "transfer" type — re-categorise them as "income" so they count toward the book balance.',
        'Import recent bank statements via Banking → Import Statement to pick up any missing transactions.',
        'Check for deposits, credit alerts, or reversals not yet recorded.',
        'Verify all income transactions are linked to this bank account.',
      ],
    };
  }

  return {
    status: 'over',
    variance,
    label: `${formatCurrency(Math.abs(variance))} over-recorded`,
    color: 'text-red-600',
    suggestions: [
      `Your records show ${formatCurrency(Math.abs(variance))} more than the bank balance.`,
      'Transfers sent FROM this account are stored as "transfer" type and excluded from the book balance — re-categorise them as "expense" so they reduce it.',
      'Check for duplicate transactions — use Banking → Reconciliation to spot duplicates.',
      'Verify expense transactions have not been double-entered.',
      'Some transactions may be pending/on hold and not yet debited by the bank.',
    ],
  };
}

// ── Balance editor (inline) ───────────────────────────────────────────────────

function BalanceEditor({
  accountId,
  currentBalance,
  onSaved,
}: {
  accountId: number;
  currentBalance: number | null | undefined;
  onSaved: (balance: number | null) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(currentBalance != null ? String(currentBalance) : '');
  const [saving, setSaving] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const open = () => { setDraft(currentBalance != null ? String(currentBalance) : ''); setEditing(true); };
  const cancel = () => setEditing(false);

  const save = async () => {
    const val = draft.trim() === '' ? null : parseFloat(draft.replace(/,/g, ''));
    if (draft.trim() !== '' && isNaN(val!)) return;
    setSaving(true);
    try {
      await updateBankAccountBalance(accountId, val);
      onSaved(val);
      setEditing(false);
    } finally {
      setSaving(false);
    }
  };

  useEffect(() => { if (editing) inputRef.current?.focus(); }, [editing]);

  if (editing) {
    return (
      <div className="flex items-center gap-1.5 mt-1">
        <span className="text-sm text-muted-foreground">₦</span>
        <input
          ref={inputRef}
          type="number"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') save(); if (e.key === 'Escape') cancel(); }}
          className="w-36 border rounded px-2 py-1 text-sm outline-none focus:ring-1 focus:ring-primary"
          placeholder="0.00"
        />
        <button type="button" aria-label="Save balance" onClick={save} disabled={saving} className="text-green-600 hover:text-green-700">
          <Check className="h-4 w-4" />
        </button>
        <button type="button" aria-label="Cancel" onClick={cancel} className="text-muted-foreground hover:text-foreground">
          <X className="h-4 w-4" />
        </button>
      </div>
    );
  }

  return (
    <button
      type="button"
      onClick={open}
      className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground mt-1 group"
    >
      <span>{currentBalance != null ? formatCurrency(currentBalance) : 'Set actual balance'}</span>
      <Pencil className="h-3 w-3 opacity-0 group-hover:opacity-100 transition-opacity" />
    </button>
  );
}

// ── Opening balance editor (inline) ──────────────────────────────────────────

function OpeningBalanceEditor({
  accountId,
  openingBalance,
  openingBalanceDate,
  onSaved,
}: {
  accountId: number;
  openingBalance: number | null | undefined;
  openingBalanceDate: string | null | undefined;
  onSaved: (balance: number | null, balanceDate: string | null) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(openingBalance != null ? String(openingBalance) : '');
  const [draftDate, setDraftDate] = useState(openingBalanceDate ?? '');
  const [saving, setSaving] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const open = () => {
    setDraft(openingBalance != null ? String(openingBalance) : '');
    setDraftDate(openingBalanceDate ?? '');
    setEditing(true);
  };
  const cancel = () => setEditing(false);

  const save = async () => {
    const val = draft.trim() === '' ? null : parseFloat(draft.replace(/,/g, ''));
    if (draft.trim() !== '' && isNaN(val!)) return;
    const dateVal = draftDate.trim() === '' ? null : draftDate;
    setSaving(true);
    try {
      await updateBankAccountOpeningBalance(accountId, val, dateVal);
      onSaved(val, dateVal);
      setEditing(false);
    } finally {
      setSaving(false);
    }
  };

  useEffect(() => { if (editing) inputRef.current?.focus(); }, [editing]);

  if (editing) {
    return (
      <div className="flex flex-col gap-1.5 mt-1">
        <div className="flex items-center gap-1.5">
          <span className="text-sm text-muted-foreground">₦</span>
          <input
            ref={inputRef}
            type="number"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') save(); if (e.key === 'Escape') cancel(); }}
            className="w-36 border rounded px-2 py-1 text-sm outline-none focus:ring-1 focus:ring-primary"
            placeholder="0.00"
          />
          <button type="button" aria-label="Save opening balance" onClick={save} disabled={saving} className="text-green-600 hover:text-green-700">
            <Check className="h-4 w-4" />
          </button>
          <button type="button" aria-label="Cancel" onClick={cancel} className="text-muted-foreground hover:text-foreground">
            <X className="h-4 w-4" />
          </button>
        </div>
        <input
          type="date"
          value={draftDate}
          onChange={(e) => setDraftDate(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') save(); if (e.key === 'Escape') cancel(); }}
          className="w-36 border rounded px-2 py-1 text-xs outline-none focus:ring-1 focus:ring-primary"
          aria-label="Opening balance as-of date"
        />
      </div>
    );
  }

  return (
    <button
      type="button"
      onClick={open}
      className="flex flex-col items-start gap-0.5 text-sm text-muted-foreground hover:text-foreground mt-1 group"
    >
      <span className="flex items-center gap-1.5">
        {openingBalance != null ? formatCurrency(openingBalance) : 'Set opening balance'}
        <Pencil className="h-3 w-3 opacity-0 group-hover:opacity-100 transition-opacity" />
      </span>
      <span className="text-xs">
        {openingBalanceDate ? `as of ${openingBalanceDate}` : 'Set as-of date'}
      </span>
    </button>
  );
}

// ── StatusBadge ───────────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: ReconcStatus['status'] }) {
  if (status === 'matched') return (
    <span className="flex items-center gap-1 text-xs font-medium text-green-700 bg-green-100 px-2 py-0.5 rounded-full">
      <CheckCircle2 className="h-3 w-3" /> Reconciled
    </span>
  );
  if (status === 'under') return (
    <span className="flex items-center gap-1 text-xs font-medium text-amber-700 bg-amber-100 px-2 py-0.5 rounded-full">
      <AlertTriangle className="h-3 w-3" /> Gap
    </span>
  );
  if (status === 'over') return (
    <span className="flex items-center gap-1 text-xs font-medium text-red-700 bg-red-100 px-2 py-0.5 rounded-full">
      <XCircle className="h-3 w-3" /> Over-recorded
    </span>
  );
  return (
    <span className="flex items-center gap-1 text-xs font-medium text-muted-foreground bg-muted px-2 py-0.5 rounded-full">
      Balance not set
    </span>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function BankAccountReports() {
  const [viewMode, setViewMode] = useState<ViewMode>('list');
  const [summaries, setSummaries] = useState<BankAccountReportSummary[]>([]);
  const [accounts, setAccounts] = useState<Record<number, BankAccount>>({});
  const [selectedReport, setSelectedReport] = useState<BankAccountReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [startDate, setStartDate] = useState('2026-01-01');
  const [endDate, setEndDate] = useState('2026-12-31');

  const fetchSummaries = async () => {
    setLoading(true);
    try {
      const params: { start_date?: string; end_date?: string } = {};
      if (startDate) params.start_date = startDate;
      if (endDate) params.end_date = endDate;
      const [data, accts] = await Promise.all([getBankAccountReports(params), getBankAccounts()]);
      setSummaries(data);
      setAccounts(Object.fromEntries(accts.map((a) => [a.id, a])));
    } finally {
      setLoading(false);
    }
  };

  const fetchDetailedReport = async (accountId: number) => {
    setLoading(true);
    try {
      const params: { start_date?: string; end_date?: string } = {};
      if (startDate) params.start_date = startDate;
      if (endDate) params.end_date = endDate;
      const data = await getBankAccountReport(accountId, params);
      setSelectedReport(data);
      setViewMode('detail');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchSummaries(); }, []);

  const handleApplyFilters = () => {
    if (viewMode === 'list') fetchSummaries();
    else if (selectedReport) fetchDetailedReport(selectedReport.bank_account_id);
  };

  const handleBackToList = () => { setViewMode('list'); setSelectedReport(null); };

  const handleBalanceSaved = (accountId: number, balance: number | null) => {
    setAccounts((prev) => ({ ...prev, [accountId]: { ...prev[accountId], current_balance: balance } }));
  };

  const handleOpeningBalanceSaved = (accountId: number, balance: number | null, balanceDate: string | null) => {
    setAccounts((prev) => ({
      ...prev,
      [accountId]: { ...prev[accountId], opening_balance: balance, opening_balance_date: balanceDate },
    }));
    // Refresh summaries so net_amount recalculates from the server. Also
    // refresh the detail report if that's the currently open view — otherwise
    // its header keeps showing the pre-edit net_amount/opening_balance until
    // the user navigates back to the list and reopens the account.
    if (viewMode === 'detail' && selectedReport?.bank_account_id === accountId) {
      fetchDetailedReport(accountId);
    }
    fetchSummaries();
  };

  // Grand totals for the list view
  const grandTotal    = summaries.reduce((s, r) => s + r.net_amount, 0);
  const actualTotal   = summaries.reduce((s, r) => {
    const bal = accounts[r.bank_account_id]?.current_balance;
    return bal != null ? s + bal : s;
  }, 0);
  const allHaveBalance = summaries.every((r) => accounts[r.bank_account_id]?.current_balance != null);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          {viewMode === 'detail' && (
            <Button variant="outline" size="sm" onClick={handleBackToList}>
              <ArrowLeft className="w-4 h-4 mr-1" /> Back
            </Button>
          )}
          <div>
            <h1 className="text-2xl font-bold">
              {viewMode === 'list' ? 'Bank Account Reports' : (selectedReport?.bank_name ?? 'Account Details')}
            </h1>
            {viewMode === 'list' && (
              <p className="text-xs text-muted-foreground mt-0.5">
                Click any account to see the full breakdown. Set actual balances to reconcile.
              </p>
            )}
            {viewMode === 'detail' && selectedReport && (
              <p className="text-xs text-muted-foreground mt-0.5">
                {[selectedReport.account_holder_name, selectedReport.account_number].filter(Boolean).join(' · ')}
              </p>
            )}
          </div>
        </div>
      </div>

      {/* Date Filters */}
      <Card>
        <CardContent className="pt-4">
          <div className="flex gap-3 items-end flex-wrap">
            <div className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
              <Calendar className="w-4 h-4" /> Date range
            </div>
            <div>
              <label className="block text-xs text-muted-foreground mb-1">From</label>
              <Input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} className="w-40" />
            </div>
            <div>
              <label className="block text-xs text-muted-foreground mb-1">To</label>
              <Input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} className="w-40" />
            </div>
            <Button onClick={handleApplyFilters} disabled={loading}>Apply</Button>
          </div>
        </CardContent>
      </Card>

      {/* ── LIST VIEW ─────────────────────────────────────────────────────────── */}
      {viewMode === 'list' && (
        <>
          {/* Grand-total cash position */}
          {summaries.length > 0 && (
            <div className="rounded-2xl border bg-card p-5">
              <p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground mb-3">Cash Position</p>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                {summaries.map((s) => {
                  const acct = accounts[s.bank_account_id];
                  const actual = acct?.current_balance;
                  return (
                    <div key={s.bank_account_id} className="flex flex-col gap-0.5">
                      <p className="text-xs text-muted-foreground truncate">{s.bank_name}</p>
                      <p className="text-lg font-bold">
                        {actual != null ? formatCurrency(actual) : <span className="text-muted-foreground text-sm">—</span>}
                      </p>
                      <p className="text-xs text-muted-foreground">Book: {formatCurrency(s.net_amount)}</p>
                    </div>
                  );
                })}
                {allHaveBalance && (
                  <div className="flex flex-col gap-0.5 border-l pl-4">
                    <p className="text-xs text-muted-foreground">Total Cash</p>
                    <p className="text-lg font-bold text-primary">{formatCurrency(actualTotal)}</p>
                    <p className="text-xs text-muted-foreground">Book: {formatCurrency(grandTotal)}</p>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Account cards */}
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {summaries.map((summary) => {
              const acct = accounts[summary.bank_account_id];
              const actual = acct?.current_balance;
              const reconc = reconcile(actual, summary.net_amount);

              return (
                <Card key={summary.bank_account_id} className="overflow-hidden">
                  {/* Card top — clickable for detail */}
                  <div
                    className="cursor-pointer hover:bg-muted/30 transition-colors p-5 pb-3"
                    onClick={() => fetchDetailedReport(summary.bank_account_id)}
                  >
                    <div className="flex items-start justify-between gap-2 mb-3">
                      <div className="flex items-center gap-2 min-w-0">
                        <div className="h-8 w-8 rounded-lg bg-primary/10 flex items-center justify-center shrink-0">
                          <Building2 className="h-4 w-4 text-primary" />
                        </div>
                        <div className="min-w-0">
                          <p className="text-sm font-semibold truncate">{summary.bank_name}</p>
                          <p className="text-xs text-muted-foreground truncate">
                            {summary.account_number || 'No account number'}
                          </p>
                        </div>
                      </div>
                      <StatusBadge status={reconc.status} />
                    </div>

                    {/* Balance comparison */}
                    <div className="grid grid-cols-2 gap-2 mb-3">
                      <div className="rounded-lg bg-muted/50 p-3">
                        <p className="text-xs text-muted-foreground mb-0.5">Book balance</p>
                        <p className={`text-base font-bold ${summary.net_amount >= 0 ? 'text-primary' : 'text-expense'}`}>
                          {formatCurrency(summary.net_amount)}
                        </p>
                        <p className="text-xs text-muted-foreground mt-0.5">Income − Expense − Transfers</p>
                      </div>
                      <div className="rounded-lg bg-muted/50 p-3">
                        <p className="text-xs text-muted-foreground mb-0.5">Actual balance</p>
                        {actual != null ? (
                          <>
                            <p className={`text-base font-bold ${actual >= 0 ? 'text-primary' : 'text-expense'}`}>
                              {formatCurrency(actual)}
                            </p>
                            <p className={`text-xs mt-0.5 font-medium ${reconc.color}`}>
                              {reconc.variance >= 0 ? '+' : ''}{formatCurrency(reconc.variance)} variance
                            </p>
                          </>
                        ) : (
                          <p className="text-sm text-muted-foreground mt-1">Not set</p>
                        )}
                      </div>
                    </div>

                    {/* Income / Expense strip */}
                    <div className="flex items-center gap-4 text-xs">
                      <div className="flex items-center gap-1 text-income">
                        <TrendingUp className="h-3.5 w-3.5" />
                        <span>{formatCurrency(summary.total_income)}</span>
                        <span className="text-muted-foreground">({summary.income_count})</span>
                      </div>
                      <div className="flex items-center gap-1 text-expense">
                        <TrendingDown className="h-3.5 w-3.5" />
                        <span>{formatCurrency(summary.total_expense)}</span>
                        <span className="text-muted-foreground">({summary.expense_count})</span>
                      </div>
                    </div>
                  </div>

                  {/* Balance editors — not inside the clickable area */}
                  <div className="px-5 pb-3 border-t pt-3 grid grid-cols-2 gap-3" onClick={(e) => e.stopPropagation()}>
                    <div>
                      <p className="text-xs text-muted-foreground mb-1">Opening balance</p>
                      <OpeningBalanceEditor
                        accountId={summary.bank_account_id}
                        openingBalance={acct?.opening_balance}
                        openingBalanceDate={acct?.opening_balance_date}
                        onSaved={(bal, balDate) => handleOpeningBalanceSaved(summary.bank_account_id, bal, balDate)}
                      />
                    </div>
                    <div>
                      <p className="text-xs text-muted-foreground mb-1">Actual balance</p>
                      <BalanceEditor
                        accountId={summary.bank_account_id}
                        currentBalance={actual}
                        onSaved={(bal) => handleBalanceSaved(summary.bank_account_id, bal)}
                      />
                    </div>
                  </div>

                  {/* Suggestions */}
                  {reconc.status !== 'matched' && reconc.status !== 'unknown' && (
                    <div className="px-5 pb-4 border-t">
                      <div className="flex items-center gap-1.5 mt-3 mb-2">
                        <Lightbulb className="h-3.5 w-3.5 text-amber-500 shrink-0" />
                        <p className="text-xs font-semibold text-amber-700">Suggestions</p>
                      </div>
                      <ul className="space-y-1">
                        {reconc.suggestions.slice(0, 3).map((s, i) => (
                          <li key={i} className="text-xs text-muted-foreground flex gap-1.5">
                            <span className="text-amber-500 shrink-0">•</span>{s}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </Card>
              );
            })}
          </div>
        </>
      )}

      {/* ── DETAIL VIEW ───────────────────────────────────────────────────────── */}
      {viewMode === 'detail' && selectedReport && (
        <div className="space-y-6">
          {/* Reconciliation banner */}
          {(() => {
            const acct = accounts[selectedReport.bank_account_id];
            const actual = acct?.current_balance;
            const reconc = reconcile(actual, selectedReport.net_amount);
            return (
              <div className={`rounded-2xl border p-5 ${
                reconc.status === 'matched' ? 'border-green-200 bg-green-50' :
                reconc.status === 'under'   ? 'border-amber-200 bg-amber-50' :
                reconc.status === 'over'    ? 'border-red-200 bg-red-50'     :
                'border-border bg-muted/30'
              }`}>
                <div className="flex items-start justify-between gap-4 flex-wrap">
                  <div>
                    <p className="text-xs font-semibold text-muted-foreground uppercase tracking-widest mb-1.5">
                      {selectedReport.bank_name}
                      {selectedReport.account_number ? ` · ${selectedReport.account_number}` : ''}
                    </p>
                    <div className="flex items-center gap-2 mb-1">
                      <StatusBadge status={reconc.status} />
                      <span className={`text-sm font-semibold ${reconc.color}`}>{reconc.label}</span>
                    </div>
                    <div className="flex items-center gap-6 text-sm mt-2 flex-wrap">
                      {selectedReport.opening_balance > 0 && (
                        <div>
                          <p className="text-xs text-muted-foreground">Opening balance</p>
                          <p className="font-bold text-primary">{formatCurrency(selectedReport.opening_balance)}</p>
                        </div>
                      )}
                      <div>
                        <p className="text-xs text-muted-foreground">Book balance</p>
                        <p className="font-bold">{formatCurrency(selectedReport.net_amount)}</p>
                      </div>
                      {actual != null && (
                        <>
                          <div>
                            <p className="text-xs text-muted-foreground">Actual balance</p>
                            <p className="font-bold">{formatCurrency(actual)}</p>
                          </div>
                          <div>
                            <p className="text-xs text-muted-foreground">Variance</p>
                            <p className={`font-bold ${reconc.color}`}>
                              {reconc.variance >= 0 ? '+' : ''}{formatCurrency(reconc.variance)}
                            </p>
                          </div>
                        </>
                      )}
                    </div>
                  </div>
                  <div className="flex flex-col gap-3" onClick={(e) => e.stopPropagation()}>
                    <div>
                      <p className="text-xs text-muted-foreground mb-1">Opening balance</p>
                      <OpeningBalanceEditor
                        accountId={selectedReport.bank_account_id}
                        openingBalance={accounts[selectedReport.bank_account_id]?.opening_balance}
                        openingBalanceDate={accounts[selectedReport.bank_account_id]?.opening_balance_date}
                        onSaved={(bal, balDate) => handleOpeningBalanceSaved(selectedReport.bank_account_id, bal, balDate)}
                      />
                    </div>
                    <div>
                      <p className="text-xs text-muted-foreground mb-1">Actual balance</p>
                      <BalanceEditor
                        accountId={selectedReport.bank_account_id}
                        currentBalance={actual}
                        onSaved={(bal) => handleBalanceSaved(selectedReport.bank_account_id, bal)}
                      />
                    </div>
                  </div>
                </div>
                {reconc.suggestions.length > 0 && reconc.status !== 'matched' && (
                  <div className="mt-4 pt-4 border-t border-current/10">
                    <div className="flex items-center gap-1.5 mb-2">
                      <Lightbulb className="h-3.5 w-3.5 text-amber-500" />
                      <p className="text-xs font-semibold">How to fix this gap</p>
                    </div>
                    <ul className="grid sm:grid-cols-2 gap-1">
                      {reconc.suggestions.map((s, i) => (
                        <li key={i} className="text-xs text-muted-foreground flex gap-1.5">
                          <span className="text-amber-500 shrink-0">{i + 1}.</span>{s}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            );
          })()}

          {/* 4-stat strip */}
          <div className="grid gap-4 md:grid-cols-4">
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium text-muted-foreground">Total Income</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold text-income">
                  {formatCurrency(selectedReport.total_income, selectedReport.currency)}
                </div>
                <p className="text-xs text-muted-foreground mt-1">{selectedReport.income_count} transactions</p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium text-muted-foreground">Total Expense</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold text-expense">
                  {formatCurrency(selectedReport.total_expense, selectedReport.currency)}
                </div>
                <p className="text-xs text-muted-foreground mt-1">{selectedReport.expense_count} transactions</p>
              </CardContent>
            </Card>
            {/* Book Balance — the destination figure of Income − Expense, visually distinct */}
            <Card className="bg-primary text-primary-foreground border-0">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium text-primary-foreground/70">Book Balance</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold font-display">
                  {formatCurrency(selectedReport.net_amount, selectedReport.currency)}
                </div>
                <p className="text-xs text-primary-foreground/70 mt-1">
                  {selectedReport.opening_balance > 0
                    ? `Opening ${formatCurrency(selectedReport.opening_balance)}${selectedReport.opening_balance_date ? ` (as of ${selectedReport.opening_balance_date})` : ''} + Income − Expense since`
                    : 'Income − Expense − Transfers out'}
                </p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium text-muted-foreground">Total Transactions</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">{selectedReport.total_transactions}</div>
                <p className="text-xs text-muted-foreground mt-1">{selectedReport.transfer_count} transfers</p>
              </CardContent>
            </Card>
          </div>

          {/* Category breakdowns */}
          <div className="grid gap-6 md:grid-cols-2">
            {/* Expense breakdown */}
            {(() => {
              const entries = Object.entries(selectedReport.expense_by_category)
                .sort(([, a], [, b]) => b - a);
              const total = entries.reduce((s, [, v]) => s + v, 0);
              return (
                <Card>
                  <CardHeader className="pb-3">
                    <div className="flex items-center justify-between">
                      <CardTitle className="text-base">Expenses</CardTitle>
                      <span className="text-sm font-semibold text-expense">{formatCurrency(total)}</span>
                    </div>
                  </CardHeader>
                  <CardContent>
                    {entries.length > 0 ? (
                      <div className="flex gap-6">
                        {/* Donut */}
                        <div className="shrink-0">
                          <ResponsiveContainer width={130} height={130}>
                            <PieChart>
                              <Pie
                                data={entries.map(([name, value]) => ({ name, value }))}
                                dataKey="value" nameKey="name"
                                cx="50%" cy="50%" innerRadius={38} outerRadius={60}
                                strokeWidth={2} stroke="white"
                              >
                                {entries.map((_, idx) => (
                                  <Cell key={idx} fill={EXPENSE_COLORS[idx % EXPENSE_COLORS.length]} />
                                ))}
                              </Pie>
                              <Tooltip formatter={(v) => formatCurrency(v as number)} />
                            </PieChart>
                          </ResponsiveContainer>
                        </div>
                        {/* Ranked rows */}
                        <div className="flex-1 space-y-2.5 min-w-0">
                          {entries.map(([cat, amt], idx) => {
                            const pct = total > 0 ? (amt / total) * 100 : 0;
                            return (
                              <div key={cat}>
                                <div className="flex items-center justify-between text-xs mb-0.5">
                                  <div className="flex items-center gap-1.5 min-w-0">
                                    <div className={`w-2 h-2 rounded-full shrink-0 ${EXPENSE_DOT[idx % EXPENSE_DOT.length]}`} />
                                    <span className="truncate font-medium text-foreground">{cat}</span>
                                  </div>
                                  <span className="text-muted-foreground shrink-0 ml-2">{pct.toFixed(1)}%</span>
                                </div>
                                <div className="flex items-center gap-2">
                                  <div className="flex-1 h-1.5 bg-muted rounded-full overflow-hidden">
                                    <div
                                      className={`category-bar-fill h-full rounded-full ${EXPENSE_DOT[idx % EXPENSE_DOT.length]}`}
                                      style={{ '--bar-w': `${pct}%` } as React.CSSProperties}
                                    />
                                  </div>
                                  <span className="text-xs font-semibold tabular-nums shrink-0 w-28 text-right">
                                    {formatCurrency(amt)}
                                  </span>
                                </div>
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    ) : <p className="text-sm text-muted-foreground">No expense data</p>}
                  </CardContent>
                </Card>
              );
            })()}

            {/* Income breakdown */}
            {(() => {
              const entries = Object.entries(selectedReport.income_by_category)
                .sort(([, a], [, b]) => b - a);
              const total = entries.reduce((s, [, v]) => s + v, 0);
              return (
                <Card>
                  <CardHeader className="pb-3">
                    <div className="flex items-center justify-between">
                      <CardTitle className="text-base">Income</CardTitle>
                      <span className="text-sm font-semibold text-income">{formatCurrency(total)}</span>
                    </div>
                  </CardHeader>
                  <CardContent>
                    {entries.length > 0 ? (
                      <div className="flex gap-6">
                        <div className="shrink-0">
                          <ResponsiveContainer width={130} height={130}>
                            <PieChart>
                              <Pie
                                data={entries.map(([name, value]) => ({ name, value }))}
                                dataKey="value" nameKey="name"
                                cx="50%" cy="50%" innerRadius={38} outerRadius={60}
                                strokeWidth={2} stroke="white"
                              >
                                {entries.map((_, idx) => (
                                  <Cell key={idx} fill={INCOME_COLORS[idx % INCOME_COLORS.length]} />
                                ))}
                              </Pie>
                              <Tooltip formatter={(v) => formatCurrency(v as number)} />
                            </PieChart>
                          </ResponsiveContainer>
                        </div>
                        <div className="flex-1 space-y-2.5 min-w-0">
                          {entries.map(([cat, amt], idx) => {
                            const pct = total > 0 ? (amt / total) * 100 : 0;
                            return (
                              <div key={cat}>
                                <div className="flex items-center justify-between text-xs mb-0.5">
                                  <div className="flex items-center gap-1.5 min-w-0">
                                    <div className={`w-2 h-2 rounded-full shrink-0 ${INCOME_DOT[idx % INCOME_DOT.length]}`} />
                                    <span className="truncate font-medium text-foreground">{cat}</span>
                                  </div>
                                  <span className="text-muted-foreground shrink-0 ml-2">{pct.toFixed(1)}%</span>
                                </div>
                                <div className="flex items-center gap-2">
                                  <div className="flex-1 h-1.5 bg-muted rounded-full overflow-hidden">
                                    <div
                                      className={`category-bar-fill h-full rounded-full ${INCOME_DOT[idx % INCOME_DOT.length]}`}
                                      style={{ '--bar-w': `${pct}%` } as React.CSSProperties}
                                    />
                                  </div>
                                  <span className="text-xs font-semibold tabular-nums shrink-0 w-28 text-right">
                                    {formatCurrency(amt)}
                                  </span>
                                </div>
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    ) : <p className="text-sm text-muted-foreground">No income data</p>}
                  </CardContent>
                </Card>
              );
            })()}
          </div>

          {/* Monthly trend */}
          <Card>
            <CardHeader><CardTitle className="text-base">Monthly Trend</CardTitle></CardHeader>
            <CardContent>
              {Object.keys(selectedReport.monthly_breakdown).length > 0 ? (
                <ResponsiveContainer width="100%" height={280}>
                  <BarChart
                    data={Object.entries(selectedReport.monthly_breakdown)
                      .sort(([a], [b]) => a.localeCompare(b))
                      .map(([month, data]) => ({ month, income: data.income, expense: data.expense, transfer: data.transfer }))}
                  >
                    <CartesianGrid strokeDasharray="3 3" vertical={false} />
                    <XAxis dataKey="month" tick={{ fontSize: 11 }} axisLine={false} tickLine={false} />
                    <YAxis tick={{ fontSize: 11 }} axisLine={false} tickLine={false} />
                    <Tooltip formatter={(v) => formatCurrency(v as number)} />
                    <Legend />
                    <Bar dataKey="income" fill="#22c55e" name="Income" radius={[4, 4, 0, 0]} />
                    <Bar dataKey="expense" fill="#ef4444" name="Expense" radius={[4, 4, 0, 0]} />
                    <Bar dataKey="transfer" fill="#6366f1" name="Transfer" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              ) : <p className="text-sm text-muted-foreground">No monthly data</p>}
            </CardContent>
          </Card>
        </div>
      )}

      {loading && (
        <div className="flex justify-center items-center py-12 text-muted-foreground">Loading…</div>
      )}
    </div>
  );
}
