import { useEffect, useState } from 'react';
import {
  Banknote, Plus, Pencil, Trash2, CheckCircle2, XCircle, AlertCircle,
  BadgeCheck, Link as LinkIcon,
} from 'lucide-react';
import {
  listAdvancePayments, createAdvancePayment, updateAdvancePayment, deleteAdvancePayment,
  listStaffMembers,
} from '../api/client';
import type { AdvancePayment, AdvancePaymentIn, StaffMember } from '../api/types';
import { Button } from '../components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { TransactionPickerModal } from '../components/TransactionPickerModal';
import { formatCurrency } from '../lib/utils';

const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
];

const EMPTY_ADVANCE: AdvancePaymentIn = {
  staff_id: 0,
  amount: 0,
  date_issued: '',
  notes: '',
};

export function AdvancePayments() {
  const [advances, setAdvances] = useState<AdvancePayment[]>([]);
  const [staffList, setStaffList] = useState<StaffMember[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<AdvancePayment | null>(null);
  const [form, setForm] = useState<AdvancePaymentIn>(EMPTY_ADVANCE);
  const [saving, setSaving] = useState(false);
  const [deleteId, setDeleteId] = useState<number | null>(null);
  const [linkingAdvance, setLinkingAdvance] = useState<AdvancePayment | null>(null);

  const load = () => {
    setLoading(true);
    Promise.all([listAdvancePayments(), listStaffMembers(true)])
      .then(([a, s]) => {
        setAdvances(a);
        setStaffList(s);
      })
      .catch(() => setError('Failed to load data'))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  const openAdd = () => { setEditing(null); setForm(EMPTY_ADVANCE); setShowForm(true); };
  const openEdit = (advance: AdvancePayment) => {
    setEditing(advance);
    setForm({
      staff_id: advance.staff_id,
      amount: advance.amount,
      date_issued: advance.date_issued,
      notes: advance.notes ?? '',
    });
    setShowForm(true);
  };

  const handleSave = async () => {
    if (!form.staff_id || form.amount <= 0 || !form.date_issued) return;
    setSaving(true);
    try {
      if (editing) {
        await updateAdvancePayment(editing.id, form);
      } else {
        await createAdvancePayment(form);
      }
      setShowForm(false);
      setEditing(null);
      load();
    } catch {
      setError('Failed to save advance payment');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!deleteId) return;
    try {
      await deleteAdvancePayment(deleteId);
      setDeleteId(null);
      load();
    } catch {
      setError('Failed to delete advance payment');
    }
  };

  const handleLinkTransaction = async (advance: AdvancePayment, transactionId: number) => {
    setLinkingAdvance(null);
    try {
      await updateAdvancePayment(advance.id, {
        staff_id: advance.staff_id,
        amount: advance.amount,
        date_issued: advance.date_issued,
        transaction_id: transactionId,
        notes: advance.notes,
      });
      load();
    } catch {
      setError('Failed to link transaction');
    }
  };

  const totalAdvanced = advances.reduce((s, a) => s + a.amount, 0);
  const totalOutstanding = advances.filter((a) => !a.is_recovered).reduce((s, a) => s + a.amount, 0);
  const totalRecovered = totalAdvanced - totalOutstanding;

  const fmt = (d: string) => new Date(d).toLocaleDateString('en-NG', { day: '2-digit', month: 'short', year: 'numeric' });

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Banknote className="h-6 w-6 text-primary" />
            Advance Payment (IOU)
          </h1>
          <p className="text-muted-foreground text-sm mt-1">
            One-off salary advances — fully deducted from the next payroll run after they're recorded
          </p>
        </div>
        <Button onClick={openAdd}>
          <Plus className="h-4 w-4 mr-1" />
          Add Advance
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

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <Card>
          <CardContent className="pt-5">
            <p className="text-xs text-muted-foreground uppercase tracking-wide">Total Advanced</p>
            <p className="text-xl font-bold mt-1">{formatCurrency(totalAdvanced)}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-5">
            <p className="text-xs text-muted-foreground uppercase tracking-wide">Outstanding (Not Yet Recovered)</p>
            <p className="text-xl font-bold mt-1 text-brand-accent">{formatCurrency(totalOutstanding)}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-5">
            <p className="text-xs text-muted-foreground uppercase tracking-wide">Recovered to Date</p>
            <p className="text-xl font-bold mt-1 text-income">{formatCurrency(totalRecovered)}</p>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">All Advances</CardTitle>
        </CardHeader>
        <CardContent>
          {loading ? (
            <p className="text-sm text-muted-foreground py-4 text-center">Loading…</p>
          ) : advances.length === 0 ? (
            <p className="text-sm text-muted-foreground py-8 text-center">
              No advances recorded yet. Click "Add Advance" to record one.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-xs text-muted-foreground">
                    <th className="text-left py-2 pr-3 font-medium">Staff</th>
                    <th className="text-left py-2 pr-3 font-medium">Date Issued</th>
                    <th className="text-right py-2 pr-3 font-medium">Amount</th>
                    <th className="text-left py-2 pr-3 font-medium">Linked Transaction</th>
                    <th className="text-left py-2 pr-3 font-medium">Recovery Status</th>
                    <th className="text-left py-2 pr-3 font-medium">Notes</th>
                    <th className="text-center py-2 font-medium">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {advances.map((a) => (
                    <tr key={a.id}>
                      <td className="py-3 pr-3 font-medium">{a.staff_name}</td>
                      <td className="py-3 pr-3">{fmt(a.date_issued)}</td>
                      <td className="py-3 pr-3 text-right text-expense font-medium">
                        {formatCurrency(a.amount)}
                        {!a.is_recovered && a.remaining_amount < a.amount && (
                          <div className="text-xs text-muted-foreground font-normal">
                            {formatCurrency(a.remaining_amount)} remaining
                          </div>
                        )}
                      </td>
                      <td className="py-3 pr-3">
                        {a.verified ? (
                          <span
                            className="inline-flex items-center gap-1 rounded-full bg-green-50 px-2 py-0.5 text-xs text-green-700 font-medium"
                            title={a.matched_tx ? `Linked to tx #${a.matched_tx.id} — ${a.matched_tx.description}` : 'Verified'}
                          >
                            <BadgeCheck className="h-3 w-3" />
                            Verified
                          </span>
                        ) : (
                          <button
                            type="button"
                            onClick={() => setLinkingAdvance(a)}
                            className="inline-flex items-center gap-1 text-xs text-primary underline hover:no-underline"
                          >
                            <LinkIcon className="h-3 w-3" />
                            Link transaction…
                          </button>
                        )}
                      </td>
                      <td className="py-3 pr-3">
                        {a.is_recovered ? (
                          <span className="inline-flex items-center gap-1 rounded-full bg-secondary px-2 py-0.5 text-xs text-secondary-foreground font-medium">
                            Recovered{a.recovered_period_year && a.recovered_period_month
                              ? ` (${MONTHS[a.recovered_period_month - 1]} ${a.recovered_period_year})`
                              : ''}
                          </span>
                        ) : (
                          <span className="text-xs text-muted-foreground">Pending — next payroll run</span>
                        )}
                      </td>
                      <td className="py-3 pr-3 text-xs text-muted-foreground">{a.notes || '—'}</td>
                      <td className="py-3 text-center">
                        <div className="flex gap-1 justify-center">
                          <button
                            type="button"
                            aria-label="Edit advance"
                            disabled={a.is_recovered}
                            onClick={() => openEdit(a)}
                            className="p-1 rounded hover:bg-accent text-muted-foreground disabled:opacity-30 disabled:cursor-not-allowed"
                          >
                            <Pencil className="h-3.5 w-3.5" />
                          </button>
                          <button
                            type="button"
                            aria-label="Delete advance"
                            disabled={a.is_recovered}
                            onClick={() => setDeleteId(a.id)}
                            className="p-1 rounded hover:bg-destructive/10 text-muted-foreground hover:text-destructive disabled:opacity-30 disabled:cursor-not-allowed"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Add/Edit modal */}
      {showForm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-md bg-card rounded-xl shadow-xl border border-border p-6 space-y-5">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-semibold">{editing ? 'Edit Advance' : 'Add Advance'}</h2>
              <button type="button" aria-label="Close" onClick={() => setShowForm(false)} className="text-muted-foreground hover:text-foreground">
                <XCircle className="h-5 w-5" />
              </button>
            </div>

            <div className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-foreground mb-1">Staff Member *</label>
                {staffList.length > 0 ? (
                  <select
                    title="Select staff member"
                    value={form.staff_id || ''}
                    onChange={(e) => setForm((f) => ({ ...f, staff_id: e.target.value ? parseInt(e.target.value, 10) : 0 }))}
                    className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
                  >
                    <option value="">— Select staff —</option>
                    {staffList.map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.full_name}{s.role ? ` (${s.role})` : ''} · ₦{s.monthly_gross.toLocaleString('en-NG')}/mo
                      </option>
                    ))}
                  </select>
                ) : (
                  <p className="text-xs text-amber-700">No staff in directory yet. <a href="/staff/directory" className="underline">Add staff first.</a></p>
                )}
              </div>

              <div>
                <label className="block text-xs font-medium text-foreground mb-1">Amount *</label>
                <input
                  type="text"
                  inputMode="numeric"
                  placeholder="0"
                  value={form.amount === 0 ? '' : form.amount.toLocaleString('en-NG')}
                  onChange={(e) => {
                    const d = e.target.value.replace(/[^0-9]/g, '');
                    setForm((f) => ({ ...f, amount: d === '' ? 0 : parseInt(d, 10) }));
                  }}
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-foreground mb-1">Date Issued *</label>
                <input
                  type="date"
                  title="Date the advance was given"
                  value={form.date_issued}
                  onChange={(e) => setForm((f) => ({ ...f, date_issued: e.target.value }))}
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
                />
                <p className="text-xs text-muted-foreground mt-1">
                  Fully deducted from the next payroll run processed after this date.
                </p>
              </div>

              <div>
                <label className="block text-xs font-medium text-foreground mb-1">Notes</label>
                <input
                  type="text"
                  placeholder="Optional — reason for the advance"
                  value={form.notes ?? ''}
                  onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))}
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
                />
              </div>
            </div>

            <div className="flex justify-end gap-2 pt-2">
              <Button variant="outline" onClick={() => setShowForm(false)} disabled={saving}>Cancel</Button>
              <Button onClick={handleSave} disabled={saving || !form.staff_id || form.amount <= 0 || !form.date_issued}>
                {saving ? 'Saving…' : editing ? 'Save Changes' : 'Add Advance'}
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Link transaction */}
      {linkingAdvance && (
        <TransactionPickerModal
          title={`Link a transaction for ${linkingAdvance.staff_name}'s advance`}
          category="IOU (Advance Salary)"
          excludeTransactionIds={advances
            .filter((a) => a.transaction_id !== null && a.id !== linkingAdvance.id)
            .map((a) => a.transaction_id as number)}
          onClose={() => setLinkingAdvance(null)}
          onSelect={(t) => handleLinkTransaction(linkingAdvance, t.id)}
        />
      )}

      {/* Delete confirmation */}
      {deleteId !== null && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-sm bg-card rounded-xl shadow-xl border border-border p-6 space-y-4">
            <h2 className="text-base font-semibold">Delete Advance Payment?</h2>
            <p className="text-sm text-muted-foreground">This will permanently remove this advance record.</p>
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => setDeleteId(null)}>Cancel</Button>
              <Button variant="destructive" onClick={handleDelete}>
                <CheckCircle2 className="h-3.5 w-3.5 mr-1" />
                Delete
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
