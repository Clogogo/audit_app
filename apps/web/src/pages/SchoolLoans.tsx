import { useEffect, useState } from 'react';
import {
  Landmark, Plus, Pencil, Trash2, CheckCircle2, XCircle, AlertCircle, ChevronDown, ChevronUp,
  BadgeCheck, Link as LinkIcon, Loader2,
} from 'lucide-react';
import {
  listSchoolLoans, createSchoolLoan, updateSchoolLoan, deleteSchoolLoan,
  addSchoolLoanPayment, updateSchoolLoanPayment, deleteSchoolLoanPayment,
  matchSchoolLoanTransactions,
} from '../api/client';
import type { SchoolLoan, SchoolLoanIn, SchoolLoanPaymentOut, SchoolLoanPaymentIn, MatchedTransaction } from '../api/types';
import { Button } from '../components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { formatCurrency } from '../lib/utils';

const EMPTY_LOAN: SchoolLoanIn = {
  lender_name: '',
  loan_amount: 0,
  interest_rate: 0,
  collected_date: '',
  notes: '',
  is_active: true,
};

const EMPTY_PAYMENT: SchoolLoanPaymentIn = {
  amount_paid: 0,
  interest_amount: 0,
  misc_amount: 0,
  paid_date: '',
  transaction_id: null,
  notes: '',
};

function progressPct(loan: SchoolLoan): number {
  if (loan.loan_amount === 0) return 100;
  const principalPaid = loan.loan_amount - loan.outstanding_today;
  return Math.min(100, Math.round((principalPaid / loan.loan_amount) * 100));
}

function NumInput({
  label, value, onChange, required = false,
}: { label: string; value: number; onChange: (n: number) => void; required?: boolean }) {
  const [raw, setRaw] = useState('');
  const [focused, setFocused] = useState(false);
  return (
    <div>
      <label className="block text-xs font-medium text-foreground mb-1">{label}{required && ' *'}</label>
      <input
        type="text"
        inputMode="numeric"
        placeholder="0"
        value={focused ? raw : (value === 0 ? '' : value.toLocaleString('en-NG'))}
        onFocus={() => { setFocused(true); setRaw(value === 0 ? '' : String(value)); }}
        onChange={(e) => {
          const d = e.target.value.replace(/[^0-9]/g, '');
          setRaw(d);
          onChange(d === '' ? 0 : parseInt(d, 10));
        }}
        onBlur={() => setFocused(false)}
        className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
      />
    </div>
  );
}

