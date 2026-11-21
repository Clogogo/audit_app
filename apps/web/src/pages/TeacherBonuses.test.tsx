import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { TeacherBonuses } from './TeacherBonuses';
import { createTeacherBonus, listTeacherBonuses, updateTeacherBonus } from '../api/client';
import type { BonusType, StaffMember, TeacherBonus } from '../api/types';

vi.mock('../api/client', () => ({
  listTeacherBonuses: vi.fn(), deleteTeacherBonus: vi.fn(), getBonusTypes: vi.fn(), createBonusType: vi.fn(),
  updateBonusType: vi.fn(), deleteBonusType: vi.fn(), listStaffMembers: vi.fn(), getTerms: vi.fn(),
  createTeacherBonus: vi.fn(), updateTeacherBonus: vi.fn(),
}));

import { deleteTeacherBonus, getBonusTypes, getTerms, listStaffMembers } from '../api/client';

const ada = { id: 1, full_name: 'Ada Obi', role: null, monthly_gross: 25000 } as StaffMember;
const award = { id: 1, key: 'award', label: 'Award', description: null, calculation_method: 'percentage', basis_is_salary: true, default_percentage: 100, is_active: true } as BonusType;
const record = { id: 7, staff_id: 1, staff_name: 'Ada Obi', bonus_type: 'award', percentage: 100, basis_amount: 25000, amount: 25000,
  frequency: 'onetime', period_year: 2026, period_month: 7, end_year: null, end_month: null, term_id: null, term_name: null,
  notes: 'Top teacher', created_at: '', updated_at: '' } as TeacherBonus;

describe('TeacherBonuses page', () => {
  beforeEach(() => {
    vi.mocked(listTeacherBonuses).mockReset().mockResolvedValue([record]);
    vi.mocked(getBonusTypes).mockReset().mockResolvedValue([award]);
    vi.mocked(listStaffMembers).mockReset().mockResolvedValue([ada]);
    vi.mocked(getTerms).mockReset().mockResolvedValue([]);
    vi.mocked(createTeacherBonus).mockReset().mockResolvedValue(record);
    vi.mocked(updateTeacherBonus).mockReset().mockResolvedValue(record);
    vi.mocked(deleteTeacherBonus).mockReset();
  });

  it('lists the bonus records', async () => {
    render(<TeacherBonuses />);
    expect(await screen.findByText('Top teacher')).toBeInTheDocument();
    expect(screen.getByText('July 2026')).toBeInTheDocument();
  });

  it('adds a bonus through the shared form and reloads the list', async () => {
    render(<TeacherBonuses />);
    await screen.findByText('Top teacher');
    fireEvent.click(screen.getByRole('button', { name: /Add Bonus/ }));
    await screen.findByRole('dialog', { name: 'Add Bonus' });
    fireEvent.change(screen.getByTitle('Select staff member'), { target: { value: '1' } });
    fireEvent.change(screen.getByTitle('Select bonus type'), { target: { value: 'award' } });
    fireEvent.click(screen.getAllByRole('button', { name: 'Add Bonus' }).find((b) => b.closest('[role="dialog"]'))!);

    await waitFor(() => expect(createTeacherBonus).toHaveBeenCalledWith(expect.objectContaining({ staff_id: 1, bonus_type: 'award', percentage: 100, basis_amount: 25000 })));
    await waitFor(() => expect(listTeacherBonuses).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole('dialog', { name: 'Add Bonus' })).not.toBeInTheDocument();
  });

  it('edits an existing bonus through the same form', async () => {
    render(<TeacherBonuses />);
    await screen.findByText('Top teacher');
    fireEvent.click(screen.getByRole('button', { name: 'Edit' }));
    await screen.findByRole('dialog', { name: 'Edit Bonus' });
    fireEvent.click(screen.getByRole('button', { name: 'Save Changes' }));
    await waitFor(() => expect(updateTeacherBonus).toHaveBeenCalledWith(7, expect.objectContaining({ staff_id: 1, period_month: 7 })));
  });
});
