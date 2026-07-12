// ── Authentication ────────────────────────────────────────────────────────────

export interface Role {
  id: number;
  name: string;
  description: string | null;
  is_system: boolean;
  permissions: string[];
}

export interface RoleIn {
  name: string;
  description?: string | null;
  permission_keys: string[];
}

export interface Permission {
  key: string;
  label: string;
}

export interface User {
  id: number;
  email: string;
  full_name?: string;
  is_active: boolean;
  role: Role | null;
  created_at: string;
}

export interface UserAdminUpdate {
  is_active?: boolean;
  role_id?: number | null;
  full_name?: string;
}

// ── Transactions ──────────────────────────────────────────────────────────────

export type TransactionType = 'expense' | 'income' | 'transfer';

export type MatchStatus = 'unmatched' | 'matched' | 'discrepancy';

export interface Transaction {
  id: number;
  type: TransactionType;
  amount: number;
  currency: string;
  category: string;
  description: string;
  date: string;
  vendor: string;
  bank?: string;
  bank_account_id?: number;
  file_id?: number;
  created_at: string;
  updated_at: string;
  // Duplicate detection fields
  is_potential_duplicate?: boolean;
  duplicate_of_id?: number;
  duplicate_reviewed?: boolean;
  duplicate_confidence?: number;
}

export interface TransactionCreate {
  type: TransactionType;
  amount: number;
  currency?: string;
  category: string;
  description: string;
  date: string;
  vendor?: string;
  bank?: string;
  file_id?: number;
}

export interface PaginatedTransactions {
  items: Transaction[];
  total: number;
  limit: number;
  offset: number;
}

export interface TransactionSummary {
  total_income: number;
  total_expenses: number;
  balance: number;
  by_category: Record<string, number>;
  expense_by_category: Record<string, number>;
  income_by_category: Record<string, number>;
  monthly: Array<{ month: string; income: number; expenses: number }>;
}

export interface TransactionAISummary {
  narrative: string | null;
  available: boolean;
}

export interface UploadedFile {
  id: number;
  original_name: string;
  stored_path: string;
  mime_type: string;
  ocr_text?: string;
  ai_result?: {
    amount?: number;
    currency?: string;
    date?: string;
    vendor?: string;
    category?: string;
    type?: TransactionType;
    description?: string;
  };
  created_at: string;
}

export interface BankStatement {
  id: number;
  bank_name: string;
  account_last4?: string;
  statement_period_start?: string;
  statement_period_end?: string;
  file_path: string;
  file_type: 'csv' | 'excel' | 'pdf';
  status: 'pending' | 'reconciled';
  created_at: string;
  transaction_count?: number;
  matched_count?: number;
}

export interface BankTransaction {
  id: number;
  statement_id: number;
  date: string;
  description: string;
  amount: number;
  transaction_type: 'debit' | 'credit';
  reference?: string;
  matched_transaction_id?: number;
  match_status: MatchStatus;
  match_confidence?: number;
  suggested_category?: string;
  suggested_type?: TransactionType;
  created_at: string;
}

export interface ReconciliationStatus {
  statement_id: number;
  total: number;
  matched: number;
  unmatched: number;
  discrepancies: number;
}

export interface BankAccount {
  id: number;
  bank_name: string;
  account_holder_name?: string;
  account_number?: string;
  opening_balance?: number | null;
  current_balance?: number | null;
  created_at: string;
  transaction_count?: number;
}

export interface BankAccountCreate {
  bank_name: string;
  account_holder_name?: string;
  account_number?: string;
  opening_balance?: number | null;
  current_balance?: number | null;
}

export interface Term {
  id: number;
  name: string;
  start_date: string;
  end_date: string;
  created_at: string;
}

export interface TermCreate {
  name: string;
  start_date: string;
  end_date: string;
}

export interface AuditLogEntry {
  id: number;
  entity_type: string;
  entity_id: number;
  action: string;
  old_values?: Record<string, unknown>;
  new_values?: Record<string, unknown>;
  timestamp: string;
}

