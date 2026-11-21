import { useState } from 'react';
import type { PayrollReconcileResult, ReconcileStatus } from '../../api/types';
import type { StaffMemberIn } from '../../api/types';
import { formatCurrency } from '../../lib/utils';
import { Card, CardContent, CardHeader, CardTitle } from '../ui/card';

const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
];

const STATUS_STYLES: Record<ReconcileStatus, { label: string; className: string }> = {
  matched: { label: 'Matched', className: 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300' },
  underpaid: { label: 'Underpaid', className: 'bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300' },
  overpaid: { label: 'Overpaid', className: 'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300' },
  not_paid: { label: 'Not paid', className: 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300' },
};

function StatusBadge({ status }: { status: ReconcileStatus }) {
  const { label, className } = STATUS_STYLES[status];
  return <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${className}`}>{label}</span>;
}

function SummaryTile({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="rounded-lg border p-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={`text-lg font-semibold ${tone ?? ''}`}>{value}</p>
    </div>
  );
}

interface ReconcileResultsProps {
  result: PayrollReconcileResult;
  /** Create a staff record for a matched schedule row that is not linked to the directory. */
  onAddStaff?: (staff: StaffMemberIn) => Promise<void>;
  /** the schedule pays more than the directory expects: record the difference as a bonus */
  onAddBonus?: (staffId: number, amount: number) => void;
  /** the schedule pays less than the directory expects: record the difference as an other deduction */
  onAddDeduction?: (staffId: number, amount: number) => void;
}

export function ReconcileResults({ result, onAddStaff, onAddBonus, onAddDeduction }: ReconcileResultsProps) {
  const [staffToAdd, setStaffToAdd] = useState<StaffMemberIn | null>(null);
  const [scheduleName, setScheduleName] = useState('');
  const [staffError, setStaffError] = useState<string | null>(null);
  const [savingStaff, setSavingStaff] = useState(false);
  const { summary, lines } = result;
  const problemRows = result.skipped_rows.filter((r) => !r.ignored);
  const ignoredRows = result.skipped_rows.filter((r) => r.ignored);
  const attention = summary.underpaid + summary.overpaid + summary.not_paid;
  const outOfSync = lines.filter((l) => l.in_sync === false).length;
  const accountFixes = lines.filter((l) => l.staff_id != null && l.paid_account && (l.account_check === 'missing' || l.account_check === 'differs'));
  const suggestions = lines.filter((l) => l.status === 'not_paid' && l.suggested_payments.length > 0);
  const duplicates = lines.filter((l) => l.extra_payment_ids.length > 0).length;
  const gap = summary.paid_total - summary.expected_total;

  const prepareStaff = (line: PayrollReconcileResult['lines'][number]) => {
    setScheduleName(line.name);
    setStaffError(null);
    setStaffToAdd({
      full_name: line.paid_to?.trim() || line.name,
      role: '',
      bank_name: line.paid_bank ?? '',
      account_number: line.paid_account ?? '',
      monthly_gross: 0,
      start_date: null,
      end_date: null,
      is_active: true,
      notes: '',
    });
  };

  const saveStaff = async () => {
    if (!staffToAdd || !onAddStaff || !staffToAdd.full_name.trim() || (staffToAdd.monthly_gross ?? 0) <= 0) return;
    setSavingStaff(true);
    setStaffError(null);
    try {
      await onAddStaff({ ...staffToAdd, full_name: staffToAdd.full_name.trim() });
      setStaffToAdd(null);
    } catch (error) {
      setStaffError(error instanceof Error ? error.message : 'Could not add staff member.');
    } finally {
      setSavingStaff(false);
    }
  };

  return (
    <>
    <details className="rounded-lg border bg-card">
      <summary className="cursor-pointer px-4 py-3 text-sm font-medium">
        Schedule vs bank — {MONTHS[result.month - 1]} {result.year}: {summary.matched} of {summary.rows} matched
        {attention > 0 && ` · ${attention} need attention`}
        {accountFixes.length > 0 && ` · ${accountFixes.length} bank account${accountFixes.length === 1 ? '' : 's'} differ from the directory`}
        {duplicates > 0 && ` · ${duplicates} possible duplicate payment${duplicates === 1 ? '' : 's'}`}
        {outOfSync > 0 && ` · ${outOfSync} total${outOfSync === 1 ? '' : 's'} differ from the staff directory`}
        {result.unlinked_staff.length > 0 && ` · ${result.unlinked_staff.length} staff not on the schedule`}
        {result.saved_at && <span className="font-normal text-muted-foreground"> · saved {new Date(result.saved_at + 'Z').toLocaleString()}</span>}
      </summary>
      <div className="space-y-4 px-4 pb-4">
        {result.notes.length > 0 && (
          <div role="note" className="rounded-lg border border-blue-300 bg-blue-50 px-4 py-3 text-sm text-blue-900 dark:bg-blue-900/20 dark:text-blue-200">
            {result.notes.map((n) => <p key={n}>{n}</p>)}
          </div>
        )}
        {problemRows.length > 0 && (
          <div className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:bg-amber-900/20 dark:text-amber-200">
            <p className="font-medium">
              {problemRows.length} row{problemRows.length === 1 ? '' : 's'} in the file could not be used and {problemRows.length === 1 ? 'was' : 'were'} left out:
            </p>
            <ul className="mt-1 list-disc pl-5 text-xs">
              {problemRows.map((r) => (
                <li key={r.row_number}>
                  Row {r.row_number}: {r.reason}
                  {r.label && <span className="text-muted-foreground"> ({r.label})</span>}
                </li>
              ))}
            </ul>
          </div>
        )}
        {ignoredRows.length > 0 && (
          <p className="text-xs text-muted-foreground">
            Ignored {ignoredRows.length} row{ignoredRows.length === 1 ? '' : 's'} that look like labels or totals:{' '}
            {ignoredRows.map((r) => `row ${r.row_number} “${r.label}”`).join(', ')}. Check none of them is a person.
          </p>
        )}

        {(accountFixes.length > 0 || suggestions.length > 0) && (
          <div className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:bg-amber-900/20 dark:text-amber-200 space-y-2">
            <p className="font-medium">Bank payment details — the bank record is the source of truth:</p>
            <ul className="space-y-2 text-xs">
              {accountFixes.map((l) => (
                <li key={`fix-${l.row_number}`} className="flex flex-wrap items-center gap-2">
                  <span>
                    <strong>{l.staff_name}</strong>: the bank paid {l.paid_to} ({l.paid_bank ?? 'bank'} {l.paid_account});
                    the directory has {l.directory_account ?? 'no account number'}.
                  </span>
                </li>
              ))}
              {suggestions.map((l) => l.suggested_payments.map((p) => (
                <li key={`sug-${l.row_number}-${p.id}`} className="flex flex-wrap items-center gap-2">
                  <span>
                    <strong>{l.staff_name ?? l.name}</strong> shows not paid, but {formatCurrency(p.amount)} on {p.date} went to {p.vendor ?? 'someone'} ({p.bank ?? 'bank'}{p.account ? ` ${p.account}` : ''}) and is unclaimed.
                  </span>
                </li>
              )))}
            </ul>
          </div>
        )}

        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <SummaryTile label="Expected (schedule)" value={formatCurrency(summary.expected_total)} />
          <SummaryTile label="Paid (bank)" value={formatCurrency(summary.paid_total)} />
          <SummaryTile
            label="Difference"
            value={formatCurrency(gap)}
            tone={Math.abs(gap) < 100 ? 'text-green-600' : gap < 0 ? 'text-amber-600' : 'text-blue-600'}
          />
          <SummaryTile label="Matched" value={`${summary.matched} of ${summary.rows}`} />
          <SummaryTile label="Underpaid" value={String(summary.underpaid)} />
          <SummaryTile label="Overpaid" value={String(summary.overpaid)} />
          <SummaryTile label="Not paid" value={String(summary.not_paid)} />
          <SummaryTile label="Paid, not on schedule" value={`${summary.unmatched_payments} · ${formatCurrency(summary.unmatched_total)}`} />
        </div>

        <Card>
          <CardHeader><CardTitle>Schedule vs bank</CardTitle></CardHeader>
          <CardContent className="overflow-x-auto">
            <table className="w-full text-sm">
              <caption className="sr-only">Payroll schedule compared with bank payments</caption>
              <thead>
                <tr className="border-b text-left text-xs text-muted-foreground">
                  <th scope="col" className="py-2 pr-3">Row</th>
                  <th scope="col" className="py-2 pr-3">Name</th>
                  <th scope="col" className="py-2 pr-3 text-right">Expected</th>
                  <th scope="col" className="py-2 pr-3 text-right">Paid</th>
                  <th scope="col" className="py-2 pr-3 text-right">Difference</th>
                  <th scope="col" className="py-2 pr-3">Status</th>
                  <th scope="col" className="py-2 pr-3">Staff directory</th>
                  <th scope="col" className="py-2">Paid to</th>
                </tr>
              </thead>
              <tbody>
                {lines.map((l) => (
                  <tr key={l.row_number} className="border-b last:border-0">
                    <td className="py-2 pr-3 text-muted-foreground">{l.row_number}</td>
                    <td className="py-2 pr-3 font-medium">{l.name}</td>
                    <td className="py-2 pr-3 text-right">{formatCurrency(l.expected_amount)}</td>
                    <td className="py-2 pr-3 text-right">{formatCurrency(l.paid_amount)}</td>
                    <td className="py-2 pr-3 text-right">{l.difference === 0 ? '—' : formatCurrency(l.difference)}</td>
                    <td className="py-2 pr-3"><StatusBadge status={l.status} /></td>
                    <td className="py-2 pr-3 text-xs">
                      {l.staff_id == null ? (
                        <div className="space-y-1">
                          <span className="text-amber-600">Not in staff directory</span>
                          {l.status === 'matched' && onAddStaff && (
                            <button type="button" className="block underline text-primary" onClick={() => prepareStaff(l)}>
                              Add to Staff Directory
                            </button>
                          )}
                        </div>
                      ) : l.in_sync ? (
                        <span className="text-green-700">In sync</span>
                      ) : (
                        <span className="text-amber-600">
                          Total {formatCurrency(l.computed_net ?? 0)} ({l.net_difference && l.net_difference > 0 ? '+' : ''}{formatCurrency(l.net_difference ?? 0)})
                          {l.net_difference != null && l.net_difference < 0 && onAddBonus && (
                            <button type="button" className="ml-2 underline text-primary"
                              onClick={() => onAddBonus(l.staff_id as number, Math.abs(l.net_difference as number))}>
                              Add {formatCurrency(Math.abs(l.net_difference))} as bonus
                            </button>
                          )}
                          {l.net_difference != null && l.net_difference > 0 && onAddDeduction && (
                            <button type="button" className="ml-2 underline text-primary"
                              onClick={() => onAddDeduction(l.staff_id as number, l.net_difference as number)}>
                              Deduct {formatCurrency(l.net_difference)}
                            </button>
                          )}
                        </span>
                      )}
                    </td>
                    <td className="py-2 text-muted-foreground">
                      {l.paid_to ?? '—'}{l.paid_date ? ` · ${l.paid_date}` : ''}
                      {l.transaction_ids.length > 1 ? ` (${l.transaction_ids.length} payments)` : ''}
                      {l.note && <span className="block text-xs text-amber-600">{l.note}</span>}
                      {l.extra_payment_ids.length > 0 && (
                        <span className="block text-xs text-amber-600">
                          Also paid {formatCurrency(l.extra_paid_amount)} in {l.extra_payment_ids.length} other payment{l.extra_payment_ids.length === 1 ? '' : 's'} — possible duplicate
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>

        {result.unlinked_staff.length > 0 && (
          <p className="text-xs text-amber-700 dark:text-amber-400">
            In the staff directory but not on the schedule: {result.unlinked_staff.map((s) => `${s.full_name} (${formatCurrency(s.computed_net)})`).join(', ')}.
          </p>
        )}

        {result.unmatched_transactions.length > 0 && (
          <Card>
            <CardHeader><CardTitle>Paid from the account but not on the schedule</CardTitle></CardHeader>
            <CardContent className="overflow-x-auto">
              <table className="w-full text-sm">
                <caption className="sr-only">Bank payments not on the schedule</caption>
                <thead>
                  <tr className="border-b text-left text-xs text-muted-foreground">
                    <th scope="col" className="py-2 pr-3">Date</th>
                    <th scope="col" className="py-2 pr-3">Paid to</th>
                    <th scope="col" className="py-2 pr-3 text-right">Amount</th>
                    <th scope="col" className="py-2">Description</th>
                  </tr>
                </thead>
                <tbody>
                  {result.unmatched_transactions.map((t) => (
                    <tr key={t.id} className="border-b last:border-0">
                      <td className="py-2 pr-3">{t.date}</td>
                      <td className="py-2 pr-3 font-medium">{t.vendor ?? '—'}</td>
                      <td className="py-2 pr-3 text-right">{formatCurrency(t.amount)}</td>
                      <td className="py-2 text-muted-foreground">{t.description}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </CardContent>
          </Card>
        )}
      </div>
    </details>
    {staffToAdd && (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
        <section role="dialog" aria-modal="true" aria-labelledby="add-matched-staff-title" className="w-full max-w-md space-y-4 rounded-xl border border-border bg-card p-6 shadow-xl">
          <div>
            <h2 id="add-matched-staff-title" className="text-lg font-semibold">Add Staff Directory Record</h2>
            <p className="mt-1 text-xs text-muted-foreground">
              Bank payment matched schedule row “{scheduleName}”. Confirm the bank name and enter the staff member’s monthly gross salary.
            </p>
          </div>
          {staffError && <p role="alert" className="text-sm text-destructive">{staffError}</p>}
          <div className="space-y-3">
            <label className="block text-xs font-medium">Name in the bank payment
              <input
                autoFocus
                value={staffToAdd.full_name}
                onChange={(e) => setStaffToAdd((current) => current ? { ...current, full_name: e.target.value } : current)}
                className="mt-1 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
              />
            </label>
            <label className="block text-xs font-medium">Role / Designation
              <input
                value={staffToAdd.role ?? ''}
                onChange={(e) => setStaffToAdd((current) => current ? { ...current, role: e.target.value } : current)}
                className="mt-1 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
              />
            </label>
            <label className="block text-xs font-medium">Monthly Gross Salary *
              <input
                type="number"
                min="1"
                step="0.01"
                value={staffToAdd.monthly_gross || ''}
                onChange={(e) => setStaffToAdd((current) => current ? { ...current, monthly_gross: Number(e.target.value) || 0 } : current)}
                className="mt-1 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
              />
            </label>
            <div className="grid grid-cols-2 gap-3">
              <label className="block text-xs font-medium">Bank Name
                <input
                  value={staffToAdd.bank_name ?? ''}
                  onChange={(e) => setStaffToAdd((current) => current ? { ...current, bank_name: e.target.value } : current)}
                  className="mt-1 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                />
              </label>
              <label className="block text-xs font-medium">Account Number
                <input
                  value={staffToAdd.account_number ?? ''}
                  onChange={(e) => setStaffToAdd((current) => current ? { ...current, account_number: e.target.value } : current)}
                  className="mt-1 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                />
              </label>
            </div>
          </div>
          <div className="flex justify-end gap-2 pt-1">
            <button type="button" disabled={savingStaff} onClick={() => setStaffToAdd(null)} className="rounded-md border border-input px-3 py-2 text-sm disabled:opacity-50">Cancel</button>
            <button type="button" disabled={savingStaff || !staffToAdd.full_name.trim() || (staffToAdd.monthly_gross ?? 0) <= 0} onClick={() => void saveStaff()} className="rounded-md bg-primary px-3 py-2 text-sm text-primary-foreground disabled:opacity-50">
              {savingStaff ? 'Saving…' : 'Add Staff'}
            </button>
          </div>
        </section>
      </div>
    )}
    </>
  );
}
