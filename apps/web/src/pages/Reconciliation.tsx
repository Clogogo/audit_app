import { useEffect, useState } from 'react';
import { GitMerge, Zap, Link2, Unlink, AlertTriangle, CheckCircle2, Trash2 } from 'lucide-react';
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
} from '../api/client';
import type { BankStatement, BankTransaction, Transaction, ReconciliationStatus } from '../api/types';
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
  const [statements, setStatements] = useState<BankStatement[]>([]);
  const [selected, setSelected] = useState<BankStatement | null>(null);
  const [bankTxs, setBankTxs] = useState<BankTransaction[]>([]);
  const [recordedTxs, setRecordedTxs] = useState<Transaction[]>([]);
  const [status, setStatus] = useState<ReconciliationStatus | null>(null);
  const [bankName, setBankName] = useState('');
  const [uploading, setUploading] = useState(false);
  const [matching, setMatching] = useState(false);
  const [selectedBankTx, setSelectedBankTx] = useState<number | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<BankStatement | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [checkedIds, setCheckedIds] = useState<Set<number>>(new Set());
  const [batchDeleting, setBatchDeleting] = useState(false);
  const [showBatchConfirm, setShowBatchConfirm] = useState(false);

  useEffect(() => {
    getBankStatements().then(setStatements);
    getTransactions().then(setRecordedTxs);
  }, []);

  const loadStatement = async (stmt: BankStatement) => {
    setSelected(stmt);
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
      alert(`Auto-matched ${result.matched} transactions.`);
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

  const handleDeleteStatement = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await deleteBankStatement(deleteTarget.id);
      const updated = await getBankStatements();
      setStatements(updated);
      if (selected?.id === deleteTarget.id) {
        setSelected(null);
        setBankTxs([]);
        setStatus(null);
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
        setSelected(null);
        setBankTxs([]);
        setStatus(null);
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

  const matchStatusColor = (s: BankTransaction['match_status']) =>
    s === 'matched' ? 'text-green-600' : s === 'discrepancy' ? 'text-yellow-600' : 'text-muted-foreground';

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

      <div className="grid grid-cols-3 gap-6">
        {/* Left: Upload + statement list */}
        <div className="space-y-4">
          <Card>
            <CardHeader><CardTitle className="text-sm">Import Bank Statement</CardTitle></CardHeader>
            <CardContent className="space-y-3">
              <Input placeholder="Bank name (e.g. Chase)" value={bankName} onChange={(e) => setBankName(e.target.value)} />
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
        <div className="col-span-2 space-y-4">
          {!selected ? (
            <div className="flex flex-col items-center justify-center h-64 rounded-lg border-2 border-dashed text-muted-foreground gap-2">
              <GitMerge className="h-8 w-8" />
              <p>Select or import a bank statement to start reconciling</p>
            </div>
          ) : (
            <>
              {/* Status bar */}
              {status && (
                <div className="grid grid-cols-4 gap-3">
                  {[
                    { label: 'Total', value: status.total, icon: null },
                    { label: 'Matched', value: status.matched, icon: CheckCircle2, color: 'text-green-600' },
                    { label: 'Unmatched', value: status.unmatched, icon: AlertTriangle, color: 'text-yellow-600' },
                    { label: 'Discrepancies', value: status.discrepancies, icon: AlertTriangle, color: 'text-red-600' },
                  ].map(({ label, value, icon: Icon, color }) => (
                    <Card key={label}>
                      <CardContent className="py-3 px-4">
                        <p className="text-xs text-muted-foreground">{label}</p>
                        <p className={`text-xl font-bold ${color ?? ''}`}>{value}</p>
                      </CardContent>
                    </Card>
                  ))}
                </div>
              )}

              <div className="flex items-center gap-2">
                <Button onClick={handleAutoMatch} disabled={matching} size="sm">
                  <Zap className="h-4 w-4" /> {matching ? 'Matching...' : 'Auto-Match'}
                </Button>
                <Button variant="outline" size="sm" onClick={() => handleExport('csv')}>Export CSV</Button>
                <Button variant="outline" size="sm" onClick={() => handleExport('pdf')}>Export PDF</Button>
              </div>

              <div className="grid grid-cols-2 gap-4">
                {/* Bank transactions */}
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">
                    Bank Transactions ({bankTxs.length})
                  </p>
                  <div className="space-y-1.5 max-h-[500px] overflow-y-auto pr-1">
                    {bankTxs.map((btx) => (
                      <div
                        key={btx.id}
                        onClick={() => btx.match_status !== 'matched' && setSelectedBankTx(btx.id === selectedBankTx ? null : btx.id)}
                        className={cn(
                          'rounded-lg border p-3 text-sm cursor-pointer transition-colors',
                          btx.id === selectedBankTx ? 'border-primary bg-primary/5' : 'hover:bg-muted/30',
                          btx.match_status === 'matched' && 'opacity-60 cursor-default'
                        )}
                      >
                        <div className="flex items-center justify-between">
                          <span className="font-medium truncate max-w-[60%]">{btx.description}</span>
                          <span className={`font-semibold ${btx.transaction_type === 'credit' ? 'text-green-600' : 'text-red-600'}`}>
                            {formatCurrency(btx.amount)}
                          </span>
                        </div>
                        <div className="flex items-center justify-between mt-1">
                          <span className="text-xs text-muted-foreground">{formatDate(btx.date)}</span>
                          <span className={`text-xs ${matchStatusColor(btx.match_status)}`}>
                            {btx.match_status}
                            {btx.match_confidence && ` (${Math.round(btx.match_confidence * 100)}%)`}
                          </span>
                        </div>
                        {btx.match_status === 'matched' && (
                          <button
                            onClick={(e) => { e.stopPropagation(); handleUnmatch(btx.id); }}
                            className="flex items-center gap-1 text-xs text-muted-foreground hover:text-destructive mt-1"
                          >
                            <Unlink className="h-3 w-3" /> Unmatch
                          </button>
                        )}
                      </div>
                    ))}
                  </div>
                </div>

                {/* Recorded transactions */}
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">
                    Recorded Transactions
                    {selectedBankTx && <span className="ml-2 text-primary normal-case font-normal">(click to match)</span>}
                  </p>
                  <div className="space-y-1.5 max-h-[500px] overflow-y-auto pr-1">
                    {recordedTxs.map((tx) => (
                      <div
                        key={tx.id}
                        onClick={() => selectedBankTx && handleManualMatch(tx.id)}
                        className={cn(
                          'rounded-lg border p-3 text-sm transition-colors',
                          selectedBankTx ? 'cursor-pointer hover:border-primary hover:bg-primary/5' : ''
                        )}
                      >
                        <div className="flex items-center justify-between">
                          <span className="font-medium truncate max-w-[60%]">{tx.description}</span>
                          <span className={`font-semibold ${tx.type === 'income' ? 'text-green-600' : 'text-red-600'}`}>
                            {formatCurrency(tx.amount, tx.currency ?? 'NGN')}
                          </span>
                        </div>
                        <div className="text-xs text-muted-foreground mt-1">{tx.vendor} · {formatDate(tx.date)}</div>
                        {selectedBankTx && (
                          <Button size="sm" variant="outline" className="mt-2 h-6 text-xs" onClick={(e) => { e.stopPropagation(); handleManualMatch(tx.id); }}>
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
