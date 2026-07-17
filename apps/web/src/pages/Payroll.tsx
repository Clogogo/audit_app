import { useEffect, useState } from 'react';
import {
  Calculator,
  ChevronLeft,
  ChevronRight,
  CheckCircle2,
  AlertCircle,
  Info,
  Loader2,
  Pencil,
} from 'lucide-react';
import { computePayroll, processPayroll, resetPayroll } from '../api/client';
import type { PayrollEntryOut, PayrollLine, PayrollLineIn } from '../api/types';
import { Button } from '../components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { TransactionPickerModal } from '../components/TransactionPickerModal';
import { formatCurrency } from '../lib/utils';

const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
];

function NumCell({
  value, onChange, disabled,
}: { value: number; onChange: (n: number) => void; disabled: boolean }) {
  const [raw, setRaw] = useState('');
  const [focused, setFocused] = useState(false);
  return (
    <input
      type="text"
      inputMode="numeric"
      disabled={disabled}
      title="Amount"
      placeholder="0"
      value={focused ? raw : (value === 0 ? '' : value.toLocaleString('en-NG'))}
      onFocus={() => { setFocused(true); setRaw(value === 0 ? '' : String(value)); }}
      onChange={(e) => {
        const d = e.target.value.replace(/[^0-9]/g, '');
        setRaw(d);
        onChange(d === '' ? 0 : parseInt(d, 10));
      }}
      onBlur={() => setFocused(false)}
      className="w-28 rounded border border-input bg-background px-2 py-1 text-xs text-right focus:outline-none focus:ring-1 focus:ring-ring disabled:opacity-50 disabled:cursor-not-allowed"
    />
  );
}

