import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { BonusFormModal } from './BonusFormModal';
import { createTeacherBonus, updateTeacherBonus } from '../api/client';
import type { BonusType, StaffMember, TeacherBonus } from '../api/types';

vi.mock('../api/client', () => ({ createTeacherBonus: vi.fn(), updateTeacherBonus: vi.fn() }));

const ada = { id: 1, full_name: 'Ada Obi', role: 'Teacher', monthly_gross: 25000 } as StaffMember;
const flat = { id: 1, key: 'one_time', label: 'One time Bonus', description: null, calculation_method: 'flat_amount', basis_is_salary: true, default_percentage: 0, is_active: true } as BonusType;
const pct = { id: 2, key: 'award', label: 'Award', description: null, calculation_method: 'percentage', basis_is_salary: true, default_percentage: 100, is_active: true } as BonusType;

const renderModal = (props: Partial<Parameters<typeof BonusFormModal>[0]> = {}) => {
  const onSaved = vi.fn();
  const onClose = vi.fn();
  render(<BonusFormModal staffList={[ada]} bonusTypes={[flat, pct]} terms={[]} onSaved={onSaved} onClose={onClose} {...props} />);
  return { onSaved, onClose };
};

describe('BonusFormModal', () => {
  beforeEach(() => {
    vi.mocked(createTeacherBonus).mockReset().mockResolvedValue({} as never);
    vi.mocked(updateTeacherBonus).mockReset().mockResolvedValue({} as never);
  });

  it('cannot be saved until a staff member and a type are chosen', () => {
    renderModal();
    expect(screen.getByRole('button', { name: 'Add Bonus' })).toBeDisabled();
  });

  it('is prefilled from the defaults and saves a percentage-of-salary bonus', async () => {
    const { onSaved } = renderModal({ defaults: { staffId: 1, year: 2026, month: 8 } });
    expect((screen.getByTitle('Select staff member') as HTMLSelectElement).value).toBe('1');
    expect((screen.getByTitle('Payroll month') as HTMLSelectElement).value).toBe('8');
    fireEvent.change(screen.getByTitle('Select bonus type'), { target: { value: 'award' } });   // 100% of salary
    expect(screen.getByText(/Computed bonus:/)).toHaveTextContent('25,000');
    fireEvent.click(screen.getByRole('button', { name: 'Add Bonus' }));
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(createTeacherBonus).toHaveBeenCalledWith(expect.objectContaining({
      staff_id: 1, bonus_type: 'award', percentage: 100, basis_amount: 25000, frequency: 'onetime', period_year: 2026, period_month: 8,
    }));
  });

  it('updates an existing record when editing', async () => {
    const record = { id: 7, staff_id: 1, bonus_type: 'award', percentage: 50, basis_amount: 25000, frequency: 'onetime',
      period_year: 2026, period_month: 7, end_year: null, end_month: null, term_id: null, notes: 'x' } as TeacherBonus;
    const { onSaved } = renderModal({ editing: record });
    fireEvent.click(screen.getByRole('button', { name: 'Save Changes' }));
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(updateTeacherBonus).toHaveBeenCalledWith(7, expect.objectContaining({ percentage: 50, period_month: 7 }));
    expect(createTeacherBonus).not.toHaveBeenCalled();
  });

  it('shows the server reason and stays open when saving fails', async () => {
    vi.mocked(createTeacherBonus).mockRejectedValue({ response: { data: { detail: 'Not allowed' } } });
    const { onSaved } = renderModal({ defaults: { staffId: 1 } });
    fireEvent.change(screen.getByTitle('Select bonus type'), { target: { value: 'award' } });
    fireEvent.click(screen.getByRole('button', { name: 'Add Bonus' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Not allowed');
    expect(onSaved).not.toHaveBeenCalled();
  });

  it('closes without saving', () => {
    const { onClose } = renderModal();
    fireEvent.click(screen.getByRole('button', { name: 'Close' }));
    expect(onClose).toHaveBeenCalled();
    expect(createTeacherBonus).not.toHaveBeenCalled();
  });
});
