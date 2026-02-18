import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  CheckCircle, Sparkles, Zap, AlertCircle, Trash2, Plus, Save, GitMerge,
  FileSpreadsheet, ScanLine, Upload as UploadIcon, FileText, Image, X,
} from 'lucide-react';
import {
  uploadBatch, confirmBatch, getFilePreviewUrl, getBankAccounts,
  uploadBankStatement, getBankTransactions, importStatementTransactions,
} from '../api/client';
import type {
  BatchConfirmItem, BatchUploadResult, BankAccount,
  BankStatement, StatementImportItem, StatementImportResult,
} from '../api/types';
import { FileUploader } from '../components/FileUploader';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Badge } from '../components/ui/badge';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select';
import axios from 'axios';
import { EXPENSE_CATEGORIES, INCOME_CATEGORIES } from '../api/types';

// ── Types ─────────────────────────────────────────────────────────────────────

interface AIStatus { provider: string; model: string; configured: boolean; }

/** Unified row used for both AI extraction and CSV/Excel import */
interface EditableRow {
  _key:         number;
  _selected:    boolean;
  _path:        'ai' | 'statement';      // which backend path produced this row
  _stmtId?:     number;                  // bank_transaction.id (statement path only)
  _matched?:    boolean;                 // already reconciled (statement path only)
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

function getFileIcon(name: string) {
  if (/\.(pdf)$/i.test(name)) return FileText;
  if (/\.(png|jpg|jpeg|webp)$/i.test(name)) return Image;
  return FileSpreadsheet;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function Upload() {
  const navigate = useNavigate();

  const [stagedFile, setStagedFile]           = useState<File | null>(null);
  const [uploading, setUploading]             = useState(false);
  const [rows, setRows]                       = useState<EditableRow[]>([]);
  const [saving, setSaving]                   = useState(false);
  const [saved, setSaved]                     = useState(false);
  const [aiStatus, setAiStatus]               = useState<AIStatus | null>(null);
  const [uploadError, setUploadError]         = useState<string | null>(null);
  const [bankAccounts, setBankAccounts]       = useState<BankAccount[]>([]);
  const [selectedBank, setSelectedBank]       = useState('');
  const [importResult, setImportResult]       = useState<StatementImportResult | null>(null);
  const aiBatchRef   = useRef<BatchUploadResult | null>(null);
  const stmtRef      = useRef<BankStatement | null>(null);
  const previewUrlRef = useRef<string | null>(null);
  const isPdfRef      = useRef(false);
  const keyRef        = useRef(0);

  useEffect(() => {
    axios.get('/api/health').then((r) => setAiStatus(r.data.ai)).catch(() => null);
    getBankAccounts().then(setBankAccounts).catch(() => {});
  }, []);

  const aiReady = aiStatus?.configured;

  const isStructured = (file: File) =>
    /\.(csv|xls|xlsx)$/i.test(file.name) ||
    ['text/csv', 'application/vnd.ms-excel',
     'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'].includes(file.type);

  const handleFileSelect = (file: File) => {
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
    aiBatchRef.current = null;
    stmtRef.current    = null;

    try {
      if (isStructured(file)) {
        if (!selectedBank.trim()) {
          setUploadError('Enter a bank name before uploading a CSV or Excel file.');
          return;
        }
        const stmt = await uploadBankStatement(file, selectedBank.trim());
        stmtRef.current = stmt;
        const txs = await getBankTransactions(stmt.id);
        setRows(
          txs.map((tx) => {
            const apiType     = tx.suggested_type as 'expense' | 'income' | 'transfer' | null ?? null;
            const apiCat      = tx.suggested_category ?? null;
            const frontType   = detectType(tx.description, tx.transaction_type);
            const finalType   = apiType ?? frontType;
            const finalCat    = apiCat ?? (finalType === 'transfer' ? 'Internal Transfer' : 'Other');
            return {
              _key:      keyRef.current++,
              _selected: tx.match_status !== 'matched',
              _path:     'statement',
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
      } else {
        const res = await uploadBatch(file);
        aiBatchRef.current       = res;
        previewUrlRef.current    = getFilePreviewUrl(res.file_id);
        isPdfRef.current         = res.mime_type?.includes('pdf') ?? false;
        setRows(
          res.items.map((item) => ({
            _key:      keyRef.current++,
            _selected: true,
            _path:     'ai',
            date:        item.date ?? '',
            description: item.description ?? '',
            vendor:      item.vendor ?? selectedBank,
            amount:      item.amount,
            currency:    item.currency ?? 'NGN',
            category:    item.category ?? '',
            type:        (item.type as 'expense' | 'income') ?? 'expense',
            reference:   item.reference ?? undefined,
          }))
        );
      }
    } catch (err: unknown) {
      const status = axios.isAxiosError(err) ? err.response?.status : null;
      const detail = axios.isAxiosError(err) ? err.response?.data?.detail : null;
      if (status === 429) {
        setUploadError(detail ?? 'Rate limit reached. Please wait and retry.');
      } else if (status === 503) {
        setUploadError('AI not available. Check your OPENROUTER_API_KEY.');
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

  const addRow = () => {
    const today = new Date().toISOString().split('T')[0];
    setRows((prev) => [...prev, {
      _key: keyRef.current++, _selected: true, _path: 'ai',
      date: today, description: '', vendor: selectedBank, amount: undefined,
      currency: 'NGN', category: '', type: 'expense',
    }]);
  };

  // ── Save ─────────────────────────────────────────────────────────────────

  const handleSave = async () => {
    const selected = rows.filter((r) => r._selected && !r._matched);
    if (!selected.length) { alert('Select at least one row to save.'); return; }

    const invalid = selected.filter((r) => !r.amount || !r.date || !r.category || !r.description);
    if (invalid.length) { alert(`${invalid.length} row(s) missing required fields.`); return; }

    setSaving(true);
    try {
      if (stmtRef.current) {
        const items: StatementImportItem[] = selected.map((r) => ({
          bank_transaction_id: r._stmtId!,
          amount:      r.amount as number,
          currency:    r.currency,
          category:    r.category,
          description: r.description,
          date:        r.date,
          vendor:      r.vendor || undefined,
          type:        r.type,
        }));
        const res = await importStatementTransactions(stmtRef.current.id, items);
        setImportResult(res);
      } else if (aiBatchRef.current) {
        const items: BatchConfirmItem[] = selected.map((r) => ({
          amount:      r.amount as number,
          currency:    r.currency,
          category:    r.category,
          description: r.description,
          date:        r.date,
          vendor:      r.vendor || undefined,
          type:        r.type as 'expense' | 'income',
          file_id:     aiBatchRef.current!.file_id,
        }));
        await confirmBatch(aiBatchRef.current.file_id, items);
      }
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
    aiBatchRef.current = null; stmtRef.current = null;
    setImportResult(null);
  };

  // ── Derived ──────────────────────────────────────────────────────────────

  const selectedCount = rows.filter((r) => r._selected && !r._matched).length;
  const hasRows       = rows.length > 0;
  const isAiPath      = aiBatchRef.current !== null;
  const previewUrl    = previewUrlRef.current;
  const isPdf         = isPdfRef.current;

  // ── Success screen ────────────────────────────────────────────────────────

  if (saved) {
    return (
      <div className="min-h-[60vh] flex items-center justify-center">
        <div className="w-full max-w-lg space-y-6 text-center">
          {/* Success icon */}
          <div className="mx-auto flex h-20 w-20 items-center justify-center rounded-full bg-green-100 ring-8 ring-green-50">
            <CheckCircle className="h-10 w-10 text-green-600" />
          </div>

          <div>
            <h2 className="text-2xl font-bold text-foreground">Import Complete!</h2>
            {importResult ? (
              <div className="mt-3 flex flex-wrap justify-center gap-3">
                {importResult.saved > 0 && (
                  <div className="rounded-xl bg-green-50 border border-green-200 px-4 py-3 text-center">
                    <p className="text-2xl font-bold text-green-700">{importResult.saved}</p>
                    <p className="text-xs text-green-600 font-medium mt-0.5">Transaction{importResult.saved !== 1 ? 's' : ''} Saved</p>
                  </div>
                )}
                {importResult.reconciled > 0 && (
                  <div className="rounded-xl bg-amber-50 border border-amber-200 px-4 py-3 text-center">
                    <p className="text-2xl font-bold text-amber-700">{importResult.reconciled}</p>
                    <p className="text-xs text-amber-600 font-medium mt-0.5">Duplicate{importResult.reconciled !== 1 ? 's' : ''} Flagged</p>
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
            {importResult && importResult.reconciled > 0 && (
              <Button variant="outline" onClick={() => navigate('/reconciliation')} className="gap-2">
                <GitMerge className="h-4 w-4" /> Review Reconciliation
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
      <div className="relative overflow-hidden rounded-2xl bg-gradient-to-br from-blue-600 via-indigo-600 to-violet-700 p-8 text-white shadow-lg">
        {/* Decorative blobs */}
        <div className="pointer-events-none absolute -top-8 -right-8 h-40 w-40 rounded-full bg-white/10 blur-2xl" />
        <div className="pointer-events-none absolute -bottom-6 -left-6 h-32 w-32 rounded-full bg-white/10 blur-2xl" />

        <div className="relative flex items-start justify-between gap-4 flex-wrap">
          <div>
            <div className="flex items-center gap-2 mb-2">
              <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-white/20 backdrop-blur">
                <Sparkles className="h-5 w-5 text-white" />
              </div>
              <h1 className="text-2xl font-bold tracking-tight">AI Document Import</h1>
            </div>
            <p className="text-blue-100 text-sm max-w-lg">
              Upload a bank statement or receipt. PDF &amp; images are analysed by Qwen AI;
              CSV &amp; Excel files are parsed instantly — no AI required.
            </p>
          </div>

          {/* AI status pill */}
          {aiStatus && (
            <div className={`flex items-center gap-2 rounded-full px-3.5 py-1.5 text-xs font-semibold backdrop-blur border ${
              aiReady
                ? 'border-white/30 bg-white/20 text-white'
                : 'border-red-300/40 bg-red-500/30 text-red-100'
            }`}>
              {aiReady
                ? <><Zap className="h-3.5 w-3.5" />{aiStatus.model} ready</>
                : <><AlertCircle className="h-3.5 w-3.5" />API key not set</>}
            </div>
          )}
        </div>

        {/* Format chips */}
        <div className="relative mt-5 flex flex-wrap gap-2">
          {[
            { icon: FileText,        label: 'PDF',   sub: 'Qwen AI',      color: 'bg-white/20' },
            { icon: Image,           label: 'Image', sub: 'Qwen AI',      color: 'bg-white/20' },
            { icon: FileSpreadsheet, label: 'CSV',   sub: 'Instant',      color: 'bg-white/20' },
            { icon: FileSpreadsheet, label: 'Excel', sub: 'Instant',      color: 'bg-white/20' },
          ].map(({ icon: Icon, label, sub, color }) => (
            <div key={label} className={`flex items-center gap-1.5 rounded-full ${color} px-3 py-1.5 text-xs text-white/90 font-medium border border-white/20`}>
              <Icon className="h-3 w-3 shrink-0" />
              <span>{label}</span>
              <span className="text-white/60">·</span>
              <span className="text-white/70">{sub}</span>
            </div>
          ))}
        </div>
      </div>

      {/* ── Error banner ─────────────────────────────────────────────────── */}
      {uploadError && (
        <div className="flex items-start gap-3 rounded-xl border border-red-200 bg-red-50 px-4 py-3.5">
          <AlertCircle className="h-5 w-5 text-red-500 shrink-0 mt-0.5" />
          <p className="text-sm text-red-700 flex-1">{uploadError}</p>
          <button type="button" onClick={() => setUploadError(null)}
            className="text-red-400 hover:text-red-600 transition-colors shrink-0">
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
                  { step: '01', title: 'Select bank', desc: 'Choose or type your bank name. Required for CSV/Excel.' },
                  { step: '02', title: 'Drop file',   desc: 'Drag & drop or click to browse. Accepts PDF, image, CSV, Excel.' },
                  { step: '03', title: 'Scan',        desc: 'Click "Scan Document" to extract all transactions.' },
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

            <Card className="border-0 bg-amber-50 border-amber-100">
              <CardContent className="py-4 px-5">
                <p className="text-xs font-semibold text-amber-700 uppercase tracking-wide mb-1.5">Tips</p>
                <ul className="text-xs text-amber-800 space-y-1.5 list-disc list-inside">
                  <li>Bank name is <strong>required</strong> for CSV / Excel files</li>
                  <li>Clear, high-resolution images improve AI accuracy</li>
                  <li>You can edit any field before saving</li>
                  <li>Duplicate transactions are flagged for reconciliation</li>
                </ul>
              </CardContent>
            </Card>
          </div>

          {/* Right: upload form */}
          <div className="lg:col-span-3">
            <Card className="shadow-sm">
              <CardHeader className="pb-4">
                <CardTitle className="flex items-center gap-2 text-base">
                  <UploadIcon className="h-4 w-4 text-primary" />
                  Upload Bank Statement
                </CardTitle>
                <CardDescription>
                  Drag &amp; drop your file or click to browse
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-5">

                {/* Bank selector */}
                <div className="space-y-1.5">
                  <label className="text-sm font-medium flex items-center gap-1.5">
                    Bank Account
                    <span className="text-xs text-muted-foreground font-normal">(required for CSV / Excel)</span>
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
                <FileUploader
                  onFileSelect={handleFileSelect}
                  isLoading={uploading}
                  accept={{
                    'application/pdf':   ['.pdf'],
                    'image/png':         ['.png'],
                    'image/jpeg':        ['.jpg', '.jpeg'],
                    'image/webp':        ['.webp'],
                    'text/csv':          ['.csv'],
                    'application/vnd.ms-excel': ['.xls'],
                    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
                  }}
                  label="Drop bank statement here — PDF, image, CSV, or Excel"
                />

                {/* Staged file card */}
                {stagedFile && (() => {
                  const FileIcon = getFileIcon(stagedFile.name);
                  return (
                    <div className="rounded-xl border border-primary/30 bg-gradient-to-br from-primary/5 to-indigo-50/50 p-4 space-y-4">
                      {/* File info row */}
                      <div className="flex items-center gap-3">
                        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary/10">
                          <FileIcon className="h-5 w-5 text-primary" />
                        </div>
                        <div className="flex-1 min-w-0">
                          <p className="text-sm font-semibold text-foreground truncate">{stagedFile.name}</p>
                          <p className="text-xs text-muted-foreground mt-0.5">{formatFileSize(stagedFile.size)}</p>
                        </div>
                        <button
                          type="button"
                          onClick={() => setStagedFile(null)}
                          className="shrink-0 rounded-lg p-1.5 text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
                          aria-label="Remove file"
                          title="Remove file"
                        >
                          <X className="h-4 w-4" />
                        </button>
                      </div>

                      {/* Divider */}
                      <div className="h-px bg-primary/10" />

                      {/* Scan button */}
                      <Button
                        type="button"
                        onClick={handleScan}
                        disabled={uploading}
                        size="lg"
                        className="w-full gap-2.5 bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-700 hover:to-indigo-700 text-white font-semibold shadow-md hover:shadow-lg transition-all duration-200 active:scale-[0.98] disabled:opacity-60 disabled:cursor-not-allowed rounded-lg"
                      >
                        {uploading ? (
                          <>
                            <span className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent shrink-0" />
                            <span>Processing document…</span>
                          </>
                        ) : (
                          <>
                            <ScanLine className="h-5 w-5 shrink-0" />
                            <span>Scan Document</span>
                          </>
                        )}
                      </Button>

                      {uploading && (
                        <p className="text-center text-xs text-muted-foreground animate-pulse">
                          Extracting transactions — this may take a moment
                        </p>
                      )}
                    </div>
                  );
                })()}

              </CardContent>
            </Card>
          </div>
        </div>
      )}

      {/* ── Results table ─────────────────────────────────────────────────── */}
      {hasRows && (
        <div className={isAiPath && previewUrl ? 'grid grid-cols-1 lg:grid-cols-2 gap-6 items-start' : 'space-y-4'}>

          {/* Document preview (AI path only) */}
          {isAiPath && previewUrl && (
            <Card className="sticky top-6 shadow-sm overflow-hidden">
              <CardHeader className="pb-3 border-b">
                <CardTitle className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Document Preview</CardTitle>
              </CardHeader>
              <CardContent className="p-0">
                {isPdf
                  ? <iframe src={previewUrl} className="w-full h-[520px] border-0" title="Document preview" />
                  : <img src={previewUrl} alt="Document preview" className="w-full object-contain max-h-[520px]" />}
              </CardContent>
            </Card>
          )}

          {/* Extracted rows */}
          <div className="space-y-4">
            <div className="flex items-center justify-between gap-3 flex-wrap">
              <div>
                <h2 className="text-lg font-semibold flex items-center gap-2">
                  {isAiPath ? <Sparkles className="h-4 w-4 text-primary" /> : <FileSpreadsheet className="h-4 w-4 text-primary" />}
                  Extracted Transactions
                  <Badge variant="secondary" className="font-normal">{rows.length} row{rows.length !== 1 ? 's' : ''}</Badge>
                </h2>
                <p className="text-sm text-muted-foreground mt-0.5">Review and edit, then save selected rows.</p>
              </div>
              <Button variant="outline" size="sm" onClick={reset} className="gap-1.5 shrink-0">
                <UploadIcon className="h-3.5 w-3.5" /> Upload Different File
              </Button>
            </div>

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
                        <th className="p-2.5 text-left font-medium text-muted-foreground text-xs uppercase tracking-wide">Type</th>
                        <th className="p-2.5 w-8"><span className="sr-only">Delete</span></th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((row) => {
                        const locked = !!row._matched;
                        return (
                          <tr key={row._key} className={`border-b last:border-0 transition-colors ${
                            locked
                              ? 'bg-green-50/60 opacity-70'
                              : row._selected
                                ? 'bg-white hover:bg-blue-50/30'
                                : 'bg-muted/20 opacity-50'
                          }`}>
                            <td className="p-2.5 text-center">
                              {locked
                                ? <span title="Already reconciled" className="text-green-600 text-xs font-bold">✓</span>
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
                                ? <Badge variant="outline" className="text-green-600 border-green-300 text-xs">reconciled</Badge>
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
                    <p className="text-sm text-muted-foreground">No rows — add one manually or upload a new file.</p>
                  </div>
                )}
              </CardContent>
            </Card>

            {/* Action bar */}
            <div className="flex items-center gap-3 rounded-xl border bg-muted/30 px-4 py-3">
              <Button variant="outline" size="sm" onClick={addRow} className="gap-1.5 bg-background">
                <Plus className="h-3.5 w-3.5" /> Add Row
              </Button>
              <span className="text-sm text-muted-foreground ml-auto">
                <strong className="text-foreground">{selectedCount}</strong> row{selectedCount !== 1 ? 's' : ''} selected
              </span>
              <Button
                onClick={handleSave}
                disabled={saving || selectedCount === 0}
                className="gap-2 bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-700 hover:to-indigo-700 text-white shadow-sm"
              >
                <Save className="h-4 w-4" />
                {saving ? 'Saving…' : `Save ${selectedCount} Transaction${selectedCount !== 1 ? 's' : ''}`}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
