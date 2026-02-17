import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  CheckCircle, Sparkles, Zap, AlertCircle, Trash2, Plus, Save, GitMerge,
} from 'lucide-react';
import {
  uploadBatch, confirmBatch, getFilePreviewUrl, getBankAccounts,
} from '../api/client';
import type {
  BatchItem, BatchConfirmItem, BatchUploadResult, BankAccount,
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

interface AIStatus {
  provider: string;
  model: string;
  configured: boolean;
}

interface EditableRow extends BatchItem {
  _key: number;
  _selected: boolean;
}

const ALL_CATEGORIES = [...new Set([...EXPENSE_CATEGORIES, ...INCOME_CATEGORIES])];

// ── Component ─────────────────────────────────────────────────────────────────

export function Upload() {
  const navigate = useNavigate();

  const [uploading, setUploading]       = useState(false);
  const [result, setResult]             = useState<BatchUploadResult | null>(null);
  const [rows, setRows]                 = useState<EditableRow[]>([]);
  const [saving, setSaving]             = useState(false);
  const [saved, setSaved]               = useState(false);
  const [aiStatus, setAiStatus]         = useState<AIStatus | null>(null);
  const [uploadError, setUploadError]   = useState<{ message: string; rateLimited: boolean } | null>(null);
  const [pendingFile, setPendingFile]   = useState<File | null>(null);
  const [bankAccounts, setBankAccounts] = useState<BankAccount[]>([]);
  const [selectedBank, setSelectedBank] = useState('');
  const keyRef = useRef(0);

  useEffect(() => {
    axios.get('/api/health').then((r) => setAiStatus(r.data.ai)).catch(() => null);
    getBankAccounts().then(setBankAccounts).catch(() => {});
  }, []);

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
        setUploadError({ message: detail ?? 'AI not available. Check your GEMINI_API_KEY.', rateLimited: false });
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

  const toggleRow    = (key: number) =>
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
      { _key: keyRef.current++, _selected: true, type: 'expense', amount: undefined, currency: 'NGN', date: today, vendor: selectedBank || '', category: '', description: '', reference: '' },
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
        amount:      r.amount as number,
        currency:    r.currency ?? 'NGN',
        category:    r.category as string,
        description: r.description as string,
        date:        r.date as string,
        vendor:      r.vendor ?? selectedBank || undefined,
        type:        r.type ?? 'expense',
        file_id:     result.file_id,
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

  const aiReady        = aiStatus?.configured;
  const previewUrl     = result ? getFilePreviewUrl(result.file_id) : null;
  const isPdf          = result?.mime_type?.includes('pdf');
  const selectedCount  = rows.filter((r) => r._selected).length;

  // ── Success screen ────────────────────────────────────────────────────────

  if (saved) {
    return (
      <div className="space-y-4 max-w-2xl">
        <Card className="border-green-200 bg-green-50">
          <CardContent className="flex items-start gap-4 py-6">
            <CheckCircle className="h-10 w-10 text-green-600 shrink-0 mt-0.5" />
            <div className="flex-1">
              <p className="font-semibold text-green-800 text-lg">Import complete!</p>
              <p className="text-sm text-green-700 mt-1">Transactions saved successfully.</p>
            </div>
          </CardContent>
        </Card>
        <div className="flex gap-3">
          <Button variant="outline" onClick={() => navigate('/transactions')}>
            View Transactions
          </Button>
          <Button variant="outline" onClick={() => navigate('/reconciliation')} className="gap-2">
            <GitMerge className="h-4 w-4" />
            Reconciliation
          </Button>
          <Button variant="ghost" className="ml-auto" onClick={() => setSaved(false)}>
            Upload Another
          </Button>
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
            Upload a bank statement PDF or image — Gemini AI extracts all transactions automatically.
          </p>
        </div>
        {aiStatus && (
          <div className={`flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium border ${
            aiReady
              ? 'border-green-200 bg-green-50 text-green-700'
              : 'border-red-200 bg-red-50 text-red-700'
          }`}>
            {aiReady ? <Zap className="h-3.5 w-3.5" /> : <AlertCircle className="h-3.5 w-3.5" />}
            {aiReady ? `${aiStatus.model} ready` : 'Gemini API key not set'}
          </div>
        )}
      </div>

      {/* AI not configured warning */}
      {aiStatus && !aiReady && (
        <Card className="border-red-200 bg-red-50">
          <CardContent className="py-4">
            <div className="flex items-start gap-3">
              <AlertCircle className="h-5 w-5 text-red-600 mt-0.5 shrink-0" />
              <p className="text-sm text-red-800">
                <strong>Gemini API key not configured.</strong> Add <code className="bg-red-100 rounded px-1">GEMINI_API_KEY</code> to your environment variables.
              </p>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Upload error */}
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

      {/* Upload form */}
      {!result && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Upload Bank Statement</CardTitle>
            <CardDescription>
              Supported: PDF, PNG, JPG, WEBP — Gemini AI will extract every transaction row.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {/* Bank selector */}
            <div>
              <label className="text-sm font-medium mb-1.5 block">Bank Account <span className="text-muted-foreground font-normal">(optional)</span></label>
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
                'application/pdf': ['.pdf'],
                'image/png': ['.png'],
                'image/jpeg': ['.jpg', '.jpeg'],
                'image/webp': ['.webp'],
              }}
              label={uploading ? 'Extracting transactions with Gemini AI…' : 'Drop bank statement here (PDF or image)'}
            />
          </CardContent>
        </Card>
      )}

      {/* Results */}
      {result && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 items-start">
          {/* Document preview */}
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

          {/* Extracted rows */}
          <div className="space-y-4">
            <Card>
              <CardHeader className="pb-3">
                <div className="flex items-center gap-2">
                  <Sparkles className="h-4 w-4 text-primary" />
                  <CardTitle className="text-base">Extracted Transactions</CardTitle>
                  <Badge variant="secondary" className="ml-auto">
                    {result.item_count} row{result.item_count !== 1 ? 's' : ''}
                  </Badge>
                </div>
                <CardDescription>Review and edit, then save selected rows.</CardDescription>
              </CardHeader>
              <CardContent className="p-0">
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b bg-muted/40">
                        <th className="p-2 w-8">
                          <input type="checkbox" aria-label="Select all"
                            checked={rows.length > 0 && rows.every((r) => r._selected)}
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
                      {rows.map((row) => (
                        <tr key={row._key} className={`border-b last:border-0 ${row._selected ? 'bg-white' : 'bg-muted/30 opacity-60'}`}>
                          <td className="p-2 text-center">
                            <input type="checkbox" aria-label="Select row"
                              checked={row._selected} onChange={() => toggleRow(row._key)} className="rounded" />
                          </td>
                          <td className="p-1">
                            <Input type="date" value={row.date ?? ''} onChange={(e) => updateRow(row._key, 'date', e.target.value)}
                              className="h-7 text-xs px-1.5 min-w-[110px]" />
                          </td>
                          <td className="p-1">
                            <Input value={row.description ?? ''} onChange={(e) => updateRow(row._key, 'description', e.target.value)}
                              placeholder="Description" className="h-7 text-xs px-1.5 min-w-[130px]" />
                          </td>
                          <td className="p-1">
                            <Input value={row.vendor ?? ''} onChange={(e) => updateRow(row._key, 'vendor', e.target.value)}
                              placeholder="Vendor" className="h-7 text-xs px-1.5 min-w-[100px]" />
                          </td>
                          <td className="p-1">
                            <Input type="number" value={row.amount ?? ''} onChange={(e) => updateRow(row._key, 'amount', parseFloat(e.target.value))}
                              placeholder="0.00" className="h-7 text-xs px-1.5 w-20" />
                          </td>
                          <td className="p-1">
                            <select title="Category" value={row.category ?? ''} onChange={(e) => updateRow(row._key, 'category', e.target.value)}
                              className="h-7 text-xs px-1.5 rounded border border-input bg-background w-28">
                              <option value="">Pick…</option>
                              {ALL_CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
                            </select>
                          </td>
                          <td className="p-1">
                            <select title="Transaction type" value={row.type ?? 'expense'} onChange={(e) => updateRow(row._key, 'type', e.target.value)}
                              className="h-7 text-xs px-1.5 rounded border border-input bg-background w-24">
                              <option value="expense">Expense</option>
                              <option value="income">Income</option>
                            </select>
                          </td>
                          <td className="p-1 text-center">
                            <button type="button" aria-label="Delete row" onClick={() => deleteRow(row._key)}
                              className="text-muted-foreground hover:text-destructive transition-colors">
                              <Trash2 className="h-3.5 w-3.5" />
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {rows.length === 0 && (
                  <p className="text-center text-muted-foreground text-sm py-8">
                    No rows extracted — add one manually or upload again.
                  </p>
                )}
              </CardContent>
            </Card>

            <div className="flex items-center gap-3">
              <Button variant="outline" size="sm" onClick={addRow} className="gap-1.5">
                <Plus className="h-3.5 w-3.5" /> Add Row
              </Button>
              <Button variant="outline" size="sm" onClick={() => { setResult(null); setSaved(false); }}>
                Upload Different File
              </Button>
              <Button className="ml-auto gap-1.5" onClick={handleSave} disabled={saving || selectedCount === 0}>
                <Save className="h-4 w-4" />
                {saving ? 'Saving…' : `Save ${selectedCount} Transaction${selectedCount !== 1 ? 's' : ''}`}
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* How it works */}
      {!result && (
        <Card className="bg-muted/30">
          <CardContent className="py-4">
            <p className="text-xs text-muted-foreground">
              <strong>How it works:</strong> Your document is sent to <strong>Gemini {aiStatus?.model ?? '2.0 Flash'}</strong> which reads
              every transaction row and returns structured data. Review the extracted rows, make any corrections, then save.
              Works with scanned PDFs, printed statements, and photos of bank books.
            </p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
