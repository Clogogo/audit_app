import { useEffect, useRef, useState } from 'react';
import {
  CheckCircle, Sparkles, Zap, AlertCircle, Trash2, Plus, Save,
  FileSpreadsheet, Upload as UploadIcon,
} from 'lucide-react';
import {
  uploadBatch, confirmBatch, getFilePreviewUrl,
  uploadBankStatement, getBankTransactions, importStatementTransactions,
  getBankAccounts,
} from '../api/client';
import type {
  BatchItem, BatchConfirmItem, BatchUploadResult,
  BankTransaction, BankStatement, StatementImportItem, BankAccount,
} from '../api/types';
import { FileUploader } from '../components/FileUploader';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Badge } from '../components/ui/badge';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select';
import axios from 'axios';
import { EXPENSE_CATEGORIES, INCOME_CATEGORIES } from '../api/types';

// ── Types ────────────────────────────────────────────────────────────────────

interface AIStatus {
  provider: string;
  model: string;
  configured: boolean;
}

interface EditableRow extends BatchItem {
  _key: number;
  _selected: boolean;
}

interface StmtRow extends BankTransaction {
  _key: number;
  _selected: boolean;
  _category: string;
  _type: 'expense' | 'income';
  _vendor: string;
  _description: string;
}

const ALL_CATEGORIES = [...new Set([...EXPENSE_CATEGORIES, ...INCOME_CATEGORIES])];

type Tab = 'ai' | 'statement';

// ── Component ─────────────────────────────────────────────────────────────────

