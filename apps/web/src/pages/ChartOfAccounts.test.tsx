import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ChartOfAccounts } from './ChartOfAccounts';
import {
  applyMappingSuggestions, getAccountMappings, getChartOfAccounts, importChartOfAccounts, setAccountMapping,
} from '../api/client';
import type { CategoryMappingRow, ChartAccount, ChartResponse } from '../api/types';

vi.mock('../api/client', () => ({
  getChartOfAccounts: vi.fn(), getAccountMappings: vi.fn(), importChartOfAccounts: vi.fn(),
  setAccountMapping: vi.fn(), applyMappingSuggestions: vi.fn(),
}));

const acct = (code: string, name: string, category: ChartAccount['category'], section: string, postable = true): ChartAccount => ({
  code, name, description: null, category, statement_section: section, normal_balance: category === 'Income' ? 'Credit' : 'Debit',
  scope: 'Core', is_postable: postable, status: 'Active',
});
const CHART: ChartResponse = { imported: true, accounts: [
  acct('4.1.1.3', 'Service Revenue', 'Income', 'Operating Revenue', false),
  acct('4.1.1.3.2', 'Tuition & School Fees', 'Income', 'Operating Revenue'),
  acct('5.2.1.1.2', 'Teaching & Academic Staff Costs', 'Expenses', 'Operating Expenses (OpEx)'),
] };
const row = (category: string, type: 'income' | 'expense', n: number, total: number, code: string | null, suggested: string | null): CategoryMappingRow =>
  ({ category, type, tx_count: n, total, account_code: code, suggested_code: suggested });
const ROWS = [
  row('School Fees', 'income', 2, 15000, null, '4.1.1.3.2'),
  row('Salary and Wages', 'expense', 5, 90000, '5.2.1.1.2', '5.2.1.1.2'),
  row('Mystery', 'expense', 1, 300, null, null),
];

const load = (chart: ChartResponse = CHART, rows = ROWS) => {
  vi.mocked(getChartOfAccounts).mockResolvedValue(chart);
  vi.mocked(getAccountMappings).mockResolvedValue({ chart_imported: chart.imported, rows });
};

describe('ChartOfAccounts page', () => {
  beforeEach(() => {
    [getChartOfAccounts, getAccountMappings, importChartOfAccounts, setAccountMapping, applyMappingSuggestions].forEach((f) => vi.mocked(f).mockReset());
    vi.mocked(setAccountMapping).mockResolvedValue({});
    load();
  });

  it('summarises how many categories are mapped and lists every one', async () => {
    render(<ChartOfAccounts />);
    expect(await screen.findByText('School Fees')).toBeInTheDocument();
    expect(screen.getByTestId('mapping-summary')).toHaveTextContent('1 of 3 categories mapped');
    expect(screen.getByTestId('mapping-summary')).toHaveTextContent('3 transactions still unmapped');
    expect((screen.getByLabelText('Account for Salary and Wages (expense)') as HTMLSelectElement).value).toBe('5.2.1.1.2');
  });

  it('only offers accounts that can receive postings, not group headings', async () => {
    render(<ChartOfAccounts />);
    const select = await screen.findByLabelText('Account for School Fees (income)');
    const options = within(select).getAllByRole('option').map((o) => o.textContent);
    expect(options).toContain('4.1.1.3.2 Tuition & School Fees');
    expect(options.some((o) => o?.startsWith('4.1.1.3 '))).toBe(false);
  });

  it('saves the chosen account and shows it', async () => {
    render(<ChartOfAccounts />);
    fireEvent.change(await screen.findByLabelText('Account for Mystery (expense)'), { target: { value: '5.2.1.1.2' } });
    await waitFor(() => expect(setAccountMapping).toHaveBeenCalledWith('Mystery', 'expense', '5.2.1.1.2'));
    expect((screen.getByLabelText('Account for Mystery (expense)') as HTMLSelectElement).value).toBe('5.2.1.1.2');
  });

  it('puts the previous choice back and shows the reason when saving fails', async () => {
    vi.mocked(setAccountMapping).mockRejectedValue({ response: { data: { detail: '4.1.1.3 is a group heading: choose one of its sub-accounts.' } } });
    render(<ChartOfAccounts />);
    fireEvent.change(await screen.findByLabelText('Account for Mystery (expense)'), { target: { value: '5.2.1.1.2' } });
    expect(await screen.findByRole('alert')).toHaveTextContent('group heading');
    expect((screen.getByLabelText('Account for Mystery (expense)') as HTMLSelectElement).value).toBe('');
  });

  it('can adopt the suggestion for one row, and clear a mapping', async () => {
    render(<ChartOfAccounts />);
    fireEvent.click(await screen.findByRole('button', { name: /Use 4\.1\.1\.3\.2 Tuition & School Fees/ }));
    await waitFor(() => expect(setAccountMapping).toHaveBeenCalledWith('School Fees', 'income', '4.1.1.3.2'));
    fireEvent.change(screen.getByLabelText('Account for Salary and Wages (expense)'), { target: { value: '' } });
    await waitFor(() => expect(setAccountMapping).toHaveBeenCalledWith('Salary and Wages', 'expense', null));
  });

  it('applies all suggestions in one click and reloads', async () => {
    vi.mocked(applyMappingSuggestions).mockResolvedValue({ applied: 1, without_suggestion: 1 });
    render(<ChartOfAccounts />);
    fireEvent.click(await screen.findByRole('button', { name: 'Apply suggested accounts' }));
    expect(await screen.findByRole('status')).toHaveTextContent('1 category mapped to their suggested account; 1 still need your choice.');
    expect(getAccountMappings).toHaveBeenCalledTimes(2);
  });

  it('asks to import the chart first, and imports the bundled one on request', async () => {
    load({ imported: false, accounts: [] });
    vi.mocked(importChartOfAccounts).mockResolvedValue({ created: 240, updated: 0, total: 240 });
    render(<ChartOfAccounts />);
    expect(await screen.findByText(/No chart imported yet/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Apply suggested accounts' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Import chart of accounts' }));
    expect(await screen.findByRole('status')).toHaveTextContent('240 added, 0 updated (240 accounts)');
    expect(importChartOfAccounts).toHaveBeenCalledWith(undefined);
  });

  it('uploads a chosen CSV file', async () => {
    vi.mocked(importChartOfAccounts).mockResolvedValue({ created: 0, updated: 2, total: 2 });
    render(<ChartOfAccounts />);
    await screen.findByText('School Fees');
    const file = new File(['x'], 'chart.csv');
    fireEvent.change(screen.getByLabelText('Upload chart CSV'), { target: { files: [file] } });
    await waitFor(() => expect(importChartOfAccounts).toHaveBeenCalledWith(file));
  });

  it('lets you browse and search the chart', async () => {
    render(<ChartOfAccounts />);
    fireEvent.click(await screen.findByRole('button', { name: /The chart \(3\)/ }));
    expect(screen.getByText('Service Revenue')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Search accounts'), { target: { value: 'tuition' } });
    expect(screen.queryByText('Service Revenue')).not.toBeInTheDocument();
    expect(screen.getByText('Tuition & School Fees')).toBeInTheDocument();
  });
});
