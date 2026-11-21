import { useState } from 'react';
import { XCircle } from 'lucide-react';
import { createTeacherBonus, updateTeacherBonus } from '../api/client';
import type { BonusType, StaffMember, TeacherBonus, TeacherBonusIn, Term } from '../api/types';
import { formatCurrency } from '../lib/utils';
import { NumInput } from './NumInput';
import { Button } from './ui/button';

const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
];

const round2 = (n: number) => Math.round(n * 100) / 100;

export interface BonusDefaults { staffId?: number; year?: number; month?: number }

interface BonusFormModalProps {
  staffList: StaffMember[];
  bonusTypes: BonusType[];
  terms: Term[];
  /** edit this record; omit to add a new one */
  editing?: TeacherBonus | null;
  /** prefill for a new bonus (e.g. from the Payroll page) */
  defaults?: BonusDefaults;
  onSaved: () => void;
  onClose: () => void;
}

const initialForm = (editing: TeacherBonus | null | undefined, defaults: BonusDefaults | undefined): TeacherBonusIn => {
  if (editing) {
    return {
      staff_id: editing.staff_id, bonus_type: editing.bonus_type, percentage: editing.percentage,
      basis_amount: editing.basis_amount, frequency: editing.frequency, period_year: editing.period_year,
      period_month: editing.period_month, end_year: editing.end_year, end_month: editing.end_month,
      term_id: editing.term_id, notes: editing.notes ?? '',
    };
  }
  const now = new Date();
  return {
    staff_id: defaults?.staffId ?? 0, bonus_type: '', percentage: 0, basis_amount: 0, frequency: 'onetime',
    period_year: defaults?.year ?? now.getFullYear(), period_month: defaults?.month ?? now.getMonth() + 1,
    end_year: null, end_month: null, term_id: null, notes: '',
  };
};

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

const SELECT = 'w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring';

/** The add/edit bonus form, shared by the Bonuses page and the Payroll page. */
export function BonusFormModal({ staffList, bonusTypes, terms, editing, defaults, onSaved, onClose }: BonusFormModalProps) {
  const [form, setForm] = useState<TeacherBonusIn>(() => initialForm(editing, defaults));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

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

  const handleSave = async () => {
    if (!form.staff_id || !form.bonus_type || form.percentage < 0 || form.basis_amount < 0) return;
    setSaving(true);
    setError(null);
    try {
      if (editing) {
        await updateTeacherBonus(editing.id, form);
      } else {
        await createTeacherBonus(form);
      }
      onSaved();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'Failed to save bonus');
    } finally {
      setSaving(false);
    }
  };

  const selectedType = bonusTypes.find((t) => t.key === form.bonus_type);
  const previewAmount = round2((form.percentage / 100) * form.basis_amount);
  // Retired types stay selectable only if they're already on the record
  // being edited — otherwise the dropdown would silently blank out.
  const typeOptions = bonusTypes.filter((t) => t.is_active || t.key === form.bonus_type);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div role="dialog" aria-label={editing ? 'Edit Bonus' : 'Add Bonus'}
        className="w-full max-w-md bg-card rounded-xl shadow-xl border border-border p-6 space-y-5 max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold">{editing ? 'Edit Bonus' : 'Add Bonus'}</h2>
          <button type="button" aria-label="Close" onClick={onClose} className="text-muted-foreground hover:text-foreground">
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
              className={SELECT}
            >
              <option value="">— Select staff —</option>
              {staffList.map((s) => (
                <option key={s.id} value={s.id}>{s.full_name}{s.role ? ` (${s.role})` : ''}</option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-xs font-medium text-foreground mb-1">Bonus Type *</label>
            <select title="Select bonus type" value={form.bonus_type} onChange={(e) => applyType(e.target.value)} className={SELECT}>
              <option value="">— Select type —</option>
              {typeOptions.map((t) => <option key={t.key} value={t.key}>{t.label}</option>)}
            </select>
            {selectedType && <p className="text-xs text-muted-foreground mt-1">{selectedType.description}</p>}
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

          <div>
            <label className="block text-xs font-medium text-foreground mb-1">Frequency *</label>
            <div className="flex gap-4 text-sm">
              <label className="flex items-center gap-1.5">
                <input type="radio" name="bonus-frequency" checked={form.frequency === 'onetime'}
                  onChange={() => setForm((f) => ({ ...f, frequency: 'onetime', end_year: null, end_month: null }))} />
                One-time payment
              </label>
              <label className="flex items-center gap-1.5">
                <input type="radio" name="bonus-frequency" checked={form.frequency === 'monthly'}
                  onChange={() => setForm((f) => ({ ...f, frequency: 'monthly' }))} />
                Monthly payment
              </label>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-foreground mb-1">
                {form.frequency === 'monthly' ? 'Start Month *' : 'Payroll Month *'}
              </label>
              <select
                title="Payroll month"
                value={form.period_month}
                onChange={(e) => setForm((f) => ({ ...f, period_month: parseInt(e.target.value, 10) }))}
                className={SELECT}
              >
                {MONTHS.map((m, i) => <option key={m} value={i + 1}>{m}</option>)}
              </select>
            </div>
            <NumInput
              label={form.frequency === 'monthly' ? 'Start Year' : 'Payroll Year'}
              value={form.period_year}
              onChange={(n) => setForm((f) => ({ ...f, period_year: n }))}
            />
          </div>

          {form.frequency === 'monthly' && (
            <div className="space-y-2 rounded-md border border-border p-3">
              <label className="flex items-center gap-1.5 text-sm">
                <input
                  type="checkbox"
                  checked={form.end_year === null}
                  onChange={(e) => {
                    if (e.target.checked) {
                      setForm((f) => ({ ...f, end_year: null, end_month: null }));
                    } else {
                      setForm((f) => ({ ...f, end_year: f.period_year, end_month: f.period_month }));
                    }
                  }}
                />
                No end date (recurs indefinitely)
              </label>
              {form.end_year !== null && (
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-xs font-medium text-foreground mb-1">End Month</label>
                    <select
                      title="End month"
                      value={form.end_month ?? form.period_month}
                      onChange={(e) => setForm((f) => ({ ...f, end_month: parseInt(e.target.value, 10) }))}
                      className={SELECT}
                    >
                      {MONTHS.map((m, i) => <option key={m} value={i + 1}>{m}</option>)}
                    </select>
                  </div>
                  <NumInput label="End Year" value={form.end_year ?? form.period_year}
                    onChange={(n) => setForm((f) => ({ ...f, end_year: n }))} />
                </div>
              )}
            </div>
          )}

          <div>
            <label className="block text-xs font-medium text-foreground mb-1">Term (optional)</label>
            <select
              title="Term"
              value={form.term_id ?? ''}
              onChange={(e) => setForm((f) => ({ ...f, term_id: e.target.value ? parseInt(e.target.value, 10) : null }))}
              className={SELECT}
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
              className={SELECT}
            />
          </div>
        </div>

        {error && <p role="alert" className="text-sm text-destructive">{error}</p>}

        <div className="flex justify-end gap-2 pt-2">
          <Button variant="outline" onClick={onClose} disabled={saving}>Cancel</Button>
          <Button onClick={handleSave} disabled={saving || !form.staff_id || !form.bonus_type}>
            {saving ? 'Saving…' : editing ? 'Save Changes' : 'Add Bonus'}
          </Button>
        </div>
      </div>
    </div>
  );
}
