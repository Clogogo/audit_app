import { useEffect, useState } from 'react';
import { Gift, Plus, Pencil, Trash2, XCircle, AlertCircle, Settings, RotateCcw } from 'lucide-react';
import {
  listTeacherBonuses, deleteTeacherBonus,
  getBonusTypes, createBonusType, updateBonusType, deleteBonusType, listStaffMembers, getTerms,
} from '../api/client';
import type { TeacherBonus, BonusType, BonusTypeIn, StaffMember, Term } from '../api/types';
import { BonusFormModal } from '../components/BonusFormModal';
import { NumInput } from '../components/NumInput';
import { Button } from '../components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { formatCurrency } from '../lib/utils';

const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
];

const emptyTypeForm = (): BonusTypeIn => ({
  label: '',
  description: '',
  calculation_method: 'percentage',
  basis_is_salary: true,
  default_percentage: 0,
  is_active: true,
});

export function TeacherBonuses() {
  const [bonuses, setBonuses] = useState<TeacherBonus[]>([]);
  const [staffList, setStaffList] = useState<StaffMember[]>([]);
  const [bonusTypes, setBonusTypes] = useState<BonusType[]>([]);
  const [terms, setTerms] = useState<Term[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [staffFilter, setStaffFilter] = useState('all');
  const [typeFilter, setTypeFilter] = useState('all');

  // the add/edit form (shared with the Payroll page)
  const [formFor, setFormFor] = useState<{ editing: TeacherBonus | null } | null>(null);
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

  const openAdd = () => setFormFor({ editing: null });
  const openEdit = (b: TeacherBonus) => setFormFor({ editing: b });

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
  const typeLabel = (key: string) => bonusTypes.find((t) => t.key === key)?.label ?? key;

  const periodLabel = (b: TeacherBonus) => {
    if (b.frequency !== 'monthly') return `${MONTHS[b.period_month - 1]} ${b.period_year}`;
    const start = `${MONTHS[b.period_month - 1]} ${b.period_year}`;
    if (b.end_year === null || b.end_month === null) return `Monthly, since ${start}`;
    return `Monthly, ${start} – ${MONTHS[b.end_month - 1]} ${b.end_year}`;
  };

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
                      <th className="text-left py-2 pr-3 font-medium">Period</th>
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
                        <td className="py-3 pr-3 text-muted-foreground">{periodLabel(b)}</td>
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

      {formFor && (
        <BonusFormModal
          staffList={staffList}
          bonusTypes={bonusTypes}
          terms={terms}
          editing={formFor.editing}
          onClose={() => setFormFor(null)}
          onSaved={() => { setFormFor(null); load(); }}
        />
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
