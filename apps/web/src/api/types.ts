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
  file_id?: number;
  created_at: string;
  updated_at: string;
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
  saved: number;       // new transactions created
  reconciled: number;  // duplicates linked to reconciliation
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
  'Housing',
  'Bank Charges & Fees',
  'Internal Transfer',
  'Other',
];

export const INCOME_CATEGORIES = [
  'Salary',
  'Freelance',
  'Investment',
  'Business',
  'Gift',
  'Refund',
  'Other',
];
