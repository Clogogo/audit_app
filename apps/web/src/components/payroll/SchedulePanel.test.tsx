import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { SchedulePanel, extractErrorMessage } from './SchedulePanel';
import { reconcilePayroll } from '../../api/client';
import type { PayrollReconcileResult } from '../../api/types';

vi.mock('../../api/client', () => ({ reconcilePayroll: vi.fn() }));

const RESULT = { year: 2026, month: 1, lines: [], notes: [] } as unknown as PayrollReconcileResult;

const renderPanel = (onResult = vi.fn(), month = 1) => {
  const utils = render(<SchedulePanel year={2026} month={month} monthLabel={`M${month} 2026`} onResult={onResult} />);
  return { onResult, ...utils };
};
const chooseFile = () => {
  const file = new File(['x'], 'jan.xlsx');
  fireEvent.change(screen.getByLabelText('Payroll schedule'), { target: { files: [file] } });
  return file;
};
const reconcileButton = () => screen.getByRole('button', { name: /^reconcile$/i });

describe('SchedulePanel', () => {
  beforeEach(() => { vi.mocked(reconcilePayroll).mockReset(); });

  it('keeps Reconcile disabled until a file is chosen', () => {
    renderPanel();
    expect(reconcileButton()).toBeDisabled();
    chooseFile();
    expect(reconcileButton()).toBeEnabled();
  });

  it('uploads the file for the month (no bank-account filter) and reports the result', async () => {
    vi.mocked(reconcilePayroll).mockResolvedValue(RESULT);
    const { onResult } = renderPanel();
    const file = chooseFile();
    fireEvent.click(reconcileButton());
    await waitFor(() => expect(onResult).toHaveBeenLastCalledWith(RESULT));
    expect(reconcilePayroll).toHaveBeenCalledWith(file, 2026, 1);
    expect(screen.queryByLabelText(/bank account/i)).not.toBeInTheDocument();
  });

  it('shows the server error message', async () => {
    vi.mocked(reconcilePayroll).mockRejectedValue({ response: { data: { detail: 'No payable rows found in the schedule.' } } });
    renderPanel();
    chooseFile();
    fireEvent.click(reconcileButton());
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('No payable rows found in the schedule.'));
  });

  it('sends pasted rows as a tab-separated file', async () => {
    vi.mocked(reconcilePayroll).mockResolvedValue(RESULT);
    renderPanel();
    fireEvent.click(screen.getByRole('button', { name: /paste from excel/i }));
    expect(reconcileButton()).toBeDisabled();
    fireEvent.change(screen.getByLabelText('Paste rows from Excel'), { target: { value: 'ADA OBI\t₦25,000.00' } });
    fireEvent.click(reconcileButton());
    await waitFor(() => expect(reconcilePayroll).toHaveBeenCalled());
    const sent = vi.mocked(reconcilePayroll).mock.calls[0][0];
    expect(sent.name).toBe('pasted.tsv');
    expect(sent.size).toBeGreaterThan(0);
  });

  it('drops the result and ignores a late response when the month changes', async () => {
    let resolve!: (r: PayrollReconcileResult) => void;
    vi.mocked(reconcilePayroll).mockReturnValue(new Promise((r) => { resolve = r; }));
    const onResult = vi.fn();
    const { rerender } = renderPanel(onResult, 1);
    chooseFile();
    fireEvent.click(reconcileButton());
    rerender(<SchedulePanel year={2026} month={2} monthLabel="M2 2026" onResult={onResult} />);
    resolve(RESULT);
    await Promise.resolve();
    expect(onResult).not.toHaveBeenCalledWith(RESULT);
    expect(onResult).toHaveBeenLastCalledWith(null);
    expect(reconcileButton()).toBeDisabled();   // the file belonged to the old month
  });
});

describe('SchedulePanel re-run', () => {
  it('re-reconciles with the same file when the re-run token is bumped, and not before', async () => {
    vi.mocked(reconcilePayroll).mockReset().mockResolvedValue(RESULT);
    const onResult = vi.fn();
    const { rerender } = render(<SchedulePanel year={2026} month={1} monthLabel="M1" onResult={onResult} rerunToken={0} />);
    const file = chooseFile();
    expect(reconcilePayroll).not.toHaveBeenCalled();
    rerender(<SchedulePanel year={2026} month={1} monthLabel="M1" onResult={onResult} rerunToken={1} />);
    await waitFor(() => expect(reconcilePayroll).toHaveBeenCalledWith(file, 2026, 1));
  });
});

describe('extractErrorMessage', () => {
  it('prefers a string detail and falls back to generic messages', () => {
    expect(extractErrorMessage({ response: { data: { detail: 'Bad file' } } })).toBe('Bad file');
    expect(extractErrorMessage({ response: { data: { detail: [{ msg: 'x' }] } } })).toMatch(/check the month/i);
    expect(extractErrorMessage(new Error('boom'))).toMatch(/failed/i);
  });
});
