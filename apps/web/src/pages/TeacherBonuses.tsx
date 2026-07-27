import { useEffect, useState } from 'react';
import { Gift, Plus, Pencil, Trash2, XCircle, AlertCircle, Settings, RotateCcw } from 'lucide-react';
import {
  listTeacherBonuses, createTeacherBonus, updateTeacherBonus, deleteTeacherBonus,
  getBonusTypes, createBonusType, updateBonusType, deleteBonusType, listStaffMembers, getTerms,
} from '../api/client';
import type { TeacherBonus, TeacherBonusIn, BonusType, BonusTypeIn, StaffMember, Term } from '../api/types';
import { Button } from '../components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { formatCurrency } from '../lib/utils';

const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
];

const todayYearMonth = () => {
  const now = new Date();
  return { year: now.getFullYear(), month: now.getMonth() + 1 };
};

const emptyForm = (): TeacherBonusIn => {
  const { year, month } = todayYearMonth();
  return {
    staff_id: 0,
    bonus_type: '',
    percentage: 0,
    basis_amount: 0,
    period_year: year,
    period_month: month,
    term_id: null,
    notes: '',
  };
};

const emptyTypeForm = (): BonusTypeIn => ({
  label: '',
  description: '',
  calculation_method: 'percentage',
  basis_is_salary: true,
  default_percentage: 0,
  is_active: true,
});

function NumInput({ label, value, onChange }: {
  label: string; value: number; onChange: (n: number) => void;
}) {
  const [raw, setRaw] = useState('');
  const [focused, setFocused] = useState(false);
  return (
    <div>
      <label className="block text-xs font-medium text-foreground mb-1">{label}</label>
      <input
        type="text"
        inputMode="numeric"
        placeholder="0"
        value={focused ? raw : (value === 0 ? '' : value.toLocaleString('en-NG'))}
        onFocus={() => { setFocused(true); setRaw(value === 0 ? '' : String(value)); }}
        onChange={(e) => {
          const d = e.target.value.replace(/[^0-9.]/g, '');
          setRaw(d);
          onChange(d === '' ? 0 : parseFloat(d));
        }}
        onBlur={() => setFocused(false)}
        className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
      />
    </div>
  );
}

