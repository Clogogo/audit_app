import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  CheckCircle, AlertCircle, AlertTriangle, ShieldCheck,
  Trash2, Save, GitMerge, FileSpreadsheet, ScanLine, Upload as UploadIcon, X,
} from 'lucide-react';
import { HelpTooltip } from '../components/HelpTooltip';
import {
  getBankAccounts, uploadBankStatement, getBankTransactions,
  importStatementTransactions, validateBankStatement,
} from '../api/client';
import type {
  BankAccount, BankStatement, StatementImportItem, StatementImportResult,
  ValidationReport,
} from '../api/types';
import { FileUploader } from '../components/FileUploader';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Badge } from '../components/ui/badge';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select';
import axios from 'axios';
import { EXPENSE_CATEGORIES, INCOME_CATEGORIES } from '../api/types';

// ── Types ─────────────────────────────────────────────────────────────────────

/** A single extracted transaction row, editable before import. */
interface EditableRow {
  _key:         number;
  _selected:    boolean;
  _stmtId:      number;                   // bank_transaction.id
  _matched:     boolean;                  // already reconciled
  date:         string;
  description:  string;
  vendor:       string;
  amount:       number | undefined;
  currency:     string;
  category:     string;
  type:         'expense' | 'income' | 'transfer';
  reference?:   string;
}

const ALL_CATEGORIES   = [...new Set([...EXPENSE_CATEGORIES, ...INCOME_CATEGORIES])];
const TRANSFER_CATS    = ['Internal Transfer', 'Bank Charges & Fees', 'Other'];

const TRANSFER_PATTERNS = [
  'auto-save to owealth', 'auto save to owealth', 'owealth withdrawal', 'owealth balance',
  'transfer to own', 'own account transfer', 'internal transfer', 'inter-bank transfer',
  'intrabank transfer', 'transfer to opay', 'transfer to moniepoint',
  'received from moniepoint', 'received from opay',
];

function detectType(desc: string, rawType: 'credit' | 'debit'): 'income' | 'expense' | 'transfer' {
  const d = desc.toLowerCase();
  if (TRANSFER_PATTERNS.some((p) => d.includes(p))) return 'transfer';
  return rawType === 'credit' ? 'income' : 'expense';
}

function formatFileSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

const ACCEPTED_FILE = {
  'text/csv': ['.csv'],
  'application/vnd.ms-excel': ['.xls'],
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
};

function isAcceptedFile(file: File): boolean {
  return /\.(csv|xls|xlsx)$/i.test(file.name) ||
    ['text/csv', 'application/vnd.ms-excel',
     'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'].includes(file.type);
}

// ── Component ─────────────────────────────────────────────────────────────────

