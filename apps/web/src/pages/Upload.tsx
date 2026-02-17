import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  CheckCircle, Sparkles, Zap, AlertCircle, Trash2, Plus, Save, GitMerge, FileSpreadsheet,
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

// ── Component ─────────────────────────────────────────────────────────────────

export function Upload() {
  const navigate = useNavigate();

  const [uploading, setUploading]             = useState(false);
  const [rows, setRows]                       = useState<EditableRow[]>([]);
  const [saving, setSaving]                   = useState(false);
  const [saved, setSaved]                     = useState(false);
  const [aiStatus, setAiStatus]               = useState<AIStatus | null>(null);
  const [uploadError, setUploadError]         = useState<string | null>(null);
  const [bankAccounts, setBankAccounts]       = useState<BankAccount[]>([]);
  const [selectedBank, setSelectedBank]       = useState('');
  const [importResult, setImportResult]       = useState<StatementImportResult | null>(null);
  // Keep refs to the upload result objects for the save step
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

  // ── File routing ─────────────────────────────────────────────────────────

  const isStructured = (file: File) =>
    /\.(csv|xls|xlsx)$/i.test(file.name) ||
    ['text/csv', 'application/vnd.ms-excel',
     'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'].includes(file.type);

  const handleFileSelect = async (file: File) => {
    setUploading(true);
    setSaved(false);
    setRows([]);
    setUploadError(null);
    aiBatchRef.current = null;
    stmtRef.current    = null;

    try {
      if (isStructured(file)) {
        // ── CSV / Excel path ──────────────────────────────────────────────
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
        // ── AI path (PDF / image) ─────────────────────────────────────────
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
        setUploadError('AI not available. Check your GEMINI_API_KEY.');
      } else {
        setUploadError('Failed to process file. Check the format and try again.');
      }
    } finally {
      setUploading(false);
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
        // Statement path
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
        // AI batch path
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
      <div className="space-y-4 max-w-2xl">
        <Card className="border-green-200 bg-green-50">
          <CardContent className="flex items-start gap-4 py-6">
            <CheckCircle className="h-10 w-10 text-green-600 shrink-0 mt-0.5" />
            <div className="flex-1">
              <p className="font-semibold text-green-800 text-lg">Import complete!</p>
              {importResult ? (
                <ul className="text-sm text-green-700 mt-1.5 space-y-0.5">
                  {importResult.saved > 0 && <li>✓ <strong>{importResult.saved}</strong> transaction{importResult.saved !== 1 ? 's' : ''} saved</li>}
                  {importResult.reconciled > 0 && <li>⟳ <strong>{importResult.reconciled}</strong> duplicate{importResult.reconciled !== 1 ? 's' : ''} sent to Reconciliation</li>}
                </ul>
              ) : (
                <p className="text-sm text-green-700 mt-1">Transactions saved successfully.</p>
              )}
            </div>
          </CardContent>
        </Card>
        <div className="flex gap-3">
          <Button variant="outline" onClick={() => navigate('/transactions')}>View Transactions</Button>
          {importResult && importResult.reconciled > 0 && (
            <Button onClick={() => navigate('/reconciliation')} className="gap-2">
              <GitMerge className="h-4 w-4" /> Review in Reconciliation
            </Button>
          )}
          <Button variant="ghost" className="ml-auto" onClick={reset}>Upload Another</Button>
        </div>
      </div>
    );
  }

  // ── Main page ─────────────────────────────────────────────────────────────

  return (
    <div className="space-y-6 max-w-6xl">

      {/* Header */}
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Sparkles className="h-6 w-6 text-primary" />
            AI Document Import
          </h1>
          <p className="text-muted-foreground mt-1">
            Upload a bank statement — PDF and images use Gemini AI; CSV and Excel are parsed instantly.
          </p>
        </div>
        {aiStatus && (
          <div className={`flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium border ${
            aiReady ? 'border-green-200 bg-green-50 text-green-700' : 'border-red-200 bg-red-50 text-red-700'
          }`}>
            {aiReady ? <Zap className="h-3.5 w-3.5" /> : <AlertCircle className="h-3.5 w-3.5" />}
            {aiReady ? `${aiStatus.model} ready` : 'Gemini key not set'}
          </div>
        )}
      </div>

      {/* Error banner */}
      {uploadError && (
        <Card className="border-red-200 bg-red-50">
          <CardContent className="py-3 flex items-center gap-3">
            <AlertCircle className="h-5 w-5 text-red-600 shrink-0" />
            <p className="text-sm text-red-700 flex-1">{uploadError}</p>
            <Button size="sm" variant="ghost" onClick={() => setUploadError(null)}>Dismiss</Button>
          </CardContent>
        </Card>
      )}

      {/* Upload form */}
      {!hasRows && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Upload Bank Statement</CardTitle>
            <CardDescription>
              Accepts <span className="font-medium">PDF · PNG · JPG</span> (Gemini AI extracts transactions)
              or <span className="font-medium">CSV · Excel</span> (parsed instantly, no AI needed).
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {/* Bank selector */}
            <div>
              <label className="text-sm font-medium mb-1.5 block">
                Bank Account <span className="text-muted-foreground font-normal">(required for CSV/Excel, optional for PDF/image)</span>
              </label>
              {bankAccounts.length > 0 ? (
                <Select value={selectedBank || '__none__'} onValueChange={(v) => setSelectedBank(v === '__none__' ? '' : v)}>
                  <SelectTrigger className="max-w-xs">
                    <SelectValue placeholder="Select bank…" />
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
                  className="max-w-xs"
                  placeholder="e.g. Access Bank, GTBank…"
                  value={selectedBank}
                  onChange={(e) => setSelectedBank(e.target.value)}
                />
              )}
            </div>

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
              label={uploading
                ? 'Processing…'
                : 'Drop bank statement here — PDF, image, CSV, or Excel'}
            />

            {/* Format hint chips */}
            <div className="flex flex-wrap gap-2 pt-1">
              <span className="flex items-center gap-1 text-xs text-muted-foreground bg-muted rounded-full px-2.5 py-1">
                <Sparkles className="h-3 w-3 text-primary" /> PDF → Gemini AI
              </span>
              <span className="flex items-center gap-1 text-xs text-muted-foreground bg-muted rounded-full px-2.5 py-1">
                <Sparkles className="h-3 w-3 text-primary" /> Image → Gemini AI
              </span>
              <span className="flex items-center gap-1 text-xs text-muted-foreground bg-muted rounded-full px-2.5 py-1">
                <FileSpreadsheet className="h-3 w-3" /> CSV → instant parse
              </span>
              <span className="flex items-center gap-1 text-xs text-muted-foreground bg-muted rounded-full px-2.5 py-1">
                <FileSpreadsheet className="h-3 w-3" /> Excel → instant parse
              </span>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Results */}
      {hasRows && (
        <div className={isAiPath && previewUrl ? 'grid grid-cols-1 lg:grid-cols-2 gap-6 items-start' : 'space-y-4'}>

          {/* Document preview (AI path only) */}
          {isAiPath && previewUrl && (
            <Card className="sticky top-6">
              <CardHeader className="pb-3">
                <CardTitle className="text-sm font-medium text-muted-foreground uppercase tracking-wide">Document Preview</CardTitle>
              </CardHeader>
              <CardContent className="p-0 overflow-hidden rounded-b-xl">
                {isPdf
                  ? <iframe src={previewUrl} className="w-full h-[520px] border-0" title="Document preview" />
                  : <img src={previewUrl} alt="Document preview" className="w-full object-contain max-h-[520px]" />}
              </CardContent>
            </Card>
          )}

          {/* Extracted rows */}
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-lg font-semibold flex items-center gap-2">
                  {isAiPath ? <Sparkles className="h-4 w-4 text-primary" /> : <FileSpreadsheet className="h-4 w-4" />}
                  Extracted Transactions
                  <Badge variant="secondary">{rows.length} row{rows.length !== 1 ? 's' : ''}</Badge>
                </h2>
                <p className="text-sm text-muted-foreground mt-0.5">Review and edit, then save selected rows.</p>
              </div>
              <Button variant="outline" size="sm" onClick={reset}>Upload Different File</Button>
            </div>

            <Card>
              <CardContent className="p-0">
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b bg-muted/40">
                        <th className="p-2 w-8">
                          <input type="checkbox" aria-label="Select all"
                            checked={rows.filter((r) => !r._matched).every((r) => r._selected)}
                            onChange={toggleAll} className="rounded" />
                        </th>
                        <th className="p-2 text-left font-medium">Date</th>
                        <th className="p-2 text-left font-medium">Description</th>
                        <th className="p-2 text-left font-medium">Vendor</th>
                        <th className="p-2 text-left font-medium">Amount</th>
                        <th className="p-2 text-left font-medium">Category</th>
                        <th className="p-2 text-left font-medium">Type</th>
                        <th className="p-2 w-8"><span className="sr-only">Delete</span></th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((row) => {
                        const locked = !!row._matched;
                        return (
                          <tr key={row._key} className={`border-b last:border-0 ${
                            locked ? 'bg-green-50 opacity-60' : row._selected ? 'bg-white' : 'bg-muted/30 opacity-60'
                          }`}>
                            <td className="p-2 text-center">
                              {locked
                                ? <span title="Already reconciled" className="text-green-600 text-xs">✓</span>
                                : <input type="checkbox" aria-label="Select row" checked={row._selected} onChange={() => toggle(row._key)} className="rounded" />}
                            </td>
                            <td className="p-1">
                              {locked
                                ? <span className="text-xs text-muted-foreground px-1.5">{row.date}</span>
                                : <Input type="date" value={row.date} onChange={(e) => update(row._key, 'date', e.target.value)} className="h-7 text-xs px-1.5 min-w-[110px]" />}
                            </td>
                            <td className="p-1">
                              <Input value={row.description} onChange={(e) => update(row._key, 'description', e.target.value)}
                                placeholder="Description" className="h-7 text-xs px-1.5 min-w-[140px]" disabled={locked} />
                            </td>
                            <td className="p-1">
                              <Input value={row.vendor} onChange={(e) => update(row._key, 'vendor', e.target.value)}
                                placeholder="Vendor" className="h-7 text-xs px-1.5 min-w-[100px]" disabled={locked} />
                            </td>
                            <td className="p-1">
                              {locked
                                ? <span className="text-xs font-medium px-1.5">₦{row.amount?.toLocaleString('en-NG', { minimumFractionDigits: 2 })}</span>
                                : <Input type="number" value={row.amount ?? ''} onChange={(e) => update(row._key, 'amount', parseFloat(e.target.value))}
                                    placeholder="0.00" className="h-7 text-xs px-1.5 w-24" />}
                            </td>
                            <td className="p-1">
                              {locked
                                ? <span className="text-xs text-green-600 px-1.5">reconciled</span>
                                : (
                                <select title="Category" value={row.category}
                                  onChange={(e) => update(row._key, 'category', e.target.value)}
                                  className="h-7 text-xs px-1.5 rounded border border-input bg-background w-28">
                                  <option value="">Pick…</option>
                                  {(row.type === 'transfer' ? TRANSFER_CATS : ALL_CATEGORIES).map((c) => (
                                    <option key={c} value={c}>{c}</option>
                                  ))}
                                </select>
                              )}
                            </td>
                            <td className="p-1">
                              {!locked && (
                                <select title="Type" value={row.type}
                                  onChange={(e) => {
                                    const t = e.target.value as EditableRow['type'];
                                    update(row._key, 'type', t);
                                    if (t === 'transfer') update(row._key, 'category', 'Internal Transfer');
                                    else if (row.type === 'transfer') update(row._key, 'category', 'Other');
                                  }}
                                  className="h-7 text-xs px-1.5 rounded border border-input bg-background w-24">
                                  <option value="expense">Expense</option>
                                  <option value="income">Income</option>
                                  <option value="transfer">Transfer</option>
                                </select>
                              )}
                            </td>
                            <td className="p-1 text-center">
                              {!locked && (
                                <button type="button" aria-label="Delete row" onClick={() => deleteRow(row._key)}
                                  className="text-muted-foreground hover:text-destructive transition-colors">
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
                  <p className="text-center text-muted-foreground text-sm py-8">No rows — add one manually or upload again.</p>
                )}
              </CardContent>
            </Card>

            <div className="flex items-center gap-3">
              <Button variant="outline" size="sm" onClick={addRow} className="gap-1.5">
                <Plus className="h-3.5 w-3.5" /> Add Row
              </Button>
              <span className="text-sm text-muted-foreground ml-auto">{selectedCount} selected</span>
              <Button className="gap-1.5" onClick={handleSave} disabled={saving || selectedCount === 0}>
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
