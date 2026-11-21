import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { Payroll } from './Payroll';
import { computePayroll, getNextPayrollMonth, listStaffMembers, processPayroll, reconcilePayroll, updateStaffMember } from '../api/client';
import type { PayrollLine, PayrollReconcileLine, PayrollReconcileResult, StaffMember } from '../api/types';

vi.mock('../api/client', () => ({
  computePayroll: vi.fn(),
  getNextPayrollMonth: vi.fn(),
  processPayroll: vi.fn(),
  resetPayroll: vi.fn(),
  listStaffMembers: vi.fn(),
  updateStaffMember: vi.fn(),
  reconcilePayroll: vi.fn(),
}));

const staffLine = (id: number, name: string, gross: number): PayrollLine => ({
  staff_id: id, full_name: name, role: null, gross_salary: gross, bonus: 0, loan_deduction: 0,
  advance_deduction: 0, other_deductions: 0, net_salary: gross, is_paid: false, paid_date: null,
  entry_id: null, transaction_id: null, paid_amount: null,
});

const scheduleLine = (id: number, name: string, amount: number, over: Partial<PayrollReconcileLine> = {}): PayrollReconcileLine => ({
  row_number: id, name, account_number: null, expected_amount: amount, paid_amount: amount, difference: 0,
  status: 'matched', transaction_ids: [id], paid_to: name, paid_date: '2026-03-30', note: null,
  extra_payment_ids: [], extra_paid_amount: 0, paid_account: null, paid_bank: null, suggested_payments: [], account_source: null, directory_account: null, account_check: null,
  staff_id: id, staff_name: name, computed_net: amount, net_difference: 0, in_sync: true, ...over,
});

const result = (lines: PayrollReconcileLine[]): PayrollReconcileResult => ({
  year: 2026, month: 3, lines, skipped_rows: [], notes: [], unlinked_staff: [], unmatched_transactions: [],
  summary: { rows: lines.length, matched: lines.length, underpaid: 0, overpaid: 0, not_paid: 0, expected_total: 0, paid_total: 0, unmatched_payments: 0, unmatched_total: 0 },
});

const loadSchedule = async () => {
  fireEvent.change(screen.getByLabelText('Payroll schedule'), { target: { files: [new File(['x'], 's.xlsx')] } });
  fireEvent.click(screen.getByRole('button', { name: /^reconcile$/i }));
  await waitFor(() => expect(reconcilePayroll).toHaveBeenCalled());
};
const processButton = () => screen.findByRole('button', { name: /process payroll/i });

// This test environment has no working localStorage; Payroll keeps its "skip" flags there.
const memoryStorage = () => {
  const store = new Map<string, string>();
  return {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => { store.set(k, String(v)); },
    removeItem: (k: string) => { store.delete(k); },
    clear: () => store.clear(),
  };
};

