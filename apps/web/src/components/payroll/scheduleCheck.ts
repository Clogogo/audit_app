import type { PayrollReconcileLine, PayrollReconcileResult, PayrollScheduleLineIn, ReconcileStatus } from '../../api/types';

/** A payment (or payroll total) less than this many naira from the schedule counts as matching. */
export const TOLERANCE_NAIRA = 100;

export type RowCheckState = 'no-schedule' | 'not-on-schedule' | 'bank' | 'account' | 'total' | 'ready';

export interface RowCheck {
  state: RowCheckState;
  expected?: number;
  paid?: number;
  status?: ReconcileStatus;
  /** payroll total minus schedule net (state 'total') */
  totalGap?: number;
  note?: string | null;
  paidAccount?: string | null;
  directoryAccount?: string | null;
}

const withinTolerance = (a: number, b: number): boolean =>
  Math.abs(Math.round(a * 100) - Math.round(b * 100)) < TOLERANCE_NAIRA * 100;

/**
 * Is this staff member ready to be processed? The schedule row must exist, the
 * bank must have paid it (reconciliation status "matched") to the account the
 * directory has, and the payroll total shown on the page must agree with the
 * schedule's net pay.
 */
export function checkRow(net: number, line: PayrollReconcileLine | undefined, hasSchedule: boolean): RowCheck {
  if (!hasSchedule) return { state: 'no-schedule' };
  if (!line) return { state: 'not-on-schedule' };
  const base = { expected: line.expected_amount, paid: line.paid_amount, status: line.status, note: line.note };
  if (line.status !== 'matched') return { state: 'bank', ...base };
  // The bank paid an account other than the one in the directory: confirm which is right first
  if (line.account_check === 'differs') {
    return { state: 'account', ...base, paidAccount: line.paid_account, directoryAccount: line.directory_account };
  }
  if (!withinTolerance(net, line.expected_amount)) {
    return { state: 'total', ...base, totalGap: Math.round((net - line.expected_amount) * 100) / 100 };
  }
  return { state: 'ready', ...base };
}

/**
 * Does this row stop processing? A missing schedule row, a missing payment, an ambiguous payment or a wrong
 * account does. A different bank amount or payroll total does not: it is saved as a note on the entry.
 */
export const isBlocking = (c: RowCheck | null): boolean => {
  if (!c) return true;
  switch (c.state) {
    case 'ready': case 'total': return false;
    case 'bank': return c.status === 'not_paid' || !!c.note;
    default: return true;
  }
};

/** Processing is allowed, but the difference will be written into the entry's notes. */
export const isNoted = (c: RowCheck | null): boolean => !!c && !isBlocking(c) && c.state !== 'ready';

export const scheduleLinesFor = (result: PayrollReconcileResult): PayrollScheduleLineIn[] =>
  result.lines.map((l) => ({
    row_number: l.row_number, name: l.name, amount: l.expected_amount, account_number: l.account_number,
  }));
