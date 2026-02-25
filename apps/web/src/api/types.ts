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

export interface TransactionSummary {
  total_income: number;
  total_expenses: number;
  balance: number;
  by_category: Record<string, number>;
  expense_by_category: Record<string, number>;
  income_by_category: Record<string, number>;
  monthly: Array<{ month: string; income: number; expenses: number }>;
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
  account_number?: string;
  created_at: string;
  transaction_count?: number;
}

export interface BankAccountCreate {
  bank_name: string;
  account_number?: string;
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

export const EXPENSE_CATEGORIES = [
  'Food & Dining',
  'Transportation',
  'Shopping',
  'Entertainment',
  'Bills & Utilities',
  'Healthcare',
  'Travel',
  'Education',
  'School Fees',
  'Housing',
  'Administration',
  'Salary',
  'Loans',
  'Repairs',
  'Bank Charges & Fees',
  'Internal Transfer',
  'Other',
];

export const INCOME_CATEGORIES = [
  'Salary',
  'School Fees',
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
  account_number: string | null;
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