export function TeacherBonuses() {
  const [bonuses, setBonuses] = useState<TeacherBonus[]>([]);
  const [staffList, setStaffList] = useState<StaffMember[]>([]);
  const [bonusTypes, setBonusTypes] = useState<BonusType[]>([]);
  const [terms, setTerms] = useState<Term[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [staffFilter, setStaffFilter] = useState('all');
  const [typeFilter, setTypeFilter] = useState('all');

  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<TeacherBonus | null>(null);
  const [form, setForm] = useState<TeacherBonusIn>(emptyForm());
  const [saving, setSaving] = useState(false);
  const [deleteId, setDeleteId] = useState<number | null>(null);

  const [showTypesModal, setShowTypesModal] = useState(false);
  const [editingType, setEditingType] = useState<BonusType | null>(null);
  const [typeForm, setTypeForm] = useState<BonusTypeIn>(emptyTypeForm());
  const [savingType, setSavingType] = useState(false);

  const load = () => {
    setLoading(true);
    Promise.all([listTeacherBonuses(), listStaffMembers(true), getBonusTypes(), getTerms()])
      .then(([b, s, t, tm]) => { setBonuses(b); setStaffList(s); setBonusTypes(t); setTerms(tm); })
      .catch(() => setError('Failed to load bonuses'))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  const openAdd = () => { setEditing(null); setForm(emptyForm()); setShowForm(true); };
  const openEdit = (b: TeacherBonus) => {
    setEditing(b);
    setForm({
      staff_id: b.staff_id,
      bonus_type: b.bonus_type,
      percentage: b.percentage,
      basis_amount: b.basis_amount,
      period_year: b.period_year,
      period_month: b.period_month,
      term_id: b.term_id,
      notes: b.notes ?? '',
    });
    setShowForm(true);
  };
  const closeForm = () => { setShowForm(false); setEditing(null); };

  // What basis_amount actually means for a type — carrying a number across
  // a category change would silently reinterpret it (e.g. a typed-in flat
  // amount becoming a percentage basis, or an auto-filled salary becoming
  // a flat amount), so a switch only keeps the old value within the same
  // category.
  const basisCategory = (t?: BonusType): 'flat' | 'salary' | 'manual' | undefined => {
    if (!t) return undefined;
    if (t.calculation_method === 'flat_amount') return 'flat';
    return t.basis_is_salary ? 'salary' : 'manual';
  };

  // A flat bonus still stores percentage/basis_amount under the hood (no
  // schema change), but basis_amount is the staff's salary and percentage
  // is DERIVED from the entered amount — "what % of their salary is this
  // flat amount" — rather than a meaningless hardcoded 100%. Falls back to
  // the old amount-as-basis/100% scheme only when salary is unknown/zero,
  // since a percentage of nothing is undefined.
  const flatFieldsFor = (amount: number, salary: number): Pick<TeacherBonusIn, 'basis_amount' | 'percentage'> =>
    salary > 0
      ? { basis_amount: salary, percentage: (amount / salary) * 100 }
      : { basis_amount: amount, percentage: 100 };

  const applyType = (typeKey: string) => {
    const type = bonusTypes.find((t) => t.key === typeKey);
    if (!type) return;
    setForm((f) => {
      const staff = staffList.find((s) => s.id === f.staff_id);
      const prevType = bonusTypes.find((t) => t.key === f.bonus_type);
      const sameCategory = basisCategory(prevType) === basisCategory(type);
      if (type.calculation_method === 'flat_amount') {
        const carriedAmount = sameCategory ? round2((f.percentage / 100) * f.basis_amount) : 0;
        return { ...f, bonus_type: typeKey, ...flatFieldsFor(carriedAmount, staff?.monthly_gross ?? 0) };
      }
      const carried = sameCategory ? f.basis_amount : 0;
      const basis = type.basis_is_salary ? (staff?.monthly_gross ?? carried) : carried;
      return { ...f, bonus_type: typeKey, percentage: type.default_percentage, basis_amount: basis };
    });
  };

  const applyStaff = (staffId: number) => {
    const staff = staffList.find((s) => s.id === staffId);
    setForm((f) => {
      const type = bonusTypes.find((t) => t.key === f.bonus_type);
      if (!type) return { ...f, staff_id: staffId };
      if (type.calculation_method === 'flat_amount') {
        const currentAmount = round2((f.percentage / 100) * f.basis_amount);
        return { ...f, staff_id: staffId, ...flatFieldsFor(currentAmount, staff?.monthly_gross ?? 0) };
      }
      if (!type.basis_is_salary) return { ...f, staff_id: staffId };
      return { ...f, staff_id: staffId, basis_amount: staff?.monthly_gross ?? f.basis_amount };
    });
  };

  const openManageTypes = () => { setEditingType(null); setTypeForm(emptyTypeForm()); setShowTypesModal(true); };
  const openEditType = (t: BonusType) => {
    setEditingType(t);
    setTypeForm({
      label: t.label, description: t.description ?? '', calculation_method: t.calculation_method,
      basis_is_salary: t.basis_is_salary, default_percentage: t.default_percentage, is_active: t.is_active,
    });
  };
  const closeTypeForm = () => { setEditingType(null); setTypeForm(emptyTypeForm()); };

  const handleSaveType = async () => {
    if (!typeForm.label.trim()) return;
    setSavingType(true);
    try {
      if (editingType) {
        await updateBonusType(editingType.id, typeForm);
      } else {
        await createBonusType(typeForm);
      }
      closeTypeForm();
      load();
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'Failed to save bonus type');
    } finally {
      setSavingType(false);
    }
  };

  const handleToggleTypeActive = async (t: BonusType) => {
    try {
      if (t.is_active) {
        await deleteBonusType(t.id);
      } else {
        await updateBonusType(t.id, {
          label: t.label, description: t.description, calculation_method: t.calculation_method,
          basis_is_salary: t.basis_is_salary, default_percentage: t.default_percentage, is_active: true,
        });
      }
      load();
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'Failed to update bonus type');
    }
  };

  const handleSave = async () => {
    if (!form.staff_id || !form.bonus_type || form.percentage < 0 || form.basis_amount < 0) return;
    setSaving(true);
    try {
      if (editing) {
        await updateTeacherBonus(editing.id, form);
      } else {
        await createTeacherBonus(form);
      }
      closeForm();
      load();
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'Failed to save bonus');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: number) => {
    try {
      await deleteTeacherBonus(id);
      setDeleteId(null);
      load();
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'Failed to delete bonus');
    }
  };

  const filtered = bonuses.filter(
    (b) => (staffFilter === 'all' || String(b.staff_id) === staffFilter) && (typeFilter === 'all' || b.bonus_type === typeFilter)
  );
  const totalAmount = filtered.reduce((sum, b) => sum + b.amount, 0);
  const selectedType = bonusTypes.find((t) => t.key === form.bonus_type);
  const previewAmount = round2((form.percentage / 100) * form.basis_amount);
  // Retired types stay selectable only if they're already on the record
  // being edited — otherwise the dropdown would silently blank out.
  const typeOptions = bonusTypes.filter((t) => t.is_active || t.key === form.bonus_type);

  const typeLabel = (key: string) => bonusTypes.find((t) => t.key === key)?.label ?? key;

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Gift className="h-6 w-6 text-primary" />
            Bonuses
          </h1>
          <p className="text-muted-foreground text-sm mt-1">
            Performance, referral, loyalty, and annual bonuses — automatically added to that staff member's payroll for the target month
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={openManageTypes}>
            <Settings className="h-4 w-4 mr-1" />
            Manage Types
          </Button>
          <Button onClick={openAdd} disabled={staffList.length === 0}>
            <Plus className="h-4 w-4 mr-1" />
            Add Bonus
          </Button>
        </div>
      </div>

      {staffList.length === 0 && !loading && (
        <p className="text-xs text-amber-700">
          No active staff in the directory yet. <a href="/staff/directory" className="underline">Add staff first.</a>
        </p>
      )}

      {error && (
        <div className="flex items-center gap-2 rounded-lg border border-destructive/20 bg-destructive/5 px-4 py-3 text-sm text-destructive">
          <AlertCircle className="h-4 w-4 shrink-0" />
          {error}
          <button type="button" title="Dismiss error" className="ml-auto text-destructive/80 hover:text-destructive" onClick={() => setError(null)}>
            <XCircle className="h-4 w-4" />
          </button>
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <Card>
          <CardContent className="pt-5">
            <p className="text-xs text-muted-foreground uppercase tracking-wide">Bonus Records (filtered)</p>
            <p className="text-xl font-bold mt-1">{filtered.length}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-5">
            <p className="text-xs text-muted-foreground uppercase tracking-wide">Total Amount (filtered)</p>
            <p className="text-xl font-bold mt-1">{formatCurrency(totalAmount)}</p>
          </CardContent>
        </Card>
      </div>

      <div className="flex items-center gap-3 flex-wrap">
        <select
          title="Filter by staff"
          value={staffFilter}
          onChange={(e) => setStaffFilter(e.target.value)}
          className="rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm"
        >
          <option value="all">All Staff</option>
          {staffList.map((s) => <option key={s.id} value={s.id}>{s.full_name}</option>)}
        </select>
        <select
          title="Filter by bonus type"
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value)}
          className="rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm"
        >
          <option value="all">All Types</option>
          {bonusTypes.map((t) => <option key={t.key} value={t.key}>{t.label}</option>)}
        </select>
      </div>

      {loading ? (
        <p className="text-muted-foreground text-sm">Loading…</p>
      ) : (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Bonuses</CardTitle>
          </CardHeader>
          <CardContent>
            {filtered.length === 0 ? (
              <p className="text-sm text-muted-foreground py-4 text-center">
                No bonus records match this filter.
              </p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b text-xs text-muted-foreground">
                      <th className="text-left py-2 pr-3 font-medium">Staff</th>
                      <th className="text-left py-2 pr-3 font-medium">Type</th>
                      <th className="text-right py-2 pr-3 font-medium">%</th>
                      <th className="text-right py-2 pr-3 font-medium">Basis</th>
                      <th className="text-right py-2 pr-3 font-medium">Amount</th>
                      <th className="text-left py-2 pr-3 font-medium">Payroll Month</th>
                      <th className="text-left py-2 pr-3 font-medium">Notes</th>
                      <th className="py-2"><span className="sr-only">Actions</span></th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {filtered.map((b) => (
                      <tr key={b.id} className="hover:bg-muted/30 transition-colors">
                        <td className="py-3 pr-3 font-medium">{b.staff_name}</td>
                        <td className="py-3 pr-3 text-muted-foreground">{typeLabel(b.bonus_type)}</td>
                        <td className="py-3 pr-3 text-right">{b.percentage.toFixed(2)}%</td>
                        <td className="py-3 pr-3 text-right text-muted-foreground">{formatCurrency(b.basis_amount)}</td>
                        <td className="py-3 pr-3 text-right font-medium text-income">{formatCurrency(b.amount)}</td>
                        <td className="py-3 pr-3 text-muted-foreground">{MONTHS[b.period_month - 1]} {b.period_year}</td>
                        <td className="py-3 pr-3 text-xs text-muted-foreground max-w-xs truncate" title={b.notes ?? ''}>{b.notes || '—'}</td>
                        <td className="py-3">
                          <div className="flex gap-1 justify-end">
                            <button type="button" aria-label="Edit" onClick={() => openEdit(b)}
                              className="p-1.5 rounded hover:bg-accent text-muted-foreground hover:text-foreground">
                              <Pencil className="h-3.5 w-3.5" />
                            </button>
                            <button type="button" aria-label="Delete" onClick={() => setDeleteId(b.id)}
                              className="p-1.5 rounded hover:bg-destructive/10 text-muted-foreground hover:text-destructive">
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
      )}

      {/* Form modal */}
      {showForm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-md bg-card rounded-xl shadow-xl border border-border p-6 space-y-5 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-semibold">{editing ? 'Edit Bonus' : 'Add Bonus'}</h2>
              <button type="button" aria-label="Close" onClick={closeForm} className="text-muted-foreground hover:text-foreground">
                <XCircle className="h-5 w-5" />
              </button>
            </div>

            <div className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-foreground mb-1">Staff Member *</label>
                <select
                  title="Select staff member"
                  value={form.staff_id || ''}
                  onChange={(e) => applyStaff(e.target.value ? parseInt(e.target.value, 10) : 0)}
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
                >
                  <option value="">— Select staff —</option>
                  {staffList.map((s) => (
                    <option key={s.id} value={s.id}>{s.full_name}{s.role ? ` (${s.role})` : ''}</option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-xs font-medium text-foreground mb-1">Bonus Type *</label>
                <select
                  title="Select bonus type"
                  value={form.bonus_type}
                  onChange={(e) => applyType(e.target.value)}
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
                >
                  <option value="">— Select type —</option>
                  {typeOptions.map((t) => <option key={t.key} value={t.key}>{t.label}</option>)}
                </select>
                {selectedType && (
                  <p className="text-xs text-muted-foreground mt-1">{selectedType.description}</p>
                )}
              </div>

              {selectedType?.calculation_method === 'flat_amount' ? (
                <>
                  <NumInput
                    label="Bonus Amount (₦)"
                    value={previewAmount}
                    onChange={(n) => {
                      const staff = staffList.find((s) => s.id === form.staff_id);
                      setForm((f) => ({ ...f, ...flatFieldsFor(n, staff?.monthly_gross ?? 0) }));
                    }}
                  />
                  {form.staff_id > 0 && (
                    <p className="text-xs text-muted-foreground">{form.percentage.toFixed(2)}% of this staff member's salary</p>
                  )}
                </>
              ) : (
                <div className="grid grid-cols-2 gap-3">
                  <NumInput label="Percentage (%)" value={form.percentage} onChange={(n) => setForm((f) => ({ ...f, percentage: n }))} />
                  <NumInput
                    label={selectedType && !selectedType.basis_is_salary ? "Referred Student's Fee" : 'Basis Amount (salary)'}
                    value={form.basis_amount}
                    onChange={(n) => setForm((f) => ({ ...f, basis_amount: n }))}
                  />
                </div>
              )}

              <div className="rounded-md bg-secondary/40 px-3 py-2 text-sm">
                Computed bonus: <span className="font-semibold text-income">{formatCurrency(previewAmount)}</span>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-medium text-foreground mb-1">Payroll Month *</label>
                  <select
                    title="Payroll month"
                    value={form.period_month}
                    onChange={(e) => setForm((f) => ({ ...f, period_month: parseInt(e.target.value, 10) }))}
                    className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
                  >
                    {MONTHS.map((m, i) => <option key={m} value={i + 1}>{m}</option>)}
                  </select>
                </div>
                <NumInput label="Payroll Year" value={form.period_year} onChange={(n) => setForm((f) => ({ ...f, period_year: n }))} />
              </div>

              <div>
                <label className="block text-xs font-medium text-foreground mb-1">Term (optional)</label>
                <select
                  title="Term"
                  value={form.term_id ?? ''}
                  onChange={(e) => setForm((f) => ({ ...f, term_id: e.target.value ? parseInt(e.target.value, 10) : null }))}
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
                >
                  <option value="">— None —</option>
                  {terms.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
                </select>
              </div>

              <div>
                <label className="block text-xs font-medium text-foreground mb-1">Notes</label>
                <input
                  type="text"
                  placeholder="e.g. Referred Chidinma Okafor, JSS1, ₦25,000 fee"
                  value={form.notes ?? ''}
                  onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))}
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
                />
              </div>
            </div>

            <div className="flex justify-end gap-2 pt-2">
              <Button variant="outline" onClick={closeForm} disabled={saving}>Cancel</Button>
              <Button onClick={handleSave} disabled={saving || !form.staff_id || !form.bonus_type}>
                {saving ? 'Saving…' : editing ? 'Save Changes' : 'Add Bonus'}
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Manage Bonus Types */}
      {showTypesModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-lg bg-card rounded-xl shadow-xl border border-border p-6 space-y-5 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-semibold">Manage Bonus Types</h2>
              <button type="button" aria-label="Close" onClick={() => { setShowTypesModal(false); closeTypeForm(); }} className="text-muted-foreground hover:text-foreground">
                <XCircle className="h-5 w-5" />
              </button>
            </div>

            <div className="space-y-3 border-b border-border pb-5">
              <h3 className="text-sm font-medium">{editingType ? `Edit "${editingType.label}"` : 'Add a new type'}</h3>
              <input
                type="text"
                placeholder="Label, e.g. Christmas Gift"
                value={typeForm.label}
                onChange={(e) => setTypeForm((f) => ({ ...f, label: e.target.value }))}
                className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
              />
              <input
                type="text"
                placeholder="Description (optional)"
                value={typeForm.description ?? ''}
                onChange={(e) => setTypeForm((f) => ({ ...f, description: e.target.value }))}
                className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
              />

              <div className="flex gap-4 text-sm">
                <label className="flex items-center gap-1.5">
                  <input
                    type="radio"
                    checked={typeForm.calculation_method === 'percentage'}
                    onChange={() => setTypeForm((f) => ({ ...f, calculation_method: 'percentage' }))}
                  />
                  Percentage of a basis amount
                </label>
                <label className="flex items-center gap-1.5">
                  <input
                    type="radio"
                    checked={typeForm.calculation_method === 'flat_amount'}
                    onChange={() => setTypeForm((f) => ({ ...f, calculation_method: 'flat_amount' }))}
                  />
                  Direct amount
                </label>
              </div>

              {typeForm.calculation_method === 'percentage' && (
                <>
                  <div className="flex gap-4 text-sm">
                    <label className="flex items-center gap-1.5">
                      <input
                        type="radio"
                        checked={typeForm.basis_is_salary}
                        onChange={() => setTypeForm((f) => ({ ...f, basis_is_salary: true }))}
                      />
                      Basis = staff's salary
                    </label>
                    <label className="flex items-center gap-1.5">
                      <input
                        type="radio"
                        checked={!typeForm.basis_is_salary}
                        onChange={() => setTypeForm((f) => ({ ...f, basis_is_salary: false }))}
                      />
                      Basis = manual entry
                    </label>
                  </div>
                  <NumInput
                    label="Default Percentage (%)"
                    value={typeForm.default_percentage}
                    onChange={(n) => setTypeForm((f) => ({ ...f, default_percentage: n }))}
                  />
                </>
              )}

              <div className="flex justify-end gap-2">
                {editingType && <Button variant="outline" onClick={closeTypeForm} disabled={savingType}>Cancel</Button>}
                <Button onClick={handleSaveType} disabled={savingType || !typeForm.label.trim()}>
                  {savingType ? 'Saving…' : editingType ? 'Save Changes' : 'Add Type'}
                </Button>
              </div>
            </div>

            <div className="space-y-2">
              {bonusTypes.map((t) => (
                <div key={t.key} className="flex items-center justify-between gap-2 py-1.5 border-b border-border/50 last:border-0">
                  <div className={t.is_active ? '' : 'opacity-50'}>
                    <p className="text-sm font-medium">{t.label}</p>
                    <p className="text-xs text-muted-foreground">
                      {t.calculation_method === 'flat_amount' ? 'Direct amount' : `${t.default_percentage}% of ${t.basis_is_salary ? "salary" : 'manual entry'}`}
                      {!t.is_active && ' — retired'}
                    </p>
                  </div>
                  <div className="flex gap-1 shrink-0">
                    <button type="button" aria-label="Edit type" onClick={() => openEditType(t)}
                      className="p-1.5 rounded hover:bg-accent text-muted-foreground hover:text-foreground">
                      <Pencil className="h-3.5 w-3.5" />
                    </button>
                    <button type="button" aria-label={t.is_active ? 'Retire type' : 'Reactivate type'} onClick={() => handleToggleTypeActive(t)}
                      className="p-1.5 rounded hover:bg-accent text-muted-foreground hover:text-foreground">
                      {t.is_active ? <Trash2 className="h-3.5 w-3.5" /> : <RotateCcw className="h-3.5 w-3.5" />}
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Delete confirmation */}
      {deleteId !== null && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-sm bg-card rounded-xl shadow-xl border border-border p-6 space-y-4">
            <h2 className="text-base font-semibold">Delete Bonus Record?</h2>
            <p className="text-sm text-muted-foreground">
              If this bonus's payroll month hasn't been processed yet, its amount will stop showing up on that
              staff member's next payroll computation.
            </p>
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => setDeleteId(null)}>Cancel</Button>
              <Button variant="destructive" onClick={() => handleDelete(deleteId)}>Delete</Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function round2(n: number): number {
  return Math.round(n * 100) / 100;
}
