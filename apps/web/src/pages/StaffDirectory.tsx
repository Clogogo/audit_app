import { useEffect, useState } from 'react';
import { Users, Plus, Pencil, Trash2, XCircle, AlertCircle, Building2 } from 'lucide-react';
import { listStaffMembers, createStaffMember, updateStaffMember, deleteStaffMember } from '../api/client';
import type { StaffMember, StaffMemberIn } from '../api/types';
import { Button } from '../components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { AISummaryCard } from '../components/AISummaryCard';
import { useStaffAISummary } from '../hooks';
import { formatCurrency } from '../lib/utils';

const EMPTY_FORM: StaffMemberIn = {
  full_name: '',
  role: '',
  bank_name: '',
  account_number: '',
  monthly_gross: 0,
  start_date: null,
  end_date: null,
  is_active: true,
  notes: '',
};

function NumInput({ label, value, onChange, required = false }: {
  label: string; value: number; onChange: (n: number) => void; required?: boolean;
}) {
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

export function StaffDirectory() {
  const [staff, setStaff] = useState<StaffMember[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<StaffMember | null>(null);
  const [form, setForm] = useState<StaffMemberIn>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [deleteId, setDeleteId] = useState<number | null>(null);

  const load = () => {
    setLoading(true);
    listStaffMembers()
      .then(setStaff)
      .catch(() => setError('Failed to load staff'))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  const aiSummary = useStaffAISummary();

  const openAdd = () => { setEditing(null); setForm(EMPTY_FORM); setShowForm(true); };
  const openEdit = (s: StaffMember) => {
    setEditing(s);
    setForm({
      full_name: s.full_name,
      role: s.role ?? '',
      bank_name: s.bank_name ?? '',
      account_number: s.account_number ?? '',
      monthly_gross: s.monthly_gross,
      start_date: s.start_date ?? null,
      end_date: s.end_date ?? null,
      is_active: s.is_active,
      notes: s.notes ?? '',
    });
    setShowForm(true);
  };
  const closeForm = () => { setShowForm(false); setEditing(null); };

  const handleSave = async () => {
    if (!form.full_name) return;
    setSaving(true);
    try {
      if (editing) {
        await updateStaffMember(editing.id, form);
      } else {
        await createStaffMember(form);
      }
      closeForm();
      load();
      aiSummary.refetch();
    } catch {
      setError('Failed to save staff member');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: number) => {
    try {
      await deleteStaffMember(id);
      setDeleteId(null);
      load();
      aiSummary.refetch();
    } catch {
      setError('Failed to delete staff member');
    }
  };

  const active = staff.filter((s) => s.is_active);
  const inactive = staff.filter((s) => !s.is_active);
  const totalPayroll = active.reduce((sum, s) => sum + s.monthly_gross, 0);

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Users className="h-6 w-6 text-primary" />
            Staff Directory
          </h1>
          <p className="text-muted-foreground text-sm mt-1">
            Employee profiles — used by payroll and loan deduction calculations
          </p>
        </div>
        <Button onClick={openAdd}>
          <Plus className="h-4 w-4 mr-1" />
          Add Staff
        </Button>
      </div>

      {error && (
        <div className="flex items-center gap-2 rounded-lg border border-destructive/20 bg-destructive/5 px-4 py-3 text-sm text-destructive">
          <AlertCircle className="h-4 w-4 shrink-0" />
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <Card>
          <CardContent className="pt-5">
            <p className="text-xs text-muted-foreground uppercase tracking-wide">Active Staff</p>
            <p className="text-xl font-bold mt-1">{active.length}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-5">
            <p className="text-xs text-muted-foreground uppercase tracking-wide">Monthly Gross Payroll</p>
            <p className="text-xl font-bold mt-1">{formatCurrency(totalPayroll)}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-5">
            <p className="text-xs text-muted-foreground uppercase tracking-wide">Total Staff</p>
            <p className="text-xl font-bold mt-1">{staff.length}</p>
          </CardContent>
        </Card>
      </div>

      <AISummaryCard
        narrative={aiSummary.narrative}
        available={aiSummary.available}
        loading={aiSummary.loading}
        title="AI Staffing Analysis"
      />

      {loading ? (
        <p className="text-muted-foreground text-sm">Loading…</p>
      ) : (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Staff Members</CardTitle>
          </CardHeader>
          <CardContent>
            {active.length === 0 ? (
              <p className="text-sm text-muted-foreground py-4 text-center">
                No staff added yet. Click "Add Staff" to create profiles.
              </p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b text-xs text-muted-foreground">
                      <th className="text-left py-2 pr-4 font-medium">Name</th>
                      <th className="text-left py-2 pr-4 font-medium">Role</th>
                      <th className="text-left py-2 pr-4 font-medium">Start Date</th>
                      <th className="text-left py-2 pr-4 font-medium">Bank</th>
                      <th className="text-left py-2 pr-4 font-medium">Account No.</th>
                      <th className="text-right py-2 pr-4 font-medium">Monthly Gross</th>
                      <th className="py-2"><span className="sr-only">Actions</span></th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {active.map((s) => (
                      <tr key={s.id} className="hover:bg-muted/30 transition-colors">
                        <td className="py-3 pr-4 font-medium">{s.full_name}</td>
                        <td className="py-3 pr-4 text-muted-foreground">{s.role || '—'}</td>
                        <td className="py-3 pr-4 text-muted-foreground">
                          {s.start_date ? new Date(s.start_date).toLocaleDateString('en-NG', { day:'2-digit', month:'short', year:'numeric' }) : '—'}
                        </td>
                        <td className="py-3 pr-4 text-muted-foreground">{s.bank_name || '—'}</td>
                        <td className="py-3 pr-4">
                          {s.account_number ? (
                            <span className="font-mono text-xs bg-muted px-2 py-0.5 rounded">{s.account_number}</span>
                          ) : '—'}
                        </td>
                        <td className="py-3 pr-4 text-right font-medium">{formatCurrency(s.monthly_gross)}</td>
                        <td className="py-3">
                          <div className="flex gap-1 justify-end">
                            <button
                              type="button"
                              aria-label="Edit"
                              onClick={() => openEdit(s)}
                              className="p-1.5 rounded hover:bg-accent text-muted-foreground hover:text-foreground"
                            >
                              <Pencil className="h-3.5 w-3.5" />
                            </button>
                            <button
                              type="button"
                              aria-label="Delete"
                              onClick={() => setDeleteId(s.id)}
                              className="p-1.5 rounded hover:bg-destructive/10 text-muted-foreground hover:text-destructive"
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                  {active.length > 1 && (
                    <tfoot>
                      <tr className="border-t font-semibold">
                        <td colSpan={5} className="py-2 text-xs text-muted-foreground">Total monthly gross</td>
                        <td className="py-2 text-right">{formatCurrency(totalPayroll)}</td>
                        <td />
                      </tr>
                    </tfoot>
                  )}
                </table>
              </div>
            )}

            {inactive.length > 0 && (
              <div className="mt-6">
                <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-3">Inactive</p>
                <div className="space-y-2">
                  {inactive.map((s) => (
                    <div key={s.id} className="flex items-center justify-between rounded-lg border border-border/50 bg-muted/20 px-4 py-2.5 gap-3">
                      <div className="min-w-0">
                        <p className="text-sm font-medium text-muted-foreground truncate">{s.full_name}</p>
                        <p className="text-xs text-muted-foreground">{s.role || 'No role'} · {formatCurrency(s.monthly_gross)}/mo</p>
                      </div>
                      <div className="flex gap-1 shrink-0">
                        <button type="button" aria-label="Edit" onClick={() => openEdit(s)}
                          className="p-1.5 rounded hover:bg-accent text-muted-foreground">
                          <Pencil className="h-3.5 w-3.5" />
                        </button>
                        <button type="button" aria-label="Delete" onClick={() => setDeleteId(s.id)}
                          className="p-1.5 rounded hover:bg-destructive/10 text-muted-foreground hover:text-destructive">
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Form modal */}
      {showForm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-md bg-card rounded-xl shadow-xl border border-border p-6 space-y-5 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-semibold">{editing ? 'Edit Staff Member' : 'Add Staff Member'}</h2>
              <button type="button" aria-label="Close" onClick={closeForm} className="text-muted-foreground hover:text-foreground">
                <XCircle className="h-5 w-5" />
              </button>
            </div>

            <div className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-foreground mb-1">Full Name *</label>
                <input
                  type="text"
                  placeholder="e.g. Mrs Adewale Funke"
                  value={form.full_name}
                  onChange={(e) => setForm((f) => ({ ...f, full_name: e.target.value }))}
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
                />
                <p className="text-xs text-muted-foreground mt-1">
                  This name must match the Vendor field used when recording salary transactions
                </p>
              </div>

              <div>
                <label className="block text-xs font-medium text-foreground mb-1">Role / Designation</label>
                <input
                  type="text"
                  placeholder="e.g. Class Teacher, Admin Officer"
                  value={form.role ?? ''}
                  onChange={(e) => setForm((f) => ({ ...f, role: e.target.value }))}
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
                />
              </div>

              <NumInput
                label="Monthly Gross Salary"
                value={form.monthly_gross ?? 0}
                onChange={(n) => setForm((f) => ({ ...f, monthly_gross: n }))}
                required
              />

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-medium text-foreground mb-1">Start Date</label>
                  <input
                    type="date"
                    title="Employment start date"
                    value={form.start_date ?? ''}
                    onChange={(e) => setForm((f) => ({ ...f, start_date: e.target.value || null }))}
                    className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-foreground mb-1">End Date</label>
                  <input
                    type="date"
                    title="Employment end date"
                    value={form.end_date ?? ''}
                    onChange={(e) => setForm((f) => ({ ...f, end_date: e.target.value || null }))}
                    className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
                  />
                </div>
              </div>

              <div className="flex items-center gap-2 pt-1">
                <Building2 className="h-4 w-4 text-muted-foreground shrink-0" />
                <p className="text-xs font-medium text-muted-foreground">Bank Details (for transaction matching)</p>
              </div>

              <div>
                <label className="block text-xs font-medium text-foreground mb-1">Bank Name</label>
                <input
                  type="text"
                  placeholder="e.g. Access Bank"
                  value={form.bank_name ?? ''}
                  onChange={(e) => setForm((f) => ({ ...f, bank_name: e.target.value }))}
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-foreground mb-1">Account Number</label>
                <input
                  type="text"
                  placeholder="e.g. 0123456789"
                  value={form.account_number ?? ''}
                  onChange={(e) => setForm((f) => ({ ...f, account_number: e.target.value }))}
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-foreground mb-1">Notes</label>
                <input
                  type="text"
                  placeholder="Optional"
                  value={form.notes ?? ''}
                  onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))}
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
                />
              </div>

              <div className="flex items-center gap-2">
                <input
                  id="is_active_staff"
                  type="checkbox"
                  checked={form.is_active ?? true}
                  onChange={(e) => setForm((f) => ({ ...f, is_active: e.target.checked }))}
                  className="rounded border-input"
                />
                <label htmlFor="is_active_staff" className="text-sm">Active employee</label>
              </div>
            </div>

            <div className="flex justify-end gap-2 pt-2">
              <Button variant="outline" onClick={closeForm} disabled={saving}>Cancel</Button>
              <Button onClick={handleSave} disabled={saving || !form.full_name}>
                {saving ? 'Saving…' : editing ? 'Save Changes' : 'Add Staff'}
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Delete confirmation */}
      {deleteId !== null && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-sm bg-card rounded-xl shadow-xl border border-border p-6 space-y-4">
            <h2 className="text-base font-semibold">Remove Staff Member?</h2>
            <p className="text-sm text-muted-foreground">
              This removes the staff profile. Existing payroll records and loans linked to this person will remain.
            </p>
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => setDeleteId(null)}>Cancel</Button>
              <Button variant="destructive" onClick={() => handleDelete(deleteId)}>Remove</Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
