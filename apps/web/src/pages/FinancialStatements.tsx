import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Building2,
  TrendingUp,
  TrendingDown,
  Scale,
  AlertCircle,
  CalendarRange,
  FileSpreadsheet,
  Download,
  Package,
  ArrowUpDown,
  BarChart2,
  BookOpen,
  ClipboardList,
  CheckCircle2,
  XCircle,
  Plus,
  Trash2,
} from 'lucide-react';
import { getComputedFinancialStatements, getTaxYears, downloadComputedFinancialStatements } from '../api/client';
import type {
  ComputedFinancialStatements,
  FSLineItem,
  FSNoteSection,
  FSPPEItem,
  FSComparatives,
} from '../api/types';
import { Button } from '../components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { formatCurrency } from '../lib/utils';
import { HelpTooltip } from '../components/HelpTooltip';

type Tab = 'pl' | 'fp' | 'cf' | 'ce' | 'notes' | 'declaration';
type Preset = 'full_year' | 'ytd' | 'q1' | 'q2' | 'q3' | 'q4' | 'custom';

const round2 = (n: number) => Math.round(n * 100) / 100;

function todayStr() { return new Date().toISOString().slice(0, 10); }
function yearStart(y: number) { return `${y}-01-01`; }
function yearEnd(y: number)   { return `${y}-12-31`; }

function buildPresets(year: number): Record<Exclude<Preset, 'custom'>, { label: string; start: string; end: string }> {
  const isCurrentYear = year === new Date().getFullYear();
  return {
    full_year: { label: 'Full Year',    start: yearStart(year), end: yearEnd(year) },
    ytd:       { label: 'Year to Date', start: yearStart(year), end: isCurrentYear ? todayStr() : yearEnd(year) },
    q1:        { label: 'Q1 (Jan–Mar)', start: `${year}-01-01`, end: `${year}-03-31` },
    q2:        { label: 'Q2 (Apr–Jun)', start: `${year}-04-01`, end: `${year}-06-30` },
    q3:        { label: 'Q3 (Jul–Sep)', start: `${year}-07-01`, end: `${year}-09-30` },
    q4:        { label: 'Q4 (Oct–Dec)', start: `${year}-10-01`, end: `${year}-12-31` },
  };
}

function formatAmount(val: number | string | null): string {
  if (val === null || val === undefined) return '—';
  if (typeof val === 'string') return val;
  return formatCurrency(val);
}

function SectionHeader({ label, help }: { label: string; help?: { title?: string; content: string } }) {
  return (
    <div className="bg-muted/40 px-3 py-1.5 mt-3 mb-1 rounded-sm flex items-center gap-2">
      <span className="text-xs font-bold uppercase tracking-widest text-foreground">{label}</span>
      {help && <HelpTooltip title={help.title} content={help.content} align="left" />}
    </div>
  );
}

function StatementRow({
  label, amount, indent = false, bold = false, totalLine = false, colorClass = '', help,
}: {
  label: string; amount: number | string | null; indent?: boolean; bold?: boolean; totalLine?: boolean; colorClass?: string; help?: string;
}) {
  return (
    <div className={`flex items-start justify-between py-1.5 ${totalLine ? 'border-t-2 border-b border-border mt-1' : 'border-b border-border/30 last:border-0'} ${indent ? 'pl-6' : ''}`}>
      <span className={`text-sm pr-2 flex-1 flex items-center gap-1.5 ${bold ? 'font-semibold' : 'text-muted-foreground'}`}>
        {label}
        {help && <HelpTooltip content={help} align="left" />}
      </span>
      <span className={`text-sm tabular-nums font-medium shrink-0 ${colorClass} ${bold ? 'font-bold' : ''}`}>
        {formatAmount(amount)}
      </span>
    </div>
  );
}