// ── Batch Upload ──────────────────────────────────────────────────────────────

export interface BatchItem {
  amount?: number;
  currency?: string;
  date?: string;
  vendor?: string;
  category?: string;
  type?: TransactionType;
  description?: string;
  reference?: string;
}

export interface BatchUploadResult {
  file_id: number;
  original_name: string;
  mime_type: string;
  item_count: number;
  items: BatchItem[];
}

export interface BatchConfirmItem {
  amount: number;
  currency: string;
  category: string;
  description: string;
  date: string;
  vendor?: string;
  bank?: string;
  type: TransactionType;
  file_id?: number;
}

// ── Statement Import ──────────────────────────────────────────────────────────

export interface StatementImportItem {
  bank_transaction_id: number;
  amount: number;
  currency: string;
  category: string;
  description: string;
  date: string;
  vendor?: string;
  type: TransactionType;
}

export interface StatementImportRequest {
  items: StatementImportItem[];
}

export interface StatementImportResult {
  saved: number;            // new transactions created
  reconciled: number;       // duplicates linked to reconciliation
  duplicates_flagged: number;   // duplicates flagged for manual review
  duplicates_resolved: number;  // duplicates auto-resolved
  statement_id: number;
}

export interface ValidationCheck {
  name: string;
  status: 'pass' | 'warn' | 'fail';
  message: string;
  count: number;
  details: Record<string, unknown>[];
}

export interface ValidationReport {
  statement_id: number;
  total_transactions: number;
  can_import: boolean;
  error_count: number;
  warning_count: number;
  checks: ValidationCheck[];
}

export const EXPENSE_CATEGORIES = [
  // Staff & directors
  'Salary and Wages',
  'IOU (Advance Salary)',
  'Employee Benefit Expenses',
  'Directors Emoluments',
  'Directors Expenses',
  'Staff Allowances',
  'Staff Loan Written Off',
  'Staff Gratuity',
  'Pension and Gratuity',
  'Other Staff & Related Cost',
  // Non-cash / statutory
  'Depreciation',
  'Amortisation of Intangible Assets',
  'Government and Regulatory Costs',
  'Bad Debt Written Off',
  'Loans',
  'Interest Expense',
  'Bank Charges',
  'Audit Fees',
  'Other Professional Fees',
  'AMCON Charges',
  'Realized Foreign Exchange Loss',
  'Fines',
  'Penalties',
  'Other Statutory Charges & Levies',
  'Licences & Leases Charges',
  'Permits',
  'Rates',
  'Royalties',
  // Marketing & relations
  'Advertisement & Promotion',
  'Corporate Promotion',
  'Public Relation',
  'Publication Cost',
  'Newspaper & Periodicals',
  'Trade Fairs & Exhibitions',
  'Sponsorship',
  'Corporate Social Responsibilities',
  'Donations',
  // Operating costs
  'Rent & Rates',
  'Rooms/Accommodation Cost',
  'Head Office Cost',
  'Electricity & Power',
  'Utilities',
  'Internet Cost',
  'Telephone',
  'Postages',
  'Fuel Expenses',
  'AGO-Diesel',
  'PMS',
  'Generator Expenses',
  'Repairs and Maintenance',
  'Security Expenses',
  'Cleaning & Janitorial Services',
  'Health, Safety and Environmental Expenses',
  'Medical Expenses',
  'Entertainment Expenses',
  'Stationeries Expenses',
  'Software Maintenance',
  'Website Design & Maintenance',
  'Subscription & Dues',
  'Service Charge',
  'Training and Development',
  'Research Cost',
  'Outsourcing Services Expenses',
  'Selling & Distribution Expenses',
  'Freight & Transport Expenses',
  'Transport of Supplies',
  'Travel Expenses',
  'Loss on Sale of Property, Plant and Equipment',
  // School-operational (school both buys and sells these)
  'Books',
  'Uniform',
  'Exam',
  // System
  'Internal Transfer',
  'Other',
];