export function Upload() {
  const navigate = useNavigate();

  const [stagedFile, setStagedFile]           = useState<File | null>(null);
  const [uploading, setUploading]             = useState(false);
  const [rows, setRows]                       = useState<EditableRow[]>([]);
  const [saving, setSaving]                   = useState(false);
  const [saved, setSaved]                     = useState(false);
  const [uploadError, setUploadError]         = useState<string | null>(null);
  const [bankAccounts, setBankAccounts]       = useState<BankAccount[]>([]);
  const [selectedBank, setSelectedBank]       = useState('');
  const [importResult, setImportResult]       = useState<StatementImportResult | null>(null);
  const [resolutionMode, setResolutionMode]   = useState<'manual' | 'auto'>('manual');
  const [validationReport, setValidationReport] = useState<ValidationReport | null>(null);
  const [validating, setValidating]           = useState(false);
  const stmtRef = useRef<BankStatement | null>(null);
  const keyRef  = useRef(0);

  useEffect(() => {
    getBankAccounts().then(setBankAccounts).catch(() => {});
  }, []);

  const handleFileSelect = (file: File) => {
    if (!isAcceptedFile(file)) {
      setUploadError('Unsupported file. Please upload a CSV or Excel (.csv, .xls, .xlsx) bank statement.');
      return;
    }
    setStagedFile(file);
    setUploadError(null);
  };

  const handleScan = async () => {
    const file = stagedFile;
    if (!file) return;
    setUploading(true);
    setSaved(false);
    setRows([]);
    setUploadError(null);
    setValidationReport(null);
    stmtRef.current = null;

    try {
      const selectedAccount = bankAccounts.find(b => b.bank_name === selectedBank);
      const stmt = await uploadBankStatement(file, selectedBank.trim(), selectedAccount?.account_holder_name);
      stmtRef.current = stmt;
      const txs = await getBankTransactions(stmt.id);
      setRows(
        txs.map((tx) => {
          const apiType   = tx.suggested_type as 'expense' | 'income' | 'transfer' | null ?? null;
          const apiCat    = tx.suggested_category ?? null;
          const frontType = detectType(tx.description, tx.transaction_type);
          const finalType = apiType ?? frontType;
          const finalCat  = apiCat ?? (finalType === 'transfer' ? 'Internal Transfer' : 'Other');
          return {
            _key:      keyRef.current++,
            _selected: tx.match_status !== 'matched',
            _stmtId:   tx.id,
            _matched:  tx.match_status === 'matched',
            date:        tx.date,
            description: tx.description,
            vendor:      '',
            amount:      tx.amount,
            currency:    'NGN',
            category:    finalCat,
            type:        finalType,
            reference:   tx.reference ?? undefined,
          };
        })
      );
      // Run validation automatically — non-blocking, warns only
      setValidating(true);
      validateBankStatement(stmt.id)
        .then(setValidationReport)
        .catch(() => {})
        .finally(() => setValidating(false));
    } catch (err: unknown) {
      const status = axios.isAxiosError(err) ? err.response?.status : null;
      const detail = axios.isAxiosError(err) ? err.response?.data?.detail : null;
      if (status === 422) {
        setUploadError(detail ?? 'No transactions found. Check the file has Date, Description and Amount/Debit/Credit columns.');
      } else {
        setUploadError('Failed to process file. Check the format and try again.');
      }
    } finally {
      setUploading(false);
      setStagedFile(null);
    }
  };

  // ── Row editing ──────────────────────────────────────────────────────────

  const update = (key: number, field: keyof EditableRow, value: string | number) =>
    setRows((prev) => prev.map((r) => (r._key === key ? { ...r, [field]: value } : r)));

  const toggle    = (key: number) =>
    setRows((prev) => prev.map((r) => (r._key === key ? { ...r, _selected: !r._selected } : r)));

  const toggleAll = () => {
    const selectable  = rows.filter((r) => !r._matched);
    const allSelected = selectable.every((r) => r._selected);
    setRows((prev) => prev.map((r) => r._matched ? r : { ...r, _selected: !allSelected }));
  };

  const deleteRow = (key: number) => setRows((prev) => prev.filter((r) => r._key !== key));

  // ── Save ─────────────────────────────────────────────────────────────────

  const handleSave = async () => {
    const selected = rows.filter((r) => r._selected && !r._matched);
    if (!selected.length) { alert('Select at least one row to save.'); return; }

    const invalid = selected.filter((r) => !r.amount || !r.date || !r.category || !r.description);
    if (invalid.length) { alert(`${invalid.length} row(s) missing required fields.`); return; }

    if (!stmtRef.current) { alert('No statement loaded. Upload a file first.'); return; }

    setSaving(true);
    try {
      const items: StatementImportItem[] = selected.map((r) => ({
        bank_transaction_id: r._stmtId,
        amount:      r.amount as number,
        currency:    r.currency,
        category:    r.category,
        description: r.description,
        date:        r.date,
        vendor:      r.vendor || undefined,
        type:        r.type,
      }));
      const res = await importStatementTransactions(stmtRef.current.id, items, undefined, resolutionMode);
      setImportResult(res);
      setSaved(true);
      setRows([]);
    } catch {
      alert('Failed to save transactions. Please try again.');
    } finally {
      setSaving(false);
    }
  };

  const reset = () => {
    setSaved(false); setRows([]); setUploadError(null);
    setStagedFile(null);
    stmtRef.current = null;
    setImportResult(null);
    setValidationReport(null);
    setValidating(false);
  };

  // ── Derived ──────────────────────────────────────────────────────────────

  const selectedCount = rows.filter((r) => r._selected && !r._matched).length;
  const hasRows       = rows.length > 0;

  // ── Success screen ────────────────────────────────────────────────────────

  if (saved) {
    return (
      <div className="min-h-[60vh] flex items-center justify-center">
        <div className="w-full max-w-lg space-y-6 text-center">
          {/* Success icon */}
          <div className="mx-auto flex h-20 w-20 items-center justify-center rounded-full bg-green-100 ring-8 ring-green-50 dark:bg-green-950/40 dark:ring-green-950/20">
            <CheckCircle className="h-10 w-10 text-green-600 dark:text-green-400" />
          </div>

          <div>
            <h2 className="text-2xl font-bold text-foreground">Import Complete!</h2>
            {importResult ? (
              <div className="mt-3 flex flex-wrap justify-center gap-3">
                {importResult.saved > 0 && (
                  <div className="rounded-xl bg-green-50 border border-green-200 dark:bg-green-950/20 dark:border-green-900/50 px-4 py-3 text-center">
                    <p className="text-2xl font-bold text-green-700 dark:text-green-300">{importResult.saved}</p>
                    <p className="text-xs text-green-600 dark:text-green-400 font-medium mt-0.5">Transaction{importResult.saved !== 1 ? 's' : ''} Saved</p>
                  </div>
                )}
                {importResult.reconciled > 0 && (
                  <div className="rounded-xl bg-amber-50 border border-amber-200 dark:bg-amber-950/20 dark:border-amber-900/50 px-4 py-3 text-center">
                    <p className="text-2xl font-bold text-amber-700 dark:text-amber-300">{importResult.reconciled}</p>
                    <p className="text-xs text-amber-600 dark:text-amber-400 font-medium mt-0.5">Reconciled</p>
                  </div>
                )}
                {importResult.duplicates_flagged > 0 && (
                  <div className="rounded-xl bg-yellow-50 border border-yellow-200 dark:bg-yellow-950/20 dark:border-yellow-900/50 px-4 py-3 text-center">
                    <p className="text-2xl font-bold text-yellow-700 dark:text-yellow-300">{importResult.duplicates_flagged}</p>
                    <p className="text-xs text-yellow-600 dark:text-yellow-400 font-medium mt-0.5">Duplicate{importResult.duplicates_flagged !== 1 ? 's' : ''} Flagged</p>
                  </div>
                )}
                {importResult.duplicates_resolved > 0 && (
                  <div className="rounded-xl bg-primary/10 border border-primary/20 px-4 py-3 text-center">
                    <p className="text-2xl font-bold text-primary">{importResult.duplicates_resolved}</p>
                    <p className="text-xs text-primary/80 font-medium mt-0.5">Duplicate{importResult.duplicates_resolved !== 1 ? 's' : ''} Auto-Resolved</p>
                  </div>
                )}
              </div>
            ) : (
              <p className="text-muted-foreground mt-2">Your transactions have been saved successfully.</p>
            )}
          </div>

          <div className="flex flex-col sm:flex-row gap-3 justify-center">
            <Button onClick={() => navigate('/transactions')} className="gap-2">
              View Transactions
            </Button>
            {importResult && importResult.duplicates_flagged > 0 && (
              <Button variant="outline" onClick={() => navigate('/reconciliation')} className="gap-2">
                <GitMerge className="h-4 w-4" /> Review Duplicates
              </Button>
            )}
            <Button variant="ghost" onClick={reset} className="gap-2">
              <UploadIcon className="h-4 w-4" /> Upload Another
            </Button>
          </div>
        </div>
      </div>
    );
  }

  // ── Main page ─────────────────────────────────────────────────────────────

  return (
    <div className="space-y-8 max-w-6xl">

      {/* ── Page header ─────────────────────────────────────────────────── */}
      <div className="relative overflow-hidden rounded-2xl bg-primary p-8 text-primary-foreground shadow-lg">
        {/* Decorative blobs */}
        <div className="pointer-events-none absolute -top-8 -right-8 h-40 w-40 rounded-full bg-white/10 blur-2xl" />
        <div className="pointer-events-none absolute -bottom-6 -left-6 h-32 w-32 rounded-full bg-white/10 blur-2xl" />

        <div className="relative">
          <div className="flex items-center gap-2 mb-2">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-white/20 backdrop-blur">
              <FileSpreadsheet className="h-5 w-5 text-white" />
            </div>
            <h1 className="text-2xl font-bold tracking-tight">Bank Statement Import</h1>
          </div>
          <p className="text-primary-foreground/80 text-sm max-w-lg">
            Upload a CSV or Excel bank statement. Transactions are parsed instantly —
            no AI, no setup, no waiting.
          </p>

          {/* Format chips */}
          <div className="mt-5 flex flex-wrap gap-2">
            {[
              { label: 'CSV',   sub: 'Instant' },
              { label: 'Excel', sub: 'Instant' },
            ].map(({ label, sub }) => (
              <div key={label} className="flex items-center gap-1.5 rounded-full bg-white/20 px-3 py-1.5 text-xs text-white/90 font-medium border border-white/20">
                <FileSpreadsheet className="h-3 w-3 shrink-0" />
                <span>{label}</span>
                <span className="text-white/60">·</span>
                <span className="text-white/70">{sub}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* ── Error banner ─────────────────────────────────────────────────── */}
      {uploadError && (
        <div className="flex items-start gap-3 rounded-xl border border-destructive/20 bg-destructive/5 px-4 py-3.5">
          <AlertCircle className="h-5 w-5 text-destructive shrink-0 mt-0.5" />
          <p className="text-sm text-destructive flex-1">{uploadError}</p>
          <button type="button" onClick={() => setUploadError(null)}
            className="text-destructive/70 hover:text-destructive transition-colors shrink-0"
            title="Close error message" aria-label="Close error message">
            <X className="h-4 w-4" />
          </button>
        </div>
      )}

      {/* ── Upload form ───────────────────────────────────────────────────── */}
      {!hasRows && (
        <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">

          {/* Left: tips panel */}
          <div className="lg:col-span-2 space-y-4">
            <Card className="border-0 bg-muted/40">
              <CardHeader className="pb-3">
                <CardTitle className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">How it works</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4 pt-0">
                {[
                  { step: '01', title: 'Select bank', desc: 'Choose or type your bank name (required).' },
                  { step: '02', title: 'Drop file',   desc: 'Drag & drop or click to browse. CSV or Excel.' },
                  { step: '03', title: 'Scan',        desc: 'Click "Scan Statement" to extract all transactions.' },
                  { step: '04', title: 'Review & save', desc: 'Edit, select rows you want, then save to your ledger.' },
                ].map(({ step, title, desc }) => (
                  <div key={step} className="flex gap-3">
                    <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary text-xs font-bold">{step}</div>
                    <div>
                      <p className="text-sm font-medium">{title}</p>
                      <p className="text-xs text-muted-foreground mt-0.5">{desc}</p>
                    </div>
                  </div>
                ))}
              </CardContent>
            </Card>

            <Card className="border-0 bg-amber-50 border-amber-100 dark:bg-amber-950/20 dark:border-amber-900/50">
              <CardContent className="py-4 px-5">
                <p className="text-xs font-semibold text-amber-700 dark:text-amber-300 uppercase tracking-wide mb-1.5">Tips</p>
                <ul className="text-xs text-amber-800 dark:text-amber-200/90 space-y-1.5 list-disc list-inside">
                  <li>Bank account selection is <strong>required</strong> before scanning</li>
                  <li>File needs <strong>Date</strong>, <strong>Description</strong> and <strong>Amount</strong> (or Debit/Credit) columns</li>
                  <li>You can edit any field before saving</li>
                  <li>Duplicate transactions are automatically flagged</li>
                </ul>
              </CardContent>
            </Card>
          </div>

          {/* Right: upload form */}
          <div className="lg:col-span-3">
            <Card className="shadow-sm">
              <CardHeader className="pb-4">
                <CardTitle className="text-base">
                  Select Bank &amp; Upload File
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-5">

                {/* Bank selector */}
                <div className="space-y-1.5">
                  <label className="text-sm font-medium flex items-center gap-1.5">
                    Bank Account
                    <span className="text-xs text-red-500 font-normal">*</span>
                  </label>
                  {bankAccounts.length > 0 ? (
                    <Select value={selectedBank || '__none__'} onValueChange={(v) => setSelectedBank(v === '__none__' ? '' : v)}>
                      <SelectTrigger>
                        <SelectValue placeholder="Select a bank account…" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="__none__">No bank selected</SelectItem>
                        {bankAccounts.map((b) => (
                          <SelectItem key={b.id} value={b.bank_name}>
                            {b.bank_name}{b.account_number ? ` — ${b.account_number}` : ''}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  ) : (
                    <Input
                      placeholder="e.g. Access Bank, GTBank…"
                      value={selectedBank}
                      onChange={(e) => setSelectedBank(e.target.value)}
                    />
                  )}
                </div>

                {/* Drop zone */}
                {!stagedFile && !uploading && (
                  <FileUploader
                    onFileSelect={handleFileSelect}
                    isLoading={uploading}
                    accept={ACCEPTED_FILE}
                    label="Drop bank statement here — CSV or Excel"
                    hint="or click to browse — .csv, .xls, .xlsx"
                  />
                )}

                {/* Staged file - ready to scan */}
                {stagedFile && !uploading && (
                  <div className="space-y-3">
                    {/* File preview */}
                    <div className="rounded-lg border bg-muted/30 p-3 flex items-center gap-3">
                      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary/10">
                        <FileSpreadsheet className="h-5 w-5 text-primary" />
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium truncate">{stagedFile.name}</p>
                        <p className="text-xs text-muted-foreground">{formatFileSize(stagedFile.size)}</p>
                      </div>
                      <button
                        type="button"
                        onClick={() => setStagedFile(null)}
                        className="shrink-0 rounded-md p-1.5 text-muted-foreground hover:text-foreground hover:bg-background transition-colors"
                        aria-label="Remove file"
                      >
                        <X className="h-4 w-4" />
                      </button>
                    </div>

                    {/* Scan button */}
                    <Button
                      type="button"
                      onClick={handleScan}
                      disabled={!selectedBank.trim()}
                      size="lg"
                      className="w-full gap-2 bg-primary hover:bg-primary/90"
                    >
                      <ScanLine className="h-5 w-5" />
                      <span>Scan Statement</span>
                    </Button>
                  </div>
                )}

                {/* Processing state */}
                {uploading && (
                  <div className="rounded-lg border bg-muted/30 p-6 text-center space-y-3">
                    <div className="flex justify-center">
                      <span className="h-8 w-8 animate-spin rounded-full border-3 border-primary border-t-transparent" />
                    </div>
                    <div>
                      <p className="text-sm font-medium">Parsing statement…</p>
                      <p className="text-xs text-muted-foreground mt-1">Extracting transactions</p>
                    </div>
                  </div>
                )}

              </CardContent>
            </Card>
          </div>
        </div>
      )}

      {/* ── Results table ─────────────────────────────────────────────────── */}
      {hasRows && (
        <div className="space-y-4">
          <div className="flex items-center justify-between gap-3 flex-wrap">
            <div>
              <h2 className="text-lg font-semibold flex items-center gap-2">
                <FileSpreadsheet className="h-4 w-4 text-primary" />
                Extracted Transactions
                <Badge variant="secondary" className="font-normal">{rows.length} row{rows.length !== 1 ? 's' : ''}</Badge>
              </h2>
              <p className="text-sm text-muted-foreground mt-0.5">Review and edit, then save selected rows.</p>
            </div>
            <Button variant="outline" size="sm" onClick={reset} className="gap-1.5 shrink-0">
              <UploadIcon className="h-3.5 w-3.5" /> Upload Different File
            </Button>
          </div>

          {/* ── Validation panel ─────────────────────────────────────────── */}
          {(validating || validationReport) && (
            <div className={`rounded-xl border px-4 py-3 space-y-2.5 ${
              validationReport
                ? validationReport.error_count > 0
                  ? 'border-red-200 bg-red-50/60 dark:border-red-900/50 dark:bg-red-950/20'
                  : validationReport.warning_count > 0
                    ? 'border-amber-200 bg-amber-50/60 dark:border-amber-900/50 dark:bg-amber-950/20'
                    : 'border-green-200 bg-green-50/60 dark:border-green-900/50 dark:bg-green-950/20'
                : 'border-muted bg-muted/30'
            }`}>
              <div className="flex items-center gap-2">
                {validating && !validationReport
                  ? <span className="h-4 w-4 animate-spin rounded-full border-2 border-primary border-t-transparent shrink-0" />
                  : <ShieldCheck className={`h-4 w-4 shrink-0 ${
                      validationReport?.error_count ? 'text-red-500' :
                      validationReport?.warning_count ? 'text-amber-500' : 'text-green-500'
                    }`} />
                }
                <span className="text-sm font-semibold flex items-center gap-1.5">
                  {validating && !validationReport ? 'Running validation…' : 'Validation Report'}
                  {!validating && validationReport && (
                    <HelpTooltip
                      content={"Validation runs 5 checks before import:\n\n· Date format — are all dates valid?\n· Missing amounts — any rows without a value?\n· Zero amounts — transactions with ₦0 (usually errors)\n· Duplicate check — do any rows match existing transactions?\n· Future dates — dates beyond today (likely typos)\n\nErrors block import. Warnings are advisory — you can still import."}
                      align="left"
                    />
                  )}
                </span>
                {validationReport && (
                  <div className="ml-auto flex gap-1.5">
                    {validationReport.error_count > 0 && (
                      <span className="inline-flex items-center rounded-full bg-red-100 text-red-700 border border-red-200 dark:bg-red-950/40 dark:text-red-300 dark:border-red-900/50 text-xs px-2 py-0.5 font-medium">
                        {validationReport.error_count} error{validationReport.error_count !== 1 ? 's' : ''}
                      </span>
                    )}
                    {validationReport.warning_count > 0 && (
                      <span className="inline-flex items-center rounded-full bg-amber-100 text-amber-700 border border-amber-200 dark:bg-amber-950/40 dark:text-amber-300 dark:border-amber-900/50 text-xs px-2 py-0.5 font-medium">
                        {validationReport.warning_count} warning{validationReport.warning_count !== 1 ? 's' : ''}
                      </span>
                    )}
                    {validationReport.error_count === 0 && validationReport.warning_count === 0 && (
                      <span className="inline-flex items-center rounded-full bg-green-100 text-green-700 border border-green-200 dark:bg-green-950/40 dark:text-green-300 dark:border-green-900/50 text-xs px-2 py-0.5 font-medium">
                        All clear
                      </span>
                    )}
                  </div>
                )}
              </div>

              {validationReport && (
                <div className="space-y-1.5">
                  {validationReport.checks.map((check, i) => (
                    <div key={i} className="flex items-start gap-2 text-sm">
                      {check.status === 'pass'
                        ? <CheckCircle className="h-4 w-4 text-green-500 mt-0.5 shrink-0" />
                        : check.status === 'warn'
                          ? <AlertTriangle className="h-4 w-4 text-amber-500 mt-0.5 shrink-0" />
                          : <AlertCircle className="h-4 w-4 text-red-500 mt-0.5 shrink-0" />
                      }
                      <div className="flex-1 min-w-0">
                        <span className={`font-medium ${
                          check.status === 'pass' ? 'text-green-700 dark:text-green-300' :
                          check.status === 'warn' ? 'text-amber-700 dark:text-amber-300' : 'text-red-700 dark:text-red-300'
                        }`}>{check.name}</span>
                        <span className={`ml-1.5 text-xs ${
                          check.status === 'pass' ? 'text-green-600 dark:text-green-400/90' :
                          check.status === 'warn' ? 'text-amber-600 dark:text-amber-400/90' : 'text-red-600 dark:text-red-400/90'
                        }`}>— {check.message}</span>
                      </div>
                      {check.count > 0 && (
                        <span className={`shrink-0 inline-flex items-center rounded-full border text-xs px-2 py-0.5 font-medium ${
                          check.status === 'warn'
                            ? 'bg-amber-50 text-amber-700 border-amber-300 dark:bg-amber-950/40 dark:text-amber-300 dark:border-amber-800'
                            : 'bg-red-50 text-red-700 border-red-300 dark:bg-red-950/40 dark:text-red-300 dark:border-red-800'
                        }`}>
                          {check.count} affected
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              )}

              {validationReport && !validationReport.can_import && (
                <p className="text-xs text-red-600 dark:text-red-400 font-medium mt-1">
                  Resolve the errors above before importing. Warnings can be reviewed but won't block import.
                </p>
              )}
            </div>
          )}

          <Card className="shadow-sm overflow-hidden">
            <CardContent className="p-0">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b bg-muted/50">
                      <th className="p-2.5 w-8">
                        <input type="checkbox" aria-label="Select all"
                          checked={rows.filter((r) => !r._matched).every((r) => r._selected)}
                          onChange={toggleAll} className="rounded" />
                      </th>
                      <th className="p-2.5 text-left font-medium text-muted-foreground text-xs uppercase tracking-wide">Date</th>
                      <th className="p-2.5 text-left font-medium text-muted-foreground text-xs uppercase tracking-wide">Description</th>
                      <th className="p-2.5 text-left font-medium text-muted-foreground text-xs uppercase tracking-wide">Vendor</th>
                      <th className="p-2.5 text-left font-medium text-muted-foreground text-xs uppercase tracking-wide">Amount</th>
                      <th className="p-2.5 text-left font-medium text-muted-foreground text-xs uppercase tracking-wide">Category</th>
                      <th className="p-2.5 text-left font-medium text-muted-foreground text-xs uppercase tracking-wide">
                        <span className="flex items-center gap-1">
                          Type
                          <HelpTooltip
                            content={"Income — money received (fees, sales, grants)\nExpense — money paid out (salaries, utilities, supplies)\nTransfer — movement between your own accounts (GTBank → Access Bank)\n\nTransfers are excluded from income/expense totals so they don't inflate your figures."}
                            align="right"
                          />
                        </span>
                      </th>
                      <th className="p-2.5 w-8"><span className="sr-only">Delete</span></th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((row) => {
                      const locked = !!row._matched;
                      return (
                        <tr key={row._key} className={`border-b last:border-0 transition-colors ${
                          locked
                            ? 'bg-green-50/60 dark:bg-green-950/20 opacity-70'
                            : row._selected
                              ? 'bg-card hover:bg-primary/5'
                              : 'bg-muted/20 opacity-50'
                        }`}>
                          <td className="p-2.5 text-center">
                            {locked
                              ? <span title="Already reconciled" className="text-green-600 dark:text-green-400 text-xs font-bold">✓</span>
                              : <input type="checkbox" aria-label="Select row" checked={row._selected} onChange={() => toggle(row._key)} className="rounded" />}
                          </td>
                          <td className="p-1.5">
                            {locked
                              ? <span className="text-xs text-muted-foreground px-1.5">{row.date}</span>
                              : <Input type="date" value={row.date} onChange={(e) => update(row._key, 'date', e.target.value)} className="h-7 text-xs px-1.5 min-w-[110px]" />}
                          </td>
                          <td className="p-1.5">
                            <Input value={row.description} onChange={(e) => update(row._key, 'description', e.target.value)}
                              placeholder="Description" className="h-7 text-xs px-1.5 min-w-[140px]" disabled={locked} />
                          </td>
                          <td className="p-1.5">
                            <Input value={row.vendor} onChange={(e) => update(row._key, 'vendor', e.target.value)}
                              placeholder="Vendor" className="h-7 text-xs px-1.5 min-w-[100px]" disabled={locked} />
                          </td>
                          <td className="p-1.5">
                            {locked
                              ? <span className="text-xs font-semibold px-1.5">₦{row.amount?.toLocaleString('en-NG', { minimumFractionDigits: 2 })}</span>
                              : <Input type="number" value={row.amount ?? ''} onChange={(e) => update(row._key, 'amount', parseFloat(e.target.value))}
                                  placeholder="0.00" className="h-7 text-xs px-1.5 w-24" />}
                          </td>
                          <td className="p-1.5">
                            {locked
                              ? <Badge variant="outline" className="text-green-600 border-green-300 dark:text-green-400 dark:border-green-800 text-xs">reconciled</Badge>
                              : (
                              <select title="Category" value={row.category}
                                onChange={(e) => update(row._key, 'category', e.target.value)}
                                className="h-7 text-xs px-1.5 rounded-md border border-input bg-background w-28 focus:outline-none focus:ring-1 focus:ring-primary">
                                <option value="">Pick…</option>
                                {(row.type === 'transfer' ? TRANSFER_CATS : ALL_CATEGORIES).map((c) => (
                                  <option key={c} value={c}>{c}</option>
                                ))}
                              </select>
                            )}
                          </td>
                          <td className="p-1.5">
                            {!locked && (
                              <select title="Type" value={row.type}
                                onChange={(e) => {
                                  const t = e.target.value as EditableRow['type'];
                                  update(row._key, 'type', t);
                                  if (t === 'transfer') update(row._key, 'category', 'Internal Transfer');
                                  else if (row.type === 'transfer') update(row._key, 'category', 'Other');
                                }}
                                className="h-7 text-xs px-1.5 rounded-md border border-input bg-background w-24 focus:outline-none focus:ring-1 focus:ring-primary">
                                <option value="expense">Expense</option>
                                <option value="income">Income</option>
                                <option value="transfer">Transfer</option>
                              </select>
                            )}
                          </td>
                          <td className="p-1.5 text-center">
                            {!locked && (
                              <button type="button" aria-label="Delete row" onClick={() => deleteRow(row._key)}
                                className="rounded-md p-1 text-muted-foreground hover:text-destructive hover:bg-destructive/10 transition-colors">
                                <Trash2 className="h-3.5 w-3.5" />
                              </button>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              {rows.length === 0 && (
                <div className="flex flex-col items-center justify-center py-12 text-center">
                  <FileSpreadsheet className="h-8 w-8 text-muted-foreground/40 mb-2" />
                  <p className="text-sm text-muted-foreground">No rows — upload a new file.</p>
                </div>
              )}
            </CardContent>
          </Card>

          {/* Action bar */}
          <div className="flex items-center gap-3 rounded-xl border bg-muted/30 px-4 py-3 flex-wrap">
            {/* Duplicate Resolution Mode Selector */}
            <div className="flex items-center gap-2">
              <span className="text-xs text-muted-foreground font-medium flex items-center gap-1">
                Duplicates:
                <HelpTooltip
                  content={"How to handle transactions that already exist in your ledger:\n\n· Manual Review — flag them as potential duplicates and let you decide in the Reconciliation page. Safest option.\n\n· Auto Resolve — automatically keep the most recent version and discard the older one. Faster, but irreversible.\n\nIf you're re-uploading the same statement, use Auto Resolve. If you're not sure, use Manual Review."}
                  align="left"
                />
              </span>
              <Select value={resolutionMode} onValueChange={(v: 'manual' | 'auto') => setResolutionMode(v)}>
                <SelectTrigger className="h-8 w-[140px] text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="manual">
                    <div className="flex flex-col items-start py-0.5">
                      <span className="font-medium">Manual Review</span>
                      <span className="text-xs text-muted-foreground">Flag for review</span>
                    </div>
                  </SelectItem>
                  <SelectItem value="auto">
                    <div className="flex flex-col items-start py-0.5">
                      <span className="font-medium">Auto Resolve</span>
                      <span className="text-xs text-muted-foreground">Keep most recent</span>
                    </div>
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>

            <span className="text-sm text-muted-foreground ml-auto">
              <strong className="text-foreground">{selectedCount}</strong> row{selectedCount !== 1 ? 's' : ''} selected
            </span>
            <Button
              onClick={handleSave}
              disabled={saving || selectedCount === 0}
              className="gap-2 bg-primary hover:bg-primary/90 text-primary-foreground shadow-sm"
            >
              <Save className="h-4 w-4" />
              {saving ? 'Saving…' : `Save ${selectedCount} Transaction${selectedCount !== 1 ? 's' : ''}`}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