export function SchoolLoans() {
  const [loans, setLoans] = useState<SchoolLoan[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Loan form
  const [showLoanForm, setShowLoanForm] = useState(false);
  const [editingLoan, setEditingLoan] = useState<SchoolLoan | null>(null);
  const [loanForm, setLoanForm] = useState<SchoolLoanIn>(EMPTY_LOAN);
  const [savingLoan, setSavingLoan] = useState(false);
  const [deleteLoanId, setDeleteLoanId] = useState<number | null>(null);

  // Payment form
  const [paymentLoanId, setPaymentLoanId] = useState<number | null>(null);
  const [editingPayment, setEditingPayment] = useState<SchoolLoanPaymentOut | null>(null);
  const [paymentForm, setPaymentForm] = useState<SchoolLoanPaymentIn>(EMPTY_PAYMENT);
  const [savingPayment, setSavingPayment] = useState(false);
  const [deletePayment, setDeletePayment] = useState<{ loanId: number; paymentId: number } | null>(null);

  // Transaction matching
  const [matchedTxs, setMatchedTxs] = useState<MatchedTransaction[]>([]);
  const [loadingTxs, setLoadingTxs] = useState(false);

  // Expanded rows
  const [expandedLoanId, setExpandedLoanId] = useState<number | null>(null);

  const load = () => {
    setLoading(true);
    listSchoolLoans()
      .then(setLoans)
      .catch(() => setError('Failed to load data'))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  // ── Loan handlers ────────────────────────────────────────────────────────────

  const openAddLoan = () => { setEditingLoan(null); setLoanForm(EMPTY_LOAN); setShowLoanForm(true); };
  const openEditLoan = (loan: SchoolLoan) => {
    setEditingLoan(loan);
    setLoanForm({
      lender_name: loan.lender_name,
      loan_amount: loan.loan_amount,
      interest_rate: loan.interest_rate,
      collected_date: loan.collected_date,
      notes: loan.notes ?? '',
      is_active: loan.is_active,
    });
    setShowLoanForm(true);
  };

  const handleSaveLoan = async () => {
    if (!loanForm.lender_name.trim() || loanForm.loan_amount <= 0 || !loanForm.collected_date) return;
    setSavingLoan(true);
    try {
      if (editingLoan) {
        await updateSchoolLoan(editingLoan.id, loanForm);
      } else {
        await createSchoolLoan(loanForm);
      }
      setShowLoanForm(false);
      setEditingLoan(null);
      load();
    } catch {
      setError('Failed to save school loan');
    } finally {
      setSavingLoan(false);
    }
  };

  const handleDeleteLoan = async (id: number) => {
    try {
      await deleteSchoolLoan(id);
      setDeleteLoanId(null);
      load();
    } catch {
      setError('Failed to delete school loan');
    }
  };

  // ── Payment handlers ─────────────────────────────────────────────────────────

  const openAddPayment = (loanId: number) => {
    setPaymentLoanId(loanId);
    setEditingPayment(null);
    setPaymentForm(EMPTY_PAYMENT);
    setMatchedTxs([]);
  };

  const openEditPayment = (loanId: number, payment: SchoolLoanPaymentOut) => {
    setPaymentLoanId(loanId);
    setEditingPayment(payment);
    setPaymentForm({
      amount_paid: payment.amount_paid,
      interest_amount: payment.interest_amount,
      misc_amount: payment.misc_amount,
      paid_date: payment.paid_date,
      transaction_id: payment.transaction_id ?? null,
      notes: payment.notes ?? '',
    });
    setMatchedTxs(payment.matched_tx ? [payment.matched_tx] : []);
  };

  const handlePaymentDateChange = async (newDate: string) => {
    setPaymentForm((f) => ({ ...f, paid_date: newDate, transaction_id: null }));
    setMatchedTxs([]);
    if (!newDate || !paymentLoanId) return;
    const parts = newDate.split('-');
    const year = parseInt(parts[0], 10);
    const month = parseInt(parts[1], 10);
    if (!year || !month) return;
    setLoadingTxs(true);
    try {
      const txs = await matchSchoolLoanTransactions(paymentLoanId, year, month);
      setMatchedTxs(txs);
    } catch {
      setMatchedTxs([]);
    } finally {
      setLoadingTxs(false);
    }
  };

  const handleSelectTx = (tx: MatchedTransaction) => {
    setPaymentForm((f) => ({ ...f, transaction_id: tx.id, amount_paid: tx.amount }));
  };

  const handleSavePayment = async () => {
    if (!paymentLoanId || paymentForm.amount_paid <= 0 || !paymentForm.paid_date) return;
    setSavingPayment(true);
    try {
      if (editingPayment) {
        await updateSchoolLoanPayment(paymentLoanId, editingPayment.id, paymentForm);
      } else {
        await addSchoolLoanPayment(paymentLoanId, paymentForm);
      }
      setPaymentLoanId(null);
      setEditingPayment(null);
      setMatchedTxs([]);
      load();
    } catch {
      setError('Failed to save payment');
    } finally {
      setSavingPayment(false);
    }
  };

  const handleDeletePayment = async () => {
    if (!deletePayment) return;
    try {
      await deleteSchoolLoanPayment(deletePayment.loanId, deletePayment.paymentId);
      setDeletePayment(null);
      load();
    } catch {
      setError('Failed to delete payment');
    }
  };

  // ── Derived ──────────────────────────────────────────────────────────────────

  const active = loans.filter((l) => l.is_active && l.outstanding_today > 0);
  const repaid = loans.filter((l) => !l.is_active || l.outstanding_today === 0);
  const totalOutstanding = active.reduce((s, l) => s + l.outstanding_today, 0);
  const totalCollected = loans.reduce((s, l) => s + l.loan_amount, 0);

  const paymentPrincipal = paymentForm.amount_paid - (paymentForm.interest_amount ?? 0) - (paymentForm.misc_amount ?? 0);

  const fmt = (d: string) => new Date(d).toLocaleDateString('en-NG', { day: '2-digit', month: 'short', year: 'numeric' });

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Landmark className="h-6 w-6 text-primary" />
            School Loans
          </h1>
          <p className="text-muted-foreground text-sm mt-1">
            Loans the school has collected from lenders — track repayments, interest, and other charges
          </p>
        </div>
        <Button onClick={openAddLoan}>
          <Plus className="h-4 w-4 mr-1" />
          Add Loan
        </Button>
      </div>

      {error && (
        <div className="flex items-center gap-2 rounded-lg border border-destructive/20 bg-destructive/5 px-4 py-3 text-sm text-destructive">
          <AlertCircle className="h-4 w-4 shrink-0" />
          {error}
          <button type="button" title="Dismiss error" className="ml-auto text-destructive/80 hover:text-destructive" onClick={() => setError(null)}>
            <XCircle className="h-4 w-4" />
          </button>
        </div>
      )}

      {/* Summary cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <Card>
          <CardContent className="pt-5">
            <p className="text-xs text-muted-foreground uppercase tracking-wide">Total Collected</p>
            <p className="text-xl font-bold mt-1">{formatCurrency(totalCollected)}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-5">
            <p className="text-xs text-muted-foreground uppercase tracking-wide">Outstanding (Payable)</p>
            <p className="text-xl font-bold mt-1 text-brand-accent">{formatCurrency(totalOutstanding)}</p>
            <p className="text-xs text-muted-foreground mt-0.5">Shown on Financial Position as Current Liability</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-5">
            <p className="text-xs text-muted-foreground uppercase tracking-wide">Repaid to Date</p>
            <p className="text-xl font-bold mt-1 text-income">{formatCurrency(totalCollected - totalOutstanding)}</p>
          </CardContent>
        </Card>
      </div>

      {loading ? (
        <p className="text-muted-foreground text-sm">Loading…</p>
      ) : (
        <>
          {/* Active loans */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base">Active Loans</CardTitle>
            </CardHeader>
            <CardContent>
              {active.length === 0 ? (
                <p className="text-sm text-muted-foreground py-4 text-center">
                  No active loans. Click "Add Loan" to record one.
                </p>
              ) : (
                <div className="space-y-4">
                  {active.map((loan) => {
                    const pct = progressPct(loan);
                    const expanded = expandedLoanId === loan.id;
                    return (
                      <div key={loan.id} className="rounded-lg border border-border bg-card overflow-hidden">
                        {/* Loan summary row */}
                        <div className="p-4 space-y-3">
                          <div className="flex items-start justify-between gap-3 flex-wrap">
                            <div className="flex-1 min-w-0">
                              <p className="font-semibold text-sm">{loan.lender_name}</p>
                              <p className="text-xs text-muted-foreground mt-0.5">
                                {loan.interest_rate}% interest{loan.notes ? ` · ${loan.notes}` : ''}
                              </p>
                            </div>
                            <div className="flex gap-1 shrink-0">
                              <button
                                type="button"
                                aria-label="Edit loan"
                                onClick={() => openEditLoan(loan)}
                                className="p-1.5 rounded hover:bg-accent text-muted-foreground hover:text-foreground"
                              >
                                <Pencil className="h-3.5 w-3.5" />
                              </button>
                              <button
                                type="button"
                                aria-label="Delete loan"
                                onClick={() => setDeleteLoanId(loan.id)}
                                className="p-1.5 rounded hover:bg-destructive/10 text-muted-foreground hover:text-destructive"
                              >
                                <Trash2 className="h-3.5 w-3.5" />
                              </button>
                            </div>
                          </div>

                          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
                            <div>
                              <p className="text-muted-foreground">Loan Amount</p>
                              <p className="font-medium">{formatCurrency(loan.loan_amount)}</p>
                            </div>
                            <div>
                              <p className="text-muted-foreground">Principal Repaid</p>
                              <p className="font-medium text-income">{formatCurrency(loan.loan_amount - loan.outstanding_today)}</p>
                            </div>
                            <div>
                              <p className="text-muted-foreground">Interest Paid</p>
                              <p className="font-medium text-expense">{formatCurrency(loan.total_interest_paid)}</p>
                            </div>
                            <div>
                              <p className="text-muted-foreground">Balance</p>
                              <p className="font-semibold text-brand-accent">{formatCurrency(loan.outstanding_today)}</p>
                            </div>
                          </div>

                          <div className="space-y-1">
                            <div className="h-2 rounded-full bg-muted overflow-hidden">
                              <div
                                className="h-full rounded-full bg-income transition-all"
                                role="presentation"
                                data-pct={pct}
                                ref={(el) => { if (el) el.style.width = `${pct}%`; }}
                              />
                            </div>
                            <p className="text-xs text-muted-foreground text-right">{pct}% repaid</p>
                          </div>

                          {/* Toggle payments */}
                          <button
                            type="button"
                            onClick={() => setExpandedLoanId(expanded ? null : loan.id)}
                            className="flex items-center gap-1 text-xs text-primary hover:underline"
                          >
                            {expanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
                            {loan.payments.length} payment{loan.payments.length !== 1 ? 's' : ''}
                          </button>
                        </div>

                        {/* Payments panel */}
                        {expanded && (
                          <div className="border-t border-border bg-muted/20 p-4 space-y-3">
                            <div className="flex items-center justify-between">
                              <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">Payment History</p>
                              <Button size="sm" variant="outline" onClick={() => openAddPayment(loan.id)}>
                                <Plus className="h-3.5 w-3.5 mr-1" />
                                Add Payment
                              </Button>
                            </div>

                            {loan.payments.length === 0 ? (
                              <p className="text-xs text-muted-foreground">No payments recorded yet.</p>
                            ) : (
                              <table className="w-full text-xs">
                                <thead>
                                  <tr className="text-muted-foreground border-b">
                                    <th className="text-left py-1.5 pr-3 font-medium">Date</th>
                                    <th className="text-right py-1.5 pr-3 font-medium">Total Paid</th>
                                    <th className="text-right py-1.5 pr-3 font-medium">Principal</th>
                                    <th className="text-right py-1.5 pr-3 font-medium">Interest</th>
                                    <th className="text-right py-1.5 pr-3 font-medium">Misc</th>
                                    <th className="text-left py-1.5 pr-3 font-medium">Status</th>
                                    <th className="py-1.5"><span className="sr-only">Actions</span></th>
                                  </tr>
                                </thead>
                                <tbody className="divide-y divide-border/50">
                                  {loan.payments.map((p) => (
                                    <tr key={p.id}>
                                      <td className="py-2 pr-3">{fmt(p.paid_date)}</td>
                                      <td className="py-2 pr-3 text-right font-medium text-income">{formatCurrency(p.amount_paid)}</td>
                                      <td className="py-2 pr-3 text-right">{formatCurrency(p.principal_paid)}</td>
                                      <td className="py-2 pr-3 text-right text-expense">{formatCurrency(p.interest_amount)}</td>
                                      <td className="py-2 pr-3 text-right text-expense">{formatCurrency(p.misc_amount)}</td>
                                      <td className="py-2 pr-3">
                                        {p.verified ? (
                                          <span
                                            className="inline-flex items-center gap-1 rounded-full bg-green-50 px-2 py-0.5 text-green-700 font-medium"
                                            title={p.matched_tx ? `Linked to tx #${p.matched_tx.id} — ${p.matched_tx.description}` : 'Verified'}
                                          >
                                            <BadgeCheck className="h-3 w-3" />
                                            Verified
                                          </span>
                                        ) : (
                                          <span className="text-muted-foreground/60">—</span>
                                        )}
                                      </td>
                                      <td className="py-2">
                                        <div className="flex gap-1 justify-end">
                                          <button
                                            type="button"
                                            aria-label="Edit payment"
                                            onClick={() => openEditPayment(loan.id, p)}
                                            className="p-1 rounded hover:bg-accent text-muted-foreground"
                                          >
                                            <Pencil className="h-3 w-3" />
                                          </button>
                                          <button
                                            type="button"
                                            aria-label="Delete payment"
                                            onClick={() => setDeletePayment({ loanId: loan.id, paymentId: p.id })}
                                            className="p-1 rounded hover:bg-destructive/10 text-muted-foreground hover:text-destructive"
                                          >
                                            <Trash2 className="h-3 w-3" />
                                          </button>
                                        </div>
                                      </td>
                                    </tr>
                                  ))}
                                </tbody>
                                <tfoot>
                                  <tr className="border-t font-semibold">
                                    <td className="py-2 text-muted-foreground">Totals</td>
                                    <td className="py-2 pr-3 text-right text-income">{formatCurrency(loan.total_paid)}</td>
                                    <td className="py-2 pr-3 text-right">{formatCurrency(loan.loan_amount - loan.outstanding_today)}</td>
                                    <td className="py-2 pr-3 text-right text-expense">{formatCurrency(loan.total_interest_paid)}</td>
                                    <td className="py-2 pr-3 text-right text-expense">{formatCurrency(loan.total_misc_paid)}</td>
                                    <td colSpan={2} />
                                  </tr>
                                </tfoot>
                              </table>
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </CardContent>
          </Card>

          {/* Repaid loans */}
          {repaid.length > 0 && (
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base text-muted-foreground">Fully Repaid / Inactive</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-2">
                  {repaid.map((loan) => (
                    <div key={loan.id} className="flex items-center justify-between rounded-lg border border-border/50 bg-muted/20 px-4 py-3 gap-3">
                      <div className="flex items-center gap-2 min-w-0">
                        <CheckCircle2 className="h-4 w-4 text-green-500 shrink-0" />
                        <div className="min-w-0">
                          <p className="text-sm font-medium truncate">{loan.lender_name}</p>
                          <p className="text-xs text-muted-foreground">
                            {formatCurrency(loan.loan_amount)} · {loan.payments.length} payments · collected {fmt(loan.collected_date)}
                          </p>
                        </div>
                      </div>
                      <div className="flex gap-1 shrink-0">
                        <button type="button" aria-label="Edit" onClick={() => openEditLoan(loan)}
                          className="p-1.5 rounded hover:bg-accent text-muted-foreground">
                          <Pencil className="h-3.5 w-3.5" />
                        </button>
                        <button type="button" aria-label="Delete" onClick={() => setDeleteLoanId(loan.id)}
                          className="p-1.5 rounded hover:bg-destructive/10 text-muted-foreground hover:text-destructive">
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}
        </>
      )}

      {/* ── Add/Edit Loan modal ────────────────────────────────────────────────── */}
      {showLoanForm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-md bg-card rounded-xl shadow-xl border border-border p-6 space-y-5 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-semibold">{editingLoan ? 'Edit School Loan' : 'Add School Loan'}</h2>
              <button type="button" aria-label="Close" onClick={() => setShowLoanForm(false)} className="text-muted-foreground hover:text-foreground">
                <XCircle className="h-5 w-5" />
              </button>
            </div>

            <div className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-foreground mb-1">Lender *</label>
                <input
                  type="text"
                  placeholder="e.g. Cooperative Society, Access Bank"
                  value={loanForm.lender_name}
                  onChange={(e) => setLoanForm((f) => ({ ...f, lender_name: e.target.value }))}
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
                />
              </div>

              <NumInput label="Loan Amount" value={loanForm.loan_amount} onChange={(n) => setLoanForm((f) => ({ ...f, loan_amount: n }))} required />

              <div>
                <label className="block text-xs font-medium text-foreground mb-1">Interest Rate (% per annum)</label>
                <input
                  type="number"
                  step="0.1"
                  min="0"
                  placeholder="0"
                  value={loanForm.interest_rate || ''}
                  onChange={(e) => setLoanForm((f) => ({ ...f, interest_rate: parseFloat(e.target.value) || 0 }))}
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
                />
                <p className="text-xs text-muted-foreground mt-1">Reference only — enter the actual interest paid per installment below.</p>
              </div>

              <div>
                <label className="block text-xs font-medium text-foreground mb-1">Date Collected *</label>
                <input
                  type="date"
                  title="Date the loan was collected"
                  value={loanForm.collected_date}
                  onChange={(e) => setLoanForm((f) => ({ ...f, collected_date: e.target.value }))}
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-foreground mb-1">Notes</label>
                <input
                  type="text"
                  placeholder="Optional — purpose of loan"
                  value={loanForm.notes ?? ''}
                  onChange={(e) => setLoanForm((f) => ({ ...f, notes: e.target.value }))}
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
                />
              </div>

              <div className="flex items-center gap-2">
                <input id="is_active" type="checkbox" checked={loanForm.is_active ?? true}
                  onChange={(e) => setLoanForm((f) => ({ ...f, is_active: e.target.checked }))}
                  className="rounded border-input" />
                <label htmlFor="is_active" className="text-sm">Active loan</label>
              </div>
            </div>

            <div className="flex justify-end gap-2 pt-2">
              <Button variant="outline" onClick={() => setShowLoanForm(false)} disabled={savingLoan}>Cancel</Button>
              <Button onClick={handleSaveLoan} disabled={savingLoan || !loanForm.lender_name.trim() || loanForm.loan_amount <= 0 || !loanForm.collected_date}>
                {savingLoan ? 'Saving…' : editingLoan ? 'Save Changes' : 'Add Loan'}
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* ── Add/Edit Payment modal ─────────────────────────────────────────────── */}
      {paymentLoanId !== null && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-md bg-card rounded-xl shadow-xl border border-border p-6 space-y-5 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-semibold">{editingPayment ? 'Edit Payment' : 'Record Payment'}</h2>
              <button
                type="button"
                aria-label="Close"
                onClick={() => { setPaymentLoanId(null); setEditingPayment(null); setMatchedTxs([]); }}
                className="text-muted-foreground hover:text-foreground"
              >
                <XCircle className="h-5 w-5" />
              </button>
            </div>

            <div className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-foreground mb-1">Payment Date *</label>
                <input
                  type="date"
                  title="Date payment was made"
                  value={paymentForm.paid_date}
                  onChange={(e) => handlePaymentDateChange(e.target.value)}
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
                />
              </div>

              {/* Transaction lookup */}
              {paymentForm.paid_date && (
                <div className="rounded-lg border border-border bg-muted/20 p-3 space-y-2">
                  <div className="flex items-center gap-1.5 text-xs font-semibold text-muted-foreground uppercase tracking-wide">
                    <LinkIcon className="h-3.5 w-3.5" />
                    Link to Transaction
                    {loadingTxs && <Loader2 className="h-3.5 w-3.5 animate-spin ml-1" />}
                  </div>

                  {!loadingTxs && matchedTxs.length === 0 && (
                    <p className="text-xs text-muted-foreground">
                      No expense transactions found for this lender in this month. You can still record the payment manually.
                    </p>
                  )}

                  {!loadingTxs && matchedTxs.length > 0 && (
                    <div className="space-y-1.5">
                      {matchedTxs.map((tx) => {
                        const isSelected = paymentForm.transaction_id === tx.id;
                        return (
                          <button
                            key={tx.id}
                            type="button"
                            onClick={() => handleSelectTx(tx)}
                            className={`w-full text-left rounded-md border px-3 py-2 text-xs transition-colors ${
                              isSelected
                                ? 'border-primary bg-primary/10 text-primary'
                                : 'border-border hover:border-primary hover:bg-accent'
                            }`}
                          >
                            <div className="flex items-center justify-between gap-2">
                              <span className="truncate font-medium">{tx.description || tx.vendor || 'Transaction'}</span>
                              <span className="shrink-0 font-semibold">{formatCurrency(tx.amount)}</span>
                            </div>
                            <div className="flex items-center justify-between mt-0.5 text-muted-foreground">
                              <span>{new Date(tx.date).toLocaleDateString('en-NG', { day: '2-digit', month: 'short', year: 'numeric' })}</span>
                              {isSelected && (
                                <span className="flex items-center gap-0.5 text-primary font-medium">
                                  <BadgeCheck className="h-3 w-3" /> Selected
                                </span>
                              )}
                            </div>
                          </button>
                        );
                      })}
                      {paymentForm.transaction_id && (
                        <button
                          type="button"
                          onClick={() => setPaymentForm((f) => ({ ...f, transaction_id: null }))}
                          className="text-xs text-muted-foreground hover:text-foreground underline"
                        >
                          Clear selection
                        </button>
                      )}
                    </div>
                  )}
                </div>
              )}

              <NumInput
                label="Total Amount Paid *"
                value={paymentForm.amount_paid}
                onChange={(n) => setPaymentForm((f) => ({ ...f, amount_paid: n }))}
                required
              />

              <div className="grid grid-cols-2 gap-3">
                <NumInput
                  label="Of which: Interest"
                  value={paymentForm.interest_amount ?? 0}
                  onChange={(n) => setPaymentForm((f) => ({ ...f, interest_amount: n }))}
                />
                <NumInput
                  label="Of which: Misc/Other"
                  value={paymentForm.misc_amount ?? 0}
                  onChange={(n) => setPaymentForm((f) => ({ ...f, misc_amount: n }))}
                />
              </div>

              <div className="rounded-md bg-muted/30 px-3 py-2 flex items-center justify-between text-xs">
                <span className="text-muted-foreground">Goes toward principal</span>
                <span className={`font-semibold ${paymentPrincipal < 0 ? 'text-destructive' : 'text-income'}`}>
                  {formatCurrency(paymentPrincipal)}
                </span>
              </div>
              {paymentPrincipal < 0 && (
                <p className="text-xs text-destructive">Interest + misc cannot exceed the total amount paid.</p>
              )}

              <div>
                <label className="block text-xs font-medium text-foreground mb-1">Notes</label>
                <input
                  type="text"
                  placeholder="e.g. Monthly installment"
                  value={paymentForm.notes ?? ''}
                  onChange={(e) => setPaymentForm((f) => ({ ...f, notes: e.target.value }))}
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
                />
              </div>
            </div>

            <div className="flex justify-end gap-2 pt-2">
              <Button variant="outline" onClick={() => { setPaymentLoanId(null); setEditingPayment(null); setMatchedTxs([]); }} disabled={savingPayment}>Cancel</Button>
              <Button onClick={handleSavePayment} disabled={savingPayment || paymentForm.amount_paid <= 0 || !paymentForm.paid_date || paymentPrincipal < 0}>
                {savingPayment ? 'Saving…' : editingPayment ? 'Save Changes' : 'Record Payment'}
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Delete loan confirmation */}
      {deleteLoanId !== null && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-sm bg-card rounded-xl shadow-xl border border-border p-6 space-y-4">
            <h2 className="text-base font-semibold">Delete School Loan?</h2>
            <p className="text-sm text-muted-foreground">This will permanently remove the loan and all its payment records.</p>
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => setDeleteLoanId(null)}>Cancel</Button>
              <Button variant="destructive" onClick={() => handleDeleteLoan(deleteLoanId)}>Delete</Button>
            </div>
          </div>
        </div>
      )}

      {/* Delete payment confirmation */}
      {deletePayment !== null && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-sm bg-card rounded-xl shadow-xl border border-border p-6 space-y-4">
            <h2 className="text-base font-semibold">Remove Payment?</h2>
            <p className="text-sm text-muted-foreground">This payment record will be deleted and the balance will increase accordingly.</p>
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => setDeletePayment(null)}>Cancel</Button>
              <Button variant="destructive" onClick={handleDeletePayment}>Delete</Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