export const INCOME_CATEGORIES = [
  'School Fees',
  'Exam',
  'Stationery',
  'Books',
  'Uniform',
  'Software',
  'Fund from Director',
  'Freelance',
  'Investment',
  'Business',
  'Loans',
  'Gift',
  'Refund',
  'Internal Transfer',
  'Other',
];
// ── LLM Bank Statement Parsing ────────────────────────────────────────────────

export interface LLMBankStatementMetadata {
  bank_name: string;
  account_number?: string;
  account_holder?: string;
  statement_period_start?: string;
  statement_period_end?: string;
  opening_balance?: number;
  closing_balance?: number;
  currency: string;
  statement_date?: string;
}

export interface LLMBankTransactionItem {
  date: string;
  description: string;
  amount: number;
  transaction_type: 'debit' | 'credit';
  balance_after?: number;
  reference?: string;
  vendor?: string;
  category_suggested?: string;
  confidence: number;
}

export interface LLMStatementParseResult {
  metadata: LLMBankStatementMetadata;
  transactions: LLMBankTransactionItem[];
  extraction_quality: 'high' | 'medium' | 'low';
  validation_issues: string[];
}

export interface LLMStatementUploadResult {
  statement_id: number;
  file_name: string;
  bank_name: string;
  statement_period_start?: string;
  statement_period_end?: string;
  transaction_count: number;
  extraction_quality: 'high' | 'medium' | 'low';
  validation_issues: string[];
  metadata: LLMBankStatementMetadata;
}

export interface LLMStatementImportItem {
  transaction_index: number;
  amount: number;
  currency: string;
  category: string;
  description: string;
  date: string;
  vendor?: string;
  type: TransactionType;
}

export interface LLMStatementImportRequest {
  statement_id: number;
  items: LLMStatementImportItem[];
  bank_account_id?: number;
}

export interface LLMStatementImportResult {
  saved: number;
  reconciled: number;
  statement_id: number;
}

// ── Bank Account Reports ──────────────────────────────────────────────────────

export interface BankAccountReportSummary {
  bank_account_id: number;
  bank_name: string;
  account_holder_name: string | null;
  account_number: string | null;
  opening_balance: number;
  total_income: number;
  total_expense: number;
  total_transfer: number;
  net_amount: number;
  income_count: number;
  expense_count: number;
  transfer_count: number;
  total_transactions: number;
  first_transaction_date: string | null;
  last_transaction_date: string | null;
  currency: string;
}

export interface BankAccountReport extends BankAccountReportSummary {
  expense_by_category: Record<string, number>;
  income_by_category: Record<string, number>;
  monthly_breakdown: Record<string, { income: number; expense: number; transfer: number }>;
}

// ── School Financial Statements ──────────────────────────────────────────────

export interface FSLineItem {
  label: string;
  amount: number | string | null;
}

export interface FSProfitLoss {
  company: string;
  title: string;
  period: string;
  income_items: FSLineItem[];
  total_income: number;
  expense_items: FSLineItem[];
  total_expenses: number;
  operating_profit: number;
  finance_cost_items: FSLineItem[];
  total_finance_costs: number;
  profit_before_tax: number;
  tax_items: FSLineItem[];
  total_tax: number;
  net_profit: string;
  notes: string[];
}

export interface FSFinancialPosition {
  company: string;
  title: string;
  as_at: string;
  non_current_asset_items: FSLineItem[];
  total_non_current_assets: number;
  current_asset_items: FSLineItem[];
  total_current_assets: number;
  total_assets: string;
  equity_items: FSLineItem[];
  total_equity: number;
  non_current_liability_items: FSLineItem[];
  total_liabilities: number;
  total_equity_and_liabilities: string;
  notes: string[];
}

export interface FSNoteLine {
  label: string;
  value: number | string | null;
}

export interface FSNote {
  title: string;
  lines: FSNoteLine[];
  table: (string | number)[][];
}

export interface FSLoanRow {
  month: string | null;
  opening_balance: number | null;
  payment: number | null;
  interest: number | null;
  principal: number | null;
  closing_balance: number | null;
}

