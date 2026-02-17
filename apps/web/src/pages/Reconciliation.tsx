import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  GitMerge, Zap, Link2, Unlink, CheckCircle2, Trash2,
  ChevronDown, ChevronRight, Save,
} from 'lucide-react';
import {
  getBankStatements,
  uploadBankStatement,
  getBankTransactions,
  getTransactions,
  autoMatch,
  manualMatch,
  unmatch,
  getReconciliationStatus,
  exportReconciliation,
  deleteBankStatement,
  batchDeleteBankStatements,
  saveUnmatchedTransactions,
} from '../api/client';
import type { BankStatement, BankTransaction, Transaction, ReconciliationStatus, StatementImportResult } from '../api/types';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Badge } from '../components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { FileUploader } from '../components/FileUploader';
import { ConfirmDialog } from '../components/ConfirmDialog';
import { formatCurrency, formatDate, cn } from '../lib/utils';

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export function Reconciliation() {
  const navigate = useNavigate();

  const [statements, setStatements]           = useState<BankStatement[]>([]);
  const [selected, setSelected]               = useState<BankStatement | null>(null);
  const [bankTxs, setBankTxs]                 = useState<BankTransaction[]>([]);
  const [recordedTxs, setRecordedTxs]         = useState<Transaction[]>([]);
  const [status, setStatus]                   = useState<ReconciliationStatus | null>(null);
  const [bankName, setBankName]               = useState('');
  const [uploading, setUploading]             = useState(false);
  const [matching, setMatching]               = useState(false);
  const [saving, setSaving]                   = useState(false);
  const [saveResult, setSaveResult]           = useState<StatementImportResult | null>(null);
  const [selectedBankTx, setSelectedBankTx]   = useState<number | null>(null);
  const [showMatched, setShowMatched]         = useState(false);
  const [deleteTarget, setDeleteTarget]       = useState<BankStatement | null>(null);
  const [deleting, setDeleting]               = useState(false);
  const [checkedIds, setCheckedIds]           = useState<Set<number>>(new Set());
  const [batchDeleting, setBatchDeleting]     = useState(false);
  const [showBatchConfirm, setShowBatchConfirm] = useState(false);

  useEffect(() => {
    getBankStatements().then(setStatements);
    getTransactions().then(setRecordedTxs);
  }, []);

  const loadStatement = async (stmt: BankStatement) => {
    setSelected(stmt);
    setSaveResult(null);
    setSelectedBankTx(null);
    const [txs, s] = await Promise.all([
      getBankTransactions(stmt.id),
      getReconciliationStatus(stmt.id),
    ]);
    setBankTxs(txs);
    setStatus(s);
  };

  const handleUpload = async (file: File) => {
    if (!bankName.trim()) { alert('Please enter the bank name first.'); return; }
    setUploading(true);
    try {
      const stmt = await uploadBankStatement(file, bankName);
      const updated = await getBankStatements();
      setStatements(updated);
      await loadStatement(stmt);
    } finally {
      setUploading(false);
    }
  };

  const handleAutoMatch = async () => {
    if (!selected) return;
    setMatching(true);
    try {
      const result = await autoMatch(selected.id);
      await loadStatement(selected);
      if (result.matched === 0) {
        alert('No automatic matches found. You can match manually, or click "Save Unmatched" to add them as new transactions.');
      } else {
        alert(`Auto-matched ${result.matched} transaction${result.matched !== 1 ? 's' : ''} to existing records.`);
      }
    } finally {
      setMatching(false);
    }
  };

  const handleManualMatch = async (transactionId: number) => {
    if (!selectedBankTx) return;
    await manualMatch(selectedBankTx, transactionId);
    setSelectedBankTx(null);
    if (selected) await loadStatement(selected);
  };

  const handleUnmatch = async (bankTxId: number) => {
    await unmatch(bankTxId);
    if (selected) await loadStatement(selected);
  };

  /** Save all remaining unmatched bank transactions as new Transactions */
  const handleSaveUnmatched = async () => {
    if (!selected) return;
    const unmatchedCount = status?.unmatched ?? 0;
    if (unmatchedCount === 0) { alert('No unmatched transactions to save.'); return; }
    setSaving(true);
    try {
      const result = await saveUnmatchedTransactions(selected.id);
      setSaveResult(result);
      await loadStatement(selected);
      // Refresh recorded transactions list so they appear immediately
      getTransactions().then(setRecordedTxs);
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteStatement = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await deleteBankStatement(deleteTarget.id);
      const updated = await getBankStatements();
      setStatements(updated);
      if (selected?.id === deleteTarget.id) {
        setSelected(null); setBankTxs([]); setStatus(null); setSaveResult(null);
      }
      setCheckedIds((prev) => { const next = new Set(prev); next.delete(deleteTarget.id); return next; });
    } finally {
      setDeleting(false);
      setDeleteTarget(null);
    }
  };

  const handleBatchDelete = async () => {
    if (checkedIds.size === 0) return;
    setBatchDeleting(true);
    try {
      await batchDeleteBankStatements([...checkedIds]);
      const updated = await getBankStatements();
      setStatements(updated);
      if (selected && checkedIds.has(selected.id)) {
        setSelected(null); setBankTxs([]); setStatus(null); setSaveResult(null);
      }
      setCheckedIds(new Set());
    } finally {
      setBatchDeleting(false);
      setShowBatchConfirm(false);
    }
  };

  const toggleCheck = (id: number, e: React.MouseEvent) => {
    e.stopPropagation();
    setCheckedIds((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const handleExport = async (format: 'csv' | 'pdf') => {
    if (!selected) return;
    const blob = await exportReconciliation(selected.id, format);
    downloadBlob(blob, `reconciliation-${selected.id}.${format}`);
  };

  // ── Derived ──────────────────────────────────────────────────────────────────
  const unmatchedBankTxs = bankTxs.filter((b) => b.match_status !== 'matched');
  const matchedBankTxs   = bankTxs.filter((b) => b.match_status === 'matched');

  const matchStatusColor = (s: BankTransaction['match_status']) =>
    s === 'matched' ? 'text-green-600' : s === 'discrepancy' ? 'text-yellow-600' : 'text-muted-foreground';

  const BankTxCard = ({ btx }: { btx: BankTransaction }) => (
    <div
      key={btx.id}
      onClick={() => btx.match_status !== 'matched' && setSelectedBankTx(btx.id === selectedBankTx ? null : btx.id)}
      className={cn(
        'rounded-lg border p-3 text-sm transition-colors',
        btx.match_status !== 'matched' ? 'cursor-pointer hover:bg-muted/30' : 'opacity-60 cursor-default bg-green-50 border-green-200',
        btx.id === selectedBankTx && 'border-primary bg-primary/5',
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="font-medium truncate max-w-[60%]">{btx.description}</span>
        <span className={`font-semibold shrink-0 ${btx.transaction_type === 'credit' ? 'text-green-600' : 'text-red-600'}`}>
          {formatCurrency(btx.amount)}
        </span>
      </div>
      <div className="flex items-center justify-between mt-1 gap-2">
        <div className="text-xs text-muted-foreground truncate">
          {formatDate(btx.date)}
          {btx.vendor && <span className="ml-1.5">· {btx.vendor}</span>}
        </div>
        <span className={`text-xs shrink-0 ${matchStatusColor(btx.match_status)}`}>
          {btx.match_status}
          {btx.match_confidence && ` (${Math.round(btx.match_confidence * 100)}%)`}
        </span>
      </div>
      {btx.match_status === 'matched' && (
        <button
          onClick={(e) => { e.stopPropagation(); handleUnmatch(btx.id); }}
          className="flex items-center gap-1 text-xs text-muted-foreground hover:text-destructive mt-1.5"
        >
          <Unlink className="h-3 w-3" /> Unmatch
        </button>
      )}
    </div>
  );

  return (
    <div className="space-y-6">
      <ConfirmDialog
        open={!!deleteTarget}
        title="Clear reconciliation?"
        description={`This will permanently delete the "${deleteTarget?.bank_name}" statement and all its bank transactions. Transactions you already saved to your records will not be affected.`}
        confirmLabel="Clear"
        loading={deleting}
        onConfirm={handleDeleteStatement}
        onCancel={() => setDeleteTarget(null)}
      />
      <ConfirmDialog
        open={showBatchConfirm}
        title={`Clear ${checkedIds.size} statement${checkedIds.size !== 1 ? 's' : ''}?`}
        description={`This will permanently delete ${checkedIds.size} bank statement${checkedIds.size !== 1 ? 's' : ''} and all their bank transactions. Transactions you already saved to your records will not be affected.`}
        confirmLabel="Clear All"
        loading={batchDeleting}
        onConfirm={handleBatchDelete}
        onCancel={() => setShowBatchConfirm(false)}
      />

      <h1 className="text-2xl font-bold">Bank Statement Reconciliation</h1>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left: Upload + statement list */}
        <div className="space-y-4">
          <Card>
            <CardHeader><CardTitle className="text-sm">Import Bank Statement</CardTitle></CardHeader>
            <CardContent className="space-y-3">
              <Input placeholder="Bank name (e.g. Access Bank)" value={bankName} onChange={(e) => setBankName(e.target.value)} />
              <FileUploader
                label="Drop CSV, Excel, or PDF"
                accept={{
                  'text/csv': ['.csv'],
                  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
                  'application/vnd.ms-excel': ['.xls'],
                  'application/pdf': ['.pdf'],
                }}
                onFileSelect={handleUpload}
                isLoading={uploading}
                className="py-4"
              />
            </CardContent>
          </Card>

          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Statements</p>
              {checkedIds.size > 0 && (
                <button
                  type="button"
                  onClick={() => setShowBatchConfirm(true)}
                  className="flex items-center gap-1 text-xs text-destructive hover:underline"
                >
                  <Trash2 className="h-3 w-3" />
                  Clear {checkedIds.size} selected
                </button>
              )}
            </div>
            {statements.length === 0 && (
              <p className="text-sm text-muted-foreground">No statements imported yet</p>
            )}
            {statements.map((s) => (
              <div
                key={s.id}
                className={cn(
                  'group relative rounded-lg border p-3 text-sm transition-colors cursor-pointer',
                  selected?.id === s.id ? 'border-primary bg-primary/5' : 'hover:bg-muted/50',
                  checkedIds.has(s.id) && 'border-destructive/40 bg-destructive/5'
                )}
                onClick={() => loadStatement(s)}
              >
                <div className="flex items-start gap-2">
                  <input
                    type="checkbox"
                    title={`Select ${s.bank_name}`}
                    checked={checkedIds.has(s.id)}
                    onClick={(e) => toggleCheck(s.id, e)}
                    onChange={() => {}}
                    className="mt-0.5 shrink-0 accent-destructive"
                  />
                  <div className="flex-1 min-w-0 pr-6">
                    <div className="font-medium truncate">{s.bank_name}</div>
                    <div className="text-xs text-muted-foreground">{s.file_type.toUpperCase()} · {formatDate(s.created_at)}</div>
                    <div className="flex items-center gap-2 mt-1">
                      <Badge variant={s.status === 'reconciled' ? 'income' : 'outline'} className="text-xs">
                        {s.status}
                      </Badge>
                      {s.transaction_count !== undefined && (
                        <span className="text-xs text-muted-foreground">{s.transaction_count} txns</span>
                      )}
                    </div>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={(e) => { e.stopPropagation(); setDeleteTarget(s); }}
                  className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity text-muted-foreground hover:text-destructive"
                  title="Clear reconciliation"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            ))}
          </div>
        </div>

        {/* Right: Reconciliation view */}
        <div className="lg:col-span-2 space-y-4">
          {!selected ? (
            <div className="flex flex-col items-center justify-center h-64 rounded-lg border-2 border-dashed text-muted-foreground gap-2">
              <GitMerge className="h-8 w-8" />
              <p>Select or import a bank statement to start reconciling</p>
            </div>
          ) : (
            <>
              {/* Status bar */}
              {status && (
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                  {[
                    { label: 'Total',         value: status.total,         color: '' },
                    { label: 'Matched',        value: status.matched,       color: 'text-green-600' },
                    { label: 'Unmatched',      value: status.unmatched,     color: 'text-yellow-600' },
                    { label: 'Discrepancies',  value: status.discrepancies, color: 'text-red-600' },
                  ].map(({ label, value, color }) => (
                    <Card key={label}>
                      <CardContent className="py-3 px-4">
                        <p className="text-xs text-muted-foreground">{label}</p>
                        <p className={`text-xl font-bold ${color}`}>{value}</p>
                      </CardContent>
                    </Card>
                  ))}
                </div>
              )}

              {/* Save result banner */}
              {saveResult && saveResult.saved > 0 && (
                <div className="flex items-center gap-3 rounded-lg border border-green-200 bg-green-50 px-4 py-3">
                  <CheckCircle2 className="h-5 w-5 text-green-600 shrink-0" />
                  <p className="text-sm text-green-800 flex-1">
                    <strong>{saveResult.saved}</strong> transaction{saveResult.saved !== 1 ? 's' : ''} saved to your records.
                  </p>
                  <Button size="sm" variant="outline" onClick={() => navigate('/transactions')}>
                    View Transactions
                  </Button>
                </div>
              )}

              {/* Action toolbar */}
              <div className="flex items-center gap-2 flex-wrap">
                <Button onClick={handleAutoMatch} disabled={matching} size="sm" variant="outline">
                  <Zap className="h-4 w-4" />
                  {matching ? 'Matching…' : 'Auto-Match'}
                </Button>

                {/* Save unmatched — primary action */}
                {(status?.unmatched ?? 0) > 0 && (
                  <Button onClick={handleSaveUnmatched} disabled={saving} size="sm" className="gap-1.5">
                    <Save className="h-4 w-4" />
                    {saving ? 'Saving…' : `Save ${status!.unmatched} Unmatched as Transactions`}
                  </Button>
                )}

                <Button variant="outline" size="sm" onClick={() => handleExport('csv')}>Export CSV</Button>
                <Button variant="outline" size="sm" onClick={() => handleExport('pdf')}>Export PDF</Button>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {/* Bank transactions — unmatched first */}
                <div>
                  {/* Unmatched */}
                  <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">
                    Unmatched Bank Transactions ({unmatchedBankTxs.length})
                    {selectedBankTx && (
                      <span className="ml-2 text-primary normal-case font-normal">
                        — click a recorded transaction on the right to link
                      </span>
                    )}
                  </p>
                  <div className="space-y-1.5 max-h-[420px] overflow-y-auto pr-1">
                    {unmatchedBankTxs.length === 0 && (
                      <p className="text-sm text-muted-foreground py-4 text-center">
                        All transactions matched ✓
                      </p>
                    )}
                    {unmatchedBankTxs.map((btx) => <BankTxCard key={btx.id} btx={btx} />)}
                  </div>

                  {/* Matched — collapsible */}
                  {matchedBankTxs.length > 0 && (
                    <div className="mt-4">
                      <button
                        type="button"
                        onClick={() => setShowMatched((v) => !v)}
                        className="flex items-center gap-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground hover:text-foreground transition-colors mb-2 w-full text-left"
                      >
                        {showMatched ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
                        Matched ({matchedBankTxs.length})
                      </button>
                      {showMatched && (
                        <div className="space-y-1.5 max-h-[300px] overflow-y-auto pr-1">
                          {matchedBankTxs.map((btx) => <BankTxCard key={btx.id} btx={btx} />)}
                        </div>
                      )}
                    </div>
                  )}
                </div>

                {/* Recorded transactions */}
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">
                    Recorded Transactions
                    {selectedBankTx && (
                      <span className="ml-2 text-primary normal-case font-normal">(click to match)</span>
                    )}
                  </p>
                  <div className="space-y-1.5 max-h-[500px] overflow-y-auto pr-1">
                    {recordedTxs.length === 0 && (
                      <p className="text-sm text-muted-foreground py-4 text-center">
                        No recorded transactions yet.
                      </p>
                    )}
                    {recordedTxs.map((tx) => (
                      <div
                        key={tx.id}
                        onClick={() => selectedBankTx && handleManualMatch(tx.id)}
                        className={cn(
                          'rounded-lg border p-3 text-sm transition-colors',
                          selectedBankTx ? 'cursor-pointer hover:border-primary hover:bg-primary/5' : ''
                        )}
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span className="font-medium truncate max-w-[60%]">{tx.description}</span>
                          <span className={`font-semibold shrink-0 ${tx.type === 'income' ? 'text-green-600' : 'text-red-600'}`}>
                            {formatCurrency(tx.amount, tx.currency ?? 'NGN')}
                          </span>
                        </div>
                        <div className="text-xs text-muted-foreground mt-1">
                          {formatDate(tx.date)}
                          {tx.vendor && <span className="ml-1.5">· {tx.vendor}</span>}
                        </div>
                        {selectedBankTx && (
                          <Button
                            size="sm" variant="outline" className="mt-2 h-6 text-xs"
                            onClick={(e) => { e.stopPropagation(); handleManualMatch(tx.id); }}
                          >
                            <Link2 className="h-3 w-3 mr-1" /> Match
                          </Button>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
