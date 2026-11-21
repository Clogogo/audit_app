import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { FinancialReports } from './FinancialReports';
import { FinancialReport } from './FinancialReport';
import { getFinancialReport } from '../api/client';
import type { FinancialReport as Report } from '../api/types';

vi.mock('../api/client', () => ({ getFinancialReport: vi.fn() }));

const REPORT: Report = {
  slug: 'vat', title: 'VAT Return', subtitle: 'The VAT you owe', estimate: true, assumptions: ['Rates are assumed'],
  start_date: '2026-01-01', as_at: '2026-11-21', summary: [{ label: 'Net VAT payable', value: 7500, kind: 'money' }],
  sections: [{ title: 'VAT by category', note: null, columns: [{ key: 'category', label: 'Category', kind: 'text' }, { key: 'vat', label: 'VAT', kind: 'money' }],
    rows: [{ category: 'Stationery', vat: 7500 }], total: { category: 'Net payable', vat: 7500 } }],
};

const memoryStorage = () => {
  const m = new Map<string, string>();
  return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v), clear: () => m.clear() };
};

describe('Financial Reports hub', () => {
  beforeEach(() => { vi.stubGlobal('localStorage', memoryStorage()); vi.mocked(getFinancialReport).mockReset(); });

  it('lists every report in its group, linking old reports to their existing pages and new ones to the hub', () => {
    render(<MemoryRouter><FinancialReports /></MemoryRouter>);
    expect(screen.getAllByRole('link').filter((l) => l.getAttribute('href')?.startsWith('/') && l.textContent !== 'Reports & Analytics')).toHaveLength(19);
    expect(screen.getByRole('link', { name: /Balance Sheet/ })).toHaveAttribute('href', '/tax/financial-statements');
    expect(screen.getByRole('link', { name: /Asset Register/ })).toHaveAttribute('href', '/tax/assets');
    expect(screen.getByRole('link', { name: /VAT Return/ }).getAttribute('href')).toMatch(/^\/financial-reports\/vat\?as_at=\d{4}-\d{2}-\d{2}$/);
  });

  it('remembers the last reports opened under "Where you left off"', () => {
    localStorage.setItem('financial-reports:recent', JSON.stringify(['vat']));
    render(<MemoryRouter><FinancialReports /></MemoryRouter>);
    expect(screen.getByRole('region', { name: 'Where you left off' })).toHaveTextContent('VAT Return');
  });
});

describe('Financial report page', () => {
  it('shows the estimate warning, the summary and the table, and asks for the chosen dates', async () => {
    vi.mocked(getFinancialReport).mockResolvedValue(REPORT);
    render(<MemoryRouter initialEntries={['/financial-reports/vat?as_at=2026-11-21&start_date=2026-01-01']}>
      <Routes><Route path="/financial-reports/:slug" element={<FinancialReport />} /></Routes></MemoryRouter>);
    expect(await screen.findByRole('heading', { name: 'VAT Return' })).toBeInTheDocument();
    expect(screen.getByRole('note')).toHaveTextContent('Rates are assumed');
    expect(screen.getByText('Stationery')).toBeInTheDocument();
    expect(getFinancialReport).toHaveBeenCalledWith('vat', { as_at: '2026-11-21', start_date: '2026-01-01' });
  });

  it('shows a friendly error when the report cannot load', async () => {
    vi.mocked(getFinancialReport).mockRejectedValue(new Error('boom'));
    render(<MemoryRouter initialEntries={['/financial-reports/vat']}><Routes><Route path="/financial-reports/:slug" element={<FinancialReport />} /></Routes></MemoryRouter>);
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('could not be loaded'));
  });
});