function ProfitLoss({ data }: { data: ComputedFinancialStatements['profit_loss'] }) {
  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="text-center space-y-0.5">
          <p className="text-xs text-muted-foreground uppercase tracking-widest">{data.company}</p>
          <CardTitle className="text-base">{data.title}</CardTitle>
          <p className="text-sm text-muted-foreground">{data.period}</p>
          <p className="text-xs text-muted-foreground italic">All amounts in Nigerian Naira (₦)</p>
        </div>
      </CardHeader>
      <CardContent className="space-y-1">
        <SectionHeader
          label="Income"
          help={{ title: 'Income', content: 'All revenue earned in the period: school fees, exam fees, book/uniform sales, and other income.\n\nExcludes internal transfers and director capital injections — these are financing flows, not operating income.' }}
        />
        {data.income_items.map((item: FSLineItem, i: number) => (
          <StatementRow key={i} label={item.label} amount={item.amount} indent />
        ))}
        <StatementRow label="TOTAL INCOME" amount={data.total_income} bold totalLine colorClass="text-green-700" />

        <SectionHeader
          label="Administrative Expenses"
          help={{ title: 'Administrative Expenses', content: 'All operational expenditure: salaries, utilities, repairs, stationery, depreciation, etc.\n\nDepreciation from the Asset Register is automatically included here.\n\nNote: Finance Costs (bank charges, interest, loans) are excluded and disclosed separately per IAS 1 / FRC standards.' }}
        />
        {data.expense_items.map((item: FSLineItem, i: number) => (
          <StatementRow key={i} label={item.label} amount={item.amount} indent />
        ))}
        <StatementRow label="TOTAL ADMINISTRATIVE EXPENSES" amount={data.total_expenses} bold totalLine colorClass="text-red-600" />

        <StatementRow
          label="OPERATING PROFIT"
          amount={data.operating_profit}
          bold totalLine
          colorClass={data.operating_profit >= 0 ? 'text-green-700' : 'text-red-600'}
          help="Operating Profit = Total Income − Administrative Expenses\n\nMeasures profitability from the school's core operations before financing costs and other income. Finance Costs are deducted separately below."
        />

        {data.finance_cost_items.length > 0 && (
          <>
            <SectionHeader
              label="Finance Costs"
              help={{ title: 'Finance Costs', content: 'The cost of financing the school — bank charges, interest expense, and loan repayments.\n\nSeparated from Administrative Expenses per IAS 1 and Nigerian accounting standards.\n\nExample: ₦45,000 bank charges + ₦82,000 loan interest = ₦127,000 Finance Costs' }}
            />
            {data.finance_cost_items.map((item: FSLineItem, i: number) => (
              <StatementRow key={i} label={item.label} amount={item.amount} indent />
            ))}
            <StatementRow label="TOTAL FINANCE COSTS" amount={data.total_finance_costs} bold totalLine colorClass="text-red-600" />
          </>
        )}

        <StatementRow
          label="PROFIT BEFORE TAX"
          amount={data.profit_before_tax}
          bold totalLine
          colorClass={data.profit_before_tax >= 0 ? 'text-green-700' : 'text-red-600'}
          help={"Formula:\nOperating Profit\n+ Other Income (investment, gifts, refunds)\n− Finance Costs (bank charges, interest, loans)\n= Profit Before Tax\n\nExample:\n₦2,100,000 operating profit\n+ ₦50,000 investment income\n− ₦180,000 finance costs\n= ₦1,970,000 Profit Before Tax\n\nThis is the base for CIT/EDT computation."}
        />

        <SectionHeader
          label="Taxation"
          help={{ title: 'Nigeria Tax (CITA)', content: 'CIT tiers (by total revenue):\n· Small (≤ ₦25M): 0% — NIL\n· Medium (₦25M–₦100M): 20%\n· Large (> ₦100M): 30%\n\nEducation Development Tax (EDT): 0.5% of Profit Before Tax — applies to all companies regardless of size.\n\nNote: Depreciation is non-allowable for CIT — it is added back and replaced by Capital Allowances on your FIRS return.' }}
        />
        {data.tax_items.map((item: FSLineItem, i: number) => (
          <StatementRow key={i} label={item.label} amount={item.amount} indent />
        ))}
        <StatementRow label="TOTAL TAX" amount={data.total_tax} bold totalLine />

        <div className="mt-4 rounded-lg bg-green-50 border border-green-200 px-4 py-3">
          <p className="text-sm font-bold text-green-800 text-center">{data.net_profit}</p>
        </div>

        {data.notes.length > 0 && (
          <div className="mt-4 space-y-2 border-t border-border/40 pt-4">
            {data.notes.map((note: string, i: number) => (
              <p key={i} className="text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded px-3 py-2 leading-relaxed">
                {note}
              </p>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

interface LoanEntry {
  id: string;
  name: string;
  opening: number;
}

interface StaffLoanEntry {
  id: string;
  name: string;
  loan_amount: number;
  monthly_deduction: number;
  deduction_start: string; // YYYY-MM-DD
}

function calcStaffLoanOutstanding(entry: StaffLoanEntry, periodEnd: string): number {
  if (!entry.deduction_start || !periodEnd || entry.loan_amount <= 0) return entry.loan_amount;
  const start = new Date(entry.deduction_start);
  const end = new Date(periodEnd);
  if (start > end) return entry.loan_amount;
  const months = (end.getFullYear() - start.getFullYear()) * 12 + (end.getMonth() - start.getMonth()) + 1;
  const recovered = Math.min(months * entry.monthly_deduction, entry.loan_amount);
  return Math.max(0, round2(entry.loan_amount - recovered));
}

function LoansPanel({
  entries,
  loanDrawdowns,
  loanRepayments,
  onAdd,
  onUpdate,
  onRemove,
}: {
  entries: LoanEntry[];
  loanDrawdowns: number;
  loanRepayments: number;
  onAdd: () => void;
  onUpdate: (id: string, field: 'name' | 'opening', value: string | number) => void;
  onRemove: (id: string) => void;
}) {
  const totalOpening = entries.reduce((s, e) => s + e.opening, 0);
  const closing = Math.max(0, totalOpening + loanDrawdowns - loanRepayments);

  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold text-amber-900 uppercase tracking-wide">Loans & Borrowings — Opening Balances</p>
        <HelpTooltip
          title="Why enter opening balances?"
          content="When you repay a loan, the payment reduces your bank balance (cash) but does NOT reduce profit — it reduces the loan liability instead.\n\nThe system already has your repayments (₦527,215.80 in 2026). Enter what you owed at the START of this period so the balance sheet can show the correct outstanding loan balance and balance properly."
          align="left"
        />
      </div>

      <p className="text-xs text-amber-700">
        Enter the outstanding balance for each loan at the <strong>start</strong> of this period. Repayments already recorded in transactions are deducted automatically.
      </p>

      <div className="space-y-2">
        {entries.map((entry) => (
          <div key={entry.id} className="flex items-center gap-2">
            <input
              type="text"
              placeholder="Creditor / loan name"
              value={entry.name}
              onChange={(e) => onUpdate(entry.id, 'name', e.target.value)}
              className="flex-1 min-w-0 rounded border border-amber-300 bg-white px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400"
            />
            <span className="text-xs text-amber-700 shrink-0">Opening ₦</span>
            <input
              type="text"
              inputMode="numeric"
              placeholder="0"
              value={entry.opening === 0 ? '' : entry.opening.toLocaleString('en-NG')}
              onChange={(e) => {
                const digits = e.target.value.replace(/[^0-9]/g, '');
                onUpdate(entry.id, 'opening', digits === '' ? 0 : parseInt(digits, 10));
              }}
              className="w-32 rounded border border-amber-300 bg-white px-2 py-1.5 text-sm text-right focus:outline-none focus:ring-2 focus:ring-amber-400"
            />
            <button
              type="button"
              aria-label="Remove loan"
              onClick={() => onRemove(entry.id)}
              className="text-amber-600 hover:text-red-600 shrink-0"
            >
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          </div>
        ))}

        <button
          type="button"
          onClick={onAdd}
          className="flex items-center gap-1 text-xs text-amber-700 hover:text-amber-900 font-medium mt-1"
        >
          <Plus className="h-3.5 w-3.5" />
          Add loan
        </button>
      </div>

      <div className="border-t border-amber-200 pt-3 space-y-1 text-sm">
        <div className="flex justify-between text-muted-foreground">
          <span>Total opening balances</span>
          <span className="tabular-nums">{formatCurrency(totalOpening)}</span>
        </div>
        {loanDrawdowns > 0 && (
          <div className="flex justify-between text-muted-foreground">
            <span>+ New borrowings this period</span>
            <span className="tabular-nums text-green-700">+{formatCurrency(loanDrawdowns)}</span>
          </div>
        )}
        <div className="flex justify-between text-muted-foreground">
          <span>− Repayments this period (from transactions)</span>
          <span className="tabular-nums text-red-600">−{formatCurrency(loanRepayments)}</span>
        </div>
        <div className="flex justify-between font-semibold border-t border-amber-200 pt-1">
          <span>= Closing loans payable</span>
          <span className="tabular-nums">{formatCurrency(closing)}</span>
        </div>
      </div>
    </div>
  );
}

function StaffLoansPanel({
  entries,
  periodEnd,
  onAdd,
  onUpdate,
  onRemove,
}: {
  entries: StaffLoanEntry[];
  periodEnd: string;
  onAdd: () => void;
  onUpdate: (id: string, field: keyof Omit<StaffLoanEntry, 'id'>, value: string | number) => void;
  onRemove: (id: string) => void;
}) {
  const totalOutstanding = entries.reduce((s, e) => s + calcStaffLoanOutstanding(e, periodEnd), 0);

  return (
    <div className="rounded-lg border border-blue-200 bg-blue-50 p-4 space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold text-blue-900 uppercase tracking-wide">Staff Loans Receivable</p>
        <HelpTooltip
          title="Staff Loans Receivable"
          content="Money the school has lent to teachers/staff that is being recovered from their salary.\n\nThis is an ASSET — the school is owed money.\n\nHow to record:\n1. When you give the loan: record as expense, category 'IOU (Advance Salary)'\n2. Each month: record the NET salary paid (gross minus deduction) as 'Salary and Wages'\n\nEnter each loan below — the outstanding balance is computed automatically from the monthly deduction and start date."
          align="left"
        />
      </div>

      <p className="text-xs text-blue-700">
        Enter each staff loan. The outstanding balance is auto-calculated based on the monthly salary deduction and when deductions started.
      </p>

      {entries.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-blue-800 border-b border-blue-200">
                <th className="text-left pb-1.5 font-medium">Employee</th>
                <th className="text-right pb-1.5 font-medium">Loan (₦)</th>
                <th className="text-right pb-1.5 font-medium">Monthly (₦)</th>
                <th className="text-left pb-1.5 font-medium pl-2">Deductions from</th>
                <th className="text-right pb-1.5 font-medium">Outstanding</th>
                <th className="pb-1.5 w-6" scope="col"><span className="sr-only">Remove</span></th>
              </tr>
            </thead>
            <tbody className="space-y-1">
              {entries.map((entry) => {
                const outstanding = calcStaffLoanOutstanding(entry, periodEnd);
                return (
                  <tr key={entry.id} className="border-b border-blue-100">
                    <td className="py-1.5 pr-2">
                      <input
                        type="text"
                        placeholder="Name"
                        value={entry.name}
                        onChange={(e) => onUpdate(entry.id, 'name', e.target.value)}
                        className="w-full rounded border border-blue-300 bg-white px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400"
                      />
                    </td>
                    <td className="py-1.5 pr-1">
                      <input
                        type="text"
                        inputMode="numeric"
                        placeholder="0"
                        value={entry.loan_amount === 0 ? '' : entry.loan_amount.toLocaleString('en-NG')}
                        onChange={(e) => {
                          const d = e.target.value.replace(/[^0-9]/g, '');
                          onUpdate(entry.id, 'loan_amount', d === '' ? 0 : parseInt(d, 10));
                        }}
                        className="w-24 rounded border border-blue-300 bg-white px-2 py-1 text-xs text-right focus:outline-none focus:ring-1 focus:ring-blue-400"
                      />
                    </td>
                    <td className="py-1.5 pr-1">
                      <input
                        type="text"
                        inputMode="numeric"
                        placeholder="0"
                        value={entry.monthly_deduction === 0 ? '' : entry.monthly_deduction.toLocaleString('en-NG')}
                        onChange={(e) => {
                          const d = e.target.value.replace(/[^0-9]/g, '');
                          onUpdate(entry.id, 'monthly_deduction', d === '' ? 0 : parseInt(d, 10));
                        }}
                        className="w-24 rounded border border-blue-300 bg-white px-2 py-1 text-xs text-right focus:outline-none focus:ring-1 focus:ring-blue-400"
                      />
                    </td>
                    <td className="py-1.5 pl-2 pr-1">
                      <input
                        type="date"
                        title="Date deductions started"
                        placeholder="YYYY-MM-DD"
                        value={entry.deduction_start}
                        onChange={(e) => onUpdate(entry.id, 'deduction_start', e.target.value)}
                        className="rounded border border-blue-300 bg-white px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400"
                      />
                    </td>
                    <td className="py-1.5 text-right tabular-nums font-medium text-blue-900">
                      {formatCurrency(outstanding)}
                    </td>
                    <td className="py-1.5 pl-2">
                      <button
                        type="button"
                        aria-label="Remove staff loan"
                        onClick={() => onRemove(entry.id)}
                        className="text-blue-400 hover:text-red-500"
                      >
                        <Trash2 className="h-3 w-3" />
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <button
        type="button"
        onClick={onAdd}
        className="flex items-center gap-1 text-xs text-blue-700 hover:text-blue-900 font-medium"
      >
        <Plus className="h-3.5 w-3.5" />
        Add staff loan
      </button>

      {entries.length > 0 && (
        <div className="border-t border-blue-200 pt-2 flex justify-between text-sm font-semibold text-blue-900">
          <span>Total Staff Loans Receivable</span>
          <span className="tabular-nums">{formatCurrency(totalOutstanding)}</span>
        </div>
      )}
    </div>
  );
}

function FinancialPosition({
  data,
  loanEntries,
  loanDrawdowns,
  loanRepayments,
  staffLoanEntries,
  periodEnd,
  onAddLoan,
  onUpdateLoan,
  onRemoveLoan,
  onAddStaffLoan,
  onUpdateStaffLoan,
  onRemoveStaffLoan,
}: {
  data: ComputedFinancialStatements['financial_position'];
  loanEntries: LoanEntry[];
  loanDrawdowns: number;
  loanRepayments: number;
  staffLoanEntries: StaffLoanEntry[];
  periodEnd: string;
  onAddLoan: () => void;
  onUpdateLoan: (id: string, field: 'name' | 'opening', value: string | number) => void;
  onRemoveLoan: (id: string) => void;
  onAddStaffLoan: () => void;
  onUpdateStaffLoan: (id: string, field: keyof Omit<StaffLoanEntry, 'id'>, value: string | number) => void;
  onRemoveStaffLoan: (id: string) => void;
}) {
  const totalOpeningLoans = loanEntries.reduce((s, e) => s + e.opening, 0);
  const closingLoansPayable = Math.max(0, totalOpeningLoans + loanDrawdowns - loanRepayments);
  const totalLiabilities = round2(data.total_liabilities + closingLoansPayable);

  const totalStaffLoans = round2(staffLoanEntries.reduce((s, e) => s + calcStaffLoanOutstanding(e, periodEnd), 0));

  const nca = data.total_non_current_assets;
  const ca = data.total_current_assets;
  const totalAssets = round2(nca + Math.max(ca, 0) + totalStaffLoans);
  const totalEL = round2(data.total_equity + totalLiabilities);
  const imbalance = round2(totalEL - totalAssets);
  const balanced = Math.abs(imbalance) < 1;

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="text-center space-y-0.5">
          <p className="text-xs text-muted-foreground uppercase tracking-widest">{data.company}</p>
          <CardTitle className="text-base">{data.title}</CardTitle>
          <p className="text-sm text-muted-foreground">{data.as_at}</p>
          <p className="text-xs text-muted-foreground italic">All amounts in Nigerian Naira (₦)</p>
        </div>
      </CardHeader>
      <CardContent className="space-y-1">
        {data.non_current_asset_items.length > 0 && (
          <>
            <SectionHeader
              label="Non-Current Assets"
              help={{ title: 'Non-Current Assets', content: 'Fixed assets held for long-term use — buildings, vehicles, furniture, equipment — shown at Net Book Value (Cost − Accumulated Depreciation).\n\nSourced directly from the Asset Register. Add assets via Tax → Asset Register.\n\nExample: ₦500,000 computer − ₦150,000 depreciation = ₦350,000 NBV' }}
            />
            {data.non_current_asset_items.map((item: FSLineItem, i: number) => (
              <StatementRow key={i} label={item.label} amount={item.amount} indent />
            ))}
            <StatementRow label="TOTAL NON-CURRENT ASSETS" amount={data.total_non_current_assets} bold totalLine />
          </>
        )}

        <SectionHeader
          label="Current Assets"
          help={{ title: 'Current Assets', content: 'Assets expected to be converted to cash within 12 months — primarily cash at bank.\n\nCalculated as: Total Receipts − Total Payments for the period.\n\nA negative balance here indicates a net overdraft position across all accounts.' }}
        />
        {data.current_asset_items.map((item: FSLineItem, i: number) => (
          <StatementRow key={i} label={item.label} amount={item.amount} indent />
        ))}

        <div className="py-2">
          <StaffLoansPanel
            entries={staffLoanEntries}
            periodEnd={periodEnd}
            onAdd={onAddStaffLoan}
            onUpdate={onUpdateStaffLoan}
            onRemove={onRemoveStaffLoan}
          />
        </div>

        {totalStaffLoans > 0 && (
          <StatementRow label="Staff Loans Receivable" amount={totalStaffLoans} indent />
        )}
        <StatementRow label="TOTAL CURRENT ASSETS" amount={round2(data.total_current_assets + totalStaffLoans)} bold totalLine />

        <div className="mt-2 rounded-lg bg-blue-50 border border-blue-200 px-4 py-2.5">
          <p className="text-sm font-bold text-blue-900 text-center">TOTAL ASSETS  ₦{totalAssets.toLocaleString('en-NG', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}</p>
        </div>

        <SectionHeader
          label="Equity"
          help={{ title: "Owner's Equity", content: "The school's net worth: what belongs to the owner after all obligations are met.\n\nEquity = Total Assets − Total Liabilities\n\nIncreases when the school is profitable; decreases when it makes a loss." }}
        />
        {data.equity_items.map((item: FSLineItem, i: number) => (
          <StatementRow key={i} label={item.label} amount={item.amount} indent />
        ))}
        <StatementRow label="TOTAL EQUITY" amount={data.total_equity} bold totalLine colorClass="text-blue-700" />

        <SectionHeader
          label="Liabilities"
          help={{ title: 'Liabilities', content: 'Amounts the school owes: loan balances and director capital injections.\n\nEnter your opening loan balances below so the balance sheet reflects the correct outstanding amounts.\n\nRepayments already recorded in transactions are automatically deducted to give the closing balance.' }}
        />

        <div className="py-2">
          <LoansPanel
            entries={loanEntries}
            loanDrawdowns={loanDrawdowns}
            loanRepayments={loanRepayments}
            onAdd={onAddLoan}
            onUpdate={onUpdateLoan}
            onRemove={onRemoveLoan}
          />
        </div>

        {closingLoansPayable > 0 && (
          <StatementRow label="Loans Payable (closing balance)" amount={closingLoansPayable} indent />
        )}
        {data.non_current_liability_items.map((item: FSLineItem, i: number) => (
          <StatementRow key={i} label={item.label} amount={item.amount} indent />
        ))}
        <StatementRow label="TOTAL LIABILITIES" amount={totalLiabilities} bold totalLine colorClass="text-red-600" />

        <div className={`mt-3 rounded-lg border px-4 py-3 flex items-start gap-3 ${balanced ? 'bg-green-50 border-green-200' : 'bg-red-50 border-red-200'}`}>
          {balanced
            ? <CheckCircle2 className="h-4 w-4 text-green-600 shrink-0 mt-0.5" />
            : <AlertCircle className="h-4 w-4 text-red-500 shrink-0 mt-0.5" />
          }
          <div className="text-xs">
            {balanced ? (
              <p className="text-green-800 font-medium">Balance sheet balances ✓  Assets = Equity + Liabilities = {formatCurrency(totalAssets)}</p>
            ) : (
              <>
                <p className="text-red-700 font-medium">Balance sheet difference: {formatCurrency(Math.abs(imbalance))}</p>
                <p className="text-red-600 mt-0.5">
                  {imbalance > 0
                    ? 'Equity + Liabilities exceeds Assets. Enter the opening loan balance(s) above — the system knows you made repayments but needs the starting balance to calculate what is still owed.'
                    : 'Assets exceed Equity + Liabilities. Check that all loans received (income side) are recorded.'}
                </p>
              </>
            )}
          </div>
        </div>

        {data.notes.length > 0 && (
          <div className="mt-4 space-y-2">
            {data.notes.map((note: string, i: number) => (
              <p key={i} className="text-xs text-muted-foreground bg-muted/30 rounded p-3 leading-relaxed">
                {note}
              </p>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function CashFlows({ data }: { data: ComputedFinancialStatements['cash_flow_statement'] }) {
  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="text-center space-y-0.5">
          <p className="text-xs text-muted-foreground uppercase tracking-widest">{data.company}</p>
          <CardTitle className="text-base">{data.title}</CardTitle>
          <p className="text-sm text-muted-foreground">{data.period}</p>
          <p className="text-xs text-muted-foreground italic">Method: {data.method} · All amounts in Nigerian Naira (₦)</p>
        </div>
      </CardHeader>
      <CardContent className="space-y-1">
        <SectionHeader
          label="Operating Activities"
          help={{ title: 'Cash from Operations', content: 'Cash generated from the school\'s day-to-day activities.\n\nIndirect Method: starts from net profit and adds back non-cash charges (depreciation), which was a book entry — no actual cash left the business.' }}
        />
        {data.operating_items.map((item, i) => (
          <StatementRow key={i} label={item.label} amount={item.amount} indent />
        ))}
        <StatementRow
          label="NET CASH FROM OPERATING ACTIVITIES"
          amount={data.total_operating}
          bold totalLine
          colorClass={data.total_operating >= 0 ? 'text-green-700' : 'text-red-600'}
        />

        {data.investing_items.length > 0 && (
          <>
            <SectionHeader
              label="Investing Activities"
              help={{ title: 'Cash from Investing', content: 'Cash used to purchase or sell long-term assets (PPE).\n\nAsset purchases are sourced from the Asset Register — they are a real cash outflow not shown in the P&L (only depreciation appears in P&L).' }}
            />
            {data.investing_items.map((item, i) => (
              <StatementRow key={i} label={item.label} amount={item.amount} indent colorClass="text-red-600" />
            ))}
            <StatementRow
              label="NET CASH FROM INVESTING ACTIVITIES"
              amount={data.total_investing}
              bold totalLine
              colorClass={data.total_investing >= 0 ? 'text-green-700' : 'text-red-600'}
            />
          </>
        )}

        {data.financing_items.length > 0 && (
          <>
            <SectionHeader
              label="Financing Activities"
              help={{ title: 'Cash from Financing', content: 'Cash flows from external funding sources.\n\nIncludes: loans received, director capital injections.\n\nThese are NOT revenue — they are liabilities or equity contributions.' }}
            />
            {data.financing_items.map((item, i) => (
              <StatementRow key={i} label={item.label} amount={item.amount} indent colorClass="text-blue-700" />
            ))}
            <StatementRow
              label="NET CASH FROM FINANCING ACTIVITIES"
              amount={data.total_financing}
              bold totalLine
              colorClass={data.total_financing >= 0 ? 'text-blue-700' : 'text-red-600'}
            />
          </>
        )}

        <div className="mt-3 pt-3 border-t-2 border-border space-y-0">
          <StatementRow
            label="Net Increase / (Decrease) in Cash"
            amount={data.net_movement}
            bold
            colorClass={data.net_movement >= 0 ? 'text-green-700' : 'text-red-600'}
          />
          <StatementRow label="Cash at Beginning of Period" amount={data.opening_cash} />
          <StatementRow label="Cash at End of Period" amount={data.closing_cash} bold colorClass="text-blue-700" totalLine />
        </div>

        {data.notes.length > 0 && (
          <div className="mt-4 space-y-2 border-t border-border/40 pt-4">
            {data.notes.map((note, i) => (
              <p key={i} className="text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded px-3 py-2 leading-relaxed">
                {note}
              </p>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function ChangesInEquity({
  data,
  comparatives,
}: {
  data: ComputedFinancialStatements['changes_in_equity'];
  comparatives: FSComparatives;
}) {
  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="text-center space-y-0.5">
          <p className="text-xs text-muted-foreground uppercase tracking-widest">{data.company}</p>
          <CardTitle className="text-base">{data.title}</CardTitle>
          <p className="text-sm text-muted-foreground">{data.period}</p>
          <p className="text-xs text-muted-foreground italic">All amounts in Nigerian Naira (₦)</p>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="overflow-x-auto rounded-md border border-border">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-muted/60 border-b border-border">
                <th className="text-left py-2.5 px-4 text-xs font-semibold uppercase tracking-wide text-muted-foreground w-1/2">Description</th>
                <th className="text-right py-2.5 px-4 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Retained Earnings</th>
                <th className="text-right py-2.5 px-4 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Total</th>
              </tr>
            </thead>
            <tbody>
              {[
                { label: 'Opening balance — 1 January', re: data.opening_retained_earnings, cls: 'text-muted-foreground' },
                { label: 'Net profit for the period', re: data.net_profit_for_period, cls: data.net_profit_for_period >= 0 ? 'text-green-700' : 'text-red-600' },
                { label: 'Dividends / drawings', re: data.dividends_drawings, cls: 'text-muted-foreground' },
              ].map((row, i) => (
                <tr key={i} className="border-b border-border/30">
                  <td className="py-2 px-4 text-muted-foreground">{row.label}</td>
                  <td className={`py-2 px-4 text-right tabular-nums ${row.cls}`}>{formatCurrency(row.re)}</td>
                  <td className={`py-2 px-4 text-right tabular-nums ${row.cls}`}>{formatCurrency(row.re)}</td>
                </tr>
              ))}
              <tr className="bg-muted/30 font-semibold border-t-2 border-border">
                <td className="py-2.5 px-4">Closing balance</td>
                <td className={`py-2.5 px-4 text-right tabular-nums ${data.closing_retained_earnings >= 0 ? 'text-blue-700' : 'text-red-600'}`}>
                  {formatCurrency(data.closing_retained_earnings)}
                </td>
                <td className={`py-2.5 px-4 text-right tabular-nums ${data.closing_retained_earnings >= 0 ? 'text-blue-700' : 'text-red-600'}`}>
                  {formatCurrency(data.closing_retained_earnings)}
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        {/* Comparative summary */}
        {comparatives.transaction_count > 0 && (
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">Prior Period Comparatives</p>
            <p className="text-xs text-muted-foreground mb-2">{comparatives.period}</p>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
              {[
                { label: 'Net Profit', val: comparatives.net_profit, color: comparatives.net_profit >= 0 ? 'text-green-700' : 'text-red-600' },
                { label: 'Total Income', val: comparatives.total_income, color: 'text-foreground' },
                { label: 'Total Expenses', val: comparatives.total_admin_expenses, color: 'text-foreground' },
                { label: 'Asset NBV', val: comparatives.total_asset_nbv, color: 'text-foreground' },
              ].map((kpi) => (
                <div key={kpi.label} className="rounded-md bg-muted/30 border border-border px-3 py-2">
                  <p className="text-xs text-muted-foreground">{kpi.label}</p>
                  <p className={`text-sm font-semibold tabular-nums ${kpi.color}`}>{formatCurrency(kpi.val)}</p>
                </div>
              ))}
            </div>
          </div>
        )}

        <p className="text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded px-3 py-2 leading-relaxed">
          {data.note}
        </p>
      </CardContent>
    </Card>
  );
}

function NotesSection({
  notes,
  comparatives,
  period,
}: {
  notes: FSNoteSection[];
  comparatives: FSComparatives;
  period: string;
}) {
  return (
    <div className="space-y-4">
      {notes.map((note) => (
        <Card key={note.number}>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-bold uppercase tracking-wide text-primary">
              Note {note.number} — {note.title}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {/* Subsections (accounting policies) */}
            {note.subsections.length > 0 && note.subsections.map((sub, i) => (
              <div key={i} className="space-y-1">
                <p className="text-sm font-semibold text-foreground">{sub.subtitle}</p>
                <p className="text-sm text-muted-foreground leading-relaxed">{sub.text}</p>
              </div>
            ))}

            {/* PPE Table (Note 4) */}
            {note.number === '4' && note.items && note.items.length > 0 && (
              <>
                {note.text && <p className="text-sm text-muted-foreground">{note.text}</p>}
                <div className="overflow-x-auto rounded-md border border-border">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="bg-muted/60 border-b border-border">
                        <th className="text-left py-2 px-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Asset</th>
                        <th className="text-right py-2 px-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Cost (₦)</th>
                        <th className="text-right py-2 px-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Period Dep.</th>
                        <th className="text-right py-2 px-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Accum. Dep.</th>
                        <th className="text-right py-2 px-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">NBV (₦)</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(note.items as FSPPEItem[]).map((item, i) => (
                        <tr key={i} className="border-b border-border/30">
                          <td className="py-2 px-3">
                            <p className="font-medium text-foreground">{item.name}</p>
                            <p className="text-muted-foreground text-xs">{item.category} · {item.depreciation_method} · {item.useful_life_years}yr life</p>
                          </td>
                          <td className="py-2 px-3 text-right tabular-nums">{formatCurrency(item.cost)}</td>
                          <td className="py-2 px-3 text-right tabular-nums text-amber-700">{formatCurrency(item.period_depreciation)}</td>
                          <td className="py-2 px-3 text-right tabular-nums text-red-600">{formatCurrency(item.accumulated_depreciation)}</td>
                          <td className="py-2 px-3 text-right tabular-nums font-semibold text-blue-700">{formatCurrency(item.nbv)}</td>
                        </tr>
                      ))}
                      <tr className="bg-muted/30 font-semibold border-t-2 border-border">
                        <td className="py-2 px-3">TOTAL</td>
                        <td className="py-2 px-3 text-right tabular-nums">{formatCurrency(note.total_cost ?? 0)}</td>
                        <td className="py-2 px-3 text-right tabular-nums text-amber-700">{formatCurrency(note.total_period_dep ?? 0)}</td>
                        <td className="py-2 px-3 text-right tabular-nums text-red-600">{formatCurrency(note.total_accumulated_dep ?? 0)}</td>
                        <td className="py-2 px-3 text-right tabular-nums text-blue-700">{formatCurrency(note.total_nbv ?? 0)}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </>
            )}

            {/* Simple line-item notes (Notes 2 & 3) */}
            {note.number !== '4' && note.items && note.items.length > 0 && (
              <>
                {note.text && <p className="text-sm text-muted-foreground">{note.text}</p>}
                <div className="space-y-0">
                  {(note.items as FSLineItem[]).map((item, i) => (
                    <StatementRow key={i} label={item.label} amount={item.amount} indent />
                  ))}
                  <StatementRow label="TOTAL" amount={note.total ?? 0} bold totalLine />
                </div>
              </>
            )}
          </CardContent>
        </Card>
      ))}

      {/* Comparative P&L table */}
      {comparatives.transaction_count > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-bold uppercase tracking-wide text-primary">
              Comparative Figures — Prior Period
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-xs text-muted-foreground mb-3">Current: {period} · Prior: {comparatives.period}</p>
            <div className="overflow-x-auto rounded-md border border-border">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-muted/60 border-b border-border">
                    <th className="text-left py-2.5 px-4 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Item</th>
                    <th className="text-right py-2.5 px-4 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Current Period</th>
                    <th className="text-right py-2.5 px-4 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Prior Period</th>
                  </tr>
                </thead>
                <tbody>
                  {[
                    { label: 'Total Income', cur: null as number | null, pri: comparatives.total_income },
                    { label: 'Admin Expenses', cur: null, pri: comparatives.total_admin_expenses },
                    { label: 'Finance Costs', cur: null, pri: comparatives.total_finance_costs },
                    { label: 'Operating Profit', cur: null, pri: comparatives.operating_profit },
                    { label: 'Profit Before Tax', cur: null, pri: comparatives.profit_before_tax },
                    { label: 'Tax', cur: null, pri: comparatives.total_tax },
                    { label: 'Net Profit', cur: null, pri: comparatives.net_profit },
                    { label: 'Asset NBV', cur: null, pri: comparatives.total_asset_nbv },
                  ].map((row, i) => (
                    <tr key={i} className="border-b border-border/30">
                      <td className="py-2 px-4 text-muted-foreground">{row.label}</td>
                      <td className="py-2 px-4 text-right tabular-nums text-muted-foreground italic">see current tab</td>
                      <td className="py-2 px-4 text-right tabular-nums">{formatCurrency(row.pri)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function DeclarationSection({ data }: { data: ComputedFinancialStatements }) {
  const decl = data.director_declaration;
  const audit = data.auditor_report;

  return (
    <div className="space-y-4">
      {/* Auditor / Compilation Report */}
      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center gap-2">
            <XCircle className="h-5 w-5 text-amber-500" />
            <div>
              <CardTitle className="text-base">{audit.type}</CardTitle>
              <p className="text-xs text-muted-foreground mt-0.5">{audit.company} · Period ended {audit.period_ended}</p>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          {audit.paragraphs.map((para, i) => (
            <div key={i}>
              <p className="text-sm font-semibold text-foreground mb-1.5">{para.heading}</p>
              {para.text && <p className="text-sm text-muted-foreground leading-relaxed mb-2">{para.text}</p>}
              {para.list.length > 0 && (
                <ul className="space-y-1.5">
                  {para.list.map((li, j) => (
                    <li key={j} className="flex items-start gap-2 text-sm text-muted-foreground">
                      <span className="mt-0.5 text-amber-500 shrink-0">•</span>
                      <span>{li}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ))}
          <p className="text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded px-3 py-2 leading-relaxed">
            {audit.disclaimer}
          </p>
        </CardContent>
      </Card>

      {/* FIRS CIT — Ready */}
      <div className="flex items-center gap-3 rounded-md border border-green-200 bg-green-50 px-4 py-3">
        <CheckCircle2 className="h-5 w-5 text-green-600 shrink-0" />
        <div>
          <p className="text-sm font-semibold text-green-800">FIRS CIT Return — Ready to File</p>
          <p className="text-xs text-green-700 mt-0.5">
            Use the Tax page to export the pre-filled FIRS CIT Excel template. It includes revenue by sector, non-allowable add-backs, and the computed CIT/EDT liability in the official FIRS format.
          </p>
        </div>
      </div>

      {/* Director's Declaration */}
      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center gap-2">
            <ClipboardList className="h-5 w-5 text-primary" />
            <div>
              <CardTitle className="text-base">Directors' Declaration</CardTitle>
              <p className="text-xs text-muted-foreground mt-0.5">
                {decl.company} · Period ended {decl.period_ended}
              </p>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">The directors of the above-named company hereby declare that:</p>
          <ol className="space-y-3">
            {decl.clauses.map((clause, i) => (
              <li key={i} className="flex items-start gap-3 text-sm text-muted-foreground">
                <span className="shrink-0 font-semibold text-foreground">({String.fromCharCode(97 + i)})</span>
                <span className="leading-relaxed">{clause}</span>
              </li>
            ))}
          </ol>

          <div className="mt-4 pt-4 border-t border-border/40 space-y-4">
            <p className="text-sm text-muted-foreground">Signed in accordance with a resolution of the Board of Directors:</p>
            {decl.signatories.map((sig, i) => (
              <div key={i} className="grid grid-cols-3 gap-4 text-sm">
                <div>
                  <p className="text-xs text-muted-foreground uppercase tracking-wide mb-1">{sig.role}</p>
                  <div className="h-10 border-b-2 border-foreground/30 relative">
                    {sig.name && <span className="absolute bottom-1 text-foreground">{sig.name}</span>}
                  </div>
                </div>
                <div>
                  <p className="text-xs text-muted-foreground uppercase tracking-wide mb-1">Full Name</p>
                  <div className="h-10 border-b-2 border-foreground/30" />
                </div>
                <div>
                  <p className="text-xs text-muted-foreground uppercase tracking-wide mb-1">Date</p>
                  <div className="h-10 border-b-2 border-foreground/30 relative">
                    {sig.date && <span className="absolute bottom-1 text-foreground">{sig.date}</span>}
                  </div>
                </div>
              </div>
            ))}
          </div>

          <p className="text-xs text-muted-foreground bg-muted/30 rounded px-3 py-2">{decl.authority}</p>
        </CardContent>
      </Card>
    </div>
  );
}

const TABS: { id: Tab; label: string; icon: React.ComponentType<{ className?: string }> }[] = [
  { id: 'pl',          label: 'Profit or Loss',      icon: TrendingUp },
  { id: 'fp',          label: 'Financial Position',  icon: Scale },
  { id: 'cf',          label: 'Cash Flows',           icon: ArrowUpDown },
  { id: 'ce',          label: 'Changes in Equity',   icon: BarChart2 },
  { id: 'notes',       label: 'Notes & Policies',    icon: BookOpen },
  { id: 'declaration', label: 'Declaration & Audit', icon: ClipboardList },
];

// Module-level response cache — persists across re-renders without causing re-renders
const _fsCache = new Map<string, ComputedFinancialStatements>();

export function FinancialStatements() {
  const currentYear = new Date().getFullYear();

  const [availableYears, setAvailableYears] = useState<number[]>([]);
  const [selectedYear, setSelectedYear]     = useState<number>(currentYear);
  const [activePreset, setActivePreset]     = useState<Preset>('full_year');
  // Start with empty dates — populated once getTaxYears resolves (avoids double API call)
  const [startDate, setStartDate]           = useState('');
  const [endDate, setEndDate]               = useState('');
  const datesReadyRef                       = useRef(false);

  const [data, setData]           = useState<ComputedFinancialStatements | null>(null);
  const [loading, setLoading]     = useState(false);
  const [error, setError]         = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<Tab>('pl');
  const [downloading, setDownloading] = useState(false);
  const [loanEntries, setLoanEntries] = useState<LoanEntry[]>([]);
  const [staffLoanEntries, setStaffLoanEntries] = useState<StaffLoanEntry[]>([]);

  // Debounce timer ref — prevents API call on every keystroke in date inputs
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Load years once on mount and set dates only after resolution (single API call on mount)
  useEffect(() => {
    getTaxYears().then((yrs) => {
      const best = yrs.length > 0 ? yrs[0] : currentYear;
      setAvailableYears(yrs);
      setSelectedYear(best);
      const p = buildPresets(best);
      setStartDate(p.full_year.start);
      setEndDate(p.full_year.end);
      datesReadyRef.current = true;
    });
  }, [currentYear]);

  // Loan entries — load from localStorage when period changes, persist on edit
  useEffect(() => {
    if (!startDate || !endDate) return;
    const saved = localStorage.getItem(`fs_loans_${startDate}_${endDate}`);
    setLoanEntries(saved ? (JSON.parse(saved) as LoanEntry[]) : []);
    const savedStaff = localStorage.getItem(`fs_staff_loans_${startDate}_${endDate}`);
    setStaffLoanEntries(savedStaff ? (JSON.parse(savedStaff) as StaffLoanEntry[]) : []);
  }, [startDate, endDate]);

  useEffect(() => {
    if (!startDate || !endDate) return;
    localStorage.setItem(`fs_loans_${startDate}_${endDate}`, JSON.stringify(loanEntries));
  }, [loanEntries, startDate, endDate]);

  useEffect(() => {
    if (!startDate || !endDate) return;
    localStorage.setItem(`fs_staff_loans_${startDate}_${endDate}`, JSON.stringify(staffLoanEntries));
  }, [staffLoanEntries, startDate, endDate]);

  const handleAddLoan = () =>
    setLoanEntries((prev) => [...prev, { id: crypto.randomUUID(), name: '', opening: 0 }]);

  const handleUpdateLoan = (id: string, field: 'name' | 'opening', value: string | number) =>
    setLoanEntries((prev) => prev.map((e) => e.id === id ? { ...e, [field]: value } : e));

  const handleRemoveLoan = (id: string) =>
    setLoanEntries((prev) => prev.filter((e) => e.id !== id));

  const handleAddStaffLoan = () =>
    setStaffLoanEntries((prev) => [...prev, { id: crypto.randomUUID(), name: '', loan_amount: 0, monthly_deduction: 0, deduction_start: '' }]);

  const handleUpdateStaffLoan = (id: string, field: keyof Omit<StaffLoanEntry, 'id'>, value: string | number) =>
    setStaffLoanEntries((prev) => prev.map((e) => e.id === id ? { ...e, [field]: value } : e));

  const handleRemoveStaffLoan = (id: string) =>
    setStaffLoanEntries((prev) => prev.filter((e) => e.id !== id));

  const handleYearChange = (year: number) => {
    setSelectedYear(year);
    if (activePreset !== 'custom') {
      const p = buildPresets(year);
      setStartDate(p[activePreset].start);
      setEndDate(p[activePreset].end);
    }
  };

  const applyPreset = (p: Exclude<Preset, 'custom'>) => {
    const presets = buildPresets(selectedYear);
    setActivePreset(p);
    setStartDate(presets[p].start);
    setEndDate(presets[p].end);
  };

  const fetchData = useCallback(() => {
    if (!startDate || !endDate || !datesReadyRef.current) return;
    const cacheKey = `${startDate}:${endDate}`;
    if (_fsCache.has(cacheKey)) {
      setData(_fsCache.get(cacheKey)!);
      return;
    }
    setLoading(true);
    setError(null);
    getComputedFinancialStatements({ start_date: startDate, end_date: endDate })
      .then((result) => { _fsCache.set(cacheKey, result); setData(result); })
      .catch(() => setError('Failed to compute statements. Check your date range or import transactions.'))
      .finally(() => setLoading(false));
  }, [startDate, endDate]);

  // Debounced effect — waits 400 ms after last date change before firing
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(fetchData, 400);
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current); };
  }, [fetchData]);

  const handleDownload = async () => {
    if (!startDate || !endDate) return;
    setDownloading(true);
    try {
      const blob = await downloadComputedFinancialStatements({ start_date: startDate, end_date: endDate });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `Financial_Statements_${startDate}_to_${endDate}.xlsx`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      // silent — user sees no change if download fails
    } finally {
      setDownloading(false);
    }
  };

  const presets = buildPresets(selectedYear);
  const yearOptions = availableYears.length > 0
    ? availableYears
    : Array.from({ length: 5 }, (_, i) => currentYear - i);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Building2 className="h-6 w-6 text-primary" />
            School Financial Statements
          </h1>
          <p className="text-muted-foreground text-sm mt-1">
            Computed from transaction data + asset register — Unaudited Management Accounts
          </p>
        </div>
        {data && (
          <Button
            variant="outline"
            size="sm"
            onClick={handleDownload}
            disabled={downloading}
          >
            <Download className="h-4 w-4 mr-1" />
            {downloading ? 'Generating…' : 'Download Excel'}
          </Button>
        )}
      </div>

      {/* Period controls */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm flex items-center gap-2">
            <CalendarRange className="h-4 w-4 text-primary" />
            Reporting Period
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {/* Year selector + preset chips */}
          <div className="flex flex-wrap items-center gap-2">
            <select
              title="Select reporting year"
              value={selectedYear}
              onChange={(e) => handleYearChange(Number(e.target.value))}
              className="rounded-md border border-input bg-background px-3 py-1.5 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
            >
              {yearOptions.map((y) => (
                <option key={y} value={y}>{y}</option>
              ))}
            </select>

            <div className="h-5 w-px bg-border" />

            {(Object.entries(presets) as [Exclude<Preset,'custom'>, { label: string }][]).map(([key, { label }]) => (
              <button
                type="button"
                key={key}
                onClick={() => applyPreset(key)}
                className={`px-3 py-1.5 rounded-md text-xs font-medium border transition-colors ${
                  activePreset === key
                    ? 'bg-primary text-primary-foreground border-primary'
                    : 'bg-background border-border text-muted-foreground hover:text-foreground hover:border-foreground/40'
                }`}
              >
                {label}
              </button>
            ))}

            <button
              type="button"
              onClick={() => setActivePreset('custom')}
              className={`px-3 py-1.5 rounded-md text-xs font-medium border transition-colors ${
                activePreset === 'custom'
                  ? 'bg-primary text-primary-foreground border-primary'
                  : 'bg-background border-border text-muted-foreground hover:text-foreground hover:border-foreground/40'
              }`}
            >
              Custom
            </button>
          </div>

          {/* Date inputs */}
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex items-center gap-2">
              <label htmlFor="fs-start" className="text-xs text-muted-foreground whitespace-nowrap">From</label>
              <input
                id="fs-start"
                type="date"
                title="Statement period start date"
                value={startDate}
                onChange={(e) => { setStartDate(e.target.value); setActivePreset('custom'); }}
                className="rounded-md border border-input bg-background px-3 py-1.5 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
              />
            </div>
            <div className="flex items-center gap-2">
              <label htmlFor="fs-end" className="text-xs text-muted-foreground whitespace-nowrap">To</label>
              <input
                id="fs-end"
                type="date"
                title="Statement period end date"
                value={endDate}
                onChange={(e) => { setEndDate(e.target.value); setActivePreset('custom'); }}
                className="rounded-md border border-input bg-background px-3 py-1.5 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
              />
            </div>
            {activePreset === 'custom' && (
              <Button type="button" size="sm" variant="outline" onClick={fetchData}>
                Apply
              </Button>
            )}
          </div>

          {data && (
            <p className="text-xs text-muted-foreground">
              Period: <span className="font-medium text-foreground">{data.period}</span>
              {' · '}{data.transaction_count} transactions
              {data.asset_count > 0 && <>{' · '}{data.asset_count} assets (NBV ₦{(data.total_asset_nbv ?? 0).toLocaleString('en-NG', { maximumFractionDigits: 0 })})</>}
            </p>
          )}
        </CardContent>
      </Card>

      {error && (
        <div className="flex items-center gap-2 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          <AlertCircle className="h-4 w-4 shrink-0" />
          {error}
        </div>
      )}

      {loading && (
        <div className="text-center py-16 text-muted-foreground">Computing statements from transactions…</div>
      )}

      {!loading && data && (
        <>
          {/* KPI cards */}
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
            <Card>
              <CardHeader className="pb-1 pt-4 px-4">
                <CardTitle className="text-xs font-medium text-muted-foreground uppercase tracking-wide flex items-center gap-1.5">
                  Total Income
                  <HelpTooltip
                    content={"Sum of all income transactions in the period.\n\nIncludes: school fees, exam fees, book/uniform sales, grants, and other operating income.\n\nExcludes: owner capital injections and internal transfers — those are financing flows, not revenue."}
                    align="left"
                  />
                </CardTitle>
              </CardHeader>
              <CardContent className="px-4 pb-4">
                <p className="text-xl font-bold text-green-600">{formatCurrency(data.profit_loss.total_income)}</p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-1 pt-4 px-4">
                <CardTitle className="text-xs font-medium text-muted-foreground uppercase tracking-wide flex items-center gap-1.5">
                  Admin Expenses
                  <HelpTooltip
                    content={"Total operational costs for the period: salaries, utilities, repairs, stationery, depreciation, etc.\n\nDepreciation from the Asset Register is automatically included.\n\nFinance Costs (bank charges, interest, loans) are excluded here — they appear separately below."}
                    align="left"
                  />
                </CardTitle>
              </CardHeader>
              <CardContent className="px-4 pb-4">
                <p className="text-xl font-bold text-red-600">{formatCurrency(data.profit_loss.total_expenses)}</p>
                {data.profit_loss.total_finance_costs > 0 && (
                  <p className="text-xs text-muted-foreground mt-0.5">
                    + ₦{data.profit_loss.total_finance_costs.toLocaleString('en-NG', { minimumFractionDigits: 2 })} finance costs
                  </p>
                )}
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-1 pt-4 px-4">
                <CardTitle className="text-xs font-medium text-muted-foreground uppercase tracking-wide flex items-center gap-1.5">
                  Profit Before Tax
                  <HelpTooltip
                    content={"Operating Profit − Finance Costs + Other Income\n\nThis is the taxable base used for CIT (Company Income Tax) computation.\n\nExample:\n₦2,100,000 income\n− ₦1,800,000 expenses\n− ₦180,000 finance costs\n= ₦120,000 Profit Before Tax"}
                    align="center"
                  />
                </CardTitle>
              </CardHeader>
              <CardContent className="px-4 pb-4">
                <p className={`text-xl font-bold ${data.profit_loss.profit_before_tax >= 0 ? 'text-foreground' : 'text-red-600'}`}>
                  {formatCurrency(data.profit_loss.profit_before_tax)}
                </p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-1 pt-4 px-4">
                <CardTitle className="text-xs font-medium text-muted-foreground uppercase tracking-wide flex items-center gap-1.5">
                  Net Cash Position
                  <HelpTooltip
                    content={"Total cash and bank balances at the end of the reporting period.\n\nCalculated as: All money-in transactions minus all money-out transactions.\n\nA positive figure means the school has cash on hand. A negative figure (red) indicates a net overdraft position."}
                    align="right"
                  />
                </CardTitle>
              </CardHeader>
              <CardContent className="px-4 pb-4">
                <p className="text-xl font-bold text-blue-600">
                  {formatCurrency(data.financial_position.total_current_assets ?? 0)}
                </p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-1 pt-4 px-4">
                <CardTitle className="text-xs font-medium text-muted-foreground uppercase tracking-wide flex items-center gap-1.5">
                  <Package className="h-3 w-3" />
                  Assets (NBV)
                  <HelpTooltip
                    content={"Net Book Value (NBV) = Original Cost − Accumulated Depreciation\n\nShows the current carrying value of all fixed assets in the Asset Register.\n\nExample:\nComputer purchased for ₦500,000\n− ₦150,000 accumulated depreciation (3 yrs)\n= ₦350,000 NBV\n\nNBV appears in the Financial Position (Balance Sheet) as a Non-Current Asset."}
                    align="right"
                  />
                </CardTitle>
              </CardHeader>
              <CardContent className="px-4 pb-4">
                <p className="text-xl font-bold text-purple-600">{formatCurrency(data.total_asset_nbv ?? 0)}</p>
                <p className="text-xs text-muted-foreground mt-0.5">{data.asset_count} asset{data.asset_count !== 1 ? 's' : ''}</p>
              </CardContent>
            </Card>
          </div>

          {/* Tabs */}
          <div className="border-b border-border">
            <nav className="flex gap-0 -mb-px">
              {TABS.map(({ id, label, icon: Icon }) => (
                <button
                  type="button"
                  key={id}
                  onClick={() => setActiveTab(id)}
                  className={`flex items-center gap-2 px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
                    activeTab === id
                      ? 'border-primary text-primary'
                      : 'border-transparent text-muted-foreground hover:text-foreground hover:border-border'
                  }`}
                >
                  <Icon className="h-4 w-4 shrink-0" />
                  {label}
                </button>
              ))}
            </nav>
          </div>

          {activeTab === 'pl'          && <ProfitLoss data={data.profit_loss} />}
          {activeTab === 'fp'          && (
            <FinancialPosition
              data={data.financial_position}
              loanEntries={loanEntries}
              loanDrawdowns={data.loan_drawdowns}
              loanRepayments={data.loan_repayments}
              staffLoanEntries={staffLoanEntries}
              periodEnd={endDate}
              onAddLoan={handleAddLoan}
              onUpdateLoan={handleUpdateLoan}
              onRemoveLoan={handleRemoveLoan}
              onAddStaffLoan={handleAddStaffLoan}
              onUpdateStaffLoan={handleUpdateStaffLoan}
              onRemoveStaffLoan={handleRemoveStaffLoan}
            />
          )}
          {activeTab === 'cf'          && <CashFlows data={data.cash_flow_statement} />}
          {activeTab === 'ce'          && <ChangesInEquity data={data.changes_in_equity} comparatives={data.comparatives} />}
          {activeTab === 'notes'       && <NotesSection notes={data.notes} comparatives={data.comparatives} period={data.period} />}
          {activeTab === 'declaration' && <DeclarationSection data={data} />}
        </>
      )}

      {!loading && !data && !error && (
        <div className="text-center py-16 text-muted-foreground">
          <FileSpreadsheet className="h-12 w-12 mx-auto mb-3 opacity-30" />
          <p>No transactions found for the selected period.</p>
          <p className="text-sm mt-1">Try a different date range or import transactions first.</p>
        </div>
      )}

      {!loading && data && data.transaction_count === 0 && (
        <div className="text-center py-8 text-muted-foreground">
          <TrendingDown className="h-8 w-8 mx-auto mb-2 opacity-30" />
          <p className="text-sm">No transactions found for {data.period}.</p>
        </div>
      )}
    </div>
  );
}