export interface FSLoanSchedule {
  title: string;
  subtitle: string;
  period: string;
  columns: string[];
  rows: (string | number | null)[][];
  summary: FSNoteLine[];
}

export interface FinancialStatements {
  profit_loss: FSProfitLoss;
  financial_position: FSFinancialPosition;
  notes: FSNote[];
  loan_schedule: FSLoanSchedule;
}

export interface FSCashFlowItem {
  label: string;
  amount: number;
}

export interface FSCashFlowStatement {
  company: string;
  title: string;
  period: string;
  method: string;
  operating_items: FSCashFlowItem[];
  total_operating: number;
  investing_items: FSCashFlowItem[];
  total_investing: number;
  financing_items: FSCashFlowItem[];
  total_financing: number;
  net_movement: number;
  opening_cash: number;
  closing_cash: number;
  notes: string[];
}

export interface FSChangesInEquity {
  company: string;
  title: string;
  period: string;
  opening_retained_earnings: number;
  net_profit_for_period: number;
  dividends_drawings: number;
  closing_retained_earnings: number;
  note: string;
}

export interface FSNoteSubsection {
  subtitle: string;
  text: string;
}

export interface FSNoteLineItem {
  label: string;
  amount: number;
}

export interface FSPPEItem {
  name: string;
  category: string;
  purchase_date: string;
  cost: number;
  useful_life_years: number;
  residual_value: number;
  depreciation_method: string;
  period_depreciation: number;
  accumulated_depreciation: number;
  nbv: number;
}

export interface FSNoteSection {
  number: string;
  title: string;
  text?: string;
  subsections: FSNoteSubsection[];
  items?: FSNoteLineItem[] | FSPPEItem[];
  total?: number;
  total_cost?: number;
  total_period_dep?: number;
  total_accumulated_dep?: number;
  total_nbv?: number;
}

export interface FSSignatory {
  role: string;
  name: string;
  date: string;
}

export interface FSDirectorDeclaration {
  company: string;
  period_ended: string;
  clauses: string[];
  signatories: FSSignatory[];
  authority: string;
}

export interface FSAuditParagraph {
  heading: string;
  text?: string;
  list: string[];
}

export interface FSAuditorReport {
  status: string;
  type: string;
  company: string;
  period_ended: string;
  paragraphs: FSAuditParagraph[];
  disclaimer: string;
}

export interface FSComparatives {
  period: string;
  total_income: number;
  total_admin_expenses: number;
  total_finance_costs: number;
  operating_profit: number;
  profit_before_tax: number;
  total_tax: number;
  net_profit: number;
  total_asset_nbv: number;
  transaction_count: number;
}

export interface ComputedFinancialStatements {
  mode: 'computed';
  period: string;
  start_date: string;
  end_date: string;
  transaction_count: number;
  asset_count: number;
  total_asset_nbv: number;
  loan_repayments: number;
  loan_drawdowns: number;
  staff_loans_outstanding: number;
  profit_loss: FSProfitLoss;
  financial_position: FSFinancialPosition;
  cash_flow_statement: FSCashFlowStatement;
  changes_in_equity: FSChangesInEquity;
  notes: FSNoteSection[];
  director_declaration: FSDirectorDeclaration;
  auditor_report: FSAuditorReport;
  comparatives: FSComparatives;
}

// ── Staff Directory ───────────────────────────────────────────────────────────