export function Upload() {
  const [tab, setTab] = useState<Tab>('ai');

  // ── AI tab state ────────────────────────────────────────────────
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState<BatchUploadResult | null>(null);
  const [rows, setRows] = useState<EditableRow[]>([]);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [aiStatus, setAiStatus] = useState<AIStatus | null>(null);
  const [uploadError, setUploadError] = useState<{ message: string; rateLimited: boolean } | null>(null);
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const keyRef = useRef(0);

  // ── Statement tab state ─────────────────────────────────────────
  const [stmtBankName, setStmtBankName] = useState('');
  const [stmtUploading, setStmtUploading] = useState(false);
  const [stmtStatement, setStmtStatement] = useState<BankStatement | null>(null);
  const [stmtRows, setStmtRows] = useState<StmtRow[]>([]);
  const [stmtSaving, setStmtSaving] = useState(false);
  const [stmtSaved, setStmtSaved] = useState(false);
  const [stmtError, setStmtError] = useState<string | null>(null);
  const stmtKeyRef = useRef(0);
  const [bankAccounts, setBankAccounts] = useState<BankAccount[]>([]);

  useEffect(() => {
    axios.get('/api/health').then((r) => setAiStatus(r.data.ai)).catch(() => null);
    getBankAccounts().then(setBankAccounts).catch(() => {});
  }, []);

  // ── AI tab ───────────────────────────────────────────────────────

  useEffect(() => {
    if (!result) { setRows([]); return; }
    setRows(
      result.items.map((item) => ({
        ...item,
        _key: keyRef.current++,
        _selected: true,
      }))
    );
  }, [result]);

  const handleFileSelect = async (file: File) => {
    setUploading(true);
    setSaved(false);
    setResult(null);
    setUploadError(null);
    setPendingFile(file);
    try {
      const res = await uploadBatch(file);
      setResult(res);
      setPendingFile(null);
    } catch (err: unknown) {
      const status = axios.isAxiosError(err) ? err.response?.status : null;
      const detail = axios.isAxiosError(err) ? err.response?.data?.detail : null;
      if (status === 429) {
        setUploadError({ message: detail ?? 'Rate limit reached. Please wait and retry.', rateLimited: true });
      } else if (status === 503) {
        setUploadError({ message: detail ?? 'No AI provider available. Start Ollama or set GEMINI_API_KEY.', rateLimited: false });
      } else {
        setUploadError({ message: 'Failed to process file. Please try again.', rateLimited: false });
      }
    } finally {
      setUploading(false);
    }
  };

  const handleRetry = () => { if (pendingFile) handleFileSelect(pendingFile); };

  const updateRow = (key: number, field: keyof BatchItem, value: string | number) =>
    setRows((prev) => prev.map((r) => (r._key === key ? { ...r, [field]: value } : r)));

  const toggleRow = (key: number) =>
    setRows((prev) => prev.map((r) => (r._key === key ? { ...r, _selected: !r._selected } : r)));

  const toggleAll = () => {
    const allSelected = rows.every((r) => r._selected);
    setRows((prev) => prev.map((r) => ({ ...r, _selected: !allSelected })));
  };

  const deleteRow = (key: number) => setRows((prev) => prev.filter((r) => r._key !== key));

  const addRow = () => {
    const today = new Date().toISOString().split('T')[0];
    setRows((prev) => [
      ...prev,
      { _key: keyRef.current++, _selected: true, type: 'expense', amount: undefined, currency: 'USD', date: today, vendor: '', category: '', description: '', reference: '' },
    ]);
  };

  const handleSave = async () => {
    if (!result) return;
    const selected = rows.filter((r) => r._selected);
    if (!selected.length) { alert('Select at least one row to save.'); return; }
    const invalid = selected.filter((r) => !r.amount || !r.date || !r.category || !r.description);
    if (invalid.length) { alert(`${invalid.length} row(s) missing required fields.`); return; }

    setSaving(true);
    try {
      const items: BatchConfirmItem[] = selected.map((r) => ({
        amount: r.amount as number,
        currency: r.currency ?? 'USD',
        category: r.category as string,
        description: r.description as string,
        date: r.date as string,
        vendor: r.vendor ?? undefined,
        type: r.type ?? 'expense',
        file_id: result.file_id,
      }));
      await confirmBatch(result.file_id, items);
      setSaved(true);
      setResult(null);
    } catch {
      alert('Failed to save transactions. Please try again.');
    } finally {
      setSaving(false);
    }
  };

  // ── Statement tab ────────────────────────────────────────────────

  const handleStmtFileSelect = async (file: File) => {
    if (!stmtBankName.trim()) { setStmtError('Enter the bank name first.'); return; }
    setStmtUploading(true);
    setStmtSaved(false);
    setStmtStatement(null);
    setStmtRows([]);
    setStmtError(null);
    try {
      const stmt = await uploadBankStatement(file, stmtBankName.trim());
      setStmtStatement(stmt);
      const txs = await getBankTransactions(stmt.id);
      setStmtRows(
        txs.map((tx) => ({
          ...tx,
          _key: stmtKeyRef.current++,
          _selected: true,
          _category: tx.transaction_type === 'credit' ? 'Other' : 'Other',
          _type: tx.transaction_type === 'credit' ? 'income' : 'expense',
          _vendor: '',
          _description: tx.description,
        }))
      );
    } catch {
      setStmtError('Failed to parse statement. Check the file format and try again.');
    } finally {
      setStmtUploading(false);
    }
  };

  const updateStmtRow = (key: number, field: keyof Pick<StmtRow, '_category' | '_type' | '_vendor' | '_description'>, value: string) =>
    setStmtRows((prev) => prev.map((r) => (r._key === key ? { ...r, [field]: value } : r)));

  const toggleStmtRow = (key: number) =>
    setStmtRows((prev) => prev.map((r) => (r._key === key ? { ...r, _selected: !r._selected } : r)));

  const toggleAllStmt = () => {
    const allSelected = stmtRows.every((r) => r._selected);
    setStmtRows((prev) => prev.map((r) => ({ ...r, _selected: !allSelected })));
  };

  const deleteStmtRow = (key: number) => setStmtRows((prev) => prev.filter((r) => r._key !== key));

  const handleStmtSave = async () => {
    if (!stmtStatement) return;
    const selected = stmtRows.filter((r) => r._selected);
    if (!selected.length) { alert('Select at least one row to save.'); return; }
    const invalid = selected.filter((r) => !r._category);
    if (invalid.length) { alert(`${invalid.length} row(s) missing a category.`); return; }

    setStmtSaving(true);
    try {
      const items: StatementImportItem[] = selected.map((r) => ({
        bank_transaction_id: r.id,
        amount: r.amount,
        currency: 'USD',
        category: r._category,
        description: r._description || r.description,
        date: r.date,
        vendor: r._vendor || undefined,
        type: r._type,
      }));
      await importStatementTransactions(stmtStatement.id, items);
      setStmtSaved(true);
      setStmtStatement(null);
      setStmtRows([]);
    } catch {
      alert('Failed to save transactions. Please try again.');
    } finally {
      setStmtSaving(false);
    }
  };

  // ── Derived ──────────────────────────────────────────────────────

  const aiReady = aiStatus?.configured;
  const previewUrl = result ? getFilePreviewUrl(result.file_id) : null;
  const isPdf = result?.mime_type?.includes('pdf');
  const selectedCount = rows.filter((r) => r._selected).length;
  const stmtSelectedCount = stmtRows.filter((r) => r._selected).length;

  // ── Render ────────────────────────────────────────────────────────

  if (saved || stmtSaved) {
    return (
      <div className="space-y-6 max-w-4xl">
        <Card className="border-green-200 bg-green-50">
          <CardContent className="flex items-center gap-3 py-8">
            <CheckCircle className="h-10 w-10 text-green-600 shrink-0" />
            <div>
              <p className="font-semibold text-green-800 text-lg">Transactions saved!</p>
              <p className="text-sm text-green-700 mt-1">Go to Transactions to view them.</p>
            </div>
            <Button className="ml-auto" onClick={() => { setSaved(false); setStmtSaved(false); }}>
              Upload Another
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-6 max-w-6xl">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold">Upload &amp; Import</h1>
          <p className="text-muted-foreground mt-1">
            Import transactions from receipts, invoices, or bank statements.
          </p>
        </div>
        {aiStatus && (
          <div className={`flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium border ${
            aiReady ? 'border-green-200 bg-green-50 text-green-700' : 'border-yellow-200 bg-yellow-50 text-yellow-700'
          }`}>
            {aiReady ? <Zap className="h-3.5 w-3.5" /> : <AlertCircle className="h-3.5 w-3.5" />}
            {aiReady ? `${aiStatus.model} ready` : 'AI key not set'}
          </div>
        )}
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b">
        <button
          type="button"
          onClick={() => setTab('ai')}
          className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
            tab === 'ai'
              ? 'border-primary text-primary'
              : 'border-transparent text-muted-foreground hover:text-foreground'
          }`}
        >
          <Sparkles className="h-4 w-4" />
          AI Document
        </button>
        <button
          type="button"
          onClick={() => setTab('statement')}
          className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
            tab === 'statement'
              ? 'border-primary text-primary'
              : 'border-transparent text-muted-foreground hover:text-foreground'
          }`}
        >
          <FileSpreadsheet className="h-4 w-4" />
          Bank Statement
          <Badge variant="secondary" className="text-[10px] py-0 px-1.5">CSV / Excel</Badge>
        </button>
      </div>

      {/* ── AI TAB ─────────────────────────────────────────────────── */}
      {tab === 'ai' && (
        <>
          {aiStatus && !aiReady && (
            <Card className="border-yellow-200 bg-yellow-50">
              <CardContent className="py-4">
                <div className="flex items-start gap-3">
                  <AlertCircle className="h-5 w-5 text-yellow-600 mt-0.5 shrink-0" />
                  <div className="text-sm text-yellow-800">
                    <strong>AI key not configured.</strong> Start Ollama or set <code className="bg-yellow-100 rounded px-1">GEMINI_API_KEY</code> in <code className="bg-yellow-100 rounded px-1">apps/api/.env</code>.
                  </div>
                </div>
              </CardContent>
            </Card>
          )}

          {uploadError && (
            <Card className={uploadError.rateLimited ? 'border-orange-200 bg-orange-50' : 'border-red-200 bg-red-50'}>
              <CardContent className="py-4">
                <div className="flex items-start gap-3">
                  <AlertCircle className={`h-5 w-5 mt-0.5 shrink-0 ${uploadError.rateLimited ? 'text-orange-600' : 'text-red-600'}`} />
                  <div className="flex-1 text-sm">
                    <strong className={uploadError.rateLimited ? 'text-orange-800' : 'text-red-800'}>
                      {uploadError.rateLimited ? 'Rate limit reached' : 'Upload failed'}
                    </strong>
                    <p className={`mt-0.5 ${uploadError.rateLimited ? 'text-orange-700' : 'text-red-700'}`}>{uploadError.message}</p>
                  </div>
                  {uploadError.rateLimited && pendingFile && (
                    <Button size="sm" variant="outline" onClick={handleRetry} disabled={uploading}
                      className="border-orange-300 text-orange-800 hover:bg-orange-100 shrink-0">
                      {uploading ? 'Retrying…' : 'Retry'}
                    </Button>
                  )}
                </div>
              </CardContent>
            </Card>
          )}

          {!result && (
            <FileUploader
              onFileSelect={handleFileSelect}
              isLoading={uploading}
              label={aiReady ? 'Drop receipt, invoice, or register here' : 'Drop file here (AI key not set)'}
            />
          )}

          {result && (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 items-start">
              <Card className="sticky top-6">
                <CardHeader className="pb-3">
                  <CardTitle className="text-sm font-medium text-muted-foreground uppercase tracking-wide">Document Preview</CardTitle>
                  <CardDescription className="truncate">{result.original_name}</CardDescription>
                </CardHeader>
                <CardContent className="p-0 overflow-hidden rounded-b-xl">
                  {previewUrl && (isPdf
                    ? <iframe src={previewUrl} className="w-full h-[520px] border-0" title="Document preview" />
                    : <img src={previewUrl} alt="Document preview" className="w-full object-contain max-h-[520px]" />
                  )}
                </CardContent>
              </Card>

              <div className="space-y-4">
                <Card>
                  <CardHeader className="pb-3">
                    <div className="flex items-center gap-2">
                      <Sparkles className="h-4 w-4 text-primary" />
                      <CardTitle className="text-base">Extracted Transactions</CardTitle>
                      <Badge variant="secondary" className="ml-auto">{result.item_count} row{result.item_count !== 1 ? 's' : ''}</Badge>
                    </div>
                    <CardDescription>Review and edit, then save selected rows as transactions.</CardDescription>
                  </CardHeader>
                  <CardContent className="p-0">
                    <div className="overflow-x-auto">
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="border-b bg-muted/40">
                            <th className="p-2 w-8">
                              <input type="checkbox" aria-label="Select all" checked={rows.length > 0 && rows.every((r) => r._selected)} onChange={toggleAll} className="rounded" />
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
                          {rows.map((row) => (
                            <tr key={row._key} className={`border-b last:border-0 ${row._selected ? 'bg-white' : 'bg-muted/30 opacity-60'}`}>
                              <td className="p-2 text-center">
                                <input type="checkbox" aria-label="Select row" checked={row._selected} onChange={() => toggleRow(row._key)} className="rounded" />
                              </td>
                              <td className="p-1">
                                <Input type="date" value={row.date ?? ''} onChange={(e) => updateRow(row._key, 'date', e.target.value)} className="h-7 text-xs px-1.5 min-w-[110px]" />
                              </td>
                              <td className="p-1">
                                <Input value={row.description ?? ''} onChange={(e) => updateRow(row._key, 'description', e.target.value)} placeholder="Description" className="h-7 text-xs px-1.5 min-w-[130px]" />
                              </td>
                              <td className="p-1">
                                <Input value={row.vendor ?? ''} onChange={(e) => updateRow(row._key, 'vendor', e.target.value)} placeholder="Vendor" className="h-7 text-xs px-1.5 min-w-[100px]" />
                              </td>
                              <td className="p-1">
                                <Input type="number" value={row.amount ?? ''} onChange={(e) => updateRow(row._key, 'amount', parseFloat(e.target.value))} placeholder="0.00" className="h-7 text-xs px-1.5 w-20" />
                              </td>
                              <td className="p-1">
                                <select title="Category" value={row.category ?? ''} onChange={(e) => updateRow(row._key, 'category', e.target.value)} className="h-7 text-xs px-1.5 rounded border border-input bg-background w-28">
                                  <option value="">Pick…</option>
                                  {ALL_CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
                                </select>
                              </td>
                              <td className="p-1">
                                <select title="Transaction type" value={row.type ?? 'expense'} onChange={(e) => updateRow(row._key, 'type', e.target.value)} className="h-7 text-xs px-1.5 rounded border border-input bg-background w-24">
                                  <option value="expense">Expense</option>
                                  <option value="income">Income</option>
                                </select>
                              </td>
                              <td className="p-1 text-center">
                                <button type="button" aria-label="Delete row" onClick={() => deleteRow(row._key)} className="text-muted-foreground hover:text-destructive transition-colors">
                                  <Trash2 className="h-3.5 w-3.5" />
                                </button>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    {rows.length === 0 && <p className="text-center text-muted-foreground text-sm py-8">No rows — add one manually or upload again.</p>}
                  </CardContent>
                </Card>

                <div className="flex items-center gap-3">
                  <Button variant="outline" size="sm" onClick={addRow} className="gap-1.5"><Plus className="h-3.5 w-3.5" /> Add Row</Button>
                  <Button variant="outline" size="sm" onClick={() => { setResult(null); setSaved(false); }}>Upload Different File</Button>
                  <Button className="ml-auto gap-1.5" onClick={handleSave} disabled={saving || selectedCount === 0}>
                    <Save className="h-4 w-4" />
                    {saving ? 'Saving…' : `Save ${selectedCount} Transaction${selectedCount !== 1 ? 's' : ''}`}
                  </Button>
                </div>
              </div>
            </div>
          )}

          {!result && (
            <Card className="bg-muted/30">
              <CardContent className="py-4">
                <p className="text-xs text-muted-foreground">
                  <strong>How it works:</strong> Images and PDFs are processed by <strong>llama3.2-vision</strong> (local) or <strong>Gemini 2.0 Flash</strong> (fallback) to extract all transaction rows automatically.
                </p>
              </CardContent>
            </Card>
          )}
        </>
      )}

      {/* ── STATEMENT TAB ──────────────────────────────────────────── */}
      {tab === 'statement' && (
        <>
          {stmtError && (
            <Card className="border-red-200 bg-red-50">
              <CardContent className="py-3 flex items-center gap-3">
                <AlertCircle className="h-5 w-5 text-red-600 shrink-0" />
                <p className="text-sm text-red-700">{stmtError}</p>
                <Button size="sm" variant="ghost" onClick={() => setStmtError(null)} className="ml-auto">Dismiss</Button>
              </CardContent>
            </Card>
          )}

          {!stmtStatement && (
            <Card>
              <CardHeader>
                <div className="flex items-center gap-2">
                  <FileSpreadsheet className="h-5 w-5 text-primary" />
                  <CardTitle className="text-base">Import Bank Statement</CardTitle>
                </div>
                <CardDescription>
                  Upload a CSV or Excel export from your bank. All rows are parsed and shown for review before saving.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="flex gap-3 items-end">
                  <div className="flex-1">
                    <label className="text-sm font-medium mb-1.5 block">Bank Name</label>
                    {bankAccounts.length > 0 ? (
                      <Select
                        value={stmtBankName || '__none__'}
                        onValueChange={(v) => setStmtBankName(v === '__none__' ? '' : v)}
                      >
                        <SelectTrigger>
                          <SelectValue placeholder="Select bank…" />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="__none__">Select bank…</SelectItem>
                          {bankAccounts.map((b) => (
                            <SelectItem key={b.id} value={b.bank_name}>
                              {b.bank_name}{b.account_number ? ` — ${b.account_number}` : ''}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    ) : (
                      <Input
                        placeholder="e.g. First Bank, Access Bank, GTBank…"
                        value={stmtBankName}
                        onChange={(e) => setStmtBankName(e.target.value)}
                      />
                    )}
                  </div>
                </div>
                <FileUploader
                  onFileSelect={handleStmtFileSelect}
                  isLoading={stmtUploading}
                  accept={{
                    'text/csv': ['.csv'],
                    'application/vnd.ms-excel': ['.xls'],
                    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
                    'application/pdf': ['.pdf'],
                  }}
                  label={stmtBankName.trim() ? `Drop ${stmtBankName} statement here (CSV or Excel)` : 'Enter bank name above, then drop statement here'}
                />
              </CardContent>
            </Card>
          )}

          {stmtStatement && stmtRows.length > 0 && (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="text-lg font-semibold">{stmtStatement.bank_name}</h2>
                  <p className="text-sm text-muted-foreground">
                    {stmtRows.length} transaction{stmtRows.length !== 1 ? 's' : ''} parsed — review and assign categories before saving
                  </p>
                </div>
                <Button variant="outline" size="sm" onClick={() => { setStmtStatement(null); setStmtRows([]); }}>
                  <UploadIcon className="h-3.5 w-3.5 mr-1.5" /> Upload Different File
                </Button>
              </div>

              <Card>
                <CardContent className="p-0">
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b bg-muted/40">
                          <th className="p-2 w-8">
                            <input type="checkbox" aria-label="Select all" checked={stmtRows.every((r) => r._selected)} onChange={toggleAllStmt} className="rounded" />
                          </th>
                          <th className="p-2 text-left font-medium">Date</th>
                          <th className="p-2 text-left font-medium">Description</th>
                          <th className="p-2 text-left font-medium">Vendor</th>
                          <th className="p-2 text-left font-medium">Amount</th>
                          <th className="p-2 text-left font-medium">Direction</th>
                          <th className="p-2 text-left font-medium">Category</th>
                          <th className="p-2 text-left font-medium">Type</th>
                          <th className="p-2 w-8"><span className="sr-only">Delete</span></th>
                        </tr>
                      </thead>
                      <tbody>
                        {stmtRows.map((row) => (
                          <tr key={row._key} className={`border-b last:border-0 ${row._selected ? 'bg-white' : 'bg-muted/30 opacity-60'}`}>
                            <td className="p-2 text-center">
                              <input type="checkbox" aria-label="Select row" checked={row._selected} onChange={() => toggleStmtRow(row._key)} className="rounded" />
                            </td>
                            <td className="p-2 text-xs text-muted-foreground whitespace-nowrap">{row.date}</td>
                            <td className="p-1">
                              <Input
                                value={row._description}
                                onChange={(e) => updateStmtRow(row._key, '_description', e.target.value)}
                                className="h-7 text-xs px-1.5 min-w-[150px]"
                              />
                            </td>
                            <td className="p-1">
                              <Input
                                value={row._vendor}
                                onChange={(e) => updateStmtRow(row._key, '_vendor', e.target.value)}
                                placeholder="Vendor"
                                className="h-7 text-xs px-1.5 min-w-[100px]"
                              />
                            </td>
                            <td className="p-2 text-xs font-medium whitespace-nowrap">
                              {row.amount.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                            </td>
                            <td className="p-2">
                              <Badge variant={row.transaction_type === 'credit' ? 'default' : 'secondary'} className="text-[10px]">
                                {row.transaction_type}
                              </Badge>
                            </td>
                            <td className="p-1">
                              <select
                                title="Category"
                                value={row._category}
                                onChange={(e) => updateStmtRow(row._key, '_category', e.target.value)}
                                className="h-7 text-xs px-1.5 rounded border border-input bg-background w-28"
                              >
                                <option value="">Pick…</option>
                                {ALL_CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
                              </select>
                            </td>
                            <td className="p-1">
                              <select
                                title="Transaction type"
                                value={row._type}
                                onChange={(e) => updateStmtRow(row._key, '_type', e.target.value as 'expense' | 'income')}
                                className="h-7 text-xs px-1.5 rounded border border-input bg-background w-24"
                              >
                                <option value="expense">Expense</option>
                                <option value="income">Income</option>
                              </select>
                            </td>
                            <td className="p-1 text-center">
                              <button type="button" aria-label="Delete row" onClick={() => deleteStmtRow(row._key)} className="text-muted-foreground hover:text-destructive transition-colors">
                                <Trash2 className="h-3.5 w-3.5" />
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </CardContent>
              </Card>

              <div className="flex items-center gap-3">
                <span className="text-sm text-muted-foreground">{stmtSelectedCount} of {stmtRows.length} selected</span>
                <Button
                  className="ml-auto gap-1.5"
                  onClick={handleStmtSave}
                  disabled={stmtSaving || stmtSelectedCount === 0}
                >
                  <Save className="h-4 w-4" />
                  {stmtSaving ? 'Saving…' : `Save ${stmtSelectedCount} Transaction${stmtSelectedCount !== 1 ? 's' : ''}`}
                </Button>
              </div>
            </div>
          )}

          {stmtStatement && stmtRows.length === 0 && !stmtUploading && (
            <Card className="border-yellow-200 bg-yellow-50">
              <CardContent className="py-6 text-center text-sm text-yellow-800">
                No transactions were parsed from this file. Make sure it has standard columns (Date, Description, Amount).
              </CardContent>
            </Card>
          )}

          {!stmtStatement && (
            <Card className="bg-muted/30">
              <CardContent className="py-4">
                <p className="text-xs text-muted-foreground">
                  <strong>Supported formats:</strong> CSV and Excel (.xlsx/.xls) exports from any bank.
                  Common column names are detected automatically — Date, Description, Amount, Debit, Credit, Reference.
                  The bank name you enter will be stored on every imported transaction.
                </p>
              </CardContent>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
