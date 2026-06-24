import { useEffect, useState } from 'react';
import { GitMerge, CheckCircle2, X, AlertTriangle, ScanLine } from 'lucide-react';
import {
  getPendingDuplicates,
  scanDuplicates,
  keepTransaction,
  markNotDuplicate,
  getDuplicateStats,
} from '../api/client';
import type { Transaction } from '../api/types';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { formatCurrency, formatDate } from '../lib/utils';
import { HelpTooltip } from '../components/HelpTooltip';

interface DuplicatePair {
  transaction: Transaction;
  duplicate: Transaction | null;
}

export function Reconciliation() {
  const [pairs, setPairs] = useState<DuplicatePair[]>([]);
  const [scanning, setScanning] = useState(false);
  const [resolving, setResolving] = useState(false);
  const [stats, setStats] = useState<{ total_duplicates: number; pending: number; reviewed: number } | null>(null);

  const loadDuplicates = async () => {
    const [dupes, statsData] = await Promise.all([
      getPendingDuplicates(),
      getDuplicateStats(),
    ]);
    setStats(statsData);

    // Group duplicates into pairs
    const grouped = new Map<number, DuplicatePair>();
    dupes.forEach((tx) => {
      if (tx.duplicate_of_id) {
        const duplicate = dupes.find((d) => d.id === tx.duplicate_of_id);
        if (!grouped.has(tx.id) && !grouped.has(tx.duplicate_of_id)) {
          grouped.set(tx.id, { transaction: tx, duplicate: duplicate || null });
        }
      }
    });
    setPairs(Array.from(grouped.values()));
  };

  useEffect(() => {
    loadDuplicates();
  }, []);

  const handleScan = async () => {
    setScanning(true);
    try {
      const result = await scanDuplicates();
      alert(`Scanned ${result.scanned} transactions, flagged ${result.flagged} duplicates.`);
      await loadDuplicates();
    } finally {
      setScanning(false);
    }
  };

  const handleKeep = async (txId: number) => {
    setResolving(true);
    try {
      await keepTransaction(txId);
      await loadDuplicates();
    } finally {
      setResolving(false);
    }
  };

  const handleMarkNotDuplicate = async (txId: number) => {
    setResolving(true);
    try {
      await markNotDuplicate(txId);
      await loadDuplicates();
    } finally {
      setResolving(false);
    }
  };

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-2">
            <GitMerge className="w-8 h-8" />
            Duplicate Resolution
            <HelpTooltip
              title="Duplicate Detection"
              content={"The system flags transactions that look like duplicates based on:\n· Same or very close amount\n· Same or adjacent date (±3 days)\n· Similar description text\n\nThis catches double-imports when you upload the same statement twice, or when a manual entry matches a bank import.\n\nFor each pair, choose which one to Keep — the other is deleted."}
              align="left"
            />
          </h1>
          <p className="text-muted-foreground mt-1">
            Duplicates are automatically detected when you create or upload transactions
          </p>
        </div>
        <Button onClick={handleScan} disabled={scanning} variant="outline" size="sm">
          <ScanLine className="w-4 h-4 mr-2" />
          {scanning ? 'Re-scanning...' : 'Re-scan All'}
        </Button>
      </div>

      {/* Stats */}
      {stats && (
        <div className="grid grid-cols-3 gap-4 mb-6">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-1.5">
                Pending Review
                <HelpTooltip
                  content={"Duplicate pairs you haven't decided on yet.\n\nFor each pair, click 'Keep This One' on the transaction you want to retain. The other will be removed from your ledger.\n\nIf neither is actually a duplicate, click 'Not a Duplicate' to dismiss."}
                  align="left"
                />
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-3xl font-bold">{stats.pending}</p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-1.5">
                Total Flagged
                <HelpTooltip
                  content={"Total transactions ever flagged as potential duplicates (all time).\n\nIncludes ones already resolved. Use 'Pending Review' to see what still needs action."}
                  align="center"
                />
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-3xl font-bold">{stats.total_duplicates}</p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-1.5">
                Reviewed
                <HelpTooltip
                  content={"Duplicate pairs you've already resolved — either by keeping one transaction or marking both as 'Not a Duplicate'.\n\nThese are removed from the Pending Review queue."}
                  align="right"
                />
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-3xl font-bold">{stats.reviewed}</p>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Empty State */}
      {pairs.length === 0 && !scanning && (
        <Card className="p-12 text-center">
          <CheckCircle2 className="w-16 h-16 mx-auto text-green-500 mb-4" />
          <h3 className="text-xl font-semibold mb-2">All Clear!</h3>
          <p className="text-muted-foreground mb-4">
            No duplicate transactions found. Click "Scan for Duplicates" to check for new ones.
          </p>
        </Card>
      )}

      {/* Duplicate Pairs */}
      <div className="space-y-6">
        {pairs.map((pair, idx) => (
          <Card key={pair.transaction.id} className="overflow-hidden">
            <CardHeader className="bg-yellow-50 border-b">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <AlertTriangle className="w-5 h-5 text-yellow-600" />
                  <CardTitle className="text-lg">
                    Potential Duplicate #{idx + 1}
                  </CardTitle>
                  {pair.transaction.duplicate_confidence && (
                    <div className="flex items-center gap-1.5">
                      <Badge variant="secondary">
                        {(pair.transaction.duplicate_confidence * 100).toFixed(0)}% confidence
                      </Badge>
                      <HelpTooltip
                        content={"Confidence score: how likely these two transactions are the same entry.\n\n· 90–100%: almost certainly a duplicate (same amount + date + description)\n· 70–89%: probably duplicate, worth reviewing\n· 50–69%: possible overlap, check carefully\n\nIf a score feels wrong, click 'Not a Duplicate' to remove the flag."}
                        align="left"
                      />
                    </div>
                  )}
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => handleMarkNotDuplicate(pair.transaction.id)}
                  disabled={resolving}
                >
                  <X className="w-4 h-4 mr-1" />
                  Not a Duplicate
                </Button>
              </div>
            </CardHeader>

            <CardContent className="p-0">
              <div className="grid grid-cols-2 divide-x">
                {/* Transaction 1 */}
                <div className="p-6 space-y-4">
                  <div className="flex items-center justify-between mb-4">
                    <h4 className="font-semibold text-lg">Transaction 1</h4>
                    <Button
                      onClick={() => handleKeep(pair.transaction.id)}
                      disabled={resolving}
                      variant="default"
                      size="sm"
                    >
                      <CheckCircle2 className="w-4 h-4 mr-1" />
                      Keep This One
                    </Button>
                  </div>

                  <div className="space-y-2 text-sm">
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Date:</span>
                      <span className="font-medium">{formatDate(pair.transaction.date)}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Amount:</span>
                      <span className="font-medium text-lg">
                        {formatCurrency(pair.transaction.amount, pair.transaction.currency)}
                      </span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Type:</span>
                      <Badge variant={pair.transaction.type === 'income' ? 'default' : 'secondary'}>
                        {pair.transaction.type}
                      </Badge>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Category:</span>
                      <span className="font-medium">{pair.transaction.category}</span>
                    </div>
                    <div className="space-y-1">
                      <span className="text-muted-foreground">Description:</span>
                      <p className="font-medium text-sm break-words">
                        {pair.transaction.description}
                      </p>
                    </div>
                    {pair.transaction.vendor && (
                      <div className="flex justify-between">
                        <span className="text-muted-foreground">Vendor:</span>
                        <span className="font-medium">{pair.transaction.vendor}</span>
                      </div>
                    )}
                    {pair.transaction.bank && (
                      <div className="flex justify-between">
                        <span className="text-muted-foreground">Bank:</span>
                        <span className="font-medium">{pair.transaction.bank}</span>
                      </div>
                    )}
                    <div className="flex justify-between pt-2 border-t">
                      <span className="text-muted-foreground text-xs">Created:</span>
                      <span className="text-xs">{formatDate(pair.transaction.created_at)}</span>
                    </div>
                  </div>
                </div>

                {/* Transaction 2 (Duplicate) */}
                {pair.duplicate ? (
                  <div className="p-6 space-y-4 bg-gray-50">
                    <div className="flex items-center justify-between mb-4">
                      <h4 className="font-semibold text-lg">Transaction 2</h4>
                      <Button
                        onClick={() => handleKeep(pair.duplicate!.id)}
                        disabled={resolving}
                        variant="default"
                        size="sm"
                      >
                        <CheckCircle2 className="w-4 h-4 mr-1" />
                        Keep This One
                      </Button>
                    </div>

                    <div className="space-y-2 text-sm">
                      <div className="flex justify-between">
                        <span className="text-muted-foreground">Date:</span>
                        <span className="font-medium">{formatDate(pair.duplicate.date)}</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-muted-foreground">Amount:</span>
                        <span className="font-medium text-lg">
                          {formatCurrency(pair.duplicate.amount, pair.duplicate.currency)}
                        </span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-muted-foreground">Type:</span>
                        <Badge variant={pair.duplicate.type === 'income' ? 'default' : 'secondary'}>
                          {pair.duplicate.type}
                        </Badge>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-muted-foreground">Category:</span>
                        <span className="font-medium">{pair.duplicate.category}</span>
                      </div>
                      <div className="space-y-1">
                        <span className="text-muted-foreground">Description:</span>
                        <p className="font-medium text-sm break-words">
                          {pair.duplicate.description}
                        </p>
                      </div>
                      {pair.duplicate.vendor && (
                        <div className="flex justify-between">
                          <span className="text-muted-foreground">Vendor:</span>
                          <span className="font-medium">{pair.duplicate.vendor}</span>
                        </div>
                      )}
                      {pair.duplicate.bank && (
                        <div className="flex justify-between">
                          <span className="text-muted-foreground">Bank:</span>
                          <span className="font-medium">{pair.duplicate.bank}</span>
                        </div>
                      )}
                      <div className="flex justify-between pt-2 border-t">
                        <span className="text-muted-foreground text-xs">Created:</span>
                        <span className="text-xs">{formatDate(pair.duplicate.created_at)}</span>
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="p-6 flex items-center justify-center text-muted-foreground">
                    <p>No matching transaction found</p>
                  </div>
                )}
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
