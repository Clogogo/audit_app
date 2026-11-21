import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { AccountingReports } from './AccountingReports';
import { getLedger, getProfitAndLoss, getTrialBalance } from '../api/client';
import type { Ledger, ProfitAndLoss, TrialBalance } from '../api/types';

vi.mock('../api/client', () => ({ getProfitAndLoss: vi.fn(), getTrialBalance: vi.fn(), getLedger: vi.fn() }));

const PL: ProfitAndLoss = {
  start_date: '2026-08-01', end_date: '2026-08-31', gross_profit: 4800, operating_profit: 2800, profit_before_tax: 2500, net_profit: 2500,
  unmapped_income: 0, unmapped_expense: 300,
  unmapped: [{ category: 'Mystery', type: 'expense', count: 1, amount: 300 }],
  sections: [
    { section: 'Operating Revenue', total: 5000, accounts: [{ code: '4.1.1.3.2', name: 'Tuition & School Fees', amount: 5000 }] },
    { section: 'Cost of Sales', total: 200, accounts: [{ code: '5.1.1.1.2', name: 'Learning Materials', amount: 200 }] },
    { section: 'Operating Expenses (OpEx)', total: 2000, accounts: [{ code: '5.2.1.1.2', name: 'Teaching Staff Costs', amount: 2000 }] },
    { section: 'Non-Operating and Finance Income', total: 0, accounts: [] },
    { section: 'Finance Costs', total: 0, accounts: [] },
    { section: 'Tax Expenses', total: 0, accounts: [] },
  ],
};
const TB: TrialBalance = {
  start_date: '2026-08-01', end_date: '2026-08-31', balanced: true, total_debit: 4000, total_credit: 4000, unmapped: [],
  rows: [
    { code: '1.2.4.1', name: 'Operating Bank Accounts', category: 'Assets', debit: 4000, credit: 0 },
    { code: '4.1.1.3.2', name: 'Tuition & School Fees', category: 'Income', debit: 0, credit: 3000 },
    { code: 'B/F', name: 'Accumulated funds brought forward', category: 'Equity', debit: 0, credit: 1000 },
  ],
};
const LEDGER: Ledger = {
  code: '5.2.1.1.2', name: 'Teaching Staff Costs', category: 'Expenses', start_date: '2026-08-01', end_date: '2026-08-31', total_debit: 2000, total_credit: 0,
  rows: [{ id: 7, date: '2026-08-28', type: 'expense', category: 'Salary and Wages', debit: 2000, credit: 0, description: 'August salary', vendor: 'ADA OBI' }],
};

const renderPage = () => render(<MemoryRouter><AccountingReports /></MemoryRouter>);

describe('AccountingReports page', () => {
  beforeEach(() => {
    [getProfitAndLoss, getTrialBalance, getLedger].forEach((f) => vi.mocked(f).mockReset());
    vi.mocked(getProfitAndLoss).mockResolvedValue(PL);
    vi.mocked(getTrialBalance).mockResolvedValue(TB);
    vi.mocked(getLedger).mockResolvedValue(LEDGER);
  });

  it('shows the Profit & Loss by section with subtotals and the net profit', async () => {
    renderPage();
    expect(await screen.findByText('Operating Revenue')).toBeInTheDocument();
    expect(screen.getByText('4.1.1.3.2 Tuition & School Fees')).toBeInTheDocument();
    expect(screen.getByText('Gross profit').closest('tr')).toHaveTextContent('4,800.00');
    expect(screen.getByText('Operating profit').closest('tr')).toHaveTextContent('2,800.00');
    expect(screen.getByText('Net profit').closest('tr')).toHaveTextContent('2,500.00');
    expect(screen.getByText('Unmapped expenses')).toBeInTheDocument();
  });

  it('asks for the report for the chosen dates', async () => {
    renderPage();
    await screen.findByText('Operating Revenue');
    fireEvent.change(screen.getByLabelText('From'), { target: { value: '2026-01-01' } });
    fireEvent.change(screen.getByLabelText('To'), { target: { value: '2026-08-31' } });
    await waitFor(() => expect(getProfitAndLoss).toHaveBeenLastCalledWith('2026-01-01', '2026-08-31'));
  });

  it('warns about unmapped transactions and links to the mapping page', async () => {
    renderPage();
    const notice = await screen.findByRole('alert');
    expect(notice).toHaveTextContent('Mystery (out): 1 transaction, ₦300.00');
    expect(screen.getByRole('link', { name: 'Map these categories' })).toHaveAttribute('href', '/tax/chart-of-accounts');
  });

  it('shows the Trial Balance with totals and says whether it balances', async () => {
    renderPage();
    await screen.findByText('Operating Revenue');
    fireEvent.click(screen.getByRole('button', { name: 'Trial Balance' }));
    expect(await screen.findByText('1.2.4.1 Operating Bank Accounts')).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('Balanced');
    expect(screen.getByText('Total').closest('tr')).toHaveTextContent('4,000.00');
  });

  it('flags a trial balance that does not balance', async () => {
    vi.mocked(getTrialBalance).mockResolvedValue({ ...TB, balanced: false, total_credit: 3999 });
    renderPage();
    await screen.findByText('Operating Revenue');
    fireEvent.click(screen.getByRole('button', { name: 'Trial Balance' }));
    expect(await screen.findByText(/Does not balance/)).toBeInTheDocument();
  });

  it('opens the transactions behind an account when it is clicked', async () => {
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: '5.2.1.1.2 Teaching Staff Costs' }));
    const dialog = await screen.findByRole('dialog', { name: 'Transactions for Teaching Staff Costs' });
    expect(dialog).toHaveTextContent('August salary');
    expect(dialog).toHaveTextContent('ADA OBI');
    expect(getLedger).toHaveBeenCalledWith('5.2.1.1.2', expect.any(String), expect.any(String));
    fireEvent.click(screen.getByRole('button', { name: 'Close' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('does not ask the server for a backwards date range', async () => {
    renderPage();
    await screen.findByText('Operating Revenue');
    vi.mocked(getProfitAndLoss).mockClear();
    fireEvent.change(screen.getByLabelText('From'), { target: { value: '2026-09-30' } });
    fireEvent.change(screen.getByLabelText('To'), { target: { value: '2026-09-01' } });
    expect(await screen.findByText('The start date must not be after the end date.')).toBeInTheDocument();
    expect(getProfitAndLoss).not.toHaveBeenCalledWith('2026-09-30', '2026-09-01');
  });

  it('shows an error when the report cannot be loaded', async () => {
    vi.mocked(getProfitAndLoss).mockRejectedValue(new Error('boom'));
    renderPage();
    expect(await screen.findByText('Could not load the report.')).toBeInTheDocument();
  });
});
