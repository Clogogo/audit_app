import axios, { type AxiosResponse } from 'axios';
import type {
  Transaction,
  TransactionCreate,
  TransactionSummary,
  TransactionAISummary,
  PaginatedTransactions,
  UploadedFile,
  BankStatement,
  BankTransaction,
  BankAccount,
  BankAccountCreate,
  ReconciliationStatus,
  AuditLogEntry,
  BatchUploadResult,
  BatchConfirmItem,
  StatementImportItem,
  StatementImportResult,
  ValidationReport,
  LLMStatementParseResult,
  LLMStatementUploadResult,
  LLMStatementImportRequest,
  LLMStatementImportResult,
  BankAccountReportSummary,
  BankAccountReport,
  TaxSummary,
  ComputedFinancialStatements,
  Asset,
  AssetCreate,
  AssetsSummary,
  Term,
  TermCreate,
} from './types';

// In production VITE_API_URL points to the Render backend (e.g. https://financeaudit-api.onrender.com)
// In development the Vite proxy rewrites /api → localhost:8000
const baseURL = import.meta.env.VITE_API_URL
  ? `${import.meta.env.VITE_API_URL}`
  : '/api';

const api = axios.create({
  baseURL,
  headers: { 'Content-Type': 'application/json' },
});

// Add Authorization header to all requests if token exists
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

const unwrap = <T>(r: AxiosResponse<T>) => r.data;

// Transactions
export const getTransactions = (params?: {
  type?: string;
  category?: string;
  bank?: string;
  vendor?: string;
  start_date?: string;
  end_date?: string;
  limit?: number;
  offset?: number;
}) => api.get<PaginatedTransactions>('/transactions', { params }).then(unwrap);

export const getTransactionYears = () =>
  api.get<number[]>('/transactions/years').then(unwrap);

export const getSummary = (params?: {
  start_date?: string;
  end_date?: string;
  bank?: string;
  vendor?: string;
}) => api.get<TransactionSummary>('/transactions/summary', { params }).then(unwrap);

export const getAISummary = (params?: {
  start_date?: string;
  end_date?: string;
  bank?: string;
  vendor?: string;
}) => api.get<TransactionAISummary>('/transactions/ai-summary', { params }).then(unwrap);

export const createTransaction = (body: TransactionCreate) =>
  api.post<Transaction>('/transactions', body).then(unwrap);

export const updateTransaction = (id: number, body: Partial<TransactionCreate>) =>
  api.put<Transaction>(`/transactions/${id}`, body).then(unwrap);

export const deleteTransaction = (id: number) =>
  api.delete<{ ok: boolean }>(`/transactions/${id}`).then(unwrap);

export const batchUpdateCategory = (ids: number[], category: string) =>
  api.patch<{ updated: number }>('/transactions/batch-category', { ids, category }).then(unwrap);