describe('Payroll page', () => {
  beforeEach(() => {
    vi.stubGlobal('localStorage', memoryStorage());
    vi.mocked(getNextPayrollMonth).mockReset();
    vi.mocked(computePayroll).mockReset();
    vi.mocked(getNextPayrollMonth).mockResolvedValue({ year: 2026, month: 3 });
    vi.mocked(computePayroll).mockResolvedValue([staffLine(1, 'Ada Obi', 15000), staffLine(2, 'Bola Eze', 20000)]);
    vi.mocked(processPayroll).mockReset();
    vi.mocked(reconcilePayroll).mockReset();
  });

  it('opens on the first month whose payroll is not complete', async () => {
    render(<Payroll />);
    expect(await screen.findByText('March 2026 Payroll')).toBeInTheDocument();
    expect(computePayroll).toHaveBeenCalledTimes(1);
    expect(computePayroll).toHaveBeenCalledWith(2026, 3);
  });

  it('falls back to the current month when the start month cannot be fetched', async () => {
    vi.mocked(getNextPayrollMonth).mockRejectedValue(new Error('offline'));
    render(<Payroll />);
    const now = new Date();
    await waitFor(() => expect(computePayroll).toHaveBeenCalledWith(now.getFullYear(), now.getMonth() + 1));
  });

  it('cannot process until the schedule is loaded', async () => {
    render(<Payroll />);
    expect(await processButton()).toBeDisabled();
    expect(screen.getByText(/Load the payroll schedule above/)).toBeInTheDocument();
  });

  it('processes with the schedule once every pending teacher matches the schedule and the bank', async () => {
    vi.mocked(reconcilePayroll).mockResolvedValue(result([scheduleLine(1, 'Ada Obi', 15000), scheduleLine(2, 'Bola Eze', 20000)]));
    vi.mocked(processPayroll).mockResolvedValue([]);
    render(<Payroll />);
    await screen.findByText('March 2026 Payroll');
    await loadSchedule();

    const button = await processButton();
    await waitFor(() => expect(button).toBeEnabled());
    fireEvent.click(button);

    await waitFor(() => expect(processPayroll).toHaveBeenCalled());
    const [year, month, lines, , schedule] = vi.mocked(processPayroll).mock.calls[0];
    expect([year, month]).toEqual([2026, 3]);
    expect(lines.map((l) => l.staff_id)).toEqual([1, 2]);
    expect(lines.every((l) => l.transaction_id === undefined)).toBe(true);
    expect(schedule).toEqual([
      { row_number: 1, name: 'Ada Obi', amount: 15000, account_number: null },
      { row_number: 2, name: 'Bola Eze', amount: 20000, account_number: null },
    ]);
    // the month is reloaded after a successful process, and no error is shown
    await waitFor(() => expect(computePayroll).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('blocks processing while a teacher is underpaid, or the payroll total differs from the schedule', async () => {
    vi.mocked(reconcilePayroll).mockResolvedValue(result([
      scheduleLine(1, 'Ada Obi', 15000, { status: 'underpaid', paid_amount: 12000 }),
      scheduleLine(2, 'Bola Eze', 18000),   // bank agrees with the schedule, the directory says 20,000
    ]));
    render(<Payroll />);
    await screen.findByText('March 2026 Payroll');
    await loadSchedule();

    expect(await screen.findByText('Underpaid (₦12,000.00)')).toBeInTheDocument();
    expect(screen.getByText(/Total differs by/)).toBeInTheDocument();
    expect(screen.getByText(/2 staff need attention before processing/)).toBeInTheDocument();
    expect(await processButton()).toBeDisabled();
  });

  it('lets the user skip the blocked staff and process the rest', async () => {
    vi.mocked(reconcilePayroll).mockResolvedValue(result([scheduleLine(1, 'Ada Obi', 15000, { status: 'not_paid', paid_amount: 0 }), scheduleLine(2, 'Bola Eze', 20000)]));
    vi.mocked(processPayroll).mockResolvedValue([]);
    render(<Payroll />);
    await screen.findByText('March 2026 Payroll');
    await loadSchedule();

    fireEvent.click((await screen.findAllByRole('button', { name: 'Skip' }))[0]);
    const button = await processButton();
    await waitFor(() => expect(button).toBeEnabled());
    fireEvent.click(button);
    await waitFor(() => expect(processPayroll).toHaveBeenCalled());
    expect(vi.mocked(processPayroll).mock.calls[0][2].map((l) => l.staff_id)).toEqual([2]);
  });

  it('lists the server\'s reasons when it refuses to process', async () => {
    vi.mocked(reconcilePayroll).mockResolvedValue(result([scheduleLine(1, 'Ada Obi', 15000), scheduleLine(2, 'Bola Eze', 20000)]));
    vi.mocked(processPayroll).mockRejectedValue({ response: { status: 422, data: { detail: {
      message: 'Cannot process payroll: 1 staff member(s) do not agree with the schedule and bank payments',
      issues: [{ staff_id: 1, full_name: 'Ada Obi', kind: 'underpaid', message: 'Bank paid ₦12,000.00, ₦3,000.00 less than the schedule (₦15,000.00).', expected: 15000, paid: 12000, computed: null }],
    } } } });
    render(<Payroll />);
    await screen.findByText('March 2026 Payroll');
    await loadSchedule();
    const button = await processButton();
    await waitFor(() => expect(button).toBeEnabled());
    fireEvent.click(button);

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Cannot process payroll');
    expect(alert).toHaveTextContent('Ada Obi');
    expect(alert).toHaveTextContent('3,000.00 less than the schedule');
  });

  describe('deactivating staff who are no longer employed', () => {
    const member = { id: 1, full_name: 'Ada Obi', role: null, bank_name: null, account_number: null, monthly_gross: 15000,
      start_date: null, end_date: null, is_active: true, notes: null, created_at: '', updated_at: '' } as StaffMember;

    beforeEach(() => {
      vi.mocked(listStaffMembers).mockReset().mockResolvedValue([member]);
      vi.mocked(updateStaffMember).mockReset().mockResolvedValue({ ...member, is_active: false });
    });

    it('deactivates in the directory after confirming, then reloads the month', async () => {
      vi.spyOn(window, 'confirm').mockReturnValue(true);
      render(<Payroll />);
      await screen.findByText('March 2026 Payroll');
      fireEvent.click((await screen.findAllByRole('button', { name: 'Deactivate' }))[0]);

      await waitFor(() => expect(updateStaffMember).toHaveBeenCalledWith(1, expect.objectContaining({ full_name: 'Ada Obi', is_active: false })));
      await waitFor(() => expect(computePayroll).toHaveBeenCalledTimes(2));
    });

    it('does nothing when the confirmation is cancelled', async () => {
      vi.spyOn(window, 'confirm').mockReturnValue(false);
      render(<Payroll />);
      await screen.findByText('March 2026 Payroll');
      fireEvent.click((await screen.findAllByRole('button', { name: 'Deactivate' }))[0]);
      expect(updateStaffMember).not.toHaveBeenCalled();
    });

    it('reports a failure instead of silently continuing', async () => {
      vi.spyOn(window, 'confirm').mockReturnValue(true);
      vi.mocked(updateStaffMember).mockRejectedValue(new Error('boom'));
      render(<Payroll />);
      await screen.findByText('March 2026 Payroll');
      fireEvent.click((await screen.findAllByRole('button', { name: 'Deactivate' }))[0]);
      expect(await screen.findByRole('alert')).toHaveTextContent('Could not deactivate Ada Obi');
    });
  });

  describe('using the bank\'s account', () => {
    const jonathan = { id: 1, full_name: 'Ada Obi', role: null, bank_name: null, account_number: null, monthly_gross: 15000,
      start_date: null, end_date: null, is_active: true, notes: null, created_at: '', updated_at: '' } as StaffMember;

    const withMismatch = () => result([scheduleLine(1, 'Ada Obi', 15000, {
      account_check: 'missing', paid_account: '7038692765', paid_bank: 'OPay', paid_to: 'PATRICIA NKECHI OGOGO',
    }), scheduleLine(2, 'Bola Eze', 20000)]);

    beforeEach(() => {
      vi.mocked(listStaffMembers).mockReset().mockResolvedValue([jonathan]);
      vi.mocked(updateStaffMember).mockReset().mockResolvedValue({ ...jonathan, account_number: '7038692765' });
      vi.mocked(reconcilePayroll).mockResolvedValue(withMismatch());
    });

    it('saves the bank account to the directory after confirming, then re-reconciles', async () => {
      const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true);
      render(<Payroll />);
      await screen.findByText('March 2026 Payroll');
      await loadSchedule();
      fireEvent.click(await screen.findByRole('button', { name: /Use the bank's account for Ada Obi/ }));

      await waitFor(() => expect(updateStaffMember).toHaveBeenCalledWith(1, expect.objectContaining({ account_number: '7038692765', bank_name: 'OPay' })));
      // the prompt shows exactly what changes and warns about an unrelated account holder
      const message = confirm.mock.calls[0][0] as string;
      expect(message).toContain('Account: none → 7038692765');
      expect(message).toContain('Bank: none → OPay');
      expect(message).toContain('WARNING: that name does not look like Ada Obi');
      await waitFor(() => expect(reconcilePayroll).toHaveBeenCalledTimes(2));
    });

    it('warns when the account is already saved for another staff member', async () => {
      const other = { ...jonathan, id: 9, full_name: 'Bola Eze', account_number: '7038692765' } as StaffMember;
      vi.mocked(listStaffMembers).mockResolvedValue([jonathan, other]);
      const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
      render(<Payroll />);
      await screen.findByText('March 2026 Payroll');
      await loadSchedule();
      fireEvent.click(await screen.findByRole('button', { name: /Use the bank's account for Ada Obi/ }));
      await waitFor(() => expect(confirm).toHaveBeenCalled());
      expect(confirm.mock.calls[0][0]).toContain('WARNING: this account is already saved for Bola Eze');
    });

    it('changes nothing when the confirmation is cancelled', async () => {
      vi.spyOn(window, 'confirm').mockReturnValue(false);
      render(<Payroll />);
      await screen.findByText('March 2026 Payroll');
      await loadSchedule();
      fireEvent.click(await screen.findByRole('button', { name: /Use the bank's account for Ada Obi/ }));
      expect(updateStaffMember).not.toHaveBeenCalled();
      expect(reconcilePayroll).toHaveBeenCalledTimes(1);
    });
  });
});
