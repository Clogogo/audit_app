import axios, { type AxiosResponse } from 'axios';
import type {
  Transaction,
  TransactionCreate,
  TransactionSummary,
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

const unwrap = <T>(r: AxiosResponse<T>) => r.data;

// Transactions
export const getTransactions = (params?: {
  type?: string;
  category?: string;
  start_date?: string;
  end_date?: string;
}) => api.get<Transaction[]>('/transactions', { params }).then(unwrap);

export const getSummary = (params?: { start_date?: string; end_date?: string }) =>
  api.get<TransactionSummary>('/transactions/summary', { params }).then(unwrap);

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
export const uploadBankStatement = (file: File, bankName: string) => {
  const form = new FormData();
  form.append('file', file);
  form.append('bank_name', bankName);
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

export const importStatementTransactions = (stmtId: number, items: StatementImportItem[]) =>
  api.post<StatementImportResult>(`/bank-statements/${stmtId}/import-transactions`, { items }).then(unwrap);

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

export const saveUnmatchedTransactions = (statementId: number) =>
  api.post<StatementImportResult>(`/reconcile/${statementId}/save-unmatched`).then(unwrap);

export const exportReconciliation = (statementId: number, format: 'csv' | 'pdf') =>
  api
    .get<Blob>(`/reconcile/${statementId}/export`, {
      params: { format },
      responseType: 'blob',
    })
    .then(unwrap);

// Bank Accounts
export const getBankAccounts = () =>
  api.get<BankAccount[]>('/bank-accounts').then(unwrap);

export const createBankAccount = (body: BankAccountCreate) =>
  api.post<BankAccount>('/bank-accounts', body).then(unwrap);

export const deleteBankAccount = (id: number) =>
  api.delete<void>(`/bank-accounts/${id}`).then(unwrap);

// Reports
export const exportReport = (
  format: 'csv' | 'pdf',
  params?: { start_date?: string; end_date?: string },
) =>
  api
    .get<Blob>('/reports/export', { params: { format, ...params }, responseType: 'blob' })
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