export function Payroll() {
  const today = new Date();
  const [year, setYear] = useState(today.getFullYear());
  const [month, setMonth] = useState(today.getMonth() + 1);
  const [lines, setLines] = useState<PayrollLine[]>([]);
  const [loading, setLoading] = useState(false);
  const [processing, setProcessing] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [showResetConfirm, setShowResetConfirm] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [missingTx, setMissingTx] = useState<string[]>([]);
  const [success, setSuccess] = useState<string | null>(null);
  // Notices about real paid amounts (excess folded into bonus / underpayment)
  // — survives the post-process reload, cleared when the month changes.
  const [payNotices, setPayNotices] = useState<string[]>([]);

  // Per-row overrides for gross, bonus, and other_deductions
  const [overrides, setOverrides] = useState<Record<number, { gross: number; bonus: number; other: number }>>({});
  // Per-row skip flag — skipped rows are excluded from totals and from processing
  const [skipped, setSkipped] = useState<Record<number, boolean>>({});
  // Manual transaction link for a missing staff member, staged until the next submit
  const [manualLink, setManualLink] = useState<Record<number, { transactionId: number; vendor: string }>>({});
  // Staff full_name currently showing the transaction picker, if any
  const [linkingFor, setLinkingFor] = useState<string | null>(null);

  const load = (preserveEdits = false) => {
    setLoading(true);
    setError(null);
    setMissingTx([]);
    setSuccess(null);
    computePayroll(year, month)
      .then((data) => {
        setLines(data);
        if (!preserveEdits) {
          // Fresh month load — initialise overrides from server values
          const init: Record<number, { gross: number; bonus: number; other: number }> = {};
          data.forEach((l) => { init[l.staff_id] = { gross: l.gross_salary, bonus: l.bonus, other: l.other_deductions }; });
          setOverrides(init);
        } else {
          // After reset — keep existing overrides; only fill in any new staff
          setOverrides((prev) => {
            const updated = { ...prev };
            data.forEach((l) => {
              if (!updated[l.staff_id]) {
                updated[l.staff_id] = { gross: l.gross_salary, bonus: l.bonus, other: l.other_deductions };
              }
            });
            return updated;
          });
        }
      })
      .catch(() => setError('Failed to load payroll data'))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    const stored = localStorage.getItem(`payroll_skip_${year}_${month}`);
    setSkipped(stored ? (JSON.parse(stored) as Record<number, boolean>) : {});
    setPayNotices([]);
    load();
  }, [year, month]);

  // Notify how each entry's real bank amount compared to the computed net:
  // excess payments were captured into Bonus; underpayments are flagged only.
  const buildPayNotices = (entries: PayrollEntryOut[]) => {
    const notices: string[] = [];
    for (const e of entries) {
      const excess = e.bonus_excess ?? 0;
      if (excess > 0.009) {
        notices.push(
          `${e.full_name}: bank paid ${formatCurrency(e.paid_amount ?? 0)} — ` +
          `${formatCurrency(excess)} above the computed net was added to Bonus.`
        );
      } else if (e.paid_amount != null && e.paid_amount < e.net_salary - 0.009) {
        notices.push(
          `${e.full_name}: bank paid ${formatCurrency(e.paid_amount)}, which is ` +
          `${formatCurrency(e.net_salary - e.paid_amount)} less than the computed net of ${formatCurrency(e.net_salary)}.`
        );
      }
    }
    setPayNotices(notices);
  };

  const isSkipped = (l: PayrollLine) => !l.is_paid && !!skipped[l.staff_id];

  const toggleSkip = (staffId: number) => {
    setSkipped((s) => {
      const updated = { ...s, [staffId]: !s[staffId] };
      localStorage.setItem(`payroll_skip_${year}_${month}`, JSON.stringify(updated));
      return updated;
    });
    setError(null);
    setMissingTx([]);
  };

  const skipMissingAndProcess = async () => {
    // Build updated skipped map using current missingTx names — a staff
    // member who was manually linked should be processed, not skipped.
    const newSkipped = { ...skipped };
    lines
      .filter((l) => missingTx.includes(l.full_name) && !manualLink[l.staff_id])
      .forEach((l) => { newSkipped[l.staff_id] = true; });
    setSkipped(newSkipped);
    localStorage.setItem(`payroll_skip_${year}_${month}`, JSON.stringify(newSkipped));
    setError(null);
    setMissingTx([]);

    // Compute payload without waiting for state flush
    const payload: PayrollLineIn[] = lines
      .filter((l) => !l.is_paid && !newSkipped[l.staff_id])
      .map((l) => ({
        staff_id: l.staff_id,
        gross_salary: getGross(l),
        bonus: getBonus(l),
        other_deductions: getOther(l),
        transaction_id: manualLink[l.staff_id]?.transactionId,
      }));

    if (payload.length === 0) return;

    setProcessing(true);
    try {
      const entries = await processPayroll(year, month, payload);
      buildPayNotices(entries);
      setSuccess(`${MONTHS[month - 1]} ${year} payroll processed and linked to bank transactions.`);
      setManualLink({});
      load(true); // preserve overrides and skipped state
    } catch (err: unknown) {
      const axiosErr = err as { response?: { status?: number; data?: { detail?: { message?: string; missing?: string[] } } } };
      const detail = axiosErr?.response?.data?.detail;
      if (axiosErr?.response?.status === 422 && detail?.missing) {
        setError(detail.message ?? 'Cannot process payroll');
        setMissingTx(detail.missing);
      } else {
        setError('Failed to process payroll');
      }
    } finally {
      setProcessing(false);
    }
  };

  const getGross = (l: PayrollLine) => overrides[l.staff_id]?.gross ?? l.gross_salary;
  const getBonus = (l: PayrollLine) => overrides[l.staff_id]?.bonus ?? l.bonus;
  const getOther = (l: PayrollLine) => overrides[l.staff_id]?.other ?? l.other_deductions;
  const getNet   = (l: PayrollLine) => Math.max(0, getGross(l) + getBonus(l) - l.loan_deduction - l.advance_deduction - getOther(l));

  // Totals exclude skipped rows
  const activeLines = lines.filter((l) => !isSkipped(l));
  const totalGross   = activeLines.reduce((s, l) => s + getGross(l), 0);
  const totalBonus   = activeLines.reduce((s, l) => s + getBonus(l), 0);
  const totalLoan    = activeLines.reduce((s, l) => s + l.loan_deduction, 0);
  const totalAdvance = activeLines.reduce((s, l) => s + l.advance_deduction, 0);
  const totalOther   = activeLines.reduce((s, l) => s + getOther(l), 0);
  const totalNet     = activeLines.reduce((s, l) => s + getNet(l), 0);

  const skippedCount = lines.filter((l) => isSkipped(l)).length;
  // Payroll is "fully processed" when every non-skipped row is paid
  const isProcessed = activeLines.length > 0 && activeLines.every((l) => l.is_paid);
  const hasAnyProcessed = lines.some((l) => l.is_paid);
  // Rows still pending (not paid, not skipped)
  const pendingLines = activeLines.filter((l) => !l.is_paid);

  const handleProcess = async () => {
    setProcessing(true);
    setError(null);
    setMissingTx([]);
    try {
      // Only process pending, non-skipped rows
      const payload: PayrollLineIn[] = pendingLines.map((l) => ({
        staff_id: l.staff_id,
        gross_salary: getGross(l),
        bonus: getBonus(l),
        other_deductions: getOther(l),
        transaction_id: manualLink[l.staff_id]?.transactionId,
      }));
      const entries = await processPayroll(year, month, payload);
      buildPayNotices(entries);
      setSuccess(`${MONTHS[month - 1]} ${year} payroll processed and linked to bank transactions.`);
      setManualLink({});
      load(true); // preserve overrides and skipped state
    } catch (err: unknown) {
      const axiosErr = err as { response?: { status?: number; data?: { detail?: { message?: string; missing?: string[]; hint?: string } } } };
      const detail = axiosErr?.response?.data?.detail;
      if (axiosErr?.response?.status === 422 && detail?.missing) {
        setError(detail.message ?? 'Cannot process payroll');
        setMissingTx(detail.missing);
      } else {
        setError('Failed to process payroll');
      }
    } finally {
      setProcessing(false);
    }
  };

  const handleReset = async () => {
    setResetting(true);
    setShowResetConfirm(false);
    try {
      await resetPayroll(year, month);
      setSuccess(`${MONTHS[month - 1]} ${year} payroll is now editable.`);
      localStorage.removeItem(`payroll_skip_${year}_${month}`);
      setSkipped({});
      load(true); // preserve overrides but reset skipped state
    } catch {
      setError('Failed to reset payroll');
    } finally {
      setResetting(false);
    }
  };

  const prevMonth = () => {
    if (month === 1) { setYear((y) => y - 1); setMonth(12); }
    else setMonth((m) => m - 1);
  };
  const nextMonth = () => {
    if (month === 12) { setYear((y) => y + 1); setMonth(1); }
    else setMonth((m) => m + 1);
  };

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Calculator className="h-6 w-6 text-primary" />
            Payroll Calculator
          </h1>
          <p className="text-muted-foreground text-sm mt-1">
            Monthly payroll — loan deductions are auto-calculated per staff member
          </p>
        </div>

        <div className="flex items-center gap-3 flex-wrap">
          {/* Month navigator */}
          <div className="flex items-center gap-2">
            <button
              type="button"
              aria-label="Previous month"
              onClick={prevMonth}
              className="p-1.5 rounded-md border border-input hover:bg-accent"
            >
              <ChevronLeft className="h-4 w-4" />
            </button>
            <span className="text-sm font-semibold min-w-[130px] text-center">
              {MONTHS[month - 1]} {year}
            </span>
            <button
              type="button"
              aria-label="Next month"
              onClick={nextMonth}
              className="p-1.5 rounded-md border border-input hover:bg-accent"
            >
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-destructive/20 bg-destructive/5 px-4 py-3 text-sm text-destructive space-y-2">
          <div className="flex items-center gap-2">
            <AlertCircle className="h-4 w-4 shrink-0" />
            <span>{error}</span>
          </div>
          {missingTx.length > 0 && (
            <div className="pl-6 space-y-2">
              <p className="text-xs font-semibold text-destructive">Missing salary transactions for:</p>
              <ul className="text-xs space-y-1">
                {missingTx.map((name, idx) => {
                  const staffLine = lines.find((l) => l.full_name === name);
                  const linked = staffLine ? manualLink[staffLine.staff_id] : undefined;
                  return (
                    <li key={`${name}-${staffLine?.staff_id ?? idx}`} className="flex items-center gap-2">
                      <span>{name}</span>
                      {linked ? (
                        <span className="inline-flex items-center gap-1.5">
                          <span className="text-green-700 dark:text-green-400">✓ linked to {linked.vendor}</span>
                          <button
                            type="button"
                            onClick={() => staffLine && setManualLink((m) => {
                              const updated = { ...m };
                              delete updated[staffLine.staff_id];
                              return updated;
                            })}
                            className="text-muted-foreground underline hover:no-underline"
                          >
                            Undo
                          </button>
                        </span>
                      ) : (
                        <button
                          type="button"
                          onClick={() => setLinkingFor(name)}
                          className="text-primary underline hover:no-underline"
                        >
                          Link transaction…
                        </button>
                      )}
                    </li>
                  );
                })}
              </ul>
              <p className="text-xs text-destructive/90">
                Import the bank statement for {MONTHS[month - 1]} {year} first, link an existing transaction above, or skip these staff members to process the rest now.
              </p>
              {(() => {
                const unresolvedCount = missingTx.filter((name) => {
                  const staffLine = lines.find((l) => l.full_name === name);
                  return !staffLine || !manualLink[staffLine.staff_id];
                }).length;
                return (
                  <button
                    type="button"
                    onClick={skipMissingAndProcess}
                    disabled={processing}
                    className="inline-flex items-center gap-1.5 rounded-md bg-destructive px-3 py-1.5 text-xs font-medium text-destructive-foreground hover:bg-destructive/90 disabled:opacity-50"
                  >
                    {processing ? <Loader2 className="h-3 w-3 animate-spin" /> : null}
                    {unresolvedCount > 0
                      ? `Skip ${unresolvedCount} staff & process the rest`
                      : 'Process with linked transactions'}
                  </button>
                );
              })()}
            </div>
          )}
        </div>
      )}

      {linkingFor && (() => {
        const staffLine = lines.find((l) => l.full_name === linkingFor);
        const monthStart = `${year}-${String(month).padStart(2, '0')}-01`;
        const monthEnd = `${year}-${String(month).padStart(2, '0')}-${String(new Date(year, month, 0).getDate()).padStart(2, '0')}`;
        const excludeIds = Object.values(manualLink).map((m) => m.transactionId);
        return (
          <TransactionPickerModal
            title={`Link a transaction for ${linkingFor}`}
            category="Salary and Wages"
            startDate={monthStart}
            endDate={monthEnd}
            excludeTransactionIds={excludeIds}
            onClose={() => setLinkingFor(null)}
            onSelect={(t) => {
              if (staffLine) {
                setManualLink((m) => ({ ...m, [staffLine.staff_id]: { transactionId: t.id, vendor: t.vendor || t.description } }));
              }
              setLinkingFor(null);
            }}
          />
        );
      })()}

      {success && (
        <div className="flex items-center gap-2 rounded-lg border border-green-300 bg-green-50 dark:border-green-900/50 dark:bg-green-950/20 px-4 py-3 text-sm text-green-700 dark:text-green-300">
          <CheckCircle2 className="h-4 w-4 shrink-0" />
          {success}
        </div>
      )}

      {payNotices.length > 0 && (
        <div className="rounded-lg border border-amber-300 bg-amber-50 dark:border-amber-900/50 dark:bg-amber-950/20 px-4 py-3 text-sm text-amber-800 dark:text-amber-200">
          <div className="flex items-center gap-2 font-medium mb-1">
            <Info className="h-4 w-4 shrink-0" />
            Real paid amounts differed from the computed net pay:
          </div>
          <ul className="list-disc list-inside space-y-0.5 text-xs">
            {payNotices.map((n, i) => <li key={i}>{n}</li>)}
          </ul>
        </div>
      )}

      {isProcessed && (
        <div className="flex items-center gap-2 rounded-lg border border-secondary bg-secondary/50 px-4 py-3 text-sm text-secondary-foreground">
          <CheckCircle2 className="h-4 w-4 shrink-0 text-primary" />
          Payroll for {MONTHS[month - 1]} {year} has been processed and linked to bank transactions.
        </div>
      )}

      {/* Summary cards */}
      <div className="grid grid-cols-2 sm:grid-cols-6 gap-4">
        <Card>
          <CardContent className="pt-4 pb-4">
            <p className="text-xs text-muted-foreground uppercase tracking-wide">Total Gross</p>
            <p className="text-lg font-bold mt-0.5">{formatCurrency(totalGross)}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4 pb-4">
            <p className="text-xs text-muted-foreground uppercase tracking-wide">Bonuses</p>
            <p className="text-lg font-bold mt-0.5 text-income">{formatCurrency(totalBonus)}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4 pb-4">
            <p className="text-xs text-muted-foreground uppercase tracking-wide">Loan Deductions</p>
            <p className="text-lg font-bold mt-0.5 text-expense">{formatCurrency(totalLoan)}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4 pb-4">
            <p className="text-xs text-muted-foreground uppercase tracking-wide">Advance Deductions</p>
            <p className="text-lg font-bold mt-0.5 text-expense">{formatCurrency(totalAdvance)}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4 pb-4">
            <p className="text-xs text-muted-foreground uppercase tracking-wide">Other Deductions</p>
            <p className="text-lg font-bold mt-0.5 text-expense">{formatCurrency(totalOther)}</p>
          </CardContent>
        </Card>
        {/* Total Net Pay — destination figure of the calculation, visually distinct */}
        <Card className="bg-primary text-primary-foreground border-0">
          <CardContent className="pt-4 pb-4">
            <p className="text-xs text-primary-foreground/70 uppercase tracking-wide">Total Net Pay</p>
            <p className="text-lg font-bold mt-0.5 font-display">{formatCurrency(totalNet)}</p>
          </CardContent>
        </Card>
      </div>

      {/* Payroll table */}
      <Card>
        <CardHeader className="pb-3 flex-row items-center justify-between space-y-0">
          <CardTitle className="text-base">{MONTHS[month - 1]} {year} Payroll</CardTitle>
          <div className="flex gap-2">
            {isProcessed && lines.length > 0 && (
              <Button variant="outline" size="sm" onClick={() => setShowResetConfirm(true)} disabled={resetting}>
                <Pencil className="h-3.5 w-3.5 mr-1.5" />
                Edit Payroll
              </Button>
            )}
            {!isProcessed && pendingLines.length > 0 && (
              <Button onClick={handleProcess} disabled={processing} size="sm">
                {processing
                  ? <><Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />Processing…</>
                  : `Process Payroll${skippedCount > 0 ? ` (${pendingLines.length} staff)` : ''}`}
              </Button>
            )}
          </div>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="flex items-center gap-2 py-6 justify-center text-muted-foreground text-sm">
              <Loader2 className="h-4 w-4 animate-spin" />
              Loading payroll data…
            </div>
          ) : lines.length === 0 ? (
            <div className="py-8 text-center space-y-2">
              <p className="text-sm text-muted-foreground">No active staff found.</p>
              <p className="text-xs text-muted-foreground">Add staff members in Staff → Staff Directory first.</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-xs text-muted-foreground">
                    <th className="text-left py-2 pr-3 font-medium">Name</th>
                    <th className="text-left py-2 pr-3 font-medium">Role</th>
                    <th className="text-right py-2 pr-3 font-medium">Gross Salary</th>
                    <th className="text-right py-2 pr-3 font-medium">Bonus</th>
                    <th className="text-right py-2 pr-3 font-medium">Loan Deduction</th>
                    <th className="text-right py-2 pr-3 font-medium">Advance Deduction</th>
                    <th className="text-right py-2 pr-3 font-medium">Other Deductions</th>
                    <th className="text-right py-2 pr-3 font-medium">Net Pay</th>
                    <th className="text-right py-2 pr-3 font-medium">Amount Paid</th>
                    <th className="text-center py-2 font-medium">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {lines.map((l) => {
                    const skippedRow = isSkipped(l);
                    const rowDisabled = l.is_paid || skippedRow;
                    return (
                      <tr
                        key={l.staff_id}
                        className={
                          l.is_paid ? 'bg-green-50/30 dark:bg-green-950/10' :
                          skippedRow ? 'opacity-40 bg-muted/10' : ''
                        }
                      >
                        <td className="py-3 pr-3 font-medium">{l.full_name}</td>
                        <td className="py-3 pr-3 text-muted-foreground text-xs">{l.role || '—'}</td>
                        <td className="py-3 pr-3 text-right">
                          {rowDisabled ? (
                            <span className={skippedRow ? 'line-through text-muted-foreground' : ''}>
                              {formatCurrency(getGross(l))}
                            </span>
                          ) : (
                            <NumCell
                              value={getGross(l)}
                              onChange={(n) => setOverrides((o) => ({ ...o, [l.staff_id]: { ...o[l.staff_id], gross: n } }))}
                              disabled={false}
                            />
                          )}
                        </td>
                        <td className="py-3 pr-3 text-right">
                          {rowDisabled ? (
                            <span className={skippedRow ? 'line-through text-muted-foreground' : (getBonus(l) > 0 ? 'text-income font-medium' : 'text-muted-foreground')}>
                              {getBonus(l) > 0 ? formatCurrency(getBonus(l)) : '—'}
                            </span>
                          ) : (
                            <NumCell
                              value={getBonus(l)}
                              onChange={(n) => setOverrides((o) => ({ ...o, [l.staff_id]: { ...o[l.staff_id], bonus: n } }))}
                              disabled={false}
                            />
                          )}
                        </td>
                        <td className="py-3 pr-3 text-right text-expense font-medium">
                          {l.loan_deduction > 0 ? `(${formatCurrency(l.loan_deduction)})` : '—'}
                        </td>
                        <td className="py-3 pr-3 text-right text-expense font-medium">
                          {l.advance_deduction > 0 ? `(${formatCurrency(l.advance_deduction)})` : '—'}
                        </td>
                        <td className="py-3 pr-3 text-right">
                          {rowDisabled ? (
                            <span>{getOther(l) > 0 ? `(${formatCurrency(getOther(l))})` : '—'}</span>
                          ) : (
                            <NumCell
                              value={getOther(l)}
                              onChange={(n) => setOverrides((o) => ({ ...o, [l.staff_id]: { ...o[l.staff_id], other: n } }))}
                              disabled={false}
                            />
                          )}
                        </td>
                        <td className={`py-3 pr-3 text-right font-semibold ${skippedRow ? 'line-through text-muted-foreground' : 'text-primary'}`}>
                          {formatCurrency(getNet(l))}
                        </td>
                        <td className="py-3 pr-3 text-right">
                          {l.is_paid && l.paid_amount != null ? (
                            Math.abs(l.paid_amount - l.net_salary) > 0.009 ? (
                              <span
                                className="inline-flex items-center gap-1 font-semibold text-amber-600 dark:text-amber-400"
                                title={`Bank transaction amount differs from computed net pay (${formatCurrency(l.net_salary)})`}
                              >
                                <AlertCircle className="h-3.5 w-3.5" />
                                {formatCurrency(l.paid_amount)}
                              </span>
                            ) : (
                              <span className="font-semibold">{formatCurrency(l.paid_amount)}</span>
                            )
                          ) : (
                            <span className="text-muted-foreground">—</span>
                          )}
                        </td>
                        <td className="py-3 text-center">
                          {l.is_paid ? (
                            <span className="inline-flex items-center gap-1 text-xs text-green-700 bg-green-100 dark:text-green-300 dark:bg-green-950/40 px-2 py-0.5 rounded-full">
                              <CheckCircle2 className="h-3 w-3" />
                              Paid
                            </span>
                          ) : skippedRow ? (
                            <div className="flex flex-col items-center gap-1">
                              <span className="inline-flex items-center gap-1 text-xs text-muted-foreground bg-muted px-2 py-0.5 rounded-full">
                                Skipped
                              </span>
                              <button
                                type="button"
                                onClick={() => toggleSkip(l.staff_id)}
                                className="text-xs text-primary underline hover:no-underline"
                              >
                                Undo
                              </button>
                            </div>
                          ) : (
                            <div className="flex flex-col items-center gap-1">
                              <span className="text-xs text-muted-foreground">Pending</span>
                              <button
                                type="button"
                                onClick={() => toggleSkip(l.staff_id)}
                                className="text-xs text-orange-600 underline hover:no-underline"
                              >
                                Skip
                              </button>
                            </div>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
                <tfoot>
                  <tr className="border-t font-semibold bg-muted/20">
                    <td colSpan={2} className="py-3 pr-3 text-xs text-muted-foreground">
                      TOTAL{skippedCount > 0 ? ` (excl. ${skippedCount} skipped)` : ''}
                    </td>
                    <td className="py-3 pr-3 text-right">{formatCurrency(totalGross)}</td>
                    <td className="py-3 pr-3 text-right text-income">
                      {totalBonus > 0 ? formatCurrency(totalBonus) : '—'}
                    </td>
                    <td className="py-3 pr-3 text-right text-expense">
                      {totalLoan > 0 ? `(${formatCurrency(totalLoan)})` : '—'}
                    </td>
                    <td className="py-3 pr-3 text-right text-expense">
                      {totalAdvance > 0 ? `(${formatCurrency(totalAdvance)})` : '—'}
                    </td>
                    <td className="py-3 pr-3 text-right text-expense">
                      {totalOther > 0 ? `(${formatCurrency(totalOther)})` : '—'}
                    </td>
                    <td className="py-3 pr-3 text-right text-primary">{formatCurrency(totalNet)}</td>
                    <td />
                  </tr>
                </tfoot>
              </table>
            </div>
          )}

          {!loading && lines.length > 0 && !isProcessed && (
            <div className="mt-4 flex items-start gap-2 rounded-lg bg-muted/30 border border-border px-4 py-3 text-xs text-muted-foreground">
              <Info className="h-3.5 w-3.5 shrink-0 mt-0.5" />
              <span>
                Adjust gross salary and bonuses before processing. Loan deductions are calculated automatically.{' '}
                <strong className="text-foreground">Before clicking "Process Payroll"</strong>, import the bank
                statement for this month — salary payments in the statement are used to verify and link each staff
                member's transaction.
              </span>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Reset confirmation */}
      {showResetConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-sm bg-card rounded-xl shadow-xl border border-border p-6 space-y-4">
            <h2 className="text-base font-semibold">Edit {MONTHS[month - 1]} {year} Payroll?</h2>
            <p className="text-sm text-muted-foreground">
              This will mark the month as <strong>unpaid</strong> so you can adjust values and re-process.
              The existing salary transactions will remain but the "Paid" status will be cleared.
            </p>
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => setShowResetConfirm(false)}>Cancel</Button>
              <Button onClick={handleReset}>
                <Pencil className="h-3.5 w-3.5 mr-1.5" />
                Yes, Edit Payroll
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
