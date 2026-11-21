import { describe, expect, it } from 'vitest';
import type { PayrollReconcileLine, PayrollReconcileResult } from '../../api/types';
import { checkRow, scheduleLinesFor } from './scheduleCheck';

const line = (over: Partial<PayrollReconcileLine> = {}): PayrollReconcileLine => ({
  row_number: 3, name: 'Ada Obi', account_number: '0123456789', expected_amount: 15000, paid_amount: 15000,
  difference: 0, status: 'matched', transaction_ids: [1], paid_to: 'ADA OBI', paid_date: '2026-01-30', note: null,
  extra_payment_ids: [], extra_paid_amount: 0, paid_account: null, paid_bank: null, suggested_payments: [], account_source: null, directory_account: null, account_check: null,
  staff_id: 1, staff_name: 'Ada Obi', computed_net: 15000, net_difference: 0, in_sync: true, ...over,
});

describe('checkRow', () => {
  it('has no verdict until a schedule is loaded', () => {
    expect(checkRow(15000, undefined, false).state).toBe('no-schedule');
  });

  it('flags staff missing from the schedule', () => {
    expect(checkRow(15000, undefined, true).state).toBe('not-on-schedule');
  });

  it('is ready when the bank matched and the total agrees', () => {
    expect(checkRow(15000, line(), true).state).toBe('ready');
  });

  it('is blocked by the bank status first', () => {
    const check = checkRow(15000, line({ status: 'underpaid', paid_amount: 12000 }), true);
    expect(check).toMatchObject({ state: 'bank', status: 'underpaid', paid: 12000 });
  });

  it('is blocked when the bank paid an account other than the directory\'s', () => {
    const check = checkRow(15000, line({ account_check: 'differs', paid_account: '0123456789', directory_account: '0999999999' }), true);
    expect(check).toMatchObject({ state: 'account', paidAccount: '0123456789', directoryAccount: '0999999999' });
  });

  it('only asks for an account (does not block) when the directory has none yet', () => {
    expect(checkRow(15000, line({ account_check: 'missing', paid_account: '0123456789' }), true).state).toBe('ready');
    expect(checkRow(15000, line({ account_check: 'ok' }), true).state).toBe('ready');
  });

  it('is blocked when the payroll total differs from the schedule by ₦100 or more', () => {
    expect(checkRow(15100, line(), true)).toMatchObject({ state: 'total', totalGap: 100 });
    expect(checkRow(14900, line(), true)).toMatchObject({ state: 'total', totalGap: -100 });
  });

  it('accepts a payroll total under ₦100 away', () => {
    expect(checkRow(15099.99, line(), true).state).toBe('ready');
    expect(checkRow(14900.01, line(), true).state).toBe('ready');
  });
});

describe('scheduleLinesFor', () => {
  it('echoes the reconciled rows back as the schedule to validate against', () => {
    const result = { lines: [line()] } as unknown as PayrollReconcileResult;
    expect(scheduleLinesFor(result)).toEqual([
      { row_number: 3, name: 'Ada Obi', amount: 15000, account_number: '0123456789' },
    ]);
  });
});
