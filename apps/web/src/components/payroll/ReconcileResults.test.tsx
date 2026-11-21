import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ReconcileResults } from './ReconcileResults';
import type { PayrollReconcileLine, PayrollReconcileResult } from '../../api/types';

const base = {
  account_number: null, transaction_ids: [1], paid_to: null, paid_date: null, note: null,
  extra_payment_ids: [] as number[], extra_paid_amount: 0,
  paid_account: null, paid_bank: null, suggested_payments: [], account_source: null, directory_account: null, account_check: null,
  staff_id: null, staff_name: null, computed_net: null, net_difference: null, in_sync: null,
};
const lines: PayrollReconcileLine[] = [
  { ...base, row_number: 2, name: 'Ngozi Williams', expected_amount: 15000, paid_amount: 15000, difference: 0, status: 'matched',
    extra_payment_ids: [8], extra_paid_amount: 15000,
    staff_id: 1, staff_name: 'Ngozi Williams', computed_net: 15000, net_difference: 0, in_sync: true },
  { ...base, row_number: 3, name: 'Chidi Okoro', expected_amount: 20000, paid_amount: 18000, difference: -2000, status: 'underpaid',
    staff_id: 2, staff_name: 'Chidi Okoro', computed_net: 22000, net_difference: 2000, in_sync: false },
  { ...base, row_number: 4, name: 'Grace Balogun', expected_amount: 9000, paid_amount: 0, difference: -9000, status: 'not_paid',
    transaction_ids: [], note: 'Several schedule rows could match the same payment — review manually.' },
];
const RESULT: PayrollReconcileResult = {
  year: 2026, month: 1, lines,
  skipped_rows: [
    { row_number: 7, reason: 'Missing name', ignored: false, label: '' },
    { row_number: 9, reason: 'Looks like a section label', ignored: true, label: 'FULL TIME' },
  ],
  notes: ['No header row found — using column I as the amount to pay (net pay).'],
  unlinked_staff: [{ staff_id: 5, full_name: 'Kemi Ala', computed_net: 10000 }],
  unmatched_transactions: [{ id: 9, date: '2026-01-29', amount: 7000, description: 'Transfer to SOMEONE ELSE', vendor: 'SOMEONE ELSE' }],
  summary: { rows: 3, matched: 1, underpaid: 1, overpaid: 0, not_paid: 1, expected_total: 44000, paid_total: 33000, unmatched_payments: 1, unmatched_total: 7000 },
};

describe('ReconcileResults', () => {
  it('summarises the reconciliation in one line', () => {
    render(<ReconcileResults result={RESULT} />);
    const summary = screen.getByText(/Schedule vs bank — January 2026/);
    expect(summary).toHaveTextContent('1 of 3 matched');
    expect(summary).toHaveTextContent('2 need attention');
    expect(summary).toHaveTextContent('1 possible duplicate payment');
    expect(summary).toHaveTextContent('1 total differ from the staff directory');
    expect(summary).toHaveTextContent('1 staff not on the schedule');
  });

  it('shows each row with its status and directory check', () => {
    render(<ReconcileResults result={RESULT} />);
    expect(screen.getByText('Underpaid', { selector: 'span' })).toBeInTheDocument();
    expect(screen.getByText('Not paid', { selector: 'span' })).toBeInTheDocument();
    expect(screen.getByText('In sync')).toBeInTheDocument();
    expect(screen.getByText('Not in staff directory')).toBeInTheDocument();
    expect(screen.getByText(/review manually/i)).toBeInTheDocument();
    expect(screen.getByText(/Also paid .*15,000.* in 1 other payment — possible duplicate/)).toBeInTheDocument();
  });

  it('lists skipped, ignored and unlinked rows so nobody is lost', () => {
    render(<ReconcileResults result={RESULT} />);
    expect(screen.getByText('Row 7: Missing name')).toBeInTheDocument();
    expect(screen.getByText(/Ignored 1 row that look like labels or totals/)).toHaveTextContent('row 9 “FULL TIME”');
    expect(screen.getByText(/In the staff directory but not on the schedule/)).toHaveTextContent('Kemi Ala');
    expect(screen.getByText('SOMEONE ELSE')).toBeInTheDocument();
    expect(screen.getByRole('note')).toHaveTextContent('using column I as the amount to pay');
  });

  describe('account details to confirm', () => {
    const withAccounts = (): PayrollReconcileResult => ({
      ...RESULT,
      lines: [
        { ...lines[0], account_check: 'differs', paid_account: '7038692765', paid_bank: 'OPay', paid_to: 'PATRICIA NKECHI OGOGO', directory_account: '0999999999' },
        { ...lines[2], staff_id: 12, staff_name: 'Jonathan Ogogo', suggested_payments: [
          { id: 2720, date: '2026-08-28', amount: 50000, vendor: 'PATRICIA NKECHI OGOGO', account: '7038692765', bank: 'OPay' },
        ] },
      ],
    });

    it('offers to save the bank\'s account for a mismatch and for an unclaimed payment', () => {
      const onUseAccount = vi.fn();
      render(<ReconcileResults result={withAccounts()} onUseAccount={onUseAccount} />);
      expect(screen.getByText(/2 accounts to confirm/)).toBeInTheDocument();
      expect(screen.getByText(/the directory has 0999999999/)).toBeInTheDocument();

      fireEvent.click(screen.getByRole('button', { name: /Use the bank's account for Ngozi Williams/ }));
      expect(onUseAccount).toHaveBeenCalledWith({ staffId: 1, staffName: 'Ngozi Williams', account: '7038692765', bank: 'OPay', holder: 'PATRICIA NKECHI OGOGO' });

      fireEvent.click(screen.getByRole('button', { name: /That is Jonathan Ogogo's account/ }));
      expect(onUseAccount).toHaveBeenLastCalledWith({ staffId: 12, staffName: 'Jonathan Ogogo', account: '7038692765', bank: 'OPay', holder: 'PATRICIA NKECHI OGOGO' });
    });

    it('shows the problems but no buttons when nothing can be saved', () => {
      render(<ReconcileResults result={withAccounts()} />);
      expect(screen.getByText(/Confirm account details/)).toBeInTheDocument();
      expect(screen.queryByRole('button')).not.toBeInTheDocument();
    });
  });

  it('offers a deduction when the schedule pays less, and a bonus when it pays more', () => {
    const onAddBonus = vi.fn();
    const onAddDeduction = vi.fn();
    const more = { ...lines[1], row_number: 5, name: 'Kemi Ala', staff_id: 3, staff_name: 'Kemi Ala', computed_net: 10000, net_difference: -5000 };
    render(<ReconcileResults result={{ ...RESULT, lines: [lines[1], more] }} onAddBonus={onAddBonus} onAddDeduction={onAddDeduction} />);
    fireEvent.click(screen.getByRole('button', { name: /Deduct ₦2,000/ }));
    expect(onAddDeduction).toHaveBeenCalledWith(2, 2000);
    fireEvent.click(screen.getByRole('button', { name: /Add ₦5,000.00 as bonus/ }));
    expect(onAddBonus).toHaveBeenCalledWith(3, 5000);
  });

  it('shows when the schedule was saved', () => {
    render(<ReconcileResults result={{ ...RESULT, saved_at: '2026-01-31T10:00:00' }} />);
    expect(screen.getByText(/Schedule vs bank — January 2026/)).toHaveTextContent('saved');
  });
});
