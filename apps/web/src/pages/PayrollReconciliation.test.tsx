import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { PayrollReconciliation, extractErrorMessage } from './PayrollReconciliation';
import { getBankAccounts, reconcilePayroll } from '../api/client';
import type { PayrollReconcileResult } from '../api/types';

vi.mock('../api/client', () => ({
  getBankAccounts: vi.fn(),
  reconcilePayroll: vi.fn(),
}));

const RESULT: PayrollReconcileResult = {
  year: 2026,
  month: 1,
  lines: [
    {
      row_number: 2, name: 'Ngozi Williams', account_number: null, expected_amount: 15000, paid_amount: 15000,
      difference: 0, status: 'matched', transaction_ids: [1], paid_to: 'NGOZI WILLIAMS', paid_date: '2026-01-30', note: null,
    },
    {
      row_number: 3, name: 'Chidi Okoro', account_number: null, expected_amount: 20000, paid_amount: 18000,
      difference: -2000, status: 'underpaid', transaction_ids: [2], paid_to: 'CHIDI OKORO', paid_date: '2026-01-30', note: null,
    },
    {
      row_number: 4, name: 'Grace Balogun', account_number: null, expected_amount: 9000, paid_amount: 0,
      difference: -9000, status: 'not_paid', transaction_ids: [], paid_to: null, paid_date: null,
      note: 'Several schedule rows could match the same payment — review manually.',
    },
  ],
  skipped_rows: [{ row_number: 7, reason: 'Missing name' }],
  unmatched_transactions: [
    { id: 9, date: '2026-01-29', amount: 7000, description: 'Transfer to SOMEONE ELSE', vendor: 'SOMEONE ELSE' },
  ],
  summary: {
    rows: 3, matched: 1, underpaid: 1, overpaid: 0, not_paid: 1,
    expected_total: 44000, paid_total: 33000, unmatched_payments: 1, unmatched_total: 7000,
  },
};

function chooseFile() {
  const input = screen.getByLabelText('Payroll schedule') as HTMLInputElement;
  const file = new File(['x'], 'jan.xlsx');
  fireEvent.change(input, { target: { files: [file] } });
  return file;
}

describe('PayrollReconciliation', () => {
  beforeEach(() => {
    vi.mocked(getBankAccounts).mockResolvedValue([]);
    vi.mocked(reconcilePayroll).mockReset();
  });

  it('keeps Reconcile disabled until a file is chosen', () => {
    render(<PayrollReconciliation />);
    expect(screen.getByRole('button', { name: /reconcile/i })).toBeDisabled();
    chooseFile();
    expect(screen.getByRole('button', { name: /reconcile/i })).toBeEnabled();
  });

  it('uploads the file for the selected month and shows the results', async () => {
    vi.mocked(reconcilePayroll).mockResolvedValue(RESULT);
    render(<PayrollReconciliation />);
    const file = chooseFile();
    fireEvent.click(screen.getByRole('button', { name: /reconcile/i }));

    expect(await screen.findByText('Chidi Okoro')).toBeInTheDocument();
    const now = new Date();
    expect(reconcilePayroll).toHaveBeenCalledWith(file, now.getFullYear(), now.getMonth() + 1, undefined);
    expect(screen.getByText('Underpaid', { selector: 'span' })).toBeInTheDocument();
    expect(screen.getByText('Not paid', { selector: 'span' })).toBeInTheDocument();
    expect(screen.getByText('SOMEONE ELSE')).toBeInTheDocument();
    expect(screen.getByText('1 of 3')).toBeInTheDocument();
    expect(screen.getByText('Results for January 2026')).toBeInTheDocument();
    expect(screen.getByText('Row 7: Missing name')).toBeInTheDocument();
    expect(screen.getByText(/review manually/i)).toBeInTheDocument();
  });

  it('ignores a response that arrives after the month was changed', async () => {
    let resolve!: (r: PayrollReconcileResult) => void;
    vi.mocked(reconcilePayroll).mockReturnValue(new Promise((r) => { resolve = r; }));
    render(<PayrollReconciliation />);
    chooseFile();
    fireEvent.click(screen.getByRole('button', { name: /reconcile/i }));
    expect(screen.getByRole('button', { name: /next month/i })).toBeDisabled();
    resolve(RESULT);
    await screen.findByText('Chidi Okoro');
  });

  it('shows the server error message when reconciliation fails', async () => {
    vi.mocked(reconcilePayroll).mockRejectedValue({ response: { data: { detail: 'No payable rows found in the schedule.' } } });
    render(<PayrollReconciliation />);
    chooseFile();
    fireEvent.click(screen.getByRole('button', { name: /reconcile/i }));
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('No payable rows found in the schedule.'));
  });

  it('clears old results when the month changes', async () => {
    vi.mocked(reconcilePayroll).mockResolvedValue(RESULT);
    render(<PayrollReconciliation />);
    chooseFile();
    fireEvent.click(screen.getByRole('button', { name: /reconcile/i }));
    await screen.findByText('Chidi Okoro');
    fireEvent.click(screen.getByRole('button', { name: /previous month/i }));
    expect(screen.queryByText('Chidi Okoro')).not.toBeInTheDocument();
  });
});

describe('extractErrorMessage', () => {
  it('prefers a string detail and falls back to generic messages', () => {
    expect(extractErrorMessage({ response: { data: { detail: 'Bad file' } } })).toBe('Bad file');
    expect(extractErrorMessage({ response: { data: { detail: [{ msg: 'x' }] } } })).toMatch(/check the month/i);
    expect(extractErrorMessage(new Error('boom'))).toMatch(/failed/i);
  });
});