export interface StaffMember {
  id: number;
  full_name: string;
  role: string | null;
  bank_name: string | null;
  account_number: string | null;
  monthly_gross: number;
  start_date: string | null;
  end_date: string | null;
  is_active: boolean;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface StaffMemberIn {
  full_name: string;
  role?: string | null;
  bank_name?: string | null;
  account_number?: string | null;
  monthly_gross?: number;
  start_date?: string | null;
  end_date?: string | null;
  is_active?: boolean;
  notes?: string | null;
}

// ── Staff Loans ───────────────────────────────────────────────────────────────

export interface MatchedTransaction {
  id: number;
  date: string;
  amount: number;
  description: string;
  vendor: string | null;
  category: string;
}

export interface LoanPayment {
  id: number;
  loan_id: number;
  transaction_id: number | null;
  amount_paid: number;
  paid_date: string;
  notes: string | null;
  verified: boolean;
  matched_tx: MatchedTransaction | null;
  created_at: string;
  updated_at: string;
}

export interface LoanPaymentIn {
  amount_paid: number;
  paid_date: string;
  transaction_id?: number | null;
  notes?: string | null;
}

export interface StaffLoan {
  id: number;
  staff_id: number | null;
  employee_name: string;
  loan_amount: number;
  deduction_rate: number;
  deduction_start: string;
  notes: string | null;
  is_active: boolean;
  outstanding_today: number;
  total_paid: number;
  monthly_deduction_amount: number;
  payments: LoanPayment[];
  created_at: string;
  updated_at: string;
}

export interface StaffLoanIn {
  staff_id?: number | null;
  employee_name?: string;
  loan_amount: number;
  deduction_rate: number;
  deduction_start: string;
  notes?: string | null;
  is_active?: boolean;
}

// ── Advance Payment (IOU) ────────────────────────────────────────────────────────

export interface AdvancePayment {
  id: number;
  staff_id: number;
  staff_name: string;
  amount: number;
  remaining_amount: number;
  date_issued: string;
  transaction_id: number | null;
  is_recovered: boolean;
  recovered_period_year: number | null;
  recovered_period_month: number | null;
  notes: string | null;
  verified: boolean;
  matched_tx: MatchedTransaction | null;
  created_at: string;
  updated_at: string;
}

export interface AdvancePaymentIn {
  staff_id: number;
  amount: number;
  date_issued: string;
  transaction_id?: number | null;
  notes?: string | null;
}

// ── School Loans (loans the school has borrowed) ───────────────────────────────

export interface SchoolLoanPaymentOut {
  id: number;
  loan_id: number;
  transaction_id: number | null;
  amount_paid: number;
  interest_amount: number;
  misc_amount: number;
  principal_paid: number;
  paid_date: string;
  notes: string | null;
  verified: boolean;
  matched_tx: MatchedTransaction | null;
  created_at: string;
  updated_at: string;
}

export interface SchoolLoanPaymentIn {
  amount_paid: number;
  interest_amount?: number;
  misc_amount?: number;
  paid_date: string;
  transaction_id?: number | null;
  notes?: string | null;
}

export interface SchoolLoan {
  id: number;
  lender_name: string;
  loan_amount: number;
  interest_rate: number;
  total_interest_due: number;
  collected_date: string;
  notes: string | null;
  is_active: boolean;
  outstanding_today: number;
  outstanding_interest: number;
  fully_paid: boolean;
  total_paid: number;
  total_interest_paid: number;
  total_misc_paid: number;
  payments: SchoolLoanPaymentOut[];
  created_at: string;
  updated_at: string;
}

export interface SchoolLoanIn {
  lender_name: string;
  loan_amount: number;
  interest_rate: number;
  total_interest_due: number;
  collected_date: string;
  notes?: string | null;
  is_active?: boolean;
}

// ── Payroll ───────────────────────────────────────────────────────────────────

export interface PayrollLine {
  staff_id: number;
  full_name: string;
  role: string | null;
  gross_salary: number;
  bonus: number;
  loan_deduction: number;
  advance_deduction: number;
  other_deductions: number;
  net_salary: number;
  is_paid: boolean;
  paid_date: string | null;
  entry_id: number | null;
}

export interface PayrollLineIn {
  staff_id: number;
  gross_salary: number;
  bonus: number;
  other_deductions: number;
  notes?: string | null;
  transaction_id?: number;
}

export interface PayrollEntryOut {
  id: number;
  staff_id: number;
  full_name: string;
  period_year: number;
  period_month: number;
  gross_salary: number;
  bonus: number;
  loan_deduction: number;
  advance_deduction: number;
  other_deductions: number;
  net_salary: number;
  is_paid: boolean;
  paid_date: string | null;
  transaction_id: number | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

// ── School Assets ─────────────────────────────────────────────────────────────

export interface Asset {
  id: number;
  name: string;
  category: string;
  purchase_date: string;
  purchase_cost: number;
  useful_life_years: number;
  depreciation_method: 'straight_line' | 'reducing_balance';
  residual_value: number;
  accumulated_depreciation: number;
  net_book_value: number;
  annual_depreciation: number | null;
  notes?: string | null;
  created_at: string;
  updated_at: string;
}

export interface AssetCreate {
  name: string;
  category: string;
  purchase_date: string;
  purchase_cost: number;
  useful_life_years: number;
  depreciation_method: 'straight_line' | 'reducing_balance';
  residual_value: number;
  notes?: string;
}

export interface AssetCategorySummary {
  category: string;
  cost: number;
  accumulated_depreciation: number;
  net_book_value: number;
  period_depreciation: number;
  count: number;
}

export interface AssetsSummary {
  start_date: string;
  end_date: string;
  asset_count: number;
  categories: AssetCategorySummary[];
  total_cost: number;
  total_accumulated_depreciation: number;
  total_net_book_value: number;
  total_period_depreciation: number;
}

// ── Tax (Nigeria CIT) ─────────────────────────────────────────────────────────

export interface TaxSummary {
  year: number | null;
  start_date: string | null;
  end_date: string | null;
  period_label: string;
  revenue_by_sector: Record<string, number>;
  other_income: Record<string, number>;
  admin_expenses: Record<string, number>;
  total_revenue: number;
  total_other_income: number;
  total_admin_expenses: number;
  gross_profit: number;
  profit_before_tax: number;
  add_backs: Record<string, number>;
  total_add_backs: number;
  adjusted_profit: number;
  company_size: string;
  tax_rate: number;
  tax_payable: number;
  minimum_tax: number;
  minimum_tax_applies: boolean;
  effective_tax_payable: number;
  transaction_count: number;
  flagged_categories: Array<{ category: string; amount: number; reason: string }>;
}

// ── Inventory ────────────────────────────────────────────────────────────────

export interface InventoryItem {
  id: number;
  name: string;
  sku: string | null;
  category: string;
  unit: string;
  unit_cost: number;
  unit_price: number;
  quantity_on_hand: number;
  reorder_level: number;
  is_low_stock: boolean;
  is_active: boolean;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface InventoryItemIn {
  name: string;
  sku?: string | null;
  category: string;
  unit?: string;
  unit_cost?: number;
  unit_price?: number;
  reorder_level?: number;
  is_active?: boolean;
  notes?: string | null;
}

export type StockRequestType = 'purchase' | 'sale';
export type StockRequestStatus = 'pending' | 'fulfilled' | 'cancelled';

export interface StockRequest {
  id: number;
  item_id: number;
  item_name: string;
  item_sku: string | null;
  request_type: StockRequestType;
  quantity: number;
  unit_amount: number;
  counterparty: string | null;
  status: StockRequestStatus;
  request_date: string;
  fulfilled_date: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface StockRequestIn {
  item_id: number;
  request_type: StockRequestType;
  quantity: number;
  unit_amount: number;
  counterparty?: string | null;
  request_date: string;
  notes?: string | null;
}

export type StockMovementType = 'purchase_in' | 'sale_out' | 'adjustment_in' | 'adjustment_out';

export interface StockMovement {
  id: number;
  item_id: number | null;
  item_name: string | null;
  movement_type: StockMovementType;
  quantity: number;
  unit_amount: number | null;
  date: string;
  request_id: number | null;
  transaction_id: number | null;
  notes: string | null;
  created_at: string;
}

export interface StockAdjustmentIn {
  item_id: number;
  movement_type: 'adjustment_in' | 'adjustment_out';
  quantity: number;
  date: string;
  notes?: string | null;
}