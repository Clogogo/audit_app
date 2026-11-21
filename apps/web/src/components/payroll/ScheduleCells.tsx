import { AlertCircle, CheckCircle2 } from 'lucide-react';
import { formatCurrency } from '../../lib/utils';
import type { ReconcileStatus } from '../../api/types';
import type { RowCheck } from './scheduleCheck';

const BANK_LABEL: Record<ReconcileStatus, string> = {
  matched: 'Matched', underpaid: 'Underpaid', overpaid: 'Overpaid', not_paid: 'Not paid',
};

const BADGE = 'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs';
const WARN = `${BADGE} bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300`;
const BAD = `${BADGE} bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300`;

function Badge({ check }: { check: RowCheck }) {
  switch (check.state) {
    case 'ready':
      return <span className={`${BADGE} bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300`}><CheckCircle2 className="h-3 w-3" />Matched</span>;
    case 'not-on-schedule':
      return <span className={WARN}><AlertCircle className="h-3 w-3" />Not on schedule</span>;
    case 'total':
      return <span className={WARN} title="Can still be processed: the difference is saved as a note. Check the salary, bonus, loans, advances and other deductions.">
        <AlertCircle className="h-3 w-3" />Total differs by {formatCurrency(Math.abs(check.totalGap ?? 0))}
      </span>;
    case 'account':
      return <span className={WARN} title={`Bank paid ${check.paidAccount}; directory has ${check.directoryAccount}`}>
        <AlertCircle className="h-3 w-3" />Account differs
      </span>;
    case 'bank':
      return <span className={check.status === 'not_paid' ? BAD : WARN}
        title={check.note ?? (check.status === 'not_paid' ? undefined : 'Can still be processed: the difference is saved as a note.')}>
        <AlertCircle className="h-3 w-3" />
        {check.status ? BANK_LABEL[check.status] : 'Check'}
        {check.status && check.status !== 'not_paid' && check.paid != null ? ` (${formatCurrency(check.paid)})` : ''}
      </span>;
    default:
      return <span className="text-muted-foreground">—</span>;
  }
}

/** The two payroll-table cells: the schedule's net pay, and whether the bank + totals agree with it. */
export function ScheduleCells({ check }: { check: RowCheck | null }) {
  return (
    <>
      <td className="py-3 pr-3 text-right">
        {check?.expected != null ? formatCurrency(check.expected) : <span className="text-muted-foreground">—</span>}
      </td>
      <td className="py-3 pr-3 text-center">
        {check ? <Badge check={check} /> : <span className="text-muted-foreground">—</span>}
      </td>
    </>
  );
}