// File Upload + AI
export const uploadFile = (file: File) => {
  const form = new FormData();
  form.append('file', file);
  return api
    .post<UploadedFile>('/upload', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    .then(unwrap);
};

export const confirmUpload = (uploadId: number, body: TransactionCreate) =>
  api.post<Transaction>(`/upload/${uploadId}/confirm`, body).then(unwrap);

export const uploadBatch = (file: File) => {
  const form = new FormData();
  form.append('file', file);
  return api
    .post<BatchUploadResult>('/upload/batch', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    .then(unwrap);
};

export const confirmBatch = (fileId: number, items: BatchConfirmItem[]) =>
  api.post<{ saved: number }>(`/upload/batch/${fileId}/confirm`, { items }).then(unwrap);

export const getFilePreviewUrl = (fileId: number) => `/api/upload/${fileId}/preview`;

// Bank Statements
export const uploadBankStatement = (file: File, bankName: string, accountHolderName?: string) => {
  const form = new FormData();
  form.append('file', file);
  form.append('bank_name', bankName);
  if (accountHolderName) {
    form.append('account_holder_name', accountHolderName);
  }
  return api
    .post<BankStatement>('/bank-statements', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    .then(unwrap);
};

export const getBankStatements = () =>
  api.get<BankStatement[]>('/bank-statements').then(unwrap);

export const deleteBankStatement = (stmtId: number) =>
  api.delete(`/bank-statements/${stmtId}`);

export const batchDeleteBankStatements = (ids: number[]) =>
  api.post<{ deleted: number }>('/bank-statements/batch-delete', { ids }).then(unwrap);

export const getBankTransactions = (statementId: number) =>
  api.get<BankTransaction[]>(`/bank-statements/${statementId}/transactions`).then(unwrap);

export const importStatementTransactions = (
  stmtId: number,
  items: StatementImportItem[],
  bankAccountId?: number,
  resolutionMode: 'manual' | 'auto' = 'manual',
) =>
  api.post<StatementImportResult>(`/bank-statements/${stmtId}/import-transactions`, {
    items,
    bank_account_id: bankAccountId ?? null,
    resolution_mode: resolutionMode,
  }).then(unwrap);

export const validateBankStatement = (stmtId: number) =>
  api.get<ValidationReport>(`/bank-statements/${stmtId}/validate`).then(unwrap);

export const autoMatch = (statementId: number) =>
  api.post<{ matched: number }>(`/reconcile/${statementId}/auto-match`).then(unwrap);

export const manualMatch = (bankTxId: number, transactionId: number) =>
  api
    .post<{ ok: boolean }>('/reconcile/manual-match', {
      bank_transaction_id: bankTxId,
      transaction_id: transactionId,
    })
    .then(unwrap);

export const unmatch = (bankTxId: number) =>
  api.delete<{ ok: boolean }>(`/reconcile/match/${bankTxId}`).then(unwrap);

export const getReconciliationStatus = (statementId: number) =>
  api.get<ReconciliationStatus>(`/reconcile/${statementId}/status`).then(unwrap);

export const exportReconciliation = (statementId: number, format: 'csv' | 'pdf') =>
  api
    .get<Blob>(`/reconcile/${statementId}/export`, {
      params: { format },
      responseType: 'blob',
    })
    .then(unwrap);

// Duplicate Detection
export const scanDuplicates = () =>
  api.post<{ scanned: number; flagged: number }>('/duplicates/scan').then(unwrap);

export const getPendingDuplicates = () =>
  api.get<Transaction[]>('/duplicates/pending').then(unwrap);

export const keepTransaction = (txId: number) =>
  api.post<{ ok: boolean }>(`/duplicates/${txId}/keep`).then(unwrap);

export const markNotDuplicate = (txId: number) =>
  api.post<{ ok: boolean }>(`/duplicates/${txId}/mark-not-duplicate`).then(unwrap);

export const getDuplicateStats = () =>
  api.get<{ total_duplicates: number; pending: number; reviewed: number }>('/duplicates/stats').then(unwrap);

// Bank Accounts
export const getBankAccounts = () =>
  api.get<BankAccount[]>('/bank-accounts').then(unwrap);

export const createBankAccount = (body: BankAccountCreate) =>
  api.post<BankAccount>('/bank-accounts', body).then(unwrap);

export const updateBankAccount = (id: number, body: BankAccountCreate) =>
  api.put<BankAccount>(`/bank-accounts/${id}`, body).then(unwrap);

export const deleteBankAccount = (id: number) =>
  api.delete<void>(`/bank-accounts/${id}`).then(unwrap);

export const updateBankAccountBalance = (id: number, balance: number | null) =>
  api.patch<BankAccount>(`/bank-accounts/${id}/balance`, { current_balance: balance }).then(unwrap);

// Terms — named custom date ranges, reusable as a filter across pages
export const getTerms = () =>
  api.get<Term[]>('/terms/').then(unwrap);

export const createTerm = (body: TermCreate) =>
  api.post<Term>('/terms/', body).then(unwrap);

export const updateTerm = (id: number, body: TermCreate) =>
  api.put<Term>(`/terms/${id}`, body).then(unwrap);

export const deleteTerm = (id: number) =>
  api.delete<void>(`/terms/${id}`).then(unwrap);

export const updateBankAccountOpeningBalance = (id: number, opening_balance: number | null) =>
  api.patch<BankAccount>(`/bank-accounts/${id}/opening-balance`, { opening_balance }).then(unwrap);

export const getAccountTransactions = (accountId: number) =>
  api.get<Transaction[]>(`/bank-accounts/${accountId}/transactions`).then(unwrap);

export const linkTransaction = (accountId: number, txId: number) =>
  api.patch<{ ok: boolean }>(`/bank-accounts/${accountId}/transactions/${txId}`).then(unwrap);

export const unlinkTransaction = (accountId: number, txId: number) =>
  api.delete<{ ok: boolean }>(`/bank-accounts/${accountId}/transactions/${txId}`).then(unwrap);

// Reports
export const exportReport = (
  format: 'csv' | 'pdf',
  params?: { start_date?: string; end_date?: string },
) =>
  api
    .get<Blob>('/reports/export', { params: { format, ...params }, responseType: 'blob' })
    .then(unwrap);

export const exportAuditReport = (params: {
  start_date?: string;
  end_date?: string;
  opinion?: 'unqualified' | 'qualified';
  qualification_note?: string;
}) =>
  api
    .get<Blob>('/reports/audit-report', { params, responseType: 'blob' })
    .then(unwrap);

// Audit Log
export const getAuditLog = (params?: {
  entity_type?: string;
  entity_id?: number;
  limit?: number;
}) => api.get<AuditLogEntry[]>('/audit-log', { params }).then(unwrap);

// Health / AI status
export interface HealthStatus {
  status: string;
  ai: {
    provider: string;
    model: string;
    configured: boolean;
    ollama_available: boolean;
  };
}
export const getHealth = () => api.get<HealthStatus>('/health').then(unwrap);
// ── LLM Bank Statement Parsing ────────────────────────────────────────────────

export const parseBankStatementLLM = (file: File) => {
  const form = new FormData();
  form.append('file', file);
  return api
    .post<LLMStatementParseResult>('/bank-statements-llm/parse', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    .then(unwrap);
};

export const uploadBankStatementLLM = (file: File, bankAccountId?: number) => {
  const form = new FormData();
  form.append('file', file);
  if (bankAccountId) {
    form.append('bank_account_id', bankAccountId.toString());
  }
  return api
    .post<LLMStatementUploadResult>('/bank-statements-llm/upload', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    .then(unwrap);
};

export const getLLMStatementTransactions = (statementId: number) =>
  api.get<BankTransaction[]>(`/bank-statements-llm/${statementId}/transactions`).then(unwrap);

export const importLLMStatementTransactions = (
  stmtId: number,
  items: LLMStatementImportRequest['items'],
  bankAccountId?: number,
) =>
  api.post<LLMStatementImportResult>(`/bank-statements-llm/${stmtId}/import`, {
    statement_id: stmtId,
    items,
    bank_account_id: bankAccountId ?? null,
  }).then(unwrap);

export const deleteLLMStatement = (stmtId: number) =>
  api.delete(`/bank-statements-llm/${stmtId}`);

// ── Bank Account Reports ──────────────────────────────────────────────────────

export const getBankAccountReports = (params?: { start_date?: string; end_date?: string }) =>
  api.get<BankAccountReportSummary[]>('/bank-statements/bank-accounts', { params }).then(unwrap);

export const getBankAccountReport = (
  accountId: number,
  params?: { start_date?: string; end_date?: string }
) =>
  api.get<BankAccountReport>(`/bank-statements/bank-accounts/${accountId}`, { params }).then(unwrap);

// ── Authentication ────────────────────────────────────────────────────────────

// ── Tax (Nigeria CIT) ─────────────────────────────────────────────────────────

export const getTaxSummary = (params: {
  year?: number;
  start_date?: string;
  end_date?: string;
}) => api.get<TaxSummary>('/tax/summary', { params }).then(unwrap);

export const getTaxYears = () =>
  api.get<number[]>('/tax/years').then(unwrap);

export const exportCITExcel = (params: {
  year?: number;
  start_date?: string;
  end_date?: string;
  share_capital?: number;
  retained_earnings_bf?: number;
  short_term_debt?: number;
  other_reserves?: number;
}) =>
  api
    .get<Blob>('/tax/export', { params, responseType: 'blob' })
    .then(unwrap);

// ── Financial Statements ─────────────────────────────────────────────────────

export const getComputedFinancialStatements = (params: {
  start_date: string;
  end_date: string;
  company?: string;
}) => api.get<ComputedFinancialStatements>('/financial-statements/computed', { params }).then(unwrap);

export const downloadFinancialStatements = () =>
  api.get<Blob>('/financial-statements/download', { responseType: 'blob' }).then(unwrap);

export const downloadComputedFinancialStatements = (params: {
  start_date: string;
  end_date: string;
  company?: string;
}) =>
  api
    .get<Blob>('/financial-statements/computed/download', { params, responseType: 'blob' })
    .then(unwrap);

// ── School Assets ──────────────────────────────────────────────────────────────

export const getAssets = (params?: { as_at?: string }) =>
  api.get<Asset[]>('/assets/', { params }).then(unwrap);

export const getAssetCategories = () =>
  api.get<string[]>('/assets/categories').then(unwrap);

export const getAssetsSummary = (params: { start_date: string; end_date: string }) =>
  api.get<AssetsSummary>('/assets/summary', { params }).then(unwrap);

export const createAsset = (body: AssetCreate) =>
  api.post<Asset>('/assets/', body).then(unwrap);

export const updateAsset = (id: number, body: Partial<AssetCreate>) =>
  api.put<Asset>(`/assets/${id}`, body).then(unwrap);

export const deleteAsset = (id: number) =>
  api.delete<void>(`/assets/${id}`).then(unwrap);

export const login = (email: string, password: string) =>
  api.post<{ access_token: string; token_type: string }>('/auth/login', { email, password }).then(unwrap);

export const register = (email: string, password: string, fullName?: string) =>
  api.post('/auth/register', { email, password, full_name: fullName }).then(unwrap);

export const forgotPassword = (email: string, newPassword: string) =>
  api.post<{ message: string }>('/auth/forgot-password', { email, new_password: newPassword }).then(unwrap);

export const getCurrentUser = () =>
  api.get('/auth/me').then(unwrap);
// ── Staff Directory ───────────────────────────────────────────────────────────
import type { StaffMember, StaffMemberIn, StaffLoan, StaffLoanIn, LoanPayment, LoanPaymentIn, MatchedTransaction, PayrollLine, PayrollLineIn, PayrollEntryOut, SchoolLoan, SchoolLoanIn, SchoolLoanPaymentOut, SchoolLoanPaymentIn } from './types';

export const listStaffMembers = (activeOnly = false) =>
  api.get<StaffMember[]>('/staff-directory/', { params: { active_only: activeOnly } }).then(unwrap);

export const createStaffMember = (body: StaffMemberIn) =>
  api.post<StaffMember>('/staff-directory/', body).then(unwrap);

export const updateStaffMember = (id: number, body: StaffMemberIn) =>
  api.put<StaffMember>(`/staff-directory/${id}`, body).then(unwrap);

export const deleteStaffMember = (id: number) =>
  api.delete<void>(`/staff-directory/${id}`).then(unwrap);

// ── Staff Loans ───────────────────────────────────────────────────────────────

export const listStaffLoans = () =>
  api.get<StaffLoan[]>('/staff-loans/').then(unwrap);

export const createStaffLoan = (body: StaffLoanIn) =>
  api.post<StaffLoan>('/staff-loans/', body).then(unwrap);

export const updateStaffLoan = (id: number, body: StaffLoanIn) =>
  api.put<StaffLoan>(`/staff-loans/${id}`, body).then(unwrap);

export const deleteStaffLoan = (id: number) =>
  api.delete<void>(`/staff-loans/${id}`).then(unwrap);

export const addLoanPayment = (loanId: number, body: LoanPaymentIn) =>
  api.post<LoanPayment>(`/staff-loans/${loanId}/payments`, body).then(unwrap);

export const updateLoanPayment = (loanId: number, paymentId: number, body: LoanPaymentIn) =>
  api.put<LoanPayment>(`/staff-loans/${loanId}/payments/${paymentId}`, body).then(unwrap);

export const deleteLoanPayment = (loanId: number, paymentId: number) =>
  api.delete<void>(`/staff-loans/${loanId}/payments/${paymentId}`).then(unwrap);

export const matchLoanTransactions = (loanId: number, year: number, month: number) =>
  api.get<MatchedTransaction[]>(`/staff-loans/${loanId}/match-transactions`, { params: { year, month } }).then(unwrap);

// ── School Loans (loans the school has borrowed) ───────────────────────────────

export const listSchoolLoans = () =>
  api.get<SchoolLoan[]>('/school-loans/').then(unwrap);

export const createSchoolLoan = (body: SchoolLoanIn) =>
  api.post<SchoolLoan>('/school-loans/', body).then(unwrap);

export const updateSchoolLoan = (id: number, body: SchoolLoanIn) =>
  api.put<SchoolLoan>(`/school-loans/${id}`, body).then(unwrap);

export const deleteSchoolLoan = (id: number) =>
  api.delete<void>(`/school-loans/${id}`).then(unwrap);

export const addSchoolLoanPayment = (loanId: number, body: SchoolLoanPaymentIn) =>
  api.post<SchoolLoanPaymentOut>(`/school-loans/${loanId}/payments`, body).then(unwrap);

export const updateSchoolLoanPayment = (loanId: number, paymentId: number, body: SchoolLoanPaymentIn) =>
  api.put<SchoolLoanPaymentOut>(`/school-loans/${loanId}/payments/${paymentId}`, body).then(unwrap);

export const deleteSchoolLoanPayment = (loanId: number, paymentId: number) =>
  api.delete<void>(`/school-loans/${loanId}/payments/${paymentId}`).then(unwrap);

export const matchSchoolLoanTransactions = (loanId: number, year: number, month: number) =>
  api.get<MatchedTransaction[]>(`/school-loans/${loanId}/match-transactions`, { params: { year, month } }).then(unwrap);

// ── Payroll ───────────────────────────────────────────────────────────────────

export const computePayroll = (year: number, month: number) =>
  api.get<PayrollLine[]>('/payroll/compute', { params: { year, month } }).then(unwrap);

export const processPayroll = (year: number, month: number, lines: PayrollLineIn[]) =>
  api.post<PayrollEntryOut[]>('/payroll/process', { year, month, lines }).then(unwrap);

export const getPayrollEntries = (year: number, month: number) =>
  api.get<PayrollEntryOut[]>('/payroll/entries', { params: { year, month } }).then(unwrap);

export const resetPayroll = (year: number, month: number) =>
  api.post<{ reset: number }>('/payroll/reset', null, { params: { year, month } }).then(unwrap);
