import { useEffect, useState } from 'react';
import { Plus, Trash2, Building2, CreditCard } from 'lucide-react';
import { getBankAccounts, createBankAccount, deleteBankAccount } from '../api/client';
import type { BankAccount } from '../api/types';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { ConfirmDialog } from '../components/ConfirmDialog';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
  DialogFooter,
} from '../components/ui/dialog';
import { Card, CardContent } from '../components/ui/card';

export function Banks() {
  const [accounts, setAccounts] = useState<BankAccount[]>([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [bankName, setBankName] = useState('');
  const [accountNumber, setAccountNumber] = useState('');
  const [error, setError] = useState('');

  // Confirm delete
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<BankAccount | null>(null);
  const [deleting, setDeleting] = useState(false);

  const load = () => {
    setLoading(true);
    getBankAccounts()
      .then(setAccounts)
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  const handleAdd = async () => {
    if (!bankName.trim()) { setError('Bank name is required'); return; }
    setSaving(true);
    setError('');
    try {
      await createBankAccount({ bank_name: bankName.trim(), account_number: accountNumber.trim() || undefined });
      setBankName('');
      setAccountNumber('');
      setDialogOpen(false);
      load();
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg || 'Failed to save bank account');
    } finally {
      setSaving(false);
    }
  };

  const askDelete = (account: BankAccount) => {
    setDeleteTarget(account);
    setConfirmOpen(true);
  };

  const handleConfirmDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await deleteBankAccount(deleteTarget.id);
    } finally {
      setDeleting(false);
      setConfirmOpen(false);
      setDeleteTarget(null);
      load();
    }
  };

  return (
    <div className="space-y-6">
      <ConfirmDialog
        open={confirmOpen}
        title="Delete bank account?"
        description={`Remove "${deleteTarget?.bank_name}${deleteTarget?.account_number ? ` (${deleteTarget.account_number})` : ''}" from your saved accounts. This does not affect existing transactions.`}
        confirmLabel="Delete"
        loading={deleting}
        onConfirm={handleConfirmDelete}
        onCancel={() => setConfirmOpen(false)}
      />

      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Bank Accounts</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Saved accounts are available as a dropdown when importing statements or adding transactions.
          </p>
        </div>

        <Dialog open={dialogOpen} onOpenChange={(o) => { setDialogOpen(o); if (!o) { setBankName(''); setAccountNumber(''); setError(''); } }}>
          <DialogTrigger asChild>
            <Button>
              <Plus className="h-4 w-4" />
              Add Bank Account
            </Button>
          </DialogTrigger>
          <DialogContent className="max-w-sm">
            <DialogHeader>
              <DialogTitle>New Bank Account</DialogTitle>
            </DialogHeader>
            <div className="space-y-4 py-2">
              <div className="space-y-2">
                <Label>Bank Name <span className="text-destructive">*</span></Label>
                <Input
                  placeholder="e.g. Access Bank, GTBank, First Bank"
                  value={bankName}
                  onChange={(e) => setBankName(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleAdd()}
                />
              </div>
              <div className="space-y-2">
                <Label>Account Number <span className="text-muted-foreground text-xs">(optional)</span></Label>
                <Input
                  placeholder="e.g. 0123456789"
                  value={accountNumber}
                  onChange={(e) => setAccountNumber(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleAdd()}
                />
              </div>
              {error && <p className="text-sm text-destructive">{error}</p>}
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => setDialogOpen(false)}>Cancel</Button>
              <Button onClick={handleAdd} disabled={saving}>
                {saving ? 'Saving…' : 'Save Account'}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>

      {loading ? (
        <div className="text-center py-16 text-muted-foreground">Loading...</div>
      ) : accounts.length === 0 ? (
        <div className="text-center py-20 text-muted-foreground">
          <Building2 className="h-12 w-12 mx-auto mb-4 opacity-30" />
          <p className="font-medium">No bank accounts saved yet</p>
          <p className="text-sm mt-1">Add an account to use it as a quick-select when importing statements.</p>
        </div>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {accounts.map((acc) => (
            <Card key={acc.id} className="group">
              <CardContent className="flex items-center gap-4 py-4">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-primary/10">
                  <Building2 className="h-5 w-5 text-primary" />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="font-medium truncate">{acc.bank_name}</p>
                  {acc.account_number ? (
                    <p className="text-xs text-muted-foreground flex items-center gap-1 mt-0.5">
                      <CreditCard className="h-3 w-3" />
                      {acc.account_number}
                    </p>
                  ) : (
                    <p className="text-xs text-muted-foreground mt-0.5">No account number</p>
                  )}
                </div>
                <Button
                  variant="ghost"
                  size="icon"
                  className="opacity-0 group-hover:opacity-100 transition-opacity shrink-0"
                  onClick={() => askDelete(acc)}
                >
                  <Trash2 className="h-4 w-4 text-destructive" />
                </Button>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
